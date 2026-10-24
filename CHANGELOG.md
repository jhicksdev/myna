# Changelog

## Unreleased

- `myna run` now resolves relative imports (`<.util:{f}`, `<.pkg.mod:{f}`) to sibling
  `.myna` modules and package directories, with lazy compilation and normal
  `sys.modules` caching. `myna compile` is still per-file, and `-t js` is single-file.
- Add `myna bundle input.myna -o app.py`, which embeds the relative-import graph in a
  single standalone Python file that needs only the standard library at runtime.
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
