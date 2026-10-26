# Versioning Policy

This document is the contract for how Myna is versioned and released. It covers the
`myna-lang` distribution, the Myna language itself, the CLI, and the public Python API.
When a change is ambiguous, this document decides the bump; when it is silent, open an
issue rather than guessing.

Design decisions that constrain releases (normative semantics, target scope) are
recorded in [`DECISIONS.md`](DECISIONS.md).

---

## 1. One version, three surfaces

| Surface | Format | Rule |
| :--- | :--- | :--- |
| **Package** (`myna-lang` on PyPI) | `X.Y.Z` | Authoritative version. Everything else derives from it. |
| **Language** (syntax and semantics) | `X.Y` | Equals the package `major.minor`. Patch releases never change the language. |
| **Spec** (`SPEC.md`) | `X.Y` | Must equal the language version whenever syntax or semantics change. |

- `myna --version` must print the package version and the language version, so a bug
  report always identifies both.
- The CLI and the public Python API follow the package version.

---

## 2. Semantic versioning for 0.x

While the major version is `0`, `0.z` takes the role of a major version.

| Bump | Meaning |
| :--- | :--- |
| **Patch** `0.y.z` (`z > 0`) | Fixes only. No new syntax, no new CLI surface, no API changes, no changed defaults, no intentional behavior changes. |
| **Minor** `0.y.0` | Additions, intentional behavior changes, deprecations, and (pre-1.0 only) breaking changes. |
| **Major** `1.0.0` | The 1.0 contract: frozen syntax and API, plus the guarantees in §7. |

### What qualifies as a patch

Allowed in a patch:

- Fixing **incorrect generated output** — a construct that compiled but ran wrongly.
- Fixing crashes, tracebacks, and diagnostics.
- Fixing documentation, metadata, packaging, tests, and CI.
- Release hygiene that exposes existing facts: adding `--version`, single-sourcing the
  version, correcting classifiers.
- Internal refactors that do not change observable behavior.

**The size of a fix is irrelevant.** A correctness fix may reasonably touch the lexer,
both backends, and the test suite; it is still a patch, because the previous output was
wrong. "It's a big diff" is not a reason to burn a minor version.

### What forces a minor

- A new construct, operator, literal form, or shorthand.
- A new CLI subcommand, alias, or functional flag (`--version`, which only reports
  existing metadata, is `Metadata`).
- A new target capability, or a change to which constructs a target supports.
- Any public API addition, removal, or signature change.
- Any changed default (for example, the `@target` default in `DECISIONS.md` D-003).
- An intentional change to how previously-correct programs behave.
- A deprecation announcement, or a removal.

### Breaking changes

- **Before 1.0:** allowed only in a minor release. They must appear under `Changed` or
  `Removed` in `CHANGELOG.md`, include a migration note, and — when the construct has
  shipped in a release — be deprecated for at least one minor before removal.
- **After 1.0:** removals happen only in a major release, after a deprecation in a minor.
- Breaking changes are **never** shipped in a patch, however small.

### The correctness exception

Changing generated output is a patch **only when the previous output was wrong**. If the
old behavior was intentional and you are changing the design, that is a minor. The test
is "would a user who wrote this program yesterday see different results?", not "did the
diff touch code generation?".

---

## 3. Changelog contract

