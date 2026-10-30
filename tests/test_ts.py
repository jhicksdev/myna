"""Tests for the TypeScript target.

TypeScript is a typed projection of the JavaScript target, so the executable cases
reuse the JavaScript cross-target corpus and only replace the compiler/runner.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from myna import TargetError, myna_to_python, myna_to_ts

from tests.test_js import TestMynaJavaScriptTarget as _JSTargetTests

REPO_ROOT = Path(__file__).resolve().parents[1]
TS_ROOT = REPO_ROOT / "tests" / "ts"
LOCAL_TSC = TS_ROOT / "node_modules" / ".bin" / "tsc"
TYPE_ROOTS = TS_ROOT / "node_modules" / "@types"


def find_tsc() -> str | None:
    override = os.environ.get("MYNA_TSC")
    if override:
        return override
    if LOCAL_TSC.is_file():
        return str(LOCAL_TSC)
    return shutil.which("tsc")


def has_ts_toolchain() -> bool:
    return bool(shutil.which("node") and find_tsc() and TYPE_ROOTS.is_dir())


def tsc_command(*, out_dir: Path | None = None, files: list[Path]) -> list[str]:
    tsc = find_tsc()
    assert tsc is not None
    command = [
        tsc,
        "--strict",
        "--target",
        "ES2022",
        "--module",
        "NodeNext",
        "--moduleResolution",
        "NodeNext",
        "--types",
        "node",
        "--typeRoots",
        str(TYPE_ROOTS),
    ]
    if out_dir is None:
        command.append("--noEmit")
    else:
        command.extend(["--outDir", str(out_dir)])
    command.extend(str(path) for path in files)
    return command


def write_ts_project(root: Path, modules: dict[str, str]) -> None:
    """Write `.ts` modules plus the `"type": "module"` package marker."""
    (root / "package.json").write_text('{"type": "module"}\n', encoding="utf-8")
    for name, code in modules.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding="utf-8")


class TestTypeScriptGeneration(unittest.TestCase):
    def test_helper_overlay_covers_every_javascript_helper(self):
        import re

        from myna.backends.js_gen import HELPERS
        from myna.backends.ts_gen import ts_helper_source

        for name in HELPERS:
            code = ts_helper_source(name)
            for match in re.finditer(r"function\s+(__myna_\w+)\s*\(([^)]*)\)", code):
                for param in match.group(2).split(","):
                    param = param.strip()
                    if param:
                        self.assertIn(
                            ":", param, f"{name}: unannotated {match.group(0)}"
                        )

    @unittest.skipUnless(has_ts_toolchain(), "node + tests/ts TypeScript toolchain required")
    def test_all_helpers_typecheck_under_strict(self):
        from myna.backends.js_gen import HELPER_ORDER, PY_EXCEPTION_ORDER
        from myna.backends.ts_gen import TSGenerator, ts_helper_source

        generator = TSGenerator()
        code = "\n".join(
            generator._exception_shim(name) for name in PY_EXCEPTION_ORDER
        )
        code += "\n" + "\n".join(ts_helper_source(name) for name in HELPER_ORDER)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_ts_project(root, {"helpers.ts": code})
            proc = subprocess.run(
                tsc_command(files=[root / "helpers.ts"]),
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                proc.returncode, 0, f"{proc.stdout}\n{proc.stderr}"
            )

    def test_arrow_builtin_values_are_annotated(self):
        from myna.backends.js_gen import BUILTIN_VALUES
        from myna.backends.ts_gen import TS_BUILTIN_VALUES

        for name, value in BUILTIN_VALUES.items():
            if "=>" in value:
                self.assertIn(": any", TS_BUILTIN_VALUES[name], name)

    def test_type_mapping(self):
        src = (
            "@target(py, js)\n"
            "@f(a:i, b:f, c:s, d:b, e:B, g:A, h:N, i2:i?, j:[s], "
            "k:{s:i}, l:{i}, m:(i,s), n:Box[i]?)->[s] => []\n"
        )
        ts = myna_to_ts(src)
        self.assertIn(
            "function f(a: number, b: number, c: string, d: boolean, "
            "e: Uint8Array, g: any, h: null, i2: number | null, j: string[], "
            "k: Record<string, number>, l: Set<number>, m: [number, string], "
            "n: Box<number> | null): string[]",
            ts,
        )

    def test_typescript_primitive_spellings(self):
        src = (
            "@target(py, js)\n"
            "@f(x:number, y:string, z:null, q:unknown)->void => U\n"
        )
        ts = myna_to_ts(src)
        self.assertIn(
            "function f(x: number, y: string, z: null, q: unknown): void", ts
        )
        self.assertNotIn("$null", ts)
        self.assertNotIn("$undefined", ts)

    def test_dict_key_types_are_valid_record_keys(self):
        src = "@target(py, js)\n@f(d:{[i]:s}, e:{i:s})->s => \"\"\n"
        ts = myna_to_ts(src)
        self.assertIn("d: Record<string, string>", ts)
        self.assertIn("e: Record<number, string>", ts)

    def test_unannotated_parameters_are_explicit_any(self):
        src = '@target(py, js)\n@f(x, y=1)->s => "x"\n@bare(z) { ^ z }\n'
        ts = myna_to_ts(src)
        self.assertIn("function f(x: any, y: any = 1): string", ts)
        self.assertIn("function bare(z: any) {", ts)

    def test_async_and_generator_return_annotations(self):
        src = (
            "@target(py, js)\n"
            '~@f(x:i)->s { ^ "x" }\n'
            "*@g(n:i) { ^* n }\n"
            "~*@h(n:i) { ^* n }\n"
        )
        ts = myna_to_ts(src)
        self.assertIn("async function f(x: number): Promise<string>", ts)
        self.assertIn("function* g(n: number) {", ts)
        self.assertIn("async function* h(n: number) {", ts)
        self.assertNotIn("function* g(n: number): number", ts)

    def test_python_typing_names_map_to_typescript(self):
        src = (
            "@target(py, js)\n"
            "@f(c:Callable[[i], s], m:Mapping[s, i], q:Sequence[i], "
            "it:Iterator[i], aw:Awaitable[i], g:Generator[i, A, s], "
            "t:Type[i], h:typing.Hashable)->i => 1\n"
        )
        ts = myna_to_ts(src)
        self.assertIn("c: (arg0: number) => string", ts)
        self.assertIn("m: Record<string, number>", ts)
        self.assertIn("q: number[]", ts)
        self.assertIn("it: Iterable<number>", ts)
        self.assertIn("aw: Promise<number>", ts)
        self.assertIn("g: Generator<number, string, any>", ts)
        self.assertIn("t: new (...args: any[]) => number", ts)
        self.assertIn("h: any", ts)
        self.assertNotIn("Callable<", ts)

    def test_bare_builtin_generics(self):
        src = (
            "@target(py, js)\n"
            "@f(a:list, b:dict, c:set, d:tuple, e:type)->i => 1\n"
        )
        ts = myna_to_ts(src)
        self.assertIn("a: any[]", ts)
        self.assertIn("b: Record<string, any>", ts)
        self.assertIn("c: Set<any>", ts)
        self.assertIn("d: any[]", ts)
        self.assertIn("e: new (...args: any[]) => any", ts)

    def test_callable_argument_forms(self):
        src = (
            "@target(py, js)\n"
            "@f(a:Callable[[i], s], b:Callable[(i, s), b], c:Callable[(), i], "
            "d:Callable[i, i], e:Callable[[i], s]?, g:[Callable[[i], s]])->i => 1\n"
        )
        ts = myna_to_ts(src)
        self.assertIn("a: (arg0: number) => string", ts)
        self.assertIn("b: (arg0: number, arg1: string) => boolean", ts)
        self.assertIn("c: () => number", ts)
        self.assertIn("d: (arg0: number) => number", ts)
        self.assertIn("e: ((arg0: number) => string) | null", ts)
        self.assertIn("g: ((arg0: number) => string)[]", ts)

    def test_generic_arguments_on_user_types_are_erased(self):
        src = (
            "@target(py, js)\n"
            "$Box { x:i = 0 }\n"
            "$= Alias = [i]\n"
            "@f(b:Box[i], a:Alias[s])->i => 1\n"
        )
        ts = myna_to_ts(src)
        self.assertIn("b: Box", ts)
        self.assertIn("a: Alias", ts)
        self.assertNotIn("Box<", ts)
        self.assertNotIn("Alias<", ts)

    def test_self_annotation_resolves_to_enclosing_class(self):
        src = (
            "@target(py, js)\n"
            "$C {\n"
            "  @copy()->Self { ^ C() }\n"
            "}\n"
        )
        self.assertIn("copy(): C", myna_to_ts(src))

    def test_var_keyword_parameter_is_optional(self):
        ts = myna_to_ts("@target(py, js)\n@f(a:i, **kw:A)->i => a\n")
        self.assertIn(
            "function f(a: number, kw: any = {} as any): number", ts
        )

    def test_with_bindings_are_hoisted_out_of_the_block(self):
        src = (
            "@target(py, js)\n"
            "$C { @close() { _ } }\n"
            '@main { !& c = C() { _ }; p("after") }\n'
        )
        ts = myna_to_ts(src)
        self.assertIn("let c: any;", ts)
        self.assertRegex(ts, r"c = __ctx_\d+_0 as any;")

    def test_dataclass_inheritance_uses_base_constructor(self):
        src = (
            "@target(py, js)\n"
            "$$Base(id:i)\n"
            "$$Child(name:s) < Base\n"
        )
        ts = myna_to_ts(src)
        self.assertIn("class Child extends Base", ts)
        child = ts[ts.index("class Child") :]
        self.assertIn("constructor(id: number, name: string)", child)
        self.assertIn("super(id);", child)
        self.assertIn("this.name = name;", child)
        self.assertNotIn("this.id = id;", child)

    def test_nested_classes_are_rejected(self):
        with self.assertRaises(TargetError):
            myna_to_ts("@target(py, js)\n$Outer { $Inner { _ } }\n")

    def test_derived_init_must_call_super(self):
        src = (
            "@target(py, js)\n"
            "$Base { @init(x:i) { .x = x } }\n"
            "$Child < Base { @init(x:i) { .x = x } }\n"
        )
        with self.assertRaises(TargetError):
            myna_to_ts(src)

    def test_dataclass_inheritance_with_custom_init_is_rejected(self):
        for fields in ("y:i", ""):
            with self.subTest(fields=fields):
                src = (
                    "@target(py, js)\n"
                    "$Base { @init(x:i) { .x = x } }\n"
                    f"$$Child({fields}) < Base\n"
                )
                with self.assertRaises(TargetError):
                    myna_to_ts(src)

    def test_dataclass_and_class_fields_are_declared(self):
        src = (
            "@target(py, js)\n"
            '$$P(x:i, y:s="a") { @total->i => .x }\n'
            "$C {\n"
            "  value:i = 0\n"
            "  @init(a:i) { .a = a }\n"
            "  @set_other(v:s) { .other = v }\n"
            "}\n"
        )
        ts = myna_to_ts(src)
        self.assertIn("x: number;", ts)
        self.assertIn("y: string;", ts)
        self.assertIn("constructor(x: number, y: string = \"a\")", ts)
        self.assertIn("value: number = 0;", ts)
        self.assertIn("a!: number;", ts)
        self.assertIn("other!: any;", ts)

    def test_type_alias_exports_and_value_use_is_rejected(self):
        src = "@target(py, js)\n$= Alias = [i]\n@f(x:Alias)->Alias => x\n"
        ts = myna_to_ts(src)
        self.assertIn("export type Alias = number[];", ts)
        self.assertIn("function f(x: Alias): Alias", ts)
        self.assertNotIn("export { Alias }", ts)

        with self.assertRaises(TargetError):
            myna_to_ts("@target(py, js)\n$= Alias = [i]\np(Alias)\n")

    def test_user_types_shadow_python_type_shorthands(self):
        src = (
            "@target(py, js)\n"
            "$int { @init(x:i) { .x = x } }\n"
            "@f(x:int)->int => x\n"
        )
        ts = myna_to_ts(src)
        self.assertIn("class int {", ts)
        self.assertIn("function f(x: int): int", ts)

        alias = myna_to_ts("@target(py, js)\n$= int = [i]\n@f(x:int)->int => x\n")
        self.assertIn("export type int = number[];", alias)
        self.assertIn("function f(x: int): int", alias)

    def test_reserved_inline_exports_use_trailing_aliases(self):
        src = (
            "@target(py, js)\n"
            "+@default(x:i)->i => x\n"
            "+$delete { _ }\n"
        )
        ts = myna_to_ts(src)
        self.assertIn("function $default(x: number): number", ts)
        self.assertIn("class $delete", ts)
        self.assertIn("export { $default as default, $delete as delete };", ts)

    def test_reserved_type_alias_is_exported_under_its_source_name(self):
        ts = myna_to_ts("@target(py, js)\n$= default = [i]\n")
        self.assertIn("type $default = number[];", ts)
        self.assertIn("export type { $default as default };", ts)

    def test_constructor_members_are_rejected(self):
        cases = [
            "$C { constructor:i = 1 }\n",
            "$$C(constructor:i)\n",
            "$C { @constructor() { _ } }\n",
            "$C { @init() { .constructor = 1 } }\n",
        ]
        for src in cases:
            with self.subTest(src=src):
                with self.assertRaises(TargetError):
                    myna_to_ts("@target(py, js)\n" + src)

    def test_reserved_typescript_names_are_rejected(self):
        with self.assertRaises(TargetError):
            myna_to_ts("@target(py, js)\n$string { _ }\n")
        with self.assertRaises(TargetError):
            myna_to_ts("@target(py, js)\n$= number = [i]\n")

    def test_target_contract_and_blocks_use_javascript(self):
        with self.assertRaises(TargetError) as caught:
            myna_to_ts("@target(py)\nvalue = 1\n")
        self.assertIn("target 'ts'", str(caught.exception))

        src = """
        @target(py, js)
        @target(py) { @platform()->s => "py" }
        @target(js) { @platform()->s => "js" }
        """
        ts = myna_to_ts(src)
        self.assertIn('"js"', ts)
        self.assertNotIn('"py"', ts)

    def test_target_errors_match_the_javascript_target(self):
        cases = [
            "$A{_}\n$B{_}\n$C < A, B {_}\n",
            '@main { p(@open("x")) }\n',
            "$C { #[dec]\n @f { ^1 } }\n",
            "#[dec]\n$C { _ }\n",
            "<math:{*}\n",
        ]
        for src in cases:
            with self.subTest(src=src):
                with self.assertRaises(TargetError):
                    myna_to_ts(src)

    def test_delete_and_catch_are_strict_safe(self):
        src = (
            "@target(py, js)\n"
            "@f(x:i)->i {\n"
            "  ~x\n"
            "  ! { !^ ValueError(\"x\") } !! e:ValueError { ^ 1 }\n"
            "}\n"
        )
        ts = myna_to_ts(src)
        self.assertIn("x = undefined as any;", ts)
        self.assertIn("catch (__myna_exc: any)", ts)
        self.assertIn("constructor(message?: any)", ts)

    def test_js_only_module_compiles_for_ts(self):
        src = "@target(js)\n@f()->i => 1\n"
        self.assertIn("function f(): number", myna_to_ts(src))
        with self.assertRaises(TargetError):
            myna_to_python(src)

    def test_relative_imports_need_a_source_path(self):
        with self.assertRaises(TargetError) as caught:
            myna_to_ts("@target(py, js)\n<.util:{f}\n")
        self.assertIn("TypeScript target", str(caught.exception))

    def test_compile_to_ts_ast_entrypoint(self):
        import myna

        code = myna.compile_to_ts(myna.parse("@target(py, js)\n@f()->i => 1\n"))
        self.assertIn("function f(): number", code)

    def test_relative_imports_emit_type_only_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            util = root / "util.myna"
            util.write_text(
                "@target(py, js)\n"
                "$= Slug = s\n"
                '@slug(text:s)->s => text.lower()\n'
                "LIMIT = 3\n",
                encoding="utf-8",
            )
            main = root / "main.myna"
            main.write_text(
                "@target(py, js)\n"
                "<.util:{slug, LIMIT, Slug}\n"
                "@label(text:Slug)->Slug => `[{slug(text)}]`\n",
                encoding="utf-8",
            )
            ts = myna_to_ts(main.read_text(), source_path=main)
            self.assertIn('import { slug, LIMIT } from "./util.js";', ts)
            self.assertIn('import type { Slug } from "./util.js";', ts)
            self.assertIn("export type { Slug };", ts)

            mjs = myna_to_ts(main.read_text(), source_path=main, module_ext=".mjs")
            self.assertIn('from "./util.mjs";', mjs)

    def test_specifier_extension_is_independent_of_output_extension(self):
        # `myna_to_ts` is given the JavaScript specifier extension, not `.ts`.
        src = "@target(py, js)\n<.util:{f}\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "util.myna").write_text(
                "@target(py, js)\n@f->i => 1\n", encoding="utf-8"
            )
            main = root / "main.myna"
            main.write_text(src, encoding="utf-8")
            ts = myna_to_ts(src, source_path=main)
            self.assertIn('from "./util.js";', ts)


@unittest.skipUnless(has_ts_toolchain(), "node + tests/ts TypeScript toolchain required")
class TestMynaTypeScriptTarget(_JSTargetTests):
    """Run the JavaScript cross-target corpus through tsc + Node."""

    def run_both_targets(self, myna_src: str) -> tuple[str, str]:
        myna_src = self.portable_source(myna_src)
        py_code = myna_to_python(myna_src)
        ts_code = myna_to_ts(myna_src)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_ts_project(root, {"main.ts": ts_code})
            (root / "main.py").write_text(py_code, encoding="utf-8")

            compile_proc = subprocess.run(
                tsc_command(out_dir=root / "out", files=[root / "main.ts"]),
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                compile_proc.returncode,
                0,
                f"invalid or ill-typed generated TypeScript:\n{ts_code}\n"
                f"{compile_proc.stdout}\n{compile_proc.stderr}",
            )

            py_proc = subprocess.run(
                [sys.executable, str(root / "main.py")],
                capture_output=True,
                text=True,
            )
            js_proc = subprocess.run(
                ["node", str(root / "out" / "main.js")],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                py_proc.returncode, 0, f"python target failed:\n{py_code}\n{py_proc.stderr}"
            )
            self.assertEqual(
                js_proc.returncode, 0, f"TypeScript target failed:\n{ts_code}\n{js_proc.stderr}"
            )
            return py_proc.stdout.strip(), js_proc.stdout.strip()

    def run_ts(self, myna_src: str) -> str:
        """Typecheck and execute a source that has no runnable Python counterpart."""
        ts_code = myna_to_ts(myna_src)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_ts_project(root, {"main.ts": ts_code})
            compile_proc = subprocess.run(
                tsc_command(out_dir=root / "out", files=[root / "main.ts"]),
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                compile_proc.returncode,
                0,
                f"invalid or ill-typed generated TypeScript:\n{ts_code}\n"
                f"{compile_proc.stdout}\n{compile_proc.stderr}",
            )
            js_proc = subprocess.run(
                ["node", str(root / "out" / "main.js")],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                js_proc.returncode,
                0,
                f"TypeScript target failed:\n{ts_code}\n{js_proc.stderr}",
            )
            return js_proc.stdout.strip()

    def test_ts_typing_annotations_typecheck_and_run(self):
        src = """
        @target(py, js)
        @apply(f:Callable[(i, i), i], x:i)->i => f(x, x)
        @main { p(apply((a, b) => a + b, 4)) }
        """
        self.assertEqual(self.run_ts(src), "8")

    def test_ts_relative_imports_typecheck_and_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src"
            src.mkdir()
            (src / "util.myna").write_text(
                "@target(py, js)\n"
                "$= Slug = s\n"
                '@slug(text:s)->s => text.lower().replace(" ", "-")\n'
                "LIMIT = 3\n",
                encoding="utf-8",
            )
            (src / "main.myna").write_text(
                "@target(py, js)\n"
                "<.util:{slug, LIMIT, Slug}\n"
                "@label(text:Slug)->Slug => `[{slug(text)}]`\n"
                "@main {\n"
                '  p(label("Hello World"))\n'
                "  p(LIMIT)\n"
                "}\n",
                encoding="utf-8",
            )
            modules = {}
            for path in src.glob("*.myna"):
                modules[f"src/{path.with_suffix('.ts').name}"] = myna_to_ts(
                    path.read_text(encoding="utf-8"), source_path=path
                )
            write_ts_project(root, modules)

            compile_proc = subprocess.run(
                tsc_command(
                    out_dir=root / "out",
                    files=[root / "src" / "main.ts", root / "src" / "util.ts"],
                ),
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(compile_proc.returncode, 0, compile_proc.stdout)

            # `tsc` infers `src/` as the common root, so the entry lands at out/main.js.
            node_proc = subprocess.run(
                ["node", str(root / "out" / "main.js")],
                capture_output=True,
                text=True,
            )
            py_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "myna",
                    "run",
                    str(src / "main.myna"),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

        self.assertEqual(node_proc.returncode, 0, node_proc.stderr)
        self.assertEqual(py_proc.returncode, 0, py_proc.stderr)
        self.assertEqual(node_proc.stdout, py_proc.stdout)
        self.assertEqual(node_proc.stdout.splitlines(), ["[hello-world]", "3"])

    def test_ts_consumer_gets_exported_types(self):
        lib_src = (
            "@target(py, js)\n"
            "$= Label = s\n"
            "$$Point(x:i, y:i)\n"
            "@double(x:i)->i => x * 2\n"
            "@label(x:Label)->Label => `[{x}]`\n"
        )
        consumer = """
        import { Point, double, label } from "./lib.js";
        import type { Label } from "./lib.js";

        const n: number = double(21);
        const p: Point = new Point(1, 2);
        const l: Label = label("x");

        // @ts-expect-error - strings are not numbers
        double("no");
        // @ts-expect-error - Point requires two numbers
        new Point(1);

        export { n, p, l };
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_ts_project(root, {"lib.ts": myna_to_ts(lib_src), "consumer.ts": consumer})
            proc = subprocess.run(
                tsc_command(files=[root / "consumer.ts", root / "lib.ts"]),
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, f"{proc.stdout}\n{proc.stderr}")

    def test_examples_generate_valid_typescript(self):
        for path in sorted((REPO_ROOT / "examples").glob("*.myna")):
            src = path.read_text(encoding="utf-8")
            try:
                ts_code = myna_to_ts(src, source_path=path)
            except TargetError:
                continue
            with self.subTest(example=path.name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                write_ts_project(root, {"main.ts": ts_code})
                proc = subprocess.run(
                    tsc_command(files=[root / "main.ts"]),
                    cwd=root,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(
                    proc.returncode,
                    0,
                    f"{path.name}:\n{ts_code}\n{proc.stdout}\n{proc.stderr}",
                )

    # These exercise the JavaScript CLI/backend directly; the TypeScript equivalents
    # above cover the same capabilities.  Shadowing them with non-callables keeps
    # unittest from collecting the inherited JavaScript implementations.
    test_js_relative_imports_compile_to_es_modules = None
    test_run_js_resolves_relative_imports = None
    test_examples_generate_valid_javascript = None


# Do not let unittest discover the imported JavaScript test class again through this
# module; it is already collected from tests/test_js.py.
del _JSTargetTests


if __name__ == "__main__":
    unittest.main()
