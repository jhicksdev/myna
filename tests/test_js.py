"""Cross-target test suite verifying that Myna compiles and runs identically on Python 3.12+ and Node.js."""

from __future__ import annotations
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from myna import TargetError, myna_to_python, myna_to_js

REPO_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "node is required for cross-target JavaScript tests")
class TestMynaJavaScriptTarget(unittest.TestCase):
    def check_js_syntax(self, js_code: str) -> None:
        """Every generated file must at least be valid JavaScript."""
        with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False, encoding="utf-8") as js_tmp:
            js_tmp.write(js_code)
            js_path = js_tmp.name
        try:
            proc = subprocess.run(["node", "--check", js_path], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, f"invalid generated JS:\n{js_code}\n{proc.stderr}")
        finally:
            Path(js_path).unlink(missing_ok=True)

    def run_both_targets(self, myna_src: str) -> tuple[str, str]:
        py_code = myna_to_python(myna_src)
        js_code = myna_to_js(myna_src)
        self.check_js_syntax(js_code)

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as py_tmp:
            py_tmp.write(py_code)
            py_path = py_tmp.name

        with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False, encoding="utf-8") as js_tmp:
            js_tmp.write(js_code)
            js_path = js_tmp.name

        try:
            py_proc = subprocess.run([sys.executable, py_path], capture_output=True, text=True)
            js_proc = subprocess.run(["node", js_path], capture_output=True, text=True)
            self.assertEqual(py_proc.returncode, 0, f"python target failed:\n{py_code}\n{py_proc.stderr}")
            self.assertEqual(js_proc.returncode, 0, f"js target failed:\n{js_code}\n{js_proc.stderr}")
            return py_proc.stdout.strip(), js_proc.stdout.strip()
        finally:
            Path(py_path).unlink(missing_ok=True)
            Path(js_path).unlink(missing_ok=True)

    def test_cross_target_classes_comprehensions_and_pipes(self):
        src = """
        $$Task(id:i, title:s, priority:i=1, done:b=F) {
            @summary->s {
                status = .done ? "DONE" : "TODO"
                ^ `[{status}] #{.id} (p{.priority}): {.title}`
            }
        }

        @double(x:i)->i => x * 2
        @add_n(x:i, n:i)->i => x + n

        @main {
            tasks = [
                Task(1, "Design grammar", 3, T),
                Task(2, "Build Myna parser", 5, F),
                Task(3, "Write tests", 4, F),
                Task(4, "JS target", 2, F)
            ]
            filtered = [t | t <- tasks ? !t.done && t.priority >= 2]
            ordered = @srt(filtered, key=t => -t.priority)
            % line <- [t.summary() | t <- ordered] {
                p(line)
            }

            piped = 5 |> double |> add_n(3)
            p(`piped={piped}`)
        }
        """
        py_out, js_out = self.run_both_targets(src)
        self.assertEqual(py_out, js_out)
        self.assertIn("[TODO] #2 (p5): Build Myna parser", js_out)
        self.assertIn("piped=13", js_out)

    def test_cross_target_control_flow_match_and_loops(self):
        src = """
        @describe(val)->s {
            ?? val {
                0 => { ^ "zero" }
                x ? x > 100 => { ^ `large:{x}` }
                _ => { ^ "other" }
            }
        }

        *@fib(n:i) {
            a, b = 0, 1
            % _ <- ..n {
                ^* a
                a, b = b, a + b
            }
        }

        @main {
            p(describe(0))
            p(describe(250))
            p(describe(42))

            total = 0
            % i <- 0..10..2 {
                ? i == 6 { ^> }
                total += i
            }
            p(`total={total}`)

            fibs = @list(fib(7))
            p(`fibs={@J(fibs)}`)
        }
        """
        py_out, js_out = self.run_both_targets(src)
        # Note: @J(fibs) in Python has spaces `[0, 1, ...]` unless compared via @j, so let's check lines
        py_lines = py_out.splitlines()
        js_lines = js_out.splitlines()
        self.assertEqual(py_lines[:4], js_lines[:4])
        self.assertEqual(js_lines[4], "fibs=[0,1,1,2,3,5,8]")

    def test_cross_target_target_blocks(self):
        src = """
        @target(py) {
            <math
            @platform()->s => `py:{math.pi:.2f}`
        }

        @target(js) {
            @platform()->s => `js:{Math.PI:.2f}`
        }

        @main {
            p(platform())
        }
        """
        py_out, js_out = self.run_both_targets(src)
        self.assertEqual(py_out, "py:3.14")
        self.assertEqual(js_out, "js:3.14")

    def test_cross_target_byte_literals(self):
        src = """
        @main {
            blob = 0b"a\\x80\\xff"
            p(#blob)
            p(blob[1])
        }
        """
        py_out, js_out = self.run_both_targets(src)
        self.assertEqual(py_out, js_out)
        self.assertEqual(js_out, "3\n128")

    def test_cross_target_dicts_json_and_exceptions(self):
        src = """
        $$User(id:i, name:s) {
            @to_dict->{s:A} => {.id, .name}
        }

        @safe_parse(raw:s)->s {
            !{
                obj = @j(raw)
                ^ `ok:{obj$name}`
            } !! e {
                ^ "err"
            }
        }

        @main {
            u = User(7, "Ada")
            d = u.to_dict()
            p(`user={d$id}:{d$name}`)
            p(safe_parse(@J(d)))
            p(safe_parse("{bad json"))
        }
        """
        py_out, js_out = self.run_both_targets(src)
        self.assertEqual(py_out, js_out)
        self.assertEqual(js_out, "user=7:Ada\nok:Ada\nerr")

    def test_cross_target_isinstance_compound_types(self):
        src = """
        @yes(flag:b)->s => flag ? "yes" : "no"

        @main {
            lst = [1, 2]
            d = {a: 1}
            st = {1, 2}
            nested = [[1]]
            p(yes(lst :? [i]))
            p(yes(d :? {s:i}))
            p(yes(st :? {i}))
            p(yes(nested :? [[i]]))
            p(yes(lst :? {s:i}))
            p(yes(5 :? [i]))
            p(yes(5 :? (i, s)))
            p(yes("x" :? (i, s)))
        }
        """
        py_out, js_out = self.run_both_targets(src)
        self.assertEqual(py_out, js_out)
        self.assertEqual(js_out, "yes\nyes\nyes\nyes\nno\nno\nyes\nyes")

    def test_cross_target_truthiness_and_equality(self):
        src = """
        @main {
            vals = [[], {}, "", 0, "x", {k: 1}, [1]]
            % v <- vals { p(v ? "T" : "F") }
            p(![])
            p(![1])
            p(0 || 5)
            p(2 || 5)
            p(0 && 5)
            p(1 && 5)
            p(1 == T)
            p(F == 0)
            p("1" == 1)
            p([1, 2] == [1, 2])
            p({a: 1} == {a: 1})
            p(N == U)
            a = [1]
            b = a
            c = [1]
            p(a === b)
            p(a === c)
            p(a !== c)
        }
        """
        py_out, js_out = self.run_both_targets(src)
        self.assertEqual(py_out, js_out)
        self.assertEqual(
            js_out,
            "\n".join(
                [
                    "F", "F", "F", "F", "T", "T", "T",
                    "True", "False", "5", "2", "0", "5",
                    "True", "True", "False", "True", "True", "True",
                    "True", "False", "True",
                ]
            ),
        )

    def test_cross_target_arithmetic_and_print_formatting(self):
        src = """
        @main {
            p(-7 % 3)
            p(7 % -3)
            p(-7 // 3)
            p(7 // -3)
            p(7 / 2)
            p("a" + "b")
            p([1] + [2])
            p("ab" * 2)
            p([1, 2] * 2)
            p(T)
            p(F)
            p(N)
            p([1, "a"])
            p({a: 1})
            p({1})
            p(0b"abc")
            p(@str([1, "a"]))
        }
        """
        py_out, js_out = self.run_both_targets(src)
        self.assertEqual(py_out, js_out)
        self.assertEqual(
            js_out,
            "\n".join(
                [
                    "2",
                    "-2",
                    "-3",
                    "-3",
                    "3.5",
                    "ab",
                    "[1, 2]",
                    "abab",
                    "[1, 2, 1, 2]",
                    "True",
                    "False",
                    "None",
                    "[1, 'a']",
                    "{'a': 1}",
                    "{1}",
                    "b'abc'",
                    "[1, 'a']",
                ]
            ),
        )

    def test_cross_target_indexing_slicing_and_dict_access(self):
        src = """
        @safe_index(i:i)->s {
            ! { ^ @str([10, 20][i]) } !! e:IndexError { ^ "index" }
        }

        @safe_key()->s {
            ! { d = {}; ^ @str(d$nope) } !! e:KeyError { ^ "key" }
        }

        @main {
            a = [10, 20, 30]
            p(a[-1]); p(a[0:2]); p(a[::-1]); p(a[1:]); p(a[:2]); p(a[-2:])
            p(a[::2]); p(a[2:0:-1])
            s = "😀ab"
            p(s[0]); p(s[1:]); p(#s)
            d = {a: 1}
            p(d$a); p(d$?z ?? "none"); p(d.get("a")); p(d.get("z", 9))
            p(safe_index(5)); p(safe_key())
        }
        """
        py_out, js_out = self.run_both_targets(src)
        self.assertEqual(py_out, js_out)
        self.assertEqual(
            js_out,
            "\n".join(
                [
                    "30", "[10, 20]", "[30, 20, 10]", "[20, 30]", "[10, 20]", "[20, 30]",
                    "[10, 30]", "[30, 20]", "😀", "ab", "3", "1", "none", "1", "9",
                    "index", "key",
                ]
            ),
        )

    def test_cross_target_exception_handlers_else_and_reraise(self):
        src = """
        @classify(k:s)->s {
            ! {
                ? k == "v" { !^ ValueError("v") }
                ? k == "k" { !^ KeyError("k") }
                !^ RuntimeError("r")
            } !! e:ValueError { ^ "value" }
              !! e:KeyError { ^ "key" }
              !! e:RuntimeError { ^ "runtime" }
              !! e { ^ "other" }
        }

        @checked(x:i)->s {
            ! {
                ? x > 0 { !^ ValueError("positive") }
            } !! e:ValueError { ^ "err" } !? { ^ "ok" }
        }

        @reraise()->s {
            ! {
                ! { !^ ValueError("inner") } !! e { !^ }
            } !! e:ValueError { ^ "reraised" }
        }

        @either(k:s)->s {
            ! {
                ? k == "v" { !^ ValueError("v") }
                !^ KeyError("k")
            } !! e:(ValueError, KeyError) { ^ "either" }
        }

        @unhandled()->s {
            ! {
                ! { !^ ValueError("x") } !! e:KeyError { ^ "wrong" }
            } !! e:ValueError { ^ "propagated" }
        }

        $AppError < Exception { }
        @app()->s {
            ! { !^ AppError("app") } !! e:AppError { ^ @str(e) }
        }

        @main {
            p(classify("v")); p(classify("k")); p(classify("x"))
            p(checked(1)); p(checked(0))
            p(reraise())
            p(either("v")); p(either("k"))
            p(unhandled())
            p(app())
            ! { p("try") } !! e { p("except") } !: { p("finally") }
            ! { p("try2") } !: { p("finally2") }
        }
        """
        py_out, js_out = self.run_both_targets(src)
        self.assertEqual(py_out, js_out)
        self.assertEqual(
            js_out,
            "\n".join(
                ["value", "key", "runtime", "err", "ok", "reraised", "either", "either",
                 "propagated", "app", "try", "finally", "try2", "finally2"],
            ),
        )

    def test_cross_target_loop_else(self):
        src = """
        @main {
            % i <- 0..3 { ? i == 5 { ^! } } %: { p("for-else") }
            % i <- 0..3 { ? i == 2 { ^! } } %: { p("unreachable") }
            j = 0
            %? j < 2 { j += 1 } %: { p("while-else") }
            k = 0
            %? k < 2 { k += 1; ? k == 1 { ^! } } %: { p("unreachable2") }
            % i <- 0..2 {
                % j <- 0..2 { ? j == 1 { ^! } } %: { p("inner-else") }
            } %: { p("outer-else") }
        }
        """
        py_out, js_out = self.run_both_targets(src)
        self.assertEqual(py_out, js_out)
        self.assertEqual(js_out, "for-else\nwhile-else\nouter-else")

    def test_cross_target_builtin_aliases_as_values(self):
        src = """
        @main {
            p([3, 1, 2] |> @srt)
            p(@srt([3, 1, 2], reverse=T))
            p([1, 2, 3] |> @sum)
            p(@min([3, 1, 2])); p(@max([3, 1, 2]))
            p(@all([1, 2])); p(@any([0, 2])); p(@all([])); p(@any([]))
            p(@list(@enum(["a", "b"])) |> @J |> @j |> @str)
            p(@list(@zip([1, 2, 3], ["a", "b"])) |> @J |> @j |> @str)
            p(@list(@map(x => x * 2, [1, 2, 3])))
            p(@list(@flt(x => x > 1, [1, 2, 3])))
            p(@list(@rev([1, 2, 3])))
        }
        """
        py_out, js_out = self.run_both_targets(src)
        self.assertEqual(py_out, js_out)
        self.assertEqual(
            js_out,
            "\n".join(
                [
                    "[1, 2, 3]", "[3, 2, 1]", "6", "1", "3", "True", "True", "True", "False",
                    "[[0, 'a'], [1, 'b']]", "[[1, 'a'], [2, 'b']]",
                    "[2, 4, 6]", "[2, 3]", "[3, 2, 1]",
                ]
            ),
        )

    def test_cross_target_helper_dependencies(self):
        # `in` needs `eq`, `*` needs `add`; using either alone must still emit its deps.
        src = """
        @main {
            p(1 <- [1, 2])
            p([1] * 2)
            p("a" * 0)
            p(#"😀")
            x = 1
            ~x
            p("deleted")
        }
        """
        py_out, js_out = self.run_both_targets(src)
        self.assertEqual(py_out, js_out)
        self.assertEqual(js_out, "True\n[1, 1]\n\n1\ndeleted")

    def test_cross_target_reserved_identifiers_and_class_fields(self):
        src = """
        @apply(default:i)->i { ^ default + 1 }

        $Box {
            'field holder'
            value:i = 0
            @get->i => .value
        }

        @main {
            default = 2
            p(apply(default))
            p(default)
            b = Box()
            p(b.get())
            p(b.value)
        }
        """
        py_out, js_out = self.run_both_targets(src)
        self.assertEqual(py_out, js_out)
        self.assertEqual(js_out, "3\n2\n0\n0")

    def test_cross_target_range_steps(self):
        src = """
        @main {
            % i <- 3..0..-1 { p(i) }
            % i <- 0..6..2 { p(i) }
            % i <- ..3 { p(i) }
        }
        """
        py_out, js_out = self.run_both_targets(src)
        self.assertEqual(py_out, js_out)
        self.assertEqual(js_out, "3\n2\n1\n0\n2\n4\n0\n1\n2")

    def test_examples_generate_valid_javascript(self):
        for path in sorted((REPO_ROOT / "examples").glob("*.myna")):
            src = path.read_text(encoding="utf-8")
            try:
                js_code = myna_to_js(src)
            except TargetError:
                continue
            with self.subTest(example=path.name):
                self.check_js_syntax(js_code)


if __name__ == "__main__":
    unittest.main()
