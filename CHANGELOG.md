# Changelog

## Unreleased

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

### Fixed

- JavaScript/TypeScript: `+@`/`+$` declarations whose names are JavaScript reserved
  words (for example `+@default`) are exported under the source name instead of an
  unimportable `$`-prefixed binding.

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
