"""Python-to-Myna decompiler/compressor using Python's built-in `ast` module."""

from __future__ import annotations
import ast as py_ast
from typing import Optional


class DecompileError(Exception):
    """Raised when a Python construct cannot be represented faithfully in Myna."""

    def __init__(self, node: py_ast.AST, message: str):
        line = getattr(node, "lineno", None)
        location = f" at line {line}" if line is not None else ""
        super().__init__(f"DecompileError{location}: {message}")
        self.node = node
        self.line = line


REVERSE_TYPE_SHORTHANDS = {
    "int": "i",
    "float": "f",
    "str": "s",
    "bool": "b",
    "bytes": "B",
    "Any": "A",
    "None": "N",
}

REVERSE_BUILTIN_SHORTHANDS = {
    "print": "p",
    "enumerate": "@enum",
    "zip": "@zip",
    "map": "@map",
    "filter": "@flt",
    "sorted": "@srt",
    "reversed": "@rev",
    "sum": "@sum",
    "min": "@min",
    "max": "@max",
    "abs": "@abs",
    "all": "@all",
    "any": "@any",
    "str": "@str",
    "int": "@int",
    "float": "@float",
    "bool": "@bool",
    "list": "@list",
    "dict": "@dict",
    "set": "@set",
    "tuple": "@tuple",
    "type": "@type",
    "repr": "@repr",
    "open": "@open",
    "input": "@inp",
    "round": "@rnd",
    "getattr": "@get",
    "setattr": "@set_a",
    "hasattr": "@has",
    "delattr": "@del_a",
}


class _DeadLocalInliner(py_ast.NodeTransformer):
    """Inlines single-use temporary variables within basic blocks (`x = expr; return x` -> `return expr`)."""

    def _inline_block(self, stmts: list[py_ast.stmt]) -> list[py_ast.stmt]:
        # Count total reads of each local variable across the statement list
        read_counts: dict[str, int] = {}
        store_counts: dict[str, int] = {}
        for s in stmts:
            for n in py_ast.walk(s):
                if isinstance(n, py_ast.Name):
                    if isinstance(n.ctx, py_ast.Load):
                        read_counts[n.id] = read_counts.get(n.id, 0) + 1
                    elif isinstance(n.ctx, py_ast.Store):
                        store_counts[n.id] = store_counts.get(n.id, 0) + 1

        out: list[py_ast.stmt] = []
        i = 0
        while i < len(stmts):
            cur = stmts[i]
            # Check if `cur` is `var = expr` (or `var: T = expr`) where `var` is stored once and read once in `stmts[i+1]`
            var_name: Optional[str] = None
            rhs_val: Optional[py_ast.expr] = None
            if isinstance(cur, py_ast.Assign) and len(cur.targets) == 1 and isinstance(cur.targets[0], py_ast.Name):
                var_name = cur.targets[0].id
                rhs_val = cur.value
            elif isinstance(cur, py_ast.AnnAssign) and isinstance(cur.target, py_ast.Name) and cur.value is not None:
                var_name = cur.target.id
                rhs_val = cur.value

            if (
                var_name
                and rhs_val is not None
                and store_counts.get(var_name, 0) == 1
                and read_counts.get(var_name, 0) == 1
                and i + 1 < len(stmts)
                and self._reads_var_directly(stmts[i + 1], var_name)
                and not any(isinstance(n, py_ast.JoinedStr) for n in py_ast.walk(rhs_val))
            ):
                stmts[i + 1] = self._replace_var(stmts[i + 1], var_name, rhs_val)
                i += 1
                continue

            # Also check if `cur` is `a, b = expr` followed by `assert ...; print(...)` where `print` only logs status:
            out.append(cur)
            i += 1
        return out

    def _reads_var_directly(self, stmt: py_ast.stmt, var_name: str) -> bool:
        # Don't inline into loops or nested function/class defs where evaluation count changes
        if isinstance(stmt, (py_ast.For, py_ast.AsyncFor, py_ast.While, py_ast.FunctionDef, py_ast.AsyncFunctionDef, py_ast.ClassDef)):
            return False
        for n in py_ast.walk(stmt):
            if isinstance(n, (py_ast.Lambda, py_ast.ListComp, py_ast.SetComp, py_ast.DictComp, py_ast.GeneratorExp)):
                # Check if var_name is read inside a comprehension's elt/filter (iter is evaluated once, so iter is safe!)
                for sub in py_ast.walk(n):
                    if isinstance(sub, py_ast.Name) and sub.id == var_name and isinstance(sub.ctx, py_ast.Load):
                        if isinstance(n, (py_ast.ListComp, py_ast.SetComp, py_ast.GeneratorExp, py_ast.DictComp)):
                            if any(
                                sub is gen_node
                                for g in n.generators
                                for gen_node in py_ast.walk(g.iter)
                                if not g.ifs
                            ):
                                continue
                        return False
            if isinstance(n, py_ast.Name) and n.id == var_name and isinstance(n.ctx, py_ast.Load):
                return True
        return False

    def _replace_var(self, stmt: py_ast.stmt, var_name: str, replacement: py_ast.expr) -> py_ast.stmt:
        class _Replacer(py_ast.NodeTransformer):
            def visit_Name(self, node: py_ast.Name) -> py_ast.AST:
                if node.id == var_name and isinstance(node.ctx, py_ast.Load):
                    return replacement
                return node
        return _Replacer().visit(stmt)

    def visit_FunctionDef(self, node: py_ast.FunctionDef) -> py_ast.AST:
        self.generic_visit(node)
        node.body = self._inline_block(node.body)
        return node

    def visit_AsyncFunctionDef(self, node: py_ast.AsyncFunctionDef) -> py_ast.AST:
        self.generic_visit(node)
        node.body = self._inline_block(node.body)
        return node

    def visit_With(self, node: py_ast.With) -> py_ast.AST:
        self.generic_visit(node)
        node.body = self._inline_block(node.body)
        return node

    def visit_ExceptHandler(self, node: py_ast.ExceptHandler) -> py_ast.AST:
        self.generic_visit(node)
        node.body = self._inline_block(node.body)
        return node

    def visit_If(self, node: py_ast.If) -> py_ast.AST:
        self.generic_visit(node)
        node.body = self._inline_block(node.body)
        node.orelse = self._inline_block(node.orelse)
        return node

    def visit_Try(self, node: py_ast.Try) -> py_ast.AST:
        self.generic_visit(node)
        node.body = self._inline_block(node.body)
        node.orelse = self._inline_block(node.orelse)
        node.finalbody = self._inline_block(node.finalbody)
        return node

    def visit_Match(self, node: py_ast.Match) -> py_ast.AST:
        self.generic_visit(node)
        for c in node.cases:
            c.body = self._inline_block(c.body)
        return node


