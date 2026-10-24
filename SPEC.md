# Myna Language Specification (v0.1)

**Myna** is an ultra-dense, symbol-based, AI-native programming language designed to minimize LLM token consumption while mapping 1-to-1 onto the semantics of **Python 3.12+** and **JavaScript (ES2024+)**.

## 1. Core Design Principles
1. **Tokenizer-Aware ASCII Sigils:** Uses standard printable ASCII characters and 2-character digraphs (`~@`, `!!`, `<-`, `|>`, `:?`, `??`, `..`) that BPE tokenizers encode as 1–2 tokens. Never uses esoteric Unicode math symbols that split into multi-byte tokens.
2. **Statement-Prefix vs. Infix Disambiguation:** Punctuation at the start of a statement acts as a structural keyword (`?` = `if`, `%` = `for/while`, `^` = `return`, `!` = `try/raise/assert`, `<` = `import`), while inside an expression it acts as a standard operator.
3. **Brace-Delimited & Whitespace-Agnostic:** Blocks are enclosed in `{ ... }`. Statements end at a newline `\n`, semicolon `;`, or before `}`. Zero indentation tokens are required.
4. **Cross-Target AST:** Every Myna construct maps deterministically to both Python and JavaScript.

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
| `` `hi {x}` `` | `f"hi {x}"` | `` `hi ${x}` `` | Interpolated string (supports format spec `{x:.2f}`; escapes `` \` ``, `\\`, `\n`, `\t`, `\r`) |
| `_"raw"` | `r"raw"` | `String.raw\`raw\`` | Raw string literal |
| `0b"bytes"` | `b"bytes"` | `new Uint8Array([...])` | Byte literal (literal text is UTF-8; `\xNN`/octal escapes produce raw byte values) |
| `# comment` | `# comment` | `// comment` | Single-line comment (`#` followed by space, `#`, or newline; note `//` is floor division) |

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

---

## 3. Declarations, Scope & Modules

| Myna | Python | JavaScript |
| :--- | :--- | :--- |
| `x = 1` | `x = 1` | `let x = 1;` |
| `x:i = 1` | `x: int = 1` | `let x = 1;` |
| `x := 1` | `x = 1` (or `:=` inside expr) | `const x = 1;` |
| `@= x, y` | `global x, y` | *(global scope)* |
| `^= x, y` | `nonlocal x, y` | *(closure scope)* |
| `~x` *(statement)* | `del x` | `delete x;` |
| `$= Alias = Type` | `type Alias = Type` | `type Alias = Type;` |
| `<os, sys` | `import os, sys` | `import * as os from 'os'; ...` |
| `<numpy>np` | `import numpy as np` | `import * as np from 'numpy';` |
| `<pathlib:{Path, PurePath>PP}` | `from pathlib import Path, PurePath as PP` | `import { Path, PurePath as PP } from 'pathlib';` |
| `<.utils:{helper}` | `from .utils import helper` | `import { helper } from './utils.js';` |
| `@target(py)` / `@target(py, js)` | module target contract (default: both) | same |
| `@target(py) { ... }` | compile-time block, emitted only for Python | same (module-level only, imports become top-level) |
| `+@f(...)` / `+$C` | `def f(...)` + adds to `__all__` | `export function f(...)` / `export class C` |

`@target(...)` with no block must be the first non-docstring statement and declares which targets the file supports; compiling for another target raises `TargetError`. With a block it selects the statements/imports emitted for that target. Target blocks are module-level only in v0.3.

Relative imports resolve against the entry file's directory when run with `myna run`: `<.util:{f}` loads `util.myna` beside the entry file, and `<.pkg.mod:{f}` loads `pkg/mod.myna` (a directory may provide `pkg/__init__.myna` or act as a namespace package). Absolute imports keep their Python meaning. `myna compile` remains per-file and does not bundle imported modules; `myna bundle` embeds the relative-import graph into one standalone Python file.

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

---

## 8. Operators & Built-in Shorthands

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
