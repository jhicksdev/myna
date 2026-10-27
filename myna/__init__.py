"""Myna: An AI-friendly, ultra-dense symbolic language that transpiles to Python and JavaScript."""

from myna.lexer import tokenize, LexError
from myna.parser import parse, ParseError
from myna.backends.python_gen import compile_to_python
from myna.backends.js_gen import compile_to_js
from myna.frontends.python_decompile import DecompileError, decompile_python
from myna.targets import TargetError

__version__ = "0.4.2"
# The language version is the package major.minor; derive it so the two cannot drift.
LANGUAGE_VERSION = ".".join(__version__.split(".")[:2])


def myna_to_python(source: str) -> str:
    """Compile Myna source code to Python 3.12+ source code."""
    ast_mod = parse(source)
    return compile_to_python(ast_mod)


def myna_to_js(source: str) -> str:
    """Compile Myna source code to JavaScript (ES2024+) source code."""
    ast_mod = parse(source)
    return compile_to_js(ast_mod)


def python_to_myna(source: str, compact: bool = True, minify_locals: bool = False) -> str:
    """Decompile/compress Python source code into Myna source code."""
    return decompile_python(source, compact=compact, minify_locals=minify_locals)


__all__ = [
    "tokenize",
    "parse",
    "compile_to_python",
    "compile_to_js",
    "decompile_python",
    "myna_to_python",
    "myna_to_js",
    "python_to_myna",
    "LexError",
    "ParseError",
    "DecompileError",
    "TargetError",
    "__version__",
    "LANGUAGE_VERSION",
]
