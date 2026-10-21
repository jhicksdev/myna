"""Round-trip regression suite: Python -> Myna -> Python.

This encodes the decompiler contract: Python we claim to support must survive
``python_to_myna`` followed by ``myna_to_python`` and still compile. Semantic
fixtures additionally execute both versions and compare their results.

These tests are intentionally written before the parser/decompiler fixes; a
failure here is a concrete bug to fix, not a flaky test.
"""

from __future__ import annotations

import pathlib
import sysconfig
import unittest

from myna import myna_to_python, python_to_myna

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
STDLIB = pathlib.Path(sysconfig.get_paths()["stdlib"])

REPO_CORPUS = sorted(
    path
    for path in [*(REPO_ROOT / "myna").rglob("*.py"), *(REPO_ROOT / "tests").glob("*.py")]
    if "__pycache__" not in path.parts
)

STDLIB_CORPUS = [
    relative
    for relative in ("json/decoder.py", "textwrap.py", "heapq.py", "json/encoder.py")
    if (STDLIB / relative).exists()
]


def run_expression(source: str, expression: str):
    """Execute ``source`` and evaluate ``expression``, capturing exceptions."""
    namespace: dict = {}
    exec(compile(source, "<roundtrip-fixture>", "exec"), namespace)
    try:
        return ("ok", eval(expression, namespace))
    except Exception as exc:
        return ("error", type(exc).__name__, str(exc))


class RoundTripAssertions(unittest.TestCase):
    def assert_roundtrips(
        self,
        source: str,
        name: str,
        *,
        compact: bool = True,
        minify_locals: bool = False,
    ) -> None:
        myna = python_to_myna(source, compact=compact, minify_locals=minify_locals)
        python = myna_to_python(myna)
        compile(python, name, "exec")

    def assert_corpus_roundtrips(
        self,
        corpus: list[pathlib.Path],
        *,
        compact: bool,
        minify_locals: bool = False,
    ) -> None:
        for path in corpus:
            with self.subTest(file=path.name, compact=compact, minify_locals=minify_locals):
                self.assert_roundtrips(
                    path.read_text(encoding="utf-8"),
                    str(path),
                    compact=compact,
                    minify_locals=minify_locals,
                )


class TestRepositoryCorpus(RoundTripAssertions):
    def test_repo_sources_compact(self):
        self.assert_corpus_roundtrips(REPO_CORPUS, compact=True)

    def test_repo_sources_pretty(self):
        self.assert_corpus_roundtrips(REPO_CORPUS, compact=False)

    def test_repo_sources_compact_with_minified_locals(self):
        self.assert_corpus_roundtrips(REPO_CORPUS, compact=True, minify_locals=True)


@unittest.skipUnless(STDLIB_CORPUS, "no usable stdlib corpus files found")
class TestStdlibCorpus(RoundTripAssertions):
    def _stdlib_paths(self) -> list[pathlib.Path]:
        return [STDLIB / relative for relative in STDLIB_CORPUS]

    def test_stdlib_sources_compact(self):
        self.assert_corpus_roundtrips(self._stdlib_paths(), compact=True)

    def test_stdlib_sources_pretty(self):
        self.assert_corpus_roundtrips(self._stdlib_paths(), compact=False)

    def test_stdlib_sources_minified_locals(self):
        self.assert_corpus_roundtrips(self._stdlib_paths(), compact=True, minify_locals=True)


# Each fixture is (name, Python source, expression to evaluate).
# They are deliberately small and self-contained so the original and the
# round-tripped version can be executed side by side.
SEMANTIC_FIXTURES = [
    (
        "modulo",
        """
def calc(a, b):
    return a % b
""",
        "calc(17, 5)",
    ),
    (
        "percent_format",
        """
def label(name, count):
    return "%s: %d" % (name, count)
""",
        'label("books", 3)',
    ),
    (
        "fstring_conversion",
        """
def show(value):
    return f"value={value!r}"
""",
        'show("hi")',
    ),
    (
        "fstring_literal_backtick_and_braces",
        """
def decorate(value):
    return f"`{{value={value}}}`"
""",
        "decorate(5)",
    ),
    (
        "not_binds_looser_than_comparison",
        """
def check(value, items):
    return not isinstance(value, (str, bytes)) and value not in items
""",
        "check(1, [2, 3])",
    ),
    (
        "one_line_if_assignment",
        """
def gate(flag):
    result = 0
    if flag:
        result = 1
    return result
""",
        "gate(True)",
    ),
    (
        "plus_at_builtin",
        """
def biggest(a, b):
    return 1 + max(a, b)
""",
        "biggest(2, 5)",
    ),
    (
        "comprehension_over_conditional",
        """
def pick(flag, first, second):
    return [value for value in (first if flag else second)]
""",
        "pick(True, [1, 2], [3])",
    ),
    (
        "tuple_if_condition",
        """
def truthy(first, second):
    if (first, second):
        return 1
    return 0
""",
        "truthy(0, 1)",
    ),
    (
        "tuple_membership_arrow_body",
        """
def shrink(token, first, second):
    count = 2
    if token in (first, second):
        count -= 1
    return count
""",
        'shrink("x", "x", "y")',
    ),
    (
        "bytes_utf8",
        """
def blob():
    return b"abc"
""",
        "blob()",
    ),
    (
        "bytes_non_utf8",
        """
def blob():
    return b"\\x80\\xff"
""",
        "blob()",
    ),
    (
        "dataclass_and_comprehension",
        """
from dataclasses import dataclass

@dataclass
class Item:
    name: str
    price: float

def cheap(items, limit):
    return sorted([item.name for item in items if item.price <= limit])
""",
        'cheap([Item("pen", 2.0), Item("laptop", 1000.0)], 10.0)',
    ),
    (
        "exceptions",
        """
def safe_div(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        return -1
    finally:
        pass
""",
        "safe_div(1, 0)",
    ),
    (
        "closure_nonlocal",
        """
def counter(start):
    total = start

    def add(n):
        nonlocal total
        total += n
        return total

    add(2)
    return add(3)
""",
        "counter(10)",
    ),
    (
        "match_statement",
        """
def describe(value):
    match value:
        case 0:
            return "zero"
        case _:
            return "other"
""",
        "describe(0)",
    ),
]


class TestSemanticRoundTrip(RoundTripAssertions):
    def test_semantic_fixtures(self):
        for compact in (True, False):
            for name, source, expression in SEMANTIC_FIXTURES:
                with self.subTest(fixture=name, compact=compact):
                    expected = run_expression(source, expression)
                    myna = python_to_myna(source, compact=compact)
                    roundtripped = myna_to_python(myna)
                    actual = run_expression(roundtripped, expression)
                    self.assertEqual(
                        actual,
                        expected,
                        msg=f"{name} changed semantics\n--- Myna ---\n{myna}\n--- Python ---\n{roundtripped}",
                    )


if __name__ == "__main__":
    unittest.main()
