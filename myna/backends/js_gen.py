"""JavaScript (ES2024+) code generator for the Myna programming language."""

from __future__ import annotations
from typing import Optional

import myna.ast_nodes as ast
from myna.targets import enforce_module_target, expand_target_blocks


class JSGenerator:
    def __init__(self, indent_str: str = "  "):
        self.indent_str = indent_str
        self.indent_level = 0
        self.in_class = False
        self.scopes: list[set[str]] = [set()]
        self.known_classes: set[str] = set()
        self.needs_range_helper = False
        self.needs_in_helper = False
        self.needs_len_helper = False
        self.needs_is_dict_helper = False

    def ind(self) -> str:
        return self.indent_str * self.indent_level

    def push_scope(self, initial: Optional[set[str]] = None) -> None:
        self.scopes.append(set(initial or set()))

    def pop_scope(self) -> None:
        self.scopes.pop()

    def is_declared(self, name: str) -> bool:
        return any(name in s for s in self.scopes)

    def declare(self, name: str) -> None:
        self.scopes[-1].add(name)

    def generate(self, mod: ast.Module) -> str:
        self._scan_classes(mod)
        lines: list[str] = []
        for stmt in mod.body:
            lines.extend(self.gen_stmt(stmt))

        helpers: list[str] = []
        if self.needs_range_helper:
            helpers.append(
                "function __myna_range(a, b, s = 1) { "
                "if (b === undefined) { b = a; a = 0; } "
                "const r = []; "
                "for (let i = a; s > 0 ? i < b : i > b; i += s) r.push(i); "
                "return r; }"
            )
        if self.needs_in_helper:
            helpers.append(
                "function __myna_in(x, c) { "
                "if (Array.isArray(c) || typeof c === 'string') return c.includes(x); "
                "if (c instanceof Set || c instanceof Map) return c.has(x); "
                "return c != null && Object.prototype.hasOwnProperty.call(c, x); }"
            )
        if self.needs_len_helper:
            helpers.append(
                "function __myna_len(x) { "
                "if (x == null) return 0; "
                "if (typeof x.length === 'number') return x.length; "
                "if (typeof x.size === 'number') return x.size; "
                "return Object.keys(x).length; }"
            )
        if self.needs_is_dict_helper:
            helpers.append(
                "function __myna_is_dict(x) { "
                "return x !== null && typeof x === 'object' "
                "&& !Array.isArray(x) && !(x instanceof Set) && !(x instanceof Map); }"
            )

        all_lines = (helpers + [""] + lines) if (helpers and lines) else (helpers + lines)
        return "\n".join(all_lines).rstrip() + "\n"

    def _scan_classes(self, mod: ast.Module) -> None:
        for stmt in mod.body:
            if isinstance(stmt, ast.ClassDef):
                self.known_classes.add(stmt.name)
                self.declare(stmt.name)
            elif isinstance(stmt, ast.FuncDef):
                self.declare(stmt.name)

    # ========================================================================
    # Statements
    # ========================================================================

    def gen_stmt(self, stmt: ast.Stmt) -> list[str]:
        if isinstance(stmt, ast.NoopStmt):
            return [f"{self.ind()}/* noop */"]

        if isinstance(stmt, ast.ExprStmt):
            return [f"{self.ind()}{self.gen_expr(stmt.expr)};"]

        if isinstance(stmt, ast.AssignStmt):
            return self.gen_assign_stmt(stmt)

        if isinstance(stmt, ast.DeleteStmt):
            parts = [f"delete {self.gen_expr(t)};" for t in stmt.targets]
            return [f"{self.ind()}{' '.join(parts)}"]

        if isinstance(stmt, ast.ScopeStmt):
            # In JS, lexical closures and module globals resolve outer bindings automatically;
            # mark them as declared in current scope so `x = ...` doesn't shadow with `let x`!
            for n in stmt.names:
                self.declare(n)
            return [f"{self.ind()}/* {stmt.kind} {', '.join(stmt.names)} */"]

        if isinstance(stmt, ast.TypeAliasStmt):
            return [f"{self.ind()}/* type {stmt.name} */"]

        if isinstance(stmt, ast.ImportStmt):
            lines: list[str] = []
            for a in stmt.names:
                local = a.asname or a.name.split(".")[-1]
                self.declare(local)
                lines.append(f'{self.ind()}import * as {local} from "{a.name}";')
            return lines

        if isinstance(stmt, ast.ImportFromStmt):
            dots = "./" if stmt.level == 1 else ("../" * (stmt.level - 1) if stmt.level > 1 else "")
            mod = f"{dots}{stmt.module or ''}"
            specs: list[str] = []
            for a in stmt.names:
                local = a.asname or a.name
                self.declare(local)
                specs.append(f"{a.name} as {a.asname}" if a.asname else a.name)
            return [f'{self.ind()}import {{ {", ".join(specs)} }} from "{mod}";']

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
                return [f"{self.ind()}return;"]
            return [f"{self.ind()}return {self.gen_expr(stmt.value)};"]

        if isinstance(stmt, ast.YieldStmt):
            kw = "yield*" if stmt.is_from else "yield"
            if stmt.value is None:
                return [f"{self.ind()}{kw};"]
            return [f"{self.ind()}{kw} {self.gen_expr(stmt.value)};"]

        if isinstance(stmt, ast.BreakStmt):
            return [f"{self.ind()}break;"]

        if isinstance(stmt, ast.ContinueStmt):
            return [f"{self.ind()}continue;"]

        if isinstance(stmt, ast.TryStmt):
            return self.gen_try_stmt(stmt)

        if isinstance(stmt, ast.RaiseStmt):
            if stmt.exc is None:
                return [f"{self.ind()}throw __myna_err;"]
            return [f"{self.ind()}throw {self.gen_expr(stmt.exc)};"]

        if isinstance(stmt, ast.AssertStmt):
            test_s = self.gen_expr(stmt.test)
            msg_s = self.gen_expr(stmt.msg) if stmt.msg is not None else repr("AssertionError")
            return [f"{self.ind()}if (!({test_s})) throw new Error({msg_s});"]

        if isinstance(stmt, ast.WithStmt):
            return self.gen_with_stmt(stmt)

        if isinstance(stmt, ast.MainGuardStmt):
            lines = [f"{self.ind()}// @main entrypoint", f"{self.ind()}{{"]
            lines.extend(self.gen_block(stmt.body))
            lines.append(f"{self.ind()}}}")
            return lines

        raise ValueError(f"Unsupported statement node for JS: {stmt!r}")

    def gen_assign_stmt(self, stmt: ast.AssignStmt) -> list[str]:
        val_str = self.gen_expr(stmt.value)
        if len(stmt.targets) == 1:
            tgt = stmt.targets[0]
            if isinstance(tgt, ast.Ident):
                if stmt.op == ":=":
                    self.declare(tgt.name)
                    return [f"{self.ind()}const {tgt.name} = {val_str};"]
                if stmt.op == "=" and not self.is_declared(tgt.name):
                    self.declare(tgt.name)
                    return [f"{self.ind()}let {tgt.name} = {val_str};"]
                return [f"{self.ind()}{tgt.name} {stmt.op} {val_str};"]

            if isinstance(tgt, ast.TupleExpr):
                names = [e.name for e in tgt.elts if isinstance(e, ast.Ident)]
                all_new = bool(names) and all(not self.is_declared(n) and n != "_" for n in names)
                for n in names:
                    if n != "_":
                        self.declare(n)
                lhs = self._gen_destructure_target(tgt)
                kw = "let " if all_new else ""
                return [f"{self.ind()}{kw}{lhs} = {val_str};"]

            return [f"{self.ind()}{self.gen_expr(tgt)} {stmt.op} {val_str};"]

        # Chained assignment `a = b = 1`
        lines: list[str] = []
        for t in stmt.targets:
            if isinstance(t, ast.Ident) and not self.is_declared(t.name):
                self.declare(t.name)
                lines.append(f"{self.ind()}let {t.name};")
        chain = " = ".join(self.gen_expr(t) for t in stmt.targets)
        lines.append(f"{self.ind()}{chain} = {val_str};")
        return lines

    def _gen_destructure_target(self, expr: ast.Expr) -> str:
        if isinstance(expr, ast.TupleExpr):
            parts: list[str] = []
            for idx, e in enumerate(expr.elts):
                if isinstance(e, ast.Ident) and e.name == "_":
                    parts.append(f"__unused_{idx}")
                else:
                    parts.append(self._gen_destructure_target(e))
            return f"[{', '.join(parts)}]"
        return self.gen_expr(expr)

    def gen_block(self, stmts: list[ast.Stmt], new_scope: bool = True) -> list[str]:
        if new_scope:
            self.push_scope()
        self.indent_level += 1
        res: list[str] = []
        for s in stmts:
            res.extend(self.gen_stmt(s))
        self.indent_level -= 1
        if new_scope:
            self.pop_scope()
        return res

    def gen_func_def(self, fn: ast.FuncDef) -> list[str]:
        self.declare(fn.name)
        export_prefix = "export " if (fn.exported and self.indent_level == 0) else ""
        async_prefix = "async " if fn.is_async else ""
        star_suffix = "*" if fn.is_generator else ""

        param_names = {p.name for p in fn.params if p.kind not in ("kwonly_sep", "posonly_sep")}
        param_strs = [self.gen_param(p) for p in fn.params if p.kind not in ("kwonly_sep", "posonly_sep")]

        self.push_scope(param_names)
        lines: list[str] = []

        if self.in_class:
            if fn.method_kind == "init":
                header = f"{self.ind()}constructor({', '.join(param_strs)}) {{"
            elif fn.method_kind in ("static", "classmethod"):
                header = f"{self.ind()}static {async_prefix}{star_suffix}{fn.name}({', '.join(param_strs)}) {{"
            elif fn.method_kind == "property":
                header = f"{self.ind()}get {fn.name}() {{"
            elif fn.method_kind == "setter":
                header = f"{self.ind()}set {fn.name}({', '.join(param_strs)}) {{"
            else:
                header = f"{self.ind()}{async_prefix}{star_suffix}{fn.name}({', '.join(param_strs)}) {{"
        else:
            header = f"{self.ind()}{export_prefix}{async_prefix}function{star_suffix} {fn.name}({', '.join(param_strs)}) {{"

        lines.append(header)
        lines.extend(self.gen_block(fn.body, new_scope=False))
        lines.append(f"{self.ind()}}}")

        # Apply decorators if present outside class
        if fn.decorators and not self.in_class:
            for dec in reversed(fn.decorators):
                lines.append(f"{self.ind()}{fn.name} = {self.gen_expr(dec)}({fn.name});")

        self.pop_scope()
        return lines

    def gen_param(self, p: ast.Param) -> str:
        prefix = "..." if p.kind == "vararg" else ""
        s = f"{prefix}{p.name}"
        if p.default is not None:
            s += f" = {self.gen_expr(p.default)}"
        return s

    def gen_class_def(self, cls: ast.ClassDef) -> list[str]:
        self.declare(cls.name)
        self.known_classes.add(cls.name)
        export_prefix = "export " if (cls.exported and self.indent_level == 0) else ""
        ext_part = f" extends {self.gen_expr(cls.bases[0])}" if cls.bases else ""

        lines = [f"{self.ind()}{export_prefix}class {cls.name}{ext_part} {{"]
        prev_in_class = self.in_class
        self.in_class = True
        self.indent_level += 1

        # If dataclass `$$C(id:i, name:s="a")`, auto-generate constructor!
        if cls.is_dataclass and cls.fields:
            p_strs = [self.gen_param(f) for f in cls.fields]
            lines.append(f"{self.ind()}constructor({', '.join(p_strs)}) {{")
            self.indent_level += 1
            for f in cls.fields:
                lines.append(f"{self.ind()}this.{f.name} = {f.name};")
            self.indent_level -= 1
            lines.append(f"{self.ind()}}}")

        for s in cls.body:
            lines.extend(self.gen_stmt(s))

        self.indent_level -= 1
        self.in_class = prev_in_class
        lines.append(f"{self.ind()}}}")
        return lines

    def gen_if_stmt(self, stmt: ast.IfStmt) -> list[str]:
        lines: list[str] = []
        for idx, br in enumerate(stmt.branches):
            kw = "if" if idx == 0 else "} else if"
            lines.append(f"{self.ind()}{kw} ({self.gen_expr(br.cond)}) {{")
            lines.extend(self.gen_block(br.body))
        if stmt.else_body is not None:
            lines.append(f"{self.ind()}}} else {{")
            lines.extend(self.gen_block(stmt.else_body))
        lines.append(f"{self.ind()}}}")
        return lines

    def gen_match_stmt(self, stmt: ast.MatchStmt) -> list[str]:
        # Compile `?? subject { pat ? guard => body }` to a clean block with `__match_val`
        lines = [f"{self.ind()}{{", f"{self.ind()}{self.indent_str}const __match_val = {self.gen_expr(stmt.subject)};"]
        self.indent_level += 1
        for idx, c in enumerate(stmt.cases):
            kw = "if" if idx == 0 else "} else if"
            is_wildcard = isinstance(c.pattern, ast.Ident) and c.pattern.name == "_"
            is_capture = isinstance(c.pattern, ast.Ident) and not is_wildcard

            if is_wildcard and c.guard is None:
                if idx == 0:
                    lines.append(f"{self.ind()}if (true) {{")
                else:
                    lines.append(f"{self.ind()}}} else {{")
                lines.extend(self.gen_block(c.body))
                break
            elif is_capture:
                self.push_scope({c.pattern.name})
                cond = "true"
                if c.guard is not None:
                    # Replace capture var in guard or bind inside
                    cond = f"((({c.pattern.name}) => ({self.gen_expr(c.guard)}))(__match_val))"
                lines.append(f"{self.ind()}{kw} ({cond}) {{")
                self.indent_level += 1
                lines.append(f"{self.ind()}const {c.pattern.name} = __match_val;")
                for s in c.body:
                    lines.extend(self.gen_stmt(s))
                self.indent_level -= 1
                self.pop_scope()
            else:
                cond = f"__match_val === {self.gen_expr(c.pattern)}"
                if c.guard is not None:
                    cond = f"({cond}) && ({self.gen_expr(c.guard)})"
                lines.append(f"{self.ind()}{kw} ({cond}) {{")
                lines.extend(self.gen_block(c.body))
        if stmt.cases:
            lines.append(f"{self.ind()}}}")
        self.indent_level -= 1
        lines.append(f"{self.ind()}}}")
        return lines

    def gen_for_stmt(self, stmt: ast.ForStmt) -> list[str]:
        # Optimize `% i <- 0..n` or `% i <- ..n` into native JS `for (let i = ...; ...)`!
        if not stmt.is_async and isinstance(stmt.iter, ast.RangeExpr) and isinstance(stmt.target, ast.Ident):
            var = stmt.target.name
            if var == "_":
                var = "__i"
            start_s = self.gen_expr(stmt.iter.start) if stmt.iter.start is not None else "0"
            stop_s = self.gen_expr(stmt.iter.stop)
            step_s = self.gen_expr(stmt.iter.step) if stmt.iter.step is not None else "1"
            lines = [f"{self.ind()}for (let {var} = {start_s}; {var} < {stop_s}; {var} += {step_s}) {{"]
            self.push_scope({var})
            lines.extend(self.gen_block(stmt.body, new_scope=False))
            self.pop_scope()
            lines.append(f"{self.ind()}}}")
            return lines

        await_part = "await " if stmt.is_async else ""
        tgt_s = self._gen_destructure_target(stmt.target)
        bound_names: set[str] = set()
        if isinstance(stmt.target, ast.Ident):
            bound_names.add(stmt.target.name)
        elif isinstance(stmt.target, ast.TupleExpr):
            bound_names.update(e.name for e in stmt.target.elts if isinstance(e, ast.Ident))

        lines = [f"{self.ind()}for {await_part}(const {tgt_s} of {self.gen_expr(stmt.iter)}) {{"]
        self.push_scope(bound_names)
        lines.extend(self.gen_block(stmt.body, new_scope=False))
        self.pop_scope()
        lines.append(f"{self.ind()}}}")
        return lines

    def gen_while_stmt(self, stmt: ast.WhileStmt) -> list[str]:
        lines = [f"{self.ind()}while ({self.gen_expr(stmt.cond)}) {{"]
        lines.extend(self.gen_block(stmt.body))
        lines.append(f"{self.ind()}}}")
        return lines

    def gen_try_stmt(self, stmt: ast.TryStmt) -> list[str]:
        lines = [f"{self.ind()}try {{"]
        lines.extend(self.gen_block(stmt.body))
        if stmt.handlers:
            err_var = stmt.handlers[0].name or "__myna_err"
            lines.append(f"{self.ind()}}} catch ({err_var}) {{")
            self.push_scope({err_var})
            if len(stmt.handlers) == 1 and (
                stmt.handlers[0].exc_type is None
                or (isinstance(stmt.handlers[0].exc_type, ast.Ident) and stmt.handlers[0].exc_type.name in ("Exception", "Error", "AssertionError", "ValueError"))
            ):
                lines.extend(self.gen_block(stmt.handlers[0].body, new_scope=False))
            else:
                lines.extend(self.gen_block(stmt.handlers[0].body, new_scope=False))
            self.pop_scope()
        if stmt.finally_body is not None:
            lines.append(f"{self.ind()}}} finally {{")
            lines.extend(self.gen_block(stmt.finally_body))
        lines.append(f"{self.ind()}}}")
        return lines

    def gen_with_stmt(self, stmt: ast.WithStmt) -> list[str]:
        lines = [f"{self.ind()}{{"]
        self.indent_level += 1
        self.push_scope()
        for idx, item in enumerate(stmt.items):
            var_s = self.gen_expr(item.optional_vars) if item.optional_vars is not None else f"__ctx_{idx}"
            if item.optional_vars is not None and isinstance(item.optional_vars, ast.Ident):
                self.declare(item.optional_vars.name)
            lines.append(f"{self.ind()}const {var_s} = {self.gen_expr(item.context_expr)};")
        lines.append(f"{self.ind()}try {{")
        lines.extend(self.gen_block(stmt.body, new_scope=False))
        lines.append(f"{self.ind()}}} finally {{")
        self.indent_level += 1
        for idx, item in enumerate(stmt.items):
            var_s = self.gen_expr(item.optional_vars) if item.optional_vars is not None else f"__ctx_{idx}"
            lines.append(f"{self.ind()}{var_s}?.close?.();")
        self.indent_level -= 1
        lines.append(f"{self.ind()}}}")
        self.pop_scope()
        self.indent_level -= 1
        lines.append(f"{self.ind()}}}")
        return lines

    # ========================================================================
    # Expressions
    # ========================================================================

    def gen_expr(self, expr: ast.Expr, parent_prec: int = 0) -> str:
        if isinstance(expr, ast.Literal):
            if expr.kind == "none":
                return "null"
            if expr.kind == "undefined":
                return "undefined"
            if expr.kind == "bool":
                return "true" if expr.value else "false"
            if expr.kind == "bytes":
                return f"new Uint8Array([{', '.join(str(ord(c)) for c in expr.value)}])"
            return repr(expr.value)

        if isinstance(expr, ast.FString):
            buf: list[str] = []
            for p in expr.parts:
                if isinstance(p, str):
                    escaped = p.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
                    buf.append(escaped)
                else:
                    sub_expr, fmt_spec = p
                    sub_s = self.gen_expr(sub_expr)
                    if fmt_spec and fmt_spec.endswith("f") and "." in fmt_spec:
                        digits = fmt_spec.split(".")[1][:-1]
                        buf.append(f"${{({sub_s}).toFixed({digits})}}")
                    else:
                        buf.append(f"${{{sub_s}}}")
            return f"`{''.join(buf)}`"

        if isinstance(expr, ast.Ident):
            if expr.name == "@j":
                return "JSON.parse"
            if expr.name == "@J":
                return "JSON.stringify"
            if expr.name == "@str":
                return "String"
            if expr.name == "@int":
                return "Math.trunc"
            if expr.name == "@float":
                return "Number"
            if expr.name == "@bool":
                return "Boolean"
            if expr.name == "@abs":
                return "Math.abs"
            if expr.name == "@min":
                return "Math.min"
            if expr.name == "@max":
                return "Math.max"
            if expr.name == "@rnd":
                return "Math.round"
            return expr.name

        if isinstance(expr, ast.SelfAttr):
            return f"this.{expr.attr}"

        if isinstance(expr, ast.SuperAttr):
            if expr.attr == "init":
                return "super"
            return f"super.{expr.attr}"

        if isinstance(expr, ast.UnaryOp):
            if expr.op == "#":
                self.needs_len_helper = True
                return f"__myna_len({self.gen_expr(expr.operand)})"
            if expr.op == "!":
                return f"!({self.gen_expr(expr.operand)})"
            if expr.op == "~":
                return f"(await {self.gen_expr(expr.operand, 85)})"
            if expr.op == "~|":
                return f"~{self.gen_expr(expr.operand, 80)}"
            if expr.op in ("*", "**"):
                return f"...{self.gen_expr(expr.operand, 80)}"
            return f"{expr.op}{self.gen_expr(expr.operand, 80)}"

        if isinstance(expr, ast.BinaryOp):
            if expr.op == "//":
                return f"Math.floor({self.gen_expr(expr.left, 60)} / {self.gen_expr(expr.right, 61)})"
            prec = 50
            s = f"{self.gen_expr(expr.left, prec)} {expr.op} {self.gen_expr(expr.right, prec + 1)}"
            return f"({s})" if parent_prec > prec else s

        if isinstance(expr, ast.CompareOp):
            if len(expr.ops) == 1 and expr.ops[0] == ":?":
                lhs = self.gen_expr(expr.left)
                return f"({self._js_isinstance(lhs, expr.comparators[0])})"

            parts: list[str] = []
            cur_left = expr.left
            for op, comp in zip(expr.ops, expr.comparators):
                l_s = self.gen_expr(cur_left, 31)
                r_s = self.gen_expr(comp, 31)
                if op in ("==", "==="):
                    parts.append(f"{l_s} === {r_s}")
                elif op in ("!=", "!=="):
                    parts.append(f"{l_s} !== {r_s}")
                elif op == "<-":
                    self.needs_in_helper = True
                    parts.append(f"__myna_in({l_s}, {r_s})")
                elif op == "!<-":
                    self.needs_in_helper = True
                    parts.append(f"!__myna_in({l_s}, {r_s})")
                else:
                    parts.append(f"{l_s} {op} {r_s}")
                cur_left = comp
            s = " && ".join(parts)
            return f"({s})" if parent_prec > 30 else s

        if isinstance(expr, ast.TernaryOp):
            s = f"{self.gen_expr(expr.cond, 11)} ? {self.gen_expr(expr.true_expr, 11)} : {self.gen_expr(expr.false_expr, 10)}"
            return f"({s})" if parent_prec > 10 else s

        if isinstance(expr, ast.RangeExpr):
            self.needs_range_helper = True
            stop_s = self.gen_expr(expr.stop)
            if expr.start is None and expr.step is None:
                return f"__myna_range({stop_s})"
            start_s = self.gen_expr(expr.start) if expr.start is not None else "0"
            if expr.step is not None:
                return f"__myna_range({start_s}, {stop_s}, {self.gen_expr(expr.step)})"
            return f"__myna_range({start_s}, {stop_s})"

        if isinstance(expr, ast.PipeExpr):
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
            return self.gen_call(expr)

        if isinstance(expr, ast.Attribute):
            val_s = self.gen_expr(expr.value, 90)
            op = "?." if expr.optional else "."
            return f"{val_s}{op}{expr.attr}"

        if isinstance(expr, ast.Subscript):
            val_s = self.gen_expr(expr.value, 90)
            if isinstance(expr.slice, ast.Slice):
                lo = self.gen_expr(expr.slice.lower) if expr.slice.lower is not None else "0"
                if expr.slice.upper is not None:
                    return f"{val_s}.slice({lo}, {self.gen_expr(expr.slice.upper)})"
                return f"{val_s}.slice({lo})"
            return f"{val_s}[{self.gen_expr(expr.slice)}]"

        if isinstance(expr, ast.ListExpr):
            return f"[{', '.join(self.gen_expr(e) for e in expr.elts)}]"

        if isinstance(expr, ast.TupleExpr):
            return f"[{', '.join(self.gen_expr(e) for e in expr.elts)}]"

        if isinstance(expr, ast.SetExpr):
            return f"new Set([{', '.join(self.gen_expr(e) for e in expr.elts)}])"

        if isinstance(expr, ast.DictExpr):
            items: list[str] = []
            for k, v in zip(expr.keys, expr.values):
                if k is None:
                    items.append(f"...{self.gen_expr(v)}")
                elif isinstance(k, ast.Literal) and k.kind == "str" and isinstance(k.value, str) and k.value.isidentifier():
                    items.append(f"{k.value}: {self.gen_expr(v)}")
                else:
                    items.append(f"[{self.gen_expr(k)}]: {self.gen_expr(v)}")
            return f"({{{', '.join(items)}}})"

        if isinstance(expr, ast.ListComp):
            return self.gen_comp_chain(expr.elt, expr.clauses)

        if isinstance(expr, ast.GenExp):
            return self.gen_comp_chain(expr.elt, expr.clauses)

        if isinstance(expr, ast.SetComp):
            return f"new Set({self.gen_comp_chain(expr.elt, expr.clauses)})"

        if isinstance(expr, ast.DictComp):
            pair = ast.TupleExpr(elts=[expr.key, expr.value])
            return f"Object.fromEntries({self.gen_comp_chain(pair, expr.clauses)})"

        if isinstance(expr, ast.Lambda):
            p_strs = [self.gen_param(p) for p in expr.params]
            s = f"({', '.join(p_strs)}) => ({self.gen_expr(expr.body)})"
            return f"({s})" if parent_prec > 5 else s

        if isinstance(expr, ast.NamedExpr):
            return f"({self.gen_expr(expr.target)} = {self.gen_expr(expr.value)})"

        raise ValueError(f"Unsupported expression node for JS: {expr!r}")

    def _js_isinstance(self, subject: str, expr: ast.Expr) -> str:
        if isinstance(expr, ast.Ident):
            if expr.name in ("i", "f", "int", "float"):
                return f"(typeof {subject} === 'number')"
            if expr.name in ("s", "str"):
                return f"(typeof {subject} === 'string')"
            if expr.name in ("b", "bool"):
                return f"(typeof {subject} === 'boolean')"
            if expr.name in ("B", "bytes"):
                return f"({subject} instanceof Uint8Array)"
            if expr.name in ("A", "Any"):
                return "true"
            if expr.name in ("N", "None"):
                return f"({subject} === null)"
        if isinstance(expr, ast.TupleExpr):
            # `(A, B)` in a runtime check is a union; bind the subject once so it is
            # not evaluated repeatedly inside the `||` chain.
            inner = " || ".join(self._js_isinstance("__v", e) for e in expr.elts) or "false"
            return f"((__v) => {inner})({subject})"
        # Compound type expressions check their runtime origin type.
        if isinstance(expr, ast.ListExpr):
            return f"Array.isArray({subject})"
        if isinstance(expr, ast.SetExpr):
            return f"({subject} instanceof Set)"
        if isinstance(expr, ast.DictExpr):
            self.needs_is_dict_helper = True
            return f"__myna_is_dict({subject})"
        if isinstance(expr, ast.Subscript):
            return self._js_isinstance(subject, expr.value)
        return f"({subject} instanceof {self.gen_expr(expr)})"

    def gen_call(self, call: ast.Call) -> str:
        if isinstance(call.func, ast.Ident):
            fn = call.func.name
            if fn == "@u8" and len(call.args) == 1:
                return f"new TextEncoder().encode({self.gen_expr(call.args[0])})"
            if fn == "@u8d" and len(call.args) == 1:
                return f"new TextDecoder().decode({self.gen_expr(call.args[0])})"
            if fn == "@sum" and len(call.args) == 1:
                return f"Array.from({self.gen_expr(call.args[0])}).reduce((__a, __b) => __a + __b, 0)"
            if fn == "@list" and len(call.args) == 1:
                return f"Array.from({self.gen_expr(call.args[0])})"
            if fn == "@set" and len(call.args) == 1:
                return f"new Set({self.gen_expr(call.args[0])})"
            if fn == "@srt" and len(call.args) >= 1:
                arr_s = f"[...{self.gen_expr(call.args[0])}]"
                key_fn: Optional[ast.Expr] = None
                for k, v in call.keywords:
                    if k == "key":
                        key_fn = v
                if key_fn is not None:
                    kf_s = self.gen_expr(key_fn)
                    return f"{arr_s}.sort((__a, __b) => {{ const __ka = ({kf_s})(__a), __kb = ({kf_s})(__b); return __ka < __kb ? -1 : (__ka > __kb ? 1 : 0); }})"
                return f"{arr_s}.sort()"

            # If calling a known class `User(1, "Alice")`, automatically emit `new User(1, "Alice")` in JS!
            if fn in self.known_classes:
                args_s = [self.gen_expr(a) for a in call.args]
                return f"new {fn}({', '.join(args_s)})"

        func_s = "console.log" if (isinstance(call.func, ast.Ident) and call.func.name == "p") else self.gen_expr(call.func, 90)
        if isinstance(call.func, ast.Attribute) and not call.keywords:
            obj_s = self.gen_expr(call.func.value, 90)
            m_name = call.func.attr
            if m_name == "lower" and not call.args:
                return f"{obj_s}.toLowerCase()"
            if m_name == "upper" and not call.args:
                return f"{obj_s}.toUpperCase()"
            if m_name == "strip" and not call.args:
                return f"{obj_s}.trim()"
            if m_name == "startswith" and len(call.args) == 1:
                return f"{obj_s}.startsWith({self.gen_expr(call.args[0])})"
            if m_name == "endswith" and len(call.args) == 1:
                return f"{obj_s}.endsWith({self.gen_expr(call.args[0])})"
            if m_name == "append" and len(call.args) == 1:
                return f"{obj_s}.push({self.gen_expr(call.args[0])})"
            if m_name == "values" and not call.args:
                return f"Object.values({obj_s})"
            if m_name == "keys" and not call.args:
                return f"Object.keys({obj_s})"
            if m_name == "items" and not call.args:
                return f"Object.entries({obj_s})"
        arg_parts = [self.gen_expr(a) for a in call.args]
        if call.keywords:
            kw_items: list[str] = []
            for k, v in call.keywords:
                if k is None:
                    kw_items.append(f"...{self.gen_expr(v)}")
                else:
                    kw_items.append(f"{k}: {self.gen_expr(v)}")
            arg_parts.append(f"{{{', '.join(kw_items)}}}")
        return f"{func_s}({', '.join(arg_parts)})"

    def gen_comp_chain(self, elt: ast.Expr, clauses: list[ast.CompClause]) -> str:
        # Recursively build `.filter(...).map(...)` or `.flatMap(...)` for nested clauses
        c = clauses[0]
        iter_s = f"Array.from({self.gen_expr(c.iter)})" if isinstance(c.iter, ast.RangeExpr) else self.gen_expr(c.iter, 90)
        param_s = self._gen_destructure_target(c.target)
        if not param_s.startswith("["):
            param_s = f"({param_s})"
        else:
            param_s = f"({param_s})"

        for cond in c.conds:
            iter_s = f"{iter_s}.filter({param_s} => ({self.gen_expr(cond)}))"

        if len(clauses) == 1:
            return f"{iter_s}.map({param_s} => ({self.gen_expr(elt)}))"
        inner = self.gen_comp_chain(elt, clauses[1:])
        return f"{iter_s}.flatMap({param_s} => {inner})"


def compile_to_js(mod: ast.Module) -> str:
    enforce_module_target(mod, "js")
    gen = JSGenerator()
    return gen.generate(expand_target_blocks(mod, "js"))
