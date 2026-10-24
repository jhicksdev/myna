---
name: myna
description: Read, write, and transpile Myna (.myna), an ultra-dense symbolic AI-native programming language that transpiles 1:1 to and from Python. Activate whenever working with .myna files, compressing Python code for token efficiency, or writing Myna code.
---

# Myna Language Skill for Coding Agents

**Myna** is an indentation-free, brace-delimited (`{}`), symbol-dense language that maps 1:1 to Python 3.12+ (and JavaScript). Statements end at a newline `\n`, semicolon `;`, or before `}`.

## 1. CLI Commands
```bash
python3 -m myna compile input.myna -o output.py   # Compile Myna -> Python
python3 -m myna compile input.myna -t js          # Compile Myna -> JavaScript (ES2024+)
python3 -m myna decompile input.py -o output.myna # Compress Python -> Myna (-m for ultra-compact)
python3 -m myna run script.myna                   # Execute .myna via Python
python3 -m myna run -t js script.myna             # Execute .myna via Node.js
python3 -m myna targets script.myna               # Report declared/inferred target support
python3 -m myna stats file.py --show              # Measure token & character savings
```

## 2. Complete Symbol Rosetta Stone

### Literals, Types & Constants
- `T` = `True`, `F` = `False`, `N` = `None`, `_` (standalone in `{_}`) = `pass`
- `` `hi {x:.2f}` `` = `f"hi {x:.2f}"` (escapes: `` \` ``, `\\`, `\n`, `\t`, `\r`), `_"raw"` = `r"raw"`, `0b"bytes"` = `b"bytes"` (literal text is UTF-8; `\xNN`/octal escapes are raw bytes)
- **Types:** `i`=`int`, `f`=`float`, `s`=`str`, `b`=`bool`, `B`=`bytes`, `A`=`Any`, `N`=`None`
- **Compound Types:** `T?`=`T | None`, `[T]`=`list[T]`, `{K:V}`=`dict[K, V]`, `{T}`=`set[T]`, `(T1,T2)`=`tuple[T1, T2]`

### Imports, Scope & Bindings
- `<os, sys` → `import os, sys`
- `<numpy>np` → `import numpy as np`
- `<pathlib:{Path, PurePath>PP}` → `from pathlib import Path, PurePath as PP`
- `<.utils:{helper}` → `from .utils import helper`
- `@=x, y` → `global x, y` | `^=x, y` → `nonlocal x, y` | `~x[k]` → `del x[k]`
- `$=Alias = [i]` → `type Alias = list[int]`
- `@target(py)` → module is Python-only; `@target(py, js)` is portable (default: both). Must precede all code.
- `@target(py) { <asyncio; ... }` / `@target(js) { ... }` → module-level compile-time block; only the matching target's statements/imports are emitted.

### Functions, Classes & Decorators
- `@f(a:i, b=1)->i { ^a+b }` → `def f(a: int, b=1) -> int: return a + b`
- `~@f(a) { ^~g(a) }` → `async def f(a): return await g(a)`
- `*@gen(n) { %i<-..n { ^*i } }` → generator (`^*` = `yield`, `^**` = `yield from`)
- `x => x+1` or `(a,b) => a+b` → `lambda`
- `$C < Base { @init(x){ .x=x; ..init() } }` → `class C(Base): def __init__(self, x): self.x = x; super().__init__()`
- `$$User(id:i, name:s="anon") { ... }` → `@dataclass class User:` with typed fields
- **Class Methods (implicit `self`/`cls`, `.attr` = `self.attr`, `..m()` = `super().m()`):**
  - `@/f(a){...}` → `@staticmethod` | `@$f(a){...}` → `@classmethod`
  - `@?prop{^._x}` → `@property` | `@=prop(v){._x=v}` → `@prop.setter`
- `#[dec1, dec2(arg)]` → `@dec1` / `@dec2(arg)`
- `+@f(...)` or `+$C` → exports symbol to `__all__`
- `@main { ... }` → `if __name__ == "__main__": ...`

### Control Flow, Loops & Comprehensions
- `? c1 { ... } :? c2 { ... } : { ... }` → `if c1: ... elif c2: ... else: ...`
- `?? val { 0 => {^"zero"}; x ? x>0 => {^"pos"}; _ => {^"neg"} }` → `match val: case ...`
- `% x <- it { ... }` → `for x in it:` (`%~` = `async for`, `%:` = loop `else`)
- `%? cond { ... }` → `while cond:`
- `^val` = `return val` | `^!` = `break` | `^>` = `continue`
- `[x*2 | x <- it ? x>0]` → `[x * 2 for x in it if x > 0]`
- `[(x,y) | x <- a % y <- b]` → nested comprehension (`for x in a for y in b`)
- `{k:v | k,v <- it}` (dict comp) | `{x | x <- it}` (set comp) | `(x | x <- it)` (gen exp)

### Error Handling & Context Managers
- `!{ ... } !!e:ValueError { ... } !!e { ... } !? { ... } !: { ... }`
  → `try: ... except ValueError as e: ... except Exception as e: ... else: ... finally: ...`
- `!^ValueError("bad")` → `raise ValueError("bad")` (`!^e <- cause` = `raise e from cause`)
- `!? cond, "msg"` → `assert cond, "msg"`
- `!& f = open(p) { ... }` → `with open(p) as f:` (`!~&` = `async with`)

### Operators, Dict Shorthands & Built-in Aliases
- **Dict Shorthands:**
  - Unquoted keys: `{error: "msg", code: 400}` → `{"error": "msg", "code": 400}` (`{[k]: v}` for dynamic key `k`)
  - Self-field punning: `{.id, .title, .done}` → `{"id": self.id, "title": self.title, "done": self.done}`
  - Variable punning: `{=name, count}` → `{"name": name, "count": count}`
  - Trailing dict argument in calls: `send(200, status: "ok", id: 1)` → `send(200, {"status": "ok", "id": 1})`
  - Keyword argument punning: `Request(url, =data, =headers)` → `Request(url, data=data, headers=headers)`
  - String-key lookup & `.get()`: `d$todos` → `d["todos"]` | `d$?title ?? "default"` → `d.get("title") or "default"`
- **Braceless `=>` Single-Statement Bodies:**
  - Functions/methods: `@to_dict->{s:A} => {.id, .title}` (implicitly returns expression)
  - Control/context blocks: `? x <= 0 => ^ {}` | `!!:ValueError => ^ "bad"` | `!& f=open(p) => ^ f.read()`
- **Logic & Comparison:** `&&` (`and`), `||` (`or`), `!x` (`not x`), `===` (`is`), `!==` (`is not`), `<-` (`in`), `!<-` (`not in`), `x :? i` (`isinstance(x, int)`; compound types check the origin — `x :? [i]` → `isinstance(x, list)`, `x :? {s:A}` → `isinstance(x, dict)`, and `x :? (i, s)` is a union)
- **Special Ops:** `#x` (`len(x)`), `~x` (`await x`), `~|x` (`~x` bitwise NOT), `a ?? b` (`a if a is not None else b`), `c ? a : b` (`a if c else b`), `x |> f(a)` (`f(x, a)`), `..n` (`range(n)`), `a..b..s` (`range(a, b, s)`)
- **Built-in Call Aliases:** `p`=`print`, `@j`=`json.loads`, `@J`=`json.dumps`, `@u8(x)`=`x.encode('utf-8')`, `@u8d(x)`=`x.decode('utf-8')`, `@enum`=`enumerate`, `@zip`=`zip`, `@map`=`map`, `@flt`=`filter`, `@srt`=`sorted`, `@rev`=`reversed`, `@sum`=`sum`, `@min`=`min`, `@max`=`max`, `@abs`=`abs`, `@all`=`all`, `@any`=`any`, `@str`=`str`, `@int`=`int`, `@float`=`float`, `@bool`=`bool`, `@list`=`list`, `@dict`=`dict`, `@set`=`set`, `@tuple`=`tuple`, `@rnd`=`round`, `@open`=`open`

## 3. Canonical Example
```myna
<asyncio
$$Task(id:i,title:s,done:b=F){
  @summary->s{^`[{.done?"x":" "}] #{.id}: {.title}`}
}
~@process(tasks:[Task])->[s]{
  !{
    ~asyncio.sleep(0.01)
    ^[t.summary()|t<-tasks?!t.done]
  }!!e{p(`Failed: {e}`);^[]}
}
@main{
  items=[Task(1,"Spec",T),Task(2,"Transpiler")]
  %line<-asyncio.run(process(items)){p(line)}
}
```
