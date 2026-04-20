#!/usr/bin/env python3
"""
xvcl - Extended VCL compiler with metaprogramming features

Features:
- #inline directive for zero-overhead text substitution macros
- Automatic parenthesization to prevent operator precedence issues
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
import os
import re
import sys
from dataclasses import dataclass, field
from difflib import get_close_matches
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
        severity_label = self.severity
        if use_colors:
            color = Colors.RED if self.severity == "error" else Colors.YELLOW
            parts.append(f"{color}{Colors.BOLD}{severity_label}[{self.rule}]{Colors.RESET}")
            parts.append(f"{Colors.BOLD}: {self.message}{Colors.RESET}\n")
        else:
            parts.append(f"{severity_label}[{self.rule}]: {self.message}\n")

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

        if use_colors:
            parts.append(f"{Colors.RED}{Colors.BOLD}Error{Colors.RESET}")
        else:
            parts.append("Error")

        if self.location:
            parts.append(f" at {self.location}:")
        else:
            parts.append(":")

        parts.append(f"\n  {self.message}\n")

        if self.context_lines and self.location:
            parts.append("\n  Context:\n")
            for line_num, line_text in self.context_lines:
                prefix = "  → " if line_num == self.location.line else "    "
                if use_colors and line_num == self.location.line:
                    parts.append(f"{Colors.BOLD}{prefix}{line_num}: {line_text}{Colors.RESET}\n")
                else:
                    parts.append(f"{prefix}{line_num}: {line_text}\n")

        return "".join(parts)


class Macro:
    """Represents an inline macro definition."""

    def __init__(
        self, name: str, params: list[str], body: str, location: Optional[SourceLocation] = None
    ):
        self.name = name
        self.params = params  # [param_name, ...]
        self.body = body  # Single expression (string)
        self.location = location

    def expand(self, args: list[str]) -> str:
        """Expand macro by substituting parameters with arguments."""
        if len(args) != len(self.params):
            raise ValueError(
                f"Macro {self.name} expects {len(self.params)} arguments, got {len(args)}"
            )

        # Start with body
        result = self.body

        # Replace each parameter with its argument
        # Use word boundaries to avoid partial replacements
        for param, arg in zip(self.params, args):
            # Only wrap argument in parentheses if it contains operators
            # This avoids creating grouped expressions for simple values
            if any(op in arg for op in ["+", "-", "*", "/", "%", "==", "!=", "<", ">", "&&", "||"]):
                wrapped_arg = f"({arg})"
            else:
                wrapped_arg = arg
            result = re.sub(rf"\b{re.escape(param)}\b", wrapped_arg, result)

        # Don't wrap entire expression - let VCL handle operator precedence naturally
        return result


class Function:
    """Represents a VCL function definition."""

    def __init__(
        self,
        name: str,
        params: list[tuple[str, str]],
        return_type,
        body: list[str],
        location: Optional[SourceLocation] = None,
    ):
        self.name = name
        self.params = params  # [(param_name, param_type), ...]
        self.return_type = return_type  # str for single return, List[str] for tuple
        self.body = body
        self.location = location

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
        self._declared_names: dict[str, tuple[str, int]] = {}  # VCL name -> (file, line)
        self._used_constants: set[str] = set()
        self._used_macros: set[str] = set()
        self._used_functions: set[str] = set()
        self._const_locations: dict[str, tuple[str, int]] = {}  # const name -> (file, line)

        # Include tracking
        self.included_files: set[str] = set()  # Absolute paths of included files
        self.include_stack: list[str] = []  # Stack for cycle detection

        # Current source location for error reporting
        self.current_file: str = ""
        self.current_line: int = 0
        self.current_lines: list[str] = []  # All lines for context

        # Per-line provenance: maps line index -> LineProvenance
        self._line_provenance: list[_LineProv] = []

    def log_debug(self, message: str, indent: int = 0):
        """Log debug message if debug mode is enabled."""
        if self.debug:
            prefix = "  " * indent
            print(f"{Colors.GRAY}[DEBUG]{Colors.RESET} {prefix}{message}")

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
        """Create a PreprocessorError with a structured Diagnostic."""
        actual_line = line_num or self.current_line

        # Resolve provenance to get the real origin file/line/source text
        prov = self._resolve_provenance(actual_line)

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
        print(f"{Colors.GREEN}✓{Colors.RESET} Compiled {input_path} -> {output_path}")
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
        abs_path = os.path.abspath(filename) if os.path.exists(filename) else filename
        self.included_files.add(abs_path)

        lines = self.current_lines

        # Initialize provenance: each line maps to its origin
        self._line_provenance = [
            _LineProv.single(filename, i + 1, lines[i].rstrip()) for i in range(len(lines))
        ]

        # Pass 0: join multi-line directives (arrays/expressions across lines)
        self.log_debug("Pass 0: Joining multi-line directives")
        lines = self._join_multiline_directives(lines)

        # First pass: extract constants
        self.log_debug("Pass 1: Extracting constants")
        lines = self._extract_constants(lines)
        self._raise_if_errors()

        # Second pass: process includes
        self.log_debug("Pass 2: Processing includes")
        lines = self._process_includes(lines, filename)

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

    def _extract_constants(self, lines: list[str]) -> list[str]:
        """
        Extract #const declarations and store them.
        Returns lines with const declarations removed.
        """
        const_locations: dict[str, tuple[int, Any]] = {}  # name -> (line, value)
        result = []
        new_prov, has_prov = self._start_provenance_pass(lines)
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            self.current_line = i + 1

            if stripped.startswith("#const "):
                try:
                    self._extract_single_constant(stripped, const_locations, i)
                except PreprocessorError as e:
                    if e.diagnostic:
                        self.diagnostics.append(e.diagnostic)
                    else:
                        raise
                i += 1
            else:
                result.append(line)
                self._keep_line_provenance(new_prov, has_prov, i)
                i += 1

        self._finish_provenance_pass(new_prov, has_prov)
        return result

    def _extract_single_constant(
        self,
        stripped: str,
        const_locations: dict[str, tuple[int, Any]],
        line_idx: int,
    ) -> None:
        """Parse and register a single #const declaration. Raises PreprocessorError on failure."""
        # Parse: #const NAME TYPE = value
        match = re.match(r"#const\s+(\w+)\s+(\w+)\s*=\s*(.+)", stripped)
        if not match:
            # Try without type: #const NAME = value (infer type)
            match = re.match(r"#const\s+(\w+)\s*=\s*(.+)", stripped)
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
            expected_type = self._python_type_from_vcl(const_type)
            if not isinstance(value, expected_type):
                raise self.make_error(
                    f"Constant '{name}' type mismatch: expected {const_type}, "
                    f"got {type(value).__name__}",
                    rule="const-type-mismatch",
                    help=f"value evaluates to {type(value).__name__}, but {const_type} was declared",
                )

        # Check for duplicate constants
        if name in const_locations:
            prev_line, prev_value = const_locations[name]
            raise self.make_error(
                f"Constant '{name}' is already defined",
                rule="const-redefined",
                notes=[f"previously defined as {prev_value!r} at {self.current_file}:{prev_line}"],
                help="rename this constant or remove the duplicate",
            )

        const_locations[name] = (self.current_line, value)
        self._const_locations[name] = (self.current_file, self.current_line)
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

    # Types that xvcl's function bridge can convert through STRING headers
    _BRIDGE_TYPES = frozenset({"STRING", "INTEGER", "FLOAT", "BOOL"})

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
    ) -> list[str]:
        """
        Process #include directives and insert included file contents.
        Returns lines with includes expanded. Also updates self._line_provenance.
        """
        if include_chain is None:
            include_chain = []

        result = []
        result_provenance: list[_LineProv] = []
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            self.current_line = i + 1

            if stripped.startswith("#include "):
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

                # Check if already included (include-once semantics)
                if abs_path in self.included_files:
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

                # Build include chain for provenance
                child_chain = include_chain + [(current_file, i + 1)]

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
                included_lines = self._extract_constants(included_lines)
                included_lines = self._process_includes(included_lines, resolved_path, child_chain)

                # Capture the included file's provenance before restoring state
                included_provenance = list(self._line_provenance)

                # Restore state
                self.current_file = saved_file
                self.current_line = saved_line
                self.current_lines = saved_lines

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

            if stripped.startswith("#inline "):
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

                # Find matching #endinline
                endinline_idx = self._find_matching_end(
                    lines, i, len(lines), "#inline", "#endinline"
                )

                # Extract macro body (should be a single expression)
                body_lines = lines[i + 1 : endinline_idx]
                # Join all lines and strip whitespace
                body = " ".join(line.strip() for line in body_lines).strip()

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

            if stripped.startswith("#def "):
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
                has_return = any(re.match(r"\s*return\s+", line) for line in body)
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
                self.functions[name] = Function(name, params, return_type, body, location)

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

        # Read parameters from globals with type conversion
        for param_name, param_type in func.params:
            global_name = func.get_param_global(param_name)
            self.output.extend(
                self._from_global_conversion_lines(
                    "  ", f"var.{param_name}", global_name, param_type
                )
            )

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

        # Process function body
        param_substituted_body = []
        for line in func.body:
            processed_line = line
            for param_name, _ in func.params:
                # Replace standalone parameter references
                processed_line = re.sub(rf"\b{param_name}\b", f"var.{param_name}", processed_line)
            param_substituted_body.append(processed_line)

        # Save current output and process body
        saved_output = self.output
        self.output = []

        self._process_lines(param_substituted_body, 0, len(param_substituted_body), {})

        body_output = self.output
        self.output = saved_output

        # Post-process the body output to handle return statements
        for line in body_output:
            # Replace "return expr1, expr2;" with multiple assignments
            if re.match(r"\s*return\s+", line):
                if func.is_tuple_return():
                    # Parse: return expr1, expr2, expr3;
                    return_match = re.search(r"\breturn\s+(.+);", line)
                    if return_match:
                        exprs_str = return_match.group(1)
                        exprs = [e.strip() for e in exprs_str.split(",")]

                        if len(exprs) != len(return_types):
                            raise self.make_error(
                                f"Function '{func.name}' expects {len(return_types)} return values, got {len(exprs)}",
                                line_num=func.location.line if func.location else None,
                                rule="return-expr-count",
                                help=f"return statement must have exactly {len(return_types)} comma-separated expressions",
                                notes=[f"return type is ({', '.join(return_types)})"],
                            )

                        match_indent = re.match(r"(\s*)", line)
                        indent = match_indent.group(1) if match_indent else ""
                        for idx, expr in enumerate(exprs):
                            self.output.append(f"{indent}set var.return_value{idx} = {expr};")
                        continue
                else:
                    # Single return
                    line = re.sub(r"\breturn\s+(.+);", r"set var.return_value = \1;", line)

            self.output.append(line)

        # Write return value(s) to global(s)
        self.output.append("")
        if func.is_tuple_return():
            for idx, ret_type in enumerate(return_types):
                return_global = func.get_return_global(idx)
                self._write_return_conversion(return_global, f"var.return_value{idx}", ret_type)
        else:
            return_global = func.get_return_global()
            self._write_return_conversion(return_global, "var.return_value", return_types[0])

        self.output.append("}")
        self.output.append("")

    def _to_global_conversion_lines(
        self, prefix: str, global_name: str, value_expr: str, value_type: str
    ) -> list[str]:
        """Build statements that store a typed value in a STRING-backed global."""
        lines = []
        if value_type == "INTEGER":
            lines.append(f"{prefix}set {global_name} = std.itoa({value_expr});")
        elif value_type == "FLOAT":
            lines.append(f'{prefix}set {global_name} = "" + {value_expr};')
        elif value_type == "BOOL":
            lines.append(f"{prefix}if ({value_expr}) {{")
            lines.append(f'{prefix}  set {global_name} = "true";')
            lines.append(f"{prefix}}} else {{")
            lines.append(f'{prefix}  set {global_name} = "false";')
            lines.append(f"{prefix}}}")
        else:
            # STRING and others
            lines.append(f"{prefix}set {global_name} = {value_expr};")
        return lines

    def _from_global_conversion_lines(
        self, prefix: str, result_var: str, global_name: str, value_type: str
    ) -> list[str]:
        """Build statements that read a typed value from a STRING-backed global."""
        lines = []
        if value_type == "INTEGER":
            lines.append(f"{prefix}set {result_var} = std.atoi({global_name});")
        elif value_type == "FLOAT":
            lines.append(f"{prefix}set {result_var} = std.atof({global_name});")
        elif value_type == "BOOL":
            lines.append(f'{prefix}set {result_var} = ({global_name} == "true");')
        else:
            lines.append(f"{prefix}set {result_var} = {global_name};")
        return lines

    def _write_return_conversion(self, global_var: str, local_var: str, var_type: str) -> None:
        """Helper to write type conversion for return value."""
        self.output.extend(self._to_global_conversion_lines("  ", global_var, local_var, var_type))

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
            stripped = line.strip()
            self.current_line = i + 1

            # Handle #for loops
            if stripped.startswith("#for "):
                self.log_debug(f"Processing #for at line {self.current_line}", indent=1)
                i = self._process_for_loop(lines, i, end, context)

            # Handle #if conditionals
            elif stripped.startswith("#if "):
                self.log_debug(f"Processing #if at line {self.current_line}", indent=1)
                i = self._process_if(lines, i, end, context)

            # Handle #let (declare + initialize)
            elif stripped.startswith("#let "):
                self.log_debug(f"Processing #let at line {self.current_line}", indent=1)
                self._process_let(line)
                i += 1

            # Skip control flow keywords
            elif stripped in ("#else", "#endif", "#endfor", "#enddef", "#endinline"):
                return i

            # Regular line - process function calls and template substitutions
            else:
                processed_line = self._process_function_calls(line)
                processed_line = self._substitute_expressions(processed_line, context)
                self.output.append(processed_line)
                # Track VCL declarations for duplicate detection
                m = self._VCL_DECL_PATTERN.match(processed_line)
                if m:
                    decl_name = m.group(1)
                    # Resolve provenance for accurate file/line
                    prov = self._resolve_provenance(i + 1)
                    if decl_name in self._declared_names:
                        prev_file, prev_line = self._declared_names[decl_name]
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
                        self._declared_names[decl_name] = (prov.file, prov.line)
                i += 1

        return i

    def _process_let(self, line: str) -> None:
        """
        Process #let directive (declare + initialize).
        Format: #let name TYPE = expression;
        Generates: declare local var.name TYPE;
                   set var.name = expression;
        """
        # Match: #let name TYPE = expression;
        match = re.match(r"(\s*)#let\s+(\w+)\s+(\w+)\s*=\s*(.+);", line)
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

    def _count_unquoted_parens(self, text: str) -> int:
        """
        Count parentheses balance, ignoring those inside string literals.
        Returns positive number for more opens than closes.
        """
        paren_depth, _ = self._count_unquoted_delimiters(text)
        return paren_depth

    def _count_unquoted_delimiters(self, text: str) -> tuple[int, int]:
        """
        Count parentheses and bracket balance, ignoring those inside string literals.
        Returns (paren_depth, bracket_depth).
        """
        paren_depth = 0
        bracket_depth = 0
        in_string = False
        string_char = None
        i = 0
        while i < len(text):
            char = text[i]
            if in_string:
                if char == "\\" and i + 1 < len(text):
                    i += 2
                    continue
                elif char == string_char:
                    in_string = False
            else:
                if char in ('"', "'"):
                    in_string = True
                    string_char = char
                elif char == "(":
                    paren_depth += 1
                elif char == ")":
                    paren_depth -= 1
                elif char == "[":
                    bracket_depth += 1
                elif char == "]":
                    bracket_depth -= 1
            i += 1
        return paren_depth, bracket_depth

    def _join_multiline_directives(self, lines: list[str]) -> list[str]:
        """
        Join multi-line directive expressions into single lines.
        Supports #const, #for, #if, and #let when expressions span multiple lines,
        such as multi-line arrays.
        Also updates self._line_provenance to track the first physical line of each join.
        """
        result = []
        new_prov, has_prov = self._start_provenance_pass(lines)
        i = 0
        # str.startswith accepts a tuple of prefixes.
        directive_prefixes = ("#const ", "#for ", "#if ", "#let ")

        while i < len(lines):
            line = lines[i]
            stripped = line.lstrip()

            if not stripped.startswith(directive_prefixes):
                result.append(line)
                self._keep_line_provenance(new_prov, has_prov, i)
                i += 1
                continue

            paren_depth, bracket_depth = self._count_unquoted_delimiters(line)
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

            leading_ws = len(line) - len(line.lstrip())
            indent = line[:leading_ws]
            joined_parts = []
            for part in accumulated:
                part_stripped = part.strip()
                if part_stripped:
                    joined_parts.append(part_stripped)
            joined = " ".join(joined_parts)
            result.append(indent + joined)
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
        i = 0

        while i < len(lines):
            line = lines[i]

            # Check if this line contains an opening parenthesis
            if "(" not in line:
                result.append(line)
                self._keep_line_provenance(new_prov, has_prov, i)
                i += 1
                continue

            # Count parentheses (ignoring those in strings) to see if they balance
            paren_depth = self._count_unquoted_parens(line)

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

            while i < len(lines) and paren_depth > 0:
                next_line = lines[i]
                accumulated.append(next_line)
                paren_depth += self._count_unquoted_parens(next_line)
                i += 1

            # Join the accumulated lines
            leading_ws = len(line) - len(line.lstrip())
            indent = line[:leading_ws]

            joined_parts = []
            for part in accumulated:
                stripped = part.strip()
                if stripped:
                    joined_parts.append(stripped)

            joined = " ".join(joined_parts)
            result.append(indent + joined)
            if has_prov:
                new_prov.append(self._merged_provenance(first_line_idx, i - 1))

        self._finish_provenance_pass(new_prov, has_prov)
        return result

    def _find_matching_paren(self, text: str, start: int) -> Optional[int]:
        """Find the matching ')' for '(' at index start, ignoring strings."""
        if start < 0 or start >= len(text) or text[start] != "(":
            return None

        depth = 1
        pos = start + 1
        in_string = False
        string_char = None

        while pos < len(text) and depth > 0:
            char = text[pos]
            if in_string:
                if char == "\\" and pos + 1 < len(text):
                    pos += 2
                    continue
                elif char == string_char:
                    in_string = False
            else:
                if char in ('"', "'"):
                    in_string = True
                    string_char = char
                elif char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
            pos += 1

        if depth != 0:
            return None

        return pos - 1

    # Known VCL built-in function names/prefixes that should not trigger
    # "undefined function" errors when used in set assignments.
    _VCL_BUILTINS = frozenset(
        {
            # String functions
            "regsub",
            "regsuball",
            "strlen",
            "strftime",
            "substr",
            # Conversion / utility (dotted-prefix modules)
            "std",
            "digest",
            "uuid",
            "accept",
            "boltsort",
            "header",
            "querystring",
            "table",
            "ratelimit",
            "subfield",
            "setcookie",
            "cookie",
            "synthbackend",
            "fastly",
            "regextract",
            # Math
            "math",
            "randomint",
            "randomstr",
            "crc32",
            # Misc
            "if",
            "now",
            "time",
            "urlencode",
            "urldecode",
        }
    )

    def _is_vcl_builtin(self, name: str) -> bool:
        """Check if a function name is a known VCL builtin (should not be flagged as undefined)."""
        # Check direct match
        if name in self._VCL_BUILTINS:
            return True
        # Check dotted prefix (std.tolower -> std)
        prefix = name.split(".")[0] if "." in name else ""
        return prefix in self._VCL_BUILTINS

    def _parse_set_function_call(
        self, line: str
    ) -> Optional[tuple[str, list[str], str, list[str], str]]:
        """
        Parse a line of the form:
            <prefix>set a, b = func(arg1, arg2);
        Returns (prefix, result_vars, func_name, args, suffix) or None.
        """
        for match in re.finditer(r"\bset\s+", line):
            prefix = line[: match.start()]
            rest = line[match.end() :]

            if "=" not in rest:
                continue

            lhs, rhs = rest.split("=", 1)
            lhs = lhs.strip()
            rhs = rhs.lstrip()

            if not lhs:
                continue

            func_match = re.match(r"(\w+)\s*\(", rhs)
            if not func_match:
                continue

            func_name = func_match.group(1)
            open_paren_index = func_match.end() - 1
            close_paren_index = self._find_matching_paren(rhs, open_paren_index)
            if close_paren_index is None:
                continue

            args_str = rhs[open_paren_index + 1 : close_paren_index]
            tail = rhs[close_paren_index + 1 :]

            semicolon_match = re.match(r"\s*;(?P<suffix>.*)", tail, flags=re.DOTALL)
            if not semicolon_match:
                continue

            suffix = semicolon_match.group("suffix")

            # Split result vars (tuple unpacking if comma-separated)
            result_vars = [v.strip() for v in lhs.split(",")] if "," in lhs else [lhs]
            if any(not v for v in result_vars):
                continue

            args = []
            if args_str.strip():
                args = self._parse_macro_args(args_str)

            return prefix, result_vars, func_name, args, suffix

        return None

    def _process_function_calls(self, line: str) -> str:
        """Replace function calls with VCL subroutine calls using globals."""
        # First, expand any macros in the line (NEW in v2.4)
        line = self._expand_macros(line)

        parsed = self._parse_set_function_call(line)
        if not parsed:
            return line

        prefix, result_vars, func_name, args, suffix = parsed

        if func_name not in self.functions:
            # Check if this looks like an xvcl function call that's undefined
            # (vs a VCL builtin like regsub, std.tolower, etc.)
            if not self._is_vcl_builtin(func_name):
                all_names = list(self.functions.keys()) + list(self.macros.keys())
                suggestions = get_close_matches(func_name, all_names, n=3, cutoff=0.6)
                raise self.make_error(
                    f"Function '{func_name}' is not defined",
                    rule="undefined-function",
                    suggestions=suggestions,
                    notes=[
                        f"defined functions: {', '.join(sorted(self.functions.keys()))}"
                        if self.functions
                        else "no functions defined"
                    ],
                )
            return line

        func = self.functions[func_name]
        self._used_functions.add(func_name)
        return_types = func.get_return_types()

        # Tuple assignment
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

            self._check_func_arg_count(func, args)

            result_lines = []
            for (param_name, param_type), arg in zip(func.params, args):
                global_name = func.get_param_global(param_name)
                result_lines.extend(self._param_to_global(prefix, global_name, arg, param_type))

            result_lines.append(f"{prefix}call {func_name};")

            for idx, (result_var, ret_type) in enumerate(zip(result_vars, return_types)):
                return_global = func.get_return_global(idx)
                result_lines.extend(
                    self._global_to_var(prefix, result_var, return_global, ret_type)
                )

            if suffix:
                result_lines[-1] = f"{result_lines[-1]}{suffix}"

            return "\n".join(result_lines)

        # Single assignment
        if func.is_tuple_return():
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

        result_lines = []
        for (param_name, param_type), arg in zip(func.params, args):
            global_name = func.get_param_global(param_name)
            result_lines.extend(self._param_to_global(prefix, global_name, arg, param_type))

        result_lines.append(f"{prefix}call {func_name};")

        return_global = func.get_return_global()
        result_lines.extend(
            self._global_to_var(prefix, result_vars[0], return_global, return_types[0])
        )

        if suffix:
            result_lines[-1] = f"{result_lines[-1]}{suffix}"

        return "\n".join(result_lines)

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
        # Keep expanding until no more macros found (handle nested macros)
        max_iterations = 10  # Prevent infinite loops
        iteration = 0

        while iteration < max_iterations:
            new_line = self._expand_macros_once(line)
            if new_line == line:
                break  # No more macros to expand
            line = new_line
            iteration += 1

        if iteration >= max_iterations:
            raise self.make_error(
                "Too many macro expansion iterations (possible recursive macros)",
                rule="macro-recursion",
                help="check for macros that expand to calls of themselves or each other",
            )

        return line

    def _expand_macros_once(self, line: str) -> str:
        """Expand macros in a line once (one pass). Expand leftmost macro first."""
        # Find potential macro calls by looking for identifier followed by (
        pattern = r"\b(\w+)\s*\("

        for match in re.finditer(pattern, line):
            macro_name = match.group(1)

            # Check if this is a macro
            if macro_name not in self.macros:
                continue

            # Find the matching closing parenthesis (ignoring parens inside strings)
            start_pos = match.end()  # Position after the opening (
            paren_depth = 1
            pos = start_pos
            in_string = False
            string_char = None

            while pos < len(line) and paren_depth > 0:
                char = line[pos]
                if in_string:
                    if char == "\\" and pos + 1 < len(line):
                        # Skip escaped character
                        pos += 2
                        continue
                    elif char == string_char:
                        in_string = False
                else:
                    if char in ('"', "'"):
                        in_string = True
                        string_char = char
                    elif char == "(":
                        paren_depth += 1
                    elif char == ")":
                        paren_depth -= 1
                pos += 1

            if paren_depth != 0:
                # Unmatched parentheses - skip this match
                continue

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

            # Build result with the macro replaced
            result = line[: match.start()] + expanded + line[pos:]
            return result

        # No macros found
        return line

    def _parse_macro_args(self, args_str: str) -> list[str]:
        """Parse macro arguments, handling nested parentheses and strings."""
        args = []
        current_arg = []
        depth = 0
        in_string = False
        string_char = None
        i = 0

        while i < len(args_str):
            char = args_str[i]

            if in_string:
                current_arg.append(char)
                if char == "\\" and i + 1 < len(args_str):
                    # Include escaped character
                    current_arg.append(args_str[i + 1])
                    i += 2
                    continue
                elif char == string_char:
                    in_string = False
            else:
                if char in ('"', "'"):
                    in_string = True
                    string_char = char
                    current_arg.append(char)
                elif char == "(":
                    depth += 1
                    current_arg.append(char)
                elif char == ")":
                    depth -= 1
                    current_arg.append(char)
                elif char == "," and depth == 0:
                    # End of current argument
                    args.append("".join(current_arg).strip())
                    current_arg = []
                else:
                    current_arg.append(char)
            i += 1

        # Add last argument
        if current_arg:
            args.append("".join(current_arg).strip())

        return args

    def _param_to_global(
        self, prefix: str, global_name: str, arg: str, param_type: str
    ) -> list[str]:
        """Convert parameter to global with type conversion."""
        return self._to_global_conversion_lines(prefix, global_name, arg, param_type)

    def _global_to_var(
        self, prefix: str, result_var: str, return_global: str, ret_type: str
    ) -> list[str]:
        """Convert global to variable with type conversion."""
        return self._from_global_conversion_lines(prefix, result_var, return_global, ret_type)

    _VCL_DECL_PATTERN = re.compile(
        r"^\s*(?:backend|sub|table|acl|director|penaltybox|ratecounter)\s+([\w.-]+)"
    )

    def _process_for_loop(
        self, lines: list[str], start: int, end: int, context: dict[str, Any]
    ) -> int:
        """Process a #for loop with optional tuple unpacking."""
        line = lines[start].strip()

        match = re.match(r"#for\s+(\w+(?:\s*,\s*\w+)*)\s+in\s+(.+)", line)
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
            if not re.match(r"^\w+$", var_name):
                raise self.make_error(
                    f"Invalid variable name in #for: '{var_name}'",
                    rule="invalid-for-var",
                    help="variable names must contain only letters, digits, and underscores",
                )

        try:
            iterable = self._evaluate_expression(iterable_expr, context)
        except Exception as e:
            raise self.make_error(
                f"Error evaluating loop expression '{iterable_expr}': {e}",
                rule="for-eval-error",
            )

        loop_end = self._find_matching_end(lines, start, end, "#for", "#endfor")

        iterable = list(iterable)
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
        """Process a #if conditional."""
        line = lines[start].strip()

        match = re.match(r"#if\s+(.+)", line)
        if not match:
            raise self.make_error(
                f"Invalid #if syntax: {line}",
                rule="invalid-if",
                help="expected '#if CONDITION'",
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

        else_idx = None
        endif_idx = self._find_matching_end(lines, start, end, "#if", "#endif")

        depth = 0
        for i in range(start, endif_idx):
            stripped = lines[i].strip()
            if stripped.startswith("#if"):
                depth += 1
            elif stripped == "#endif":
                depth -= 1
            elif stripped == "#else" and depth == 1:
                else_idx = i
                break

        if result:
            branch_end = else_idx if else_idx else endif_idx
            self.log_debug("Taking if branch", indent=2)
            self._process_lines(lines, start + 1, branch_end, context)
        else:
            if else_idx:
                self.log_debug("Taking else branch", indent=2)
                self._process_lines(lines, else_idx + 1, endif_idx, context)
            else:
                self.log_debug("Skipping if block", indent=2)

        return endif_idx + 1

    def _find_matching_end(
        self, lines: list[str], start: int, end: int, open_keyword: str, close_keyword: str
    ) -> int:
        """Find the matching closing keyword for a block."""
        depth = 0
        for i in range(start, end):
            stripped = lines[i].strip()
            # Check for open keyword with word boundary (followed by space or end of line)
            if stripped == open_keyword or stripped.startswith(open_keyword + " "):
                depth += 1
            elif stripped == close_keyword:
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

        def replace_expr(match):
            expr = match.group(1)
            try:
                value = self._evaluate_expression(expr, context)
            except Exception as e:
                raise self.make_error(
                    f"Error evaluating expression '{expr}': {e}",
                    rule="expr-eval-error",
                )
            if isinstance(value, bool):
                return "true" if value else "false"
            return str(value)

        return re.sub(r"\{\{(.+?)\}\}", replace_expr, line)

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

            # Merge constants into context
            eval_env = {**safe_globals, **self.constants, **context}
            result = eval(expr, {"__builtins__": {}}, eval_env)

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
        output_path = args.input.replace(".xvcl", ".vcl")
    else:
        output_path = args.input + ".vcl"

    # Set up include paths
    include_paths = args.include_paths or ["."]

    # Enable debug if verbose flag is used
    debug = args.debug or args.verbose

    error_format = args.error_format
    use_json = error_format == "json"

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
                    print(w.format_text(use_colors=True), file=sys.stderr)

        print(f"{Colors.GREEN}{Colors.BOLD}✓ Compilation complete{Colors.RESET}")

    except PreprocessorError as e:
        # Collect all error diagnostics from the compiler
        all_error_diags = [d for d in compiler.diagnostics if d.severity == "error"]
        if not all_error_diags and e.diagnostic:
            all_error_diags = [e.diagnostic]
        elif not all_error_diags:
            all_error_diags = []

        if use_json:
            diags = (
                [d.to_json() for d in all_error_diags] if all_error_diags else [{"message": str(e)}]
            )
            print(json.dumps({"diagnostics": diags}, indent=2), file=sys.stderr)
        else:
            if all_error_diags:
                for diag in all_error_diags[:10]:  # Cap at 10
                    print(diag.format_text(use_colors=True), file=sys.stderr)
                if len(all_error_diags) > 10:
                    print(
                        f"... and {len(all_error_diags) - 10} more errors",
                        file=sys.stderr,
                    )
            else:
                print(e.format_error(use_colors=True), file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        diag = Diagnostic(rule="file-not-found", severity="error", message=str(e))
        if use_json:
            print(json.dumps({"diagnostics": [diag.to_json()]}, indent=2), file=sys.stderr)
        else:
            print(f"{Colors.RED}Error:{Colors.RESET} {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        diag = Diagnostic(rule="internal-error", severity="error", message=str(e))
        if use_json:
            print(json.dumps({"diagnostics": [diag.to_json()]}, indent=2), file=sys.stderr)
        else:
            print(f"{Colors.RED}Unexpected error:{Colors.RESET} {e}", file=sys.stderr)
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
