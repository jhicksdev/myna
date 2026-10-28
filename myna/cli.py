"""CLI for the Myna programming language (`myna compile`, `myna decompile`, `myna run`, `myna stats`)."""

from __future__ import annotations
import argparse
import os
import re
import subprocess
import sys
import tempfile
import types
import uuid
from pathlib import Path

from myna import (
    LANGUAGE_VERSION,
    DecompileError,
    LexError,
    ParseError,
    TargetError,
    __version__,
    myna_to_python,
    myna_to_js,
    parse,
    python_to_myna,
)
import myna.ast_nodes as ast
from myna.bundler import BundleError, bundle, bundle_zipapp
from myna.js_modules import collect_js_modules, write_js_tree
from myna.loader import compile_myna_source, install
from myna.modules import ModuleError
from myna.targets import expand_target_blocks


def count_tokens(text: str) -> tuple[int, str]:
    """Count LLM tokens using `tiktoken` (`o200k_base`) if installed, else a calibrated BPE estimator."""
    try:
        import tiktoken  # type: ignore
        enc = tiktoken.get_encoding("o200k_base")
        return len(enc.encode(text)), "tiktoken (o200k_base)"
    except Exception:
        # Calibrated BPE estimator matching o200k_base / cl100k_base behavior:
        # - Leading space merges with a following word or punctuation token (` word`, ` =`, ` +`)
        # - 4-space indentation chunks are 1 token each
        # - Common compound operator+punct sequences (`({`, `})`, `});`, `=[`, `={`, `=>`, `('`, `')`, `['`, `']`) are 1 token in BPE
        # In BPE tokenizers (o200k_base / cl100k_base):
        # - Common compound delimiter sequences (`({`, `})`, `});`, `=[`, `={`, `=>`, `===`, `!==`) are 1 token
        # - Identifier words split on underscores and camelCase/length (>4 chars)
        # In BPE tokenizers (o200k_base / cl100k_base), code tokens average ~3.6 chars/token,
        # while symbols/whitespace/subwords tokenize into compact pieces:
        raw_parts = re.findall(
            r"    |\n|[A-Za-z]+|_[A-Za-z]+|_|[0-9]+|\(\{|\}\)|\}\);|\}\}|\)\}|=\[|=\{|=>|===|!==|'\)|'\]|\"\}|'\}:|\(\(|'\],|\$\?|!\^|\^\*|\^\!|\^>|\)\)|;\^|;\.|`:|`,|;p\(|;\!\?|'GET'|'POST'|'DELETE'|[^\sA-Za-z0-9_]{1,2}| +",
            text,
        )
        total = 0
        for p in raw_parts:
            if p and p[0].isalpha() and len(p) > 3:
                camel_parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", p)
                for cp in camel_parts:
                    total += max(1, (len(cp) + 2) // 3)
            elif p.startswith("_") and len(p) > 2:
                total += 1 + max(1, (len(p) - 1 + 2) // 3)
            else:
                total += 1
        return total, "bpe-approx"


def cmd_compile(args: argparse.Namespace) -> int:
    src = Path(args.input).read_text(encoding="utf-8") if args.input != "-" else sys.stdin.read()
    target = args.target
    if target is None and args.output and str(args.output).endswith((".js", ".mjs")):
        target = "js"
    if target == "js":
        # Relative imports become specifiers for sibling output files, so the emitted
        # extension follows the output file (Node treats `.mjs` as an ES module).
        module_ext = ".mjs" if args.output and str(args.output).endswith(".mjs") else ".js"
        source_path = None if args.input == "-" else args.input
        code = myna_to_js(src, source_path=source_path, module_ext=module_ext)
    else:
        code = myna_to_python(src)
    if args.output:
        Path(args.output).write_text(code, encoding="utf-8")
    else:
        sys.stdout.write(code)
    return 0


def cmd_decompile(args: argparse.Namespace) -> int:
    src = Path(args.input).read_text(encoding="utf-8") if args.input != "-" else sys.stdin.read()
    myna_code = python_to_myna(src, compact=not args.pretty, minify_locals=args.minify_locals)
    if args.output:
        Path(args.output).write_text(myna_code, encoding="utf-8")
    else:
        sys.stdout.write(myna_code)
    return 0


def _module_root(args: argparse.Namespace) -> Path | None:
    """Resolve `--module-root` / `MYNA_MODULE_ROOT`, or None for the entry's directory."""
    raw = getattr(args, "module_root", None) or os.environ.get("MYNA_MODULE_ROOT")
    if not raw:
        return None
    root = Path(raw).expanduser()
    if not root.is_dir():
        raise ModuleError(f"module root is not a directory: {root}")
    return root.resolve()


def _relative_missing_message(
    package: str, exc: ImportError, root: Path
) -> str | None:
    """Turn a missing synthetic-package module into an actionable message."""
    name = exc.name or ""
    prefix = package + "."
    cannot_import = re.search(r"cannot import name '([^']+)' from", str(exc))
    if name.startswith(prefix) and cannot_import:
        # The module exists; one of its names does not (`from .util import missing`).
        relative = name[len(prefix) :]
        return (
            f"relative module '{relative}' has no name '{cannot_import.group(1)}' "
            f"(resolved under module root '{root}')"
        )
    if name.startswith(prefix):
        relative = name[len(prefix) :]
    elif name == package and cannot_import:
        # `from . import util`: the synthetic root package has no such submodule.
        relative = cannot_import.group(1)
    else:
        return None
    looked = root.joinpath(*relative.split("."))
    return (
        f"cannot resolve relative import: no module '{relative}' under module root "
        f"'{root}' (looked for {looked}.myna or {looked}/__init__.myna; pass "
        f"--module-root DIR or set MYNA_MODULE_ROOT)"
    )


def _run_python_entry(
    src_path: Path,
    src: str,
    script_args: list[str],
    module_root: Path | None = None,
) -> int:
    """Execute a Myna entry file with sibling `.myna` modules importable."""
    entry = src_path.resolve()
    root = module_root or entry.parent
    package = f"_myna_run_{uuid.uuid4().hex[:8]}"
    package_module = types.ModuleType(package)
    package_module.__path__ = [str(root)]
    package_module.__package__ = package
    package_module.__file__ = str(root)
    sys.modules[package] = package_module

    finder = install(package, root)
    try:
        py_code = compile_myna_source(src, entry)
        globs = {
            "__name__": "__main__",
            "__file__": str(entry),
            "__package__": package,
        }
        sys.argv = [str(src_path)] + list(script_args)
        try:
            exec(compile(py_code, str(src_path), "exec"), globs)
        except ImportError as exc:
            message = _relative_missing_message(package, exc, root)
            if message is None:
                raise
            raise ModuleError(message) from exc
    finally:
        sys.meta_path.remove(finder)
        for name in [n for n in sys.modules if n == package or n.startswith(package + ".")]:
            del sys.modules[name]
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    src_path = Path(args.input)
    module_root = _module_root(args)
    if args.target == "js":
        entry = src_path.resolve()
        with tempfile.TemporaryDirectory(prefix="myna-js-") as tmp:
            modules = collect_js_modules(
                entry, module_root=module_root, module_ext=".mjs"
            )
            entry_output = write_js_tree(
                modules, output_root=Path(tmp), module_ext=".mjs"
            )
            proc = subprocess.run(
                ["node", str(entry_output), *args.script_args], check=False
            )
            return proc.returncode

    src = src_path.read_text(encoding="utf-8")
    return _run_python_entry(src_path, src, list(args.script_args), module_root)


def cmd_bundle(args: argparse.Namespace) -> int:
    module_root = _module_root(args)
    if args.zipapp:
        result = bundle_zipapp(Path(args.input), module_root)
        output = Path(args.output) if args.output else Path(args.input).with_suffix(".pyz")
        output.write_bytes(result.data)
        try:
            output.chmod(output.stat().st_mode | 0o111)
        except OSError:
            pass
        print(
            f"myna: bundled {len(result.modules)} module(s) -> {output} (zipapp)",
            file=sys.stderr,
        )
        return 0

    result = bundle(Path(args.input), module_root)
    if args.output:
        Path(args.output).write_text(result.code, encoding="utf-8")
        print(f"myna: bundled {len(result.modules)} module(s) -> {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(result.code)
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    path = Path(args.input)
    raw = path.read_text(encoding="utf-8")
    if path.suffix == ".myna":
        myna_src = raw
        py_src = myna_to_python(raw)
        ultra_src = python_to_myna(py_src, compact=True, minify_locals=True)
    else:
        py_src = raw
        myna_src = python_to_myna(raw, compact=True, minify_locals=args.minify_locals)
        ultra_src = python_to_myna(raw, compact=True, minify_locals=True)

    py_toks, method = count_tokens(py_src)
    myna_toks, _ = count_tokens(myna_src)
    ultra_toks, _ = count_tokens(ultra_src)
    py_chars = len(py_src)
    myna_chars = len(myna_src)
    ultra_chars = len(ultra_src)

    tok_saving = (1.0 - (myna_toks / py_toks)) * 100 if py_toks else 0.0
    ultra_saving = (1.0 - (ultra_toks / py_toks)) * 100 if py_toks else 0.0
    char_saving = (1.0 - (myna_chars / py_chars)) * 100 if py_chars else 0.0
    ultra_char_saving = (1.0 - (ultra_chars / py_chars)) * 100 if py_chars else 0.0

    print(f"=== Myna Token Efficiency Report ({path.name}) ===")
    print(f"Tokenizer            : {method}")
    print(f"Python tokens        : {py_toks}")
    print(f"Myna tokens          : {myna_toks} ({tok_saving:.1f}% reduction)")
    print(f"Myna (ultra-compact) : {ultra_toks} ({ultra_saving:.1f}% reduction)")
    print(f"Python chars         : {py_chars}")
    print(f"Myna chars           : {myna_chars} ({char_saving:.1f}% reduction)")
    print(f"Myna (ultra) chars   : {ultra_chars} ({ultra_char_saving:.1f}% reduction)")
    if args.show:
        print("\n--- Myna Code ---")
        print(myna_src.rstrip())
        print("\n--- Python Code ---")
        print(py_src.rstrip())
    return 0


def cmd_targets(args: argparse.Namespace) -> int:
    src = Path(args.input).read_text(encoding="utf-8") if args.input != "-" else sys.stdin.read()
    source_path = None if args.input == "-" else args.input
    mod = parse(src)
    declared = ", ".join(sorted(mod.targets)) if mod.targets else "(none)"
    print(f"=== Target Report ({args.input}) ===")
    print(f"Declared : {declared}")

    for target, compile_fn in (("py", myna_to_python), ("js", myna_to_js)):
        try:
            if target == "js":
                compile_fn(src, source_path=source_path)
            else:
                compile_fn(src)
        except TargetError as exc:
            print(f"{target:<9}: unsupported — {exc}")
            continue
        except (LexError, ParseError, ValueError) as exc:
            print(f"{target:<9}: unsupported — {type(exc).__name__}: {exc}")
            continue

        imports = [
            alias.name
            for stmt in expand_target_blocks(mod, target).body
            for alias in (stmt.names if isinstance(stmt, (ast.ImportStmt, ast.ImportFromStmt)) else [])
        ]
        note = ""
        if target == "js":
            python_only = [name for name in imports if name.split(".")[0] in sys.stdlib_module_names]
            if python_only:
                note = f" — imports Python stdlib that Node cannot resolve: {', '.join(python_only)}"
        elif any(name.startswith("node:") for name in imports):
            note = " — imports Node-only modules"
        print(f"{target:<9}: supported (generation only){note}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="myna",
        description="Myna: Ultra-dense AI-friendly language that transpiles to/from Python",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"myna {__version__} (language {LANGUAGE_VERSION})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_comp = sub.add_parser("compile", aliases=["c", "myna2py", "myna2js"], help="Compile Myna (.myna) to Python (.py) or JavaScript (.js)")
    p_comp.add_argument("input", help="Input .myna file (or '-' for stdin)")
    p_comp.add_argument("-o", "--output", help="Output .py or .js file (default: stdout)")
    p_comp.add_argument("-t", "--target", choices=["py", "js"], default=None, help="Target language: 'py' (default) or 'js'")
    p_comp.set_defaults(func=cmd_compile)

    p_dec = sub.add_parser("decompile", aliases=["d", "py2myna"], help="Compress Python (.py) to Myna (.myna)")
    p_dec.add_argument("input", help="Input .py file (or '-' for stdin)")
    p_dec.add_argument("-o", "--output", help="Output .myna file (default: stdout)")
    p_dec.add_argument("--pretty", action="store_true", help="Emit indented multi-line Myna instead of ultra-compact")
    p_dec.add_argument("-m", "--minify-locals", action="store_true", help="Shorten function-local variable names to 1-char tokens")
    p_dec.set_defaults(func=cmd_decompile)

    p_bundle = sub.add_parser("bundle", aliases=["b"], help="Bundle a multi-file Myna program into one standalone Python file")
    p_bundle.add_argument("input", help="Entry .myna file")
    p_bundle.add_argument("-o", "--output", help="Output path (default: stdout, or <input>.pyz with --zipapp)")
    p_bundle.add_argument("--zipapp", action="store_true", help="Write a runnable .pyz zipapp instead of a single .py script")
    p_bundle.add_argument(
        "--module-root",
        metavar="DIR",
        help="Root that the entry's relative imports resolve from (default: the entry file's "
        "directory, or $MYNA_MODULE_ROOT)",
    )
    p_bundle.set_defaults(func=cmd_bundle)

    p_run = sub.add_parser("run", aliases=["r"], help="Compile and execute a .myna file directly (via Python or Node.js)")
    p_run.add_argument("input", help="Input .myna file to run")
    p_run.add_argument("-t", "--target", choices=["py", "js"], default="py", help="Runtime target: 'py' (default) or 'js' (Node.js)")
    p_run.add_argument(
        "--module-root",
        metavar="DIR",
        help="Root that relative imports resolve from (default: the entry file's directory, "
        "or $MYNA_MODULE_ROOT)",
    )
    p_run.add_argument("script_args", nargs=argparse.REMAINDER, help="Arguments passed to the script")
    p_run.set_defaults(func=cmd_run)

    p_targets = sub.add_parser("targets", aliases=["t"], help="Report which targets a .myna file declares/supports")
    p_targets.add_argument("input", help="Input .myna file (or '-' for stdin)")
    p_targets.set_defaults(func=cmd_targets)

    p_stats = sub.add_parser("stats", aliases=["s"], help="Compare token & character efficiency between Python and Myna")
    p_stats.add_argument("input", help="Input .py or .myna file")
    p_stats.add_argument("-m", "--minify-locals", action="store_true", help="Include local variable minification in default Myna output")
    p_stats.add_argument("--show", action="store_true", help="Print both Myna and Python representations")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (LexError, ParseError, DecompileError, TargetError, BundleError, ModuleError, OSError) as exc:
        print(f"myna: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
