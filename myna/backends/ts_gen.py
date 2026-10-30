"""TypeScript code generator for the Myna programming language.

TypeScript is a **typed projection** of the JavaScript target (``DECISIONS.md``
D-006), not a third semantics.  The generated modules execute the same inlined
``__myna_*`` helpers as ``js_gen``; type annotations are erased and never add runtime
checks.  A module that compiles for ``-t js`` compiles for ``-t ts``, and a module that
is rejected for JavaScript is rejected here with the same ``TargetError``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import myna.ast_nodes as ast
from myna.backends.js_gen import (
    BUILTIN_VALUES,
    HELPER_ORDER,
    HELPERS,
    PY_EXCEPTION_ORDER,
    PY_EXCEPTIONS,
    JSGenerator,
    js_ident,
)
from myna.checks import check_call_dict_shorthand
from myna.modules import (
    ModuleError,
    module_bindings,
    module_classes,
    module_type_aliases,
    resolve_from_import,
)
from myna.targets import TargetError, enforce_module_target, expand_target_blocks


# Myna type shorthands -> TypeScript types.  Python spellings are accepted too, so a
# hand-written annotation or a future decompiler change does not leak `int`/`str` into
# generated TypeScript.
TYPE_SHORTHANDS_TS: dict[str, str] = {
    "i": "number",
    "f": "number",
    "s": "string",
    "b": "boolean",
    "B": "Uint8Array",
    "A": "any",
    "N": "null",
    "int": "number",
    "float": "number",
    "str": "string",
    "bool": "boolean",
    "bytes": "Uint8Array",
    "bytearray": "Uint8Array",
    "Any": "any",
    "None": "null",
    # TypeScript spellings are accepted too; a user class or alias with the same
    # name wins because `gen_type` checks the known type names first.
    "any": "any",
    "bigint": "bigint",
    "boolean": "boolean",
    "never": "never",
    "null": "null",
    "number": "number",
    "object": "object",
    "string": "string",
    "symbol": "symbol",
    "undefined": "undefined",
    "unknown": "unknown",
    "void": "void",
}

# Python's `typing` names have no direct TypeScript spelling.  These are the
# unparameterised fallbacks; `_gen_generic_type` handles their arguments.
TYPING_SIMPLE_TS: dict[str, str] = {
    "Annotated": "any",
    "AnyStr": "string",
    "AsyncContextManager": "any",
    "Awaitable": "Promise<any>",
    "Callable": "(...args: any[]) => any",
    "ClassVar": "any",
    "Coroutine": "Promise<any>",
    "Dict": "Record<string, any>",
    "Final": "any",
    "FrozenSet": "Set<any>",
    "Generator": "Generator<any, any, any>",
    "Iterable": "Iterable<any>",
    "Iterator": "Iterable<any>",
    "List": "any[]",
    "LiteralString": "string",
    "Mapping": "Record<string, any>",
    "MutableMapping": "Record<string, any>",
    "MutableSequence": "any[]",
    "MutableSet": "Set<any>",
    "Never": "never",
    "NoReturn": "never",
    "Optional": "any",
    "Sequence": "any[]",
    "Set": "Set<any>",
    "Text": "string",
    "Tuple": "any[]",
    "Type": "new (...args: any[]) => any",
    "Union": "any",
    # Bare builtin generics, e.g. `x: list` / `x: dict`.
    "dict": "Record<string, any>",
    "frozenset": "Set<any>",
    "list": "any[]",
    "set": "Set<any>",
    "tuple": "any[]",
    "type": "new (...args: any[]) => any",
    "AsyncGenerator": "AsyncGenerator<any, any>",
    "AsyncIterable": "AsyncIterable<any>",
    "AsyncIterator": "AsyncIterable<any>",
    "Collection": "Iterable<any>",
    "Container": "Iterable<any>",
    "ContextManager": "any",
    "Generic": "any",
    "Hashable": "any",
    "Literal": "any",
    "NotRequired": "any",
    "Protocol": "any",
    "ReadOnly": "any",
    "Required": "any",
    "Reversible": "any[]",
    "Sized": "any",
    "TypedDict": "any",
}

_TYPING_PREFIXES = frozenset(
    {"typing", "typing_extensions", "collections", "collections.abc", "builtins"}
)


def _typing_short_name(name: str) -> str:
    """Return ``T`` for ``typing.T``/``collections.abc.T`` and ``name`` otherwise."""
    prefix, sep, rest = name.rpartition(".")
    return rest if sep and prefix in _TYPING_PREFIXES else name

# TypeScript does not allow these as class or type-alias names.  They cannot be
# renamed everywhere the way JS reserved words can, because an annotation such as
# `x: string` must keep meaning the primitive.
TS_TYPE_KEYWORDS = frozenset(
    {
        "any",
        "bigint",
        "boolean",
        "never",
        "null",
        "number",
        "object",
        "string",
        "symbol",
        "undefined",
        "unknown",
        "void",
    }
)

# Builtin aliases with the same values as JavaScript, except that arrow-valued aliases
# carry explicit `any` parameters so generated code passes `tsc --strict`.
TS_BUILTIN_VALUES: dict[str, str] = dict(BUILTIN_VALUES)
TS_BUILTIN_VALUES.update(
    {
        # `int()`/`json.loads()` accept coercible inputs at runtime; keep the helper
        # signatures permissive so typed arguments do not fail `tsc` spuriously.
        "@int": "(x: any) => Math.trunc(x)",
        "@j": "(x: any) => JSON.parse(x)",
        "@set": "(x: any) => new Set(x)",
        "@u8": "(x: any) => new TextEncoder().encode(x)",
        "@u8d": "(x: any) => new TextDecoder().decode(x)",
        "@rev": "(x: any) => Array.from(x).reverse()",
        "@enum": "(x: any) => Array.from(x).entries()",
        "@map": "(f: any, x: any) => Array.from(x).map(f)",
        "@flt": "(f: any, x: any) => Array.from(x).filter(f)",
    }
)

# The JavaScript helpers are the normative implementation.  TypeScript reuses their
# bodies and only adds erased annotations: top-level signatures plus the handful of
# local arrow functions that strict mode cannot type contextually.
TS_HELPER_REPLACEMENTS: list[tuple[str, str]] = [
    ("function __myna_repr(x)", "function __myna_repr(x: any): string"),
    ("function __myna_str(x)", "function __myna_str(x: any): string"),
    ("function __myna_print(...args)", "function __myna_print(...args: any[]): void"),
    ("function __myna_truthy(x)", "function __myna_truthy(x: any): boolean"),
    ("function __myna_eq(a, b)", "function __myna_eq(a: any, b: any): boolean"),
    ("function __myna_add(a, b)", "function __myna_add(a: any, b: any): any"),
    ("function __myna_sub(a, b)", "function __myna_sub(a: any, b: any): any"),
    ("function __myna_mul(a, b)", "function __myna_mul(a: any, b: any): any"),
    ("function __myna_div(a, b)", "function __myna_div(a: any, b: any): any"),
    ("function __myna_floordiv(a, b)", "function __myna_floordiv(a: any, b: any): any"),
    ("function __myna_mod(a, b)", "function __myna_mod(a: any, b: any): any"),
    ("function __myna_neg(a)", "function __myna_neg(a: any): any"),
    ("function __myna_pos(a)", "function __myna_pos(a: any): any"),
    ("function __myna_len(x)", "function __myna_len(x: any): number"),
    ("function __myna_in(x, c)", "function __myna_in(x: any, c: any): boolean"),
    ("function __myna_getitem(o, k)", "function __myna_getitem(o: any, k: any): any"),
    ("function __myna_get(o, k, dflt)", "function __myna_get(o: any, k: any, dflt?: any): any"),
    ("function __myna_slice(x, lo, hi, step)", "function __myna_slice(x: any, lo: any, hi: any, step: any): any"),
    ("function __myna_iter(x)", "function __myna_iter(x: any): any[]"),
    ("function __myna_range(a, b, s = 1)", "function __myna_range(a: any, b?: any, s: any = 1): number[]"),
    ("function __myna_sort(seq, key, reverse)", "function __myna_sort(seq: any, key?: any, reverse?: any): any[]"),
    ("function __myna_zip(...its)", "function __myna_zip(...its: any[]): any[][]"),
    ("function __myna_min(...a)", "function __myna_min(...a: any[]): any"),
    ("function __myna_max(...a)", "function __myna_max(...a: any[]): any"),
    ("function __myna_sum(seq, start = 0)", "function __myna_sum(seq: any, start: any = 0): any"),
    ("function __myna_all(seq)", "function __myna_all(seq: any): boolean"),
    ("function __myna_any(seq)", "function __myna_any(seq: any): boolean"),
    # `codePointAt` is `number | undefined` in the TypeScript lib; the loop only
    # iterates over code points, so assert the non-null case (erased at runtime).
    ("const c = ch.codePointAt(0);", "const c = ch.codePointAt(0)!;"),
    ("const n = (v) =>", "const n = (v: any) =>"),
    ("const repeat = (seq, count, empty) =>", "const repeat = (seq: any, count: any, empty: any) =>"),
    ("const norm = (v, dflt) =>", "const norm = (v: any, dflt: any) =>"),
    ("const kf = key || ((v) => v);", "const kf = key || ((v: any) => v);"),
]

_TS_HELPER_CACHE: dict[str, str] = {}


def ts_helper_source(name: str) -> str:
    """Return the TypeScript form of a JavaScript helper, annotated on demand."""
    cached = _TS_HELPER_CACHE.get(name)
    if cached is not None:
        return cached
    code = HELPERS[name]
    for old, new in TS_HELPER_REPLACEMENTS:
        code = code.replace(old, new)
    _TS_HELPER_CACHE[name] = code
    return code


def _array_of(ts_type: str) -> str:
    """Wrap a union or function element type in parentheses before appending `[]`."""
    if "|" in ts_type or "=>" in ts_type:
        return f"({ts_type})[]"
    return f"{ts_type}[]"


def _optional_of(ts_type: str) -> str:
    """Append ``| null`` without changing a function type's meaning."""
    if ts_type in ("any", "null"):
        return ts_type
    if "=>" in ts_type:
        return f"({ts_type}) | null"
    return f"{ts_type} | null"


