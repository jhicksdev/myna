"""Bundle a multi-file Myna program into one standalone Python file.

`myna bundle src/main.myna -o app.py` resolves the relative-import graph, compiles every
module to Python, and embeds the results in a single artifact. Running the artifact needs
only the Python standard library — not the `myna` package.

The generated file installs the same kind of scoped finder that `myna run` uses, so module
semantics (lazy imports, package `__init__`, namespace directories) are preserved.
Absolute imports are left untouched and must be installed in the target environment.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Iterator

import myna.ast_nodes as ast
from myna.backends.python_gen import compile_to_python
from myna.lexer import LexError
from myna.parser import ParseError, parse
from myna.targets import expand_target_blocks


class BundleError(Exception):
    """Raised when a relative import cannot be resolved while bundling."""


@dataclass
class BundleModule:
    name: str
    source_path: Path
    code: str
    is_package: bool = False


@dataclass
class Bundle:
    code: str
    modules: list[BundleModule]
    namespaces: set[str]


def _walk_nodes(node) -> Iterator[ast.Node]:
    if isinstance(node, ast.Node):
        yield node
        for field in fields(node):
            yield from _walk_nodes(getattr(node, field.name))
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from _walk_nodes(item)


def _parse_module(source_path: Path) -> ast.Module:
    source = source_path.read_text(encoding="utf-8")
    try:
        return parse(source)
    except LexError as exc:
        raise LexError(exc.msg, exc.line, exc.col, filename=str(source_path)) from exc
    except ParseError as exc:
        raise ParseError(exc.msg, exc.token, filename=str(source_path)) from exc


def _find_module(root: Path, parts: list[str]) -> tuple[str, Path, bool] | None:
    """Return (kind, path, is_package) for a dotted module path under `root`."""
    if not parts:
        return None
    base = root.joinpath(*parts)
    module_path = base.with_suffix(".myna")
    if module_path.is_file():
        return "module", module_path, False
    if base.is_dir():
        init_path = base / "__init__.myna"
        if init_path.is_file():
            return "module", init_path, True
        return "namespace", base, True
    return None


def _package_parts(module_name: str, is_package: bool) -> list[str]:
    parts = module_name.split(".") if module_name else []
    return parts if is_package else parts[:-1]


def _resolve_import(
    current: str, is_package: bool, node: ast.ImportFromStmt
) -> tuple[list[str], list[list[str]]]:
    """Resolve one relative import to its module path plus optional submodule candidates."""
    package = _package_parts(current, is_package)
    keep = len(package) - (node.level - 1)
    if keep < 0:
        raise BundleError(
            f"relative import at line {node.line} goes above the bundle root"
        )
    base = package[:keep]
    if node.module:
        base = base + node.module.split(".")
    # `from .pkg import helper` may import `pkg/helper.myna` as a submodule.
    extras = [base + [alias.name] for alias in node.names if alias.name != "*"]
    return base, extras


def _load_module(entry: Path) -> Bundle:
    root = entry.resolve().parent
    modules: dict[str, BundleModule] = {}
    namespaces: set[str] = set()
    pending: list[tuple[Path, str, bool]] = [(entry.resolve(), "", False)]
    seen: set[Path] = set()

    while pending:
        source_path, name, is_package = pending.pop()
        if source_path in seen:
            continue
        seen.add(source_path)

        tree = _parse_module(source_path)
        code = compile_to_python(tree)
        if name:
            modules[name] = BundleModule(name, source_path, code, is_package)

        expanded = expand_target_blocks(tree, "py")
        for node in _walk_nodes(expanded):
            if not isinstance(node, ast.ImportFromStmt) or node.level == 0:
                continue
            try:
                base, extras = _resolve_import(name, is_package, node)
            except BundleError as exc:
                raise BundleError(f"{source_path}: {exc}") from exc
            for index, parts in enumerate([base, *extras]):
                if not parts:
                    continue  # `from . import name` targets the bundle-root package
                found = _find_module(root, parts)
                if found is None:
                    if index > 0:
                        continue  # an imported symbol, not a submodule
                    dotted = ".".join(parts)
                    display = "." * node.level + (node.module or "")
                    raise BundleError(
                        f"{source_path}:{node.line}: cannot resolve relative import "
                        f"{display!r} (looked for {dotted or 'the package root'})"
                    )
                kind, target_path, target_is_package = found
                module_name = ".".join(parts)

                # Ensure every parent directory is importable too.
                for depth in range(1, len(parts)):
                    prefix_parts = parts[:depth]
                    prefix = ".".join(prefix_parts)
                    if prefix in modules or prefix in namespaces:
                        continue
                    parent = _find_module(root, prefix_parts)
                    if parent is None:
                        continue  # parts are relative to an existing module file
                    parent_kind, parent_path, parent_is_package = parent
                    if parent_kind == "namespace":
                        namespaces.add(prefix)
                    else:
                        pending.append((parent_path, prefix, parent_is_package))

                if kind == "namespace":
                    namespaces.add(module_name)
                else:
                    pending.append((target_path, module_name, target_is_package))

    ordered = sorted(modules.values(), key=lambda m: m.name)
    return Bundle(_render(entry.resolve(), ordered, namespaces), ordered, namespaces)


def bundle(entry: Path) -> Bundle:
    """Compile `entry` and its relative `.myna` imports into one standalone script."""
    return _load_module(entry)


def _render(entry: Path, modules: list[BundleModule], namespaces: set[str]) -> str:
    # The entry is compiled separately so `myna bundle` fails early on its errors, and so
    # `__name__ == "__main__"` keeps working in the artifact.
    entry_tree = _parse_module(entry)
    entry_code = compile_to_python(entry_tree)

    module_lines = [
        f"    {m.name!r}: ({str(m.source_path)!r}, {m.is_package!r}, {m.code!r}),"
        for m in modules
    ]
    modules_block = "\n".join(module_lines) if module_lines else ""

    return f'''#!/usr/bin/env python3
# Generated by `myna bundle` from {entry}. Do not edit by hand.
# All relative Myna imports are embedded below and compiled lazily at runtime.
from __future__ import annotations
import importlib.abc
import importlib.machinery
import importlib.util
import sys
import types

_PACKAGE = "_myna_bundle"
_ENTRY = ({str(entry)!r}, {entry_code!r})
_MODULES = {{
{modules_block}
}}
_NAMESPACES = {sorted(namespaces)!r}


class _BundleFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def _relative(self, fullname):
        prefix = _PACKAGE + "."
        if not fullname.startswith(prefix):
            return None
        return fullname[len(prefix):]

    def find_spec(self, fullname, path=None, target=None):
        relative = self._relative(fullname)
        if relative is None:
            return None
        if relative in _MODULES:
            origin, is_package, _code = _MODULES[relative]
            spec = importlib.util.spec_from_loader(
                fullname, self, origin=origin, is_package=is_package
            )
            if is_package:
                spec.submodule_search_locations = []
            return spec
        if relative in _NAMESPACES:
            spec = importlib.machinery.ModuleSpec(fullname, None, is_package=True)
            spec.submodule_search_locations = []
            return spec
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        origin, _is_package, code = _MODULES[self._relative(module.__name__)]
        module.__file__ = origin
        exec(compile(code, origin, "exec"), module.__dict__)


def _main():
    package = types.ModuleType(_PACKAGE)
    package.__path__ = []
    package.__package__ = _PACKAGE
    sys.modules[_PACKAGE] = package
    sys.meta_path.insert(0, _BundleFinder())
    entry_path, entry_code = _ENTRY
    globs = {{"__name__": "__main__", "__file__": entry_path, "__package__": _PACKAGE}}
    exec(compile(entry_code, entry_path, "exec"), globs)


if __name__ == "__main__":
    _main()
'''
