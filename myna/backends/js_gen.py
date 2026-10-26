"""JavaScript (ES2024+) code generator for the Myna programming language.

Myna semantics are Python semantics (see ``DECISIONS.md`` D-001).  JavaScript is a
bounded target: constructs that can be emulated exactly use the inlined ``__myna_*``
helpers below, and constructs that cannot are rejected with ``TargetError`` instead of
being approximated.
"""

from __future__ import annotations
from typing import Optional

import myna.ast_nodes as ast
from myna.targets import TargetError, enforce_module_target, expand_target_blocks


# Python exception hierarchy entries that do not exist natively in JavaScript.  The
# generator emits these as ``Error`` subclasses on demand so ``!! e:ValueError`` and
# ``!^ValueError(...)`` keep working.
PY_EXCEPTIONS: dict[str, Optional[str]] = {
    "BaseException": None,
    "Exception": "BaseException",
    "ArithmeticError": "Exception",
    "ZeroDivisionError": "ArithmeticError",
    "LookupError": "Exception",
    "KeyError": "LookupError",
    "IndexError": "LookupError",
    "ValueError": "Exception",
    "RuntimeError": "Exception",
    "StopIteration": "Exception",
    "AttributeError": "Exception",
    "AssertionError": "Exception",
    "NameError": "Exception",
    "OSError": "Exception",
    "FileNotFoundError": "OSError",
}

PY_EXCEPTION_ORDER = [
    "BaseException",
    "Exception",
    "ArithmeticError",
    "ZeroDivisionError",
    "LookupError",
    "KeyError",
    "IndexError",
    "ValueError",
    "RuntimeError",
    "StopIteration",
    "AttributeError",
    "AssertionError",
    "NameError",
    "OSError",
    "FileNotFoundError",
]

# Python allows identifiers that JavaScript reserves. Binding positions must be renamed;
# property names (`.default`, `{default: 1}`) are left alone because they are legal.
JS_RESERVED = frozenset(
    {
        "await", "break", "case", "catch", "class", "const", "continue", "debugger",
        "default", "delete", "do", "else", "enum", "export", "extends", "false",
        "finally", "for", "function", "if", "implements", "import", "in", "instanceof",
        "interface", "let", "new", "null", "package", "private", "protected", "public",
        "return", "static", "super", "switch", "this", "throw", "true", "try", "typeof",
        "var", "void", "while", "with", "yield", "arguments", "eval", "undefined",
    }
)


def js_ident(name: str) -> str:
    """Return a safe JavaScript binding name. ``$`` cannot start a Myna identifier."""
    return f"${name}" if name in JS_RESERVED else name


# Builtin aliases that have no faithful JavaScript equivalent.  Using one is a compile
# error for `-t js` rather than silently emitting an invalid identifier.
UNSUPPORTED_JS_BUILTINS = frozenset(
    {
        "@open",
        "@inp",
        "@hash",
        "@id",
        "@dir",
        "@vars",
        "@chr",
        "@ord",
        "@hex",
        "@bin",
        "@oct",
        "@iter",
        "@next",
        "@type",
        "@get",
        "@set_a",
        "@has",
        "@del_a",
        "@dict",
    }
)

