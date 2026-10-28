# AGENTS.md

Myna (package `myna-lang`) is a dense, brace-delimited language that transpiles to/from Python and to JavaScript. Syntax is documented in `SPEC.md` and `skills/myna/SKILL.md`; read one before editing any `.myna` file or language behavior.

`VERSIONING.md` defines how releases are numbered; `DECISIONS.md` records the accepted semantics and target-scope decisions. Read both before changing observable behavior.

## Commands

```bash
python3 -m unittest discover -s tests -v             # full suite
python3 -m unittest discover -s tests -p "test_js.py" -v
python3 -m unittest tests.test_myna.TestMynaTranspiler.test_operators_pipe_and_shorthands
python3 -m myna run examples/demo.myna                # smoke-test the CLI + examples
python3 -m myna stats examples/demo.myna
```

- Run from the repo root (imports are absolute `myna.*`) or `pip install -e .`. Python >= 3.11 for the CLI; generated Python is 3.12+ when the source uses `$=` (it emits a `type` statement). No runtime dependencies.
- `tests/test_js.py` shells out to `node` and skips when Node is not on `PATH`; CI runs it on Node 20/22/24, so do not accept a local run where it skipped.
- No lint, format, or typecheck config is checked in; unittest is the verification gate and `.github/workflows/test.yml` runs it on every PR. `.ruff_cache/` is a local artifact, not a configured tool.
- CLI aliases: `compile`/`c`/`myna2py`/`myna2js`, `decompile`/`d`/`py2myna`, `run`/`r`, `stats`/`s`. Output extension `.js`/`.mjs` selects the JS target only when `-t` is omitted.

## Architecture

- Myna -> target: `lexer.py` (tokens) -> `parser.py` (recursive descent + Pratt) -> `ast_nodes.py` -> `backends/python_gen.py` or `backends/js_gen.py`.
- `myna run` for the Python target installs `myna/loader.py`, a scoped import hook that resolves relative imports to sibling `.myna` modules; `--module-root DIR` / `MYNA_MODULE_ROOT` changes the entry file's import base. `myna compile` does not bundle imports.
- Relative imports are supported for `-t js` as multi-file ES modules: `myna/backends/js_gen.py` resolves them through `myna/modules.py` and emits `./name.js`/`./name.mjs` specifiers plus a trailing export list, and `myna/js_modules.py` compiles the graph for `myna run -t js` (D-005). `myna bundle` remains Python-only.
- `myna bundle` (`bundler.py`) compiles the relative-import graph into one standalone Python file with embedded module sources, or a reproducible `.pyz` zipapp with real module files.
- Python -> Myna: `frontends/python_decompile.py` uses Python's stdlib `ast`; it does not go through the Myna lexer/parser. `test_roundtrip_py_to_myna_to_py` and `test_roundtrip_corpus.py` are the contract.
- Adding a construct means touching lexer + parser + both backends. Each generator raises `ValueError("Unsupported ... node")` for unhandled AST nodes, so JS/Python parity gaps surface only when exercised.
- Target support: `targets.py` enforces module-level `@target(...)` contracts and expands `@target(...) { ... }` blocks before either backend generates code.
- Public API is re-exported from `myna/__init__.py`; CLI wiring is in `myna/cli.py`.

## Language-change checklist

- Tests execute generated code and assert semantics, not emitted text. `test_js.py` compiles the same source for Python and Node, runs `node --check` on the generated file, executes both, and compares stdout. New constructs need a cross-target case there or an explicit `TargetError` test in `test_myna.py`.
- Syntax is duplicated in three docs that must stay consistent: the README cheat sheet, `SPEC.md`, and `skills/myna/SKILL.md`.
- `examples/*.myna` double as `myna stats` fixtures; keep them compilable.
- Version bumps follow `VERSIONING.md` §2–§3: classify the change in `CHANGELOG.md` first, then apply the bump the categories imply. The version lives in `myna/__init__.py:__version__`; `pyproject.toml` reads it dynamically, so never edit a literal version there.
- Target blocks are module-level only; imports inside them are emitted at module top level.

## Gotchas

- `myna stats` soft-imports `tiktoken` and otherwise uses a calibrated `bpe-approx` estimator. The README benchmark numbers match the `bpe-approx` fallback, so installing `tiktoken` changes reported counts; `tiktoken` is not a declared dependency.
- `myna targets` reports whether code *generates*, not whether it *runs*. The JS backend emulates Python semantics through inlined `__myna_*` helpers and rejects unemulable constructs (multiple inheritance, class/method decorators, star imports, some builtins) with `TargetError`. Remaining known limits: JS has one number type (no int/float or >2^53 integers), tuples and lists are both arrays, `with` is approximated, keyword arguments to user functions become a trailing object, and f-string format specs beyond `.Nf` are not translated. D-001/D-002/D-005 in `DECISIONS.md` define the target contract.
- `myna run` for Python execs the compiled code in-process with `__name__ == "__main__"`, so top-level `@main` blocks run.
- Don't add runtime dependencies casually; the project advertises zero deps and optional `tiktoken` only soft-imports.
