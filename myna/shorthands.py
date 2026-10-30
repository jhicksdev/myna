"""Language-level name tables shared by the parser, the backends, and the decompiler.

The parser accepts ``@name`` in expression position only for a name listed here; anything
else is a declaration sigil and cannot appear inside an expression.
"""

from __future__ import annotations

BUILTIN_SHORTHANDS = {
    "p": "print",
    "@j": "json.loads",
    "@J": "json.dumps",
    "@enum": "enumerate",
    "@zip": "zip",
    "@map": "map",
    "@flt": "filter",
    "@srt": "sorted",
    "@rev": "reversed",
    "@sum": "sum",
    "@min": "min",
    "@max": "max",
    "@abs": "abs",
    "@all": "all",
    "@any": "any",
    "@str": "str",
    "@int": "int",
    "@float": "float",
    "@bool": "bool",
    "@list": "list",
    "@dict": "dict",
    "@set": "set",
    "@tuple": "tuple",
    "@type": "type",
    "@repr": "repr",
    "@id": "id",
    "@dir": "dir",
    "@vars": "vars",
    "@open": "open",
    "@inp": "input",
    "@chr": "chr",
    "@ord": "ord",
    "@hex": "hex",
    "@bin": "bin",
    "@oct": "oct",
    "@pow": "pow",
    "@rnd": "round",
    "@hash": "hash",
    "@iter": "iter",
    "@next": "next",
    "@get": "getattr",
    "@set_a": "setattr",
    "@has": "hasattr",
    "@del_a": "delattr",
}

# Names accepted as `@name` in expression position that are not Python builtins: the
# UTF-8 codec helpers are special-cased by the Python backend and live in the
# JavaScript/TypeScript builtin-value table.
SIGIL_SHORTHANDS = frozenset({"@u8", "@u8d"})

EXPRESSION_SHORTHANDS = frozenset(BUILTIN_SHORTHANDS) | SIGIL_SHORTHANDS

# Single-letter identifiers that parse as literals in Myna (`T`/`F` booleans, `N` None,
# `U` undefined). They cannot be used as binding names: a class named `U` would be
# shadowed by the literal at every use site.
LITERAL_BINDING_NAMES = frozenset({"T", "F", "N", "U"})
