# Myna (`myna-lang`)

[![PyPI](https://img.shields.io/pypi/v/myna-lang?style=flat-square&logo=pypi&logoColor=white)](https://pypi.org/project/myna-lang/)
[![PyPI downloads](https://img.shields.io/pypi/dm/myna-lang?style=flat-square&label=downloads)](https://pypi.org/project/myna-lang/)
[![Python versions](https://img.shields.io/pypi/pyversions/myna-lang?style=flat-square&logo=python&logoColor=white)](https://pypi.org/project/myna-lang/)
[![License: MIT](https://img.shields.io/github/license/jhicksdev/myna?style=flat-square&color=yellow)](https://github.com/jhicksdev/myna/blob/main/LICENSE)

**Myna** is an ultra-dense, symbol-based, AI-native programming language designed to cut LLM token and character usage by **~50%** while transpiling 1:1 to **Python 3.12+** and to bounded **JavaScript (ES2024+)** and **TypeScript** targets—and decompiling existing Python code back into Myna.

---

## Why Myna?

Coding agents spend thousands of context and output tokens on repetitive syntactic boilerplate (`def __init__(self, ...):`, `self.`, `Optional[...]`, `try ... except Exception as e:`, quoted JSON keys, and 4-space indentation blocks).

Myna replaces verbose multi-token boilerplate with **tokenizer-friendly ASCII sigils and digraphs** (`$$`, `@`, `~@`, `=>`, `??`, `!?`, `!&`, `$`, `$?`) and brace-delimited blocks (`{}`):
- **~46%–52% fewer LLM tokens** and **~48%–58% fewer characters** than equivalent Python (compact and ultra-compact modes).
- **Zero indentation fragility:** Blocks use `{ ... }` or `=>`, making partial diffs and single-line generation rock-solid for AI agents.
- **Bi-directional (`Python <-> Myna`) & Multi-Target (`Myna -> Python / JS / TS`):** Compress existing Python codebases into `.myna` to fit twice as much code into an agent's context window, or let agents write `.myna` and transpile to clean Python, JavaScript, or typed TypeScript.
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

# Run the same program through the TypeScript target (Bun, or Node >= 22.6)
python3 -m myna run -t ts examples/cross_target.myna

# Compile Myna -> Python (.py)
python3 -m myna compile examples/rest_api.myna -o rest_api.py

# Compile Myna -> JavaScript (.js)
python3 -m myna compile -t js examples/cross_target.myna -o cross_target.js

# Compile Myna -> TypeScript (.ts), or infer it from the output extension
python3 -m myna compile -t ts examples/cross_target.myna -o cross_target.ts

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

# Report declared/inferred Python, JavaScript & TypeScript support
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

- `<.util:{slug}` → `util.myna` beside the importing module.
- `<.pkg.helper:{parse}` → `pkg/helper.myna`; `pkg` may have an `__init__.myna` or be a
  plain directory (namespace package).
- `<.util` (no `{...}` list) binds the imported module object.
- Absolute imports (`<json`, `<mypkg>alias`) keep their normal Python meaning. A quoted
  name imports a package that is not a dotted Python identifier, which is how scoped npm
  packages work for the JS/TS targets: `<"@opentui/core":{createCliRenderer}` (the Python
  target rejects it).
- Imported files are compiled on first import and cached by Python's import system.
- `myna run --module-root DIR` (or `MYNA_MODULE_ROOT=DIR`) resolves the **entry file's**
  relative imports from `DIR` instead of the entry's own directory. For the usual
  `src/` + `tests/` layout this removes the need for a symlink:

  ```bash
  python3 -m myna run --module-root . tests/run_tests.myna
  ```

  Modules imported from that root still resolve their own relative imports from their own
  directory. With a module root set, the entry's own directory is not searched, so a
  file beside the entry is imported by its path from the root (e.g. `<.tests.harness`).
  The root is also the ceiling: `<..src.util` from an entry of any depth resolves against
  it, so a nested entry can reach a sibling `src/` with `..` as well as with `.`. A
  relative import that would climb past the root is an error when no root is declared.
- `myna run` reports a runtime failure with the Myna line and the Myna source line, not
  the generated Python: failures inside imported `.myna` modules map the same way, and
  frames from the runner itself are omitted.
- `myna bundle src/main.myna -o app.py` embeds the whole relative-import graph in one
  standalone Python file. It runs with a plain `python3` and does not need `myna`
  installed; absolute imports still come from the environment.
- `myna bundle src/main.myna --zipapp -o app.pyz` writes a runnable, executable zipapp
  containing real module files (`python3 app.pyz`). It is reproducible: rebuilding the
  same sources produces identical bytes. Without `-o`, the archive lands next to the
  entry file as `<name>.pyz`. `--module-root` applies to bundling too.
- `myna compile` still compiles one file at a time. If you use relative imports, the
  emitted `.py` files must be placed in a matching Python package.
- For `-t js`, each relative import becomes a relative ES module specifier
  (`./util.js`, or `./util.mjs` when the output ends in `.mjs`) and every top-level
  binding is exported. Compile the files into a mirrored tree, or let
  `myna run -t js` do it. Node treats a `.js` file containing `import`/`export` as
  CommonJS unless the project sets `"type": "module"`, so prefer `.mjs` outputs or add
  that to the project's `package.json`. `myna bundle` remains Python-only.

### JavaScript target

`myna compile -t js` and `myna run -t js` emit ES modules. Portability is opt-in: a
module without a declaration is Python-only, so add `@target(py, js)` to any file that
must compile for JavaScript or TypeScript (`DECISIONS.md` D-003). JavaScript is a
**bounded target**: Myna semantics are Python semantics, so the generator inlines
`__myna_*` helpers for truthiness, equality, `%`, `//`, `#`, `<-`, indexing, slicing, and
printing. The runtime floor is Node 20.11+ (`import.meta.filename` backs the `@main`
guard).

Unsupported constructs fail with a compile-time `TargetError` instead of producing wrong
output:

- single-file bundling for JavaScript (`myna bundle` is Python-only; use
  `myna compile -t js` over the tree or `myna run -t js`);
- star imports (`<math:{*}`);
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
`@main` compiles to an `import.meta.filename === process.argv[1]` guard (Node's `__main__`
equivalent), so an imported module's entry block stays dormant.
`myna targets` reports
whether a file *generates* for a target; the test suite also executes the Node output and
runs `node --check` on every generated file.

### TypeScript target

`myna compile -t ts` emits `.ts` (or `.mts`) modules. TypeScript is a **typed projection
of the JavaScript target**, not a third semantics: it uses the same helpers, the same
Portable Core, the same `TargetError`s, and the same `@target(py, js)` contract. There is
no `@target(ts)`; `@target(js)` blocks are emitted for TypeScript. Type annotations are
**erased** and never add runtime checks.

`myna run -t ts` compiles the reachable module graph to a temporary `.mts` tree and runs it
with Bun, or with Node >= 22.6 (Node strips the types). `myna compile -t ts` still emits
sibling imports as `./x.mjs`, which `tsc` (NodeNext) maps to `x.mts` and Bun resolves too;
only the runner's temporary tree names `.mts`, because it executes the files instead of
compiling them.

Annotations become TypeScript types where Myna has them:

| Myna | TypeScript |
| :--- | :--- |
| `i`, `f` | `number` |
| `s` | `string` |
| `b` | `boolean` |
| `B` | `Uint8Array` |
| `A` | `any` |
| `N` | `null` |
| `T?` | `T \| null` |
| `[T]` | `T[]` |
| `{K:V}` | `Record<K, V>` |
| `{T}` | `Set<T>` |
| `(T1, T2)` | `[T1, T2]` |
| `Name[T]` | `Name<T>` for TypeScript-library types; the arguments are erased for user classes and aliases |

Python `typing` names are translated too: `Callable[[i], s]` becomes
`(arg0: number) => string`, `Mapping[K, V]` becomes `Record<K, V>`, `Sequence[T]`
becomes `T[]`, `Iterator[T]` becomes `Iterable<T>`, `Awaitable[T]` becomes
`Promise<T>`, `Generator[Y, S, R]` becomes `Generator<Y, R, S>`, `Type[T]` becomes
`new (...args: any[]) => T`, and `Self` resolves to the enclosing class.
`ClassVar[T]`, `Final[T]`, and `Annotated[T, ...]` erase to `T`; an unknown
`typing.*` name becomes `any` instead of a dangling identifier. User classes and
aliases are not generic in Myna, so `Box[int]` is emitted as `Box` (the same rule as
erased annotations).

`$= Alias = Type` becomes `export type Alias = Type`, and a relative import of a type
alias becomes `import type`; every other top-level binding is exported as before.
Unannotated parameters are emitted as explicit `any` (not implicit), and a function with
a declared return type gets a `null as any` fallback where Python could fall off the end.
A `**kwargs` parameter becomes an optional trailing object parameter, matching the
JavaScript projection's keyword-argument shape.

The guarantee is that a module whose annotations are truthful passes `tsc --strict`.
`tsc` also rejects a Myna annotation that does not match the value (for example
`@f(x:i)->s => 1`); `myna compile` still emits the file. TypeScript is advisory, like
Python annotations.

Recommended `tsconfig.json` for direct Node execution:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "strict": true,
    "types": ["node"]
  }
}
```

Use `.mts`, or set `"type": "module"` in `package.json`, so NodeNext treats the files as
ES modules; otherwise `import.meta.filename` (the `@main` guard) is rejected. Bundler
users can use `"module": "ESNext"` and `"moduleResolution": "Bundler"` instead.
`@types/node` is required for `@main`, `p`, and the `Uint8Array`/`TextEncoder` helpers.
Relative-import specifiers are `./util.js` (`./util.mjs` for `.mts` output), so `tsc`
resolves them to the generated `.ts` files.

The JavaScript limits apply unchanged. TypeScript-specific limits: no decorators
(NestJS/Angular-style), no JSX/TSX, no `implements`, and no generic declarations.
Classes only declare fields found in the class body, dataclass fields, or `self.x =`
assignments inside methods; dynamically added attributes need a declaration. Nested
classes are rejected. A dataclass may inherit one dataclass defined in the same module;
the subclass constructor takes the base's fields and calls `super(...)`. Deriving a
dataclass from a class with a custom `@init` is rejected because there is no dataclass
constructor to forward to. Tuples and lists are both arrays, and dictionary keys are
string-coerced at runtime, so `Record<K, V>` is advisory; a non-key-compatible `K` is
emitted as `Record<string, V>`. Strict TypeScript also rejects dynamically retyped
locals; annotate them with `A`. A `with ... as name` binding is declared outside the
generated `try` so it remains visible after the statement, as in Python.

The test suite compiles the cross-target corpus with `tsc --strict`, transpiles it, and
executes it with Node alongside the Python output. The dev-only toolchain lives in
`tests/ts/package.json`; run `npm ci --prefix tests/ts` to enable the TypeScript tests
locally.

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
| **Types** | `i`, `f`, `s`, `b`, `B`, `A`, `T?`, `[T]`, `{K:V}` | `int`, `float`, `str`, `bool`, `bytes`, `Any`, `T \| None`, `list[T]`, `dict[K, V]` | JS strips annotations; TS emits `number`, `string`, `boolean`, `Uint8Array`, `any`, `T \| null`, `T[]`, `Record<K, V>` |
| **Imports** | `<os, numpy>np` / `<mod:{a, b>c}` | `import os, numpy as np` / `from mod import a, b as c` | `import * as ...` / `import { a, b as c } from ...` |
| **Targets** | `@target(py)` / `@target(py) { ... }` | Python-only module / Python-only block | JS/TS-only module / block (`@target(js)` also applies to `-t ts`) |
| **Functions** | `@f(a:i, b=1)->i { ^a+b }` or `@f(a)=>a+1` | `def f(a: int, b=1) -> int: return a + b` | `function f(a, b = 1) { return a + b; }` |
| **Async / Gen** | `~@f` / `~expr` / `*@gen` / `^*val` | `async def` / `await` / generator / `yield` | `async function` / `await` / `function*` / `yield` |
| **Classes** | `$C < Base { @init(x){ .x=x } }` | `class C(Base): def __init__(self, x): self.x = x` | `class C extends Base { constructor(x) { this.x = x; } }` |
| **Constructors** | `new ExternalCtor(1, opts: T)` | `ExternalCtor(1, {"opts": True})` | `new ExternalCtor(1, {opts: true})` |
| **Dataclasses** | `$$User(id:i, name:s="anon")` | `@dataclass class User: ...` | `class User { constructor(id, name = "anon") ... }` |
| **Dict Shorthands** | `{.id, .title, =name, ok: T}` | `{"id": self.id, "title": self.title, "name": name, "ok": True}` | `({id: this.id, title: this.title, name, ok: true})` |
| **Key Lookup** | `d$key` / `d$?key ?? "def"` | `d["key"]` / `d.get("key") or "def"` | `d["key"]` / `d.get("key") ?? "def"` |
| **Branching** | `? c1 {...} :? c2 {...} : {...}` | `if c1: ... elif c2: ... else: ...` | `if (c1) {...} else if (c2) {...} else {...}` |
| **Pattern Match** | `?? v { 0 => {...}; x ? x>0 => {...}; _ => {...} }` | `match v: case 0: ... case x if x > 0: ... case _: ...` | Block-scoped pattern & guard dispatch |
| **Match Expression** | `t = ?? v { 0 => "zero"; _ => "other" }` | Evaluates to the matched arm's value | Nested conditional |
| **Loops** | `% x <- 0..10 { ... }` / `%? cond { ... }` | `for x in range(10): ...` / `while cond: ...` | `for (let x = 0; x < 10; x += 1)` / `while (cond)` |
| **Comprehensions** | `[x*2 \| x <- items ? x > 0]` | `[x * 2 for x in items if x > 0]` | `items.filter(x => x > 0).map(x => x * 2)` |
| **Exceptions** | `!{ ... } !!e:ValueError { ... } !: { ... }` | `try: ... except ValueError as e: ... finally: ...` | `try { ... } catch (e) { ... } finally { ... }` |
| **With / Assert** | `!& f=open(p) { ... }` / `!? cond, "msg"` | `with open(p) as f:` / `assert cond, "msg"` | Scoped try/finally `.close()` / `if (!cond) throw ...` |
| **Built-in Aliases** | `p`, `#x`, `@j`, `@J`, `@u8`, `@u8d`, `@srt`, `@sum` | `print`, `len(x)`, `json.loads`, `json.dumps`, `.encode`, `.decode`, `sorted`, `sum` | `console.log`, `len`, `JSON.parse`, `JSON.stringify`, `TextEncoder`, `TextDecoder`, `.sort`, `.reduce` |

`T`, `F`, `N`, and `U` are reserved: they cannot name a class, function, parameter,
variable, loop target, or import alias. `d$key` is a *literal* key lookup — use `d[k]` for a
computed key — and a trailing `k: v` argument is a dict, while `k=v` is a keyword argument.

See [`SPEC.md`](https://github.com/jhicksdev/myna/blob/main/SPEC.md) for the complete language specification and [`skills/myna/SKILL.md`](https://github.com/jhicksdev/myna/blob/main/skills/myna/SKILL.md) for the AI agent skill file.

---

## Running Tests

```bash
npm ci --prefix tests/ts          # dev-only TypeScript compiler + Node types
python3 -m unittest discover -s tests -v
```

The TypeScript tests use `tests/ts/node_modules/.bin/tsc`; without it (and Node on
`PATH`) the executable TypeScript cases are skipped, but CI installs the toolchain and
runs them.

---

## Versioning & Design Decisions

Releases follow the policy in [`VERSIONING.md`](https://github.com/jhicksdev/myna/blob/main/VERSIONING.md): during 0.x, patches are correctness fixes and release hygiene, minors carry new syntax, new capabilities, or intentional behavior changes, and 1.0 is gated on a documented, executable parity matrix. The accepted decisions behind the targets are recorded in [`DECISIONS.md`](https://github.com/jhicksdev/myna/blob/main/DECISIONS.md).

---

## License

[MIT](https://github.com/jhicksdev/myna/blob/main/LICENSE)
