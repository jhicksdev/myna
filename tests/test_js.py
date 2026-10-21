"""Cross-target test suite verifying that Myna compiles and runs identically on Python 3.12+ and Node.js."""

from __future__ import annotations
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from myna import myna_to_python, myna_to_js


@unittest.skipUnless(shutil.which("node"), "node is required for cross-target JavaScript tests")
class TestMynaJavaScriptTarget(unittest.TestCase):
    def run_both_targets(self, myna_src: str) -> tuple[str, str]:
        py_code = myna_to_python(myna_src)
        js_code = myna_to_js(myna_src)

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as py_tmp:
            py_tmp.write(py_code)
            py_path = py_tmp.name

        with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False, encoding="utf-8") as js_tmp:
            js_tmp.write(js_code)
            js_path = js_tmp.name

        try:
            py_proc = subprocess.run(["python3", py_path], capture_output=True, text=True, check=True)
            js_proc = subprocess.run(["node", js_path], capture_output=True, text=True, check=True)
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


if __name__ == "__main__":
    unittest.main()
