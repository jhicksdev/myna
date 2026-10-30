"""Myna: An AI-friendly, ultra-dense symbolic language that transpiles to Python, JavaScript, and TypeScript."""

from myna.lexer import tokenize, LexError
from myna.parser import parse, ParseError
from myna.backends.python_gen import compile_to_python
from myna.backends.js_gen import compile_to_js
from myna.backends.ts_gen import compile_to_ts
from myna.frontends.python_decompile import DecompileError, decompile_python
from myna.targets import TargetError

__version__ = "0.6.1"
# The language version is the package major.minor; derive it so the two cannot drift.
LANGUAGE_VERSION = ".".join(__version__.split(".")[:2])


def myna_to_python(source: str, *, sourcemap: bool = False) -> str:
    """Compile Myna source code to Python 3.12+ source code.

    ``sourcemap=True`` prefixes every emitted statement with a ``# myna:LINE`` marker so
    a caller can build a generated-line -> Myna-line table (`myna.sourcemap`).
    """
    ast_mod = parse(source)
    return compile_to_python(ast_mod, sourcemap=sourcemap)


def myna_to_js(
    source: str,
    *,
    source_path: str | None = None,
    module_ext: str = ".js",
    import_base: str | None = None,
) -> str:
    """Compile Myna source code to JavaScript (ES2024+) source code.

    ``source_path`` is the file the source came from; relative imports are resolved
    from it and emitted as relative ES module specifiers ending in ``module_ext``.
    Without it, relative imports raise :class:`TargetError`.
    """
    ast_mod = parse(source)
    return compile_to_js(
        ast_mod,
        source_path=source_path,
        module_ext=module_ext,
        import_base=import_base,
    )


def myna_to_ts(
    source: str,
    *,
    source_path: str | None = None,
    module_ext: str = ".js",
    import_base: str | None = None,
) -> str:
    """Compile Myna source code to TypeScript source code.

    TypeScript is a typed projection of the JavaScript target: the runtime behaviour
    and the portable-core boundary are identical to :func:`myna_to_js`, and type
    annotations are erased.  ``module_ext`` is the extension of the JavaScript files
    that relative-import specifiers point at (``.js``, or ``.mjs`` for ``.mts`` output).
    """
    ast_mod = parse(source)
    return compile_to_ts(
        ast_mod,
        source_path=source_path,
        module_ext=module_ext,
        import_base=import_base,
    )


def python_to_myna(source: str, compact: bool = True, minify_locals: bool = False) -> str:
    """Decompile/compress Python source code into Myna source code."""
    return decompile_python(source, compact=compact, minify_locals=minify_locals)


__all__ = [
    "tokenize",
    "parse",
    "compile_to_python",
    "compile_to_js",
    "compile_to_ts",
    "decompile_python",
    "myna_to_python",
    "myna_to_js",
    "myna_to_ts",
    "python_to_myna",
    "LexError",
    "ParseError",
    "DecompileError",
    "TargetError",
    "__version__",
    "LANGUAGE_VERSION",
]