# Helper functions, emitted on demand.  They implement the Python behaviour that the
# equivalent JavaScript operator or builtin does not.
HELPERS: dict[str, str] = {
    "str": (
        "function __myna_repr(x) {"
        " if (typeof x === 'string') {"
        "   const q = x.includes(\"'\") && !x.includes('\"') ? '\"' : \"'\";"
        "   const esc = q === '\"' ? x.replace(/\\\\/g, '\\\\\\\\').replace(/\"/g, '\\\\\"')"
        "     : x.replace(/\\\\/g, '\\\\\\\\').replace(/'/g, \"\\\\'\");"
        "   return q + esc + q; }"
        " return __myna_str(x); }"
        "function __myna_str(x) {"
        " if (x === true) return 'True';"
        " if (x === false) return 'False';"
        " if (x === null || x === undefined) return 'None';"
        " if (typeof x === 'string') return x;"
        " if (typeof x === 'number') return Object.is(x, -0) ? '-0.0' : String(x);"
        " if (typeof x === 'bigint') return String(x);"
        " if (x instanceof Error) return x.message;"
        " if (Array.isArray(x)) return '[' + x.map(__myna_repr).join(', ') + ']';"
        " if (x instanceof Uint8Array) return \"b'\" + Array.from(x).map((b) =>"
        "   (b >= 32 && b < 127 && b !== 39 && b !== 92) ? String.fromCharCode(b)"
        "   : '\\\\x' + b.toString(16).padStart(2, '0')).join('') + \"'\";"
        " if (x instanceof Set) return x.size === 0 ? 'set()'"
        "   : '{' + Array.from(x).map(__myna_repr).join(', ') + '}';"
        " if (typeof x === 'object') { const ks = Object.keys(x);"
        "   return ks.length ? '{' + ks.map((k) => __myna_repr(k) + ': ' + __myna_repr(x[k])).join(', ') + '}' : '{}'; }"
        " return String(x); }"
        "function __myna_print(...args) { console.log(args.map(__myna_str).join(' ')); }"
    ),
    "truthy": (
        "function __myna_truthy(x) {"
        " if (x === null || x === undefined || x === false) return false;"
        " if (typeof x === 'number' || typeof x === 'bigint') return x !== 0;"
        " if (typeof x === 'string') return x.length > 0;"
        " if (Array.isArray(x) || x instanceof Uint8Array) return x.length > 0;"
        " if (x instanceof Map || x instanceof Set) return x.size > 0;"
        " if (typeof x === 'object') return Object.keys(x).length > 0;"
        " return true; }"
    ),
    "eq": (
        "function __myna_eq(a, b) {"
        " if (a === b) return true;"
        " if (a === null || a === undefined || b === null || b === undefined)"
        "   return (a === null || a === undefined) && (b === null || b === undefined);"
        " if (typeof a === 'boolean' && typeof b === 'number') return (a ? 1 : 0) === b;"
        " if (typeof b === 'boolean' && typeof a === 'number') return (b ? 1 : 0) === a;"
        " if (typeof a !== typeof b) return false;"
        " if (Array.isArray(a) || Array.isArray(b))"
        "   return Array.isArray(a) && Array.isArray(b) && a.length === b.length"
        "     && a.every((v, i) => __myna_eq(v, b[i]));"
        " if (a instanceof Uint8Array || b instanceof Uint8Array)"
        "   return a instanceof Uint8Array && b instanceof Uint8Array && a.length === b.length"
        "     && a.every((v, i) => v === b[i]);"
        " if (a instanceof Set || b instanceof Set) {"
        "   if (!(a instanceof Set) || !(b instanceof Set) || a.size !== b.size) return false;"
        "   for (const x of a) { let found = false;"
        "     for (const y of b) if (__myna_eq(x, y)) { found = true; break; }"
        "     if (!found) return false; }"
        "   return true; }"
        " if (a instanceof Map || b instanceof Map) {"
        "   if (!(a instanceof Map) || !(b instanceof Map) || a.size !== b.size) return false;"
        "   for (const [k, v] of a) if (!b.has(k) || !__myna_eq(v, b.get(k))) return false;"
        "   return true; }"
        " if (typeof a === 'object') {"
        "   const ka = Object.keys(a), kb = Object.keys(b);"
        "   return ka.length === kb.length"
        "     && ka.every((k) => Object.prototype.hasOwnProperty.call(b, k) && __myna_eq(a[k], b[k])); }"
        " return false; }"
    ),
    "add": (
        "function __myna_add(a, b) {"
        " const n = (v) => typeof v === 'boolean' ? (v ? 1 : 0) : v;"
        " if ((typeof a === 'number' || typeof a === 'boolean')"
        "   && (typeof b === 'number' || typeof b === 'boolean')) return n(a) + n(b);"
        " if (typeof a === 'string' && typeof b === 'string') return a + b;"
        " if (Array.isArray(a) && Array.isArray(b)) return [...a, ...b];"
        " if (a instanceof Uint8Array && b instanceof Uint8Array) {"
        "   const r = new Uint8Array(a.length + b.length); r.set(a); r.set(b, a.length); return r; }"
        " throw new TypeError('unsupported operand type(s) for +'); }"
    ),
    "sub": (
        "function __myna_sub(a, b) {"
        " const n = (v) => typeof v === 'boolean' ? (v ? 1 : 0) : v;"
        " if ((typeof a === 'number' || typeof a === 'boolean')"
        "   && (typeof b === 'number' || typeof b === 'boolean')) return n(a) - n(b);"
        " throw new TypeError('unsupported operand type(s) for -'); }"
    ),
    "mul": (
        "function __myna_mul(a, b) {"
        " const n = (v) => typeof v === 'boolean' ? (v ? 1 : 0) : v;"
        " if ((typeof a === 'number' || typeof a === 'boolean')"
        "   && (typeof b === 'number' || typeof b === 'boolean')) return n(a) * n(b);"
        " const repeat = (seq, count, empty) => {"
        "   if (!Number.isInteger(count)) throw new TypeError('can not multiply sequence by non-int');"
        "   if (count <= 0) return empty();"
        "   let out = empty(); for (let i = 0; i < count; i++) out = __myna_add(out, seq); return out; };"
        " if (typeof a === 'string' && typeof b === 'number') return repeat(a, b, () => '');"
        " if (typeof b === 'string' && typeof a === 'number') return repeat(b, a, () => '');"
        " if (Array.isArray(a) && typeof b === 'number') return repeat(a, b, () => []);"
        " if (Array.isArray(b) && typeof a === 'number') return repeat(b, a, () => []);"
        " if (a instanceof Uint8Array && typeof b === 'number') return repeat(a, b, () => new Uint8Array());"
        " if (b instanceof Uint8Array && typeof a === 'number') return repeat(b, a, () => new Uint8Array());"
        " throw new TypeError('unsupported operand type(s) for *'); }"
    ),
    "div": (
        "function __myna_div(a, b) {"
        " const n = (v) => typeof v === 'boolean' ? (v ? 1 : 0) : v;"
        " if ((typeof a !== 'number' && typeof a !== 'boolean')"
        "   || (typeof b !== 'number' && typeof b !== 'boolean'))"
        "   throw new TypeError('unsupported operand type(s) for /');"
        " if (n(b) === 0) throw new ZeroDivisionError('division by zero');"
        " return n(a) / n(b); }"
    ),
    "floordiv": (
        "function __myna_floordiv(a, b) {"
        " const n = (v) => typeof v === 'boolean' ? (v ? 1 : 0) : v;"
        " if ((typeof a !== 'number' && typeof a !== 'boolean')"
        "   || (typeof b !== 'number' && typeof b !== 'boolean'))"
        "   throw new TypeError('unsupported operand type(s) for //');"
        " if (n(b) === 0) throw new ZeroDivisionError('integer division or modulo by zero');"
        " return Math.floor(n(a) / n(b)); }"
    ),
    "mod": (
        "function __myna_mod(a, b) {"
        " const n = (v) => typeof v === 'boolean' ? (v ? 1 : 0) : v;"
        " if ((typeof a !== 'number' && typeof a !== 'boolean')"
        "   || (typeof b !== 'number' && typeof b !== 'boolean'))"
        "   throw new TypeError('unsupported operand type(s) for %');"
        " if (n(b) === 0) throw new ZeroDivisionError('integer modulo by zero');"
        " return n(a) - n(b) * Math.floor(n(a) / n(b)); }"
    ),
    "neg": (
        "function __myna_neg(a) {"
        " if (typeof a === 'boolean') return -(a ? 1 : 0);"
        " if (typeof a !== 'number') throw new TypeError('bad operand type for unary -');"
        " return -a; }"
    ),
    "pos": (
        "function __myna_pos(a) {"
        " if (typeof a === 'boolean') return a ? 1 : 0;"
        " if (typeof a !== 'number') throw new TypeError('bad operand type for unary +');"
        " return +a; }"
    ),
    "len": (
        "function __myna_len(x) {"
        " if (x === null || x === undefined) throw new TypeError(\"object of type 'NoneType' has no len()\");"
        " if (typeof x === 'string') return Array.from(x).length;"
        " if (Array.isArray(x) || x instanceof Uint8Array) return x.length;"
        " if (x instanceof Map || x instanceof Set) return x.size;"
        " if (typeof x === 'object') return Object.keys(x).length;"
        " throw new TypeError('object has no len()'); }"
    ),
    "in": (
        "function __myna_in(x, c) {"
        " if (typeof c === 'string') {"
        "   if (typeof x !== 'string') throw new TypeError(\"'in <string>' requires string as left operand\");"
        "   return c.includes(x); }"
        " if (c instanceof Uint8Array) {"
        "   if (typeof x !== 'number') throw new TypeError('a bytes-like object is required');"
        "   return c.includes(x); }"
        " if (Array.isArray(c)) return c.some((v) => __myna_eq(v, x));"
        " if (c instanceof Set) { for (const v of c) if (__myna_eq(v, x)) return true; return false; }"
        " if (c instanceof Map) { for (const k of c.keys()) if (__myna_eq(k, x)) return true; return false; }"
        " if (c !== null && typeof c === 'object') return Object.prototype.hasOwnProperty.call(c, x);"
        " throw new TypeError('argument is not iterable'); }"
    ),
    "getitem": (
        "function __myna_getitem(o, k) {"
        " if (typeof o === 'string' || Array.isArray(o) || o instanceof Uint8Array) {"
        "   const seq = typeof o === 'string' ? Array.from(o) : o;"
        "   if (typeof k !== 'number') throw new TypeError('indices must be integers');"
        "   let i = Math.trunc(k); if (i < 0) i += seq.length;"
        "   if (i < 0 || i >= seq.length) throw new IndexError('index out of range');"
        "   return seq[i]; }"
        " if (o instanceof Map) { if (!o.has(k)) throw new KeyError(JSON.stringify(k)); return o.get(k); }"
        " if (o !== null && typeof o === 'object') {"
        "   if (!Object.prototype.hasOwnProperty.call(o, k)) throw new KeyError(JSON.stringify(k));"
        "   return o[k]; }"
        " throw new TypeError('object is not subscriptable'); }"
    ),
    "get": (
        "function __myna_get(o, k, dflt) {"
        " if (o !== null && o !== undefined) {"
        "   if (typeof o === 'string' || Array.isArray(o)) {"
        "     let i = typeof k === 'number' ? Math.trunc(k) : NaN; if (i < 0) i += o.length;"
        "     if (i >= 0 && i < o.length) return typeof o === 'string' ? Array.from(o)[i] : o[i];"
        "   } else if (o instanceof Map) { if (o.has(k)) return o.get(k); }"
        "   else if (typeof o === 'object' && Object.prototype.hasOwnProperty.call(o, k)) return o[k]; }"
        " return arguments.length > 2 ? dflt : null; }"
    ),
    "slice": (
        "function __myna_slice(x, lo, hi, step) {"
        " step = step === undefined || step === null ? 1 : step;"
        " if (step === 0) throw new ValueError('slice step cannot be zero');"
        " const src = typeof x === 'string' ? Array.from(x) : x;"
        " const len = src.length;"
        " const norm = (v, dflt) => v === undefined || v === null ? dflt : (v < 0 ? v + len : v);"
        " let start, stop;"
        " if (step > 0) {"
        "   start = Math.min(Math.max(norm(lo, 0), 0), len);"
        "   stop = Math.min(Math.max(norm(hi, len), 0), len);"
        " } else {"
        "   start = Math.min(Math.max(norm(lo, len - 1), -1), len - 1);"
        "   stop = Math.min(Math.max(norm(hi, -1), -1), len - 1); }"
        " const out = [];"
        " if (step > 0) for (let i = start; i < stop; i += step) out.push(src[i]);"
        " else for (let i = start; i > stop; i += step) out.push(src[i]);"
        " return typeof x === 'string' ? out.join('') : (x instanceof Uint8Array ? new Uint8Array(out) : out); }"
    ),
    "iter": (
        "function __myna_iter(x) {"
        " if (x === null || x === undefined) throw new TypeError(\"'NoneType' object is not iterable\");"
        " if (typeof x === 'string' || Array.isArray(x) || x instanceof Uint8Array"
        "   || x instanceof Set || x instanceof Map || typeof x[Symbol.iterator] === 'function')"
        "   return Array.from(x);"
        " if (typeof x === 'object') return Object.keys(x);"
        " throw new TypeError('object is not iterable'); }"
    ),
    "range": (
        "function __myna_range(a, b, s = 1) {"
        " if (b === undefined) { b = a; a = 0; }"
        " if (s === 0) throw new ValueError('range() arg 3 must not be zero');"
        " const r = [];"
        " if (s > 0) for (let i = a; i < b; i += s) r.push(i);"
        " else for (let i = a; i > b; i += s) r.push(i);"
        " return r; }"
    ),
    "sort": (
        "function __myna_sort(seq, key, reverse) {"
        " const kf = key || ((v) => v);"
        " const decorated = Array.from(seq).map((v, i) => [kf(v), i, v]);"
        " decorated.sort((a, b) => {"
        "   let c; const x = a[0], y = b[0];"
        "   if (typeof x === 'number' && typeof y === 'number') c = x - y;"
        "   else if (x < y) c = -1; else if (x > y) c = 1; else c = 0;"
        "   if (reverse) c = -c;"
        "   return c || (a[1] - b[1]); });"
        " return decorated.map((d) => d[2]); }"
    ),
    "zip": (
        "function __myna_zip(...its) {"
        " const arrs = its.map((x) => Array.from(x));"
        " const n = arrs.length ? Math.min(...arrs.map((a) => a.length)) : 0;"
        " const out = []; for (let i = 0; i < n; i++) out.push(arrs.map((a) => a[i]));"
        " return out; }"
    ),
    "min": (
        "function __myna_min(...a) {"
        " const items = a.length === 1 && (Array.isArray(a[0]) || typeof a[0] === 'string'"
        "   || a[0] instanceof Set || a[0] instanceof Map || a[0] instanceof Uint8Array)"
        "   ? Array.from(a[0]) : a;"
        " if (items.length === 0) throw new ValueError('min() arg is an empty sequence');"
        " let best = items[0];"
        " for (const v of items.slice(1)) if (v < best) best = v;"
        " return best; }"
    ),
    "max": (
        "function __myna_max(...a) {"
        " const items = a.length === 1 && (Array.isArray(a[0]) || typeof a[0] === 'string'"
        "   || a[0] instanceof Set || a[0] instanceof Map || a[0] instanceof Uint8Array)"
        "   ? Array.from(a[0]) : a;"
        " if (items.length === 0) throw new ValueError('max() arg is an empty sequence');"
        " let best = items[0];"
        " for (const v of items.slice(1)) if (v > best) best = v;"
        " return best; }"
    ),
    "sum": (
        "function __myna_sum(seq, start = 0) {"
        " let acc = start; for (const v of seq) acc = __myna_add(acc, v); return acc; }"
    ),
    "all": (
        "function __myna_all(seq) {"
        " for (const v of seq) if (!__myna_truthy(v)) return false; return true; }"
    ),
    "any": (
        "function __myna_any(seq) {"
        " for (const v of seq) if (__myna_truthy(v)) return true; return false; }"
    ),
}

