# Myna (`myna-lang`)

[![PyPI](https://img.shields.io/pypi/v/myna-lang?style=flat-square&logo=pypi&logoColor=white)](https://pypi.org/project/myna-lang/)
[![PyPI downloads](https://img.shields.io/pypi/dm/myna-lang?style=flat-square&label=downloads)](https://pypi.org/project/myna-lang/)
[![Python versions](https://img.shields.io/pypi/pyversions/myna-lang?style=flat-square&logo=python&logoColor=white)](https://pypi.org/project/myna-lang/)
[![License: MIT](https://img.shields.io/github/license/jhicksdev/myna?style=flat-square&color=yellow)](https://github.com/jhicksdev/myna/blob/main/LICENSE)

**Myna** is an ultra-dense, symbol-based, AI-native programming language designed to cut LLM token and character usage by **~50%** while transpiling 1:1 to **Python 3.12+** and to a bounded **JavaScript (ES2024+)** target—and decompiling existing Python code back into Myna.

---

## Why Myna?

Coding agents spend thousands of context and output tokens on repetitive syntactic boilerplate (`def __init__(self, ...):`, `self.`, `Optional[...]`, `try ... except Exception as e:`, quoted JSON keys, and 4-space indentation blocks).

Myna replaces verbose multi-token boilerplate with **tokenizer-friendly ASCII sigils and digraphs** (`$$`, `@`, `~@`, `=>`, `??`, `!?`, `!&`, `$`, `$?`) and brace-delimited blocks (`{}`):
- **~46%–52% fewer LLM tokens** and **~48%–58% fewer characters** than equivalent Python (compact and ultra-compact modes).
- **Zero indentation fragility:** Blocks use `{ ... }` or `=>`, making partial diffs and single-line generation rock-solid for AI agents.
- **Bi-directional (`Python <-> Myna`) & Multi-Target (`Myna -> Python / JS`):** Compress existing Python codebases into `.myna` to fit twice as much code into an agent's context window, or let agents write `.myna` and transpile to clean Python or JavaScript.
- **Agent-Ready:** Ships with a compact Rosetta Stone skill (`skills/myna/SKILL.md`) that teaches any coding agent to read and write idiomatic Myna in one shot.

---

## Side-by-Side Comparison

### Python (21 lines, 611 chars)
```python
from dataclasses import dataclass
import asyncio

@dataclass
class Task:
    id: int
    title: str
    priority: int = 1
    done: bool = False

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "title": self.title, "done": self.done}

async def pending(tasks: list[Task], min_p: int = 1) -> list[dict[str, object]]:
    try:
        await asyncio.sleep(0.01)
        items = [t for t in tasks if not t.done and t.priority >= min_p]
        return [t.to_dict() for t in sorted(items, key=lambda t: -t.priority)]
    except Exception as e:
        print(f"Error: {e}")
        return []
```

### Myna (11 lines, 299 chars — 51% smaller)
```myna
<asyncio
$$Task(id:i,title:s,priority:i=1,done:b=F){
  @to_dict->{s:A}=>{.id,.title,.done}
}
~@pending(tasks:[Task],min_p:i=1)->[{s:A}]{
  !{
    ~asyncio.sleep(0.01)
    items=[t|t<-tasks?!t.done&&t.priority>=min_p]
    ^[t.to_dict()|t<-@srt(items,key=t=>-t.priority)]
  }!!e{p(`Error: {e}`);^[]}
}
```

---

## Quickstart

The CLI requires **Python 3.11+** and has **zero external dependencies**. Generated Python targets **3.12+** when the source declares a type alias (`$=` emits `type X = ...`); other output runs on 3.11+.

```bash
# Install from PyPI
pip install myna-lang          # or: uv tool install myna-lang / pipx install myna-lang

# Install for local development (from a checkout)
pip install -e .

# Show the package and language versions
myna --version

# Create and run a script
printf 'p(`hello from {1+1}`)\n' > hello.myna
myna run hello.myna

# The remaining examples are in a checkout of the repository.
# Run a Myna script directly (via Python)
python3 -m myna run examples/demo.myna

# Run a portable Myna script via Node.js (JavaScript target)
python3 -m myna run -t js examples/cross_target.myna

# Compile Myna -> Python (.py)
python3 -m myna compile examples/rest_api.myna -o rest_api.py

# Compile Myna -> JavaScript (.js)
python3 -m myna compile -t js examples/cross_target.myna -o cross_target.js

# Bundle a multi-file program into one standalone Python file
python3 -m myna bundle src/main.myna -o app.py

# ...or into a runnable zipapp (stdlib-only, executable)
python3 -m myna bundle src/main.myna --zipapp -o app.pyz

# Compress existing Python -> Myna (.myna)
python3 -m myna decompile script.py -o script.myna

# Ultra-compact decompilation (with local variable minification)
python3 -m myna decompile -m script.py -o script.min.myna

# Compare token & character efficiency
python3 -m myna stats examples/books_api.myna

# Report declared/inferred Python & JavaScript support
python3 -m myna targets examples/demo.myna
```

### Multi-file programs

`myna run` gives relative imports a package context, so a program can be split into
sibling `.myna` files:

```myna
# main.myna
<.util:{slug}
p(slug("Hello World"))
```

```myna
# util.myna
@slug(text:s)->s { ^ text.lower().replace(" ", "-") }
```

- `<.util:{slug}` → `util.myna` beside the entry file.
- `<.pkg.helper:{parse}` → `pkg/helper.myna`; `pkg` may have an `__init__.myna` or be a
  plain directory (namespace package).
- Absolute imports (`<json`, `<mypkg>alias`) keep their normal Python meaning.
- Imported files are compiled on first import and cached by Python's import system.
- `myna bundle src/main.myna -o app.py` embeds the whole relative-import graph in one
  standalone Python file. It runs with a plain `python3` and does not need `myna`
  installed; absolute imports still come from the environment.
- `myna bundle src/main.myna --zipapp -o app.pyz` writes a runnable, executable zipapp
  containing real module files (`python3 app.pyz`). It is reproducible: rebuilding the
  same sources produces identical bytes. Without `-o`, the archive lands next to the
  entry file as `<name>.pyz`.
- `myna compile` still compiles one file at a time. If you use relative imports, the
  emitted `.py` files must be placed in a matching Python package.
- `myna run -t js` is single-file; relative imports are a compile error for the
  JavaScript target, and multi-file resolution and bundling are Python-target only.

### JavaScript target

`myna compile -t js` and `myna run -t js` emit ES modules. JavaScript is a **bounded
target**: Myna semantics are Python semantics, so the generator inlines `__myna_*`
helpers for truthiness, equality, `%`, `//`, `#`, `<-`, indexing, slicing, and printing.

Unsupported constructs fail with a compile-time `TargetError` instead of producing wrong
output:

- relative imports and multi-file bundling;
- multiple inheritance, class decorators, and method decorators;
- builtins with no faithful JavaScript equivalent (`@open`, `@ord`, `@id`, …);
- Python standard-library imports (they are not rewritten for Node).

Known representation limits: JavaScript has one number type (no `int`/`float` split or
arbitrary-precision integers), tuples and lists are both arrays, dictionary keys are
JavaScript property names (string-coerced), `with` is approximated
with `try`/`finally` + `.close()`, keyword arguments to user functions become a trailing
object, f-string format specs beyond `.Nf` are not translated, `===` maps to `Object.is`
(so primitive identity compares by value), ordered comparisons use JavaScript coercion
when operand types differ, and bitwise operators use 32-bit JavaScript semantics.
`myna targets` reports
whether a file *generates* for a target; the test suite also executes the Node output and
runs `node --check` on every generated file.

---

## Token & Character Efficiency Benchmarks

Measured by compiling each example to Python and running `python3 -m myna stats` on the generated file (so the Myna columns reflect the decompiler's `compact` and `-m` modes). Counts use the built-in `bpe-approx` estimator unless `tiktoken` is installed:

```bash
python3 -m myna compile examples/demo.myna -o /tmp/demo.py
python3 -m myna stats /tmp/demo.py
```

Running `stats` directly on a `.myna` file instead compares the generated Python against that file as written, so its Myna counts will differ from the table.

| Example Program | Python Tokens / Chars | Myna (Compact) | Myna (Ultra-Compact `-m`) |
| :--- | :--- | :--- | :--- |
| **`examples/demo.myna`** (Async Task Pipeline) | `517` toks / `953` chars | `271` toks (**-47.6%**) / `463` chars (**-51.4%**) | **`247` toks (-52.2%)** / **`397` chars (-58.3%)** |
| **`examples/rest_api.myna`** (Todo HTTP REST API) | `4,105` toks / `8,011` chars | `2,183` toks (**-46.8%**) / `3,932` chars (**-50.9%**) | **`2,045` toks (-50.2%)** / **`3,573` chars (-55.4%)** |
| **`examples/books_api.myna`** (Library Catalog API) | `4,402` toks / `8,515` chars | `2,371` toks (**-46.1%**) / `4,381` chars (**-48.5%**) | **`2,289` toks (-48.0%)** / **`4,104` chars (-51.8%)** |

---

## Language Cheat Sheet

| Feature | Myna Syntax | Python Equivalent | JavaScript Equivalent |
| :--- | :--- | :--- | :--- |
| **Literals** | `T`, `F`, `N`, `U`, `_` | `True`, `False`, `None`, `None`, `pass` | `true`, `false`, `null`, `undefined`, `/*noop*/` |
| **Types** | `i`, `f`, `s`, `b`, `B`, `A`, `T?`, `[T]`, `{K:V}` | `int`, `float`, `str`, `bool`, `bytes`, `Any`, `T \| None`, `list[T]`, `dict[K, V]` | *(Type annotations stripped in JS)* |
| **Imports** | `<os, numpy>np` / `<mod:{a, b>c}` | `import os, numpy as np` / `from mod import a, b as c` | `import * as ...` / `import { a, b as c } from ...` |
| **Targets** | `@target(py)` / `@target(py) { ... }` | Python-only module / Python-only block | JS-only module / JS-only block |
| **Functions** | `@f(a:i, b=1)->i { ^a+b }` or `@f(a)=>a+1` | `def f(a: int, b=1) -> int: return a + b` | `function f(a, b = 1) { return a + b; }` |
| **Async / Gen** | `~@f` / `~expr` / `*@gen` / `^*val` | `async def` / `await` / generator / `yield` | `async function` / `await` / `function*` / `yield` |
| **Classes** | `$C < Base { @init(x){ .x=x } }` | `class C(Base): def __init__(self, x): self.x = x` | `class C extends Base { constructor(x) { this.x = x; } }` |
| **Dataclasses** | `$$User(id:i, name:s="anon")` | `@dataclass class User: ...` | `class User { constructor(id, name = "anon") ... }` |
| **Dict Shorthands** | `{.id, .title, =name, ok: T}` | `{"id": self.id, "title": self.title, "name": name, "ok": True}` | `({id: this.id, title: this.title, name, ok: true})` |
| **Key Lookup** | `d$key` / `d$?key ?? "def"` | `d["key"]` / `d.get("key") or "def"` | `d["key"]` / `d.get("key") ?? "def"` |
| **Branching** | `? c1 {...} :? c2 {...} : {...}` | `if c1: ... elif c2: ... else: ...` | `if (c1) {...} else if (c2) {...} else {...}` |
| **Pattern Match** | `?? v { 0 => {...}; x ? x>0 => {...}; _ => {...} }` | `match v: case 0: ... case x if x > 0: ... case _: ...` | Block-scoped pattern & guard dispatch |
| **Loops** | `% x <- 0..10 { ... }` / `%? cond { ... }` | `for x in range(10): ...` / `while cond: ...` | `for (let x = 0; x < 10; x += 1)` / `while (cond)` |
| **Comprehensions** | `[x*2 \| x <- items ? x > 0]` | `[x * 2 for x in items if x > 0]` | `items.filter(x => x > 0).map(x => x * 2)` |
| **Exceptions** | `!{ ... } !!e:ValueError { ... } !: { ... }` | `try: ... except ValueError as e: ... finally: ...` | `try { ... } catch (e) { ... } finally { ... }` |
| **With / Assert** | `!& f=open(p) { ... }` / `!? cond, "msg"` | `with open(p) as f:` / `assert cond, "msg"` | Scoped try/finally `.close()` / `if (!cond) throw ...` |
| **Built-in Aliases** | `p`, `#x`, `@j`, `@J`, `@u8`, `@u8d`, `@srt`, `@sum` | `print`, `len(x)`, `json.loads`, `json.dumps`, `.encode`, `.decode`, `sorted`, `sum` | `console.log`, `len`, `JSON.parse`, `JSON.stringify`, `TextEncoder`, `TextDecoder`, `.sort`, `.reduce` |

See [`SPEC.md`](https://github.com/jhicksdev/myna/blob/main/SPEC.md) for the complete language specification and [`skills/myna/SKILL.md`](https://github.com/jhicksdev/myna/blob/main/skills/myna/SKILL.md) for the AI agent skill file.

---

## Running Tests

```bash
python3 -m unittest discover -s tests -v
```

---

## Versioning & Design Decisions

Releases follow the policy in [`VERSIONING.md`](https://github.com/jhicksdev/myna/blob/main/VERSIONING.md): during 0.x, patches are correctness fixes and release hygiene, minors carry new syntax, new capabilities, or intentional behavior changes, and 1.0 is gated on a documented, executable parity matrix. The accepted decisions behind the targets are recorded in [`DECISIONS.md`](https://github.com/jhicksdev/myna/blob/main/DECISIONS.md).

---

## License

[MIT](https://github.com/jhicksdev/myna/blob/main/LICENSE)
