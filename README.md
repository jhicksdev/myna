# Myna (`myna-lang`)

**Myna** is an ultra-dense, symbol-based, AI-native programming language designed to cut LLM token and character usage by **~50%** while transpiling 1:1 to **Python 3.12+** and **JavaScript (ES2024+)**—and decompiling existing Python code back into Myna.

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

Myna requires **Python 3.11+** and has **zero external dependencies**.

```bash
# Install in editable/local mode (optional)
pip install -e .

# Run a Myna script directly (via Python)
python3 -m myna run examples/demo.myna

# Run a Myna script via Node.js (JavaScript target)
python3 -m myna run -t js examples/demo.myna

# Compile Myna -> Python (.py)
python3 -m myna compile examples/rest_api.myna -o rest_api.py

# Compile Myna -> JavaScript (.js)
python3 -m myna compile -t js examples/demo.myna -o demo.js

# Compress existing Python -> Myna (.myna)
python3 -m myna decompile script.py -o script.myna

# Ultra-compact decompilation (with local variable minification)
python3 -m myna decompile -m script.py -o script.min.myna

# Compare token & character efficiency
python3 -m myna stats examples/books_api.myna
```

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

See [`SPEC.md`](SPEC.md) for the complete language specification and [`skills/myna/SKILL.md`](skills/myna/SKILL.md) for the AI agent skill file.

---

## Running Tests

```bash
python3 -m unittest discover -s tests -v
```

---

## License

[MIT](LICENSE)
