"""XVCL - Extended VCL Compiler.

A preprocessor and compiler for Fastly VCL with metaprogramming features including:
- For loops and conditionals
- Template expressions
- Constants and variables
- Inline macros
- Functions with single/tuple returns
- File includes
"""

__version__ = "2.5.0"
__all__ = ["XVCLCompiler", "__version__"]

from xvcl.compiler import XVCLCompiler