HELPER_ORDER = [
    "str",
    "truthy",
    "eq",
    "add",
    "sub",
    "mul",
    "div",
    "floordiv",
    "mod",
    "neg",
    "pos",
    "len",
    "in",
    "getitem",
    "get",
    "slice",
    "iter",
    "range",
    "sort",
    "zip",
    "min",
    "max",
    "sum",
    "all",
    "any",
]

# Aliases usable as first-class values (`x |> @sum`).  Values may reference helpers.
BUILTIN_VALUES: dict[str, str] = {
    "@j": "JSON.parse",
    "@J": "JSON.stringify",
    "@str": "__myna_str",
    "@repr": "__myna_repr",
    "@int": "Math.trunc",
    "@float": "Number",
    "@abs": "Math.abs",
    "@rnd": "Math.round",
    "@pow": "Math.pow",
    "@list": "Array.from",
    "@tuple": "Array.from",
    "@set": "(x) => new Set(x)",
    "@u8": "(x) => new TextEncoder().encode(x)",
    "@u8d": "(x) => new TextDecoder().decode(x)",
    "@rev": "(x) => Array.from(x).reverse()",
    "@enum": "(x) => Array.from(x).entries()",
    "@zip": "__myna_zip",
    "@map": "(f, x) => Array.from(x).map(f)",
    "@flt": "(f, x) => Array.from(x).filter(f)",
    "@srt": "__myna_sort",
    "@sum": "__myna_sum",
    "@min": "__myna_min",
    "@max": "__myna_max",
    "@all": "__myna_all",
    "@any": "__myna_any",
    "@bool": "__myna_truthy",
}


