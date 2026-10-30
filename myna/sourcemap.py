"""Map generated Python line numbers back to Myna source lines.

`myna run` compiles Python whose line numbers are the *generated* ones, so a traceback used
to point at a `.myna` file with the wrong line and the wrong excerpt (GAPS.md G12).

The Python backend can emit a marker comment before every statement (`sourcemap=True`,
`# myna:42`). `split_markers` turns that into a generated-line -> Myna-line table and
blanks the marker lines so the line count is unchanged; `relabel` then rewrites the
generated AST's line numbers before it is compiled. Line numbers are correct natively, so
`traceback`, `linecache`, `dis`, and user `except` handlers all agree, and the excerpt
printed for a frame is the Myna source itself.
"""

from __future__ import annotations

import ast as py_ast

# Marker printed by the backend before an emitted statement, e.g. `# myna:42`.
SOURCE_MARKER = "# myna:"


def split_markers(code: str) -> tuple[str, list[int]]:
    """Return ``(code_without_markers, line_map)``.

    ``line_map[i]`` is the Myna line for generated line ``i + 1``. Lines that precede the
    first marker (an injected import, for example) take the first statement's line.
    """
    lines = code.split("\n")
    line_map: list[int] = []
    current: int | None = None
    stripped: list[str] = []
    for line in lines:
        text = line.strip()
        if text.startswith(SOURCE_MARKER):
            digits = text[len(SOURCE_MARKER):].strip()
            if digits.isdigit():
                current = int(digits)
                line_map.append(current)
                stripped.append("")
                continue
        stripped.append(line)
        line_map.append(current if current is not None else 0)

    first = next((line for line in line_map if line), 0)
    if first:
        line_map = [line or first for line in line_map]
    return "\n".join(stripped), line_map


def relabel(tree: py_ast.AST, line_map: list[int]) -> None:
    """Rewrite every node's line numbers through ``line_map`` in place."""

    def mapped(lineno: int | None) -> int | None:
        if lineno is None or not 0 < lineno <= len(line_map):
            return lineno
        return line_map[lineno - 1] or lineno

    for node in py_ast.walk(tree):
        lineno = getattr(node, "lineno", None)
        if lineno is None:
            continue
        node.lineno = mapped(lineno)
        end = getattr(node, "end_lineno", None)
        if end is not None:
            node.end_lineno = max(node.lineno, mapped(end) or node.lineno)
        # Columns describe the generated Python, not the Myna line, so drop them rather
        # than print carets under the wrong characters.
        if hasattr(node, "col_offset"):
            node.col_offset = 0
        if hasattr(node, "end_col_offset"):
            node.end_col_offset = 0
