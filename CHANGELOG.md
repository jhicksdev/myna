# Changelog

## 0.3.0

- Add module-level `@target(...)` declarations and compile-time `@target(...) { ... }` blocks.
- Add `myna targets` to report declared target support and likely JavaScript import incompatibilities.
- Harden Python-to-Myna round-trips: corpus tests, lossless byte literals, f-string conversions, clearer `DecompileError` failures.
- Improve parser handling of tuple conditions, brace-adjacent definition sigils, and f-string error locations.
- Print concise language errors from the CLI instead of tracebacks.

## 0.2.0

- Initial public release of Myna with Python and JavaScript backends, Python decompilation, and token-efficiency stats.
