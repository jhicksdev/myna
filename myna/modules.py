"""Filesystem resolution for relative Myna imports.

Relative imports are resolved against the importing module's package directory, which is
its parent directory for both plain modules and ``__init__.myna`` packages::

    <.util:{f}          # <module dir>/util.myna
    <.pkg.helper:{f}    # <module dir>/pkg/helper.myna
    <..util:{f}         # <parent of module dir>/util.myna

The module *root* only overrides this for a program's entry file, so ``tests/run.myna``
with ``--module-root .`` can reach a sibling ``src/`` tree (see ``GAPS.md`` G3).

This module is shared by the JavaScript and TypeScript backends (which turn a relative
import into a relative ES module specifier and need to know whether a package's symbol
comes from its ``__init__`` or a submodule, and whether it is a type alias) and
``myna run -t js``. The Python loader and ``myna bundle`` resolve imports through the
same conventions but keep their own import-machinery integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import myna.ast_nodes as ast


class ModuleError(Exception):
    """Raised when a relative import cannot be resolved on disk."""


@dataclass(frozen=True)
class FoundModule:
    """A `.myna` module, package, or namespace directory on disk."""

    path: Path
    is_package: bool = False
    is_namespace: bool = False

    @property
    def directory(self) -> Path:
        """The directory that holds this module's submodules."""
        return self.path if self.is_namespace else self.path.parent


@dataclass(frozen=True)
class ImportBinding:
    """One name bound by a relative ``from`` import.

    ``imported`` is ``None`` when the local name is bound to the imported module object
    itself (a namespace import), which happens for ``from .pkg import submodule``.
    """

    path: Path
    local: str
    imported: str | None


def find_module(base: Path, parts: list[str]) -> FoundModule | None:
    """Find the module named by ``parts`` under ``base``, or return ``None``."""
    if not parts:
        return None
    candidate = base.joinpath(*parts)
    module_path = candidate.with_suffix(".myna")
    if module_path.is_file():
        return FoundModule(module_path)
    if candidate.is_dir():
        init_path = candidate / "__init__.myna"
        if init_path.is_file():
            return FoundModule(init_path, is_package=True)
        return FoundModule(candidate, is_package=True, is_namespace=True)
    return None


def module_base(current_path: Path, level: int, root: Path | None = None) -> Path:
    """Return the directory a relative import of ``level`` resolves against.

    ``root`` replaces the importing module's directory for a program's entry file. A
    relative import may not climb above an explicitly supplied root.
    """
    if level < 1:
        raise ValueError("module_base() requires a relative import level >= 1")
    base = root if root is not None else current_path.parent
    for _ in range(level - 1):
        parent = base.parent
        if parent == base:
            raise ModuleError("relative import goes above the filesystem root")
        if root is not None and base == root:
            raise ModuleError("relative import goes above the module root")
        base = parent
    return base


def _current_package(current_path: Path, root: Path | None = None) -> FoundModule:
    base = root if root is not None else current_path.parent
    init_path = base / "__init__.myna"
    if init_path.is_file():
        return FoundModule(init_path, is_package=True)
    return FoundModule(base, is_package=True, is_namespace=True)


def resolve_module_import(
    current_path: Path,
    level: int,
    module: str,
    root: Path | None = None,
) -> FoundModule:
    """Resolve ``import .module`` (a module-object binding) to a file on disk."""
    if level == 0:
        raise ValueError("absolute imports have no filesystem target")
    base = module_base(current_path, level, root)
    parts = module.split(".") if module else []
    found = find_module(base, parts) if parts else _current_package(current_path, root)
    if found is None:
        dotted = "." * level + module
        raise ModuleError(
            f"cannot resolve relative import {dotted!r} "
            f"(looked for {base.joinpath(*parts).with_suffix('.myna')})"
        )
    if found.is_namespace:
        raise ModuleError(
            f"cannot import namespace package {'.' * level + module!r} as a module"
        )
    return found