class _LocalRenamer(py_ast.NodeTransformer):
    """Safely renames function-local variables to compact 1-2 char names while preserving parameters, globals, and exports."""

    SHORT_NAMES = [c for c in "abcdefghijklmnopqrstuvwxyz" if c not in ("i", "f", "s", "b", "p")] + [
        f"{c1}{c2}" for c1 in "abcdefghjklmnoqrtuvwxyz" for c2 in "aeiou"
    ]

    def __init__(self, tree: py_ast.Module, preserve_public: bool = False):
        self.preserve_public = preserve_public
        self.module_globals: set[str] = set()
        for stmt in tree.body:
            if isinstance(stmt, (py_ast.FunctionDef, py_ast.AsyncFunctionDef, py_ast.ClassDef)):
                self.module_globals.add(stmt.name)
            elif isinstance(stmt, py_ast.Assign):
                for t in stmt.targets:
                    for n in py_ast.walk(t):
                        if isinstance(n, py_ast.Name):
                            self.module_globals.add(n.id)
            elif isinstance(stmt, py_ast.AnnAssign) and isinstance(stmt.target, py_ast.Name):
                self.module_globals.add(stmt.target.id)
            elif isinstance(stmt, (py_ast.Import, py_ast.ImportFrom)):
                for a in stmt.names:
                    self.module_globals.add(a.asname or a.name.split(".")[0])

        # Find all keyword argument names passed in any Call across the module so we know which parameter names are safe to minify
        self.kwarg_called_names: set[str] = set()
        for n in py_ast.walk(tree):
            if isinstance(n, py_ast.Call):
                for kw in n.keywords:
                    if kw.arg:
                        self.kwarg_called_names.add(kw.arg)

        # Also rename private helper methods/attributes (`_foo`) safely across the whole tree!
        self._minify_private_members(tree)

    def _minify_private_members(self, tree: py_ast.Module) -> None:
        # Collect class-defined private methods (`def _foo`), private instance attributes (`self._bar`),
        # and module-internal functions/classes/constants (since a standalone script or internal module symbols are only referenced inside `tree`)
        renamable_globals: set[str] = set()
        renamable_methods_and_attrs: set[str] = set()
        used: set[str] = set()
        # Preserve HTTP handler methods (`do_GET`, `do_POST`, `do_DELETE`, `log_message`), stdlib method names, and `__all__`
        protected_names = {
            "dataclass", "Optional", "Any", "List", "Dict", "Set", "Tuple", "Union",
            "do_GET", "do_POST", "do_DELETE", "do_PUT", "do_PATCH", "do_HEAD", "do_OPTIONS", "log_message",
            "send_response", "send_header", "end_headers", "serve_forever", "shutdown", "server_close",
            "wfile", "rfile", "headers", "path", "server_port", "status", "code", "values", "get", "split", "lower", "strip", "read", "write", "start", "join", "encode", "decode",
        }
        for stmt in tree.body:
            if isinstance(stmt, py_ast.Assign):
                for t in stmt.targets:
                    if isinstance(t, py_ast.Name) and t.id == "__all__" and isinstance(stmt.value, (py_ast.List, py_ast.Tuple)):
                        for elt in stmt.value.elts:
                            if isinstance(elt, py_ast.Constant) and isinstance(elt.value, str):
                                protected_names.add(elt.value)

        # Find user-defined classes without external base classes (whose methods/attributes are 100% controlled by this file)
        pure_user_classes: list[py_ast.ClassDef] = []
        for stmt in tree.body:
            if isinstance(stmt, (py_ast.FunctionDef, py_ast.AsyncFunctionDef)):
                if len(stmt.name) > 2 and stmt.name not in protected_names and not stmt.name.startswith("__"):
                    renamable_globals.add(stmt.name)
            elif isinstance(stmt, py_ast.ClassDef):
                if len(stmt.name) > 2 and stmt.name not in protected_names:
                    renamable_globals.add(stmt.name)
                if not stmt.bases and not self.preserve_public:
                    pure_user_classes.append(stmt)
                    # Only rename methods (not dataclass fields whose names appear in `to_dict()` / external JSON)
                    is_dc = any(isinstance(d, py_ast.Name) and d.id == "dataclass" for d in stmt.decorator_list)
                    for item in stmt.body:
                        if isinstance(item, (py_ast.FunctionDef, py_ast.AsyncFunctionDef)):
                            if not item.name.startswith("__") and len(item.name) > 2 and item.name not in protected_names:
                                renamable_methods_and_attrs.add(item.name)
                        if not is_dc:
                            for sub in py_ast.walk(item):
                                if (
                                    isinstance(sub, py_ast.Attribute)
                                    and isinstance(sub.ctx, py_ast.Store)
                                    and isinstance(sub.value, py_ast.Name)
                                    and sub.value.id in ("self", "cls")
                                    and len(sub.attr) > 2
                                    and sub.attr not in protected_names
                                ):
                                    renamable_methods_and_attrs.add(sub.attr)
            elif isinstance(stmt, py_ast.Assign):
                for t in stmt.targets:
                    if isinstance(t, py_ast.Name) and len(t.id) > 2 and t.id not in protected_names and not t.id.startswith("__"):
                        renamable_globals.add(t.id)

        if self.preserve_public:
            renamable_globals = {g for g in renamable_globals if g.startswith("_")}

        priv_defs: set[str] = set()
        for n in py_ast.walk(tree):
            if isinstance(n, (py_ast.FunctionDef, py_ast.AsyncFunctionDef)):
                used.add(n.name)
                if n.name.startswith("_") and not n.name.startswith("__") and len(n.name) > 2:
                    priv_defs.add(n.name)
            elif isinstance(n, py_ast.Attribute):
                used.add(n.attr)
                if n.attr.startswith("_") and not n.attr.startswith("__") and len(n.attr) > 2:
                    if isinstance(n.value, py_ast.Name) and n.value.id in ("self", "cls"):
                        priv_defs.add(n.attr)
            elif isinstance(n, py_ast.Name):
                used.add(n.id)

        priv_map: dict[str, str] = {}
        idx = 0
        priv_pool = [f"{c1}{c2}" for c1 in "klmnprtvwz" for c2 in "aeiou"]
        for name in sorted(priv_defs | renamable_methods_and_attrs):
            while idx < len(priv_pool) and (priv_pool[idx] in used or priv_pool[idx] in priv_map.values()):
                idx += 1
            if idx < len(priv_pool):
                priv_map[name] = priv_pool[idx]
                idx += 1

        glob_pool = [c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c not in ("T", "F", "N", "U", "A", "B")]
        g_idx = 0
        for name in sorted(renamable_globals):
            while g_idx < len(glob_pool) and (glob_pool[g_idx] in used or glob_pool[g_idx] in priv_map.values()):
                g_idx += 1
            if g_idx < len(glob_pool):
                priv_map[name] = glob_pool[g_idx]
                self.module_globals.discard(name)
                self.module_globals.add(glob_pool[g_idx])
                g_idx += 1

        for stmt in tree.body:
            if isinstance(stmt, py_ast.ImportFrom):
                for a in stmt.names:
                    if not self.preserve_public and a.asname is None and len(a.name) > 5 and a.name not in protected_names:
                        while g_idx < len(glob_pool) and (glob_pool[g_idx] in used or glob_pool[g_idx] in priv_map.values()):
                            g_idx += 1
                        if g_idx < len(glob_pool):
                            a.asname = glob_pool[g_idx]
                            priv_map[a.name] = a.asname
                            self.module_globals.discard(a.name)
                            self.module_globals.add(a.asname)
                            g_idx += 1
            elif isinstance(stmt, py_ast.Import):
                for a in stmt.names:
                    if not self.preserve_public and a.asname is None and len(a.name) > 5 and "." not in a.name and a.name not in ("json",):
                        while g_idx < len(glob_pool) and (glob_pool[g_idx] in used or glob_pool[g_idx] in priv_map.values()):
                            g_idx += 1
                        if g_idx < len(glob_pool):
                            a.asname = glob_pool[g_idx]
                            priv_map[a.name] = a.asname
                            self.module_globals.discard(a.name)
                            self.module_globals.add(a.asname)
                            g_idx += 1

        if not priv_map:
            return

        for n in py_ast.walk(tree):
            if isinstance(n, (py_ast.FunctionDef, py_ast.AsyncFunctionDef, py_ast.ClassDef)) and n.name in priv_map:
                n.name = priv_map[n.name]
            elif isinstance(n, py_ast.Attribute) and n.attr in priv_map:
                n.attr = priv_map[n.attr]
            elif isinstance(n, py_ast.Name) and n.id in priv_map:
                n.id = priv_map[n.id]
            elif isinstance(n, py_ast.Constant) and isinstance(n.value, str) and n.value in priv_map:
                n.value = priv_map[n.value]

    def _minify_scope(
        self,
        stmts: list[py_ast.stmt],
        reserved: set[str],
        extra_renamable: Optional[set[str]] = None,
        arg_nodes: Optional[list[py_ast.arg]] = None,
    ) -> None:
        assigned: set[str] = set(extra_renamable or set())
        explicit_scopes: set[str] = set()
        used_names: set[str] = set(reserved) | self.module_globals

        for s in stmts:
            for n in py_ast.walk(s):
                if isinstance(n, (py_ast.Global, py_ast.Nonlocal)):
                    explicit_scopes.update(n.names)
                elif isinstance(n, py_ast.Name):
                    used_names.add(n.id)
                    if isinstance(n.ctx, py_ast.Store) and len(n.id) > 1 and not n.id.startswith("_"):
                        assigned.add(n.id)
                elif isinstance(n, py_ast.ExceptHandler) and n.name and len(n.name) > 1:
                    assigned.add(n.name)

        candidates = sorted(assigned - reserved - self.module_globals - explicit_scopes)
        mapping: dict[str, str] = {}
        pool_idx = 0
        for orig in candidates:
            while pool_idx < len(self.SHORT_NAMES) and (
                self.SHORT_NAMES[pool_idx] in used_names or self.SHORT_NAMES[pool_idx] in mapping.values()
            ):
                pool_idx += 1
            if pool_idx < len(self.SHORT_NAMES):
                mapping[orig] = self.SHORT_NAMES[pool_idx]
                pool_idx += 1

        if not mapping:
            return

        if arg_nodes:
            for a in arg_nodes:
                if a.arg in mapping:
                    a.arg = mapping[a.arg]

        for s in stmts:
            for n in py_ast.walk(s):
                if isinstance(n, py_ast.Name) and n.id in mapping:
                    n.id = mapping[n.id]
                elif isinstance(n, py_ast.ExceptHandler) and n.name in mapping:
                    n.name = mapping[n.name]

    def _minify_func(self, node: py_ast.FunctionDef | py_ast.AsyncFunctionDef) -> None:
        all_args = node.args.args + node.args.posonlyargs + node.args.kwonlyargs
        if node.args.vararg:
            all_args.append(node.args.vararg)
        if node.args.kwarg:
            all_args.append(node.args.kwarg)

        # Parameters that cannot be renamed (`self`, `cls`, or anything called by keyword in the module)
        protected_params = {"self", "cls"} | (self.kwarg_called_names & {a.arg for a in all_args})
        renamable_params = {a.arg for a in all_args if len(a.arg) > 1 and a.arg not in protected_params}
        self._minify_scope(node.body, protected_params, extra_renamable=renamable_params, arg_nodes=all_args)

    def visit_FunctionDef(self, node: py_ast.FunctionDef) -> py_ast.AST:
        self.generic_visit(node)
        self._minify_func(node)
        return node

    def visit_AsyncFunctionDef(self, node: py_ast.AsyncFunctionDef) -> py_ast.AST:
        self.generic_visit(node)
        self._minify_func(node)
        return node

    def visit_If(self, node: py_ast.If) -> py_ast.AST:
        self.generic_visit(node)
        if (
            isinstance(node.test, py_ast.Compare)
            and isinstance(node.test.left, py_ast.Name)
            and node.test.left.id == "__name__"
        ):
            self._minify_scope(node.body, set())
        return node

        if (
            isinstance(node.test, py_ast.Compare)
            and isinstance(node.test.left, py_ast.Name)
            and node.test.left.id == "__name__"
        ):
            self._minify_scope(node.body, set())
        return node
        self.generic_visit(node)
        return node
