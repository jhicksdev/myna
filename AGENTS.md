# AGENTS.md

Myna (package `myna-lang`) is a dense, brace-delimited language that transpiles to/from Python and to JavaScript. Syntax is documented in `SPEC.md` and `skills/myna/SKILL.md`; read one before editing any `.myna` file or language behavior.

## Commands

```bash
python3 -m unittest discover -s tests -v             # full suite
python3 -m unittest discover -s tests -p "test_js.py" -v
python3 -m unittest tests.test_myna.TestMynaTranspiler.test_operators_pipe_and_shorthands
python3 -m myna run examples/demo.myna                # smoke-test the CLI + examples
python3 -m myna stats examples/demo.myna
```

- Run from the repo root (imports are absolute `myna.*`) or `pip install -e .`. Python >= 3.11; no runtime dependencies.
- `tests/test_js.py` shells out to `node` and skips when Node is not on `PATH`.
- No lint, format, typecheck, or CI config is checked in; unittest is the only verification gate. `.ruff_cache/` is a local artifact, not a configured tool.
- CLI aliases: `compile`/`c`/`myna2py`/`myna2js`, `decompile`/`d`/`py2myna`, `run`/`r`, `stats`/`s`. Output extension `.js`/`.mjs` selects the JS target only when `-t` is omitted.

## Architecture

- Myna -> target: `lexer.py` (tokens) -> `parser.py` (recursive descent + Pratt) -> `ast_nodes.py` -> `backends/python_gen.py` or `backends/js_gen.py`.
- Python -> Myna: `frontends/python_decompile.py` uses Python's stdlib `ast`; it does not go through the Myna lexer/parser. `test_roundtrip_py_to_myna_to_py` and `test_roundtrip_corpus.py` are the contract.
- Adding a construct means touching lexer + parser + both backends. Each generator raises `ValueError("Unsupported ... node")` for unhandled AST nodes, so JS/Python parity gaps surface only when exercised.
- Public API is re-exported from `myna/__init__.py`; CLI wiring is in `myna/cli.py`.

## Language-change checklist

- Tests execute generated code and assert semantics, not emitted text. `test_js.py` compiles the same source for Python and Node and compares stdout.
- Syntax is duplicated in three docs that must stay consistent: the README cheat sheet, `SPEC.md`, and `skills/myna/SKILL.md`.
- `examples/*.myna` double as `myna stats` fixtures; keep them compilable.
- The version is duplicated in `pyproject.toml` and `myna/__init__.py`; bump both together.

## Gotchas

- `myna stats` soft-imports `tiktoken` and otherwise uses a calibrated `bpe-approx` estimator. The README benchmark numbers match the `bpe-approx` fallback, so installing `tiktoken` changes reported counts; `tiktoken` is not a declared dependency.
- `myna run` for Python execs the compiled code in-process with `__name__ == "__main__"`, so top-level `@main` blocks run.
- Don't add runtime dependencies casually; the project advertises zero deps and optional `tiktoken` only soft-imports.