`CHANGELOG.md` uses [Keep a Changelog](https://keepachangelog.com/) headings:

- `Added` — new capability.
- `Changed` — intentional behavior change.
- `Deprecated` — still works, will be removed.
- `Removed` — no longer available.
- `Fixed` — a bug fix.
- `Security` — vulnerability fix.
- `Documentation` — documentation-only change (a small extension to Keep a Changelog,
  used so policy and guide updates are recorded without pretending to be features).
- `Metadata` — release hygiene that exposes existing facts rather than adding a
  capability: `--version` reporting, package metadata/classifier corrections, and
  version single-sourcing. A new *functional* flag or command is `Added`, not
  `Metadata`.

Rules:

1. `main` always carries an `## Unreleased` section.
2. Every user-visible change gets an entry written as **user impact**, not as a commit
   message. "JS: `d$?k` no longer emits `d.get(k)`" beats "fix js_gen".
3. Language changes link to the affected `SPEC.md` section.
4. Internal-only changes (tests, CI, refactors) are omitted; they do not need an entry.
5. Cutting a release moves `Unreleased` entries under `## X.Y.Z (YYYY-MM-DD)`.
6. **The categories decide the bump mechanically:** any `Added`, `Changed`, `Deprecated`,
   or `Removed` entry means a minor; only `Fixed`, `Security`, `Documentation`, and
   `Metadata` entries mean a patch.

---

## 4. Single source of truth

The version must live in exactly one place.

- `myna/__init__.py:__version__` is authoritative; `pyproject.toml` reads it
  dynamically via `[tool.setuptools.dynamic]`. Never add a literal version to
  `pyproject.toml`.
- Never hardcode a version in documentation, examples, tests, or generated code.
  Refer to "the current release" instead.
- Do not confuse the distribution name (`myna-lang`) with the import name (`myna`).

---

## 5. Release procedure

1. Start from a clean tree on `main`; a release is never cut from a dirty working copy.
2. Update `CHANGELOG.md`: move `Unreleased` entries under the new version and date.
3. Decide the bump using §3, then apply it in the single source from §4.
4. If syntax or semantics changed, update the language version and the relevant text in
   `SPEC.md` in the same commit.
5. Run the full suite from the repository root:
   `python3 -m unittest discover -s tests -v`. Node must be available — do not accept a
   run where the JavaScript tests were skipped.
6. Build the sdist and wheel, install the wheel in a clean virtual environment, and
   smoke-test it: `myna --version`, `myna run` on an example, `myna compile -t js` on an
   example.
7. Tag `vX.Y.Z` and publish through `.github/workflows/publish.yml` (PyPI trusted
   publishing).
8. Verify the published artifact: `pip install myna-lang==X.Y.Z` and confirm the version
   reported by the package and by `myna --version`.
9. If a bad artifact ships, **yank** that version on PyPI. Never re-upload different
   bytes under the same version.

---

## 6. Language and generated-code compatibility

- `SPEC.md` states the language version. A backend-only bug fix does not change it.
- Generated-code requirements (Python version, JavaScript edition) are part of the
  language contract: raising the Python floor or changing the JS target is a **minor**,
  never a patch.
- The supported runtime matrix and the current Python floor are recorded in the
  `README.md` and in `SPEC.md`; this document only defines how changes to them are
  versioned.

---

## 7. The 1.0 gate

`1.0.0` is a **major** bump even if it adds no syntax: it is a promise about stability.

It may only be released when all of the following hold:

1. A `0.9.x` line has shipped as a stabilization cycle with patch releases only, and no
   known silent miscompile remains open.
2. The conformance matrix is green for both targets — including JavaScript execution,
   not just code generation.
3. The JavaScript Portable Core is documented, and unsupported constructs are rejected
   at compile time rather than approximated (`DECISIONS.md` D-001, D-002).
4. The syntax and the public Python API are frozen, and the deprecation policy in §2 is
   in force.
5. `SPEC.md` is normative, complete, and version-aligned; it no longer refers to older
   versions.
6. Versioning is single-sourced, the changelog is complete, and the release procedure in
   §5 has been executed at least once end to end.
7. There is no known correctness bug that produces wrong output without an error.

Until then, the honest label is `0.y.z`.

---

## 8. Worked examples

| Change | Category | Bump |
| :--- | :--- | :--- |
| JS drops `else` branches from `try` / loops | `Fixed` | **patch** |
| `d$?k` emits a non-existent `.get()` in JS | `Fixed` | **patch** |
| Add `myna fmt` | `Added` | **minor** |
| Add `myna check` | `Added` | **minor** |
| Add `myna --version` (reports existing versions) | `Metadata` | **patch** |
| Add a `--strict` flag that changes compilation | `Added` | **minor** |
| Fix a typo in `README.md` | `Documentation` | **patch** |
| Write the release policy (`VERSIONING.md`) | `Documentation` | **patch** |
| Flip the `@target` default to `py`-only (D-003) | `Changed` | **minor**, with deprecation |
| Remove `===` from the language | `Removed` | **minor** |
| Emit `BigInt` for JS integers | `Changed` | **minor** (not a fix) |
| Raise the generated-Python floor from 3.11 to 3.12 | `Changed` | **minor** |
| Speed up the parser without changing output | — | **patch** |

---

## 9. Enforcement

- `AGENTS.md` points contributors and agents at this document.
- A pull request that changes behavior must state the intended bump and the reason.
- A release that skips a step in §5 is a defect in the release, not in the code.
- If a change does not fit a category, that is a signal to split the change — not to
  pick a bump and move on.

---

## Adoption status (0.4.x)

- This policy is adopted as of 0.4.0 (2026-10-26).
- 0.4.1 single-sources the version in `myna/__init__.py`; `pyproject.toml` reads it
  dynamically (§4).
- 0.4.1 adds `myna --version`, reporting the package and language versions (§1).
- 0.4.1 adds a pull-request CI matrix (Python 3.11–3.13 × Node 20/22/24) and runs the
  suite on every push and pull request.
