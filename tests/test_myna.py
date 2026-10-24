"""Comprehensive test suite for the Myna programming language."""

from __future__ import annotations
import asyncio
import pathlib
import subprocess
import sys
import tempfile
import unittest

from myna import DecompileError, ParseError, TargetError, myna_to_js, myna_to_python, python_to_myna


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
        self.assertEqual(report.returncode, 0)
        self.assertIn("Declared : py", report.stdout)
        self.assertIn("js       : unsupported", report.stdout)
        self.assertEqual(compile_js.returncode, 1)
        self.assertIn("module declares @target(py)", compile_js.stderr)

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


if __name__ == "__main__":
    unittest.main()
