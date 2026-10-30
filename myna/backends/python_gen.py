"""Python 3.12+ code generator for the Myna programming language."""

from __future__ import annotations
from typing import Optional

import myna.ast_nodes as ast
from myna.shorthands import BUILTIN_SHORTHANDS
from myna.sourcemap import SOURCE_MARKER
from myna.targets import enforce_module_target, expand_target_blocks


TYPE_SHORTHANDS = {
    "i": "int",
    "f": "float",
    "s": "str",
    "b": "bool",
    "B": "bytes",
    "A": "Any",
    "N": "None",
}



class PythonGenerator:
    def __init__(self, indent_str: str = "    ", *, sourcemap: bool = False):
        self.indent_str = indent_str
        # When set, every emitted statement is prefixed with a `# myna:LINE` marker so a
        # caller can build a generated-line -> Myna-line table (`myna.sourcemap`).
        self.sourcemap = sourcemap
        self.indent_level = 0
        self.in_class = False
        self.receiver_name = "self"
        self.needs_dataclass_import = False
        self.needs_field_import = False
        self.needs_any_import = False
        self.needs_json_import = False
        self.has_explicit_dataclass_import = False
        self.explicit_dataclass_names: set[str] = set()
        self.has_explicit_any_import = False
        self.has_explicit_json_import = False
        self.exports: list[str] = []

    def ind(self) -> str:
        return self.indent_str * self.indent_level

    def generate(self, mod: ast.Module) -> str:
        self._scan_imports(mod)
        lines: list[str] = []
        prefix_len = 0
        in_prefix = True
        for stmt in mod.body:
            lines.extend(self.gen_stmt(stmt))
            if in_prefix and self._is_module_prefix_stmt(stmt):
                prefix_len = len(lines)
            else:
                in_prefix = False

        header: list[str] = []
        if self.needs_dataclass_import and not self.has_explicit_dataclass_import:
            names = "dataclass, field" if self.needs_field_import else "dataclass"
            header.append(f"from dataclasses import {names}")
        elif self.needs_field_import and "field" not in self.explicit_dataclass_names:
            header.append("from dataclasses import field")
        if self.needs_any_import and not self.has_explicit_any_import:
            header.append("from typing import Any")
        if self.needs_json_import and not self.has_explicit_json_import:
            header.append("import json")

        if self.exports:
            export_list = ", ".join(repr(name) for name in self.exports)
            lines.append(f"__all__ = [{export_list}]")

        if header:
            # Automatically injected imports must follow the module docstring and
            # any `from __future__` imports to remain valid Python.
            lines = lines[:prefix_len] + header + [""] + lines[prefix_len:]
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _is_module_prefix_stmt(stmt: ast.Stmt) -> bool:
        if isinstance(stmt, ast.ExprStmt) and isinstance(stmt.expr, ast.Literal):
            return stmt.expr.kind in ("str", "raw_str")
        if isinstance(stmt, ast.ImportFromStmt) and stmt.module == "__future__":
            return True
        return False

    def _scan_imports(self, mod: ast.Module) -> None:
        for stmt in mod.body:
            if isinstance(stmt, ast.ImportStmt):
                if any(a.name == "json" and a.asname is None for a in stmt.names):
                    self.has_explicit_json_import = True
            if isinstance(stmt, ast.ImportFromStmt):
                if stmt.module == "dataclasses":
                    for alias in stmt.names:
                        if alias.name in ("dataclass", "field", "*"):
                            self.explicit_dataclass_names.add(alias.asname or alias.name)
                        if alias.name in ("dataclass", "*"):
                            self.has_explicit_dataclass_import = True
                if stmt.module == "typing" and any(a.name in ("Any", "*") for a in stmt.names):
                    self.has_explicit_any_import = True

    # ========================================================================
    # Statements
    # ========================================================================

    def gen_stmt(self, stmt: ast.Stmt) -> list[str]:
        if self.sourcemap:
            return [f"{self.ind()}{SOURCE_MARKER}{stmt.line}", *self._gen_stmt(stmt)]
        return self._gen_stmt(stmt)

    def _gen_stmt(self, stmt: ast.Stmt) -> list[str]:
        if isinstance(stmt, ast.NoopStmt):
            return [f"{self.ind()}pass"]

        if isinstance(stmt, ast.ExprStmt):
            return [f"{self.ind()}{self.gen_expr(stmt.expr)}"]

        if isinstance(stmt, ast.AssignStmt):
            val_str = self.gen_expr(stmt.value)
            if stmt.type_ann is not None:
                tgt = self.gen_expr(stmt.targets[0])
                t_str = self.gen_type(stmt.type_ann)
                return [f"{self.ind()}{tgt}: {t_str} = {val_str}"]
            op = "=" if stmt.op == ":=" else stmt.op
            tgts = " = ".join(self.gen_expr(t) for t in stmt.targets)
            return [f"{self.ind()}{tgts} {op} {val_str}"]

        if isinstance(stmt, ast.DeleteStmt):
            tgts = ", ".join(self.gen_expr(t) for t in stmt.targets)
            return [f"{self.ind()}del {tgts}"]

        if isinstance(stmt, ast.ScopeStmt):
            names = ", ".join(stmt.names)
            return [f"{self.ind()}{stmt.kind} {names}"]

        if isinstance(stmt, ast.TypeAliasStmt):
            return [f"{self.ind()}type {stmt.name} = {self.gen_type(stmt.value)}"]

        if isinstance(stmt, ast.ImportStmt):
            parts = [f"{a.name} as {a.asname}" if a.asname else a.name for a in stmt.names]
            if stmt.level:
                return self._gen_relative_module_imports(stmt)
            return [f"{self.ind()}import {', '.join(parts)}"]

        if isinstance(stmt, ast.ImportFromStmt):
            dots = "." * stmt.level
            mod = f"{dots}{stmt.module or ''}"
            parts = [f"{a.name} as {a.asname}" if a.asname else a.name for a in stmt.names]
            return [f"{self.ind()}from {mod} import {', '.join(parts)}"]

        if isinstance(stmt, ast.FuncDef):
            return self.gen_func_def(stmt)

        if isinstance(stmt, ast.ClassDef):
            return self.gen_class_def(stmt)

        if isinstance(stmt, ast.IfStmt):
            return self.gen_if_stmt(stmt)

        if isinstance(stmt, ast.MatchStmt):
            return self.gen_match_stmt(stmt)

        if isinstance(stmt, ast.ForStmt):
            return self.gen_for_stmt(stmt)

        if isinstance(stmt, ast.WhileStmt):
            return self.gen_while_stmt(stmt)

        if isinstance(stmt, ast.ReturnStmt):
            if stmt.value is None:
                return [f"{self.ind()}return"]
            return [f"{self.ind()}return {self.gen_expr(stmt.value)}"]

        if isinstance(stmt, ast.YieldStmt):
            kw = "yield from" if stmt.is_from else "yield"
            if stmt.value is None:
                return [f"{self.ind()}{kw}"]
            return [f"{self.ind()}{kw} {self.gen_expr(stmt.value)}"]

        if isinstance(stmt, ast.BreakStmt):
            return [f"{self.ind()}break"]

        if isinstance(stmt, ast.ContinueStmt):
            return [f"{self.ind()}continue"]

        if isinstance(stmt, ast.TryStmt):
            return self.gen_try_stmt(stmt)

        if isinstance(stmt, ast.RaiseStmt):
            if stmt.exc is None:
                return [f"{self.ind()}raise"]
            exc_s = self.gen_expr(stmt.exc)
            if stmt.cause is not None:
                return [f"{self.ind()}raise {exc_s} from {self.gen_expr(stmt.cause)}"]
            return [f"{self.ind()}raise {exc_s}"]

        if isinstance(stmt, ast.AssertStmt):
            test_s = self.gen_expr(stmt.test)
            if stmt.msg is not None:
                return [f"{self.ind()}assert {test_s}, {self.gen_expr(stmt.msg)}"]
            return [f"{self.ind()}assert {test_s}"]

        if isinstance(stmt, ast.WithStmt):
            return self.gen_with_stmt(stmt)

        if isinstance(stmt, ast.MainGuardStmt):
            lines = [f'{self.ind()}if __name__ == "__main__":']
            lines.extend(self.gen_block(stmt.body))
            return lines

        raise ValueError(f"Unsupported statement node: {stmt!r}")

    def gen_block(self, stmts: list[ast.Stmt]) -> list[str]:
        self.indent_level += 1
        if not stmts:
            res = [f"{self.ind()}pass"]
        else:
            res = []
            for s in stmts:
                res.extend(self.gen_stmt(s))
        self.indent_level -= 1
        return res

    def _gen_relative_module_imports(self, stmt: ast.ImportStmt) -> list[str]:
        """Lower a relative module-object import (``<.pk.mod``).

        ``from . import pk.mod`` is not valid Python, so a dotted name becomes
        ``from .pk import mod``; plain names keep the ``from . import a, b`` form.
        """
        dots = "." * stmt.level
        plain = [f"{a.name} as {a.asname}" if a.asname else a.name
                 for a in stmt.names if "." not in a.name]
        lines: list[str] = []
        if plain:
            lines.append(f"{self.ind()}from {dots} import {', '.join(plain)}")
        for alias in stmt.names:
            if "." not in alias.name:
                continue
            parent, _, leaf = alias.name.rpartition(".")
            asname = f" as {alias.asname}" if alias.asname else ""
            lines.append(f"{self.ind()}from {dots}{parent} import {leaf}{asname}")
        return lines

    def gen_func_def(self, fn: ast.FuncDef) -> list[str]:
        if fn.exported and self.indent_level == 0:
            self.exports.append(fn.name)

        lines: list[str] = []
        for dec in fn.decorators:
            lines.append(f"{self.ind()}@{self.gen_expr(dec)}")

        if fn.method_kind == "static":
            lines.append(f"{self.ind()}@staticmethod")
        elif fn.method_kind == "classmethod":
            lines.append(f"{self.ind()}@classmethod")
        elif fn.method_kind == "property":
            lines.append(f"{self.ind()}@property")
        elif fn.method_kind == "setter":
            lines.append(f"{self.ind()}@{fn.name}.setter")

        py_name = "__init__" if (self.in_class and fn.method_kind == "init") else fn.name

        # Determine implicit receiver parameter (`self` or `cls`)
        param_strs: list[str] = []
        prev_receiver = self.receiver_name
        if self.in_class:
            if fn.method_kind == "classmethod":
                self.receiver_name = "cls"
                if not fn.params or fn.params[0].name != "cls":
                    param_strs.append("cls")
            elif fn.method_kind != "static":
                self.receiver_name = "self"
                if not fn.params or fn.params[0].name != "self":
                    param_strs.append("self")

        for p in fn.params:
            param_strs.append(self.gen_param(p))

        ret_ann = ""
        if fn.return_type is not None:
            ret_ann = f" -> {self.gen_type(fn.return_type)}"
        elif self.in_class and fn.method_kind == "init":
            ret_ann = ""

        kw = "async def" if fn.is_async else "def"
        lines.append(f"{self.ind()}{kw} {py_name}({', '.join(param_strs)}){ret_ann}:")
        lines.extend(self.gen_block(fn.body))
        self.receiver_name = prev_receiver
        return lines

    def gen_param(self, p: ast.Param) -> str:
        if p.kind in ("kwonly_sep", "posonly_sep"):
            return p.name
        prefix = "*" if p.kind == "vararg" else ("**" if p.kind == "kwarg" else "")
        s = f"{prefix}{p.name}"
        if p.type_ann is not None:
            s += f": {self.gen_type(p.type_ann)}"
        if p.default is not None:
            sep = " = " if p.type_ann is not None else "="
            s += f"{sep}{self.gen_expr(p.default)}"
        return s

    def _dataclass_field_factory(self, default: Optional[ast.Expr]) -> Optional[str]:
        """Return a `field(default_factory=...)` for a mutable dataclass default.

        `@dataclass` rejects a `list`/`dict`/`set` default at class-creation time, and a
        shared mutable default is wrong even where it is allowed; a factory gives every
        instance its own value, which is what the JavaScript target's constructor default
        already does (GAPS.md G6).
        """
        if isinstance(default, ast.ListExpr):
            if not default.elts:
                return "field(default_factory=list)"
        elif isinstance(default, ast.DictExpr):
            if not default.keys:
                return "field(default_factory=dict)"
        elif isinstance(default, ast.SetExpr):
            if not default.elts:
                return "field(default_factory=set)"
        else:
            return None
        return f"field(default_factory=lambda: {self.gen_expr(default)})"

    def gen_class_def(self, cls: ast.ClassDef) -> list[str]:
        if cls.exported and self.indent_level == 0:
            self.exports.append(cls.name)

        lines: list[str] = []
        for dec in cls.decorators:
            lines.append(f"{self.ind()}@{self.gen_expr(dec)}")

        if cls.is_dataclass:
            has_dc_dec = any(
                (isinstance(d, ast.Ident) and d.name == "dataclass")
                or (isinstance(d, ast.Call) and isinstance(d.func, ast.Ident) and d.func.name == "dataclass")
                for d in cls.decorators
            )
            if not has_dc_dec:
                self.needs_dataclass_import = True
                lines.append(f"{self.ind()}@dataclass")

        bases_str = f"({', '.join(self.gen_expr(b) for b in cls.bases)})" if cls.bases else ""
        lines.append(f"{self.ind()}class {cls.name}{bases_str}:")

        prev_in_class = self.in_class
        self.in_class = True
        self.indent_level += 1

        body_lines: list[str] = []
        for f in cls.fields:
            f_line = f"{self.ind()}{f.name}"
            if f.type_ann is not None:
                f_line += f": {self.gen_type(f.type_ann)}"
            else:
                self.needs_any_import = True
                f_line += ": Any"
            factory = self._dataclass_field_factory(f.default) if cls.is_dataclass else None
            if factory is not None:
                self.needs_field_import = True
                f_line += f" = {factory}"
            elif f.default is not None:
                f_line += f" = {self.gen_expr(f.default)}"
            body_lines.append(f_line)

        for s in cls.body:
            body_lines.extend(self.gen_stmt(s))

        if not body_lines:
            body_lines.append(f"{self.ind()}pass")

        self.indent_level -= 1
        self.in_class = prev_in_class
        lines.extend(body_lines)
        return lines

    def gen_if_stmt(self, stmt: ast.IfStmt) -> list[str]:
        lines: list[str] = []
        for idx, br in enumerate(stmt.branches):
            kw = "if" if idx == 0 else "elif"
            lines.append(f"{self.ind()}{kw} {self.gen_expr(br.cond)}:")
            lines.extend(self.gen_block(br.body))
        if stmt.else_body is not None:
            lines.append(f"{self.ind()}else:")
            lines.extend(self.gen_block(stmt.else_body))
        return lines

    def gen_match_stmt(self, stmt: ast.MatchStmt) -> list[str]:
        lines = [f"{self.ind()}match {self.gen_expr(stmt.subject)}:"]
        self.indent_level += 1
        for c in stmt.cases:
            pat_s = self.gen_expr(c.pattern)
            guard_s = f" if {self.gen_expr(c.guard)}" if c.guard is not None else ""
            lines.append(f"{self.ind()}case {pat_s}{guard_s}:")
            lines.extend(self.gen_block(c.body))
        self.indent_level -= 1
        return lines

    def gen_for_stmt(self, stmt: ast.ForStmt) -> list[str]:
        kw = "async for" if stmt.is_async else "for"
        tgt_s = self.gen_target(stmt.target)
        lines = [f"{self.ind()}{kw} {tgt_s} in {self.gen_expr(stmt.iter)}:"]
        lines.extend(self.gen_block(stmt.body))
        if stmt.else_body is not None:
            lines.append(f"{self.ind()}else:")
            lines.extend(self.gen_block(stmt.else_body))
        return lines

    def gen_while_stmt(self, stmt: ast.WhileStmt) -> list[str]:
        lines = [f"{self.ind()}while {self.gen_expr(stmt.cond)}:"]
        lines.extend(self.gen_block(stmt.body))
        if stmt.else_body is not None:
            lines.append(f"{self.ind()}else:")
            lines.extend(self.gen_block(stmt.else_body))
        return lines

    def gen_try_stmt(self, stmt: ast.TryStmt) -> list[str]:
        lines = [f"{self.ind()}try:"]
        lines.extend(self.gen_block(stmt.body))
        for h in stmt.handlers:
            if h.exc_type is not None and h.name is not None:
                lines.append(f"{self.ind()}except {self.gen_expr(h.exc_type)} as {h.name}:")
            elif h.exc_type is not None:
                lines.append(f"{self.ind()}except {self.gen_expr(h.exc_type)}:")
            else:
                lines.append(f"{self.ind()}except:")
            lines.extend(self.gen_block(h.body))
        if stmt.else_body is not None:
            lines.append(f"{self.ind()}else:")
            lines.extend(self.gen_block(stmt.else_body))
        if stmt.finally_body is not None:
            lines.append(f"{self.ind()}finally:")
            lines.extend(self.gen_block(stmt.finally_body))
        return lines

    def gen_with_stmt(self, stmt: ast.WithStmt) -> list[str]:
        kw = "async with" if stmt.is_async else "with"
        item_strs: list[str] = []
        for item in stmt.items:
            ctx = self.gen_expr(item.context_expr)
            if item.optional_vars is not None:
                item_strs.append(f"{ctx} as {self.gen_target(item.optional_vars)}")
            else:
                item_strs.append(ctx)
        lines = [f"{self.ind()}{kw} {', '.join(item_strs)}:"]
        lines.extend(self.gen_block(stmt.body))
        return lines

    # ========================================================================
    # Types
    # ========================================================================

    def gen_type(self, t: ast.TypeNode) -> str:
        if isinstance(t, ast.SimpleType):
            base = TYPE_SHORTHANDS.get(t.name, t.name)
            if base == "Any":
                self.needs_any_import = True
            return f"{base} | None" if t.optional else base

        if isinstance(t, ast.ListType):
            base = f"list[{self.gen_type(t.elem)}]"
            return f"{base} | None" if t.optional else base

        if isinstance(t, ast.DictType):
            base = f"dict[{self.gen_type(t.key)}, {self.gen_type(t.value)}]"
            return f"{base} | None" if t.optional else base

        if isinstance(t, ast.SetType):
            base = f"set[{self.gen_type(t.elem)}]"
            return f"{base} | None" if t.optional else base

        if isinstance(t, ast.TupleType):
            args = ", ".join(self.gen_type(e) for e in t.elems) if t.elems else "()"
            base = f"tuple[{args}]"
            return f"{base} | None" if t.optional else base

        if isinstance(t, ast.GenericType):
            b_name = TYPE_SHORTHANDS.get(t.base, t.base)
            args = ", ".join(self.gen_type(a) for a in t.args)
            base = f"{b_name}[{args}]"
            return f"{base} | None" if t.optional else base

        if isinstance(t, ast.UnionType):
            return " | ".join(self.gen_type(sub) for sub in t.types)

        return "Any"

    # ========================================================================
    # Expressions
    # ========================================================================

    def gen_target(self, expr: ast.Expr) -> str:
        if isinstance(expr, ast.TupleExpr):
            return ", ".join(self.gen_expr(e) for e in expr.elts)
        return self.gen_expr(expr)

    # Delimiters a Python 3.11 f-string may use, most conventional first.
    # Triple quotes allow the same quote character inside an interpolation.
    _FSTRING_DELIMITERS = ('"', "'", '"""', "'''")

    @staticmethod
    def _escape_fstring_literal(text: str, quote: str) -> str:
        """Escape literal f-string text for a 3.11-compatible f-string.

        A backslash is always escaped, as are braces and the delimiter quote.
        Escaping every delimiter quote keeps the output valid even for a
        triple-quoted delimiter, where a raw run of three quotes would close it.
        """
        return (
            text.replace("\\", "\\\\")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("{", "{{")
            .replace("}", "}}")
            .replace(quote, "\\" + quote)
        )

    @staticmethod
    def _escape_format_literal(text: str) -> str:
        """Escape literal text for a ``str.format`` fallback template."""
        return (
            text.replace("\\", "\\\\")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace('"', '\\"')
            .replace("{", "{{")
            .replace("}", "}}")
        )

    def gen_fstring(self, expr: ast.FString) -> str:
        """Emit an f-string that also compiles on Python 3.11.

        Before PEP 701 (Python 3.12), an interpolation cannot contain a
        backslash or the delimiter's quote character. Pick a safe delimiter
        when possible; otherwise fall back to ``str.format`` so runtime values
        still use ``__format__`` exactly as an f-string would.
        """
        rendered: list[str | tuple[str, Optional[str]]] = []
        interpolations: list[str] = []
        for p in expr.parts:
            if isinstance(p, str):
                rendered.append(p)
            else:
                sub_expr, fmt_spec = p
                sub_s = self.gen_expr(sub_expr)
                rendered.append((sub_s, fmt_spec))
                interpolations.append(sub_s)

        if all("\\" not in sub_s for sub_s in interpolations):
            for delim in self._FSTRING_DELIMITERS:
                if any(delim in sub_s for sub_s in interpolations):
                    continue
                body: list[str] = []
                for p in rendered:
                    if isinstance(p, str):
                        body.append(self._escape_fstring_literal(p, delim[0]))
                    else:
                        sub_s, fmt_spec = p
                        if fmt_spec is not None:
                            body.append(f"{{{sub_s}:{fmt_spec}}}")
                        else:
                            body.append(f"{{{sub_s}}}")
                return f"f{delim}{''.join(body)}{delim}"

        # Fallback for interpolations that cannot appear in a 3.11 f-string.
        # ``str.format`` applies the same __format__ protocol as an f-string.
        template: list[str] = []
        args: list[str] = []
        for p in rendered:
            if isinstance(p, str):
                template.append(self._escape_format_literal(p))
                continue
            sub_s, fmt_spec = p
            index = len(args)
            args.append(sub_s)
            if fmt_spec is not None:
                spec = (
                    fmt_spec.replace("\\", "\\\\")
                    .replace('"', '\\"')
                    .replace("\n", "\\n")
                    .replace("\r", "\\r")
                )
                template.append(f"{{{index}:{spec}}}")
            else:
                template.append(f"{{{index}}}")
        if not args:
            return f'"{"".join(template)}"'
        return f'"{"".join(template)}".format({", ".join(args)})'

    def gen_expr(self, expr: ast.Expr, parent_prec: int = 0) -> str:
        if isinstance(expr, ast.Literal):
            if expr.kind == "ellipsis":
                return "..."
            if expr.kind in ("none", "undefined"):
                return "None"
            if expr.kind == "bool":
                return "True" if expr.value else "False"
            if expr.kind == "raw_str":
                return repr(expr.value)
            if expr.kind == "bytes":
                assert isinstance(expr.value, str)
                return repr(expr.value.encode("latin-1"))
            return repr(expr.value)

        if isinstance(expr, ast.FString):
            return self.gen_fstring(expr)

        if isinstance(expr, ast.Ident):
            if expr.name in ("@j", "@J"):
                self.needs_json_import = True
            if expr.name == "p":
                return "p"
            return BUILTIN_SHORTHANDS.get(expr.name, expr.name)

        if isinstance(expr, ast.SelfAttr):
            return f"{self.receiver_name}.{expr.attr}"

        if isinstance(expr, ast.SuperAttr):
            attr = "__init__" if expr.attr == "init" else expr.attr
            return f"super().{attr}"

        if isinstance(expr, ast.UnaryOp):
            if expr.op == "#":
                return f"len({self.gen_expr(expr.operand)})"
            if expr.op == "!":
                s = f"not {self.gen_expr(expr.operand, 28)}"
                return f"({s})" if parent_prec > 28 else s
            if expr.op == "~":
                s = f"await {self.gen_expr(expr.operand, 85)}"
                return f"({s})" if parent_prec > 85 else s
            if expr.op == "~|":
                return f"~{self.gen_expr(expr.operand, 80)}"
            if expr.op in ("*", "**"):
                return f"{expr.op}{self.gen_expr(expr.operand, 80)}"
            return f"{expr.op}{self.gen_expr(expr.operand, 80)}"

        if isinstance(expr, ast.BinaryOp):
            if expr.op == "??":
                l_s = self.gen_expr(expr.left, 15)
                r_s = self.gen_expr(expr.right, 15)
                s = f"{l_s} if {l_s} is not None else {r_s}"
                return f"({s})" if parent_prec > 10 else s

            py_op = {"&&": "and", "||": "or"}.get(expr.op, expr.op)
            prec = self._py_prec(py_op)
            l_s = self.gen_expr(expr.left, prec)
            r_s = self.gen_expr(expr.right, prec + (0 if py_op == "**" else 1))
            s = f"{l_s} {py_op} {r_s}"
            return f"({s})" if parent_prec > prec else s

        if isinstance(expr, ast.CompareOp):
            # Handle `x :? Type` -> `isinstance(x, Type)`
            if len(expr.ops) == 1 and expr.ops[0] == ":?":
                lhs = self.gen_expr(expr.left)
                rhs_expr = expr.comparators[0]
                rhs = self._gen_isinstance_type(rhs_expr)
                return f"isinstance({lhs}, {rhs})"

            parts = [self.gen_expr(expr.left, 31)]
            op_map = {
                "===": "is",
                "!==": "is not",
                "<-": "in",
                "!<-": "not in",
            }
            for op, comp in zip(expr.ops, expr.comparators):
                py_op = op_map.get(op, op)
                parts.append(py_op)
                parts.append(self.gen_expr(comp, 31))
            s = " ".join(parts)
            return f"({s})" if parent_prec > 30 else s

        if isinstance(expr, ast.TernaryOp):
            c_s = self.gen_expr(expr.cond, 11)
            t_s = self.gen_expr(expr.true_expr, 11)
            f_s = self.gen_expr(expr.false_expr, 10)
            s = f"{t_s} if {c_s} else {f_s}"
            return f"({s})" if parent_prec > 10 else s

        if isinstance(expr, ast.RangeExpr):
            stop_s = self.gen_expr(expr.stop)
            if expr.start is None and expr.step is None:
                return f"range({stop_s})"
            start_s = self.gen_expr(expr.start) if expr.start is not None else "0"
            if expr.step is not None:
                return f"range({start_s}, {stop_s}, {self.gen_expr(expr.step)})"
            # Optimize `0..n` -> `range(n)`
            if start_s == "0":
                return f"range({stop_s})"
            return f"range({start_s}, {stop_s})"

        if isinstance(expr, ast.PipeExpr):
            # `x |> f` -> `f(x)` and `x |> f(a, b)` -> `f(x, a, b)`
            if isinstance(expr.right, ast.Call):
                rewritten = ast.Call(
                    func=expr.right.func,
                    args=[expr.left] + expr.right.args,
                    keywords=expr.right.keywords,
                    line=expr.line,
                    col=expr.col,
                )
                return self.gen_expr(rewritten, parent_prec)
            return f"{self.gen_expr(expr.right, 90)}({self.gen_expr(expr.left)})"

        if isinstance(expr, ast.Call):
            if isinstance(expr.func, ast.Ident) and expr.func.name in ("@u8", "@u8d") and len(expr.args) == 1 and not expr.keywords:
                target_s = self.gen_expr(expr.args[0], 90)
                method = "encode" if expr.func.name == "@u8" else "decode"
                return f"{target_s}.{method}('utf-8')"
            func_s = "print" if (isinstance(expr.func, ast.Ident) and expr.func.name == "p") else self.gen_expr(expr.func, 90)
            arg_parts = [self.gen_expr(a) for a in expr.args]
            # If call has only `k: v` style keywords and no positional args for methods that take a dict, wait:
            # Wait: what if `f(k: v)` is used for a single dict argument when `f` is `._send_json(200, error: "msg")`?
            for k, v in expr.keywords:
                if k is None:
                    arg_parts.append(f"**{self.gen_expr(v)}")
                else:
                    arg_parts.append(f"{k}={self.gen_expr(v)}")
            return f"{func_s}({', '.join(arg_parts)})"

        if isinstance(expr, ast.Attribute):
            val_s = self.gen_expr(expr.value, 90)
            if expr.optional:
                return f"(None if {val_s} is None else {val_s}.{expr.attr})"
            return f"{val_s}.{expr.attr}"

        if isinstance(expr, ast.Subscript):
            val_s = self.gen_expr(expr.value, 90)
            if isinstance(expr.slice, ast.TupleExpr):
                sl_s = ", ".join(self.gen_expr(e) for e in expr.slice.elts)
            else:
                sl_s = self.gen_expr(expr.slice)
            return f"{val_s}[{sl_s}]"

        if isinstance(expr, ast.Slice):
            lo = self.gen_expr(expr.lower) if expr.lower is not None else ""
            up = self.gen_expr(expr.upper) if expr.upper is not None else ""
            if expr.step is not None:
                return f"{lo}:{up}:{self.gen_expr(expr.step)}"
            return f"{lo}:{up}"

        if isinstance(expr, ast.ListExpr):
            return f"[{', '.join(self.gen_expr(e) for e in expr.elts)}]"

        if isinstance(expr, ast.TupleExpr):
            if not expr.elts:
                return "()"
            if len(expr.elts) == 1:
                return f"({self.gen_expr(expr.elts[0])},)"
            return f"({', '.join(self.gen_expr(e) for e in expr.elts)})"

        if isinstance(expr, ast.SetExpr):
            if not expr.elts:
                return "set()"
            return f"{{{', '.join(self.gen_expr(e) for e in expr.elts)}}}"

        if isinstance(expr, ast.DictExpr):
            items: list[str] = []
            for k, v in zip(expr.keys, expr.values):
                if k is None:
                    items.append(f"**{self.gen_expr(v)}")
                else:
                    items.append(f"{self.gen_expr(k)}: {self.gen_expr(v)}")
            return f"{{{', '.join(items)}}}"

        if isinstance(expr, ast.ListComp):
            return f"[{self.gen_expr(expr.elt)} {self._gen_comp_clauses(expr.clauses)}]"

        if isinstance(expr, ast.SetComp):
            return f"{{{self.gen_expr(expr.elt)} {self._gen_comp_clauses(expr.clauses)}}}"

        if isinstance(expr, ast.GenExp):
            return f"({self.gen_expr(expr.elt)} {self._gen_comp_clauses(expr.clauses)})"

        if isinstance(expr, ast.DictComp):
            return f"{{{self.gen_expr(expr.key)}: {self.gen_expr(expr.value)} {self._gen_comp_clauses(expr.clauses)}}}"

        if isinstance(expr, ast.Lambda):
            p_strs = [self.gen_param(p) for p in expr.params]
            p_part = f" {', '.join(p_strs)}" if p_strs else ""
            s = f"lambda{p_part}: {self.gen_expr(expr.body)}"
            return f"({s})" if parent_prec > 5 else s

        if isinstance(expr, ast.NamedExpr):
            s = f"{self.gen_expr(expr.target)} := {self.gen_expr(expr.value)}"
            return f"({s})" if parent_prec > 0 else f"({s})"

        raise ValueError(f"Unsupported expression node: {expr!r}")

    def _gen_isinstance_type(self, expr: ast.Expr) -> str:
        if isinstance(expr, ast.Ident):
            return TYPE_SHORTHANDS.get(expr.name, expr.name)
        if isinstance(expr, ast.TupleExpr):
            # `(A, B)` in a runtime check is a union: `isinstance(x, (A, B))`.
            return f"({', '.join(self._gen_isinstance_type(e) for e in expr.elts)})"
        # Compound type expressions check their runtime origin type; parameterized
        # generics are not valid as the second argument to `isinstance()`.
        if isinstance(expr, ast.ListExpr):
            return "list"
        if isinstance(expr, ast.DictExpr):
            return "dict"
        if isinstance(expr, ast.SetExpr):
            return "set"
        if isinstance(expr, ast.Subscript):
            return self._gen_isinstance_type(expr.value)
        return self.gen_expr(expr)

    def _gen_comp_clauses(self, clauses: list[ast.CompClause]) -> str:
        parts: list[str] = []
        for c in clauses:
            kw = "async for" if c.is_async else "for"
            iter_s = self.gen_expr(c.iter, 11) if isinstance(c.iter, ast.TernaryOp) else self.gen_expr(c.iter)
            part = f"{kw} {self.gen_target(c.target)} in {iter_s}"
            for cond in c.conds:
                part += f" if {self.gen_expr(cond)}"
            parts.append(part)
        return " ".join(parts)

    def _py_prec(self, op: str) -> int:
        return {
            "or": 20,
            "and": 25,
            "|": 35,
            "^": 37,
            "&": 39,
            "<<": 42,
            ">>": 42,
            "+": 50,
            "-": 50,
            "*": 60,
            "/": 60,
            "//": 60,
            "%": 60,
            "**": 70,
        }.get(op, 50)


def compile_to_python(mod: ast.Module, *, sourcemap: bool = False) -> str:
    enforce_module_target(mod, "py")
    gen = PythonGenerator(sourcemap=sourcemap)
    return gen.generate(expand_target_blocks(mod, "py"))
