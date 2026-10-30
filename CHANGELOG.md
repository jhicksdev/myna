# Changelog

## Unreleased

## 0.7.0 (2026-10-29)

Second half of the Starling downstream report (`GAPS.md`): the additions that were
language or CLI surface rather than fixes. Minor bump per `VERSIONING.md` §2.

### Added

- `new C(args)` constructs a class defined outside Myna. Python emits a plain call;
  JavaScript and TypeScript emit `new`, which a foreign class requires. Myna classes keep
  their implicit `new`. See `DECISIONS.md` D-009.
- `?? subject { pat => expr; _ => expr }` in expression position is a match expression:
  the value of the matched arm, with the same patterns, guards, and captures as the
  statement form and a single evaluation of the subject. Python hoists a `match` helper;
  JavaScript/TypeScript build a nested conditional.
- Quoted module names import packages that are not dotted identifiers, which is how scoped
  npm packages work: `<"@opentui/core":{createCliRenderer}` or `<"@opentui/core">core`.
  The Python target raises `TargetError`.
- `myna run -t ts` compiles the reachable graph to a temporary `.mts` tree and executes it
  with Bun or Node >= 22.6. `DECISIONS.md` D-006 is amended accordingly.
- `CompileError` (exported from `myna`) reports program-level problems found before code
  generation.

### Changed

- A call whose callee is declared in the same module with `**kwargs` and receives a trailing
  `k: v` argument now raises `CompileError` naming both spellings. Passing a dict to an
  imported callable is unchanged. See `DECISIONS.md` D-008.
- A statement-form match arm holding a bare value (`?? v { 0 => "zero" }`) is a parse
  error: it was computed and discarded. Block arms and arms with a side effect are
  unchanged.

### Fixed

- JavaScript/TypeScript: an alternative pattern (`"b" | "c"`) compiled to a bitwise OR
  instead of an alternative set.

### Documentation

- `SPEC.md` is v0.7 and documents `new`, the match expression, quoted module names, and the
  call-site dict / `d$key` rules.
- TypeScript import specifiers are unchanged, and `SPEC.md` now says why: `tsc` under
  `--module nodenext` maps `./x.mjs` to `x.mts` and emits `./x.mjs`, and Bun resolves it
  too. Only a tool that resolves the specifier literally against the filesystem would
  care, which `myna run -t ts` sidesteps by naming `.mts` in its temporary tree.

## 0.6.1 (2026-10-29)

Correctness patch from the Starling downstream report (`GAPS.md`). No new syntax, no CLI
surface change, no behaviour change for programs that compiled correctly before.

### Fixed

- `T`, `F`, `N`, and `U` are reserved binding names. A class, function, parameter,
  variable, loop target, or import alias with one of those names was accepted and then
  resolved to the literal at every use site, so `$$U(a:i)` compiled to `None(1)`.
  `python_to_myna` renames such Python bindings (`class U` → `$U_`) to keep the
  round-trip contract. See `DECISIONS.md` D-007.
- A relative module-object import with a dotted name (`<.pkg.mod`) emitted
  `from . import pkg.mod`, which is not valid Python. It now emits
  `from .pkg import mod`, keeping any alias.
- A dataclass field defaulting to a list, dict, or set literal (`$$D(xs:[s]=[])`) emitted
  a class-level mutable default that `@dataclass` rejects at import time. It is emitted as
  `field(default_factory=...)`, so each instance gets its own value — matching what the
  JavaScript/TypeScript targets already did.
- `@name` in expression position is accepted only for the builtin aliases (plus
  `@u8`/`@u8d`); any other name raised no error and produced invalid Python
  (`p(@f(2))` → `print(@f(2))`).
- `{Content-Type: "json"}` parsed as a subtraction and failed at run time. A dict key that
  is a subtraction or division of two identifiers is now a parse error telling the reader
  to quote it; `{(a-b): 1}` still computes a key.
- `myna run` tracebacks point at the `.myna` line with the Myna source, including failures
  inside imported `.myna` modules, and no longer print runner frames. `myna_to_python` /
  `compile_to_python` take an optional `sourcemap=True` for the underlying line mapping;
  default output is unchanged.
- `--module-root` is now a ceiling for the entry file, so `<..src.util` from an entry in
  `tests/` resolves against the declared root instead of failing with "attempted relative
  import beyond top-level package". `myna run`, `myna bundle`, the zipapp, and the
  JavaScript/TypeScript resolver all apply the same rule.
- A bare `raise` written as `=>!^` immediately followed by a compound clause (`!!`, `%:`,
  `:?`) was parsed as the start of a raise expression.
- The decompiler emitted a one-statement `for`/`while`/`with` body as `=>stmt`, which
  re-parsed as a paren lambda; those bodies now use braces.

### Documentation

- `SPEC.md` now documents dict literals, `d$key`/`d$?key` key access, call-site `k: v`
  dicts versus `k=v` keyword arguments, and `@` in expressions — the behaviours behind
  several entries in the downstream report.
