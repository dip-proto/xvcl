#!/usr/bin/env python3
"""
xvcl - Extended VCL compiler with metaprogramming features

Features:
- #inline directive for zero-overhead text substitution macros
- Token-aware macro expansion that preserves VCL strings and comments
- Macros work in any expression context (unlike functions)
- #include directive for code reuse across files
- #const directive for named constants
- Better error messages with line numbers and context
- --debug mode for tracing expansion
- Source maps (optional)
- For loops, conditionals, template expressions
- Functions with single/tuple returns
- #let directive for variable declaration
"""

import argparse
import json
import math
import os
import re
import sys
import textwrap
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from difflib import get_close_matches
from itertools import accumulate
from typing import Any, Optional


# ANSI color codes for terminal output
class Colors:
    RED = "\033[91m"
    YELLOW = "\033[93m"
    GREEN = "\033[92m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"
    GRAY = "\033[90m"


def _styled(text: str, *codes: str, enabled: bool) -> str:
    """Wrap text in ANSI codes when colors are enabled."""
    return "".join(codes) + text + Colors.RESET if enabled else text


@dataclass
class SourceLocation:
    """Tracks source location for error reporting."""

    file: str
    line: int

    def __str__(self):
        return f"{self.file}:{self.line}"


@dataclass
class Diagnostic:
    """Structured diagnostic with rule ID, severity, and actionable help."""

    rule: str
    severity: str  # "error" or "warning"
    message: str
    file: str = ""
    line: int = 0
    col_start: Optional[int] = None
    col_end: Optional[int] = None
    source_line: str = ""
    help: Optional[str] = None
    notes: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    included_from: list[tuple[str, int]] = field(default_factory=list)

    def format_text(self, use_colors: bool = True) -> str:
        """Format diagnostic in rustc-style text output."""
        parts = []

        # Header: error[rule]: message
        color = Colors.RED if self.severity == "error" else Colors.YELLOW
        parts.append(
            _styled(f"{self.severity}[{self.rule}]", color, Colors.BOLD, enabled=use_colors)
        )
        parts.append(_styled(f": {self.message}", Colors.BOLD, enabled=use_colors) + "\n")

        # Location: --> file:line
        if self.file:
            parts.append(f"  --> {self.file}:{self.line}\n")

        # Source line with caret
        if self.source_line:
            line_str = str(self.line)
            pad = " " * len(line_str)
            parts.append(f"   {pad}|\n")
            parts.append(f"   {line_str} | {self.source_line}\n")
            if self.col_start is not None and self.col_end is not None:
                caret_pad = " " * self.col_start
                caret_len = max(1, self.col_end - self.col_start)
                carets = "^" * caret_len
                parts.append(f"   {pad}| {caret_pad}{carets}\n")
            elif self.source_line.strip():
                # Point at the whole trimmed content
                leading = len(self.source_line) - len(self.source_line.lstrip())
                content_len = len(self.source_line.rstrip()) - leading
                if content_len > 0:
                    caret_pad = " " * leading
                    carets = "^" * content_len
                    parts.append(f"   {pad}| {caret_pad}{carets}\n")

        # Help
        if self.help:
            parts.append(f"   = help: {self.help}\n")

        # Notes
        for note in self.notes:
            parts.append(f"   = note: {note}\n")

        # Did-you-mean suggestions
        if self.suggestions:
            parts.append(f"   = did you mean: {', '.join(self.suggestions)}?\n")

        # Include chain
        for inc_file, inc_line in self.included_from:
            parts.append(f"   = note: included from {inc_file}:{inc_line}\n")

        return "".join(parts)

    def to_json(self) -> dict:
        """Convert diagnostic to a JSON-serializable dict."""
        d: dict[str, Any] = {
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
        }
        if self.file:
            d["file"] = self.file
            d["line"] = self.line
        if self.col_start is not None:
            d["column"] = self.col_start
        if self.source_line:
            d["source_line"] = self.source_line
        if self.help:
            d["help"] = self.help
        if self.notes:
            d["notes"] = self.notes
        if self.suggestions:
            d["suggestions"] = self.suggestions
        if self.included_from:
            d["included_from"] = [
                {"file": inc_file, "line": inc_line} for inc_file, inc_line in self.included_from
            ]
        return d


class PreprocessorError(Exception):
    """Base exception for preprocessor errors."""

    def __init__(
        self,
        message: str,
        location: Optional[SourceLocation] = None,
        context_lines: Optional[list[tuple[int, str]]] = None,
        diagnostic: Optional[Diagnostic] = None,
    ):
        self.message = message
        self.location = location
        self.context_lines = context_lines
        self.diagnostic = diagnostic
        super().__init__(message)

    def format_error(self, use_colors: bool = True) -> str:
        """Format error with context for display."""
        if self.diagnostic:
            return self.diagnostic.format_text(use_colors)

        # Legacy fallback for errors not yet converted to Diagnostic
        parts = []

        parts.append(_styled("Error", Colors.RED, Colors.BOLD, enabled=use_colors))

        if self.location:
            parts.append(f" at {self.location}:")
        else:
            parts.append(":")

        parts.append(f"\n  {self.message}\n")

        if self.context_lines and self.location:
            parts.append("\n  Context:\n")
            for line_num, line_text in self.context_lines:
                current = line_num == self.location.line
                prefix = "  → " if current else "    "
                text = f"{prefix}{line_num}: {line_text}"
                parts.append(_styled(text, Colors.BOLD, enabled=use_colors and current) + "\n")

        return "".join(parts)


def _python_string_end(text: str, start: int) -> int:
    """Return the end of the Python string literal that starts at start."""
    quote = text[start]
    delimiter = quote * 3 if text.startswith(quote * 3, start) else quote
    i = start + len(delimiter)
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            i += 2
        elif text.startswith(delimiter, i):
            return i + len(delimiter)
        else:
            i += 1
    return len(text)


def _find_template_expression_end(text: str, start: int) -> Optional[int]:
    """Find the }} that closes a template expression, ignoring Python strings and nested brackets."""
    delimiter_stack = []
    matching_open = {")": "(", "]": "[", "}": "{"}
    i = start
    while i < len(text):
        char = text[i]
        if char in "\"'":
            i = _python_string_end(text, i)
            continue
        if char in "([{":
            delimiter_stack.append(char)
        elif char in ")]}":
            if delimiter_stack and delimiter_stack[-1] == matching_open[char]:
                delimiter_stack.pop()
            elif char == "}" and not delimiter_stack and text.startswith("}}", i):
                return i
        i += 1
    return None


def _template_end(text: str, start: int) -> Optional[int]:
    """Return the end of the {{...}} template expression at start, if it is closed."""
    if not text.startswith("{{", start):
        return None
    end = _find_template_expression_end(text, start + 2)
    return None if end is None else end + 2


def _find_outside_templates(text: str, needle: str, start: int) -> int:
    """Like str.find, but skips template expressions, whose text is Python and not VCL."""
    while True:
        pos = text.find(needle, start)
        template = text.find("{{", start)
        if pos == -1 or template == -1 or pos < template:
            return pos
        end = _template_end(text, template)
        if end is None:
            return pos
        start = end


_SEGMENT_START = re.compile(r"[{/#\"']")
_LONG_STRING_OPEN = re.compile(r'\{([A-Za-z0-9_]*)"')
_NOT_NEWLINE = re.compile(r"[^\n]")
_QUOTE = re.compile(r"[\"']")
_VCL_TOKEN = re.compile(r"[\w.:-]+")


def _vcl_segments(text: str, let_is_code: bool = False) -> Iterator[tuple[str, int, int]]:
    """Yield (kind, start, end) for each template, string and comment in VCL text.

    kind is "template", "string" or "comment".
    VCL strings have no escapes, and a template inside a string belongs to that string.
    """
    i = 0
    while match := _SEGMENT_START.search(text, i):
        i = match.start()
        long_string = _LONG_STRING_OPEN.match(text, i)
        if (end := _template_end(text, i)) is not None:
            kind = "template"
        elif long_string:
            kind = "string"
            closing = f'"{long_string.group(1)}}}'
            end = _find_outside_templates(text, closing, long_string.end())
            end = len(text) if end == -1 else end + len(closing)
        elif text.startswith("/*", i):
            kind = "comment"
            end = text.find("*/", i + 2)
            end = len(text) if end == -1 else end + 2
        elif text.startswith("//", i) or (
            text[i] == "#" and not (let_is_code and text.startswith("#let ", i))
        ):
            kind = "comment"
            end = text.find("\n", i)
            end = len(text) if end == -1 else end
        elif text[i] == '"':
            kind = "string"
            end = _find_outside_templates(text, '"', i + 1)
            end = len(text) if end == -1 else end + 1
        elif text[i] == "'":
            # Single quotes only occur in Python, inside compile-time expressions.
            kind = "string"
            end = _python_string_end(text, i)
        else:
            i += 1
            continue
        yield kind, i, end
        i = end


def _blank(text: str, spans: Iterable[tuple[int, int]]) -> str:
    """Replace each (start, end) span with spaces, keeping newlines so offsets still line up."""
    parts = []
    cursor = 0
    for start, end in spans:
        parts.append(text[cursor:start])
        parts.append(_NOT_NEWLINE.sub(" ", text[start:end]))
        cursor = end
    if not parts:
        return text
    parts.append(text[cursor:])
    return "".join(parts)


def _mask_vcl_opaque(text: str) -> str:
    """Blank VCL strings and comments, and the Python strings inside templates.

    The rest of a template stays visible, since macros can be used there.
    """
    spans: list[tuple[int, int]] = []
    for kind, start, end in _vcl_segments(text):
        if kind != "template":
            spans.append((start, end))
            continue
        while quote := _QUOTE.search(text, start, end):
            start = min(end, _python_string_end(text, quote.start()))
            spans.append((quote.start(), start))
    return _blank(text, spans)


def _vcl_code_view(text: str) -> str:
    """Blank everything that isn't VCL code: strings, comments and templates."""
    return _blank(text, [(start, end) for _, start, end in _vcl_segments(text)])


def _strip_vcl_comments(text: str) -> str:
    """Replace each VCL comment with a space."""
    comments = [(start, end, " ") for kind, start, end in _vcl_segments(text) if kind == "comment"]
    return _apply_edits(text, comments)


def _continuation_lines(lines: list[str]) -> list[bool]:
    """Flag each line that starts inside a block comment, long string or template from an earlier line."""
    text = "\n".join(lines)
    starts = list(accumulate((len(line) + 1 for line in lines[:-1]), initial=0))
    flags = [False] * len(lines)
    for _, start, end in _vcl_segments(text):
        # Short strings can't span lines, and an unclosed one must not swallow the rest of the file.
        if text[start] in "{/":
            for index in range(bisect_right(starts, start), bisect_left(starts, end)):
                flags[index] = True
    return flags


def _vcl_token_spans(text: str) -> list[tuple[int, int]]:
    """Return (start, end) offsets of VCL tokens outside strings, comments and templates.

    #let lines count as code, since their initializer can use function parameters.
    """
    spans: list[tuple[int, int]] = []
    cursor = 0
    for _, start, end in _vcl_segments(text, let_is_code=True):
        spans.extend(token.span() for token in _VCL_TOKEN.finditer(text, cursor, start))
        cursor = end
    spans.extend(token.span() for token in _VCL_TOKEN.finditer(text, cursor))
    return spans


