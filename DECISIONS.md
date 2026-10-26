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

**Status:** Accepted — 2026-10-26

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

**Status:** Accepted — 2026-10-26; scheduled for 0.5.0

### Context

Today every module is implicitly `@target(py, js)`. If JavaScript only supports a
Portable Core (D-002), that default is a false promise: a portable module fails or
misbehaves only when someone tries it.

### Decision

The default becomes `@target(py)`. Claiming portability requires an explicit
`@target(py, js)`. This is a breaking change, so it ships in a minor (0.5.0) with a
deprecation note and a migration line in `CHANGELOG.md`.

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