- Documented the reserved literal names, the module-root ceiling, mutable dataclass
  defaults, and `myna run` tracebacks in `README.md`, `SPEC.md`, and
  `skills/myna/SKILL.md`.

## 0.6.0 (2026-10-29)

### Added

- TypeScript: `myna compile -t ts` (and `myna_to_ts`) emits typed `.ts`/`.mts` modules.
  TypeScript is a typed projection of the JavaScript target: it uses the same runtime
  helpers, Portable Core, `@target(py, js)` contract, `@target(js)` blocks, and
  `TargetError`s. `$=` becomes `export type`, a relative import of an alias becomes
  `import type`, and annotations are erased. Unannotated parameters are explicit `any`;
  truthful annotations pass `tsc --strict`. `myna run -t ts` is compile-only in this
  release. See `DECISIONS.md` D-006 and the README TypeScript section.
- `myna targets` reports `ts` alongside `py`/`js`; an output extension of `.ts`/`.mts`
  selects the target when `-t` is omitted.
- `myna_to_ts()` / `compile_to_ts()` are exported from `myna`; a new
  `myna.modules.module_type_aliases()` lets the generator emit type-only imports.

### Changed

- **Breaking:** a module with no `@target(...)` declaration now defaults to
  `@target(py)` instead of implicit `@target(py, js)`. Portability is opt-in. Add
  `@target(py, js)` to any module that must compile for JavaScript or TypeScript. This
  completes the deprecation announced in 0.5.0 (`DECISIONS.md` D-003); there is no
  syntax change, only one declaration per portable module.

### Fixed

- JavaScript/TypeScript: `+@`/`+$` declarations whose names are JavaScript reserved
  words (for example `+@default`) are exported under the source name instead of an
  unimportable `$`-prefixed binding.
- TypeScript: Python `typing`/`collections.abc` annotations now generate valid types.
  `Callable`, `Mapping`, `Sequence`, `Iterator`, `Awaitable`, `Generator`, `Type`, and
  `Self` map to their TypeScript equivalents; `ClassVar`/`Final`/`Annotated` erase to
  their inner type; unknown `typing.*` names become `any`. Type arguments on user
  classes and aliases are erased because Myna has no generic declarations.
- TypeScript: a `**kwargs` parameter is optional (`= {} as any`), so calls without
  keyword arguments type-check.
- JavaScript/TypeScript: a `with ... as name` binding remains visible after the
  statement. The context object is closed instead of the bound value, and sibling
  `with` statements no longer share a context-handle name.
- JavaScript/TypeScript: dataclass subclasses now call `super(...)` with the base
  dataclass's fields, producing valid classes in both targets. Nested classes and
  dataclass inheritance from a class with a custom `@init` are rejected with
  `TargetError` instead of emitting invalid code.

### Documentation

- Document the TypeScript target, its type mapping, `tsconfig` requirements, and limits
  in `SPEC.md`, `README.md`, and `skills/myna/SKILL.md`.

## 0.5.0 (2026-10-28)

### Added

- `myna run` and `myna bundle` accept `--module-root DIR` (or `MYNA_MODULE_ROOT`), which
  resolves the entry file's relative imports from `DIR`. A `tests/` entry can now reach a
  sibling `src/` tree without a committed symlink.
- JavaScript: relative imports compile to multi-file ES modules
  (`<.util:{f}` → `import { f } from "./util.js"`), every top-level binding is exported,
  and `myna run -t js` compiles the reachable graph to `.mjs` files before running Node.
  Single-file JS bundling is still out of scope. See `DECISIONS.md` D-005.
- `<.util` (a relative import without a name list) now binds the imported module object
  instead of silently becoming the absolute `import util`.

### Changed