def _find_top_level(code: str, start: int, stops: str) -> Optional[int]:
    """Return the index of the first character of stops at parenthesis depth 0, in masked code."""
    depth = 0
    for pos in range(start, len(code)):
        char = code[pos]
        if char in stops and depth == 0:
            return pos
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
    return None


def _split_like(text: str, entries: list[str]) -> list[str]:
    """Cut text, which has the same newlines as "\\n".join(entries), back into one piece per entry."""
    lines = text.split("\n")
    pieces = []
    pos = 0
    for entry in entries:
        count = entry.count("\n") + 1
        pieces.append("\n".join(lines[pos : pos + count]))
        pos += count
    return pieces


def _apply_edits(text: str, edits: list[tuple[int, int, str]]) -> str:
    """Replace non-overlapping (start, end, replacement) spans of text."""
    result = []
    cursor = 0
    for start, end, replacement in sorted(edits):
        result.append(text[cursor:start])
        result.append(replacement)
        cursor = end
    result.append(text[cursor:])
    return "".join(result)


def _replace_vcl_identifiers(text: str, replacements: dict[str, str]) -> str:
    """Replace bare VCL identifiers, all in one pass, without touching strings, comments or variables."""
    edits = [
        (start, end, replacements[text[start:end]])
        for start, end in _vcl_token_spans(text)
        if text[start:end] in replacements
    ]
    return _apply_edits(text, edits)


