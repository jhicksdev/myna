"""Target declarations and compile-time target blocks."""

from __future__ import annotations

import myna.ast_nodes as ast

VALID_TARGETS = frozenset({"py", "js"})


class TargetError(Exception):
    """Raised when a module is compiled for a target it does not support."""


def enforce_module_target(
    mod: ast.Module, target: str, *, label: str | None = None
) -> None:
    """Reject targets excluded by a module-level `@target(...)` declaration.

    ``label`` is the user-facing target name when one backend serves more than one
    output format (the TypeScript target uses the ``js`` contract but reports ``ts``).
    """
    declared_targets = mod.targets if mod.targets is not None else {"py"}
    if target not in declared_targets:
        declared = ", ".join(sorted(declared_targets))
        shown = label or target
        raise TargetError(
            f"module declares @target({declared}); target '{shown}' is not supported"
        )


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
