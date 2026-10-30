# Myna Language Specification (v0.6)

**Myna** is an ultra-dense, symbol-based, AI-native programming language designed to minimize LLM token consumption while mapping 1-to-1 onto the semantics of **Python 3.12+** (normative) and a portable subset of **JavaScript (ES2024+)** and **TypeScript**.

## 1. Core Design Principles
1. **Tokenizer-Aware ASCII Sigils:** Uses standard printable ASCII characters and 2-character digraphs (`~@`, `!!`, `<-`, `|>`, `:?`, `??`, `..`) that BPE tokenizers encode as 1–2 tokens. Never uses esoteric Unicode math symbols that split into multi-byte tokens.
2. **Statement-Prefix vs. Infix Disambiguation:** Punctuation at the start of a statement acts as a structural keyword (`?` = `if`, `%` = `for/while`, `^` = `return`, `!` = `try/raise/assert`, `<` = `import`), while inside an expression it acts as a standard operator.
3. **Brace-Delimited & Whitespace-Agnostic:** Blocks are enclosed in `{ ... }`. Statements end at a newline `\n`, semicolon `;`, or before `}`. Zero indentation tokens are required.
4. **Cross-Target AST:** Every Myna construct maps deterministically to Python; the JavaScript and TypeScript targets map the portable core and reject the rest explicitly.

### Target semantics

Python 3.12 is the normative semantics. The JavaScript target **emulates** those
semantics with inlined helpers; a construct that cannot be emulated exactly is rejected
for `-t js` with `TargetError` rather than approximated. See `DECISIONS.md` D-001 and
D-002 for the target contract and the JavaScript portable-core scope.

TypeScript is a **typed projection of the JavaScript target** (`DECISIONS.md` D-006).
`-t ts` emits the same runtime helpers and portable core, uses the same `@target(py, js)`
contract and `@target(js)` blocks, and raises the same `TargetError`s. Type annotations
are erased and never add runtime checks; unannotated parameters are emitted as explicit
`any`. A module whose annotations are truthful type-checks under `tsc --strict`.
`myna run -t ts` is not supported; `-t js` executes the same program.

---

## 2. Lexical Grammar & Literals