def _format_template_value(value: Any, in_string: bool) -> str:
    """Render a compile-time value as VCL source text."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and math.isfinite(value) and not in_string:
        # Falco rejects FLOAT literals like 5e-05, and the point keeps the literal a FLOAT.
        text = repr(value)
        if "e" in text:
            text = format(Decimal(text), "f")
            if "." not in text:
                text += ".0"
        return text
    return str(value)


class Macro:
    """Represents an inline macro definition."""

    def __init__(
        self, name: str, params: list[str], body: str, location: Optional[SourceLocation] = None
    ):
        self.name = name
        self.params = params  # [param_name, ...]
        self.body = body  # Single expression (string)
        self.location = location
        self._param_pattern = (
            re.compile(r"\b(?:" + "|".join(map(re.escape, params)) + r")\b") if params else None
        )

    def expand(self, args: list[str]) -> str:
        """Expand macro by substituting parameters with arguments."""
        if len(args) != len(self.params):
            raise ValueError(
                f"Macro {self.name} expects {len(self.params)} arguments, got {len(args)}"
            )
        if self._param_pattern is None:
            return self.body

        substitutions = dict(zip(self.params, args))
        param_pattern = self._param_pattern

        # {{param}} placeholders are Python and also work inside VCL strings, while other parameters are VCL tokens.
        # All replacements are found in the original body and applied together, so an argument is never rewritten again.
        edits = []
        start = self.body.find("{{")
        while start != -1 and (end := _template_end(self.body, start)) is not None:
            expression = self.body[start + 2 : end - 2]
            replaced = param_pattern.sub(lambda m: substitutions[m.group(0)], expression)
            edits.append((start + 2, end - 2, replaced))
            start = self.body.find("{{", end)
        for start, end in _vcl_token_spans(self.body):
            if self.body[start:end] in substitutions:
                edits.append((start, end, substitutions[self.body[start:end]]))

        # Expansion is textual on purpose: VCL only allows grouping in boolean expressions, so adding parentheses could break valid STRING VCL.
        return _apply_edits(self.body, edits)


class Function:
    """Represents a VCL function definition."""

    def __init__(
        self,
        name: str,
        params: list[tuple[str, str]],
        return_type,
        body: list[str],
        location: SourceLocation,
        body_provenance: list["_LineProv"],
    ):
        self.name = name
        self.params = params  # [(param_name, param_type), ...]
        self.return_type = return_type  # str for single return, List[str] for tuple
        self.body = body
        self.location = location
        self.body_provenance = body_provenance  # one entry per body line, or empty

    def get_param_global(self, param_name: str) -> str:
        """Get the global header name for a parameter."""
        return f"req.http.X-Func-{self.name}-{param_name}"

    def get_return_global(self, index: Optional[int] = None) -> str:
        """Get the global header name for the return value."""
        if isinstance(self.return_type, list):
            # Tuple return - use indexed global
            if index is None:
                raise ValueError(f"Function {self.name} returns tuple, index required")
            return f"req.http.X-Func-{self.name}-Return{index}"
        else:
            # Single return
            return f"req.http.X-Func-{self.name}-Return"

    def is_tuple_return(self) -> bool:
        """Check if function returns a tuple."""
        return isinstance(self.return_type, list)

    def get_return_types(self) -> list[str]:
        """Get return types as a list (single type becomes 1-element list)."""
        if isinstance(self.return_type, list):
            return self.return_type
        else:
            return [self.return_type]


_EMPTY_INC_CHAIN: list[tuple[str, int]] = []


@dataclass
class _LineProv:
    """Provenance for a single logical line after pass transformations."""

    file: str  # Origin file
    line: int  # Origin line number (first physical line if merged)
    source_text: str  # The original source text at origin
    included_from: list[tuple[str, int]] = field(default_factory=list)
    # For merged lines: range of physical lines (first, last) inclusive
    line_end: Optional[int] = None  # None means single line

    @staticmethod
    def single(
        file: str, line: int, text: str, included_from: Optional[list] = None
    ) -> "_LineProv":
        return _LineProv(
            file, line, text, included_from if included_from is not None else _EMPTY_INC_CHAIN
        )

    @staticmethod
    def merged(
        file: str, first_line: int, last_line: int, text: str, included_from: Optional[list] = None
    ) -> "_LineProv":
        return _LineProv(
            file,
            first_line,
            text,
            included_from if included_from is not None else _EMPTY_INC_CHAIN,
            last_line,
        )


class XVCLCompiler:
    """Extended VCL compiler with loops, conditionals, templates, functions, includes, and constants."""

    def __init__(
        self,
        include_paths: Optional[list[str]] = None,
        debug: bool = False,
        source_maps: bool = False,
    ):
        self.include_paths = include_paths or ["."]
        self.debug = debug
        self.source_maps = source_maps

        # State
        self.variables: dict[str, Any] = {}
        self.constants: dict[str, Any] = {}  # Constants defined with #const
        self.macros: dict[str, Macro] = {}  # NEW in v2.4: Inline macros
        self.functions: dict[str, Function] = {}
        self.output: list[str] = []
        self.diagnostics: list[Diagnostic] = []  # Collected diagnostics
        # (namespace, VCL name) -> (file, line).
        # Each kind of declaration has its own namespace, but a director can also be used as a backend.
        self._declared_names: dict[tuple[str, str], tuple[str, int]] = {}
        self._used_constants: set[str] = set()
        self._used_macros: set[str] = set()
        self._used_functions: set[str] = set()
        self._const_locations: dict[str, tuple[str, int]] = {}  # const name -> (file, line)

        # Include tracking
        self.included_files: set[str] = set()  # Absolute paths of included files
        self.include_stack: list[str] = []  # Stack for cycle detection
        self._conditional_includes: set[str] = set()  # Files first included under an #if
        self._includes_with_output: set[str] = set()

        # Current source location for error reporting
        self.current_file: str = ""
        self.current_line: int = 0
        self.current_lines: list[str] = []  # All lines for context

        # Per-line provenance: maps line index -> LineProvenance
        self._line_provenance: list[_LineProv] = []

        # The #def whose body is being compiled, if any
        self._current_function: Optional[Function] = None

    def log_debug(self, message: str, indent: int = 0):
        """Log debug message if debug mode is enabled."""
        if self.debug:
            prefix = "  " * indent
            print(
                f"{_styled('[DEBUG]', Colors.GRAY, enabled=sys.stdout.isatty())} {prefix}{message}"
            )

    def get_context_lines(self, line_num: int, context: int = 3) -> list[tuple[int, str]]:
        """Get context lines around the given line number."""
        if not self.current_lines:
            return []

        start = max(0, line_num - context - 1)
        end = min(len(self.current_lines), line_num + context)

        result = []
        for i in range(start, end):
            result.append((i + 1, self.current_lines[i].rstrip()))

        return result

    def _start_provenance_pass(self, lines: list[str]) -> tuple[list[_LineProv], bool]:
        """Begin a pass that may change line count. Returns (new_provenance, has_provenance)."""
        has_provenance = len(self._line_provenance) == len(lines)
        return [], has_provenance

    def _keep_line_provenance(
        self, new_provenance: list[_LineProv], has_provenance: bool, idx: int
    ) -> None:
        """Copy provenance for a kept line."""
        if has_provenance:
            new_provenance.append(self._line_provenance[idx])

    def _finish_provenance_pass(
        self, new_provenance: list[_LineProv], has_provenance: bool
    ) -> None:
        """Commit updated provenance after a pass."""
        if has_provenance:
            self._line_provenance = new_provenance

    def _merged_provenance(self, first_idx: int, last_idx: int) -> _LineProv:
        """Create a merged provenance entry spanning first_idx..last_idx (0-based)."""
        first = self._line_provenance[first_idx]
        last = self._line_provenance[last_idx] if last_idx < len(self._line_provenance) else first
        return _LineProv.merged(
            first.file, first.line, last.line, first.source_text, first.included_from
        )

    def _raise_if_errors(self) -> None:
        """Raise PreprocessorError if any error-severity diagnostics have been collected."""
        for d in self.diagnostics:
            if d.severity == "error":
                raise PreprocessorError(
                    d.message,
                    SourceLocation(d.file, d.line),
                    diagnostic=d,
                )

    def _resolve_provenance(self, line_idx: int) -> "_LineProv":
        """Look up provenance for a 1-based line index."""
        idx = line_idx - 1
        if 0 <= idx < len(self._line_provenance):
            return self._line_provenance[idx]
        # Fallback: construct from current state
        source_text = ""
        if self.current_lines and 0 < line_idx <= len(self.current_lines):
            source_text = self.current_lines[line_idx - 1].rstrip()
        return _LineProv.single(self.current_file, line_idx, source_text)

    def make_error(
        self,
        message: str,
        line_num: Optional[int] = None,
        *,
        rule: str = "compile-error",
        help: Optional[str] = None,
        notes: Optional[list[str]] = None,
        suggestions: Optional[list[str]] = None,
        severity: str = "error",
    ) -> PreprocessorError:
        """Create a PreprocessorError with a structured Diagnostic.

        line_num is a 1-based index into the current provenance table, not a source line number.
        """
        # Resolve provenance to get the real origin file/line/source text
        prov = self._resolve_provenance(line_num or self.current_line)

        loc = SourceLocation(prov.file, prov.line)

        # Use source text from provenance (correct even for included files)
        source_line = prov.source_text

        all_notes = [n for n in (notes or []) if n]

        # For merged lines, note the physical line range
        if prov.line_end is not None and prov.line_end > prov.line:
            all_notes.append(f"spans lines {prov.line}-{prov.line_end} (joined into one)")

        diag = Diagnostic(
            rule=rule,
            severity=severity,
            message=message,
            file=prov.file,
            line=prov.line,
            source_line=source_line,
            help=help,
            notes=all_notes,
            suggestions=suggestions or [],
            included_from=prov.included_from,
        )
        return PreprocessorError(message, loc, diagnostic=diag)

    def process_file(self, input_path: str, output_path: str) -> None:
        """Process a VCL template file and write the result."""
        self.log_debug(f"Processing file: {input_path}")

        try:
            with open(input_path) as f:
                template = f.read()
        except FileNotFoundError:
            raise FileNotFoundError(f"XVCL file not found: {input_path}")
        except Exception as e:
            raise Exception(f"Error reading file {input_path}: {e}")

        self.current_file = input_path
        result = self.process(template, input_path)

        try:
            with open(output_path, "w") as f:
                f.write(result)
        except Exception as e:
            raise Exception(f"Error writing output file {output_path}: {e}")

        # Summary
        print(
            f"{_styled('✓', Colors.GREEN, enabled=sys.stdout.isatty())} Compiled {input_path} -> {output_path}"
        )
        if self.constants:
            print(f"  Constants: {len(self.constants)}")
        if self.macros:
            print(f"  Macros: {len(self.macros)} ({', '.join(self.macros.keys())})")
        if self.functions:
            print(f"  Functions: {len(self.functions)} ({', '.join(self.functions.keys())})")
        if len(self.included_files) > 1:  # More than just the main file
            print(f"  Included files: {len(self.included_files) - 1}")

    def process(self, template: str, filename: str = "<string>") -> str:
        """Process a template string and return the result."""
        self.log_debug(f"Starting processing of {filename}")

        self.output = []
        self.current_file = filename
        self.current_lines = template.split("\n")

        # Add to included files (using absolute path)
        abs_path = os.path.realpath(filename) if os.path.exists(filename) else filename
        self.included_files.add(abs_path)
        self.include_stack = [abs_path] if os.path.exists(filename) else []

        lines = self.current_lines

        # Initialize provenance: each line maps to its origin
        self._line_provenance = [
            _LineProv.single(filename, i + 1, lines[i].rstrip()) for i in range(len(lines))
        ]

        # Pass 0: join multi-line directives (arrays/expressions across lines)
        self.log_debug("Pass 0: Joining multi-line directives")
        lines = self._join_multiline_directives(lines)

        # Passes 1 and 2 run together, in order, so a constant can use constants from files included before it.
        self.log_debug("Passes 1-2: Extracting constants and processing includes")
        lines = self._process_includes(lines, filename)
        self._raise_if_errors()

        # Third pass: extract inline macros (NEW in v2.4)
        self.log_debug("Pass 3: Extracting inline macros")
        lines = self._extract_macros(lines)

        # Fourth pass: extract function definitions
        self.log_debug("Pass 4: Extracting functions")
        lines = self._extract_functions(lines)

        # NEW: Fourth-and-a-half pass: join multi-line function calls
        self.log_debug("Pass 4.5: Joining multi-line function calls")
        lines = self._join_multiline_function_calls(lines)

        # Fifth pass: process loops/conditionals and replace function calls/macros
        self.log_debug("Pass 5: Processing directives and generating code")
        self._process_lines(lines, 0, len(lines), {})

        # Sixth pass: append function subroutine implementations
        self.log_debug("Pass 6: Generating function subroutines")
        self._generate_function_subroutines()

        # Check for unused definitions
        self._check_unused_definitions()

        # Final check for any error-severity diagnostics collected during compilation
        self._raise_if_errors()

        self.log_debug(f"Processing complete: {len(self.output)} lines generated")
        return "\n".join(self.output)

    def _extract_single_constant(self, stripped: str) -> None:
        """Parse and register a single #const declaration. Raises PreprocessorError on failure."""
        # Parse: #const NAME TYPE = value
        match = re.match(r"#const\s+(\w+)\s+(\w+)\s*=\s*(.+)", stripped, flags=re.DOTALL)
        if not match:
            # Try without type: #const NAME = value (infer type)
            match = re.match(r"#const\s+(\w+)\s*=\s*(.+)", stripped, flags=re.DOTALL)
            if not match:
                raise self.make_error(
                    f"Invalid #const syntax: {stripped}",
                    rule="invalid-const",
                    help="expected '#const NAME = value' or '#const NAME TYPE = value'",
                    notes=["example: #const PORT INTEGER = 8080"],
                )

            name = match.group(1)
            const_type = None
            value_expr = match.group(2)
        else:
            name = match.group(1)
            const_type = match.group(2)
            value_expr = match.group(3)

        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise self.make_error(
                f"Invalid constant name '{name}'",
                rule="invalid-const-name",
                help="constant names must start with a letter or underscore",
            )

        # Evaluate the expression
        try:
            value = self._evaluate_expression(value_expr, {})
        except Exception as e:
            raise self.make_error(
                f"Error evaluating constant '{name}': {e}",
                rule="const-eval-error",
                help=f"check that the expression '{value_expr}' is valid",
            )

        # Type checking if type was specified
        if const_type:
            self._validate_vcl_type(const_type, f"constant '{name}'")
            if const_type not in self._CONST_TYPES:
                raise self.make_error(
                    f"Type '{const_type}' is not supported for constants",
                    rule="unsupported-const-type",
                    help=f"supported #const types: {', '.join(sorted(self._CONST_TYPES))}",
                )
            expected_type = self._python_type_from_vcl(const_type)
            if type(value) is not expected_type:
                raise self.make_error(
                    f"Constant '{name}' type mismatch: expected {const_type}, "
                    f"got {type(value).__name__}",
                    rule="const-type-mismatch",
                    help=f"value evaluates to {type(value).__name__}, but {const_type} was declared",
                )

        # Check for duplicate constants
        if name in self.constants:
            prev_file, prev_line = self._const_locations[name]
            raise self.make_error(
                f"Constant '{name}' is already defined",
                rule="const-redefined",
                notes=[
                    f"previously defined as {self.constants[name]!r} at {prev_file}:{prev_line}"
                ],
                help="rename this constant or remove the duplicate",
            )

        prov = self._resolve_provenance(self.current_line)
        self._const_locations[name] = (prov.file, prov.line)
        self.constants[name] = value
        self.log_debug(f"Defined constant: {name} = {value}")

    # All valid VCL types recognized by Falco
    _VALID_VCL_TYPES = frozenset(
        {
            "STRING",
            "INTEGER",
            "FLOAT",
            "BOOL",
            "RTIME",
            "TIME",
            "BACKEND",
            "IP",
            "ACL",
            "REGEX",
        }
    )

    # A function becomes "sub NAME", so NAME has to be a valid name for both Falco and Fastly.
    # Falco reads these words as keywords.
    _FALCO_KEYWORDS = frozenset(
        {
            "acl",
            "add",
            "backend",
            "break",
            "call",
            "case",
            "declare",
            "default",
            "director",
            "else",
            "elseif",
            "elsif",
            "error",
            "esi",
            "fallthrough",
            "false",
            "goto",
            "if",
            "import",
            "include",
            "log",
            "penaltybox",
            "pragma",
            "ratecounter",
            "remove",
            "restart",
            "return",
            "set",
            "sub",
            "switch",
            "synthetic",
            "table",
            "true",
            "unset",
        }
    )

    # Fastly refuses these as names: statements, return actions, and builtin functions without a namespace.
    _FASTLY_RESERVED_NAMES = frozenset(
        {
            "add",
            "break",
            "call",
            "case",
            "client",
            "cstr_escape",
            "declare",
            "deliver",
            "deliver_stale",
            "early_hints",
            "else",
            "elseif",
            "elsif",
            "esi",
            "fallthrough",
            "false",
            "fetch",
            "for",
            "foreach",
            "goto",
            "hit_for_pass",
            "http_status_matches",
            "if",
            "import",
            "lookup",
            "now",
            "parse_time_delta",
            "penaltybox",
            "pipe",
            "pragma",
            "randombool",
            "randombool_seeded",
            "randomint",
            "randomint_seeded",
            "randomstr",
            "ratecounter",
            "regsub",
            "regsuball",
            "remove",
            "return",
            "set",
            "strftime",
            "sub",
            "subfield",
            "substr",
            "switch",
            "table",
            "true",
            "unset",
            "upgrade",
            "urldecode",
            "urlencode",
            "vcl",
            "xml_escape",
        }
    )

    _RESERVED_FUNCTION_NAMES = _FALCO_KEYWORDS | _FASTLY_RESERVED_NAMES

    # Types that can go through the STRING headers used to pass arguments and results.
    # FLOAT isn't one of them, since VCL rounds it to three decimals when it becomes a string.
    _BRIDGE_TYPES = frozenset({"STRING", "INTEGER", "BOOL"})
    _CONST_TYPES = frozenset({"STRING", "INTEGER", "FLOAT", "BOOL"})

    def _validate_vcl_type(self, type_name: str, context: str) -> None:
        """Validate that a type name is a valid VCL type.

        Raises PreprocessorError for invalid or unsupported types.
        context is a description like "parameter 'x' of function 'add'" for error messages.
        """
        if type_name not in self._VALID_VCL_TYPES:
            suggestions = get_close_matches(type_name, self._VALID_VCL_TYPES, n=3, cutoff=0.5)
            raise self.make_error(
                f"'{type_name}' is not a valid VCL type",
                rule="invalid-vcl-type",
                help=f"valid types: {', '.join(sorted(self._VALID_VCL_TYPES))}",
                suggestions=suggestions,
                notes=[f"in {context}"],
            )

    def _validate_bridge_type(self, type_name: str, context: str) -> None:
        """Validate that a type is supported by xvcl's function bridge.

        Types like RTIME, IP, etc. are valid VCL but produce broken conversion
        code when used in #def parameters or return types.
        """
        if type_name in self._VALID_VCL_TYPES and type_name not in self._BRIDGE_TYPES:
            raise self.make_error(
                f"Type '{type_name}' is not supported in xvcl function parameters/returns",
                rule="unsupported-bridge-type",
                help="use STRING and convert manually, or use an #inline macro instead",
                notes=[
                    f"in {context}",
                    "xvcl function parameter passing converts through STRING headers",
                    "a FLOAT would be rounded to three decimals on the way"
                    if type_name == "FLOAT"
                    else "",
                    f"supported types for #def: {', '.join(sorted(self._BRIDGE_TYPES))}",
                ],
            )

    def _python_type_from_vcl(self, vcl_type: str) -> type:
        """Convert VCL type name to Python type for validation."""
        type_map = {
            "INTEGER": int,
            "STRING": str,
            "FLOAT": float,
            "BOOL": bool,
        }
        return type_map.get(vcl_type, object)

    def _process_includes(
        self,
        lines: list[str],
        current_file: str,
        include_chain: Optional[list[tuple[str, int]]] = None,
        conditional: bool = False,
    ) -> list[str]:
        """
        Process #include directives and insert included file contents, and
        extract #const declarations along the way, in source order.
        Returns the remaining lines.
        Also updates self._line_provenance.
        """
        if include_chain is None:
            include_chain = []

        result = []
        result_provenance: list[_LineProv] = []
        if_depth = 0
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            self.current_line = i + 1
            directive = self._directive(line)
            if directive == "#if":
                if_depth += 1
            elif directive == "#endif":
                if_depth -= 1
            in_conditional = conditional or if_depth > 0

            if directive == "#const":
                # Errors are collected so that every bad constant gets reported.
                try:
                    self._extract_single_constant(stripped)
                except PreprocessorError as e:
                    if e.diagnostic:
                        self.diagnostics.append(e.diagnostic)
                    else:
                        raise
                i += 1
                continue

            if directive == "#include":
                # Parse: #include "path/to/file.xvcl"
                match = re.match(r'#include\s+["\'](.+?)["\']', stripped)
                if not match:
                    # Try without quotes: #include <stdlib/file.xvcl>
                    match = re.match(r"#include\s+<(.+?)>", stripped)

                if not match:
                    raise self.make_error(
                        f"Invalid #include syntax: {stripped}",
                        rule="invalid-include",
                        help="expected '#include \"path/to/file.xvcl\"' or '#include <path>'",
                    )

                include_path = match.group(1)

                # Resolve include path
                resolved_path = self._resolve_include_path(include_path, current_file)

                if not resolved_path:
                    search_dirs = [
                        os.path.dirname(os.path.abspath(current_file))
                    ] + self.include_paths
                    raise self.make_error(
                        f"Cannot find included file: {include_path}",
                        rule="include-not-found",
                        help=f"searched in: {', '.join(search_dirs)}",
                    )

                abs_path = os.path.abspath(resolved_path)

                # Check for cycles
                if abs_path in self.include_stack:
                    cycle = " -> ".join(self.include_stack + [abs_path])
                    raise self.make_error(
                        f"Circular include detected: {cycle}",
                        rule="circular-include",
                        help="restructure includes to avoid the cycle",
                    )

                # Include-once runs before #if, so if the first copy sits in a branch that isn't taken, skipping this one would lose its VCL.
                if abs_path in self.included_files:
                    if abs_path in self._includes_with_output & self._conditional_includes:
                        raise self.make_error(
                            f"'{include_path}' is included again, but it was first included inside a conditional block",
                            rule="conditional-reinclude",
                            help="include it once, outside of #if blocks",
                            notes=["each file is included only once, before #if is evaluated"],
                        )
                    self.log_debug(f"Skipping already included file: {resolved_path}")
                    i += 1
                    continue

                self.log_debug(f"Including file: {resolved_path}")

                # Read and process included file
                try:
                    with open(resolved_path) as f:
                        included_content = f.read()
                except Exception as e:
                    raise self.make_error(
                        f"Error reading included file {resolved_path}: {e}",
                        rule="include-read-error",
                    )

                # Add to included files and stack
                self.included_files.add(abs_path)
                self.include_stack.append(abs_path)

                # Save current state
                saved_file = self.current_file
                saved_line = self.current_line
                saved_lines = self.current_lines
                saved_provenance = self._line_provenance

                # Build include chain for provenance
                child_chain = include_chain + [(current_file, self._resolve_provenance(i + 1).line)]

                # Process included file
                self.current_file = resolved_path
                self.current_lines = included_content.split("\n")

                # Initialize provenance for included file lines
                self._line_provenance = [
                    _LineProv.single(
                        resolved_path, j + 1, self.current_lines[j].rstrip(), child_chain
                    )
                    for j in range(len(self.current_lines))
                ]

                # Recursively process includes in the included file
                included_lines = self._join_multiline_directives(self.current_lines)
                included_lines = self._process_includes(
                    included_lines, resolved_path, child_chain, in_conditional
                )
                if self._has_vcl_output(included_lines):
                    self._includes_with_output.add(abs_path)
                if in_conditional:
                    self._conditional_includes.add(abs_path)

                # Capture the included file's provenance before restoring state
                included_provenance = list(self._line_provenance)

                # Restore state
                self.current_file = saved_file
                self.current_line = saved_line
                self.current_lines = saved_lines
                self._line_provenance = saved_provenance

                # Pop from stack
                self.include_stack.pop()

                if self.source_maps:
                    result.append(f"// BEGIN INCLUDE: {include_path}")
                    result_provenance.append(
                        _LineProv.single(
                            resolved_path, 0, f"// BEGIN INCLUDE: {include_path}", child_chain
                        )
                    )

                # Add included lines with their own provenance
                for j, inc_line in enumerate(included_lines):
                    result.append(inc_line)
                    if j < len(included_provenance):
                        result_provenance.append(included_provenance[j])
                    else:
                        result_provenance.append(
                            _LineProv.single(resolved_path, j + 1, inc_line.rstrip(), child_chain)
                        )

                if self.source_maps:
                    result.append(f"// END INCLUDE: {include_path}")
                    result_provenance.append(
                        _LineProv.single(
                            resolved_path, 0, f"// END INCLUDE: {include_path}", child_chain
                        )
                    )

                i += 1
            else:
                result.append(line)
                if i < len(self._line_provenance):
                    result_provenance.append(self._line_provenance[i])
                else:
                    result_provenance.append(
                        _LineProv.single(current_file, i + 1, line.rstrip(), include_chain)
                    )
                i += 1

        # Update the compiler-wide provenance
        self._line_provenance = result_provenance
        return result

    def _has_vcl_output(self, lines: list[str]) -> bool:
        """Return whether lines produce VCL, beyond definitions, directives and comments."""
        block_end = None
        for line in lines:
            directive = self._directive(line)
            if block_end:
                if directive == block_end:
                    block_end = None
            elif directive == "#inline":
                block_end = "#endinline"
            elif directive == "#def":
                block_end = "#enddef"
            elif directive == "#let" or _vcl_code_view(line).strip():
                return True
        return False

    def _resolve_include_path(self, include_path: str, current_file: str) -> Optional[str]:
        """Resolve include path by searching include paths."""

        def resolve_from_root(root: str) -> Optional[str]:
            root = os.path.realpath(root)
            candidate = os.path.realpath(os.path.join(root, include_path))
            if os.path.commonpath([root, candidate]) != root:
                return None
            if os.path.exists(candidate):
                return candidate
            return None

        # Try relative to current file first
        if current_file and current_file != "<string>":
            current_dir = os.path.dirname(os.path.abspath(current_file))
            candidate = resolve_from_root(current_dir)
            if candidate:
                return candidate

        # Try include paths
        for search_path in self.include_paths:
            candidate = resolve_from_root(search_path)
            if candidate:
                return candidate

        return None

    def _extract_macros(self, lines: list[str]) -> list[str]:
        """
        Extract #inline...#endinline blocks and store them as macros.
        Returns lines with macro definitions removed.
        """
        result = []
        new_prov, has_prov = self._start_provenance_pass(lines)
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            self.current_line = i + 1

            if self._directive(line) == "#inline":
                # Parse: #inline name(param1, param2, ...)
                match = re.match(r"#inline\s+(\w+)\s*\(([^)]*)\)", stripped)
                if not match:
                    raise self.make_error(
                        f"Invalid #inline syntax: {stripped}",
                        rule="invalid-inline",
                        help="expected '#inline name(param1, param2, ...)'",
                        notes=["the macro body goes on the next line(s), closed with #endinline"],
                    )

                name = match.group(1)
                params_str = match.group(2).strip()

                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                    raise self.make_error(
                        f"Invalid macro name '{name}'",
                        rule="invalid-macro-name",
                        help="macro names must start with a letter or underscore",
                    )

                # Check for duplicate macro names
                if name in self.macros:
                    raise self.make_error(
                        f"Macro '{name}' is already defined",
                        rule="duplicate-macro",
                        notes=[f"previously defined at {self.macros[name].location}"],
                        help="rename this macro or remove the duplicate",
                    )

                # Parse parameters (comma-separated)
                params = []
                if params_str:
                    params = [p.strip() for p in params_str.split(",")]

                seen_params = set()
                for param in params:
                    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", param):
                        raise self.make_error(
                            f"Invalid parameter name '{param}' in macro '{name}'",
                            rule="invalid-macro-param",
                            help="parameter names must be VCL identifiers",
                        )
                    if param in seen_params:
                        raise self.make_error(
                            f"Macro '{name}' has duplicate parameter '{param}'",
                            rule="duplicate-macro-param",
                            help="give every macro parameter a unique name",
                        )
                    seen_params.add(param)

                # Find matching #endinline
                endinline_idx = self._find_matching_end(
                    lines, i, len(lines), "#inline", "#endinline"
                )

                # Extract macro body. Keep line boundaries: flattening with spaces
                # would make a // comment swallow every following body line.
                body_lines = lines[i + 1 : endinline_idx]
                body = textwrap.dedent("\n".join(body_lines)).strip()

                if not body:
                    raise self.make_error(
                        f"Macro '{name}' has empty body",
                        rule="empty-macro-body",
                        help="add an expression between #inline and #endinline",
                    )

                # Store macro with provenance-resolved location
                prov = self._resolve_provenance(i + 1)
                location = SourceLocation(prov.file, prov.line)
                self.macros[name] = Macro(name, params, body, location)

                self.log_debug(f"Defined macro: {name}({', '.join(params)})")

                # Skip past #endinline (block lines are consumed, not added to result)
                i = endinline_idx + 1
            else:
                result.append(line)
                self._keep_line_provenance(new_prov, has_prov, i)
                i += 1

        self._finish_provenance_pass(new_prov, has_prov)
        return result

    def _extract_functions(self, lines: list[str]) -> list[str]:
        """
        Extract #def...#enddef blocks and store them as functions.
        Returns lines with function definitions removed.
        """
        result = []
        new_prov, has_prov = self._start_provenance_pass(lines)
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            self.current_line = i + 1

            if self._directive(line) == "#def":
                # Parse function definition
                func_def = self._parse_function_def(stripped)
                if not func_def:
                    raise self.make_error(
                        f"Invalid #def syntax: {stripped}",
                        rule="invalid-def",
                        help="expected '#def name(param TYPE, ...) -> RETURN_TYPE'",
                        notes=["example: #def add(a INTEGER, b INTEGER) -> INTEGER"],
                    )

                name, params, return_type = func_def

                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                    raise self.make_error(
                        f"Invalid function name '{name}'",
                        rule="invalid-function-name",
                        help="function names must start with a letter or underscore",
                    )
                if name.startswith("vcl_"):
                    raise self.make_error(
                        f"Function name '{name}' uses the reserved 'vcl_' prefix",
                        rule="reserved-function-name",
                        help="choose a custom function name without the 'vcl_' prefix",
                    )
                if name in self._RESERVED_FUNCTION_NAMES:
                    raise self.make_error(
                        f"Function name '{name}' is reserved in VCL",
                        rule="reserved-function-name",
                        help="rename the function: VCL keywords and builtin function names can't name a subroutine",
                    )

                seen_params = set()
                for param_name, _ in params:
                    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", param_name):
                        raise self.make_error(
                            f"Invalid parameter name '{param_name}' in function '{name}'",
                            rule="invalid-function-param",
                            help="parameter names must be VCL identifiers",
                        )
                    if param_name in seen_params:
                        raise self.make_error(
                            f"Function '{name}' has duplicate parameter '{param_name}'",
                            rule="duplicate-function-param",
                            help="give every function parameter a unique name",
                        )
                    if param_name == "return_value" or re.fullmatch(r"return_value\d+", param_name):
                        raise self.make_error(
                            f"Function parameter '{param_name}' conflicts with generated return storage",
                            rule="reserved-function-param",
                            help="rename the parameter",
                        )
                    seen_params.add(param_name)

                if isinstance(return_type, list) and not return_type:
                    raise self.make_error(
                        f"Function '{name}' has an empty return tuple",
                        rule="invalid-function-return",
                        help="list at least one return type inside the parentheses",
                    )

                # Validate parameter types
                for param_name, param_type in params:
                    self._validate_vcl_type(
                        param_type, f"parameter '{param_name}' of function '{name}'"
                    )
                    self._validate_bridge_type(
                        param_type, f"parameter '{param_name}' of function '{name}'"
                    )

                # Validate return types
                ret_types = return_type if isinstance(return_type, list) else [return_type]
                for rt in ret_types:
                    self._validate_vcl_type(rt, f"return type of function '{name}'")
                    self._validate_bridge_type(rt, f"return type of function '{name}'")

                # Check for duplicate function names
                if name in self.functions:
                    raise self.make_error(
                        f"Function '{name}' is already defined",
                        rule="duplicate-function",
                        notes=[f"previously defined at {self.functions[name].location}"],
                        help="rename this function or remove the duplicate",
                    )

                # Find matching #enddef
                enddef_idx = self._find_matching_end(lines, i, len(lines), "#def", "#enddef")

                # Extract function body
                body = lines[i + 1 : enddef_idx]

                # Check for missing return statement
                has_return = self._RETURN_KEYWORD.search(_vcl_code_view("\n".join(body)))
                if return_type and not has_return:
                    ret_desc = (
                        f"({', '.join(return_type)})"
                        if isinstance(return_type, list)
                        else return_type
                    )
                    raise self.make_error(
                        f"Function '{name}' declares return type {ret_desc} but has no return statement",
                        rule="missing-return",
                        help="add 'return <expression>;' to the function body",
                    )

                # Store function with provenance-resolved location
                prov = self._resolve_provenance(i + 1)
                location = SourceLocation(prov.file, prov.line)
                body_provenance = self._line_provenance[i + 1 : enddef_idx] if has_prov else []
                self.functions[name] = Function(
                    name, params, return_type, body, location, body_provenance
                )

                self.log_debug(
                    f"Defined function: {name}({', '.join(p[0] for p in params)}) -> {return_type}"
                )

                # Skip past #enddef (block lines are consumed, not added to result)
                i = enddef_idx + 1
            else:
                result.append(line)
                self._keep_line_provenance(new_prov, has_prov, i)
                i += 1

        self._finish_provenance_pass(new_prov, has_prov)
        return result

    def _parse_function_def(self, line: str):
        """
        Parse function definition line.
        Format: #def name(param1 TYPE, param2 TYPE) -> RETURN_TYPE
                #def name(param1 TYPE, param2 TYPE) -> (TYPE1, TYPE2, ...)
        Returns: (name, [(param, type), ...], return_type)
                 return_type is str for single, List[str] for tuple
        """
        # Try tuple return first: #def name(params) -> (TYPE1, TYPE2, ...)
        tuple_match = re.match(r"#def\s+(\w+)\s*\((.*?)\)\s*->\s*\((.*?)\)", line)
        if tuple_match:
            name = tuple_match.group(1)
            params_str = tuple_match.group(2).strip()
            return_types_str = tuple_match.group(3).strip()

            # Parse return types
            return_types = [rt.strip() for rt in return_types_str.split(",") if rt.strip()]

            # Parse parameters
            params = []
            if params_str:
                for param in params_str.split(","):
                    param = param.strip()
                    if " " in param:
                        param_name, param_type = param.rsplit(" ", 1)
                        params.append((param_name.strip(), param_type.strip()))
                    else:
                        params.append((param, "STRING"))

            # A one-element tuple is a single value, and is called like one.
            if len(return_types) == 1:
                return (name, params, return_types[0])
            return (name, params, return_types)  # List for tuple return

        # Try single return: #def name(params) -> TYPE
        single_match = re.match(r"#def\s+(\w+)\s*\((.*?)\)\s*->\s*(\w+)", line)
        if not single_match:
            return None

        name = single_match.group(1)
        params_str = single_match.group(2).strip()
        return_type = single_match.group(3)

        # Parse parameters: "param1 TYPE, param2 TYPE"
        params = []
        if params_str:
            for param in params_str.split(","):
                param = param.strip()
                if " " in param:
                    param_name, param_type = param.rsplit(" ", 1)
                    params.append((param_name.strip(), param_type.strip()))
                else:
                    # Just param name, assume STRING
                    params.append((param, "STRING"))

        return (name, params, return_type)  # str for single return

    def _check_unused_definitions(self) -> None:
        """Emit warnings for constants, macros, and functions that are defined but never used."""
        for name in sorted(self.constants.keys()):
            if name not in self._used_constants:
                const_file, const_line = self._const_locations.get(name, (self.current_file, 0))
                self.diagnostics.append(
                    Diagnostic(
                        rule="unused-const",
                        severity="warning",
                        message=f"Constant '{name}' is defined but never used",
                        file=const_file,
                        line=const_line,
                        source_line="",
                    )
                )

        for name, macro in sorted(self.macros.items()):
            if name not in self._used_macros:
                loc = macro.location
                self.diagnostics.append(
                    Diagnostic(
                        rule="unused-macro",
                        severity="warning",
                        message=f"Macro '{name}' is defined but never used",
                        file=loc.file if loc else self.current_file,
                        line=loc.line if loc else 0,
                        source_line="",
                    )
                )

        for name, func in sorted(self.functions.items()):
            if name not in self._used_functions:
                loc = func.location
                self.diagnostics.append(
                    Diagnostic(
                        rule="unused-function",
                        severity="warning",
                        message=f"Function '{name}' is defined but never used",
                        file=loc.file if loc else self.current_file,
                        line=loc.line if loc else 0,
                        source_line="",
                    )
                )

    def _generate_function_subroutines(self) -> None:
        """Generate VCL subroutines for all defined functions."""
        if not self.functions:
            return

        if self.output and self.output[-1].strip():
            self.output.append("")

        for func in self.functions.values():
            if ("sub", func.name) in self._declared_names:
                prev_file, prev_line = self._declared_names[("sub", func.name)]
                self.diagnostics.append(
                    Diagnostic(
                        rule="duplicate-generated",
                        severity="error",
                        message=f"Function '{func.name}' clashes with a VCL subroutine of the same name",
                        file=func.location.file,
                        line=func.location.line,
                        notes=[f"'{func.name}' is also declared at {prev_file}:{prev_line}"],
                        help="rename the function or the VCL declaration",
                    )
                )
            self._generate_function_subroutine(func)

    def _generate_function_subroutine(self, func: Function) -> None:
        """Generate a VCL subroutine for a function."""
        if self.source_maps and func.location:
            self.output.append(f"// Generated from {func.location}")

        self.output.append(f"// Function: {func.name}")
        self.output.append("//@recv, hash, hit, miss, pass, fetch, error, deliver, log")
        self.output.append(f"sub {func.name} {{")
        self.output.append("")

        # Declare local variables for parameters
        for param_name, param_type in func.params:
            self.output.append(f"  declare local var.{param_name} {param_type};")

        if func.params:
            self.output.append("")

        # Request headers reach the origin, so each one is removed once it's read.
        for param_name, param_type in func.params:
            global_name = func.get_param_global(param_name)
            self.output.extend(
                self._from_global_conversion_lines(
                    "  ", f"var.{param_name}", global_name, param_type
                )
            )
            self.output.append(f"  unset {global_name};")

        if func.params:
            self.output.append("")

        # Declare return variable(s)
        return_types = func.get_return_types()
        if func.is_tuple_return():
            # Multiple return values
            for idx, ret_type in enumerate(return_types):
                self.output.append(f"  declare local var.return_value{idx} {ret_type};")
        else:
            # Single return value
            self.output.append(f"  declare local var.return_value {return_types[0]};")
        self.output.append("")

        # Parameters become var.* locals.
        # Replacing them in the whole body keeps multi-line strings and comments intact.
        # The body is then cut back into its entries, so multi-line directives stay joined.
        processed_body = _replace_vcl_identifiers(
            "\n".join(func.body), {name: f"var.{name}" for name, _ in func.params}
        )
        body_lines = _split_like(processed_body, func.body)

        saved_provenance = self._line_provenance
        self._line_provenance = func.body_provenance
        body_lines = self._join_multiline_function_calls(body_lines)

        saved_output = self.output
        self.output = []
        self._current_function = func
        self._process_lines(body_lines, 0, len(body_lines), {})
        self._current_function = None
        body_output = self.output
        self.output = saved_output
        self._line_provenance = saved_provenance

        self.output.extend(body_output)

        # If the body can reach its end, still hand back the return values.
        last_statement = next(
            (code for code in map(_vcl_code_view, reversed(body_output)) if code.strip()), ""
        )
        if not self._BARE_RETURN_AT_END.search(last_statement.rstrip()):
            self.output.append("")
            for idx, ret_type in enumerate(return_types):
                local_var = (
                    f"var.return_value{idx}" if func.is_tuple_return() else "var.return_value"
                )
                self.output.extend(
                    self._to_global_conversion_lines(
                        "  ", func.get_return_global(idx), local_var, ret_type
                    )
                )

        self.output.append("}")
        self.output.append("")

    def _rewrite_value_returns(self, text: str, func: Function, context: dict[str, Any]) -> str:
        """Turn the 'return EXPR;' statements of a #def body into assignments for the caller.

        The generated sub is VOID, so the value is stored in a header and a bare return goes back to the call site.
        """
        if "return" not in text:
            return text
        code = _vcl_code_view(text)
        return_types = func.get_return_types()
        edits: list[tuple[int, int, str]] = []

        for match in self._RETURN_KEYWORD.finditer(code):
            end = _find_top_level(code, match.end(), ";")
            expressions = _strip_vcl_comments(text[match.end() : end]).strip() if end else ""
            if not expressions:
                continue

            if func.is_tuple_return():
                # Expand templates first, since one may produce several values.
                exprs = self._parse_macro_args(self._substitute_expressions(expressions, context))
                if len(exprs) != len(return_types):
                    raise self.make_error(
                        f"Function '{func.name}' expects {len(return_types)} return values, got {len(exprs)}",
                        rule="return-expr-count",
                        help=f"return statement must have exactly {len(return_types)} comma-separated expressions",
                        notes=[f"return type is ({', '.join(return_types)})"],
                    )
                statements = [
                    f"set var.return_value{idx} = {expr};" for idx, expr in enumerate(exprs)
                ]
                for idx, ret_type in enumerate(return_types):
                    statements.extend(
                        self._to_global_conversion_lines(
                            "", func.get_return_global(idx), f"var.return_value{idx}", ret_type
                        )
                    )
            else:
                statements = [f"set var.return_value = {expressions};"]
                statements.extend(
                    self._to_global_conversion_lines(
                        "", func.get_return_global(), "var.return_value", return_types[0]
                    )
                )
            statements.append("return;")

            line_start = text.rfind("\n", 0, match.start()) + 1
            if code[line_start : match.start()].strip():
                replacement = " ".join(statement.strip() for statement in statements)
            else:
                indent = text[line_start : match.start()]
                replacement = f"\n{indent}".join(statements)
            assert end is not None
            edits.append((match.start(), end + 1, replacement))

        return _apply_edits(text, edits)

    def _to_global_conversion_lines(
        self, prefix: str, global_name: str, value_expr: str, value_type: str
    ) -> list[str]:
        """Build statements that store a typed value in a STRING-backed global."""
        lines = []
        if value_type == "INTEGER":
            lines.append(f"{prefix}set {global_name} = std.itoa({value_expr});")
        elif value_type == "BOOL":
            lines.append(f"{prefix}if ({value_expr}) {{")
            lines.append(f'{prefix}  set {global_name} = "true";')
            lines.append(f"{prefix}}} else {{")
            lines.append(f'{prefix}  set {global_name} = "false";')
            lines.append(f"{prefix}}}")
        else:
            lines.append(f"{prefix}set {global_name} = {value_expr};")
        return lines

    def _from_global_conversion_lines(
        self,
        prefix: str,
        result_var: str,
        global_name: str,
        value_type: str,
        operator: str = "=",
    ) -> list[str]:
        """Build statements that read a typed value from a STRING-backed global."""
        if value_type == "INTEGER":
            value = f"std.atoi({global_name})"
        elif value_type == "BOOL":
            value = f'({global_name} == "true")'
        else:
            value = global_name
        return [f"{prefix}set {result_var} {operator} {value};"]

    def _process_lines(
        self, lines: list[str], start: int, end: int, context: dict[str, Any]
    ) -> int:
        """
        Process lines from start to end with given context.
        Returns the index of the last processed line.
        """
        i = start
        while i < end:
            line = lines[i]
            self.current_line = i + 1

            directive = self._directive(line)

            # Handle #for loops
            if directive == "#for":
                self.log_debug(f"Processing #for at line {self.current_line}", indent=1)
                i = self._process_for_loop(lines, i, end, context)

            # Handle #if conditionals
            elif directive == "#if":
                self.log_debug(f"Processing #if at line {self.current_line}", indent=1)
                i = self._process_if(lines, i, end, context)

            # Handle #let (declare + initialize)
            elif directive == "#let":
                self.log_debug(f"Processing #let at line {self.current_line}", indent=1)
                self._process_let(line, context)
                i += 1

            # Blocks never pass their own closing line here, so this one has no opening directive.
            elif directive in ("#elif", "#else", "#endif", "#endfor", "#enddef", "#endinline"):
                raise self.make_error(
                    f"'{directive}' without a matching opening directive",
                    rule="unmatched-directive",
                    help=f"remove this '{directive}' or add the block it belongs to",
                )

            # Regular line - process function calls and template substitutions
            else:
                function = self._current_function
                if function is not None:
                    line = self._rewrite_value_returns(self._expand_macros(line), function, context)
                processed_line = self._process_function_calls(line, expand_macros=function is None)
                processed_line = self._substitute_expressions(processed_line, context)
                self.output.append(processed_line)
                # Track VCL declarations for duplicate detection, skipping commented-out ones.
                code = ""
                if self._VCL_DECL_PATTERN.search(processed_line):
                    code = _vcl_code_view(processed_line)
                for m in self._VCL_DECL_PATTERN.finditer(code):
                    decl_kind = m.group(1)
                    decl_name = m.group(2)
                    if decl_kind == "sub" and decl_name in self._CONCATENABLE_VCL_SUBROUTINES:
                        continue
                    # Resolve provenance for accurate file/line
                    prov = self._resolve_provenance(i + 1)
                    namespace = "backend" if decl_kind == "director" else decl_kind
                    if (namespace, decl_name) in self._declared_names:
                        prev_file, prev_line = self._declared_names[(namespace, decl_name)]
                        self.diagnostics.append(
                            Diagnostic(
                                rule="duplicate-generated",
                                severity="error",
                                message=f"Generated duplicate VCL declaration '{decl_name}'",
                                file=prov.file,
                                line=prov.line,
                                source_line=prov.source_text,
                                notes=[
                                    f"'{decl_name}' was first declared at {prev_file}:{prev_line}"
                                ],
                                help="check that loop iterations produce unique names",
                                included_from=prov.included_from,
                            )
                        )
                    else:
                        self._declared_names[(namespace, decl_name)] = (prov.file, prov.line)
                i += 1

        return i

    def _process_let(self, line: str, context: dict[str, Any]) -> None:
        """
        Process #let directive (declare + initialize).
        Format: #let name TYPE = expression;
        Generates: declare local var.name TYPE;
                   set var.name = expression;
        """
        # Macros expand before templates, as on ordinary lines, so placeholders from macro bodies get filled in.
        # Only the part after "#let" is expanded, since the whole line would look like a comment.
        indent, _, rest = line.partition("#let")
        line = self._substitute_expressions(f"{indent}#let{self._expand_macros(rest)}", context)

        # Match: #let name TYPE = expression;
        match = re.match(r"(\s*)#let\s+(\w+)\s+(\w+)\s*=\s*(.+);", line, flags=re.DOTALL)
        if not match:
            raise self.make_error(
                f"Invalid #let syntax: {line.strip()}",
                rule="invalid-let",
                help="expected '#let name TYPE = expression;'",
                notes=["example: #let count INTEGER = 0;"],
            )

        indent = match.group(1)
        var_name = match.group(2)
        var_type = match.group(3)
        expression = match.group(4)

        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", var_name):
            raise self.make_error(
                f"Invalid #let variable name '{var_name}'",
                rule="invalid-let-name",
                help="variable names must start with a letter or underscore",
            )

        # Validate the type
        self._validate_vcl_type(var_type, f"variable '{var_name}' in #let")

        self.log_debug(f"Declaring variable: var.{var_name} {var_type} = {expression}", indent=2)

        # Generate declare statement
        self.output.append(f"{indent}declare local var.{var_name} {var_type};")

        # Generate set statement and process any function calls in the expression
        set_statement = f"{indent}set var.{var_name} = {expression};"
        processed_set = self._process_function_calls(set_statement)

        # The processed_set might be multi-line if it contains function calls
        if "\n" in processed_set:
            self.output.extend(processed_set.split("\n"))
        else:
            self.output.append(processed_set)

    def _count_unquoted_delimiters(self, text: str) -> tuple[int, int]:
        """
        Count parentheses and bracket balance in Python code, ignoring strings and comments.
        Returns (paren_depth, bracket_depth), where brackets include {} braces.
        """
        paren_depth = 0
        bracket_depth = 0
        i = 0
        while i < len(text):
            char = text[i]
            if char in "\"'":
                i = _python_string_end(text, i)
                continue
            if char == "#":
                newline = text.find("\n", i)
                if newline == -1:
                    break
                i = newline
            elif char == "(":
                paren_depth += 1
            elif char == ")":
                paren_depth -= 1
            elif char in "[{":
                bracket_depth += 1
            elif char in "]}":
                bracket_depth -= 1
            i += 1
        return paren_depth, bracket_depth

    def _join_multiline_directives(self, lines: list[str]) -> list[str]:
        """
        Join lines that belong together into single entries.
        That's #const, #for, #if, #elif, and #let when their expression spans multiple lines, such as multi-line arrays.
        It's also every line of a multi-line comment, long string or template, so that text in there is never read as a directive.
        Also updates self._line_provenance to track the first physical line of each join.
        """
        result: list[str] = []
        first_indexes: list[int] = []
        new_prov, has_prov = self._start_provenance_pass(lines)
        continuations = _continuation_lines(lines)
        i = 0

        while i < len(lines):
            line = lines[i]

            if continuations[i] and result:
                result[-1] += "\n" + line
                if has_prov:
                    new_prov[-1] = self._merged_provenance(first_indexes[-1], i)
                i += 1
                continue
            first_indexes.append(i)

            if self._directive(line) not in ("#const", "#elif", "#for", "#if", "#let"):
                result.append(line)
                self._keep_line_provenance(new_prov, has_prov, i)
                i += 1
                continue

            expression = line.lstrip().split(None, 1)[1] if len(line.split()) > 1 else ""
            paren_depth, bracket_depth = self._count_unquoted_delimiters(expression)
            if paren_depth == 0 and bracket_depth == 0:
                result.append(line)
                self._keep_line_provenance(new_prov, has_prov, i)
                i += 1
                continue

            first_line_idx = i
            accumulated = [line]
            i += 1

            while i < len(lines) and (paren_depth > 0 or bracket_depth > 0):
                next_line = lines[i]
                accumulated.append(next_line)
                delta_paren, delta_bracket = self._count_unquoted_delimiters(next_line)
                paren_depth += delta_paren
                bracket_depth += delta_bracket
                i += 1

            result.append("\n".join(accumulated))
            if has_prov:
                new_prov.append(self._merged_provenance(first_line_idx, i - 1))

        self._finish_provenance_pass(new_prov, has_prov)
        return result

    def _join_multiline_function_calls(self, lines: list[str]) -> list[str]:
        """
        Join multi-line function calls into single lines.
        Also updates self._line_provenance.
        """
        result = []
        new_prov, has_prov = self._start_provenance_pass(lines)

        # Masked as a whole, since strings and comments can span lines.
        masked_lines = _split_like(_mask_vcl_opaque("\n".join(lines)), lines)
        i = 0

        while i < len(lines):
            line = lines[i]
            masked_line = masked_lines[i]

            # Check if this line contains an opening parenthesis
            if "(" not in masked_line:
                result.append(line)
                self._keep_line_provenance(new_prov, has_prov, i)
                i += 1
                continue

            paren_depth = masked_line.count("(") - masked_line.count(")")

            if paren_depth == 0:
                # Balanced on this line, no joining needed
                result.append(line)
                self._keep_line_provenance(new_prov, has_prov, i)
                i += 1
                continue

            # Unbalanced - need to join with following lines
            first_line_idx = i
            accumulated = [line]
            i += 1

            # A directive inside the parentheses must still run as a directive.
            while i < len(lines) and paren_depth > 0 and not self._directive(lines[i]):
                accumulated.append(lines[i])
                paren_depth += masked_lines[i].count("(") - masked_lines[i].count(")")
                i += 1

            # Keep physical newlines. The call parser accepts whitespace, while
            # flattening would make // comments swallow subsequent VCL tokens.
            result.append("\n".join(accumulated))
            if has_prov:
                new_prov.append(self._merged_provenance(first_line_idx, i - 1))

        self._finish_provenance_pass(new_prov, has_prov)
        return result

    # VCL names can contain "-", and rol= and ror= are words, so those operators need a space before them.
    # "X-Label-=" and "Control=" are plain assignments.
    _ASSIGNMENT_PATTERN = re.compile(
        r"(?P<lhs>[^=;]*?)(?P<op>\s*(?:[+*/%|&^]|<<|>>|&&|\|\|)?=|\s+(?:-|rol|ror)=)(?!=)"
    )
    _NAME_BOUNDARY = r"(?<![\w.:-])"
    _CALL_PATTERN = re.compile(r"(?<![\w.])(\w+)\s*\(")
    _RETURN_KEYWORD = re.compile(_NAME_BOUNDARY + r"return(?=\s)")
    _BARE_RETURN_AT_END = re.compile(_NAME_BOUNDARY + r"return\s*;$")
    _SPACES_THEN_SEMICOLON = re.compile(r"\s*;")

    def _parse_set_function_call(
        self, line: str
    ) -> Optional[tuple[str, str, list[str], str, str, list[str], str]]:
        """
        Parse a line of the form:
            <prefix>set a, b = func(arg1, arg2);
        Compound assignments such as "set x += func(...);" are recognized too.
        Returns (before, indent, result_vars, operator, func_name, args, suffix) or None.
        """
        masked_line = _mask_vcl_opaque(line)
        for match in re.finditer(r"\bset\s+", masked_line):
            assignment = self._ASSIGNMENT_PATTERN.match(masked_line, match.end())
            if not assignment:
                continue
            lhs = line[match.end() : assignment.end("lhs")].strip()
            if not lhs:
                continue

            # Spaces are checked on the real line: a masked string looks like spaces too.
            rhs_start = len(line) - len(line[assignment.end() :].lstrip())
            func_match = self._CALL_PATTERN.match(masked_line, rhs_start)
            if not func_match or func_match.group(1) not in self.functions:
                continue
            func_name = func_match.group(1)
            open_paren_index = func_match.end() - 1
            close_paren_index = _find_top_level(masked_line, open_paren_index + 1, ")")
            if close_paren_index is None:
                continue

            semicolon_match = self._SPACES_THEN_SEMICOLON.match(line, close_paren_index + 1)
            if not semicolon_match:
                continue

            # Comments between arguments must not end up inside generated statements.
            args_str = _strip_vcl_comments(line[open_paren_index + 1 : close_paren_index])
            args = self._parse_macro_args(args_str) if args_str.strip() else []

            result_vars = [v.strip() for v in lhs.split(",")] if "," in lhs else [lhs]
            if any(not v for v in result_vars):
                continue

            prefix = line[: match.start()]
            physical_prefix = prefix.rsplit("\n", 1)[-1]
            indent_match = re.match(r"\s*", physical_prefix)
            indent = indent_match.group(0) if indent_match else ""
            suffix = line[semicolon_match.end() :]
            operator = assignment.group("op").strip()
            return prefix, indent, result_vars, operator, func_name, args, suffix

        return None

    def _find_function_call(self, text: str) -> Optional[str]:
        """Return the name of the first xvcl function called in VCL code, if any."""
        if "(" not in text or not any(name in text for name in self.functions):
            return None
        for match in self._CALL_PATTERN.finditer(_vcl_code_view(text)):
            if match.group(1) in self.functions:
                return match.group(1)
        return None

    def _process_function_calls(self, line: str, expand_macros: bool = True) -> str:
        """Replace function calls with VCL subroutine calls using globals."""
        if expand_macros:
            line = self._expand_macros(line)

        parsed = self._parse_set_function_call(line)
        if not parsed:
            # Anything left would reach the VCL output as a call to an unknown function.
            leftover = self._find_function_call(line)
            if leftover:
                raise self.make_error(
                    f"Function '{leftover}' can only be called as 'set VAR = {leftover}(...);'",
                    rule="unsupported-function-call",
                    help="assign the result to a variable first, then use the variable",
                )
            return line

        before, indent, result_vars, operator, func_name, args, suffix = parsed

        func = self.functions[func_name]
        self._used_functions.add(func_name)
        return_types = func.get_return_types()

        if len(result_vars) > 1:
            if not func.is_tuple_return():
                raise self.make_error(
                    f"Function '{func_name}' returns a single value, but {len(result_vars)} variables provided",
                    rule="return-count-mismatch",
                    help=f"use single assignment: set var.x = {func_name}(...);",
                    notes=[
                        f"returns {func.return_type}",
                        f"defined at {func.location}" if func.location else "",
                    ],
                )

            if len(result_vars) != len(return_types):
                raise self.make_error(
                    f"Function '{func_name}' returns {len(return_types)} values, "
                    f"but {len(result_vars)} variables provided",
                    rule="return-count-mismatch",
                    help=f"use exactly {len(return_types)} variables: set a, b = {func_name}(...);",
                    notes=[
                        f"returns ({', '.join(return_types)})",
                        f"defined at {func.location}" if func.location else "",
                    ],
                )

            if operator != "=":
                raise self.make_error(
                    f"Tuple assignment from '{func_name}' must use '=', not '{operator}'",
                    rule="return-count-mismatch",
                    help="assign the values first, then combine them one by one",
                )
        elif func.is_tuple_return():
            raise self.make_error(
                f"Function '{func_name}' returns {len(return_types)} values, but assigned to a single variable",
                rule="return-count-mismatch",
                help=f"use tuple unpacking: set {', '.join('var.' + chr(97 + i) for i in range(len(return_types)))} = {func_name}(...);",
                notes=[
                    f"returns ({', '.join(return_types)})",
                    f"defined at {func.location}" if func.location else "",
                ],
            )

        self._check_func_arg_count(func, args)

        for arg in args:
            nested = self._find_function_call(arg)
            if nested:
                raise self.make_error(
                    f"Call to '{nested}' inside the arguments of '{func_name}'",
                    rule="nested-function-call",
                    help=f"assign the result of '{nested}(...)' to a variable first, then pass the variable",
                    notes=[
                        "arguments and results go through shared headers, so an inner call "
                        "could overwrite them"
                    ],
                )

        result_lines = []
        for (param_name, param_type), arg in zip(func.params, args):
            global_name = func.get_param_global(param_name)
            result_lines.extend(
                self._to_global_conversion_lines(indent, global_name, arg, param_type)
            )

        result_lines.append(f"{indent}call {func_name};")

        for idx, (result_var, ret_type) in enumerate(zip(result_vars, return_types)):
            return_global = func.get_return_global(idx)
            result_lines.extend(
                self._from_global_conversion_lines(
                    indent, result_var, return_global, ret_type, operator
                )
            )

        # Request headers reach the origin, so results are removed once read.
        # The exception is a result stored back into its own header.
        targets = {result_var.lower() for result_var in result_vars}
        for idx in range(len(return_types)):
            return_global = func.get_return_global(idx)
            if return_global.lower() not in targets:
                result_lines.append(f"{indent}unset {return_global};")

        if suffix:
            result_lines[-1] = f"{result_lines[-1]}{suffix}"

        result_lines[0] = before + result_lines[0][len(indent) :]
        return self._process_function_calls("\n".join(result_lines), expand_macros=False)

    def _check_func_arg_count(self, func: Function, args: list[str]) -> None:
        """Raise if argument count doesn't match function parameter count."""
        if len(args) != len(func.params):
            param_sig = ", ".join(f"{n} {t}" for n, t in func.params)
            raise self.make_error(
                f"Function '{func.name}' expects {len(func.params)} arguments, got {len(args)}",
                rule="func-arg-count",
                help=f"expected: {func.name}({param_sig})",
                notes=[f"defined at {func.location}" if func.location else ""],
            )

    def _expand_macros(self, line: str) -> str:
        """Expand all macro calls in a line."""
        # Keep expanding until no macros remain. Repeated output proves a direct or
        # mutual recursion; the cap also catches recursions whose output keeps growing.
        seen = set()
        for _ in range(100):
            if line in seen:
                raise self.make_error(
                    "Recursive macro expansion detected",
                    rule="macro-recursion",
                    help="check for macros that expand to calls of themselves or each other",
                )
            seen.add(line)

            line, expanded = self._expand_macros_once(line)
            if not expanded:
                return line

        raise self.make_error(
            "More than 100 macro expansions on one line (possible recursive macros)",
            rule="macro-recursion",
            help="check for macros that expand to calls of themselves or each other",
        )

    def _expand_macros_once(self, line: str) -> tuple[str, bool]:
        """Expand macros in a line once (one pass). Expand leftmost macro first."""
        # Names inside dotted VCL identifiers such as std.strlen are not macro calls.
        masked_line = _mask_vcl_opaque(line)
        for match in self._CALL_PATTERN.finditer(masked_line):
            macro_name = match.group(1)

            # Check if this is a macro
            if macro_name not in self.macros:
                continue

            close_paren = _find_top_level(masked_line, match.end(), ")")
            if close_paren is None:
                continue
            start_pos = match.end()
            pos = close_paren + 1

            # Extract arguments string (between parentheses)
            args_str = line[start_pos : pos - 1]

            # Parse arguments
            args = []
            if args_str.strip():
                args = self._parse_macro_args(args_str)

            # Expand the macro
            macro = self.macros[macro_name]
            self._used_macros.add(macro_name)
            try:
                expanded = macro.expand(args)
                self.log_debug(f"Expanded macro {macro_name}({args_str}) -> {expanded}", indent=3)
            except ValueError as e:
                raise self.make_error(
                    str(e),
                    rule="macro-arg-count",
                    help=f"macro '{macro_name}' expects {len(macro.params)} arguments: ({', '.join(macro.params)})",
                    notes=[f"defined at {macro.location}" if macro.location else ""],
                )

            if "\n" in expanded and not line[: match.start()].strip():
                indent = line[: match.start()]
                expanded = expanded.replace("\n", f"\n{indent}")

            # Build result with the macro replaced
            result = line[: match.start()] + expanded + line[pos:]
            return result, True

        # No macros found
        return line, False

    def _parse_macro_args(self, args_str: str) -> list[str]:
        """Split call arguments on commas outside strings, comments, templates and parentheses."""
        code = _vcl_code_view(args_str)
        args = []
        start = 0
        while (comma := _find_top_level(code, start, ",")) is not None:
            args.append(args_str[start:comma].strip())
            start = comma + 1
        if start < len(args_str):
            args.append(args_str[start:].strip())
        return args

    _DIRECTIVE_PATTERN = re.compile(
        r"#(const|def|elif|else|enddef|endfor|endif|endinline|for|if|include|inline|let)(?:\s|$)"
    )

    def _directive(self, line: str) -> Optional[str]:
        """Return the xvcl directive a line starts with, such as "#if", or None for VCL."""
        match = self._DIRECTIVE_PATTERN.match(line.strip())
        return "#" + match.group(1) if match else None

    _VCL_DECL_PATTERN = re.compile(
        r"^[ \t]*(backend|sub|table|acl|director|penaltybox|ratecounter)\s+([\w.-]+)", re.MULTILINE
    )
    _CONCATENABLE_VCL_SUBROUTINES = frozenset(
        {
            "vcl_recv",
            "vcl_hash",
            "vcl_hit",
            "vcl_miss",
            "vcl_pass",
            "vcl_fetch",
            "vcl_error",
            "vcl_deliver",
            "vcl_log",
        }
    )

    def _process_for_loop(
        self, lines: list[str], start: int, end: int, context: dict[str, Any]
    ) -> int:
        """Process a #for loop with optional tuple unpacking."""
        line = lines[start].strip()

        match = re.match(r"#for\s+(\w+(?:\s*,\s*\w+)*)\s+in\s+(.+)", line, flags=re.DOTALL)
        if not match:
            raise self.make_error(
                f"Invalid #for syntax: {line}",
                rule="invalid-for",
                help="expected '#for VARIABLE in EXPRESSION'",
                notes=["example: #for i in range(10)", "example: #for name, port in BACKENDS"],
            )

        vars_str = match.group(1).strip()
        iterable_expr = match.group(2)

        var_names = [v.strip() for v in vars_str.split(",")] if "," in vars_str else [vars_str]

        for var_name in var_names:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", var_name):
                raise self.make_error(
                    f"Invalid variable name in #for: '{var_name}'",
                    rule="invalid-for-var",
                    help="variable names must contain only letters, digits, and underscores",
                )
        if len(set(var_names)) != len(var_names):
            raise self.make_error(
                f"Duplicate variable name in #for: '{vars_str}'",
                rule="duplicate-for-var",
                help="give every tuple-unpacking variable a unique name",
            )

        try:
            iterable = self._evaluate_expression(iterable_expr, context)
        except Exception as e:
            raise self.make_error(
                f"Error evaluating loop expression '{iterable_expr}': {e}",
                rule="for-eval-error",
            )

        loop_end = self._find_matching_end(lines, start, end, "#for", "#endfor")

        try:
            iterable = list(iterable)
        except TypeError:
            raise self.make_error(
                f"Loop expression '{iterable_expr}' is not iterable",
                rule="for-not-iterable",
                help="use a list, tuple, range(), or another iterable value",
                notes=[f"got {type(iterable).__name__}: {iterable!r}"],
            )
        self.log_debug(f"Loop iterating {len(iterable)} times", indent=2)

        for idx, value in enumerate(iterable):
            loop_context = context.copy()

            if len(var_names) == 1:
                loop_context[var_names[0]] = value
                self.log_debug(f"Iteration {idx}: {var_names[0]} = {value}", indent=3)
            else:
                try:
                    values = tuple(value)
                except TypeError:
                    raise self.make_error(
                        f"Cannot unpack non-iterable value '{value}' into {len(var_names)} variables",
                        rule="unpack-not-iterable",
                        help=f"each item in the iterable must be a tuple of {len(var_names)} values",
                        notes=[f"got value: {value!r} (type: {type(value).__name__})"],
                    )

                if len(values) != len(var_names):
                    raise self.make_error(
                        f"Cannot unpack {len(values)} values into {len(var_names)} variables "
                        f"({', '.join(var_names)})",
                        rule="unpack-count-mismatch",
                        help=f"each item must have exactly {len(var_names)} elements",
                        notes=[f"got {len(values)} values: {values!r}"],
                    )

                for var_name, val in zip(var_names, values):
                    loop_context[var_name] = val

                self.log_debug(
                    f"Iteration {idx}: {', '.join(f'{n}={v}' for n, v in zip(var_names, values))}",
                    indent=3,
                )

            self._process_lines(lines, start + 1, loop_end, loop_context)

        # Raise first duplicate-generated error if any were collected during this loop
        dup_errors = [d for d in self.diagnostics if d.rule == "duplicate-generated"]
        if dup_errors:
            raise PreprocessorError(
                dup_errors[0].message,
                SourceLocation(dup_errors[0].file, dup_errors[0].line),
                diagnostic=dup_errors[0],
            )

        return loop_end + 1

    def _process_if(self, lines: list[str], start: int, end: int, context: dict[str, Any]) -> int:
        """Process a #if conditional with optional #elif and #else branches."""
        endif_idx = self._find_matching_end(lines, start, end, "#if", "#endif")

        # Branch headers of this block: the #if line, every #elif, then #else.
        headers = [start]
        depth = 0
        for i in range(start, endif_idx):
            directive = self._directive(lines[i])
            if directive == "#if":
                depth += 1
            elif directive == "#endif":
                depth -= 1
            elif depth == 1 and directive in ("#elif", "#else"):
                if self._directive(lines[headers[-1]]) == "#else":
                    self.current_line = i + 1
                    raise self.make_error(
                        f"'{directive}' after '#else' in the same #if block",
                        rule="misplaced-else",
                        help="#else must be the last branch before #endif",
                    )
                headers.append(i)

        for branch, header_idx in enumerate(headers):
            branch_end = headers[branch + 1] if branch + 1 < len(headers) else endif_idx
            line = lines[header_idx].strip()
            self.current_line = header_idx + 1

            if self._directive(line) != "#else":
                keyword = "#if" if branch == 0 else "#elif"
                match = re.match(rf"{keyword}\s+(.+)", line, flags=re.DOTALL)
                if not match:
                    raise self.make_error(
                        f"Invalid {keyword} syntax: {line}",
                        rule="invalid-if",
                        help=f"expected '{keyword} CONDITION'",
                        notes=["example: #if PRODUCTION", "example: #if len(BACKENDS) > 0"],
                    )

                condition = match.group(1)
                try:
                    result = self._evaluate_expression(condition, context)
                except Exception as e:
                    raise self.make_error(
                        f"Error evaluating condition '{condition}': {e}",
                        rule="if-eval-error",
                    )

                self.log_debug(f"Condition '{condition}' evaluated to {result}", indent=2)
                if not result:
                    continue

            self.log_debug(f"Taking branch at line {header_idx + 1}", indent=2)
            self._process_lines(lines, header_idx + 1, branch_end, context)
            break
        else:
            self.log_debug("Skipping if block", indent=2)

        return endif_idx + 1

    def _find_matching_end(
        self, lines: list[str], start: int, end: int, open_keyword: str, close_keyword: str
    ) -> int:
        """Find the matching closing keyword for a block."""
        depth = 0
        for i in range(start, end):
            directive = self._directive(lines[i])
            if directive == open_keyword:
                depth += 1
            elif directive == close_keyword:
                depth -= 1
                if depth == 0:
                    return i

        raise self.make_error(
            f"No matching {close_keyword} for {open_keyword} at line {start + 1}",
            line_num=start + 1,
            rule="unclosed-block",
            help=f"add '{close_keyword}' to close this block",
        )

    def _substitute_expressions(self, line: str, context: dict[str, Any]) -> str:
        """Substitute {{expression}} in a line."""
        result = []
        cursor = 0
        string_spans: Optional[list[tuple[int, int]]] = None

        while True:
            start = line.find("{{", cursor)
            if start == -1:
                result.append(line[cursor:])
                break

            result.append(line[cursor:start])
            end = _find_template_expression_end(line, start + 2)
            if end is None:
                raise self.make_error(
                    "No matching '}}' for template expression",
                    rule="unclosed-template-expression",
                    help="add '}}' after the compile-time expression",
                )

            expr = line[start + 2 : end]
            try:
                value = self._evaluate_expression(expr, context)
            except Exception as e:
                raise self.make_error(
                    f"Error evaluating expression '{expr}': {e}",
                    rule="expr-eval-error",
                )
            in_string = False
            if isinstance(value, float):
                if string_spans is None:
                    string_spans = [
                        (s, e) for kind, s, e in _vcl_segments(line) if kind == "string"
                    ]
                in_string = any(s < start < e for s, e in string_spans)
            result.append(_format_template_value(value, in_string))
            cursor = end + 2

        return "".join(result)

    def _evaluate_expression(self, expr: str, context: dict[str, Any]) -> Any:
        """Safely evaluate an expression in the given context."""
        try:
            safe_globals = {
                "range": range,
                "len": len,
                "str": str,
                "int": int,
                "hex": hex,
                "format": format,
                "abs": abs,
                "min": min,
                "max": max,
                "enumerate": enumerate,
                # Boolean literals (both Python and C-style)
                "True": True,
                "False": False,
                "true": True,
                "false": False,
            }

            # Merge constants into context.
            # The environment is passed as eval's *globals*: comprehension and
            # lambda bodies get their own scope and resolve free names through
            # globals, so names placed only in locals would be invisible there.
            # __builtins__ goes last so no constant or loop variable can
            # shadow it and restore access to Python builtins.
            eval_env = {**safe_globals, **self.constants, **context, "__builtins__": {}}
            result = eval(expr, eval_env)

            # Track which constants were referenced (fast pre-filter before regex)
            for const_name in self.constants:
                if const_name in expr and re.search(rf"\b{re.escape(const_name)}\b", expr):
                    self._used_constants.add(const_name)

            return result
        except NameError as e:
            # Provide helpful suggestions
            var_name = str(e).split("'")[1] if "'" in str(e) else ""
            available_names = (
                list(safe_globals.keys()) + list(self.constants.keys()) + list(context.keys())
            )
            suggestions = get_close_matches(var_name, available_names, n=3, cutoff=0.6)

            error_msg = f"Name '{var_name}' is not defined"
            if suggestions:
                error_msg += f"\n  Did you mean: {', '.join(suggestions)}?"
            error_msg += f"\n  Available: {', '.join(sorted(available_names))}"

            raise NameError(error_msg)
        except Exception as e:
            raise ValueError(f"Error evaluating expression '{expr}': {e}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="xvcl - Extended VCL compiler with metaprogramming features",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Features:
  - For loops: #for var in range(n)
  - Conditionals: #if condition
  - Templates: {{expression}}
  - Constants: #const NAME TYPE = value
  - Includes: #include "path/to/file.xvcl"
  - Inline macros: #inline name(params) ... #endinline
  - Functions: #def name(params) -> TYPE
  - Variables: #let name TYPE = expression;

Example:
  xvcl input.xvcl -o output.vcl
  xvcl input.xvcl -o output.vcl --debug
  xvcl input.xvcl -o output.vcl -I /path/to/includes
        """,
    )

    parser.add_argument("input", help="Input XVCL file")
    parser.add_argument("-o", "--output", help="Output VCL file (default: removes .xvcl extension)")
    parser.add_argument(
        "-I",
        "--include",
        dest="include_paths",
        action="append",
        help="Add include search path (can be specified multiple times)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug mode (verbose output)")
    parser.add_argument(
        "--source-maps", action="store_true", help="Add source map comments to generated code"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose output (alias for --debug)"
    )
    parser.add_argument(
        "--error-format",
        choices=["text", "json"],
        default="text",
        help="Error output format (default: text)",
    )

    args = parser.parse_args()

    # Determine output path
    if args.output:
        output_path = args.output
    elif args.input.endswith(".xvcl"):
        output_path = os.path.splitext(args.input)[0] + ".vcl"
    else:
        output_path = args.input + ".vcl"

    # Set up include paths
    include_paths = args.include_paths or ["."]

    # Enable debug if verbose flag is used
    debug = args.debug or args.verbose

    error_format = args.error_format
    use_json = error_format == "json"
    use_colors = sys.stderr.isatty()

    try:
        compiler = XVCLCompiler(
            include_paths=include_paths, debug=debug, source_maps=args.source_maps
        )
        compiler.process_file(args.input, output_path)

        # Report any warnings
        warnings = [d for d in compiler.diagnostics if d.severity == "warning"]
        if warnings:
            if use_json:
                print(
                    json.dumps({"diagnostics": [d.to_json() for d in warnings]}, indent=2),
                    file=sys.stderr,
                )
            else:
                for w in warnings:
                    print(w.format_text(use_colors=use_colors), file=sys.stderr)

        print(
            _styled(
                "✓ Compilation complete", Colors.GREEN, Colors.BOLD, enabled=sys.stdout.isatty()
            )
        )

    except PreprocessorError as e:
        # The error that stopped compilation isn't always among the collected ones.
        all_error_diags = [d for d in compiler.diagnostics if d.severity == "error"]
        if e.diagnostic and e.diagnostic not in all_error_diags:
            all_error_diags.append(e.diagnostic)

        if use_json:
            diags = (
                [d.to_json() for d in all_error_diags] if all_error_diags else [{"message": str(e)}]
            )
            print(json.dumps({"diagnostics": diags}, indent=2), file=sys.stderr)
        else:
            if all_error_diags:
                for diag in all_error_diags[:10]:  # Cap at 10
                    print(diag.format_text(use_colors=use_colors), file=sys.stderr)
                if len(all_error_diags) > 10:
                    print(
                        f"... and {len(all_error_diags) - 10} more errors",
                        file=sys.stderr,
                    )
            else:
                print(e.format_error(use_colors=use_colors), file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        diag = Diagnostic(rule="file-not-found", severity="error", message=str(e))
        if use_json:
            print(json.dumps({"diagnostics": [diag.to_json()]}, indent=2), file=sys.stderr)
        else:
            print(f"{_styled('Error:', Colors.RED, enabled=use_colors)} {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        diag = Diagnostic(rule="internal-error", severity="error", message=str(e))
        if use_json:
            print(json.dumps({"diagnostics": [diag.to_json()]}, indent=2), file=sys.stderr)
        else:
            print(
                f"{_styled('Unexpected error:', Colors.RED, enabled=use_colors)} {e}",
                file=sys.stderr,
            )
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
