"""Checks that need a whole module rather than a single node.

These run before code generation so every target agrees: a program that passes the check
compiles the same way for Python, JavaScript, and TypeScript.
"""

from __future__ import annotations

from dataclasses import fields

import myna.ast_nodes as ast


class CompileError(Exception):
    """A program-level error found before code generation."""

    def __init__(
        self,
        msg: str,
        *,
        line: int | None = None,
        col: int | None = None,
        filename: str | None = None,
    ):
        self.msg = msg
        self.line = line
        self.col = col
        self.filename = filename
        if line is None:
            super().__init__(f"CompileError: {msg}")
        else:
            location = f"{filename}:{line}:{col}" if filename else f"{line}:{col}"
            super().__init__(f"CompileError at {location}: {msg}")


def iter_nodes(node) -> "list[ast.Node]":
    """Yield every AST node reachable from ``node`` in source order."""
    found: list[ast.Node] = []

    def walk(current) -> None:
        if isinstance(current, ast.Node):
            found.append(current)
            for field in fields(current):
                walk(getattr(current, field.name))
        elif isinstance(current, (list, tuple)):
            for item in current:
                walk(item)

    walk(node)
    return found


def _declares_kwargs(fn: ast.FuncDef) -> bool:
    return any(param.kind == "kwarg" for param in fn.params)


def _kwargs_callables(mod: ast.Module) -> dict[str, str]:
    """Map same-module callable names that declare `**kwargs` to a display name."""
    names: dict[str, str] = {}
    for node in iter_nodes(mod):
        if isinstance(node, ast.FuncDef):
            if _declares_kwargs(node):
                names[node.name] = f"{node.name}()"
            if node.method_kind == "init" and _declares_kwargs(node):
                names[node.name] = f"{node.name}()"
        elif isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, ast.FuncDef) and stmt.method_kind == "init" and _declares_kwargs(stmt):
                    names[node.name] = f"{node.name}.@init()"
    return names


def check_call_dict_shorthand(mod: ast.Module) -> None:
    """Reject `f(1, k: v)` when `f` is a known callable that declares `**kwargs`.

    A trailing `k: v` argument is a dict literal (see `SPEC.md` §8), which silently
    shadowed the `**kwargs` reading every Python author has. The rule only fires when the
    callee is declared in this module, so imported callables keep the documented
    behaviour (GAPS.md G3).
    """
    callables = _kwargs_callables(mod)
    if not callables:
        return
    for node in iter_nodes(mod):
        if not isinstance(node, ast.Call) or not getattr(node, "dict_shorthand", False):
            continue
        if not isinstance(node.func, ast.Ident):
            continue
        display = callables.get(node.func.name)
        if display is None:
            continue
        example = "k"
        tail = node.args[-1] if node.args else None
        if isinstance(tail, ast.DictExpr) and tail.keys and isinstance(tail.keys[0], ast.Literal):
            example = str(tail.keys[0].value)
        name = node.func.name
        raise CompileError(
            f"{display} declares **kwargs, but a trailing 'key: value' argument is a "
            f"dict literal; write keyword arguments as {name}(..., {example}=...) or "
            f"pass the dict explicitly as {name}(..., {{{example}: ...}})",
            line=node.line,
            col=node.col,
        )