def resolve_from_import(
    current_path: Path,
    node: ast.ImportFromStmt,
    root: Path | None = None,
) -> list[ImportBinding]:
    """Resolve one relative ``from`` import to the files that provide its names."""
    if node.level == 0:
        raise ValueError("absolute imports have no filesystem target")
    base = module_base(current_path, node.level, root)
    parts = node.module.split(".") if node.module else []
    if parts:
        target = find_module(base, parts)
        if target is None:
            dotted = "." * node.level + (node.module or "")
            raise ModuleError(
                f"cannot resolve relative import {dotted!r} "
                f"(looked for {base.joinpath(*parts).with_suffix('.myna')})"
            )
    else:
        target = _current_package(current_path, root)

    bindings: list[ImportBinding] = []
    for alias in node.names:
        if alias.name == "*":
            raise ModuleError(
                "star imports are not supported for relative imports by this target"
            )
        local = alias.asname or alias.name
        if not target.is_package:
            bindings.append(ImportBinding(target.path, local, alias.name))
            continue
        if target.is_namespace:
            submodule = find_module(target.directory, [alias.name])
            if submodule is None or submodule.is_namespace:
                raise ModuleError(
                    f"cannot resolve name {alias.name!r} in relative import "
                    f"{'.' * node.level}{node.module or ''!s}"
                )
            bindings.append(ImportBinding(submodule.path, local, None))
            continue
        # A package `__init__` attribute wins over a same-named submodule, matching
        # Python (`from .pkg import name` prefers pkg/__init__'s binding).
        if alias.name in _top_level_names(target.path):
            bindings.append(ImportBinding(target.path, local, alias.name))
            continue
        submodule = find_module(target.directory, [alias.name])
        if submodule is not None and not submodule.is_namespace:
            bindings.append(ImportBinding(submodule.path, local, None))
            continue
        # Neither: let the target module report its own missing export.
        bindings.append(ImportBinding(target.path, local, alias.name))
    return bindings


def module_bindings(mod: ast.Module) -> list[str]:
    """Names a module defines at top level, in declaration order.

    This is the set of names another module can import from it (Python's module
    semantics), and therefore the set the JavaScript backend exports.
    """
    names: list[str] = []

    def add(name: str) -> None:
        if name and name != "_" and name not in names:
            names.append(name)

    for stmt in mod.body:
        if isinstance(stmt, (ast.FuncDef, ast.ClassDef)):
            add(stmt.name)
        elif isinstance(stmt, ast.AssignStmt):
            for target in stmt.targets:
                for name in _target_names(target):
                    add(name)
        elif isinstance(stmt, (ast.ImportStmt, ast.ImportFromStmt)):
            for alias in stmt.names:
                if alias.name == "*":
                    continue
                add(alias.asname or _import_local(alias.name))
    return names


def _import_local(name: str) -> str:
    return name.split(".")[-1]


def _target_names(target: ast.Expr) -> list[str]:
    if isinstance(target, ast.Ident):
        return [target.name]
    if isinstance(target, ast.TupleExpr):
        return [name for element in target.elts for name in _target_names(element)]
    return []


@lru_cache(maxsize=None)
def module_classes(path: Path) -> frozenset[str]:
    """Class names a module defines at top level for the JavaScript target."""
    from myna.targets import expand_target_blocks

    tree = _parse_file(Path(path))
    expanded = expand_target_blocks(tree, "js")
    return frozenset(
        stmt.name for stmt in expanded.body if isinstance(stmt, ast.ClassDef)
    )


@lru_cache(maxsize=None)
def module_type_aliases(path: Path) -> frozenset[str]:
    """Type alias names a module defines at top level for the TypeScript target.

    The TypeScript backend needs this to emit ``import type`` for a name that has no
    runtime binding.  Target blocks are expanded with the ``js`` contract because
    TypeScript is a typed projection of the JavaScript target.
    """
    from myna.targets import expand_target_blocks

    tree = _parse_file(Path(path))
    expanded = expand_target_blocks(tree, "js")
    return frozenset(
        stmt.name for stmt in expanded.body if isinstance(stmt, ast.TypeAliasStmt)
    )


@lru_cache(maxsize=None)
def _top_level_names(path: Path) -> frozenset[str]:
    """Top-level binding names of a module file, used for package-attribute imports."""
    return frozenset(module_bindings(_parse_file(Path(path))))


def _parse_file(path: Path):
    """Parse a module file, attributing lex/parse errors to its path."""
    # Imported lazily so `myna.modules` stays importable from the lexer/parser layer.
    from myna.lexer import LexError
    from myna.parser import ParseError, parse

    source = path.read_text(encoding="utf-8")
    try:
        return parse(source)
    except LexError as exc:
        raise LexError(exc.msg, exc.line, exc.col, filename=str(path)) from exc
    except ParseError as exc:
        raise ParseError(exc.msg, exc.token, filename=str(path)) from exc
