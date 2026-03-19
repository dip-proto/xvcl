"""XVCL - Extended VCL Compiler.

A preprocessor and compiler for Fastly VCL with metaprogramming features including:
- For loops and conditionals
- Template expressions
- Constants and variables
- Inline macros
- Functions with single/tuple returns
- File includes
"""

__version__ = "2.7.0"
__all__ = ["XVCLCompiler", "Diagnostic", "__version__"]


def __getattr__(name: str):
    """Lazy imports to avoid runpy warning when running as python -m xvcl.compiler."""
    if name == "XVCLCompiler":
        from xvcl.compiler import XVCLCompiler

        return XVCLCompiler
    if name == "Diagnostic":
        from xvcl.compiler import Diagnostic

        return Diagnostic
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
