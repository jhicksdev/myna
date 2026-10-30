"""Runtime module resolution for multi-file Myna programs.

`myna run path/to/main.myna` executes the entry file inside a synthetic package whose
search path is the entry file's directory. That gives relative imports a package context:

    <.util:{slug}          # -> <entry dir>/util.myna
    <.pkg:{name}           # -> <entry dir>/pkg/__init__.myna (or a namespace directory)
    <.pkg.helper:{parse}   # -> <entry dir>/pkg/helper.myna

Imported modules are compiled from `.myna` source on first import and cached in
`sys.modules` by the normal import machinery. Absolute imports (`<json`, `<mypkg>alias`)
keep their usual Python meaning, so stdlib and installed Python packages still work.
"""

from __future__ import annotations

import ast as py_ast
import importlib.abc
import importlib.machinery
import importlib.util
import sys
from pathlib import Path

from myna.backends.python_gen import compile_to_python
from myna.lexer import LexError, TT, Token
from myna.modules import clamp_relative_levels
from myna.parser import ParseError, parse
from myna.sourcemap import relabel, split_markers


def compile_myna_source(
    source: str, path: Path, *, relative_ceiling: int | None = None
) -> str:
    """Compile Myna source, attributing lex/parse errors to the originating file.

    ``relative_ceiling`` caps relative-import levels before generation, which the Python
    entry needs when it runs under ``--module-root`` (see `clamp_relative_levels`).
    """
    return _generate_python(source, path, relative_ceiling=relative_ceiling)


def _generate_python(
    source: str, path: Path, *, relative_ceiling: int | None = None, sourcemap: bool = False
) -> str:
    try:
        tree = parse(source)
        if relative_ceiling is not None:
            clamp_relative_levels(tree, relative_ceiling)
        return compile_to_python(tree, sourcemap=sourcemap)
    except LexError as exc:
        raise LexError(exc.msg, exc.line, exc.col, filename=str(path)) from exc
    except ParseError as exc:
        raise ParseError(exc.msg, exc.token, filename=str(path)) from exc


def compile_myna_code(
    source: str, path: Path, *, relative_ceiling: int | None = None
):
    """Compile Myna source to a code object whose line numbers are Myna lines.

    Tracebacks then point at the `.myna` file, the right line, and the right excerpt
    (GAPS.md G11).
    """
    generated = _generate_python(
        source, path, relative_ceiling=relative_ceiling, sourcemap=True
    )
    text, line_map = split_markers(generated)
    try:
        py_tree = py_ast.parse(text)
    except SyntaxError as exc:  # a generator bug; surface the generated line
        raise ParseError(
            f"generated Python is not valid: {exc.msg}", Token(TT.EOF, "", 1, 1, "")
        ) from exc
    relabel(py_tree, line_map)
    return compile(py_tree, str(path), "exec")


class MynaModuleFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Find and execute `.myna` modules inside one synthetic package."""

    def __init__(self, package: str, root: Path) -> None:
        self.package = package
        self.root = root

    def _relative_parts(self, fullname: str) -> list[str] | None:
        if fullname == self.package:
            return None
        prefix = self.package + "."
        if not fullname.startswith(prefix):
            return None
        return fullname[len(prefix):].split(".")

    def find_spec(self, fullname, path=None, target=None):
        parts = self._relative_parts(fullname)
        if parts is None:
            return None
        base = self.root.joinpath(*parts)
        module_path = base.with_suffix(".myna")
        if module_path.is_file():
            return importlib.util.spec_from_file_location(fullname, module_path, loader=self)
        if base.is_dir():
            init_path = base / "__init__.myna"
            if init_path.is_file():
                return importlib.util.spec_from_file_location(
                    fullname,
                    init_path,
                    loader=self,
                    submodule_search_locations=[str(base)],
                )
            # A directory without `__init__.myna` is a namespace subpackage.
            spec = importlib.machinery.ModuleSpec(fullname, None, is_package=True)
            spec.submodule_search_locations = [str(base)]
            return spec
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module) -> None:
        source_path = Path(module.__spec__.origin)
        source = source_path.read_text(encoding="utf-8")
        code = compile_myna_code(source, source_path)
        module.__file__ = str(source_path)
        exec(code, module.__dict__)


def install(package: str, root: Path) -> MynaModuleFinder:
    """Register a finder for `package` and return it so the caller can unregister."""
    finder = MynaModuleFinder(package, root)
    sys.meta_path.insert(0, finder)
    return finder
