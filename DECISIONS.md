# Design Decisions

Accepted decisions that constrain the language, the backends, and the release plan.
Each decision is normative until superseded. Version bumps follow
[`VERSIONING.md`](VERSIONING.md).

---

## D-001 — Python is the normative semantics

**Status:** Accepted — 2026-10-26
**Supersedes:** none

### Context

Myna has two backends, a Python-to-Myna decompiler, and no runtime library. The Python
backend is a textual translation, so it cannot define behavior independently of CPython.
The JavaScript backend is a re-implementation, and it currently diverges from Python in
several ways: truthiness of empty lists and dicts, `%` with negative operands, `#` on
astral-plane strings, integer width, and multiple inheritance.

### Decision

Myna is a **dense surface syntax over Python 3.12 semantics**. `SPEC.md` is the normative
text; CPython is the executable oracle; differential tests against CPython enforce the
match.

The JavaScript target **emulates** those semantics through inlined helpers (the existing
`__myna_len` / `__myna_in` approach generalizes to truthiness, equality, modulo, slicing,
and type checks). A construct that cannot be emulated exactly is rejected for `-t js`
with `TargetError` — never silently approximated.

### Consequences

- JS output may grow due to helpers. That is acceptable: Python is the density target,
  and the helpers are inlined, so the zero-dependency promise is preserved.
- Operators cannot follow the host language. `&&`, `||`, `!`, `==`, `%`, `#`, `<-`, and
  `:?` must all go through Python semantics on JS.
- The decompiler must preserve Python semantics; its guarantee is stated in terms of
  Python, not Myna.
- Two syntax questions must be resolved before the syntax freeze:
  - `===` currently means identity (`is`) in Python and `===` in JS. Keep it as identity
    and emit `Object.is` in JS (documenting the primitive caveat), or remove it.
  - `p(...)` is always rewritten to `print`, even when the user defines `@p`. Under
    Python-normative semantics, user definitions must win; aliases need a resolution rule.
- JS integers outside `±2^53`, `bytes`, and arbitrary-precision arithmetic are documented
  limitations of the portable core, not silent fixes.

### Open questions

- Exact helper set and where the portable core boundary is drawn (0.5.0).
- Exception type mapping between Python and JS.
- Slice and negative-index semantics on JS.

---

## D-002 — JavaScript is a bounded second target at 1.0

**Status:** Accepted — 2026-10-26. The packaging rules for relative imports and
`myna run -t js` are superseded by D-005 (2026-10-28); the rest remains normative.

### Context

The README presents Python and JavaScript as equal targets, but the JS backend is
single-file, has no import resolution or bundling, and silently drops several constructs.
Full parity at 1.0 would roughly double the release surface without strengthening the
language's core promise.

### Decision

At 1.0, JavaScript is a **supported second target with a documented Portable Core**:

- Single-file ESM only.
- Python semantics emulated via inlined helpers (D-001).
- Constructs outside the Portable Core are rejected at compile time for `-t js`.
- `myna run -t js` remains single-file.
- Relative-import resolution and JS bundling are explicitly **post-1.0 (1.x)**. Compiling
  a file with relative imports for JS must produce a clear error, not unresolvable output.
- `myna targets` reports which constructs block JS, so the claim is checkable.

Python remains the primary target: everything documented must work there.

### Consequences

- Cross-target tests must be **differential** (execute both, compare behavior), not just
  compare generated text, and every generated JS file must pass `node --check`.
- The README's portability claim must link to the Portable Core matrix rather than imply
  universal parity.
- New language constructs must be classified as `portable`, `python-only`, or `js-only`
  at design time.

### Open questions

- The exact Portable Core construct list (0.5.0).
- Whether the first-class JS story (multi-file, bundling, source maps) becomes the 1.x
  headline.

---

## D-003 — `@target` defaults to Python only

**Status:** Accepted — 2026-10-26; deferred to 0.6.0 (2026-10-28)

### Context

Today every module is implicitly `@target(py, js)`. If JavaScript only supports a
Portable Core (D-002), that default is a false promise: a portable module fails or
misbehaves only when someone tries it.

### Decision

The default becomes `@target(py)`. Claiming portability requires an explicit
`@target(py, js)`. This is a breaking change, so it ships in a minor (0.6.0) with a
deprecation note and a migration line in `CHANGELOG.md`. The deprecation is announced in
0.5.0; the flip was deferred from 0.5.0 so that release could ship the JavaScript
relative-import work (D-005) without an unrelated language-wide breaking change.

### Consequences

- Existing files that rely on implicit portability need one added declaration.
- `myna targets` output changes: "portable" is opt-in and reported as claimed, not
  assumed.
- Modules declaring `@target(py, js)` are checked against the Portable Core.

### Open questions

- Whether a `--allow-implicit-portability` migration flag is worth shipping.
- Length of the deprecation window (proposed: one minor).

---

## D-004 — Release versioning policy

**Status:** Accepted — 2026-10-26

The rules for patch/minor/major bumps, changelog categories, the release procedure, and
the 1.0 gate live in [`VERSIONING.md`](VERSIONING.md). This entry exists so the policy is
discoverable from the decision log.

---

## D-005 — JavaScript relative imports are multi-file ES modules

**Status:** Accepted — 2026-10-28
**Supersedes:** D-002's "Single-file ESM only" packaging rule and its
"Relative-import resolution and JS bundling are explicitly post-1.0 (1.x)" bullet, for
relative-import resolution only.

### Context

D-002 kept the JavaScript target single-file and deferred relative-import resolution to
1.x. A downstream project (`myna-lang` 0.4.2, `GAPS.md` G2) found that this blocked the
"compile the portable core to JavaScript" path entirely: modules that avoid Python-only
APIs and declare `@target(py, js)` still could not be compiled because their import graph
did not fit in one file.

### Decision

Relative imports are part of the JavaScript target:

- `<.util:{slug}` compiles to `import { slug } from "./util.js"`; the specifier mirrors
  the source tree and uses the extension of the output file (`-o app.mjs` → `./util.mjs`).
- Every top-level binding is exported so relative imports behave like Python's: a module
  can import any name it could import on the Python target. `+@`/`+$` continue to emit
  inline `export` declarations.
- `myna run -t js` compiles the reachable relative-import graph into a temporary tree and
  runs the entry with Node, so multi-file programs execute.
- `myna_to_js(source)` has no filesystem context, so it requires `source_path=` (or a
  `myna compile` of the file) when relative imports are present.

Single-file JavaScript **bundling** remains out of scope (`myna bundle` is Python-only);
the supported JavaScript unit is a tree of ES modules. Namespace imports and import
cycles follow Node's ESM semantics, not Python's partially-initialized modules.

### Consequences

- `node --check` must pass for every generated module, and cross-target tests must
  execute a compiled multi-file tree.
- The generated files must be written as siblings preserving their relative layout;
  `myna compile` remains per-file.
- `myna targets` reports relative imports as supported for `js`.
- The JavaScript runtime floor is Node 20.11+ (`import.meta.filename` backs the `@main`
  guard, matching Python's `__name__ == "__main__"`), which is a minor change under
  `VERSIONING.md` §6.
- This is a new target capability, so it is a minor, not a patch (`VERSIONING.md` §2),
  and the README/SPEC Portable Core text no longer lists relative imports as rejected.