| Myna | Python | JavaScript | Description |
| :--- | :--- | :--- | :--- |
| `T` / `F` | `True` / `False` | `true` / `false` | Boolean literals |
| `N` | `None` | `null` | Null / None literal |
| `U` | `None` | `undefined` | Undefined literal |
| `_` | `pass` / `_` | `/*noop*/` / `_` | No-op statement when standalone in block, or wildcard identifier |
| `42`, `3.14`, `0xff` | `42`, `3.14`, `0xff` | `42`, `3.14`, `0xff` | Numeric literals |
| `"str"`, `'str'` | `"str"`, `'str'` | `"str"`, `'str'` | String literals |
| `` `hi {x}` `` | `f"hi {x}"` | `` `hi ${x}` `` | Interpolated string (supports format spec `{x:.2f}`; escapes: every escape below plus `` \` ``) |
| `_"raw"` | `r"raw"` | `String.raw\`raw\`` | Raw string literal |
| `0b"bytes"` | `b"bytes"` | `new Uint8Array([...])` | Byte literal (literal text is UTF-8; `\xNN`/octal escapes produce raw byte values) |
| `# comment` | `# comment` | `// comment` | Single-line comment (`#` followed by space, `#`, or newline; note `//` is floor division) |

`T`, `F`, `N`, and `U` **cannot be used as binding names** — a class, function, parameter,
variable, loop target, import alias, or `except` name spelled with one of those letters is a
parse error (`DECISIONS.md` D-007). They parse as literals at every use site, so a binding
with one of those names would silently resolve to `True`/`False`/`None` instead of the
value it holds.

Strings decode Python's escape set: `\a \b \f \n \r \t \v \\ \' \"`, octal `\ooo`,
`\xNN`, `\uNNNN`, `\UNNNNNNNN`, `\N{NAME}`, and a backslash-newline line continuation.
An unknown or malformed escape is a lexer error instead of a silently kept backslash; use
a raw string (`_"..."`) to keep the backslash. Byte literals accept `\xNN` and octal
escapes as raw byte values, and reject `\u`, `\U`, and `\N`.

### Built-in Type Shorthands (in Type Annotations)
| Myna | Python | TypeScript / JS |
| :--- | :--- | :--- |
| `i` | `int` | `number` |
| `f` | `float` | `number` |
| `s` | `str` | `string` |
| `b` | `bool` | `boolean` |
| `B` | `bytes` | `Uint8Array` |
| `A` | `Any` | `any` |
| `N` | `None` | `null` |
| `T?` | `Optional[T]` (`T \| None`) | `T \| null` |
| `[T]` | `list[T]` | `T[]` |
| `{K:V}` | `dict[K, V]` | `Record<K, V>` |
| `{T}` | `set[T]` | `Set<T>` |
| `(T1, T2)` | `tuple[T1, T2]` | `[T1, T2]` |

`T?` appends `| null`. A list of a union or function type is parenthesized
(`(A | B)[]`, `((x: A) => B)[]`). A dictionary whose key type is not a valid `Record` key
(`string`, `number`, `symbol`, or a union of those) is emitted as `Record<string, V>`,
matching JavaScript's string-coerced keys.

The TypeScript target also translates Python `typing`/`collections.abc` annotations:
`Callable[[T], R]` (or `Callable[(T1, T2), R]`) becomes `(arg0: T, ...) => R`,
`Mapping[K, V]` becomes `Record<K, V>`, `Sequence[T]` becomes `T[]`, `Iterator[T]`
becomes `Iterable<T>`, `Awaitable[T]` becomes `Promise<T>`,
`Generator[Y, S, R]` becomes `Generator<Y, R, S>`, `Type[T]` becomes
`new (...args: any[]) => T`, and `Self` resolves to the enclosing class. `ClassVar[T]`,
`Final[T]`, `Annotated[T, ...]`, `Required[T]`, and `NotRequired[T]` erase to `T`; an
unknown `typing.*` name becomes `any`. Myna has no generic declarations, so type
arguments on a user class or alias are erased (`Box[int]` becomes `Box`). JavaScript
strips all annotations; TypeScript emits them.

---

## 3. Declarations, Scope & Modules

| Myna | Python | JavaScript |
| :--- | :--- | :--- |
| `x = 1` | `x = 1` | `let x = 1;` |
| `x:i = 1` | `x: int = 1` | `let x = 1;` (TS: `let x: number = 1;`) |
| `x := 1` | `x = 1` (or `:=` inside expr) | `const x = 1;` |
| `@= x, y` | `global x, y` | *(global scope)* |
| `^= x, y` | `nonlocal x, y` | *(closure scope)* |
| `~x` *(statement)* | `del x` | `delete x;` |
| `$= Alias = Type` | `type Alias = Type` | JS: type-only (stripped); TS: `export type Alias = Type;` |
| `<os, sys` | `import os, sys` | `import * as os from 'os'; ...` |
| `<numpy>np` | `import numpy as np` | `import * as np from 'numpy';` |
| `<pathlib:{Path, PurePath>PP}` | `from pathlib import Path, PurePath as PP` | `import { Path, PurePath as PP } from 'pathlib';` |
| `<.utils:{helper}` | `from .utils import helper` | `import { helper } from './utils.js';` |
| `@target(py)` / `@target(py, js)` | module target contract (default: `py`) | same (`js` also permits `-t ts`; there is no `@target(ts)`) |
| `@target(py) { ... }` | compile-time block, emitted only for Python | same (module-level only, imports become top-level; `@target(js)` also applies to `-t ts`) |
| `+@f(...)` / `+$C` | `def f(...)` + adds to `__all__` | `export function f(...)` / `export class C` |

`@target(...)` with no block must be the first non-docstring statement and declares which targets the file supports; compiling for another target raises `TargetError`. With a block it selects the statements/imports emitted for that target. Target blocks are module-level only.

In language 0.6 a module with no declaration is treated as `@target(py)`. Portability is
opt-in: add `@target(py, js)` to a module that must compile for JavaScript or TypeScript
(`DECISIONS.md` D-003).

Relative imports resolve against the importing module's directory: `<.util:{f}` loads `util.myna` beside the importing module, `<.pkg.mod:{f}` loads `pkg/mod.myna` (a directory may provide `pkg/__init__.myna` or act as a namespace package), and `<.util` without a name list binds the imported module object. A dotted module-object import keeps its submodule meaning: `<.pkg.mod` is `from .pkg import mod`, so `mod.v()` works. A program's entry file instead resolves against its own directory when run with `myna run`, or against `--module-root DIR` / `MYNA_MODULE_ROOT` when set, which lets an entry in `tests/` reach a sibling `src/`; a declared module root is also the ceiling, so `<..src.util` from an entry of any depth resolves against that root. Absolute imports keep their Python meaning. `myna compile` remains per-file and does not bundle imported modules; `myna bundle` embeds the relative-import graph into one standalone Python file, or with `--zipapp` into a runnable `.pyz` archive.

For the JavaScript target a relative import becomes a relative ES module specifier
(`<.util:{slug}` → `import { slug } from "./util.js"`, with the extension following
`-o`'s suffix), and every top-level binding is exported so another module can import it
the way Python allows. `myna run -t js` compiles the reachable graph into `.mjs` files in
a temporary directory and runs it with Node. `myna_to_js(source)` has no filesystem
context, so it requires `source_path=` (or a `myna compile` of the file) when relative
imports are present.

The TypeScript target uses the same specifiers and module graph, including `.mjs` for
`.mts` output. A relative import of a `$=` type alias is emitted as `import type`, and a
type alias is exported with `export type`; using a type alias as a value is a
`TargetError` for `-t ts`. `myna_to_ts(source)` likewise requires `source_path=` when
relative imports are present. `myna run -t ts` is not supported; use `-t js` to execute
the same program.

---

## 4. Functions, Classes & Object-Oriented Constructs

| Myna | Python | JavaScript |
| :--- | :--- | :--- |
| `@f(a:i, b=1)->i { ... }` | `def f(a: int, b=1) -> int:` | `function f(a, b=1) { ... }` |
| `~@f(a) { ... }` | `async def f(a):` | `async function f(a) { ... }` |
| `*@f(a) { ... }` | `def f(a):` (with `yield`) | `function* f(a) { ... }` |
| `~*@f(a) { ... }` | `async def f(a):` (async gen) | `async function* f(a) { ... }` |
| `@/f(a) { ... }` | `@staticmethod\ndef f(a):` | `static f(a) { ... }` |
| `@$f(a) { ... }` | `@classmethod\ndef f(cls, a):` | `static f(a) { ... }` |
| `@?prop { ^._x }` | `@property\ndef prop(self): return self._x` | `get prop() { return this._x; }` |
| `@=prop(v) { ._x = v }` | `@prop.setter\ndef prop(self, v): self._x = v` | `set prop(v) { this._x = v; }` |
| `@init(a, b) { .a=a; .b=b }` | `def __init__(self, a, b): ...` | `constructor(a, b) { ... }` |
| `x => x + 1` or `(a, b) => a + b` | `lambda x: x + 1` | `(x) => x + 1` |
| `$C { ... }` | `class C:` | `class C { ... }` |
| `$C < B1, B2 { ... }` | `class C(B1, B2):` | `class C extends B1 { ... }` |
| `$$C(id:i, name:s="a") { ... }` | `@dataclass\nclass C:\n    id: int\n    name: str = "a"` | Class with field constructor |
| `.x` / `.m()` | `self.x` / `self.m()` | `this.x` / `this.m()` |
| `..init(a)` / `..m()` | `super().__init__(a)` / `super().m()` | `super(a)` / `super.m()` |
| `#[dec1, dec2(arg)]` | `@dec1\n@dec2(arg)` | `@dec1\n@dec2(arg)` |

*Note: Inside any class method (except `@/f` static methods and `@$f` class methods), `self` is automatically injected in Python (or `cls` for `@$f`), and leading-dot `.attr` expands to `self.attr` (or `cls.attr`).*

The JavaScript and TypeScript targets support single inheritance only and reject nested
classes. A `$$` dataclass subclass may inherit a dataclass defined in the same module;
its generated constructor takes the base's fields and forwards them to `super(...)`.
A class with an explicit `@init` must call the base constructor with `..init(...)` when
it has a base.

A dataclass field may default to a list, dict, or set literal (`$$D(xs:[s]=[])`): Python
emits `field(default_factory=...)` and the JavaScript/TypeScript targets emit a constructor
default, so every instance gets its own value rather than a shared mutable object.

---

## 5. Control Flow & Pattern Matching

| Myna | Python | JavaScript |
| :--- | :--- | :--- |
| `? cond { ... }` | `if cond:` | `if (cond) { ... }` |
| `:? cond { ... }` | `elif cond:` | `else if (cond) { ... }` |
| `: { ... }` | `else:` | `else { ... }` |
| `?? subject { pat => { ... }; _ => { ... } }` | `match subject:\n    case pat: ...\n    case _: ...` | `switch (subject) { ... }` |
| `?? subject { pat ? guard => expr }` | `case pat if guard: ...` | Switch with guard |
| `^expr` / `^` | `return expr` / `return` | `return expr;` / `return;` |
| `^*expr` | `yield expr` | `yield expr;` |
| `^**expr` | `yield from expr` | `yield* expr;` |
| `^!` | `break` | `break;` |
| `^>` | `continue` | `continue;` |

---

## 6. Loops & Comprehensions

| Myna | Python | JavaScript |
| :--- | :--- | :--- |
| `% x <- iter { ... }` | `for x in iter:` | `for (const x of iter) { ... }` |
| `% i, x <- iter { ... }` | `for i, x in iter:` | `for (const [i, x] of iter) { ... }` |
| `%~ x <- iter { ... }` | `async for x in iter:` | `for await (const x of iter) { ... }` |
| `%? cond { ... }` | `while cond:` | `while (cond) { ... }` |
| `%: { ... }` | `else:` *(loop else)* | *(flag-emulated loop else)* |
| `[expr \| x <- it]` | `[expr for x in it]` | `it.map(x => expr)` |
| `[expr \| x <- it ? cond]` | `[expr for x in it if cond]` | `it.filter(x => cond).map(x => expr)` |
| `[expr \| x <- it1 % y <- it2]` | `[expr for x in it1 for y in it2]` | `it1.flatMap(...)` |
| `{k: v \| x <- it ? cond}` | `{k: v for x in it if cond}` | `Object.fromEntries(...)` |
| `{expr \| x <- it ? cond}` | `{expr for x in it if cond}` | `new Set(...)` |
| `(expr \| x <- it ? cond)` | `(expr for x in it if cond)` | Generator comprehension |

---

## 7. Error Handling & Resource Management

| Myna | Python | JavaScript |
| :--- | :--- | :--- |
| `!{ ... }` | `try:` | `try { ... }` |
| `!! e:Err { ... }` | `except Err as e:` | `catch (e) { ... }` |
| `!! :Err { ... }` | `except Err:` | `catch (_e) { ... }` |
| `!! e { ... }` | `except Exception as e:` | `catch (e) { ... }` |
| `!! { ... }` | `except:` | `catch { ... }` |
| `!? { ... }` *(after `!!`)* | `else:` *(try-else)* | *(try-else emulation)* |
| `!: { ... }` | `finally:` | `finally { ... }` |
| `!^ Err("msg")` / `!^` | `raise Err("msg")` / `raise` | `throw new Err("msg");` |
| `!? cond, "msg"` *(statement)* | `assert cond, "msg"` | `console.assert(cond, "msg");` |
| `!& f = open(p) { ... }` | `with open(p) as f:` | `using f = open(p);` |
| `!& open(p) { ... }` | `with open(p):` |Context block |
| `!~& f = aopen(p) { ... }` | `async with aopen(p) as f:` | `await using f = aopen(p);` |

`try` requires at least one `!!` handler or a `!:` finally block. A try-else (`!?`) is
only valid when the try has at least one handler.

---

## 8. Operators & Built-in Shorthands

### Dict Literals, Key Access & Call-Site Dicts
| Myna | Python | Notes |
| :--- | :--- | :--- |
| `{error: "msg", code: 400}` | `{"error": "msg", "code": 400}` | A bare identifier key is a string key |
| `{"Content-Type": "json"}` | `{"Content-Type": "json"}` | Quote a key containing `-` or `/`; `{Content-Type: …}` is a parse error, not a subtraction |
| `{[k]: v}` | `{k: v}` | Computed key |
| `{**base, a: 1}` | `{**base, "a": 1}` | Spread |
| `{=name}` / `{.attr}` | `{"name": name}` / `{"attr": self.attr}` | Variable / self-field punning |
| `d$key` / `d$?key` | `d["key"]` / `d.get("key")` | **Literal** key only; use `d[k]` for a computed key |
| `f(a, k: v)` | `f(a, {"k": v})` | A trailing `k: v` argument is a dict literal |
| `f(a, k=v)` | `f(a, k=v)` | Keyword argument |


### Prefix Operators (in Expressions)
| Myna | Python | JavaScript |
| :--- | :--- | :--- |
| `!x` | `not x` | `!x` |
| `~x` | `await x` | `await x` |
| `~\|x` | `~x` *(bitwise NOT)* | `~x` |
| `#x` | `len(x)` | `x.length` |
| `-x`, `+x` | `-x`, `+x` | `-x`, `+x` |
| `*x`, `**x` | `*x`, `**x` | `...x` |

### Infix & Ternary Operators
| Myna | Python | JavaScript |
| :--- | :--- | :--- |
| `&&` | `and` | `&&` |
| `\|\|` | `or` | `\|\|` |
| `===` / `!==` | `is` / `is not` | `===` / `!==` |
| `<-` / `!<-` *(in expr)* | `in` / `not in` | `.includes()` / `in` |
| `:?` *(in expr: `x :? T`)* | `isinstance(x, T)` | `x instanceof T` |
| `c ? a : b` | `a if c else b` | `c ? a : b` |
| `a ?? b` | `a if a is not None else b` | `a ?? b` |
| `x \|> f` / `x \|> f(a)` | `f(x)` / `f(x, a)` | `f(x)` / `f(x, a)` |
| `a..b` / `a..b..s` | `range(a, b)` / `range(a, b, s)` | Range iterator |
| `..b` | `range(b)` | Range iterator `0..b` |

*Runtime type checks with `:?` accept the type shorthands plus compound types. Compound
types check their runtime origin: `[T]` → `list`/`Array.isArray`, `{K:V}` →
`dict`/plain object, `{T}` → `set`/`Set`, and `Name[T]` → `Name`. A parenthesized list of
types is a **union** — `x :? (i, s)` is `isinstance(x, (int, str))`, not a tuple type.*

### Built-in Call Shorthands
| Myna | Python | JavaScript |
| :--- | :--- | :--- |
| `p(...)` | `print(...)` | `console.log(...)` |
| `@enum(x)` | `enumerate(x)` | `x.entries()` |
| `@zip(a, b)` | `zip(a, b)` | `zip(a, b)` |
| `@map(f, x)` | `map(f, x)` | `x.map(f)` |
| `@flt(f, x)` | `filter(f, x)` | `x.filter(f)` |
| `@ srt(x)` -> `@srt(x)` | `sorted(x)` | `[...x].sort()` |
| `@rev(x)` | `reversed(x)` | `[...x].reverse()` |
| `@sum(x)` / `@min(x)` / `@max(x)` | `sum(x)` / `min(x)` / `max(x)` | Array reduction |
| `@str(x)` / `@int(x)` / `@flt_n(x)` | `str(x)` / `int(x)` / `float(x)` | `String(x)` / `Number(x)` |
| `@ main { ... }` | `if __name__ == "__main__": ...` | Entrypoint check |

`@name` is accepted in expression position only for the aliases above (plus `@u8`/`@u8d`);
any other `@name` inside an expression is a parse error, because `@` also introduces
decorators and the `@main` block.