class JSGenerator:
    def __init__(self, indent_str: str = "  "):
        self.indent_str = indent_str
        self.indent_level = 0
        self.in_class = False
        self.scopes: list[set[str]] = [set()]
        self.known_classes: set[str] = set()
        self.helpers: set[str] = set()
        self.exception_shims: set[str] = set()
        self.loop_stack: list[Optional[str]] = []
        self.loop_counter = 0
        self.exc_var_stack: list[str] = []

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

    # ------------------------------------------------------------------
    # Helper bookkeeping
    # ------------------------------------------------------------------

    def use_helper(self, name: str) -> None:
        """Register a helper (and its dependencies) for emission."""
        if name in self.helpers:
            return
        self.helpers.add(name)
        if name == "print":
            self.use_helper("str")
        elif name in ("sum", "mul"):
            self.use_helper("add")
        elif name == "in":
            self.use_helper("eq")
        elif name in ("all", "any"):
            self.use_helper("truthy")
        elif name in ("getitem",):
            self.use_exception("KeyError")
            self.use_exception("IndexError")
        elif name in ("slice", "range", "min", "max"):
            self.use_exception("ValueError")
        elif name in ("div", "floordiv", "mod"):
            self.use_exception("ZeroDivisionError")

    def use_exception(self, name: str) -> None:
        """Emit the Python-style exception class for `name` if it has no JS equivalent."""
        if name not in PY_EXCEPTIONS or name in self.known_classes:
            return
        cur: Optional[str] = name
        while cur is not None:
            self.exception_shims.add(cur)
            cur = PY_EXCEPTIONS[cur]

    def _exception_shim(self, name: str) -> str:
        base = PY_EXCEPTIONS[name] or "Error"
        return (
            f"class {name} extends {base} {{ constructor(message) {{"
            f" super(message); this.name = '{name}'; }} }}"
        )

    def _helper_lines(self) -> list[str]:
        lines: list[str] = []
        for name in PY_EXCEPTION_ORDER:
            if name in self.exception_shims:
                lines.append(self._exception_shim(name))
        for name in HELPER_ORDER:
            if name in self.helpers:
                lines.append(HELPERS[name])
        return lines

    def generate(self, mod: ast.Module) -> str:
        self._scan_classes(mod)
        lines: list[str] = []
        for stmt in mod.body:
            lines.extend(self.gen_stmt(stmt))

        helpers = self._helper_lines()
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
            parts: list[str] = []
            for target in stmt.targets:
                if isinstance(target, ast.Ident):
                    # `delete x` is a SyntaxError for lexical bindings in strict mode.
                    parts.append(f"{js_ident(target.name)} = undefined;")
                else:
                    parts.append(f"delete {self._gen_lvalue(target)};")
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
                lines.append(f'{self.ind()}import * as {js_ident(local)} from "{a.name}";')
            return lines

        if isinstance(stmt, ast.ImportFromStmt):
            if stmt.level > 0:
                raise TargetError(
                    "relative imports are not supported by the JavaScript target; "
                    "use an absolute specifier or compile for Python"
                )
            mod = stmt.module or ""
            specs: list[str] = []
            for a in stmt.names:
                local = a.asname or a.name
                self.declare(local)
                bound = js_ident(local)
                specs.append(f"{a.name} as {bound}" if bound != a.name else a.name)
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
            flag = self.loop_stack[-1] if self.loop_stack else None
            if flag:
                return [f"{self.ind()}{flag} = true;", f"{self.ind()}break;"]
            return [f"{self.ind()}break;"]

        if isinstance(stmt, ast.ContinueStmt):
            return [f"{self.ind()}continue;"]

        if isinstance(stmt, ast.TryStmt):
            return self.gen_try_stmt(stmt)

        if isinstance(stmt, ast.RaiseStmt):
            if stmt.exc is None:
                if self.exc_var_stack:
                    return [f"{self.ind()}throw {self.exc_var_stack[-1]};"]
                self.use_exception("RuntimeError")
                return [
                    f"{self.ind()}throw new RuntimeError('No active exception to reraise');"
                ]
            return [f"{self.ind()}throw {self.gen_expr(stmt.exc)};"]

        if isinstance(stmt, ast.AssertStmt):
            self.use_helper("truthy")
            self.use_exception("AssertionError")
            test_s = self.gen_expr(stmt.test)
            msg_s = self.gen_expr(stmt.msg) if stmt.msg is not None else "''"
            return [
                f"{self.ind()}if (!__myna_truthy({test_s})) throw new AssertionError({msg_s});"
            ]

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
                bound = js_ident(tgt.name)
                if stmt.op == ":=":
                    self.declare(tgt.name)
                    return [f"{self.ind()}const {bound} = {val_str};"]
                if stmt.op == "=" and not self.is_declared(tgt.name):
                    self.declare(tgt.name)
                    return [f"{self.ind()}let {bound} = {val_str};"]
                return [f"{self.ind()}{bound} {stmt.op} {val_str};"]

            if isinstance(tgt, ast.TupleExpr):
                names = [e.name for e in tgt.elts if isinstance(e, ast.Ident)]
                all_new = bool(names) and all(not self.is_declared(n) and n != "_" for n in names)
                for n in names:
                    if n != "_":
                        self.declare(n)
                lhs = self._gen_destructure_target(tgt)
                kw = "let " if all_new else ""
                return [f"{self.ind()}{kw}{lhs} = {val_str};"]

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

    def _gen_lvalue(self, expr: ast.Expr) -> str:
        """Generate an assignable reference (never a throwing read helper)."""
        if isinstance(expr, ast.Subscript):
            return f"{self.gen_expr(expr.value, 90)}[{self.gen_expr(expr.slice)}]"
        return self.gen_expr(expr)

    def _gen_destructure_target(self, expr: ast.Expr) -> str:
        if isinstance(expr, ast.TupleExpr):
            parts: list[str] = []
            for idx, e in enumerate(expr.elts):
                if isinstance(e, ast.Ident) and e.name == "_":
                    parts.append(f"__unused_{idx}")
                else:
                    parts.append(self._gen_destructure_target(e))
            return f"[{', '.join(parts)}]"
        return self._gen_lvalue(expr)

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

        if self.in_class and fn.decorators:
            raise TargetError(
                f"method decorators are not supported by the JavaScript target "
                f"(method '{fn.name}')"
            )

        param_names = {p.name for p in fn.params if p.kind not in ("kwonly_sep", "posonly_sep")}
        param_strs = [self.gen_param(p) for p in fn.params if p.kind not in ("kwonly_sep", "posonly_sep")]

        self.push_scope(param_names)
        self.loop_stack.append(None)
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
            header = f"{self.ind()}{export_prefix}{async_prefix}function{star_suffix} {js_ident(fn.name)}({', '.join(param_strs)}) {{"

        lines.append(header)
        lines.extend(self.gen_block(fn.body, new_scope=False))
        lines.append(f"{self.ind()}}}")

        # Apply decorators if present outside class
        if fn.decorators and not self.in_class:
            bound = js_ident(fn.name)
            for dec in reversed(fn.decorators):
                lines.append(f"{self.ind()}{bound} = {self.gen_expr(dec)}({bound});")

        self.loop_stack.pop()
        self.pop_scope()
        return lines

    def gen_param(self, p: ast.Param) -> str:
        prefix = "..." if p.kind == "vararg" else ""
        s = f"{prefix}{js_ident(p.name)}"
        if p.default is not None:
            s += f" = {self.gen_expr(p.default)}"
        return s

    def gen_class_def(self, cls: ast.ClassDef) -> list[str]:
        if len(cls.bases) > 1:
            raise TargetError(
                f"class '{cls.name}': multiple inheritance is not supported by the JavaScript target"
            )
        if cls.decorators:
            raise TargetError(
                f"class '{cls.name}': class decorators are not supported by the JavaScript target"
            )

        self.declare(cls.name)
        self.known_classes.add(cls.name)
        export_prefix = "export " if (cls.exported and self.indent_level == 0) else ""
        ext_part = ""
        if cls.bases:
            base = cls.bases[0]
            if isinstance(base, ast.Ident) and base.name in PY_EXCEPTIONS:
                self.use_exception(base.name)
            ext_part = f" extends {self.gen_expr(base)}"

        lines = [f"{self.ind()}{export_prefix}class {js_ident(cls.name)}{ext_part} {{"]
        prev_in_class = self.in_class
        self.in_class = True
        self.indent_level += 1
        self.loop_stack.append(None)

        # If dataclass `$$C(id:i, name:s="a")`, auto-generate constructor!
        if cls.is_dataclass and cls.fields:
            p_strs = [self.gen_param(f) for f in cls.fields]
            lines.append(f"{self.ind()}constructor({', '.join(p_strs)}) {{")
            self.indent_level += 1
            for f in cls.fields:
                lines.append(f"{self.ind()}this.{f.name} = {js_ident(f.name)};")
            self.indent_level -= 1
            lines.append(f"{self.ind()}}}")

        for s in cls.body:
            # Python class bodies execute once and may hold docstrings, attributes, and
            # methods. JS class bodies only accept fields and methods: emit attributes as
            # class fields and reject anything that has no class-body equivalent.
            if isinstance(s, ast.ExprStmt) and isinstance(s.expr, ast.Literal) and s.expr.kind in ("str", "raw_str"):
                continue
            if isinstance(s, ast.AssignStmt):
                for target in s.targets:
                    if not isinstance(target, ast.Ident):
                        raise TargetError(
                            f"class '{cls.name}': unpacked class attributes are not supported "
                            "by the JavaScript target"
                        )
                    lines.append(f"{self.ind()}{target.name} = {self.gen_expr(s.value)};")
                continue
            if isinstance(s, (ast.FuncDef, ast.ClassDef, ast.NoopStmt)):
                lines.extend(self.gen_stmt(s))
                continue
            raise TargetError(
                f"class '{cls.name}': {type(s).__name__} is not supported in a JavaScript "
                "class body"
            )

        self.loop_stack.pop()
        self.indent_level -= 1
        self.in_class = prev_in_class
        lines.append(f"{self.ind()}}}")
        return lines

    def gen_if_stmt(self, stmt: ast.IfStmt) -> list[str]:
        self.use_helper("truthy")
        lines: list[str] = []
        for idx, br in enumerate(stmt.branches):
            kw = "if" if idx == 0 else "} else if"
            lines.append(f"{self.ind()}{kw} (__myna_truthy({self.gen_expr(br.cond)})) {{")
            lines.extend(self.gen_block(br.body))
        if stmt.else_body is not None:
            lines.append(f"{self.ind()}}} else {{")
            lines.extend(self.gen_block(stmt.else_body))
        lines.append(f"{self.ind()}}}")
        return lines

    def gen_match_stmt(self, stmt: ast.MatchStmt) -> list[str]:
        # Compile `?? subject { pat ? guard => body }` to a clean block with `__match_val`
        self.use_helper("eq")
        self.use_helper("truthy")
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
            elif is_wildcard:
                cond = f"__myna_truthy({self.gen_expr(c.guard)})"
                lines.append(f"{self.ind()}{kw} ({cond}) {{")
                lines.extend(self.gen_block(c.body))
            elif is_capture:
                self.push_scope({c.pattern.name})
                bound = js_ident(c.pattern.name)
                cond = "true"
                if c.guard is not None:
                    cond = f"((({bound}) => (__myna_truthy({self.gen_expr(c.guard)})))(__match_val))"
                lines.append(f"{self.ind()}{kw} ({cond}) {{")
                self.indent_level += 1
                lines.append(f"{self.ind()}const {bound} = __match_val;")
                for s in c.body:
                    lines.extend(self.gen_stmt(s))
                self.indent_level -= 1
                self.pop_scope()
            else:
                cond = f"__myna_eq(__match_val, {self.gen_expr(c.pattern)})"
                if c.guard is not None:
                    cond = f"({cond}) && (__myna_truthy({self.gen_expr(c.guard)}))"
                lines.append(f"{self.ind()}{kw} ({cond}) {{")
                lines.extend(self.gen_block(c.body))
        if stmt.cases:
            lines.append(f"{self.ind()}}}")
        self.indent_level -= 1
        lines.append(f"{self.ind()}}}")
        return lines

    def gen_for_stmt(self, stmt: ast.ForStmt) -> list[str]:
        self.loop_counter += 1
        flag = f"__myna_brk_{self.loop_counter}" if stmt.else_body is not None else None
        lines: list[str] = []
        if flag:
            lines.append(f"{self.ind()}let {flag} = false;")

        tgt_s = self._gen_destructure_target(stmt.target)
        bound_names: set[str] = set()
        if isinstance(stmt.target, ast.Ident):
            bound_names.add(stmt.target.name)
        elif isinstance(stmt.target, ast.TupleExpr):
            bound_names.update(e.name for e in stmt.target.elts if isinstance(e, ast.Ident))

        if stmt.is_async:
            iter_s = self.gen_expr(stmt.iter)
            head = f"{self.ind()}for await (const {tgt_s} of {iter_s}) {{"
        else:
            self.use_helper("iter")
            iter_s = f"__myna_iter({self.gen_expr(stmt.iter)})"
            head = f"{self.ind()}for (let {tgt_s} of {iter_s}) {{"

        lines.append(head)
        self.push_scope(bound_names)
        self.loop_stack.append(flag)
        lines.extend(self.gen_block(stmt.body, new_scope=False))
        self.loop_stack.pop()
        self.pop_scope()
        lines.append(f"{self.ind()}}}")

        if flag and stmt.else_body is not None:
            lines.append(f"{self.ind()}if (!{flag}) {{")
            lines.extend(self.gen_block(stmt.else_body))
            lines.append(f"{self.ind()}}}")
        return lines

    def gen_while_stmt(self, stmt: ast.WhileStmt) -> list[str]:
        self.use_helper("truthy")
        self.loop_counter += 1
        flag = f"__myna_brk_{self.loop_counter}" if stmt.else_body is not None else None
        lines: list[str] = []
        if flag:
            lines.append(f"{self.ind()}let {flag} = false;")
        lines.append(f"{self.ind()}while (__myna_truthy({self.gen_expr(stmt.cond)})) {{")
        self.loop_stack.append(flag)
        lines.extend(self.gen_block(stmt.body))
        self.loop_stack.pop()
        lines.append(f"{self.ind()}}}")
        if flag and stmt.else_body is not None:
            lines.append(f"{self.ind()}if (!{flag}) {{")
            lines.extend(self.gen_block(stmt.else_body))
            lines.append(f"{self.ind()}}}")
        return lines

    def _exc_match(self, exc_type: Optional[ast.Expr], evar: str) -> Optional[str]:
        """Return a JS condition matching an exception, or None for a catch-all."""
        if exc_type is None:
            return None
        if isinstance(exc_type, ast.Ident):
            name = exc_type.name
            if name in ("Exception", "BaseException", "Error"):
                return None
            self.use_exception(name)
            if name == "ValueError":
                # Python's json.JSONDecodeError is a ValueError; JS JSON.parse throws SyntaxError.
                return f"({evar} instanceof ValueError || {evar} instanceof SyntaxError)"
            return f"({evar} instanceof {name})"
        if isinstance(exc_type, ast.TupleExpr):
            parts = [self._exc_match(e, evar) for e in exc_type.elts]
            if any(p is None for p in parts):
                return None
            return "(" + " || ".join(p for p in parts if p) + ")"
        return f"({evar} instanceof {self.gen_expr(exc_type)})"

    def gen_try_stmt(self, stmt: ast.TryStmt) -> list[str]:
        ind = self.ind()
        if not stmt.handlers:
            # finally-only try: the parser rejects handler-less tries without a finally.
            assert stmt.finally_body is not None
            lines = [f"{ind}try {{"]
            lines.extend(self.gen_block(stmt.body))
            lines.append(f"{ind}}} finally {{")
            lines.extend(self.gen_block(stmt.finally_body))
            lines.append(f"{ind}}}")
            return lines

        if stmt.finally_body is None:
            return self._gen_try_core(stmt)

        # Handler chain plus finally: the chain is a complete try statement, so wrap it.
        lines = [f"{ind}try {{"]
        self.indent_level += 1
        lines.extend(self._gen_try_core(stmt))
        self.indent_level -= 1
        lines.append(f"{ind}}} finally {{")
        lines.extend(self.gen_block(stmt.finally_body))
        lines.append(f"{ind}}}")
        return lines

    def _gen_try_core(self, stmt: ast.TryStmt) -> list[str]:
        ind = self.ind()
        has_else = stmt.else_body is not None
        lines: list[str] = []
        if has_else:
            lines.append(f"{ind}let __myna_ok = true;")
        lines.append(f"{ind}try {{")
        lines.extend(self.gen_block(stmt.body))

        if stmt.handlers:
            evar = "__myna_exc"
            lines.append(f"{ind}}} catch ({evar}) {{")
            self.indent_level += 1
            if has_else:
                lines.append(f"{self.ind()}__myna_ok = false;")
            self.exc_var_stack.append(evar)
            self.push_scope()

            chain_open = False
            catch_all = False
            for handler in stmt.handlers:
                match = self._exc_match(handler.exc_type, evar)
                if match is None:
                    if not chain_open:
                        if handler.name:
                            lines.append(f"{self.ind()}const {js_ident(handler.name)} = {evar};")
                        lines.extend(self.gen_block(handler.body, new_scope=False))
                    else:
                        lines.append(f"{self.ind()}}} else {{")
                        if handler.name:
                            lines.append(
                                f"{self.ind()}{self.indent_str}const {js_ident(handler.name)} = {evar};"
                            )
                        lines.extend(self.gen_block(handler.body, new_scope=False))
                        lines.append(f"{self.ind()}}}")
                    catch_all = True
                    break

                kw = "if" if not chain_open else "} else if"
                lines.append(f"{self.ind()}{kw} ({match}) {{")
                if handler.name:
                    lines.append(f"{self.ind()}{self.indent_str}const {js_ident(handler.name)} = {evar};")
                lines.extend(self.gen_block(handler.body, new_scope=False))
                chain_open = True

            if chain_open and not catch_all:
                lines.append(f"{self.ind()}}} else {{")
                lines.append(f"{self.ind()}{self.indent_str}throw {evar};")
                lines.append(f"{self.ind()}}}")

            self.pop_scope()
            self.exc_var_stack.pop()
            self.indent_level -= 1
            lines.append(f"{ind}}}")

            if has_else:
                lines.append(f"{ind}if (__myna_ok) {{")
                lines.extend(self.gen_block(stmt.else_body))
                lines.append(f"{ind}}}")
        else:
            # try/finally with no handlers
            lines.append(f"{ind}}}")

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
            return self._ident_value(expr.name)

        if isinstance(expr, ast.SelfAttr):
            return f"this.{expr.attr}"

        if isinstance(expr, ast.SuperAttr):
            if expr.attr == "init":
                return "super"
            return f"super.{expr.attr}"

        if isinstance(expr, ast.UnaryOp):
            if expr.op == "#":
                self.use_helper("len")
                return f"__myna_len({self.gen_expr(expr.operand)})"
            if expr.op == "!":
                self.use_helper("truthy")
                return f"!__myna_truthy({self.gen_expr(expr.operand)})"
            if expr.op == "-":
                self.use_helper("neg")
                return f"__myna_neg({self.gen_expr(expr.operand)})"
            if expr.op == "+":
                self.use_helper("pos")
                return f"__myna_pos({self.gen_expr(expr.operand)})"
            if expr.op == "~":
                return f"(await {self.gen_expr(expr.operand, 85)})"
            if expr.op == "~|":
                return f"~{self.gen_expr(expr.operand, 80)}"
            if expr.op in ("*", "**"):
                return f"...{self.gen_expr(expr.operand, 80)}"
            return f"{expr.op}{self.gen_expr(expr.operand, 80)}"

        if isinstance(expr, ast.BinaryOp):
            if expr.op in ("&&", "||"):
                return self._gen_boolop(expr, parent_prec)
            helper = {
                "+": "add",
                "-": "sub",
                "*": "mul",
                "/": "div",
                "//": "floordiv",
                "%": "mod",
            }.get(expr.op)
            if helper:
                self.use_helper(helper)
                return (
                    f"__myna_{helper}({self.gen_expr(expr.left)}, "
                    f"{self.gen_expr(expr.right)})"
                )
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
                if op in ("==", "!="):
                    self.use_helper("eq")
                    call = f"__myna_eq({l_s}, {r_s})"
                    parts.append(call if op == "==" else f"!{call}")
                elif op in ("===", "!=="):
                    call = f"Object.is({l_s}, {r_s})"
                    parts.append(call if op == "===" else f"!{call}")
                elif op == "<-":
                    self.use_helper("in")
                    parts.append(f"__myna_in({l_s}, {r_s})")
                elif op == "!<-":
                    self.use_helper("in")
                    parts.append(f"!__myna_in({l_s}, {r_s})")
                else:
                    parts.append(f"{l_s} {op} {r_s}")
                cur_left = comp
            s = " && ".join(parts)
            return f"({s})" if parent_prec > 30 else s

        if isinstance(expr, ast.TernaryOp):
            self.use_helper("truthy")
            s = (
                f"__myna_truthy({self.gen_expr(expr.cond, 11)}) ? "
                f"{self.gen_expr(expr.true_expr, 11)} : {self.gen_expr(expr.false_expr, 10)}"
            )
            return f"({s})" if parent_prec > 10 else s

        if isinstance(expr, ast.RangeExpr):
            self.use_helper("range")
            stop_s = self.gen_expr(expr.stop)
            if expr.start is None and expr.step is None:
                return f"__myna_range({stop_s})"
            start_s = self.gen_expr(expr.start) if expr.start is not None else "0"
            if expr.step is not None:
                return f"__myna_range({start_s}, {stop_s}, {self.gen_expr(expr.step)})"
            return f"__myna_range({start_s}, {stop_s})"

        if isinstance(expr, ast.PipeExpr):
            right = expr.right
            rewritten = (
                ast.Call(
                    func=right.func,
                    args=[expr.left] + right.args,
                    keywords=right.keywords,
                    line=expr.line,
                    col=expr.col,
                )
                if isinstance(right, ast.Call)
                else ast.Call(func=right, args=[expr.left], keywords=[], line=expr.line, col=expr.col)
            )
            return self.gen_expr(rewritten, parent_prec)

        if isinstance(expr, ast.Call):
            return self.gen_call(expr)

        if isinstance(expr, ast.Attribute):
            val_s = self.gen_expr(expr.value, 90)
            op = "?." if expr.optional else "."
            return f"{val_s}{op}{expr.attr}"

        if isinstance(expr, ast.Subscript):
            val_s = self.gen_expr(expr.value, 90)
            if isinstance(expr.slice, ast.Slice):
                self.use_helper("slice")
                lo = self.gen_expr(expr.slice.lower) if expr.slice.lower is not None else "undefined"
                hi = self.gen_expr(expr.slice.upper) if expr.slice.upper is not None else "undefined"
                st = self.gen_expr(expr.slice.step) if expr.slice.step is not None else "undefined"
                return f"__myna_slice({val_s}, {lo}, {hi}, {st})"
            self.use_helper("getitem")
            return f"__myna_getitem({val_s}, {self.gen_expr(expr.slice)})"

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
            return f"({self._gen_lvalue(expr.target)} = {self.gen_expr(expr.value)})"

        raise ValueError(f"Unsupported expression node for JS: {expr!r}")

    def _ident_value(self, name: str) -> str:
        if name in PY_EXCEPTIONS:
            self.use_exception(name)
            return name
        if name in UNSUPPORTED_JS_BUILTINS:
            raise TargetError(
                f"builtin '{name}' is not supported by the JavaScript target"
            )
        if name == "p":
            self.use_helper("print")
            return "__myna_print"
        if name.startswith("@"):
            value = BUILTIN_VALUES.get(name)
            if value is None:
                raise TargetError(
                    f"builtin '{name}' is not supported by the JavaScript target"
                )
            helper = {
                "@sum": "sum",
                "@min": "min",
                "@max": "max",
                "@srt": "sort",
                "@zip": "zip",
                "@all": "all",
                "@any": "any",
                "@bool": "truthy",
                "@str": "str",
                "@repr": "str",
            }.get(name)
            if helper:
                self.use_helper(helper)
            return value
        return js_ident(name)

    def _gen_boolop(self, expr: ast.BinaryOp, parent_prec: int) -> str:
        self.use_helper("truthy")
        left = self.gen_expr(expr.left)
        right = self.gen_expr(expr.right)
        if isinstance(expr.left, (ast.Ident, ast.Literal)):
            if expr.op == "||":
                return f"(__myna_truthy({left}) ? {left} : {right})"
            return f"(__myna_truthy({left}) ? {right} : {left})"
        # Bind the left operand once so side effects are not repeated.
        if expr.op == "||":
            body = f"__myna_truthy(__v) ? __v : {right}"
        else:
            body = f"__myna_truthy(__v) ? {right} : __v"
        return f"((__v) => {body})({left})"

    def _js_isinstance(self, subject: str, expr: ast.Expr) -> str:
        if isinstance(expr, ast.Ident):
            if expr.name in ("i", "f", "int", "float"):
                # Python's bool is a subclass of int.
                return f"(typeof {subject} === 'number' || typeof {subject} === 'boolean')"
            if expr.name in ("s", "str"):
                return f"(typeof {subject} === 'string')"
            if expr.name in ("b", "bool"):
                return f"(typeof {subject} === 'boolean')"
            if expr.name in ("B", "bytes"):
                return f"({subject} instanceof Uint8Array)"
            if expr.name in ("A", "Any"):
                return "true"
            if expr.name in ("N", "None"):
                return f"({subject} == null)"
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
            return (
                f"({subject} !== null && typeof {subject} === 'object'"
                f" && !Array.isArray({subject}) && !({subject} instanceof Set)"
                f" && !({subject} instanceof Map))"
            )
        if isinstance(expr, ast.Subscript):
            return self._js_isinstance(subject, expr.value)
        return f"({subject} instanceof {self.gen_expr(expr)})"

    def gen_call(self, call: ast.Call) -> str:
        if isinstance(call.func, ast.Ident):
            fn = call.func.name
            if fn in UNSUPPORTED_JS_BUILTINS:
                raise TargetError(
                    f"builtin '{fn}' is not supported by the JavaScript target"
                )

            if fn == "@srt" and call.keywords:
                self.use_helper("sort")
                arr_s = self.gen_expr(call.args[0]) if call.args else "[]"
                key_s = "undefined"
                reverse_s = "false"
                for k, v in call.keywords:
                    if k == "key":
                        key_s = self.gen_expr(v)
                    elif k == "reverse":
                        reverse_s = self.gen_expr(v)
                    else:
                        raise TargetError(
                            f"unsupported keyword '{k}' for '@srt' on the JavaScript target"
                        )
                return f"__myna_sort({arr_s}, {key_s}, {reverse_s})"

            if fn == "@set" and len(call.args) == 1 and not call.keywords:
                return f"new Set({self.gen_expr(call.args[0])})"

            if fn in self.known_classes or fn in PY_EXCEPTIONS:
                if fn in PY_EXCEPTIONS:
                    self.use_exception(fn)
                args_s = [self.gen_expr(a) for a in call.args]
                return f"new {js_ident(fn)}({', '.join(args_s)})"

        if isinstance(call.func, ast.Attribute) and not call.keywords:
            obj_s = self.gen_expr(call.func.value, 90)
            m_name = call.func.attr
            if m_name == "get" and len(call.args) in (1, 2):
                self.use_helper("get")
                args_s = ", ".join(self.gen_expr(a) for a in call.args)
                return f"__myna_get({obj_s}, {args_s})"
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
            if m_name == "extend" and len(call.args) == 1:
                return f"{obj_s}.push(...{self.gen_expr(call.args[0])})"
            if m_name == "values" and not call.args:
                return f"Object.values({obj_s})"
            if m_name == "keys" and not call.args:
                return f"Object.keys({obj_s})"
            if m_name == "items" and not call.args:
                return f"Object.entries({obj_s})"

        if isinstance(call.func, ast.Ident) and call.func.name == "p":
            self.use_helper("print")
            func_s = "__myna_print"
        else:
            func_s = self.gen_expr(call.func, 90)
            # Builtin aliases expand to arrow functions; a bare `(x) => ...(a)` would
            # parse the call as part of the arrow body.
            if "=>" in func_s:
                func_s = f"({func_s})"
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
        self.use_helper("iter")
        self.use_helper("truthy")
        c = clauses[0]
        iter_s = f"__myna_iter({self.gen_expr(c.iter)})"
        param_s = self._gen_destructure_target(c.target)
        param_s = f"({param_s})"

        for cond in c.conds:
            iter_s = f"{iter_s}.filter({param_s} => (__myna_truthy({self.gen_expr(cond)})))"

        if len(clauses) == 1:
            return f"{iter_s}.map({param_s} => ({self.gen_expr(elt)}))"
        inner = self.gen_comp_chain(elt, clauses[1:])
        return f"{iter_s}.flatMap({param_s} => {inner})"


def compile_to_js(mod: ast.Module) -> str:
    enforce_module_target(mod, "js")
    gen = JSGenerator()
    return gen.generate(expand_target_blocks(mod, "js"))
