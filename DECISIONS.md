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

**Status:** Accepted — 2026-10-26; implemented in 0.6.0 (2026-10-29)

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

---

## D-006 — TypeScript is a typed projection of the JavaScript target

**Status:** Accepted — 2026-10-28
**Supersedes:** none

### Context

TypeScript is a superset of JavaScript: its types are erased before execution, and it
does not provide new runtime capabilities. Myna already has a bounded JavaScript target
(D-001, D-002, D-005) whose Python-semantics helpers and `TargetError` boundary are
tested by execution. Downstream TypeScript tools and frameworks want typed modules,
but making TypeScript a third semantic target would duplicate a contract with no
runtime difference and create ambiguity between `@target(js)` and `@target(ts)` blocks.

### Decision

TypeScript is an **output dialect** of the JavaScript target, not a third target:

- `myna compile -t ts` emits `.ts` (or `.mts`) modules using the same inlined
  `__myna_*` helpers, the same Portable Core, the same `TargetError` boundary, and the
  same `@target(py, js)` contract. `@target(js)` blocks are emitted for `-t ts`.
- `VALID_TARGETS` stays `py`/`js`; there is no `@target(ts)`. `myna targets` reports
  `ts` as a derived, generation-only target.
- Type annotations are **advisory and erased**. Unannotated parameters are emitted as
  explicit `any`; a module whose annotations are truthful passes `tsc --strict`. No
  runtime checks are added, and `i`/`f` both map to `number`.
- `$= Alias = Type` becomes `export type Alias = Type`; a relative import of an alias
  becomes `import type`; using a type alias as a value is a `TargetError` for `-t ts`.
- Relative-import specifiers are `.js`/`.mjs` (the files `tsc` emits), independent of
  the `.ts`/`.mts` output extension. NodeNext, `"type": "module"` or `.mts`, and
  `@types/node` are documented requirements for direct Node execution.
- The target is compile-only: `myna run -t ts` is rejected with an instruction to use
  `-t js`, which executes the same program.
- Class and type-alias names that TypeScript reserves for primitives (`string`,
  `number`, `any`, `unknown`, `never`, `void`, `object`, `symbol`, `bigint`, `null`,
  `undefined`) are rejected with `TargetError`; they cannot be renamed consistently
  because annotations such as `x: string` must keep meaning the primitive.

### Consequences

- `myna/backends/ts_gen.py` subclasses `JSGenerator` and reuses the JavaScript helper
  bodies with an annotated overlay. Helper bodies stay single-sourced; a change to a
  JavaScript helper surfaces as a TypeScript typecheck failure in the test suite.
- Python `typing`/`collections.abc` annotations are translated (`Callable`, `Mapping`,
  `Sequence`, `Iterator`, `Awaitable`, `Generator`, `Type`, `Self`, and their relatives)
  rather than emitted verbatim. Myna has no generic declarations, so type arguments on a
  user class or alias are erased (`Box[int]` → `Box`); unknown `typing.*` names become
  `any` instead of a dangling identifier. The helper typecheck test compiles every
  helper, not only the helpers a particular corpus uses.
- The test suite compiles the JavaScript cross-target corpus with `tsc --strict`,
  transpiles it, and executes it with Node, in addition to type-mapping and interop
  tests. The TypeScript compiler and `@types/node` are dev-only tools in
  `tests/ts/package.json`; the package keeps zero runtime dependencies.
- The JavaScript runtime floor (Node 20.11+) is unchanged. The TypeScript target is
  Node-first; browser/DOM output is not a supported contract.
- The README, `SPEC.md`, and `skills/myna/SKILL.md` document TypeScript as a typed
  projection and must not imply that `tsc` errors make `myna compile` fail.

### Open questions

- Class/method decorators and JSX/TSX, which frameworks such as NestJS, Angular, and
  React use, remain out of scope.
- Whether a TS-only construct would justify `@target(ts)` or a separate target in a
  future minor.
- Whether generated `.d.ts` sidecars or type inference for Myna become worthwhile.
- Browser-oriented output would need a different `@main` guard and DOM type story.


---

## D-007 — `T`, `F`, `N`, `U` are reserved as binding names

**Status:** Accepted — 2026-10-29
**Supersedes:** none

### Context

`T`, `F`, `N`, and `U` are the boolean, `None`, and `undefined` literals (D-001). They are
also legal identifiers, so a program could declare a class named `U` and then call
`U(1)`; the *use* parsed as the `undefined` literal and the program compiled to
`None(1)` and failed at run time. Downstream this survived review because the source
looked correct (GAPS.md G1). Myna has no scope-sensitive literal parsing, and adding it
would make the meaning of a one-letter token depend on a whole-file analysis.

### Decision

`T`, `F`, `N`, and `U` cannot be bindings. A class, function, type alias, parameter,
assignment target, `for`/comprehension target, `with ... as` name, `except ... as` name,
`global`/`nonlocal` name, or import alias spelled with one of them is a parse error
naming the collision. The literals themselves, and `N` as the `None` type shorthand,
are unchanged.

### Consequences

- The error is raised in the parser, so every target and `myna targets` agree.
- `python_to_myna` renames such Python bindings consistently (`class U` → `$U_`,
  including keyword arguments and `__all__`) so the
  `python -> myna -> python` contract in `test_roundtrip_corpus.py` still holds.
- The alternative — treating the literals as shadowable — was rejected: it would make
  `x = 1; T = 2; p(T)` depend on statement order for a one-character token.

---

## D-009 — `new` is an explicit constructor call

**Status:** Accepted — 2026-10-29
**Supersedes:** none

### Context

The JavaScript target injects `new` when the callee is a class it knows about (a Myna
class, an imported Myna class, or a Python exception shim). A class from a JavaScript or
TypeScript library is not in that set, so `BoxRenderable(r, opts)` emitted a plain call
and failed at run time with "Cannot call a class constructor without new" — cleanly
compiled, silently wrong (GAPS.md G8). Guessing from the callee's capitalisation would
break Python callables and Myna functions, and there is no runtime class test that works
before the call.

### Decision

`new C(a, b)` is an expression-level constructor call:

- Python emits `C(a, b)` (identity — Python classes are called).
- JavaScript and TypeScript emit `new C(a, b)`.
- Implicit `new` for known classes is unchanged, so existing Myna code is unaffected.
- `new` must be followed by a call: `new C(args)` or `new a.b.C(args)`. `new` is a soft
  keyword — it is only special when followed by an identifier or `(` in prefix position,
  so an existing binding named `new` outside that shape still parses.

### Consequences

- A library adapter layer (`box()`, `text()`, …) is no longer required; `new` lives in the
  calling Myna code.
- The Python target cannot distinguish an external call from a constructor, so a `new`
  that is meaningless on Python compiles to a plain call rather than erroring.
- `Call` and `NewExpr` share the argument layout, including the `k: v` dict shorthand and
  the `**kwargs` diagnostic in `myna/checks.py`.