- String literals now decode Python's full escape set (`\a \b \f \v \xNN \uNNNN
  \UNNNNNNNN \ooo \N{NAME}` and a backslash-newline continuation), closing `GAPS.md` G1.
  Unknown or malformed escapes are a `LexError` instead of being silently kept; use a raw
  string (`_"..."`) to keep a backslash.
- JavaScript `p` of a string inside a list/dict/set now escapes control characters the way
  Python's `repr` does, so escaped values print identically on both targets.

### Deprecated

- Implicit `@target(py, js)` for modules with no declaration. From **0.6.0** a module
  defaults to `@target(py)`; add `@target(py, js)` to any module that must compile for
  JavaScript. This is `DECISIONS.md` D-003, deferred from 0.5.0 and announced here per
  `VERSIONING.md` §2. Migration: one declaration per portable module, no syntax change.

### Fixed

- JavaScript `@main` is guarded by `import.meta.filename === process.argv[1]` instead of
  running whenever the module is loaded, so a multi-file program only runs its entry
  file's `@main` block (matching Python's `__name__ == "__main__"`).
- JavaScript string literals are emitted as valid ES string literals for every code point
  (`repr` could emit `\UXXXXXXXX`/`\N{...}`).
- A relative import that cannot be resolved under the module root now reports an
  actionable error (with the module root and the expected path) instead of a
  `ModuleNotFoundError` traceback mentioning the synthetic package name.
- JavaScript star imports (`<math:{*}`) are rejected with `TargetError` instead of
  emitting invalid JavaScript.

### Documentation

- `SPEC.md`, `README.md`, and `skills/myna/SKILL.md` document the string escape set,
  `--module-root`, and the JavaScript multi-file import rules.

## 0.4.2 (2026-10-27)

### Fixed

- The Python-to-Myna decompiler's compact mode no longer inlines a string-bearing
  temporary into an f-string interpolation. The emitted f-string needed Python 3.12's
  PEP 701 quoting rules, so round-tripped output failed to compile on Python 3.11.
- The Python backend now emits Python 3.11-compatible f-strings when an interpolation
  contains a quote or backslash, choosing a safe delimiter or falling back to
  `str.format`. Previously such Myna source produced PEP 701-only output.

## 0.4.1 (2026-10-26)

### Fixed

- JavaScript: `!?` try-else blocks, loop-else (`%:`) blocks, and every `!!` handler are
  now emitted. Previously the `else` blocks were dropped and only the first handler was
  generated.
- JavaScript semantics now match Python for truthiness (`?`, `%?`, `?:`, `!`, `&&`,
  `||`, comprehension filters), equality (`==`, `!=`, `===`, `!==`), floored `%` and
  `//`, `#`, `<-`/`!<-`, indexing (including negative indices and missing keys/slices),
  slicing (including steps), `d$k`/`d$?k`, and `+`/`*` string and list behaviour.
- JavaScript `@` builtins now work as first-class values and through `|>`: `@sum`,
  `@srt`, `@enum`, `@zip`, `@map`, `@flt`, `@rev`, `@min`, `@max`, `@all`, `@any`.
  `@srt` now sorts numbers numerically and honours `reverse=`.
- JavaScript `p` prints Python-style values (`True`/`False`/`None`, lists, dicts, sets,
  bytes) instead of `console.log` formatting.
- JavaScript `del x` no longer emits a strict-mode `delete x` syntax error.
- JavaScript ranges with negative steps iterate correctly.
- Bare `!^` inside a renamed `!!` handler re-raises the caught exception.
- `try` without an `!!` handler or `!:` block, and try-else without `!!`, are now parse
  errors instead of producing invalid Python.
- JavaScript rejects multiple inheritance, class/method decorators, relative imports,
  and builtins with no faithful JavaScript equivalent with `TargetError` instead of
  emitting wrong output.
- `myna compile -t js` no longer emits invalid JavaScript for builtin aliases used
  through `|>`.

### Metadata

- `myna --version` reports the package version and the language version.
- The version is single-sourced from `myna/__init__.py`; `pyproject.toml` reads it
  dynamically.

### Documentation

- Add `VERSIONING.md` (release policy) and `DECISIONS.md` (Python is the normative
  semantics; JavaScript is a bounded portable-core target; `@target` defaults to Python
  only from 0.5.0).
- Document the JavaScript target's current scope and limitations in `README.md`, and
  align `SPEC.md` with language 0.4.

## 0.4.0 (2026-10-24)

- `myna run` now resolves relative imports (`<.util:{f}`, `<.pkg.mod:{f}`) to sibling
  `.myna` modules and package directories, with lazy compilation and normal
  `sys.modules` caching. `myna compile` is still per-file, and `-t js` is single-file.
- Add `myna bundle input.myna -o app.py`, which embeds the relative-import graph in a
  single standalone Python file that needs only the standard library at runtime. With
  `--zipapp` it writes a runnable, reproducible `.pyz` archive with real module files.
- Lex/parse errors raised while running or importing a module now include the source
  file path.
- Fix `:?` runtime checks with compound types (`[T]`, `{K:V}`, `{T}`, `Name[T]`): they
  emitted invalid Python (`isinstance(x, [s])`) and JS (`x instanceof [s]`). They now
  check the runtime origin type (`list`, `dict`, `set`, `Name`); `(A, B)` remains a union.
- Fix `pip install -e .` failing because setuptools flat-layout discovery treated
  `skills/` as a package; the distributed packages are now declared explicitly.

## 0.3.0

- Add module-level `@target(...)` declarations and compile-time `@target(...) { ... }` blocks.
- Add `myna targets` to report declared target support and likely JavaScript import incompatibilities.
- Harden Python-to-Myna round-trips: corpus tests, lossless byte literals, f-string conversions, clearer `DecompileError` failures.
- Improve parser handling of tuple conditions, brace-adjacent definition sigils, and f-string error locations.
- Print concise language errors from the CLI instead of tracebacks.

## 0.2.0

- Initial public release of Myna with Python and JavaScript backends, Python decompilation, and token-efficiency stats.
