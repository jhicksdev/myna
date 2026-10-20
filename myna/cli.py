"""CLI for the Myna programming language (`myna compile`, `myna decompile`, `myna run`, `myna stats`)."""

from __future__ import annotations
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from myna import myna_to_python, myna_to_js, python_to_myna


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
    code = myna_to_js(src) if target == "js" else myna_to_python(src)
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


def cmd_run(args: argparse.Namespace) -> int:
    src_path = Path(args.input)
    src = src_path.read_text(encoding="utf-8")
    if args.target == "js":
        js_code = myna_to_js(src)
        with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False, encoding="utf-8") as tmp:
            tmp.write(js_code)
            tmp_path = tmp.name
        try:
            proc = subprocess.run(["node", tmp_path, *args.script_args], check=False)
            return proc.returncode
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    py_code = myna_to_python(src)
    globs = {
        "__name__": "__main__",
        "__file__": str(src_path.resolve()),
    }
    sys.argv = [str(src_path)] + list(args.script_args)
    exec(compile(py_code, str(src_path), "exec"), globs)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="myna",
        description="Myna: Ultra-dense AI-friendly language that transpiles to/from Python",
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

    p_run = sub.add_parser("run", aliases=["r"], help="Compile and execute a .myna file directly (via Python or Node.js)")
    p_run.add_argument("input", help="Input .myna file to run")
    p_run.add_argument("-t", "--target", choices=["py", "js"], default="py", help="Runtime target: 'py' (default) or 'js' (Node.js)")
    p_run.add_argument("script_args", nargs=argparse.REMAINDER, help="Arguments passed to the script")
    p_run.set_defaults(func=cmd_run)

    p_stats = sub.add_parser("stats", aliases=["s"], help="Compare token & character efficiency between Python and Myna")
    p_stats.add_argument("input", help="Input .py or .myna file")
    p_stats.add_argument("-m", "--minify-locals", action="store_true", help="Include local variable minification in default Myna output")
    p_stats.add_argument("--show", action="store_true", help="Print both Myna and Python representations")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
