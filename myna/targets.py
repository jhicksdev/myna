"""Target declarations and compile-time target blocks."""

from __future__ import annotations

import myna.ast_nodes as ast

VALID_TARGETS = frozenset({"py", "js"})


class TargetError(Exception):
    """Raised when a module is compiled for a target it does not support."""


def enforce_module_target(mod: ast.Module, target: str) -> None:
    """Reject targets excluded by a module-level `@target(...)` declaration."""
    if mod.targets is not None and target not in mod.targets:
        declared = ", ".join(sorted(mod.targets))
        raise TargetError(f"module declares @target({declared}); target '{target}' is not supported")


def expand_target_blocks(mod: ast.Module, target: str) -> ast.Module:
    """Return a Module with only the target blocks that match `target`."""
    return ast.Module(
        body=_expand_stmts(mod.body, target),
        targets=mod.targets,
        line=mod.line,
        col=mod.col,
    )


def _expand_stmts(stmts: list[ast.Stmt], target: str) -> list[ast.Stmt]:
    expanded: list[ast.Stmt] = []
    for stmt in stmts:
        if isinstance(stmt, ast.TargetBlock):
            if target in stmt.targets:
                expanded.extend(_expand_stmts(stmt.body, target))
        else:
            expanded.append(stmt)
    return expanded