class PythonDecompiler:
    def __init__(self, compact: bool = True, minify_locals: bool = False):
        self.compact = compact
        self.minify_locals = minify_locals
        self.indent_level = 0
        self.in_class = False
        self.receiver_name: Optional[str] = None

    def ind(self) -> str:
        return "" if self.compact else ("  " * self.indent_level)

    def decompile(self, source: str) -> str:
        tree = py_ast.parse(source)
        if self.compact:
            _DeadLocalInliner().visit(tree)
            _LocalRenamer(tree, preserve_public=not self.minify_locals).visit(tree)
        elif self.minify_locals:
            _LocalRenamer(tree, preserve_public=False).visit(tree)
        lines: list[str] = []
        for stmt in tree.body:
            if self._is_auto_import(stmt):
                continue
            filtered = self._filter_json_import(stmt, source)
            if filtered is None:
                continue
            res = self.dec_stmt(filtered)
            if res:
                lines.append(res)
        return "\n".join(lines).rstrip() + "\n"

    def _is_auto_import(self, stmt: py_ast.stmt) -> bool:
        if isinstance(stmt, py_ast.ImportFrom):
            if stmt.module == "dataclasses" and len(stmt.names) == 1 and stmt.names[0].name == "dataclass":
                return True
            if stmt.module == "typing":
                auto_names = {"Optional", "Any", "List", "Dict", "Set", "Tuple", "Union"}
                if all(alias.name in auto_names for alias in stmt.names):
                    return True
        return False

    def _filter_json_import(self, stmt: py_ast.stmt, full_source: str) -> Optional[py_ast.stmt]:
        # If `json` is only used for `json.loads` / `json.dumps` (not `json.JSONDecodeError`), we can omit `<json`
        if isinstance(stmt, py_ast.Import) and "json.JSONDecodeError" not in full_source:
            rem = [a for a in stmt.names if not (a.name == "json" and a.asname is None)]
            if not rem:
                return None
            return py_ast.Import(names=rem)
        return stmt

    # ========================================================================
    # Statements
    # ========================================================================

    def dec_stmt(self, stmt: py_ast.stmt) -> str:
        if isinstance(stmt, py_ast.Pass):
            return f"{self.ind()}_"

        if isinstance(stmt, py_ast.Expr):
            # Skip docstrings in ultra-dense mode if desired, or keep as expressions
            return f"{self.ind()}{self.dec_expr(stmt.value)}"

        if isinstance(stmt, py_ast.Assign):
            tgts = "=".join(self.dec_target(t) for t in stmt.targets)
            if isinstance(stmt.value, py_ast.Tuple) and len(stmt.value.elts) > 1:
                val_s = ",".join(self.dec_expr(e) for e in stmt.value.elts)
            else:
                val_s = self.dec_expr(stmt.value)
            return f"{self.ind()}{tgts}={val_s}"

        if isinstance(stmt, py_ast.AnnAssign):
            tgt = self.dec_expr(stmt.target)
            t_ann = self.dec_type(stmt.annotation)
            if stmt.value is not None:
                return f"{self.ind()}{tgt}:{t_ann}={self.dec_expr(stmt.value)}"
            return f"{self.ind()}{tgt}:{t_ann}=N"

        if isinstance(stmt, py_ast.AugAssign):
            op = self._aug_op(stmt.op)
            if op is None:
                raise DecompileError(stmt, f"unsupported augmented operator: {type(stmt.op).__name__}")
            return f"{self.ind()}{self.dec_expr(stmt.target)}{op}={self.dec_expr(stmt.value)}"

        if isinstance(stmt, py_ast.Delete):
            tgts = ",".join(self.dec_expr(t) for t in stmt.targets)
            return f"{self.ind()}~{tgts}"

        if isinstance(stmt, py_ast.Global):
            return f"{self.ind()}@={','.join(stmt.names)}"

        if isinstance(stmt, py_ast.Nonlocal):
            return f"{self.ind()}^={','.join(stmt.names)}"

        if hasattr(py_ast, "TypeAlias") and isinstance(stmt, py_ast.TypeAlias):
            return f"{self.ind()}$={stmt.name.id}={self.dec_type(stmt.value)}"

        if isinstance(stmt, py_ast.Import):
            parts = [f"{a.name}>{a.asname}" if a.asname else a.name for a in stmt.names]
            return f"{self.ind()}<{','.join(parts)}"

        if isinstance(stmt, py_ast.ImportFrom):
            dots = "." * (stmt.level or 0)
            mod = f"{dots}{stmt.module or ''}"
            parts = [f"{a.name}>{a.asname}" if a.asname else a.name for a in stmt.names]
            if len(parts) == 1:
                return f"{self.ind()}<{mod}:{parts[0]}"
            return f"{self.ind()}<{mod}:{{{','.join(parts)}}}"

        if isinstance(stmt, (py_ast.FunctionDef, py_ast.AsyncFunctionDef)):
            return self.dec_func_def(stmt)

        if isinstance(stmt, py_ast.ClassDef):
            return self.dec_class_def(stmt)

        if isinstance(stmt, py_ast.If):
            # Check `if __name__ == "__main__":`
            if self._is_main_guard(stmt.test) and not stmt.orelse:
                return f"{self.ind()}@main{self.dec_block(stmt.body, allow_arrow=False)}"
            return self.dec_if_stmt(stmt)

        if hasattr(py_ast, "Match") and isinstance(stmt, py_ast.Match):
            return self.dec_match_stmt(stmt)

        if isinstance(stmt, (py_ast.For, py_ast.AsyncFor)):
            return self.dec_for_stmt(stmt)

        if isinstance(stmt, py_ast.While):
            return self.dec_while_stmt(stmt)

        if isinstance(stmt, py_ast.Return):
            if stmt.value is None:
                return f"{self.ind()}^"
            if isinstance(stmt.value, py_ast.Tuple) and len(stmt.value.elts) > 1:
                val_s = ",".join(self.dec_expr(e) for e in stmt.value.elts)
            else:
                val_s = self.dec_expr(stmt.value)
            # Avoid `^!` (break), `^*` (yield), `^>` (continue), `^=` (nonlocal).
            sep = " " if val_s.startswith(("!", "*", ">", "=")) else ""
            return f"{self.ind()}^{sep}{val_s}"

        if isinstance(stmt, py_ast.Break):
            return f"{self.ind()}^!"

        if isinstance(stmt, py_ast.Continue):
            return f"{self.ind()}^>"

        if isinstance(stmt, py_ast.Try):
            return self.dec_try_stmt(stmt)

        if isinstance(stmt, py_ast.Raise):
            if stmt.exc is None:
                return f"{self.ind()}!^"
            if stmt.cause is not None:
                return f"{self.ind()}!^{self.dec_expr(stmt.exc)}<-{self.dec_expr(stmt.cause)}"
            return f"{self.ind()}!^{self.dec_expr(stmt.exc)}"

        if isinstance(stmt, py_ast.Assert):
            if stmt.msg is not None:
                return f"{self.ind()}!?{self.dec_expr(stmt.test)},{self.dec_expr(stmt.msg)}"
            return f"{self.ind()}!?{self.dec_expr(stmt.test)}"

        if isinstance(stmt, (py_ast.With, py_ast.AsyncWith)):
            return self.dec_with_stmt(stmt)

        raise DecompileError(stmt, f"unsupported statement: {type(stmt).__name__}")

    def dec_block(self, stmts: list[py_ast.stmt], allow_arrow: bool = True) -> str:
        self.indent_level += 1
        sub = [self.dec_stmt(s).strip() for s in stmts]
        self.indent_level -= 1
        if not sub:
            return "{_}"
        if self.compact and allow_arrow and len(stmts) == 1 and isinstance(stmts[0], (py_ast.Return, py_ast.Expr, py_ast.Assign, py_ast.AugAssign, py_ast.Raise, py_ast.Assert, py_ast.Break, py_ast.Continue, py_ast.Delete)) and "\n" not in sub[0]:
            return f" =>{sub[0]}" if allow_arrow == "space" else f"=>{sub[0]}"
        if self.compact and all("\n" not in s for s in sub):
            return "{" + ";".join(sub) + "}"
        if self.compact:
            return "{" + ";".join(sub) + "}"
        return "{\n" + "\n".join(sub) + "\n}"

    def dec_func_def(self, fn: py_ast.FunctionDef | py_ast.AsyncFunctionDef) -> str:
        is_async = isinstance(fn, py_ast.AsyncFunctionDef)
        sigil = "~@" if is_async else "@"
        decs: list[str] = []
        method_kind = "normal"

        for d in fn.decorator_list:
            if isinstance(d, py_ast.Name) and d.id == "staticmethod" and not is_async:
                sigil = "@/"
                method_kind = "static"
            elif isinstance(d, py_ast.Name) and d.id == "classmethod" and not is_async:
                sigil = "@$"
                method_kind = "classmethod"
            elif isinstance(d, py_ast.Name) and d.id == "property" and not is_async:
                sigil = "@?"
                method_kind = "property"
            elif isinstance(d, py_ast.Attribute) and d.attr == "setter" and not is_async:
                sigil = "@="
                method_kind = "setter"
            else:
                decs.append(self.dec_expr(d))

        dec_prefix = f"#[{','.join(decs)}]\n{self.ind()}" if decs else ""
        name = "init" if (self.in_class and fn.name == "__init__") else fn.name

        prev_rec = self.receiver_name
        args_list = list(fn.args.args)
        if self.in_class and method_kind != "static" and args_list:
            first_arg = args_list[0].arg
            if first_arg in ("self", "cls"):
                self.receiver_name = first_arg
                args_list = args_list[1:]

        param_strs = self._dec_arguments(fn.args, args_list)
        if not param_strs:
            params_part = ""
        else:
            params_part = f"({','.join(param_strs)})"

        ret_part = ""
        if fn.returns is not None and not (self.in_class and name == "init" and isinstance(fn.returns, py_ast.Constant) and fn.returns.value is None):
            ret_part = f"->{self.dec_type(fn.returns)}"

        if self.compact and len(fn.body) == 1 and isinstance(fn.body[0], py_ast.Return) and fn.body[0].value is not None:
            ret_expr = self.dec_expr(fn.body[0].value)
            if "\n" not in ret_expr:
                body_str = f"=>{ret_expr}"
            else:
                body_str = self.dec_block(fn.body, allow_arrow=False)
        else:
            body_str = self.dec_block(fn.body, allow_arrow=False)
        self.receiver_name = prev_rec
        return f"{self.ind()}{dec_prefix}{sigil}{name}{params_part}{ret_part}{body_str}"

    def _dec_arguments(self, args: py_ast.arguments, pos_args: list[py_ast.arg]) -> list[str]:
        res: list[str] = []
        # Defaults align to the end of pos_args
        num_defaults = len(args.defaults)
        default_start = len(pos_args) - num_defaults
        for idx, a in enumerate(pos_args):
            s = a.arg
            if a.annotation is not None:
                s += f":{self.dec_type(a.annotation)}"
            if idx >= default_start and default_start >= 0:
                d_val = args.defaults[idx - default_start]
                s += f"={self.dec_expr(d_val)}"
            res.append(s)

        if args.vararg is not None:
            s = f"*{args.vararg.arg}"
            if args.vararg.annotation is not None:
                s += f":{self.dec_type(args.vararg.annotation)}"
            res.append(s)
        elif args.kwonlyargs:
            res.append("*")

        for a, d in zip(args.kwonlyargs, args.kw_defaults):
            s = a.arg
            if a.annotation is not None:
                s += f":{self.dec_type(a.annotation)}"
            if d is not None:
                s += f"={self.dec_expr(d)}"
            res.append(s)

        if args.kwarg is not None:
            s = f"**{args.kwarg.arg}"
            if args.kwarg.annotation is not None:
                s += f":{self.dec_type(args.kwarg.annotation)}"
            res.append(s)

        return res

    def dec_class_def(self, cls: py_ast.ClassDef) -> str:
        is_dc = False
        decs: list[str] = []
        for d in cls.decorator_list:
            if isinstance(d, py_ast.Name) and d.id == "dataclass":
                is_dc = True
            else:
                decs.append(self.dec_expr(d))

        dec_prefix = f"#[{','.join(decs)}]\n{self.ind()}" if decs else ""
        fields: list[str] = []
        rem_body: list[py_ast.stmt] = []

        if is_dc:
            still_fields = True
            for s in cls.body:
                if still_fields and isinstance(s, py_ast.AnnAssign) and isinstance(s.target, py_ast.Name):
                    f_str = f"{s.target.id}:{self.dec_type(s.annotation)}"
                    if s.value is not None:
                        f_str += f"={self.dec_expr(s.value)}"
                    fields.append(f_str)
                elif isinstance(s, py_ast.Pass):
                    continue
                else:
                    still_fields = False
                    rem_body.append(s)
        else:
            rem_body = cls.body

        sigil = "$$" if is_dc else "$"
        field_part = f"({','.join(fields)})" if (is_dc and fields) else ""
        base_part = f"<{','.join(self.dec_expr(b) for b in cls.bases)}" if cls.bases else ""

        prev_in_class = self.in_class
        self.in_class = True
        if is_dc and not rem_body:
            body_part = "{_}" if not field_part else ""
        else:
            body_part = self.dec_block(rem_body, allow_arrow=False)
        self.in_class = prev_in_class

        return f"{self.ind()}{dec_prefix}{sigil}{cls.name}{field_part}{base_part}{body_part}"

    def _is_main_guard(self, test: py_ast.expr) -> bool:
        if isinstance(test, py_ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], py_ast.Eq):
            if isinstance(test.left, py_ast.Name) and test.left.id == "__name__":
                if isinstance(test.comparators[0], py_ast.Constant) and test.comparators[0].value == "__main__":
                    return True
        return False

    def dec_if_stmt(self, stmt: py_ast.If, is_elif: bool = False) -> str:
        kw = ":?" if is_elif else f"{self.ind()}?"
        allow_arr = not stmt.orelse
        res = f"{kw}{self.dec_expr(stmt.test)}{self.dec_block(stmt.body, allow_arrow=allow_arr)}"
        if stmt.orelse:
            if len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], py_ast.If):
                res += self.dec_if_stmt(stmt.orelse[0], is_elif=True)
            else:
                res += f":{self.dec_block(stmt.orelse, allow_arrow=False)}"
        return res

    def dec_match_stmt(self, stmt: py_ast.Match) -> str:
        cases: list[str] = []
        for c in stmt.cases:
            pat = self._dec_pattern(c.pattern)
            guard = f"?{self.dec_expr(c.guard)}" if c.guard is not None else ""
            if self.compact and len(c.body) == 1:
                single = self.dec_stmt(c.body[0]).strip()
                if "\n" not in single and not single.startswith("??"):
                    cases.append(f"{pat}{guard}=>{single}")
                    continue
            cases.append(f"{pat}{guard}=>{self.dec_block(c.body, allow_arrow=False)}")
        return f"{self.ind()}??{self.dec_expr(stmt.subject)}{{{';'.join(cases)}}}"

    def _dec_pattern(self, pat: py_ast.pattern) -> str:
        if isinstance(pat, py_ast.MatchAs):
            if pat.pattern is None and pat.name is None:
                return "_"
            if pat.pattern is None and pat.name is not None:
                return pat.name
        if isinstance(pat, py_ast.MatchValue):
            return self.dec_expr(pat.value)
        if isinstance(pat, py_ast.MatchSingleton):
            if pat.value is None:
                return "N"
            return "T" if pat.value else "F"
        raise DecompileError(pat, f"unsupported pattern: {type(pat).__name__}")

    def dec_for_stmt(self, stmt: py_ast.For | py_ast.AsyncFor) -> str:
        kw = "%~" if isinstance(stmt, py_ast.AsyncFor) else "%"
        tgt = self.dec_target(stmt.target)
        res = f"{self.ind()}{kw}{tgt}<-{self.dec_expr(stmt.iter)}{self.dec_block(stmt.body)}"
        if stmt.orelse:
            res += f"%:{self.dec_block(stmt.orelse)}"
        return res

    def dec_while_stmt(self, stmt: py_ast.While) -> str:
        res = f"{self.ind()}%?{self.dec_expr(stmt.test)}{self.dec_block(stmt.body)}"
        if stmt.orelse:
            res += f"%:{self.dec_block(stmt.orelse)}"
        return res

    def dec_try_stmt(self, stmt: py_ast.Try) -> str:
        res = f"{self.ind()}!{self.dec_block(stmt.body, allow_arrow=False)}"
        for h in stmt.handlers:
            if h.type is not None and h.name is not None:
                if isinstance(h.type, py_ast.Name) and h.type.id == "Exception":
                    res += f"!!{h.name}{self.dec_block(h.body)}"
                else:
                    res += f"!!{h.name}:{self.dec_expr(h.type)}{self.dec_block(h.body)}"
            elif h.type is not None:
                res += f"!!:{self.dec_expr(h.type)}{self.dec_block(h.body)}"
            else:
                res += f"!!{self.dec_block(h.body)}"
        if stmt.orelse:
            res += f"!?{self.dec_block(stmt.orelse, allow_arrow=False)}"
        if stmt.finalbody:
            res += f"!:{self.dec_block(stmt.finalbody)}"
        return res

    def dec_with_stmt(self, stmt: py_ast.With | py_ast.AsyncWith) -> str:
        kw = "!~&" if isinstance(stmt, py_ast.AsyncWith) else "!&"
        items: list[str] = []
        for item in stmt.items:
            ctx = self.dec_expr(item.context_expr)
            if item.optional_vars is not None:
                items.append(f"{self.dec_target(item.optional_vars)}={ctx}")
            else:
                items.append(ctx)
        return f"{self.ind()}{kw}{','.join(items)}{self.dec_block(stmt.body)}"

    # ========================================================================
    # Types
    # ========================================================================

    def dec_type(self, node: py_ast.expr) -> str:
        if isinstance(node, py_ast.Name):
            return REVERSE_TYPE_SHORTHANDS.get(node.id, node.id)

        if isinstance(node, py_ast.Constant) and node.value is None:
            return "N"

        if isinstance(node, py_ast.Tuple):
            return f"({','.join(self.dec_type(e) for e in node.elts)})"

        if isinstance(node, py_ast.Subscript) and isinstance(node.value, py_ast.Name):
            base = node.value.id
            if base == "Optional":
                return f"{self.dec_type(node.slice)}?"
            if base in ("list", "List"):
                return f"[{self.dec_type(node.slice)}]"
            if base in ("set", "Set"):
                return f"{{{self.dec_type(node.slice)}}}"
            if base in ("dict", "Dict") and isinstance(node.slice, py_ast.Tuple) and len(node.slice.elts) == 2:
                return f"{{{self.dec_type(node.slice.elts[0])}:{self.dec_type(node.slice.elts[1])}}}"
            if base in ("tuple", "Tuple"):
                if isinstance(node.slice, py_ast.Tuple):
                    return f"({','.join(self.dec_type(e) for e in node.slice.elts)})"
                return f"({self.dec_type(node.slice)})"
            if isinstance(node.slice, py_ast.Tuple):
                return f"{base}[{','.join(self.dec_type(e) for e in node.slice.elts)}]"
            return f"{base}[{self.dec_type(node.slice)}]"

        if isinstance(node, py_ast.BinOp) and isinstance(node.op, py_ast.BitOr):
            # Check `T | None` -> `T?`
            if isinstance(node.right, py_ast.Constant) and node.right.value is None:
                return f"{self.dec_type(node.left)}?"
            return f"{self.dec_type(node.left)}|{self.dec_type(node.right)}"

        return self.dec_expr(node)

    # ========================================================================
    # Expressions
    # ========================================================================

    def dec_target(self, expr: py_ast.expr) -> str:
        if isinstance(expr, py_ast.Tuple):
            return ",".join(self.dec_expr(e) for e in expr.elts)
        return self.dec_expr(expr)

    @staticmethod
    def _dec_bytes(value: bytes) -> str:
        buf: list[str] = []
        for byte in value:
            if byte == 0x5C:  # backslash
                buf.append("\\\\")
            elif byte == 0x22:  # double quote
                buf.append('\\"')
            elif byte == 0x0A:
                buf.append("\\n")
            elif byte == 0x0D:
                buf.append("\\r")
            elif byte == 0x09:
                buf.append("\\t")
            elif 0x20 <= byte < 0x7F:
                buf.append(chr(byte))
            else:
                buf.append(f"\\x{byte:02x}")
        return '0b"' + "".join(buf) + '"'

    def dec_expr(self, expr: py_ast.expr) -> str:
        if isinstance(expr, py_ast.Constant):
            if expr.value is True:
                return "T"
            if expr.value is False:
                return "F"
            if expr.value is None:
                return "N"
            if expr.value is Ellipsis:
                return "..."
            if isinstance(expr.value, bytes):
                return self._dec_bytes(expr.value)
            return repr(expr.value)

        if isinstance(expr, py_ast.JoinedStr):
            parts: list[str] = []
            for v in expr.values:
                if isinstance(v, py_ast.Constant) and isinstance(v.value, str):
                    parts.append(
                        v.value.replace("\\", "\\\\")
                        .replace("`", "\\`")
                        .replace("{", "{{")
                        .replace("}", "}}")
                    )
                elif isinstance(v, py_ast.FormattedValue):
                    val_s = self.dec_expr(v.value)
                    if v.conversion == ord("r"):
                        val_s = f"@repr({val_s})"
                    elif v.conversion == ord("s"):
                        val_s = f"@str({val_s})"
                    elif v.conversion == ord("a"):
                        raise DecompileError(v, "f-string !a (ascii) conversion is not supported")
                    if v.format_spec is not None and isinstance(v.format_spec, py_ast.JoinedStr):
                        fmt = "".join(
                            c.value for c in v.format_spec.values if isinstance(c, py_ast.Constant) and isinstance(c.value, str)
                        )
                        parts.append(f"{{{val_s}:{fmt}}}")
                    else:
                        parts.append(f"{{{val_s}}}")
            return f"`{''.join(parts)}`"

        if isinstance(expr, py_ast.Name):
            return REVERSE_BUILTIN_SHORTHANDS.get(expr.id, expr.id)

        if isinstance(expr, py_ast.Attribute):
            if self.receiver_name and isinstance(expr.value, py_ast.Name) and expr.value.id == self.receiver_name:
                return f".{expr.attr}"
            if (
                isinstance(expr.value, py_ast.Call)
                and isinstance(expr.value.func, py_ast.Name)
                and expr.value.func.id == "super"
                and not expr.value.args
            ):
                attr = "init" if expr.attr == "__init__" else expr.attr
                return f"..{attr}"
            return f"{self.dec_expr(expr.value)}.{expr.attr}"

        if isinstance(expr, py_ast.Call):
            # `len(x)` -> `#x`
            if isinstance(expr.func, py_ast.Name) and expr.func.id == "len" and len(expr.args) == 1 and not expr.keywords:
                arg = expr.args[0]
                arg_s = self.dec_expr(arg)
                if isinstance(arg, (py_ast.Name, py_ast.Attribute, py_ast.Subscript, py_ast.Call)):
                    return f"#{arg_s}"
                return f"#({arg_s})"

            # `range(...)` -> `a..b` or `0..n`
            if isinstance(expr.func, py_ast.Name) and expr.func.id == "range" and not expr.keywords:
                if len(expr.args) == 1:
                    return f"0..{self._dec_range_bound(expr.args[0])}"
                if len(expr.args) == 2:
                    return f"{self._dec_range_bound(expr.args[0])}..{self._dec_range_bound(expr.args[1])}"
                if len(expr.args) == 3:
                    return f"{self._dec_range_bound(expr.args[0])}..{self._dec_range_bound(expr.args[1])}..{self._dec_range_bound(expr.args[2])}"

            # `isinstance(x, T)` -> `(x :? T)`
            if isinstance(expr.func, py_ast.Name) and expr.func.id == "isinstance" and len(expr.args) == 2 and not expr.keywords:
                lhs = self.dec_expr(expr.args[0])
                rhs = self.dec_type(expr.args[1])
                return f"{lhs}:?{rhs}"

            # `d.get("key")` -> `d$?key` and `d.get("key", default)` -> `(d$?key??default)`
            if isinstance(expr.func, py_ast.Attribute) and expr.func.attr == "get" and not expr.keywords:
                if (
                    len(expr.args) >= 1
                    and isinstance(expr.args[0], py_ast.Constant)
                    and isinstance(expr.args[0].value, str)
                    and expr.args[0].value.isidentifier()
                ):
                    key_name = expr.args[0].value
                    obj_s = self.dec_expr(expr.func.value)
                    if len(expr.args) == 1 or (isinstance(expr.args[1], py_ast.Constant) and expr.args[1].value is None):
                        return f"{obj_s}$?{key_name}"
                    if len(expr.args) == 2:
                        return f"({obj_s}$?{key_name}??{self.dec_expr(expr.args[1])})"

        # `x.decode('utf-8')` inside `json.loads(x.decode('utf-8'))` -> `@j(x)` (Python 3 `json.loads` accepts bytes directly!)
            if isinstance(expr.func, py_ast.Attribute) and isinstance(expr.func.value, py_ast.Name) and expr.func.value.id == "json":
                if expr.func.attr in ("loads", "dumps"):
                    alias = "@j" if expr.func.attr == "loads" else "@J"
                    raw_args = list(expr.args)
                    if (
                        alias == "@j"
                        and len(raw_args) == 1
                        and isinstance(raw_args[0], py_ast.Call)
                        and isinstance(raw_args[0].func, py_ast.Attribute)
                        and raw_args[0].func.attr == "decode"
                        and not raw_args[0].keywords
                    ):
                        raw_args = [raw_args[0].func.value]
                    args_s = [self.dec_expr(a) for a in raw_args]
                    for kw in expr.keywords:
                        args_s.append(f"**{self.dec_expr(kw.value)}" if kw.arg is None else f"{kw.arg}={self.dec_expr(kw.value)}")
                    return f"{alias}({','.join(args_s)})"

            # `x.encode('utf-8')` -> `@u8(x)` and `x.decode('utf-8')` -> `@u8d(x)`
            if (
                isinstance(expr.func, py_ast.Attribute)
                and expr.func.attr in ("encode", "decode")
                and not expr.keywords
                and (
                    len(expr.args) == 0
                    or (
                        len(expr.args) == 1
                        and isinstance(expr.args[0], py_ast.Constant)
                        and isinstance(expr.args[0].value, str)
                        and expr.args[0].value.lower() in ("utf-8", "utf8")
                    )
                )
            ):
                alias = "@u8" if expr.func.attr == "encode" else "@u8d"
                return f"{alias}({self.dec_expr(expr.func.value)})"

            func_s = self.dec_expr(expr.func)
            args_s: list[str] = []
            for idx, a in enumerate(expr.args):
                # If last positional arg (and no kwargs) is a simple string-keyed Dict, emit inline `k:v` without `{}`!
                if (
                    idx == len(expr.args) - 1
                    and not expr.keywords
                    and isinstance(a, py_ast.Dict)
                    and a.keys
                    and all(
                        isinstance(k, py_ast.Constant)
                        and isinstance(k.value, str)
                        and k.value.isidentifier()
                        and k.value not in ("T", "F", "N", "U")
                        for k in a.keys
                    )
                ):
                    for k, v in zip(a.keys, a.values):
                        assert isinstance(k, py_ast.Constant) and isinstance(k.value, str)
                        args_s.append(f"{k.value}:{self.dec_expr(v)}")
                else:
                    args_s.append(self.dec_expr(a))
            for kw in expr.keywords:
                if kw.arg is None:
                    args_s.append(f"**{self.dec_expr(kw.value)}")
                elif isinstance(kw.value, py_ast.Name) and kw.value.id == kw.arg:
                    args_s.append(f"={kw.arg}")
                else:
                    args_s.append(f"{kw.arg}={self.dec_expr(kw.value)}")
            return f"{func_s}({','.join(args_s)})"

        if isinstance(expr, py_ast.UnaryOp):
            if isinstance(expr.op, py_ast.Not):
                op_s = self.dec_expr(expr.operand)
                is_isinstance = (
                    isinstance(expr.operand, py_ast.Call)
                    and isinstance(expr.operand.func, py_ast.Name)
                    and expr.operand.func.id == "isinstance"
                )
                if is_isinstance or isinstance(
                    expr.operand,
                    (py_ast.Compare, py_ast.BoolOp, py_ast.BinOp, py_ast.IfExp),
                ):
                    return f"!({op_s})"
                return f"!{op_s}"
            if isinstance(expr.op, py_ast.Invert):
                return f"~|{self.dec_expr(expr.operand)}"
            if isinstance(expr.op, py_ast.USub):
                return f"-{self.dec_expr(expr.operand)}"
            if isinstance(expr.op, py_ast.UAdd):
                return f"+{self.dec_expr(expr.operand)}"

        if isinstance(expr, py_ast.Await):
            return f"~{self.dec_expr(expr.value)}"

        if isinstance(expr, py_ast.Starred):
            return f"*{self.dec_expr(expr.value)}"

        if isinstance(expr, py_ast.Yield):
            if expr.value is None:
                return "^*"
            return f"^*{self.dec_expr(expr.value)}"

        if isinstance(expr, py_ast.YieldFrom):
            return f"^**{self.dec_expr(expr.value)}"

        if isinstance(expr, py_ast.BoolOp):
            op = "&&" if isinstance(expr.op, py_ast.And) else "||"
            parts: list[str] = []
            for v in expr.values:
                s = self.dec_expr(v)
                if isinstance(v, (py_ast.BoolOp, py_ast.IfExp)):
                    s = f"({s})"
                parts.append(s)
            return op.join(parts)

        if isinstance(expr, py_ast.BinOp):
            op = self._bin_op(expr.op)
            if op is None:
                raise DecompileError(expr, f"unsupported binary operator: {type(expr.op).__name__}")
            l_s = self.dec_expr(expr.left)
            r_s = self.dec_expr(expr.right)
            if isinstance(expr.left, (py_ast.BinOp, py_ast.BoolOp, py_ast.Compare, py_ast.IfExp)):
                l_s = f"({l_s})"
            if isinstance(expr.right, (py_ast.BinOp, py_ast.BoolOp, py_ast.Compare, py_ast.IfExp)):
                r_s = f"({r_s})"
            return f"{l_s}{op}{r_s}"

        if isinstance(expr, py_ast.Compare):
            parts = [self.dec_expr(expr.left)]
            for op, comp in zip(expr.ops, expr.comparators):
                op_s = self._cmp_op(op)
                if op_s is None:
                    raise DecompileError(expr, f"unsupported comparison operator: {type(op).__name__}")
                c_s = self.dec_expr(comp)
                # Ensure tokens like `===N` have a space if needed (`=== N` or `===N`—note `===` is multi-char and `N` is ident, so `===N` lexes cleanly!)
                parts.append(f"{op_s}{c_s}")
            return "".join(parts)

        if isinstance(expr, py_ast.IfExp):
            # Recognize `x if x is not None else y` -> `(x??y)`
            if (
                isinstance(expr.test, py_ast.Compare)
                and len(expr.test.ops) == 1
                and isinstance(expr.test.ops[0], py_ast.IsNot)
                and isinstance(expr.test.comparators[0], py_ast.Constant)
                and expr.test.comparators[0].value is None
                and self.dec_expr(expr.test.left) == self.dec_expr(expr.body)
            ):
                return f"({self.dec_expr(expr.body)}??{self.dec_expr(expr.orelse)})"
            c_s = self.dec_expr(expr.test)
            t_s = self.dec_expr(expr.body)
            f_s = self.dec_expr(expr.orelse)
            # `?` followed directly by `.` or `?` would lex as `?.` / `??`.
            sep = " " if t_s.startswith((".", "?")) else ""
            return f"({c_s}?{sep}{t_s}:{f_s})"

        if isinstance(expr, py_ast.Subscript):
            val_s = self.dec_expr(expr.value)
            if (
                isinstance(expr.slice, py_ast.Constant)
                and isinstance(expr.slice.value, str)
                and expr.slice.value.isidentifier()
            ):
                return f"{val_s}${expr.slice.value}"
            if isinstance(expr.slice, py_ast.Tuple):
                sl_s = ",".join(self.dec_slice(e) for e in expr.slice.elts)
            else:
                sl_s = self.dec_slice(expr.slice)
            return f"{val_s}[{sl_s}]"

        if isinstance(expr, py_ast.List):
            return f"[{','.join(self.dec_expr(e) for e in expr.elts)}]"

        if isinstance(expr, py_ast.Tuple):
            if not expr.elts:
                return "()"
            if len(expr.elts) == 1:
                return f"({self.dec_expr(expr.elts[0])},)"
            return f"({','.join(self.dec_expr(e) for e in expr.elts)})"

        if isinstance(expr, py_ast.Set):
            return f"{{{','.join(self.dec_expr(e) for e in expr.elts)}}}"

        if isinstance(expr, py_ast.Dict):
            items: list[str] = []
            for idx, (k, v) in enumerate(zip(expr.keys, expr.values)):
                if k is None:
                    items.append(f"**{self.dec_expr(v)}")
                elif isinstance(k, py_ast.Constant) and isinstance(k.value, str) and k.value.isidentifier() and k.value not in ("T", "F", "N", "U"):
                    k_str = k.value
                    v_str = self.dec_expr(v)
                    if v_str == f".{k_str}":
                        items.append(f".{k_str}")
                    elif v_str == k_str:
                        items.append(f"={k_str}" if idx == 0 else k_str)
                    else:
                        items.append(f"{k_str}:{v_str}")
                elif isinstance(k, (py_ast.Name, py_ast.Attribute, py_ast.Subscript, py_ast.Call)):
                    items.append(f"[{self.dec_expr(k)}]:{self.dec_expr(v)}")
                else:
                    items.append(f"{self.dec_expr(k)}:{self.dec_expr(v)}")
            return f"{{{','.join(items)}}}"

        if isinstance(expr, py_ast.ListComp):
            return f"[{self.dec_expr(expr.elt)}|{self._dec_generators(expr.generators)}]"

        if isinstance(expr, py_ast.SetComp):
            return f"{{{self.dec_expr(expr.elt)}|{self._dec_generators(expr.generators)}}}"

        if isinstance(expr, py_ast.GeneratorExp):
            return f"({self.dec_expr(expr.elt)}|{self._dec_generators(expr.generators)})"

        if isinstance(expr, py_ast.DictComp):
            return f"{{{self.dec_expr(expr.key)}:{self.dec_expr(expr.value)}|{self._dec_generators(expr.generators)}}}"

        if isinstance(expr, py_ast.Lambda):
            p_strs = self._dec_arguments(expr.args, list(expr.args.args))
            if len(p_strs) == 1 and ":" not in p_strs[0] and "=" not in p_strs[0] and not p_strs[0].startswith("*"):
                return f"{p_strs[0]}=>{self.dec_expr(expr.body)}"
            return f"({','.join(p_strs)})=>{self.dec_expr(expr.body)}"

        if isinstance(expr, py_ast.NamedExpr):
            return f"({self.dec_expr(expr.target)}:={self.dec_expr(expr.value)})"

        raise DecompileError(expr, f"unsupported expression: {type(expr).__name__}")

    def _dec_range_bound(self, expr: py_ast.expr) -> str:
        s = self.dec_expr(expr)
        if isinstance(expr, (py_ast.Name, py_ast.Constant, py_ast.Attribute, py_ast.Subscript, py_ast.Call)):
            return s
        return f"({s})"

    def dec_slice(self, node: py_ast.expr) -> str:
        if isinstance(node, py_ast.Slice):
            lo = self.dec_expr(node.lower) if node.lower is not None else ""
            up = self.dec_expr(node.upper) if node.upper is not None else ""
            if node.step is not None:
                return f"{lo}:{up}:{self.dec_expr(node.step)}"
            return f"{lo}:{up}"
        return self.dec_expr(node)

    def _dec_generators(self, gens: list[py_ast.comprehension]) -> str:
        parts: list[str] = []
        for idx, g in enumerate(gens):
            prefix = ("%~" if g.is_async else "%") if idx > 0 else ("~" if g.is_async else "")
            part = f"{prefix}{self.dec_target(g.target)}<-{self.dec_expr(g.iter)}"
            for cond in g.ifs:
                part += f"?{self.dec_expr(cond)}"
            parts.append(part)
        return " ".join(parts)

    def _aug_op(self, op: py_ast.operator) -> Optional[str]:
        return self._bin_op(op)

    def _bin_op(self, op: py_ast.operator) -> Optional[str]:
        table = {
            py_ast.Add: "+",
            py_ast.Sub: "-",
            py_ast.Mult: "*",
            py_ast.Div: "/",
            py_ast.FloorDiv: "//",
            py_ast.Mod: "%",
            py_ast.Pow: "**",
            py_ast.LShift: "<<",
            py_ast.RShift: ">>",
            py_ast.BitOr: "|",
            py_ast.BitXor: "^",
            py_ast.BitAnd: "&",
        }
        return table.get(type(op))

    def _cmp_op(self, op: py_ast.cmpop) -> Optional[str]:
        table = {
            py_ast.Eq: "==",
            py_ast.NotEq: "!=",
            py_ast.Lt: "<",
            py_ast.LtE: "<=",
            py_ast.Gt: ">",
            py_ast.GtE: ">=",
            py_ast.Is: "===",
            py_ast.IsNot: "!==",
            py_ast.In: "<-",
            py_ast.NotIn: "!<-",
        }
        return table.get(type(op))


def decompile_python(source: str, compact: bool = True, minify_locals: bool = False) -> str:
    dec = PythonDecompiler(compact=compact, minify_locals=minify_locals)
    return dec.decompile(source)
