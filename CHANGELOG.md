# Changelog

## Unreleased

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
