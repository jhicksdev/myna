"""Comprehensive test suite for the Myna programming language."""

from __future__ import annotations
import asyncio
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
import zipfile

import myna
from myna import (
    DecompileError,
    LexError,
    ParseError,
    TargetError,
    myna_to_js,
    myna_to_python,
    myna_to_ts,
    python_to_myna,
)


class TestMynaTranspiler(unittest.TestCase):
    def exec_myna(self, myna_src: str) -> dict:
        py_code = myna_to_python(myna_src)
        ns: dict = {}
        exec(py_code, ns)
        return ns

    def test_literals_and_types(self):
        src = """
        a: i = 42
        b: f = 3.14
        c: s = "hello"
        d: b = T
        e: b = F
        n: s? = N
        r = _"raw\\nstring"
        by = 0b"abc"
        msg = `a={a}, b={b:.1f}`
        """
        ns = self.exec_myna(src)
        self.assertEqual(ns["a"], 42)
        self.assertAlmostEqual(ns["b"], 3.14)
        self.assertEqual(ns["c"], "hello")
        self.assertIs(ns["d"], True)
        self.assertIs(ns["e"], False)
        self.assertIsNone(ns["n"])
        self.assertEqual(ns["r"], r"raw\nstring")
        self.assertEqual(ns["by"], b"abc")
        self.assertEqual(ns["msg"], "a=42, b=3.1")

    def test_functions_and_lambdas(self):
        src = """
        @add(x:i, y:i=10)->i {
            ^ x + y
        }
        inc = x => x + 1
        mul = (a, b) => a * b
        res1 = add(5)
        res2 = add(5, 7)
        res3 = inc(res1)
        res4 = mul(3, 4)
        """
        ns = self.exec_myna(src)
        self.assertEqual(ns["res1"], 15)
        self.assertEqual(ns["res2"], 12)
        self.assertEqual(ns["res3"], 16)
        self.assertEqual(ns["res4"], 12)

    def test_classes_and_dataclasses(self):
        src = """
        $$User(id:i, name:s, email:s?=N) {
            @display->s {
                ? .email !== N {
                    ^ `{.name} <{.email}>`
                }
                ^ .name
            }
        }

        $Admin < User {
            @init(id:i, name:s, role:s="super") {
                ..init(id, name, N)
                .role = role
            }
            @?badge->s {
                ^ `[.role] {.name}`
            }
            @/version->i {
                ^ 1
            }
        }

        u1 = User(1, "Alice", "a@b.c")
        u2 = User(2, "Bob")
        adm = Admin(3, "Carol", "root")
        d1 = u1.display()
        d2 = u2.display()
        b_str = adm.badge
        ver = Admin.version()
        """
        ns = self.exec_myna(src)
        self.assertEqual(ns["d1"], "Alice <a@b.c>")
        self.assertEqual(ns["d2"], "Bob")
        self.assertEqual(ns["b_str"], "[.role] Carol")
        self.assertEqual(ns["ver"], 1)

    def test_decorators_scope_del_and_exports(self):
        src = """
        count = 0

        @dec(fn) {
            @wrap(*args, **kwargs) {
                ^ fn(*args, **kwargs) + 100
            }
            ^ wrap
        }

        #[dec]
        +@bump(x:i)->i {
            @= count
            count += x
            ^ count
        }

        @outer(start:i)->i {
            acc = start
            @inner(d:i) {
                ^= acc
                acc += d
            }
            inner(5)
            inner(7)
            ^ acc
        }

        d = {"a": 1, "b": 2, "c": 3}
        ~d["b"]

        r_bump = bump(10)
        r_outer = outer(3)
        """
        ns = self.exec_myna(src)
        self.assertEqual(ns["r_bump"], 110)
        self.assertEqual(ns["count"], 10)
        self.assertEqual(ns["r_outer"], 15)
        self.assertEqual(ns["d"], {"a": 1, "c": 3})
        self.assertEqual(ns["__all__"], ["bump"])

    def test_nested_comprehensions_and_dict_spread(self):
        src = """
        pairs = [(x, y) | x <- 0..3 % y <- 0..3 ? x != y]
        base = {"a": 1, "b": 2}
        merged = {**base, "b": 20, "c": 30}
        """
        ns = self.exec_myna(src)
        self.assertEqual(ns["pairs"], [(0, 1), (0, 2), (1, 0), (1, 2), (2, 0), (2, 1)])
        self.assertEqual(ns["merged"], {"a": 1, "b": 20, "c": 30})

    def test_high_density_shorthands(self):
        src = """
        $$Point(x:i, y:i) {
            @to_dict->{s:i} => {.x, .y}
        }
        @make_item(name:s, count:i=1)->{s:A} => {=name, count, ok: T, ["dyn_" + name]: count * 2}
        @send(code:i, payload:{s:A}) => (code, payload)

        pt = Point(3, 4)
        d_pt = pt.to_dict()
        item = make_item("box", 5)
        k_ok = item$ok
        k_missing = item$?missing ?? "default_val"
        sent_code, sent_body = send(200, status: "ok", total: 42)
        encoded = @u8(@J({a: 1}))
        decoded = @j(@u8d(encoded))
        """
        ns = self.exec_myna(src)
        self.assertEqual(ns["d_pt"], {"x": 3, "y": 4})
        self.assertEqual(ns["item"], {"name": "box", "count": 5, "ok": True, "dyn_box": 10})
        self.assertIs(ns["k_ok"], True)
        self.assertEqual(ns["k_missing"], "default_val")
        self.assertEqual(ns["sent_code"], 200)
        self.assertEqual(ns["sent_body"], {"status": "ok", "total": 42})
        self.assertEqual(ns["decoded"], {"a": 1})

    def test_definition_sigils_after_infix_operators(self):
        src = """
        x = 1 + @max(2, 3)
        y = 2*@max(3, 4)
        z = 1+@max(5, 6)

        +@exported(a:i)->i => a + 1
        """
        ns = self.exec_myna(src)
        self.assertEqual(ns["x"], 4)
        self.assertEqual(ns["y"], 8)
        self.assertEqual(ns["z"], 7)
        self.assertEqual(ns["__all__"], ["exported"])

    def test_tuple_condition_with_arrow_body(self):
        src = """
        @shrink(token, first, second) {
            count = 2
            ? token <- (first, second) => count -= 1
            ^ count
        }

        @kind(value) {
            ? value :? (str, bytes) => ^ "text"
            ^ "other"
        }

        shrunk = shrink("x", "x", "y")
        untouched = shrink("z", "x", "y")
        text = kind("hi")
        other = kind(1)
        """
        ns = self.exec_myna(src)
        self.assertEqual(ns["shrunk"], 1)
        self.assertEqual(ns["untouched"], 2)
        self.assertEqual(ns["text"], "text")
        self.assertEqual(ns["other"], "other")

    def test_fstring_subexpression_error_reports_source_line(self):
        src = "@f {\n  x = 1\n  ^`value={x.}`\n}"
        with self.assertRaises(ParseError) as ctx:
            myna_to_python(src)
        self.assertEqual(ctx.exception.token.line, 3)

    def test_fstring_quoting_avoids_python_312_only_syntax(self):
        src = """
        d = {"it's": 7}
        quoted = `v={d["it's"]}`
        mixed = `both " and ' in {d["it's"]}`
        escaped = `[{'x\\ny'}]`
        """
        ns = self.exec_myna(src)
        self.assertEqual(ns["quoted"], "v=7")
        self.assertEqual(ns["mixed"], "both \" and ' in 7")
        self.assertEqual(ns["escaped"], "[x\ny]")

    def test_control_flow_and_loops(self):
        src = """
        @classify(x:i)->s {
            ? x < 0 { ^ "neg" }
            :? x == 0 { ^ "zero" }
            : { ^ "pos" }
        }

        total = 0
        % i <- 0..10..2 {
            ? i == 6 { ^> }
            total += i
        }

        w = 1
        %? w < 20 {
            w *= 2
            ? w > 10 { ^! }
        }

        c_neg = classify(-5)
        c_zero = classify(0)
        c_pos = classify(8)
        """
        ns = self.exec_myna(src)
        self.assertEqual(ns["c_neg"], "neg")
        self.assertEqual(ns["c_zero"], "zero")
        self.assertEqual(ns["c_pos"], "pos")
        self.assertEqual(ns["total"], 0 + 2 + 4 + 8)
        self.assertEqual(ns["w"], 16)

    def test_pattern_matching(self):
        src = """
        @describe(val)->s {
            ?? val {
                0 => { ^ "zero" }
                x ? x > 100 => { ^ `large:{x}` }
                _ => { ^ "other" }
            }
        }
        r0 = describe(0)
        r1 = describe(250)
        r2 = describe(42)
        """
        ns = self.exec_myna(src)
        self.assertEqual(ns["r0"], "zero")
        self.assertEqual(ns["r1"], "large:250")
        self.assertEqual(ns["r2"], "other")

    def test_comprehensions_and_generators(self):
        src = """
        squares = [x**2 | x <- 0..6 ? x % 2 == 0]
        lookup = {x: x*10 | x <- 1..4}
        uniq = {x % 3 | x <- 0..9}
        gen_sum = @sum(x + 1 | x <- 0..5)

        *@fib(n:i) {
            a, b = 0, 1
            % _ <- ..n {
                ^* a
                a, b = b, a + b
            }
        }
        fib_list = @list(fib(6))
        """
        ns = self.exec_myna(src)
        self.assertEqual(ns["squares"], [0, 4, 16])
        self.assertEqual(ns["lookup"], {1: 10, 2: 20, 3: 30})
        self.assertEqual(ns["uniq"], {0, 1, 2})
        self.assertEqual(ns["gen_sum"], sum(x + 1 for x in range(5)))
        self.assertEqual(ns["fib_list"], [0, 1, 1, 2, 3, 5])

    def test_exceptions_and_with(self):
        src = """
        <contextlib:{nullcontext}

        @safe_div(a, b) {
            !{
                !? b != 0, "div by zero"
                ^ a / b
            } !! e:AssertionError {
                ^ -1
            } !: {
                _
            }
        }

        !& v = nullcontext(99) {
            ctx_val = v
        }

        ok = safe_div(10, 2)
        fail = safe_div(10, 0)
        """
        ns = self.exec_myna(src)
        self.assertEqual(ns["ok"], 5.0)
        self.assertEqual(ns["fail"], -1)
        self.assertEqual(ns["ctx_val"], 99)

    def test_operators_pipe_and_shorthands(self):
        src = """
        @double(x) { ^ x * 2 }
        @add_n(x, n) { ^ x + n }

        piped = 5 |> double |> add_n(3)
        arr = [10, 20, 30, 40]
        n_len = #arr
        sliced = arr[1:3]
        is_int = 42 :? i
        has_20 = 20 <- arr
        not_99 = 99 !<- arr
        coal = N ?? "fallback"
        tern = 5 > 3 ? "yes" : "no"
        bit_inv = ~|0
        """
        ns = self.exec_myna(src)
        self.assertEqual(ns["piped"], 13)
        self.assertEqual(ns["n_len"], 4)
        self.assertEqual(ns["sliced"], [20, 30])
        self.assertTrue(ns["is_int"])
        self.assertTrue(ns["has_20"])
        self.assertTrue(ns["not_99"])
        self.assertEqual(ns["coal"], "fallback")
        self.assertEqual(ns["tern"], "yes")
        self.assertEqual(ns["bit_inv"], ~0)

    def test_isinstance_compound_types(self):
        src = """
        $Box {
            @init(x:i) { .x = x }
        }
        lst = [1, 2]
        d = {a: 1}
        st = {1, 2}
        nested = [[1]]
        box = Box(3)
        lst_ok = lst :? [i]
        dict_ok = d :? {s:i}
        set_ok = st :? {i}
        nested_ok = nested :? [[i]]
        generic_ok = box :? Box[i]
        list_matches_dict = lst :? {s:i}
        int_matches_list = 5 :? [i]
        primitive_union = 5 :? (i, s)
        single_ok = 5 :? i
        """
        ns = self.exec_myna(src)
        self.assertTrue(ns["lst_ok"])
        self.assertTrue(ns["dict_ok"])
        self.assertTrue(ns["set_ok"])
        self.assertTrue(ns["nested_ok"])
        self.assertTrue(ns["generic_ok"])
        self.assertFalse(ns["list_matches_dict"])
        self.assertFalse(ns["int_matches_list"])
        self.assertTrue(ns["primitive_union"])
        self.assertTrue(ns["single_ok"])

    def test_async_functions(self):
        src = """
        <asyncio

        ~@fetch_val(x:i)->i {
            ~asyncio.sleep(0.001)
            ^ x * 3
        }
        """
        ns = self.exec_myna(src)
        res = asyncio.run(ns["fetch_val"](7))
        self.assertEqual(res, 21)

    def test_auto_imports_follow_docstring_and_future(self):
        src = '"""Module docs."""\n<__future__:annotations\n$$P(x:i)\n'
        ns: dict = {}
        exec(compile(myna_to_python(src), "<auto-imports>", "exec"), ns)
        point = ns["P"](3)
        self.assertEqual(point.x, 3)
        self.assertEqual(ns["__doc__"], "Module docs.")

    def test_target_module_declaration(self):
        py_only = '@target(py)\n<math\nvalue=math.pi\n'
        ns = self.exec_myna(py_only)
        self.assertAlmostEqual(ns["value"], 3.141592653589793)
        with self.assertRaises(TargetError):
            myna_to_js(py_only)

        # D-003: no declaration means Python-only; portability is opt-in.
        implicit = "value=1\n"
        self.assertIn("value = 1", myna_to_python(implicit))
        with self.assertRaises(TargetError):
            myna_to_js(implicit)

        portable = '@target(py, js)\n"""doc"""\nvalue=1\n'
        self.assertIn("value = 1", myna_to_python(portable))
        self.assertIn("let value = 1;", myna_to_js(portable))

    def test_target_blocks_select_code_and_imports(self):
        src = """
        @target(py) {
            <math
            @platform()->s => `py:{math.pi:.2f}`
        }

        @target(js) {
            @platform()->s => `js:{Math.PI:.2f}`
            @only_js()->i => 1
        }
        """
        ns = self.exec_myna(src)
        self.assertEqual(ns["platform"](), "py:3.14")
        self.assertNotIn("only_js", ns)

        # A target block does not opt the module into portability (D-003).
        with self.assertRaises(TargetError):
            myna_to_js(src)

    def test_target_syntax_errors(self):
        invalid = [
            "@target(rust)\nvalue=1\n",
            "@target()\nvalue=1\n",
            "@target(py)\n@target(js)\nvalue=1\n",
            "value=1\n@target(py)\n",
            "@f { @target(py) { _ } }\n",
        ]
        for src in invalid:
            with self.subTest(src=src):
                with self.assertRaises(ParseError):
                    myna_to_python(src)

    def test_definition_sigils_after_inline_block(self):
        ns = self.exec_myna("@f { _ } +@b()=>2\n")
        self.assertEqual(ns["__all__"], ["b"])
        self.assertEqual(ns["b"](), 2)

    def test_byte_literal_escapes_and_utf8(self):
        ns = self.exec_myna('raw = 0b"a\\x80\\377"\ntext = 0b"é"\n')
        self.assertEqual(ns["raw"], b"a\x80\xff")
        self.assertEqual(ns["text"], "é".encode("utf-8"))

    def test_string_escapes_decode_like_python(self):
        src = r'''
        s = "a\fb\vc\a\b\x41\u00e9\101\N{BULLET}"
        t = `a\fb\vc{{x}}`
        r = _"a\fb"
        by = 0b"a\f\101\x42"
        '''
        ns = self.exec_myna(src)
        self.assertEqual(ns["s"], "a\fb\vc\a\b\x41\u00e9\101\N{BULLET}")
        self.assertEqual(ns["t"], "a\fb\vc{x}")
        self.assertEqual(ns["r"], "a\\fb")
        self.assertEqual(ns["by"], b"a\fAB")

    def test_invalid_string_escapes_are_errors(self):
        cases = [
            's = "\\q"\n',
            's = "\\x4"\n',
            's = "\\u123"\n',
            's = "\\N{NOT A CHARACTER}"\n',
            's = 0b"\\u0041"\n',
            "s = `\\q`\n",
        ]
        for src in cases:
            with self.subTest(src=src):
                with self.assertRaises(LexError):
                    myna_to_python(src)

    def test_decompile_preserves_control_characters(self):
        py_src = 's = "a\\x0cb\\x0bc\\x07"\n'
        ns: dict = {}
        exec(myna_to_python(python_to_myna(py_src)), ns)
        self.assertEqual(ns["s"], "a\fb\vc\a")

    def test_cli_version(self):
        proc = subprocess.run(
            [sys.executable, "-m", "myna", "--version"],
            cwd=pathlib.Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(f"myna {myna.__version__}", proc.stdout)
        self.assertIn(f"language {myna.LANGUAGE_VERSION}", proc.stdout)

    def test_js_rejects_unemulable_constructs(self):
        cases = {
            "multiple inheritance": "$A{_}\n$B{_}\n$C < A, B {_}\n",
            "unsupported builtin": '@main { p(@open("x")) }\n',
            "method decorator": "$C { #[dec]\n @f { ^1 } }\n",
            "class decorator": "#[dec]\n$C { _ }\n",
            "star import": '<math:{*}\n',
        }
        for label, src in cases.items():
            with self.subTest(construct=label):
                with self.assertRaises(TargetError):
                    myna_to_js("@target(py, js)\n" + src)

    def test_js_relative_imports_require_a_source_path(self):
        with self.assertRaises(TargetError) as caught:
            myna_to_js("@target(py, js)\n<.util:{f}\n")
        self.assertIn("source path", str(caught.exception))

    def test_try_requires_handler_or_finally(self):
        for src in ("!{ _ } !? { _ }\n", "!{ _ }\n"):
            with self.subTest(src=src):
                with self.assertRaises(ParseError):
                    myna_to_python(src)
        # finally-only try blocks remain valid
        self.assertEqual(
            myna_to_python("!{ p(1) } !: { p(2) }\n"),
            "try:\n    print(1)\nfinally:\n    print(2)\n",
        )

    def test_decompile_error_on_unsupported_construct(self):
        unsupported = [
            "try:\n    pass\nexcept* ValueError:\n    pass\n",
            "def f(value):\n    return f'{value!a}'\n",
            "def f(a, b):\n    return a @ b\n",
            "def f(x):\n    match x:\n        case [a as b, c]:\n            return b\n",
        ]
        for src in unsupported:
            with self.subTest(src=src):
                with self.assertRaises(DecompileError):
                    python_to_myna(src)

    def test_cli_targets_report_and_compile_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "py_only.myna"
            source.write_text("@target(py)\n<math\nvalue=math.pi\n", encoding="utf-8")
            implicit = pathlib.Path(tmp) / "implicit.myna"
            implicit.write_text("value=1\n", encoding="utf-8")
            cwd = pathlib.Path(__file__).resolve().parents[1]
            report = subprocess.run(
                [sys.executable, "-m", "myna", "targets", str(source)],
                cwd=cwd,
                capture_output=True,
                text=True,
            )
            compile_js = subprocess.run(
                [sys.executable, "-m", "myna", "compile", "-t", "js", str(source)],
                cwd=cwd,
                capture_output=True,
                text=True,
            )
            implicit_report = subprocess.run(
                [sys.executable, "-m", "myna", "targets", str(implicit)],
                cwd=cwd,
                capture_output=True,
                text=True,
            )
        self.assertEqual(report.returncode, 0)
        self.assertIn("Declared : py", report.stdout)
        self.assertIn("js       : unsupported", report.stdout)
        self.assertEqual(compile_js.returncode, 1)
        self.assertIn("module declares @target(py)", compile_js.stderr)
        self.assertEqual(implicit_report.returncode, 0)
        self.assertIn("Declared : py", implicit_report.stdout)
        self.assertIn("js       : unsupported", implicit_report.stdout)

    def test_typescript_api_and_cli(self):
        src = "@target(py, js)\n@double(x:i)->i => x * 2\n"
        self.assertIn("function double(x: number): number", myna_to_ts(src))

        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "portable.myna"
            source.write_text(src, encoding="utf-8")
            out = pathlib.Path(tmp) / "portable.ts"
            cwd = pathlib.Path(__file__).resolve().parents[1]

            compiled = subprocess.run(
                [sys.executable, "-m", "myna", "compile", str(source), "-o", str(out)],
                cwd=cwd,
                capture_output=True,
                text=True,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            self.assertIn("function double(x: number): number", out.read_text())

            report = subprocess.run(
                [sys.executable, "-m", "myna", "targets", str(source)],
                cwd=cwd,
                capture_output=True,
                text=True,
            )
            self.assertEqual(report.returncode, 0, report.stderr)
            self.assertIn("ts       : supported", report.stdout)

            run = subprocess.run(
                [sys.executable, "-m", "myna", "run", "-t", "ts", str(source)],
                cwd=cwd,
                capture_output=True,
                text=True,
            )
            self.assertEqual(run.returncode, 1)
            self.assertIn("compile-only", run.stderr)

            source.write_text("@target(py)\nvalue = 1\n", encoding="utf-8")
            rejected = subprocess.run(
                [sys.executable, "-m", "myna", "compile", "-t", "ts", str(source)],
                cwd=cwd,
                capture_output=True,
                text=True,
            )
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("target 'ts'", rejected.stderr)

    def test_run_resolves_relative_myna_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "util.myna").write_text(
                "@target(py)\n@slug(text:s)->s { ^ text.lower().replace(' ', '-') }\n",
                encoding="utf-8",
            )
            pkg = root / "pkg"
            pkg.mkdir()
            (pkg / "__init__.myna").write_text(
                '@target(py)\n@name->s => "pkg"\n', encoding="utf-8"
            )
            (pkg / "helper.myna").write_text(
                "@target(py)\n<..util:{slug}\n@label(x:s)->s => slug(x)\n",
                encoding="utf-8",
            )
            (root / "plain.myna").write_text(
                '@target(py)\n@helper->s => "plain"\n', encoding="utf-8"
            )
            (root / "main.myna").write_text(
                "@target(py)\n"
                "<.util:{slug}\n"
                "<.pkg:{name}\n"
                "<.pkg.helper:{label}\n"
                "<.plain:{helper}\n"
                'p(slug("Hello World"))\n'
                "p(name())\n"
                'p(label("Deep Import"))\n'
                "p(helper())\n",
                encoding="utf-8",
            )
            proc = subprocess.run(
                [sys.executable, "-m", "myna", "run", str(root / "main.myna")],
                cwd=pathlib.Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.splitlines(), ["hello-world", "pkg", "deep-import", "plain"])

    def test_run_relative_module_import_binds_module_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "util.myna").write_text(
                '@target(py)\n@bang(text:s)->s => text + "!"\n', encoding="utf-8"
            )
            (root / "main.myna").write_text(
                "@target(py)\n<.util\n@main { p(util.bang(\"hey\")) }\n",
                encoding="utf-8",
            )
            proc = subprocess.run(
                [sys.executable, "-m", "myna", "run", str(root / "main.myna")],
                cwd=pathlib.Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "hey!")

    def test_relative_dotted_module_import_emits_submodule_form(self):
        src = "@target(py)\n<.pkg.mod\n<.pkg.other>o\n"
        py_code = myna_to_python(src)
        self.assertIn("from .pkg import mod", py_code)
        self.assertIn("from .pkg import other as o", py_code)
        self.assertNotIn("from . import pkg.mod", py_code)
        compile(py_code, "<generated>", "exec")

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "pkg").mkdir()
            (root / "pkg" / "mod.myna").write_text(
                "@target(py)\n@v()->i { ^7 }\n", encoding="utf-8"
            )
            (root / "pkg" / "other.myna").write_text(
                "@target(py)\n@w()->i { ^8 }\n", encoding="utf-8"
            )
            (root / "main.myna").write_text(
                "@target(py)\n<.pkg.mod\n<.pkg.other>o\n@main { p(mod.v() + o.w()) }\n",
                encoding="utf-8",
            )
            proc = subprocess.run(
                [sys.executable, "-m", "myna", "run", str(root / "main.myna")],
                cwd=pathlib.Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "15")

    def _write_deep_entry_layout(self, root: pathlib.Path) -> pathlib.Path:
        """A `tests/` entry that reaches a sibling `src/` with `..` (GAPS.md G14)."""
        (root / "src").mkdir()
        (root / "tests").mkdir()
        (root / "src" / "util.myna").write_text(
            '@target(py)\n@bang(s:s)->s => s + "!"\n', encoding="utf-8"
        )
        (root / "tests" / "helper.myna").write_text(
            "@target(py)\n<..src.util:{bang}\n@shout(s:s)->s => bang(s).upper()\n",
            encoding="utf-8",
        )
        entry = root / "tests" / "run.myna"
        entry.write_text(
            "@target(py)\n"
            "<..src.util:{bang}\n"
            "<.tests.helper:{shout}\n"
            'p(bang("a"))\n'
            'p(shout("b"))\n',
            encoding="utf-8",
        )
        return entry

    def test_module_root_is_the_ceiling_for_a_nested_entry(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            entry = self._write_deep_entry_layout(root)

            def myna(*args: str):
                return subprocess.run(
                    [sys.executable, "-m", "myna", *args],
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                )

            direct = myna("run", "--module-root", str(root), str(entry))
            script = myna(
                "bundle", "--module-root", str(root), str(entry), "-o", str(root / "app.py")
            )
            zipapp = myna(
                "bundle",
                "--zipapp",
                "--module-root",
                str(root),
                str(entry),
                "-o",
                str(root / "app.pyz"),
            )
            bundled = subprocess.run(
                [sys.executable, "-I", str(root / "app.py")],
                cwd=tmp,
                capture_output=True,
                text=True,
            )
            packed = subprocess.run(
                [sys.executable, "-I", str(root / "app.pyz")],
                cwd=tmp,
                capture_output=True,
                text=True,
            )
            without_root = myna("run", str(entry))

        for proc in (direct, bundled, packed):
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.splitlines(), ["a!", "B!"])
        for proc in (script, zipapp):
            self.assertEqual(proc.returncode, 0, proc.stderr)
        # Without a declared root `..` still cannot climb out of the entry's package.
        self.assertEqual(without_root.returncode, 1)

    def _write_src_tests_layout(self, root: pathlib.Path) -> None:
        src = root / "src"
        tests = root / "tests"
        src.mkdir()
        tests.mkdir()
        (src / "highlight.myna").write_text(
            "@target(py)\n@highlight_code(s:s)->s => `<{s}>`\n", encoding="utf-8"
        )
        (src / "util.myna").write_text(
            '@target(py)\n@bang(s:s)->s => s + "!"\n', encoding="utf-8"
        )
        (src / "uses_util.myna").write_text(
            "@target(py)\n<.util:{bang}\n@shout(s:s)->s => bang(s).upper()\n",
            encoding="utf-8",
        )
        (tests / "run_tests.myna").write_text(
            "@target(py)\n"
            "<.src.highlight:{highlight_code}\n"
            "<.src.uses_util:{shout}\n"
            'p(highlight_code("x"))\n'
            'p(shout("hi"))\n',
            encoding="utf-8",
        )

    def test_run_reports_missing_relative_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "util.myna").write_text(
                '@target(py)\n@bang(s:s)->s => s + "!"\n', encoding="utf-8"
            )
            (root / "main.myna").write_text(
                "@target(py)\n<.util:{slug}\np(slug(\"x\"))\n", encoding="utf-8"
            )
            proc = subprocess.run(
                [sys.executable, "-m", "myna", "run", str(root / "main.myna")],
                cwd=pathlib.Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
            )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("relative module 'util' has no name 'slug'", proc.stderr)
        self.assertIn("module root", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_run_module_root_reaches_sibling_src(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self._write_src_tests_layout(root)
            entry = root / "tests" / "run_tests.myna"

            def run(extra_args: list[str], env: dict | None = None):
                return subprocess.run(
                    [sys.executable, "-m", "myna", "run", *extra_args, str(entry)],
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                    env=env,
                )

            by_flag = run(["--module-root", str(root)])
            by_env = run([], env={**os.environ, "MYNA_MODULE_ROOT": str(root)})
            without_root = run([])
            bundle = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "myna",
                    "bundle",
                    "--module-root",
                    str(root),
                    str(entry),
                    "-o",
                    str(root / "app.py"),
                ],
                cwd=repo_root,
                capture_output=True,
                text=True,
            )
            bundled_run = subprocess.run(
                [sys.executable, "-I", str(root / "app.py")],
                cwd=tmp,
                capture_output=True,
                text=True,
            )

        for proc in (by_flag, by_env, bundled_run):
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.splitlines(), ["<x>", "HI!"])

        self.assertEqual(bundle.returncode, 0, bundle.stderr)
        self.assertEqual(without_root.returncode, 1)
        self.assertIn("--module-root", without_root.stderr)
        self.assertIn("src", without_root.stderr)
        self.assertNotIn("Traceback", without_root.stderr)

    def test_run_reports_parse_error_with_module_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "broken.myna").write_text("@target(py)\n? nope {\n", encoding="utf-8")
            (root / "main.myna").write_text(
                '@target(py)\n<.broken:{x}\np("unreachable")\n', encoding="utf-8"
            )
            proc = subprocess.run(
                [sys.executable, "-m", "myna", "run", str(root / "main.myna")],
                cwd=pathlib.Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
            )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("broken.myna", proc.stderr)
        self.assertIn("ParseError", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_bundle_produces_standalone_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "util.myna").write_text(
                "@target(py)\n@slug(text:s)->s { ^ text.lower().replace(' ', '-') }\n",
                encoding="utf-8",
            )
            (root / "plain.myna").write_text(
                '@target(py)\n@plain->s => "plain"\n', encoding="utf-8"
            )
            pkg = root / "pkg"
            pkg.mkdir()
            (pkg / "__init__.myna").write_text(
                '@target(py)\n@name->s => "pkg"\n', encoding="utf-8"
            )
            (pkg / "helper.myna").write_text(
                "@target(py)\n<..util:{slug}\n@label(x:s)->s => slug(x)\n",
                encoding="utf-8",
            )
            (root / "main.myna").write_text(
                "@target(py)\n"
                "<.util:{slug}\n"
                "<.:{plain}\n"
                "<.pkg.helper:{label}\n"
                'p(slug("Hello World"))\n'
                "p(plain.plain())\n"
                'p(label("Deep Import"))\n',
                encoding="utf-8",
            )
            bundle_path = root / "app.py"
            repo_root = pathlib.Path(__file__).resolve().parents[1]
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "myna",
                    "bundle",
                    str(root / "main.myna"),
                    "-o",
                    str(bundle_path),
                ],
                cwd=repo_root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            bundled = bundle_path.read_text(encoding="utf-8")
            run = subprocess.run(
                [sys.executable, "-I", str(bundle_path)],
                cwd=tmp,
                capture_output=True,
                text=True,
            )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stdout.splitlines(), ["hello-world", "plain", "deep-import"])
        self.assertNotIn("import myna", bundled)
        self.assertNotIn("from myna", bundled)

    def test_bundle_zipapp_runs_standalone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "util.myna").write_text(
                "@target(py)\n@slug(text:s)->s { ^ text.lower().replace(' ', '-') }\n",
                encoding="utf-8",
            )
            pkg = root / "pkg"
            pkg.mkdir()
            (pkg / "__init__.myna").write_text(
                '@target(py)\n@name->s => "pkg"\n', encoding="utf-8"
            )
            (pkg / "helper.myna").write_text(
                "@target(py)\n<..util:{slug}\n@label(x:s)->s => slug(x)\n",
                encoding="utf-8",
            )
            nsdir = root / "nsdir"
            nsdir.mkdir()
            (nsdir / "codes.myna").write_text(
                '@target(py)\n@code->i => 7\n', encoding="utf-8"
            )
            (root / "main.myna").write_text(
                "@target(py)\n"
                "<.util:{slug}\n"
                "<.pkg:{name}\n"
                "<.pkg.helper:{label}\n"
                "<.nsdir.codes:{code}\n"
                'p(slug("Hello World"))\n'
                "p(name())\n"
                'p(label("Deep Import"))\n'
                "p(code())\n",
                encoding="utf-8",
            )
            repo_root = pathlib.Path(__file__).resolve().parents[1]
            outputs = [root / "app.pyz", root / "app2.pyz"]
            for output in outputs:
                proc = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "myna",
                        "bundle",
                        str(root / "main.myna"),
                        "--zipapp",
                        "-o",
                        str(output),
                    ],
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
            first, second = (path.read_bytes() for path in outputs)
            run = subprocess.run(
                [sys.executable, "-I", str(outputs[0])],
                cwd=tmp,
                capture_output=True,
                text=True,
            )
            with zipfile.ZipFile(outputs[0]) as archive:
                names = set(archive.namelist())
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(
            run.stdout.splitlines(), ["hello-world", "pkg", "deep-import", "7"]
        )
        self.assertEqual(first, second)  # reproducible builds
        self.assertTrue(first.startswith(b"#!/usr/bin/env python3\n"))
        self.assertIn("_myna_app/main.py", names)
        self.assertIn("_myna_app/nsdir/__init__.py", names)
        self.assertIn("_myna_app/pkg/__init__.py", names)

    def test_bundle_reports_unresolved_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "main.myna").write_text(
                '@target(py)\n<.missing:{thing}\np("unreachable")\n', encoding="utf-8"
            )
            proc = subprocess.run(
                [sys.executable, "-m", "myna", "bundle", str(root / "main.myna")],
                cwd=pathlib.Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
            )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("main.myna", proc.stderr)
        self.assertIn("missing", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_cli_reports_decompile_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = pathlib.Path(tmp) / "bad.py"
            bad.write_text("try:\n    pass\nexcept* ValueError:\n    pass\n", encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, "-m", "myna", "decompile", str(bad)],
                cwd=pathlib.Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
            )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("DecompileError", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_roundtrip_py_to_myna_to_py(self):
        py_src = """
from dataclasses import dataclass
from typing import Optional

@dataclass
class Item:
    name: str
    price: float
    tags: Optional[list[str]] = None

    def total(self, tax: float = 0.1) -> float:
        if self.price <= 0:
            return 0.0
        return round(self.price * (1 + tax), 2)

def filter_items(items: list[Item], min_price: float) -> list[str]:
    res = [it.name for it in items if it.total() >= min_price]
    return sorted(res)
"""
        myna_code = python_to_myna(py_src)
        recompiled_py = myna_to_python(myna_code)

        # Verify Myna code is significantly shorter than Python
        self.assertLess(len(myna_code), len(py_src) * 0.65)

        # Execute recompiled Python and verify semantics match
        ns: dict = {}
        exec(recompiled_py, ns)
        Item = ns["Item"]
        filter_items = ns["filter_items"]
        items = [Item("Book", 20.0), Item("Pen", 2.0), Item("Laptop", 1000.0)]
        self.assertEqual(filter_items(items, 15.0), ["Book", "Laptop"])

    def test_single_statement_loop_bodies_roundtrip(self):
        """`for`/`while`/`with` one-statement bodies must not use the `=>` shorthand.

        ``%x<-(xs)=>f(x)`` is a paren lambda, not a loop body, so the compact form had to
        fall back to braces; this guards the emitted Myna against re-parse failures.
        """
        py_src = """
def walk(xs):
    for x in xs:
        print(x)
    while xs:
        xs = xs[1:]
    with open(__file__) as fh:
        print(bool(fh))
    return len(xs)
"""
        myna_code = python_to_myna(py_src, compact=True)
        self.assertNotIn(")=>", myna_code.replace(" ", ""))
        recompiled = myna_to_python(myna_code)
        ns: dict = {}
        exec(compile(recompiled, "<roundtrip>", "exec"), ns)
        self.assertIn("walk", ns)


if __name__ == "__main__":
    unittest.main()
