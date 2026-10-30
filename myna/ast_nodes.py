"""Language-agnostic AST nodes for the Myna programming language."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Union


@dataclass
class Node:
    line: int = 0
    col: int = 0


# ============================================================================
# Type Annotations
# ============================================================================

@dataclass
class TypeNode(Node):
    pass


@dataclass
class SimpleType(TypeNode):
    name: str = ""
    optional: bool = False


@dataclass
class ListType(TypeNode):
    elem: TypeNode = field(default_factory=TypeNode)
    optional: bool = False


@dataclass
class DictType(TypeNode):
    key: TypeNode = field(default_factory=TypeNode)
    value: TypeNode = field(default_factory=TypeNode)
    optional: bool = False


@dataclass
class SetType(TypeNode):
    elem: TypeNode = field(default_factory=TypeNode)
    optional: bool = False


@dataclass
class TupleType(TypeNode):
    elems: list[TypeNode] = field(default_factory=list)
    optional: bool = False


@dataclass
class GenericType(TypeNode):
    base: str = ""
    args: list[TypeNode] = field(default_factory=list)
    optional: bool = False


@dataclass
class UnionType(TypeNode):
    types: list[TypeNode] = field(default_factory=list)


# ============================================================================
# Expressions
# ============================================================================

@dataclass
class Expr(Node):
    pass


@dataclass
class Literal(Expr):
    value: Union[int, float, str, bool, None] = None
    kind: str = "literal"  # "int", "float", "str", "raw_str", "bytes", "bool", "none", "undefined"


@dataclass
class FString(Expr):
    parts: list[Union[str, tuple[Expr, Optional[str]]]] = field(default_factory=list)


@dataclass
class Ident(Expr):
    name: str = ""


@dataclass
class SelfAttr(Expr):
    """Represents `.attr` -> `self.attr` (or `this.attr` in JS)."""
    attr: str = ""


@dataclass
class SuperAttr(Expr):
    """Represents `..attr` -> `super().attr` (or `super.attr` in JS)."""
    attr: str = ""


@dataclass
class UnaryOp(Expr):
    op: str = ""  # "!", "-", "+", "~", "~|", "#", "*", "**"
    operand: Expr = field(default_factory=Expr)


@dataclass
class BinaryOp(Expr):
    op: str = ""
    left: Expr = field(default_factory=Expr)
    right: Expr = field(default_factory=Expr)


@dataclass
class CompareOp(Expr):
    left: Expr = field(default_factory=Expr)
    ops: list[str] = field(default_factory=list)
    comparators: list[Expr] = field(default_factory=list)


@dataclass
class TernaryOp(Expr):
    cond: Expr = field(default_factory=Expr)
    true_expr: Expr = field(default_factory=Expr)
    false_expr: Expr = field(default_factory=Expr)


@dataclass
class RangeExpr(Expr):
    start: Optional[Expr] = None
    stop: Expr = field(default_factory=Expr)
    step: Optional[Expr] = None


@dataclass
class PipeExpr(Expr):
    left: Expr = field(default_factory=Expr)
    right: Expr = field(default_factory=Expr)


@dataclass
class Call(Expr):
    func: Expr = field(default_factory=Expr)
    args: list[Expr] = field(default_factory=list)
    keywords: list[tuple[Optional[str], Expr]] = field(default_factory=list)  # (name, val); name=None for **kwargs
    dict_shorthand: bool = False  # a trailing `k: v` argument became a dict literal


@dataclass
class NewExpr(Expr):
    """`new C(args)`: an explicit constructor call for a foreign class."""

    func: Expr = field(default_factory=Expr)
    args: list[Expr] = field(default_factory=list)
    keywords: list[tuple[Optional[str], Expr]] = field(default_factory=list)
    dict_shorthand: bool = False


@dataclass
class Attribute(Expr):
    value: Expr = field(default_factory=Expr)
    attr: str = ""
    optional: bool = False  # `?.` safe navigation


@dataclass
class Subscript(Expr):
    value: Expr = field(default_factory=Expr)
    slice: Expr = field(default_factory=Expr)


@dataclass
class Slice(Expr):
    lower: Optional[Expr] = None
    upper: Optional[Expr] = None
    step: Optional[Expr] = None


@dataclass
class ListExpr(Expr):
    elts: list[Expr] = field(default_factory=list)


@dataclass
class TupleExpr(Expr):
    elts: list[Expr] = field(default_factory=list)


@dataclass
class SetExpr(Expr):
    elts: list[Expr] = field(default_factory=list)


@dataclass
class DictExpr(Expr):
    keys: list[Optional[Expr]] = field(default_factory=list)  # None for **spread
    values: list[Expr] = field(default_factory=list)


@dataclass
class CompClause:
    target: Expr
    iter: Expr
    conds: list[Expr] = field(default_factory=list)
    is_async: bool = False


@dataclass
class ListComp(Expr):
    elt: Expr = field(default_factory=Expr)
    clauses: list[CompClause] = field(default_factory=list)


@dataclass
class SetComp(Expr):
    elt: Expr = field(default_factory=Expr)
    clauses: list[CompClause] = field(default_factory=list)


@dataclass
class GenExp(Expr):
    elt: Expr = field(default_factory=Expr)
    clauses: list[CompClause] = field(default_factory=list)


@dataclass
class DictComp(Expr):
    key: Expr = field(default_factory=Expr)
    value: Expr = field(default_factory=Expr)
    clauses: list[CompClause] = field(default_factory=list)


@dataclass
class Lambda(Expr):
    params: list[Param] = field(default_factory=list)
    body: Expr = field(default_factory=Expr)


@dataclass
class NamedExpr(Expr):
    """Walrus / assignment expression."""
    target: Expr = field(default_factory=Expr)
    value: Expr = field(default_factory=Expr)


# ============================================================================
# Statements
# ============================================================================

@dataclass
class Stmt(Node):
    pass


@dataclass
class Module(Node):
    body: list[Stmt] = field(default_factory=list)
    # Set by a module-level `@target(...)` declaration; None means "no contract".
    targets: Optional[set[str]] = None


@dataclass
class TargetBlock(Stmt):
    """Module-level `@target(py) { ... }` conditional compilation block."""

    targets: set[str] = field(default_factory=set)
    body: list[Stmt] = field(default_factory=list)


@dataclass
class ExprStmt(Stmt):
    expr: Expr = field(default_factory=Expr)


@dataclass
class NoopStmt(Stmt):
    """`_` -> `pass`."""
    pass


@dataclass
class AssignStmt(Stmt):
    targets: list[Expr] = field(default_factory=list)
    value: Expr = field(default_factory=Expr)
    type_ann: Optional[TypeNode] = None
    op: str = "="  # "=", ":=", "+=", "-=", "*=", etc.


@dataclass
class DeleteStmt(Stmt):
    targets: list[Expr] = field(default_factory=list)


@dataclass
class ScopeStmt(Stmt):
    kind: str = "global"  # "global" (@=) or "nonlocal" (^=)
    names: list[str] = field(default_factory=list)


@dataclass
class TypeAliasStmt(Stmt):
    name: str = ""
    value: TypeNode = field(default_factory=TypeNode)


@dataclass
class ImportAlias:
    name: str
    asname: Optional[str] = None


@dataclass
class ImportStmt(Stmt):
    names: list[ImportAlias] = field(default_factory=list)
    level: int = 0  # relative-import level for `<.pkg` / `<..pkg`


@dataclass
class ImportFromStmt(Stmt):
    module: Optional[str] = None
    level: int = 0
    names: list[ImportAlias] = field(default_factory=list)


@dataclass
class Param:
    name: str
    type_ann: Optional[TypeNode] = None
    default: Optional[Expr] = None
    kind: str = "normal"  # "normal", "vararg" (*args), "kwarg" (**kwargs), "kwonly_sep" (*), "posonly_sep" (/)


@dataclass
class FuncDef(Stmt):
    name: str = ""
    params: list[Param] = field(default_factory=list)
    return_type: Optional[TypeNode] = None
    body: list[Stmt] = field(default_factory=list)
    decorators: list[Expr] = field(default_factory=list)
    is_async: bool = False
    is_generator: bool = False
    method_kind: str = "normal"  # "normal", "static" (@/), "classmethod" (@$), "property" (@?), "setter" (@=), "init" (@init)
    exported: bool = False


@dataclass
class ClassDef(Stmt):
    name: str = ""
    bases: list[Expr] = field(default_factory=list)
    fields: list[Param] = field(default_factory=list)  # For $$C(...) dataclass shorthand
    body: list[Stmt] = field(default_factory=list)
    decorators: list[Expr] = field(default_factory=list)
    is_dataclass: bool = False
    exported: bool = False


@dataclass
class IfBranch:
    cond: Expr
    body: list[Stmt]


@dataclass
class IfStmt(Stmt):
    branches: list[IfBranch] = field(default_factory=list)
    else_body: Optional[list[Stmt]] = None


@dataclass
class MatchCase:
    pattern: Expr
    guard: Optional[Expr] = None
    body: list[Stmt] = field(default_factory=list)


@dataclass
class MatchStmt(Stmt):
    subject: Expr = field(default_factory=Expr)
    cases: list[MatchCase] = field(default_factory=list)


@dataclass
class ForStmt(Stmt):
    target: Expr = field(default_factory=Expr)
    iter: Expr = field(default_factory=Expr)
    body: list[Stmt] = field(default_factory=list)
    else_body: Optional[list[Stmt]] = None
    is_async: bool = False


@dataclass
class WhileStmt(Stmt):
    cond: Expr = field(default_factory=Expr)
    body: list[Stmt] = field(default_factory=list)
    else_body: Optional[list[Stmt]] = None


@dataclass
class ReturnStmt(Stmt):
    value: Optional[Expr] = None


@dataclass
class YieldStmt(Stmt):
    value: Optional[Expr] = None
    is_from: bool = False


@dataclass
class BreakStmt(Stmt):
    pass


@dataclass
class ContinueStmt(Stmt):
    pass


@dataclass
class ExceptHandler:
    exc_type: Optional[Expr] = None
    name: Optional[str] = None
    body: list[Stmt] = field(default_factory=list)


@dataclass
class TryStmt(Stmt):
    body: list[Stmt] = field(default_factory=list)
    handlers: list[ExceptHandler] = field(default_factory=list)
    else_body: Optional[list[Stmt]] = None
    finally_body: Optional[list[Stmt]] = None


@dataclass
class RaiseStmt(Stmt):
    exc: Optional[Expr] = None
    cause: Optional[Expr] = None


@dataclass
class AssertStmt(Stmt):
    test: Expr = field(default_factory=Expr)
    msg: Optional[Expr] = None


@dataclass
class WithItem:
    context_expr: Expr
    optional_vars: Optional[Expr] = None


@dataclass
class WithStmt(Stmt):
    items: list[WithItem] = field(default_factory=list)
    body: list[Stmt] = field(default_factory=list)
    is_async: bool = False


@dataclass
class MainGuardStmt(Stmt):
    """`@main { ... }` -> `if __name__ == "__main__": ...`."""
    body: list[Stmt] = field(default_factory=list)