def _union_part(ts_type: str) -> str:
    """Parenthesize a function type that appears as a union member."""
    return f"({ts_type})" if "=>" in ts_type else ts_type


def _record_key(ts_type: str) -> str:
    """Return a valid `Record` key type, matching JavaScript's string-coerced keys."""
    parts = [part.strip().strip("()") for part in ts_type.split("|")]
    if parts and all(part in {"string", "number", "symbol", "any"} for part in parts):
        return ts_type
    return "string"


class TSGenerator(JSGenerator):
    def __init__(
        self,
        indent_str: str = "  ",
        *,
        source_path: Optional[Path] = None,
        module_ext: str = ".js",
        import_base: Optional[Path] = None,
    ):
        super().__init__(
            indent_str,
            source_path=source_path,
            module_ext=module_ext,
            import_base=import_base,
        )
        # Names that exist only in the type namespace: top-level `$=` aliases and
        # `import type` bindings.  Using one as a value is a compile error.
        self.type_only_names: set[str] = set()
        # A top-level alias whose source name is a JS reserved word is declared under
        # its `$`-prefixed binding and re-exported under the source name.
        self.type_export_aliases: list[tuple[str, str]] = []
        # The class whose body is being generated; `Self` resolves to it.
        self.current_class: Optional[str] = None

    # ------------------------------------------------------------------
    # Generator hooks
    # ------------------------------------------------------------------

    def _require_source_path(self) -> Path:
        if self.source_path is None:
            raise TargetError(
                "relative imports need a source path for the TypeScript target; "
                "compile the file with `myna compile` (or pass source_path= to "
                "myna_to_ts) so the specifier can be resolved"
            )
        return self.source_path

    def return_annotation(self, fn: ast.FuncDef) -> str:
        if fn.method_kind in ("init", "setter") or fn.is_generator:
            return ""
        if fn.return_type is None:
            return ""
        rendered = self.gen_type(fn.return_type)
        if fn.is_async:
            rendered = f"Promise<{rendered}>"
        return f": {rendered}"

    def catch_clause(self, evar: str) -> str:
        # `useUnknownInCatchVariables` is on under `strict`; the generator handles
        # arbitrary thrown values, so the binding is explicitly `any`.
        return f"catch ({evar}: any)"

    def builtin_value(self, name: str) -> Optional[str]:
        return TS_BUILTIN_VALUES.get(name)

    def lambda_param(self, name: str) -> str:
        return f"{name}: any"

    def function_fallthrough(self, fn: ast.FuncDef) -> list[str]:
        # Python falls off the end of a function and returns None even when the
        # return annotation promises a concrete type.  The generated TypeScript must
        # satisfy `noImplicitReturns`-style checking without changing that behaviour,
        # so add an unreachable/None fallback that matches Python's implicit return.
        if (
            fn.return_type is None
            or fn.is_generator
            or fn.method_kind in ("init", "setter")
        ):
            return []
        if fn.body and isinstance(fn.body[-1], (ast.ReturnStmt, ast.RaiseStmt)):
            return []
        return [f"{self.ind()}{self.indent_str}return null as any;"]

    # ------------------------------------------------------------------
    # Types
    # ------------------------------------------------------------------

    def gen_type(self, t: ast.TypeNode) -> str:
        if isinstance(t, ast.SimpleType):
            if t.name in self.known_classes or t.name in self.type_only_names:
                base = js_ident(t.name)
            else:
                short = _typing_short_name(t.name)
                if short in self.known_classes or short in self.type_only_names:
                    base = js_ident(short)
                elif short == "Self":
                    base = self._self_type()
                elif short in TYPING_SIMPLE_TS:
                    base = TYPING_SIMPLE_TS[short]
                elif short != t.name:
                    # An unhandled name from `typing`/`collections.abc` has no
                    # TypeScript counterpart; a dangling identifier would fail `tsc`.
                    base = "any"
                else:
                    base = TYPE_SHORTHANDS_TS.get(short, js_ident(short))
            return _optional_of(base) if t.optional else base

        if isinstance(t, ast.ListType):
            base = _array_of(self.gen_type(t.elem))
            return _optional_of(base) if t.optional else base

        if isinstance(t, ast.DictType):
            key = _record_key(self.gen_type(t.key))
            base = f"Record<{key}, {self.gen_type(t.value)}>"
            return _optional_of(base) if t.optional else base

        if isinstance(t, ast.SetType):
            base = f"Set<{self.gen_type(t.elem)}>"
            return _optional_of(base) if t.optional else base

        if isinstance(t, ast.TupleType):
            args = ", ".join(self.gen_type(e) for e in t.elems)
            base = f"[{args}]"
            return _optional_of(base) if t.optional else base

        if isinstance(t, ast.GenericType):
            base = self._gen_generic_type(t)
            return _optional_of(base) if t.optional else base

        if isinstance(t, ast.UnionType):
            return " | ".join(_union_part(self.gen_type(sub)) for sub in t.types) or "any"

        return "any"

    def _gen_generic_type(self, t: ast.GenericType) -> str:
        args = [self.gen_type(a) for a in t.args]
        base = _typing_short_name(t.base)

        # Myna has no generic declarations, so type arguments on a user class or
        # alias are advisory noise.  Erasing them keeps `Box[int]` valid TypeScript
        # instead of emitting `Box<number>` for a non-generic class.
        if t.base in self.known_classes or t.base in self.type_only_names:
            return js_ident(t.base)
        if base in self.known_classes or base in self.type_only_names:
            return js_ident(base)

        if base == "Callable":
            return self._gen_callable_type(t.args)
        if base == "Optional":
            return _optional_of(args[0]) if args else "any"
        if base == "Union":
            return " | ".join(_union_part(a) for a in args) if args else "any"
        if base in ("list", "List", "Sequence", "MutableSequence"):
            return _array_of(args[0]) if args else "any[]"
        if base in ("dict", "Dict", "Mapping", "MutableMapping"):
            if len(args) == 2:
                return f"Record<{_record_key(args[0])}, {args[1]}>"
            return f"Record<string, {args[0] if args else 'any'}>"
        if base in ("set", "Set", "MutableSet", "FrozenSet", "frozenset"):
            return f"Set<{args[0] if args else 'any'}>"
        if base in ("tuple", "Tuple"):
            return f"[{', '.join(args)}]"
        if base in ("Iterable", "Iterator", "Collection", "Container"):
            return f"Iterable<{args[0] if args else 'any'}>"
        if base in ("AsyncIterable", "AsyncIterator"):
            return f"AsyncIterable<{args[0] if args else 'any'}>"
        if base == "Reversible":
            return _array_of(args[0]) if args else "any[]"
        if base == "Awaitable":
            return f"Promise<{args[0] if args else 'any'}>"
        if base == "Coroutine":
            if len(args) >= 3:
                return f"Promise<{args[2]}>"
            return f"Promise<{args[0] if args else 'any'}>"
        if base == "Generator":
            if len(args) >= 3:
                # Python is Generator[Yield, Send, Return]; TypeScript is
                # Generator<Yield, Return, Next>.
                return f"Generator<{args[0]}, {args[2]}, {args[1]}>"
            if len(args) == 2:
                return f"Generator<{args[0]}, {args[1]}, any>"
            return f"Generator<{args[0] if args else 'any'}, any, any>"
        if base == "AsyncGenerator":
            if len(args) >= 2:
                return f"AsyncGenerator<{args[0]}, {args[1]}>"
            return f"AsyncGenerator<{args[0] if args else 'any'}, any>"
        if base in ("Type", "type"):
            return f"new (...args: any[]) => {args[0] if args else 'any'}"
        if base in (
            "ClassVar",
            "Final",
            "NotRequired",
            "Required",
            "ReadOnly",
            "Annotated",
        ):
            return args[0] if args else "any"
        if base in ("Literal", "LiteralString"):
            return "any" if base == "Literal" else "string"
        if base in ("Self",):
            return self._self_type()
        if base in ("NoReturn", "Never"):
            return "never"
        if base in ("AnyStr", "Text"):
            return "string"

        # An unknown name from a typing namespace has no TypeScript counterpart;
        # `any` is safer than a dangling identifier that fails `tsc`.
        if base != t.base:
            return "any"
        name = TYPE_SHORTHANDS_TS.get(t.base, js_ident(t.base))
        return f"{name}<{', '.join(args)}>"

    def _self_type(self) -> str:
        """Resolve `Self` to the enclosing class, or `any` outside a class."""
        return js_ident(self.current_class) if self.current_class else "any"

    def _match_param(self, name: str) -> str:
        # `tsc --strict` has no contextual type for an immediately-invoked arrow.
        return f"{name}: any"

    def _gen_callable_type(self, args: list[ast.TypeNode]) -> str:
        if len(args) < 2:
            return "(...args: any[]) => any"
        params, ret = args[0], self.gen_type(args[1])
        if isinstance(params, ast.TupleType):
            elems = params.elems
        elif isinstance(params, ast.ListType):
            elems = [params.elem]
        else:
            elems = [params]
        rendered = ", ".join(
            f"arg{index}: {self.gen_type(elem)}" for index, elem in enumerate(elems)
        )
        return f"({rendered}) => {ret}"

    # ------------------------------------------------------------------
    # Parameters and functions
    # ------------------------------------------------------------------

    def gen_param(self, p: ast.Param) -> str:
        if p.kind in ("kwonly_sep", "posonly_sep"):
            return p.name
        name = js_ident(p.name)
        rendered = self.gen_type(p.type_ann) if p.type_ann is not None else "any"
        if p.kind == "vararg":
            s = f"...{name}: {_array_of(rendered)}"
        elif p.kind == "kwarg":
            # The JavaScript projection passes keyword arguments as a trailing
            # object, and Python's `**kwargs` is always optional at the call site.
            s = f"{name}: {rendered} = {{}} as any"
        else:
            s = f"{name}: {rendered}"
        if p.default is not None:
            s += f" = {self.gen_expr(p.default)}"
        return s

    # ------------------------------------------------------------------
    # Statements
    # ------------------------------------------------------------------

    def gen_stmt(self, stmt: ast.Stmt) -> list[str]:
        if isinstance(stmt, ast.TypeAliasStmt):
            return self.gen_type_alias(stmt)
        if isinstance(stmt, ast.DeleteStmt):
            return self.gen_delete_stmt(stmt)
        return super().gen_stmt(stmt)

    def gen_type_alias(self, stmt: ast.TypeAliasStmt) -> list[str]:
        if stmt.name in TS_TYPE_KEYWORDS:
            raise TargetError(
                f"type alias name '{stmt.name}' is reserved in TypeScript"
            )
        self.type_only_names.add(stmt.name)
        bound = js_ident(stmt.name)
        prefix = ""
        if self.indent_level == 0:
            if bound == stmt.name:
                prefix = "export "
            else:
                alias = (bound, stmt.name)
                if alias not in self.type_export_aliases:
                    self.type_export_aliases.append(alias)
        return [
            f"{self.ind()}{prefix}type {bound} = {self.gen_type(stmt.value)};"
        ]

    def gen_delete_stmt(self, stmt: ast.DeleteStmt) -> list[str]:
        parts: list[str] = []
        for target in stmt.targets:
            if isinstance(target, ast.Ident):
                # There is no lexical-binding delete in strict-mode ESM.
                parts.append(f"{js_ident(target.name)} = undefined as any;")
            elif isinstance(target, ast.SelfAttr):
                parts.append(f"delete (this as any).{target.attr};")
            elif isinstance(target, ast.Attribute):
                parts.append(
                    f"delete ({self.gen_expr(target.value)} as any).{target.attr};"
                )
            elif isinstance(target, ast.Subscript):
                parts.append(
                    f"delete ({self.gen_expr(target.value)} as any)"
                    f"[{self.gen_expr(target.slice)}];"
                )
            else:
                parts.append(f"delete {self._gen_lvalue(target)};")
        return [f"{self.ind()}{' '.join(parts)}"]

    def gen_assign_stmt(self, stmt: ast.AssignStmt) -> list[str]:
        val_str = self.gen_expr(stmt.value)
        ann = f": {self.gen_type(stmt.type_ann)}" if stmt.type_ann is not None else ""
        if len(stmt.targets) == 1:
            tgt = stmt.targets[0]
            if isinstance(tgt, ast.Ident):
                bound = js_ident(tgt.name)
                if stmt.op == ":=":
                    self.declare(tgt.name)
                    return [f"{self.ind()}const {bound}{ann} = {val_str};"]
                if stmt.op == "=" and not self.is_declared(tgt.name):
                    self.declare(tgt.name)
                    return [f"{self.ind()}let {bound}{ann} = {val_str};"]
                # A type annotation is only legal at the declaration site.
                return [f"{self.ind()}{bound} {stmt.op} {val_str};"]

            if isinstance(tgt, ast.TupleExpr):
                names = [e.name for e in tgt.elts if isinstance(e, ast.Ident)]
                all_new = bool(names) and all(
                    not self.is_declared(n) and n != "_" for n in names
                )
                for n in names:
                    if n != "_":
                        self.declare(n)
                lhs = self._gen_destructure_target(tgt)
                kw = "let " if all_new else ""
                destructure_ann = ann if all_new else ""
                return [f"{self.ind()}{kw}{lhs}{destructure_ann} = {val_str};"]

            op = "=" if stmt.op == ":=" else stmt.op
            return [f"{self.ind()}{self._gen_lvalue(tgt)} {op} {val_str};"]

        # Chained assignment `a = b = 1`
        lines: list[str] = []
        for t in stmt.targets:
            if isinstance(t, ast.Ident) and not self.is_declared(t.name):
                self.declare(t.name)
                lines.append(f"{self.ind()}let {js_ident(t.name)};")
        chain = " = ".join(self._gen_lvalue(t) for t in stmt.targets)
        lines.append(f"{self.ind()}{chain} = {val_str};")
        return lines

    def gen_class_def(self, cls: ast.ClassDef) -> list[str]:
        if len(cls.bases) > 1:
            raise TargetError(
                f"class '{cls.name}': multiple inheritance is not supported by the "
                "TypeScript target"
            )
        if cls.decorators:
            raise TargetError(
                f"class '{cls.name}': class decorators are not supported by the "
                "TypeScript target"
            )
        if cls.name in TS_TYPE_KEYWORDS:
            raise TargetError(
                f"class name '{cls.name}' is reserved in TypeScript"
            )

        self.declare(cls.name)
        self.known_classes.add(cls.name)
        inline_export = (
            cls.exported
            and self.indent_level == 0
            and js_ident(cls.name) == cls.name
        )
        export_prefix = "export " if inline_export else ""
        if inline_export:
            self.inline_exports.add(cls.name)
        ext_part = ""
        if cls.bases:
            base = cls.bases[0]
            if isinstance(base, ast.Ident) and base.name in PY_EXCEPTIONS:
                self.use_exception(base.name)
            ext_part = f" extends {self.gen_expr(base)}"

        plan = (
            self._dataclass_constructor_plan(cls)
            if cls.is_dataclass and cls.bases
            else None
        )
        if cls.bases and not cls.is_dataclass:
            init = next(
                (
                    stmt
                    for stmt in cls.body
                    if isinstance(stmt, ast.FuncDef) and stmt.method_kind == "init"
                ),
                None,
            )
            if init is not None and not self._calls_super_init(init):
                raise TargetError(
                    f"class '{cls.name}': a derived class with @init must call "
                    "the base constructor with ..init(...)"
                )

        lines = [f"{self.ind()}{export_prefix}class {js_ident(cls.name)}{ext_part} {{"]
        prev_in_class = self.in_class
        prev_class = self.current_class
        self.in_class = True
        self.current_class = cls.name
        self.indent_level += 1
        self.loop_stack.append(None)

        declared: set[str] = set()
        base_field_names = {
            field.name
            for field in (
                self.dataclass_fields.get(cls.bases[0].name, [])
                if cls.is_dataclass
                and cls.bases
                and isinstance(cls.bases[0], ast.Ident)
                else []
            )
        }

        # Dataclass fields become property declarations; the generated constructor
        # assigns them, so definite-assignment assertions are not needed.  Inherited
        # fields are declared by the base class, and redeclaring one without an
        # initializer trips `strictPropertyInitialization` in TypeScript.
        if cls.is_dataclass and cls.fields:
            for f in cls.fields:
                if f.name == "constructor":
                    raise TargetError(
                        f"class '{cls.name}': TypeScript cannot declare a field "
                        "named 'constructor'"
                    )
                if f.name in base_field_names:
                    declared.add(f.name)
                    continue
                rendered = self.gen_type(f.type_ann) if f.type_ann is not None else "any"
                lines.append(f"{self.ind()}{f.name}: {rendered};")
                declared.add(f.name)

        # Inherited dataclass fields are declared by the base class; remember them
        # so `_method_attributes` does not redeclare them on this class.
        if cls.is_dataclass and cls.bases and isinstance(cls.bases[0], ast.Ident):
            declared.update(
                field.name
                for field in self.dataclass_fields.get(cls.bases[0].name, [])
            )

        # Class-body assignments are class fields.  They must be declared before the
        # methods that use them.
        for s in cls.body:
            if not isinstance(s, ast.AssignStmt):
                continue
            for target in s.targets:
                if not isinstance(target, ast.Ident):
                    raise TargetError(
                        f"class '{cls.name}': unpacked class attributes are not "
                        "supported by the TypeScript target"
                    )
                if target.name == "constructor":
                    raise TargetError(
                        f"class '{cls.name}': TypeScript cannot declare a field "
                        "named 'constructor'"
                    )
                rendered = self.gen_type(s.type_ann) if s.type_ann is not None else ""
                annotation = f": {rendered}" if rendered else ""
                lines.append(
                    f"{self.ind()}{target.name}{annotation} = {self.gen_expr(s.value)};"
                )
                declared.add(target.name)

        if cls.is_dataclass and cls.fields:
            params, super_args, assignments = plan or (cls.fields, [], cls.fields)
            p_strs = [self.gen_param(f) for f in params]
            lines.append(f"{self.ind()}constructor({', '.join(p_strs)}) {{")
            self.indent_level += 1
            if cls.bases:
                lines.append(f"{self.ind()}super({', '.join(super_args)});")
            for f in assignments:
                lines.append(f"{self.ind()}this.{f.name} = {js_ident(f.name)};")
            self.indent_level -= 1
            lines.append(f"{self.ind()}}}")

        # Python classes may create attributes in any method.  Declare those that are
        # not already class fields, using the constructor parameter's annotation when
        # `@init` assigns a parameter directly.
        for name, rendered in self._method_attributes(cls, declared):
            lines.append(f"{self.ind()}{name}!: {rendered or 'any'};")

        for s in cls.body:
            if isinstance(s, ast.ExprStmt) and isinstance(s.expr, ast.Literal) and s.expr.kind in ("str", "raw_str"):
                continue
            if isinstance(s, ast.AssignStmt):
                continue
            if (
                isinstance(s, ast.FuncDef)
                and s.name == "constructor"
                and s.method_kind != "init"
            ):
                raise TargetError(
                    f"class '{cls.name}': method 'constructor' is reserved for "
                    "@init in the TypeScript target"
                )
            if isinstance(s, ast.ClassDef):
                raise TargetError(
                    f"class '{cls.name}': nested classes are not supported by the "
                    "TypeScript target"
                )
            if isinstance(s, (ast.FuncDef, ast.NoopStmt)):
                lines.extend(self.gen_stmt(s))
                continue
            raise TargetError(
                f"class '{cls.name}': {type(s).__name__} is not supported in a "
                "TypeScript class body"
            )

        self.loop_stack.pop()
        self.indent_level -= 1
        self.in_class = prev_in_class
        self.current_class = prev_class
        lines.append(f"{self.ind()}}}")
        return lines

    def _method_attributes(
        self, cls: ast.ClassDef, declared: set[str]
    ) -> list[tuple[str, Optional[str]]]:
        found: list[tuple[str, Optional[str]]] = []
        for stmt in cls.body:
            if not isinstance(stmt, ast.FuncDef):
                continue
            param_types: dict[str, str] = {}
            for p in stmt.params:
                if p.type_ann is not None and p.kind not in ("kwonly_sep", "posonly_sep"):
                    rendered = self.gen_type(p.type_ann)
                    param_types[p.name] = (
                        _array_of(rendered) if p.kind == "vararg" else rendered
                    )
            for inner in self._walk_stmts(stmt.body):
                if not isinstance(inner, ast.AssignStmt):
                    continue
                rendered: Optional[str] = None
                if stmt.method_kind == "init" and isinstance(inner.value, ast.Ident):
                    rendered = param_types.get(inner.value.name)
                for attr in self._self_attr_targets(inner.targets):
                    if attr == "constructor":
                        raise TargetError(
                            f"class '{cls.name}': TypeScript cannot declare an "
                            "attribute named 'constructor'"
                        )
                    if attr in declared:
                        continue
                    declared.add(attr)
                    found.append((attr, rendered))
        return found

    def _walk_stmts(self, stmts: list[ast.Stmt]):
        for stmt in stmts:
            yield stmt
            if isinstance(stmt, ast.IfStmt):
                for branch in stmt.branches:
                    yield from self._walk_stmts(branch.body)
                if stmt.else_body is not None:
                    yield from self._walk_stmts(stmt.else_body)
            elif isinstance(stmt, (ast.ForStmt, ast.WhileStmt)):
                yield from self._walk_stmts(stmt.body)
                if stmt.else_body is not None:
                    yield from self._walk_stmts(stmt.else_body)
            elif isinstance(stmt, ast.TryStmt):
                yield from self._walk_stmts(stmt.body)
                for handler in stmt.handlers:
                    yield from self._walk_stmts(handler.body)
                if stmt.else_body is not None:
                    yield from self._walk_stmts(stmt.else_body)
                if stmt.finally_body is not None:
                    yield from self._walk_stmts(stmt.finally_body)
            elif isinstance(stmt, ast.WithStmt):
                yield from self._walk_stmts(stmt.body)
            elif isinstance(stmt, ast.MatchStmt):
                for case in stmt.cases:
                    yield from self._walk_stmts(case.body)

    def _self_attr_targets(self, targets: list[ast.Expr]):
        for target in targets:
            if isinstance(target, ast.SelfAttr):
                yield target.attr
            elif isinstance(target, ast.TupleExpr):
                yield from self._self_attr_targets(target.elts)

    def gen_with_stmt(self, stmt: ast.WithStmt) -> list[str]:
        lines: list[str] = []
        # Python's `with` does not introduce a scope, so a name bound by `as` must
        # remain visible after the block.  `let` without an initializer is `any`
        # under `strict`; the generator assigns it from the context handle.
        for item in stmt.items:
            if item.optional_vars is None:
                continue
            for name in self._binding_names(item.optional_vars):
                if not self.is_declared(name):
                    lines.append(f"{self.ind()}let {js_ident(name)}: any;")
                    self.declare(name)

        # The context handle needs a name that is unique across sibling `with`
        # statements; the statement itself must not add a block because Python's
        # `with` does not scope assignments made in its body.
        self.with_counter += 1
        prefix = f"__ctx_{self.with_counter}"
        self.push_scope()
        for idx, item in enumerate(stmt.items):
            lines.append(
                f"{self.ind()}const {prefix}_{idx} = "
                f"{self.gen_expr(item.context_expr)};"
            )
            if item.optional_vars is not None and not (
                isinstance(item.optional_vars, ast.Ident)
                and item.optional_vars.name == "_"
            ):
                target = self._gen_destructure_target(item.optional_vars)
                # Python rebinding is dynamic; an existing local may have a
                # narrower inferred type, so keep the erased/`any` semantics.
                lines.append(f"{self.ind()}{target} = {prefix}_{idx} as any;")
        lines.append(f"{self.ind()}try {{")
        lines.extend(self.gen_block(stmt.body, new_scope=False))
        lines.append(f"{self.ind()}}} finally {{")
        self.indent_level += 1
        for idx, _ in enumerate(stmt.items):
            lines.append(f"{self.ind()}({prefix}_{idx} as any)?.close?.();")
        self.indent_level -= 1
        lines.append(f"{self.ind()}}}")
        self.pop_scope()
        return lines

    # ------------------------------------------------------------------
    # Relative imports and exports
    # ------------------------------------------------------------------

    def _gen_relative_import(self, stmt: ast.ImportFromStmt) -> list[str]:
        source = self._require_source_path()
        try:
            bindings = resolve_from_import(source, stmt, root=self.import_base)
        except ModuleError as exc:
            raise TargetError(str(exc)) from exc

        emitted = []
        for binding in bindings:
            if binding.path == source and binding.imported is not None:
                continue
            is_type = (
                binding.imported is not None
                and binding.imported in module_type_aliases(binding.path)
            )
            if is_type:
                self.type_only_names.add(binding.local)
            else:
                self.declare(binding.local)
            self.dependencies.add(binding.path)
            if binding.imported is not None and binding.imported in module_classes(
                binding.path
            ):
                self.known_classes.add(binding.local)
            emitted.append(binding)

        lines: list[str] = []
        index = 0
        while index < len(emitted):
            binding = emitted[index]
            spec = self._specifier(binding.path)
            if binding.imported is None:
                lines.append(
                    f'{self.ind()}import * as {js_ident(binding.local)} from "{spec}";'
                )
                index += 1
                continue

            is_type = binding.imported in module_type_aliases(binding.path)
            named: list[str] = []
            while index < len(emitted):
                current = emitted[index]
                if current.imported is None:
                    break
                if self._specifier(current.path) != spec:
                    break
                if (current.imported in module_type_aliases(current.path)) != is_type:
                    break
                bound = js_ident(current.local)
                imported = current.imported
                named.append(imported if bound == imported else f"{imported} as {bound}")
                index += 1
            keyword = "import type" if is_type else "import"
            lines.append(f'{self.ind()}{keyword} {{ {", ".join(named)} }} from "{spec}";')
        return lines

    def export_lines(self, mod: ast.Module) -> list[str]:
        names = [n for n in module_bindings(mod) if n not in self.inline_exports]
        value_names = [n for n in names if n not in self.type_only_names]
        type_names = [n for n in names if n in self.type_only_names]
        lines: list[str] = []

        def specs(source: list[str]) -> str:
            out = []
            for name in source:
                bound = js_ident(name)
                out.append(bound if bound == name else f"{bound} as {name}")
            return ", ".join(out)

        if value_names:
            lines.append(f"export {{ {specs(value_names)} }};")
        if type_names:
            lines.append(f"export type {{ {specs(type_names)} }};")
        for bound, name in self.type_export_aliases:
            lines.append(f"export type {{ {bound} as {name} }};")
        return lines

    # ------------------------------------------------------------------
    # Expressions and helpers
    # ------------------------------------------------------------------

    def _js_isinstance(self, subject: str, expr: ast.Expr) -> str:
        # `instanceof` rejects operands such as `number` or a narrowed `never` under
        # strict TypeScript.  The runtime check is Python's and must keep working for
        # every JavaScript value, so bind/cast the subject to `any` where needed.
        if isinstance(expr, ast.Ident) and expr.name in ("B", "bytes"):
            return f"(({subject}) as any) instanceof Uint8Array"
        if isinstance(expr, ast.SetExpr):
            return f"(({subject}) as any) instanceof Set"
        if isinstance(expr, ast.DictExpr):
            return (
                f"((__v: any) => (__v !== null && typeof __v === 'object'"
                f" && !Array.isArray(__v) && !(__v instanceof Set)"
                f" && !(__v instanceof Map)))({subject})"
            )
        if isinstance(expr, ast.Subscript):
            return self._js_isinstance(subject, expr.value)
        if isinstance(expr, (ast.Ident, ast.TupleExpr, ast.ListExpr)):
            return super()._js_isinstance(subject, expr)
        return f"(({subject}) as any) instanceof {self.gen_expr(expr)}"

    def _ident_value(self, name: str) -> str:
        if name in self.type_only_names and not self.is_declared(name):
            raise TargetError(
                f"type alias '{name}' is a type and cannot be used as a value for "
                "the TypeScript target"
            )
        return super()._ident_value(name)

    def _exception_shim(self, name: str) -> str:
        base = PY_EXCEPTIONS[name] or "Error"
        return (
            f"class {name} extends {base} {{ constructor(message?: any) {{"
            f" super(message); this.name = '{name}'; }} }}"
        )

    def _helper_lines(self) -> list[str]:
        lines: list[str] = []
        for name in PY_EXCEPTION_ORDER:
            if name in self.exception_shims:
                lines.append(self._exception_shim(name))
        for name in HELPER_ORDER:
            if name in self.helpers:
                lines.append(ts_helper_source(name))
        return lines

    def _scan_classes(self, mod: ast.Module) -> None:
        super()._scan_classes(mod)
        for stmt in mod.body:
            if isinstance(stmt, ast.TypeAliasStmt):
                self.type_only_names.add(stmt.name)


def compile_to_ts(
    mod: ast.Module,
    *,
    source_path: Path | str | None = None,
    module_ext: str = ".js",
    import_base: Path | str | None = None,
) -> str:
    """Generate one TypeScript module.

    ``module_ext`` is the extension of the JavaScript files that relative-import
    specifiers point at (``.js`` for a ``.ts`` source, ``.mjs`` for ``.mts``), not the
    extension of the emitted TypeScript file.
    """
    enforce_module_target(mod, "js", label="ts")
    check_call_dict_shorthand(mod)
    gen = TSGenerator(
        source_path=source_path, module_ext=module_ext, import_base=import_base
    )
    return gen.generate(expand_target_blocks(mod, "js"))


def compile_module_ts(
    mod: ast.Module,
    *,
    source_path: Path | str | None = None,
    module_ext: str = ".js",
    import_base: Path | str | None = None,
) -> tuple[str, list[Path]]:
    """Generate one TypeScript module and return it with its relative dependencies."""
    enforce_module_target(mod, "js", label="ts")
    gen = TSGenerator(
        source_path=source_path, module_ext=module_ext, import_base=import_base
    )
    code = gen.generate(expand_target_blocks(mod, "js"))
    return code, sorted(gen.dependencies)
