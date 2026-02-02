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
import os
import re
import sys
from dataclasses import dataclass
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


class PreprocessorError(Exception):
    """Base exception for preprocessor errors."""

    def __init__(
        self,
        message: str,
        location: Optional[SourceLocation] = None,
        context_lines: Optional[list[tuple[int, str]]] = None,
    ):
        self.message = message
        self.location = location
        self.context_lines = context_lines
        super().__init__(message)

    def format_error(self, use_colors: bool = True) -> str:
        """Format error with context for display."""
        parts = []

        # Error header
        if use_colors:
            parts.append(f"{Colors.RED}{Colors.BOLD}Error{Colors.RESET}")
        else:
            parts.append("Error")

        if self.location:
            parts.append(f" at {self.location}:")
        else:
            parts.append(":")

        parts.append(f"\n  {self.message}\n")

        # Context lines
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

        # Include tracking
        self.included_files: set[str] = set()  # Absolute paths of included files
        self.include_stack: list[str] = []  # Stack for cycle detection

        # Current source location for error reporting
        self.current_file: str = ""
        self.current_line: int = 0
        self.current_lines: list[str] = []  # All lines for context

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

    def make_error(self, message: str, line_num: Optional[int] = None) -> PreprocessorError:
        """Create a PreprocessorError with context."""
        loc = SourceLocation(self.current_file, line_num or self.current_line)
        context = self.get_context_lines(line_num or self.current_line)
        return PreprocessorError(message, loc, context)

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

        # Pass 0: join multi-line directives (arrays/expressions across lines)
        self.log_debug("Pass 0: Joining multi-line directives")
        lines = self._join_multiline_directives(lines)

        # First pass: extract constants
        self.log_debug("Pass 1: Extracting constants")
        lines = self._extract_constants(lines)

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

        self.log_debug(f"Processing complete: {len(self.output)} lines generated")
        return "\n".join(self.output)

    def _extract_constants(self, lines: list[str]) -> list[str]:
        """
        Extract #const declarations and store them.
        Returns lines with const declarations removed.
        """
        result = []
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            self.current_line = i + 1

            if stripped.startswith("#const "):
                # Parse: #const NAME TYPE = value
                match = re.match(r"#const\s+(\w+)\s+(\w+)\s*=\s*(.+)", stripped)
                if not match:
                    # Try without type: #const NAME = value (infer type)
                    match = re.match(r"#const\s+(\w+)\s*=\s*(.+)", stripped)
                    if not match:
                        raise self.make_error(f"Invalid #const syntax: {stripped}")

                    name = match.group(1)
                    const_type = None  # Infer from value
                    value_expr = match.group(2)
                else:
                    name = match.group(1)
                    const_type = match.group(2)
                    value_expr = match.group(3)

                # Evaluate the expression
                try:
                    value = self._evaluate_expression(value_expr, {})
                except Exception as e:
                    raise self.make_error(f"Error evaluating constant '{name}': {e}")

                # Type checking if type was specified
                if const_type:
                    expected_type = self._python_type_from_vcl(const_type)
                    if not isinstance(value, expected_type):
                        raise self.make_error(
                            f"Constant '{name}' type mismatch: expected {const_type}, "
                            f"got {type(value).__name__}"
                        )

                self.constants[name] = value
                self.log_debug(f"Defined constant: {name} = {value}")
                i += 1
            else:
                result.append(line)
                i += 1

        return result

    def _python_type_from_vcl(self, vcl_type: str) -> type:
        """Convert VCL type name to Python type for validation."""
        type_map = {
            "INTEGER": int,
            "STRING": str,
            "FLOAT": float,
            "BOOL": bool,
        }
        return type_map.get(vcl_type, object)

    def _process_includes(self, lines: list[str], current_file: str) -> list[str]:
        """
        Process #include directives and insert included file contents.
        Returns lines with includes expanded.
        """
        result = []
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
                    raise self.make_error(f"Invalid #include syntax: {stripped}")

                include_path = match.group(1)

                # Resolve include path
                resolved_path = self._resolve_include_path(include_path, current_file)

                if not resolved_path:
                    raise self.make_error(f"Cannot find included file: {include_path}")

                abs_path = os.path.abspath(resolved_path)

                # Check for cycles
                if abs_path in self.include_stack:
                    cycle = " -> ".join(self.include_stack + [abs_path])
                    raise self.make_error(f"Circular include detected: {cycle}")

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
                    raise self.make_error(f"Error reading included file {resolved_path}: {e}")

                # Add to included files and stack
                self.included_files.add(abs_path)
                self.include_stack.append(abs_path)

                # Save current state
                saved_file = self.current_file
                saved_line = self.current_line
                saved_lines = self.current_lines

                # Process included file
                self.current_file = resolved_path
                self.current_lines = included_content.split("\n")

                # Recursively process includes in the included file
                included_lines = self._join_multiline_directives(self.current_lines)
                included_lines = self._extract_constants(included_lines)
                included_lines = self._process_includes(included_lines, resolved_path)

                # Restore state
                self.current_file = saved_file
                self.current_line = saved_line
                self.current_lines = saved_lines

                # Pop from stack
                self.include_stack.pop()

                # Add comment marker if source maps enabled
                if self.source_maps:
                    result.append(f"// BEGIN INCLUDE: {include_path}")

                # Add included lines to result
                result.extend(included_lines)

                if self.source_maps:
                    result.append(f"// END INCLUDE: {include_path}")

                i += 1
            else:
                result.append(line)
                i += 1

        return result

    def _resolve_include_path(self, include_path: str, current_file: str) -> Optional[str]:
        """Resolve include path by searching include paths."""
        # Try relative to current file first
        if current_file and current_file != "<string>":
            current_dir = os.path.dirname(os.path.abspath(current_file))
            candidate = os.path.join(current_dir, include_path)
            if os.path.exists(candidate):
                return candidate

        # Try include paths
        for search_path in self.include_paths:
            candidate = os.path.join(search_path, include_path)
            if os.path.exists(candidate):
                return candidate

        return None

    def _extract_macros(self, lines: list[str]) -> list[str]:
        """
        Extract #inline...#endinline blocks and store them as macros.
        Returns lines with macro definitions removed.
        """
        result = []
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            self.current_line = i + 1

            if stripped.startswith("#inline "):
                # Parse: #inline name(param1, param2, ...)
                match = re.match(r"#inline\s+(\w+)\s*\(([^)]*)\)", stripped)
                if not match:
                    raise self.make_error(f"Invalid #inline syntax: {stripped}")

                name = match.group(1)
                params_str = match.group(2).strip()

                # Check for duplicate macro names
                if name in self.macros:
                    raise self.make_error(
                        f"Macro '{name}' already defined at {self.macros[name].location}"
                    )

                # Parse parameters (comma-separated)
                params = []
                if params_str:
                    params = [p.strip() for p in params_str.split(",")]

                # Find matching #endinline
                try:
                    endinline_idx = self._find_matching_end(
                        lines, i, len(lines), "#inline", "#endinline"
                    )
                except SyntaxError as e:
                    raise self.make_error(str(e))

                # Extract macro body (should be a single expression)
                body_lines = lines[i + 1 : endinline_idx]
                # Join all lines and strip whitespace
                body = " ".join(line.strip() for line in body_lines).strip()

                if not body:
                    raise self.make_error(f"Macro '{name}' has empty body")

                # Store macro
                location = SourceLocation(self.current_file, i + 1)
                self.macros[name] = Macro(name, params, body, location)

                self.log_debug(f"Defined macro: {name}({', '.join(params)})")

                # Skip past #endinline
                i = endinline_idx + 1
            else:
                result.append(line)
                i += 1

        return result

    def _extract_functions(self, lines: list[str]) -> list[str]:
        """
        Extract #def...#enddef blocks and store them as functions.
        Returns lines with function definitions removed.
        """
        result = []
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            self.current_line = i + 1

            if stripped.startswith("#def "):
                # Parse function definition
                func_def = self._parse_function_def(stripped)
                if not func_def:
                    raise self.make_error(f"Invalid #def syntax: {stripped}")

                name, params, return_type = func_def

                # Check for duplicate function names
                if name in self.functions:
                    raise self.make_error(
                        f"Function '{name}' already defined at {self.functions[name].location}"
                    )

                # Find matching #enddef
                try:
                    enddef_idx = self._find_matching_end(lines, i, len(lines), "#def", "#enddef")
                except SyntaxError as e:
                    raise self.make_error(str(e))

                # Extract function body
                body = lines[i + 1 : enddef_idx]

                # Store function
                location = SourceLocation(self.current_file, i + 1)
                self.functions[name] = Function(name, params, return_type, body, location)

                self.log_debug(
                    f"Defined function: {name}({', '.join(p[0] for p in params)}) -> {return_type}"
                )

                # Skip past #enddef
                i = enddef_idx + 1
            else:
                result.append(line)
                i += 1

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
            if param_type == "INTEGER":
                self.output.append(f"  set var.{param_name} = std.atoi({global_name});")
            elif param_type == "FLOAT":
                self.output.append(f"  set var.{param_name} = std.atof({global_name});")
            elif param_type == "BOOL":
                self.output.append(f'  set var.{param_name} = ({global_name} == "true");')
            else:
                # STRING and others
                self.output.append(f"  set var.{param_name} = {global_name};")

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
                            raise ValueError(
                                f"Function {func.name} expects {len(return_types)} return values, got {len(exprs)}"
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

    def _write_return_conversion(self, global_var: str, local_var: str, var_type: str) -> None:
        """Helper to write type conversion for return value."""
        if var_type == "INTEGER":
            self.output.append(f"  set {global_var} = std.itoa({local_var});")
        elif var_type == "FLOAT":
            self.output.append(f'  set {global_var} = "" + {local_var};')
        elif var_type == "BOOL":
            self.output.append(f"  if ({local_var}) {{")
            self.output.append(f'    set {global_var} = "true";')
            self.output.append("  } else {")
            self.output.append(f'    set {global_var} = "false";')
            self.output.append("  }")
        else:
            # STRING and others
            self.output.append(f"  set {global_var} = {local_var};")

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
            raise self.make_error(f"Invalid #let syntax: {line}")

        indent = match.group(1)
        var_name = match.group(2)
        var_type = match.group(3)
        expression = match.group(4)

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
        """
        result = []
        i = 0
        # str.startswith accepts a tuple of prefixes.
        directive_prefixes = ("#const ", "#for ", "#if ", "#let ")

        while i < len(lines):
            line = lines[i]
            stripped = line.lstrip()

            if not stripped.startswith(directive_prefixes):
                result.append(line)
                i += 1
                continue

            paren_depth, bracket_depth = self._count_unquoted_delimiters(line)
            if paren_depth == 0 and bracket_depth == 0:
                result.append(line)
                i += 1
                continue

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

        return result

    def _join_multiline_function_calls(self, lines: list[str]) -> list[str]:
        """
        Join multi-line function calls into single lines.
        Transforms:
            set var.x = func(
                arg1,
                arg2
            );
        Into:
            set var.x = func(arg1, arg2);
        """
        result = []
        i = 0

        while i < len(lines):
            line = lines[i]

            # Check if this line contains an opening parenthesis
            if "(" not in line:
                result.append(line)
                i += 1
                continue

            # Count parentheses (ignoring those in strings) to see if they balance
            paren_depth = self._count_unquoted_parens(line)

            if paren_depth == 0:
                # Balanced on this line, no joining needed
                result.append(line)
                i += 1
                continue

            # Unbalanced - need to join with following lines
            accumulated = [line]
            i += 1

            while i < len(lines) and paren_depth > 0:
                next_line = lines[i]
                accumulated.append(next_line)
                paren_depth += self._count_unquoted_parens(next_line)
                i += 1

            # Join the accumulated lines
            # Preserve the indentation of the first line
            leading_ws = len(line) - len(line.lstrip())
            indent = line[:leading_ws]

            # Join all lines, removing leading/trailing whitespace from each
            joined_parts = []
            for part in accumulated:
                stripped = part.strip()
                if stripped:
                    joined_parts.append(stripped)

            joined = " ".join(joined_parts)

            # Add back the original indentation
            result.append(indent + joined)

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
            return line

        func = self.functions[func_name]
        return_types = func.get_return_types()

        # Tuple assignment
        if len(result_vars) > 1:
            if not func.is_tuple_return():
                return line

            if len(result_vars) != len(return_types):
                raise self.make_error(
                    f"Function {func_name} returns {len(return_types)} values, "
                    f"but {len(result_vars)} variables provided"
                )

            if len(args) != len(func.params):
                raise self.make_error(
                    f"Function {func_name} expects {len(func.params)} arguments, got {len(args)}"
                )

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
            return line

        if len(args) != len(func.params):
            raise self.make_error(
                f"Function {func_name} expects {len(func.params)} arguments, got {len(args)}"
            )

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
            raise self.make_error("Too many macro expansion iterations (possible recursive macros)")

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
            try:
                expanded = macro.expand(args)
                self.log_debug(f"Expanded macro {macro_name}({args_str}) -> {expanded}", indent=3)
            except ValueError as e:
                raise self.make_error(str(e))

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
        lines = []
        if param_type == "INTEGER":
            lines.append(f"{prefix}set {global_name} = std.itoa({arg});")
        elif param_type == "FLOAT":
            lines.append(f'{prefix}set {global_name} = "" + {arg};')
        elif param_type == "BOOL":
            lines.append(f"{prefix}if ({arg}) {{")
            lines.append(f'{prefix}  set {global_name} = "true";')
            lines.append(f"{prefix}}} else {{")
            lines.append(f'{prefix}  set {global_name} = "false";')
            lines.append(f"{prefix}}}")
        else:
            lines.append(f"{prefix}set {global_name} = {arg};")
        return lines

    def _global_to_var(
        self, prefix: str, result_var: str, return_global: str, ret_type: str
    ) -> list[str]:
        """Convert global to variable with type conversion."""
        lines = []
        if ret_type == "INTEGER":
            lines.append(f"{prefix}set {result_var} = std.atoi({return_global});")
        elif ret_type == "FLOAT":
            lines.append(f"{prefix}set {result_var} = std.atof({return_global});")
        elif ret_type == "BOOL":
            lines.append(f'{prefix}set {result_var} = ({return_global} == "true");')
        else:
            lines.append(f"{prefix}set {result_var} = {return_global};")
        return lines

    def _process_for_loop(
        self, lines: list[str], start: int, end: int, context: dict[str, Any]
    ) -> int:
        """Process a #for loop with optional tuple unpacking."""
        line = lines[start].strip()

        match = re.match(r"#for\s+(\w+(?:\s*,\s*\w+)*)\s+in\s+(.+)", line)
        if not match:
            raise self.make_error(f"Invalid #for syntax: {line}")

        vars_str = match.group(1).strip()
        iterable_expr = match.group(2)

        var_names = [v.strip() for v in vars_str.split(",")] if "," in vars_str else [vars_str]

        for var_name in var_names:
            if not re.match(r"^\w+$", var_name):
                raise self.make_error(f"Invalid variable name in #for: '{var_name}'")

        try:
            iterable = self._evaluate_expression(iterable_expr, context)
        except Exception as e:
            raise self.make_error(f"Error evaluating loop expression '{iterable_expr}': {e}")

        try:
            loop_end = self._find_matching_end(lines, start, end, "#for", "#endfor")
        except SyntaxError as e:
            raise self.make_error(str(e))

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
                        f"Cannot unpack non-iterable value '{value}' into {len(var_names)} variables"
                    )

                if len(values) != len(var_names):
                    raise self.make_error(
                        f"Cannot unpack {len(values)} values into {len(var_names)} variables "
                        f"({', '.join(var_names)})"
                    )

                for var_name, val in zip(var_names, values):
                    loop_context[var_name] = val

                self.log_debug(
                    f"Iteration {idx}: {', '.join(f'{n}={v}' for n, v in zip(var_names, values))}",
                    indent=3,
                )

            self._process_lines(lines, start + 1, loop_end, loop_context)

        return loop_end + 1

    def _process_if(self, lines: list[str], start: int, end: int, context: dict[str, Any]) -> int:
        """Process a #if conditional."""
        line = lines[start].strip()

        match = re.match(r"#if\s+(.+)", line)
        if not match:
            raise self.make_error(f"Invalid #if syntax: {line}")

        condition = match.group(1)

        try:
            result = self._evaluate_expression(condition, context)
        except Exception as e:
            raise self.make_error(f"Error evaluating condition '{condition}': {e}")

        self.log_debug(f"Condition '{condition}' evaluated to {result}", indent=2)

        else_idx = None
        try:
            endif_idx = self._find_matching_end(lines, start, end, "#if", "#endif")
        except SyntaxError as e:
            raise self.make_error(str(e))

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

        raise SyntaxError(f"No matching {close_keyword} for {open_keyword} at line {start + 1}")

    def _substitute_expressions(self, line: str, context: dict[str, Any]) -> str:
        """Substitute {{expression}} in a line."""

        def replace_expr(match):
            expr = match.group(1)
            try:
                value = self._evaluate_expression(expr, context)
            except Exception as e:
                raise self.make_error(f"Error evaluating expression '{expr}': {e}")
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

    try:
        compiler = XVCLCompiler(
            include_paths=include_paths, debug=debug, source_maps=args.source_maps
        )
        compiler.process_file(args.input, output_path)

        print(f"{Colors.GREEN}{Colors.BOLD}✓ Compilation complete{Colors.RESET}")

    except PreprocessorError as e:
        print(e.format_error(use_colors=True), file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"{Colors.RED}Error:{Colors.RESET} {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"{Colors.RED}Unexpected error:{Colors.RESET} {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
