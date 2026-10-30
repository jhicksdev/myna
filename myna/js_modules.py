"""Compile a Myna program's relative-import graph to Node-runnable ES modules.

`myna run -t js` uses this to lay out every reachable `.myna` module as a sibling `.mjs`
file in a temporary directory, so Node's own ES module resolution handles the graph.
`myna run -t ts` passes `compile_module_ts` and `.mts`, which is also what its
relative-import specifiers name. `myna compile` compiles one file at a time and is not
involved here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import myna.ast_nodes as ast
from myna.backends.js_gen import compile_module_js
from myna.backends.ts_gen import compile_module_ts
from myna.lexer import LexError
from myna.modules import ModuleError
from myna.parser import ParseError, parse
from myna.targets import TargetError


@dataclass
class JSModule:
    path: Path
    code: str


def _parse_module(path: Path) -> ast.Module:
    source = path.read_text(encoding="utf-8")
    try:
        return parse(source)
    except LexError as exc:
        raise LexError(exc.msg, exc.line, exc.col, filename=str(path)) from exc
    except ParseError as exc:
        raise ParseError(exc.msg, exc.token, filename=str(path)) from exc


def _compile_module(
    path: Path,
    *,
    module_ext: str,
    import_base: Path | None = None,
    compiler=compile_module_js,
) -> tuple[str, list[Path]]:
    tree = _parse_module(path)
    try:
        return compiler(
            tree,
            source_path=path,
            module_ext=module_ext,
            import_base=import_base,
        )
    except TargetError as exc:
        raise TargetError(f"{path}: {exc}") from exc
    except ModuleError as exc:
        raise ModuleError(f"{path}: {exc}") from exc


def collect_js_modules(
    entry: Path | str,
    *,
    module_root: Path | str | None = None,
    module_ext: str = ".mjs",
    compiler=compile_module_js,
) -> list[JSModule]:
    """Compile ``entry`` and every module reachable through relative imports.

    ``compiler`` selects the target: `compile_module_js` for JavaScript (the default) or
    `compile_module_ts` for TypeScript, whose output extension is passed as ``module_ext``.
    """
    entry_path = Path(entry).resolve()
    root = Path(module_root).resolve() if module_root is not None else None
    pending: list[tuple[Path, Path | None]] = [(entry_path, root)]
    seen: dict[Path, JSModule] = {}
    order: list[Path] = []

    while pending:
        path, import_base = pending.pop(0)
        if path in seen:
            continue
        code, dependencies = _compile_module(
            path, module_ext=module_ext, import_base=import_base, compiler=compiler
        )
        seen[path] = JSModule(path, code)
        order.append(path)
        for dependency in dependencies:
            if dependency not in seen:
                pending.append((dependency, None))

    return [seen[path] for path in order]


def write_js_tree(
    modules: list[JSModule],
    *,
    output_root: Path,
    module_ext: str = ".mjs",
) -> Path:
    """Write compiled modules under ``output_root``, mirroring their source layout.

    The layout base is the deepest directory that contains every module, so specifiers
    computed from the source paths stay valid regardless of where the entry lives
    relative to ``--module-root``. Returns the entry module's generated path.
    """
    if not modules:
        raise ModuleError("nothing to run: no Myna modules were found")
    try:
        source_root = Path(
            os.path.commonpath([str(module.path.parent) for module in modules])
        )
    except ValueError as exc:  # Windows paths on different drives
        raise ModuleError(
            "cannot mirror the module tree: sources are on different drives"
        ) from exc

    entry_output: Path | None = None
    for module in modules:
        output = output_root.joinpath(module.path.relative_to(source_root)).with_suffix(
            module_ext
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(module.code, encoding="utf-8")
        if entry_output is None:
            entry_output = output
    return entry_output
