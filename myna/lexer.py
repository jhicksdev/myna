"""Lexer for the Myna programming language."""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto


class TT(Enum):
    # Literals & Identifiers
    IDENT = auto()
    INT = auto()
    FLOAT = auto()
    STR = auto()
    RAW_STR = auto()
    BYTES = auto()
    FSTR = auto()

    # Delimiters
    LPAREN = auto()      # (
    RPAREN = auto()      # )
    LBRACK = auto()      # [
    RBRACK = auto()      # ]
    LBRACE = auto()      # {
    RBRACE = auto()      # }
    COMMA = auto()       # ,
    SEMI = auto()        # ;
    NEWLINE = auto()     # \n (outside parens/brackets)

    # Multi-char operators & sigils
    TILDE_AT = auto()       # ~@
    STAR_AT = auto()        # *@
    TILDE_STAR_AT = auto()  # ~*@
    AT_SLASH = auto()       # @/
    AT_DOLLAR = auto()      # @$
    AT_QMARK = auto()       # @?
    AT_EQ = auto()          # @=
    PLUS_AT = auto()        # +@
    PLUS_DOLLAR = auto()    # +$
    DOLLAR_DOLLAR = auto()  # $$
    DOLLAR_EQ = auto()      # $=
    HASH_LBRACK = auto()    # #[

    COLON_QMARK = auto()    # :?
    QMARK_QMARK = auto()    # ??
    QMARK_DOT = auto()      # ?.
    ARROW = auto()          # ->
    FAT_ARROW = auto()      # =>
    LEFT_ARROW = auto()     # <-
    NOT_LEFT_ARROW = auto() # !<-
    PIPE_GT = auto()        # |>
    DOT_DOT = auto()        # ..
    ELLIPSIS = auto()       # ...

    PCT_TILDE = auto()      # %~
    PCT_QMARK = auto()      # %?
    PCT_COLON = auto()      # %:

    CARET_STAR_STAR = auto()# ^**
    CARET_STAR = auto()     # ^*
    CARET_BANG = auto()     # ^!
    CARET_GT = auto()       # ^>
    CARET_EQ = auto()       # ^=

    BANG_BANG = auto()      # !!
    BANG_COLON = auto()     # !:
    BANG_CARET = auto()     # !^
    BANG_QMARK = auto()     # !?
    BANG_AMP = auto()       # !&
    BANG_TILDE_AMP = auto() # !~&

    TILDE_PIPE = auto()     # ~|
    COLON_EQ = auto()       # :=

    # Comparisons & Logical
    EQ_EQ_EQ = auto()       # ===
    BANG_EQ_EQ = auto()     # !==
    EQ_EQ = auto()          # ==
    BANG_EQ = auto()        # !=
    LT_EQ = auto()          # <=
    GT_EQ = auto()          # >=
    AMP_AMP = auto()        # &&
    PIPE_PIPE = auto()      # ||
    LSHIFT = auto()         # <<
    RSHIFT = auto()         # >>
    STAR_STAR = auto()      # **
    SLASH_SLASH = auto()    # //

    # Augmented assignment
    PLUS_EQ = auto()        # +=
    MINUS_EQ = auto()       # -=
    STAR_EQ = auto()        # *=
    SLASH_EQ = auto()       # /=
    SLASH_SLASH_EQ = auto() # //=
    PCT_EQ = auto()         # %=
    STAR_STAR_EQ = auto()   # **=
    AMP_EQ = auto()         # &=
    PIPE_EQ = auto()        # |=
    CARET_BIT_EQ = auto()   # ^|= (or we handle ^= at expr vs stmt)
    LSHIFT_EQ = auto()      # <<=
    RSHIFT_EQ = auto()      # >>=

    # Single-char tokens
    AT = auto()             # @
    DOLLAR = auto()         # $
    QMARK = auto()          # ?
    COLON = auto()          # :
    PCT = auto()            # %
    CARET = auto()          # ^
    BANG = auto()           # !
    TILDE = auto()          # ~
    HASH = auto()           # #
    DOT = auto()            # .
    EQ = auto()             # =
    PLUS = auto()           # +
    MINUS = auto()          # -
    STAR = auto()           # *
    SLASH = auto()          # /
    AMP = auto()            # &
    PIPE = auto()           # |
    LT = auto()             # <
    GT = auto()             # >

    EOF = auto()


MULTI_CHAR_TOKENS: list[tuple[str, TT]] = [
    # 3-char tokens
    ("~*@", TT.TILDE_STAR_AT),
    ("!<-", TT.NOT_LEFT_ARROW),
    ("^**", TT.CARET_STAR_STAR),
    ("!~&", TT.BANG_TILDE_AMP),
    ("===", TT.EQ_EQ_EQ),
    ("!==", TT.BANG_EQ_EQ),
    ("...", TT.ELLIPSIS),
    ("//=", TT.SLASH_SLASH_EQ),
    ("**=", TT.STAR_STAR_EQ),
    ("<<=", TT.LSHIFT_EQ),
    (">>=", TT.RSHIFT_EQ),
    # 2-char tokens
    ("~@", TT.TILDE_AT),
    ("*@", TT.STAR_AT),
    ("@/", TT.AT_SLASH),
    ("@$", TT.AT_DOLLAR),
    ("@?", TT.AT_QMARK),
    ("@=", TT.AT_EQ),
    ("+@", TT.PLUS_AT),
    ("+$", TT.PLUS_DOLLAR),
    ("$$", TT.DOLLAR_DOLLAR),
    ("$=", TT.DOLLAR_EQ),
    ("#[", TT.HASH_LBRACK),
    (":?", TT.COLON_QMARK),
    ("??", TT.QMARK_QMARK),
    ("?.", TT.QMARK_DOT),
    ("->", TT.ARROW),
    ("=>", TT.FAT_ARROW),
    ("<-", TT.LEFT_ARROW),
    ("|>", TT.PIPE_GT),
    ("..", TT.DOT_DOT),
    ("%~", TT.PCT_TILDE),
    ("%?", TT.PCT_QMARK),
    ("%:", TT.PCT_COLON),
    ("^*", TT.CARET_STAR),
    ("^!", TT.CARET_BANG),
    ("^>", TT.CARET_GT),
    ("^=", TT.CARET_EQ),
    ("!!", TT.BANG_BANG),
    ("!:", TT.BANG_COLON),
    ("!^", TT.BANG_CARET),
    ("!?", TT.BANG_QMARK),
    ("!&", TT.BANG_AMP),
    ("~|", TT.TILDE_PIPE),
    (":=", TT.COLON_EQ),
    ("==", TT.EQ_EQ),
    ("!=", TT.BANG_EQ),
    ("<=", TT.LT_EQ),
    (">=", TT.GT_EQ),
    ("&&", TT.AMP_AMP),
    ("||", TT.PIPE_PIPE),
    ("<<", TT.LSHIFT),
    (">>", TT.RSHIFT),
    ("**", TT.STAR_STAR),
    ("//", TT.SLASH_SLASH),
    ("+=", TT.PLUS_EQ),
    ("-=", TT.MINUS_EQ),
    ("*=", TT.STAR_EQ),
    ("/=", TT.SLASH_EQ),
    ("%=", TT.PCT_EQ),
    ("&=", TT.AMP_EQ),
    ("|=", TT.PIPE_EQ),
]

# Sigils that introduce a definition and are only valid at the start of a
# statement. When they appear mid-expression the lexer falls through to the
# single-character operator (e.g. `1+@max(...)` -> `1 + @max(...)`).
STATEMENT_ONLY_SIGILS = {"+@", "+$", "*@", "~@", "~*@"}


SINGLE_CHAR_TOKENS: dict[str, TT] = {
    "(": TT.LPAREN,
    ")": TT.RPAREN,
    "[": TT.LBRACK,
    "]": TT.RBRACK,
    "{": TT.LBRACE,
    "}": TT.RBRACE,
    ",": TT.COMMA,
    ";": TT.SEMI,
    "@": TT.AT,
    "$": TT.DOLLAR,
    "?": TT.QMARK,
    ":": TT.COLON,
    "%": TT.PCT,
    "^": TT.CARET,
    "!": TT.BANG,
    "~": TT.TILDE,
    "#": TT.HASH,
    ".": TT.DOT,
    "=": TT.EQ,
    "+": TT.PLUS,
    "-": TT.MINUS,
    "*": TT.STAR,
    "/": TT.SLASH,
    "&": TT.AMP,
    "|": TT.PIPE,
    "<": TT.LT,
    ">": TT.GT,
}


@dataclass
class Token:
    type: TT
    value: str
    line: int
    col: int
    preceded_by_space: bool = False


class LexError(Exception):
    def __init__(self, msg: str, line: int, col: int):
        super().__init__(f"LexError at {line}:{col}: {msg}")
        self.line = line
        self.col = col


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    n = len(source)
    i = 0
    line = 1
    col = 1
    paren_depth = 0  # Tracks (), [] depth (not {} since {} are statement blocks too)
    had_space = True
    at_stmt_start = True

    while i < n:
        ch = source[i]

        # Spaces and tabs
        if ch in (" ", "\t", "\r"):
            had_space = True
            i += 1
            col += 1
            continue

        # Newlines
        if ch == "\n":
            had_space = True
            if paren_depth == 0:
                if tokens and tokens[-1].type != TT.NEWLINE:
                    tokens.append(Token(TT.NEWLINE, "\n", line, col, True))
                at_stmt_start = True
            i += 1
            line += 1
            col = 1
            continue

        # Line continuation \
        if ch == "\\" and i + 1 < n and source[i + 1] == "\n":
            i += 2
            line += 1
            col = 1
            had_space = True
            continue

        # Comments: `# ...` when at start of line or preceded by space/delimiter and followed by space
        # Note: `#x` is `len(x)` and `#[` is decorator!
        # So `# ` or `##` or `#\n` is a comment.
        if ch == "#" and (i + 1 >= n or source[i + 1] in (" ", "\t", "#", "\n")):
            while i < n and source[i] != "\n":
                i += 1
            continue

        # Raw strings: _"..." or _'...'
        if ch == "_" and i + 1 < n and source[i + 1] in ('"', "'"):
            start_col = col
            i += 1
            col += 1
            s_val, i, line, col = _read_string(source, i, line, col, raw=True)
            tokens.append(Token(TT.RAW_STR, s_val, line, start_col, had_space))
            had_space = False
            at_stmt_start = False
            continue

        # Byte literals: 0b"..." or 0b'...'
        if ch == "0" and i + 2 < n and source[i + 1] in ("b", "B") and source[i + 2] in ('"', "'"):
            start_col = col
            i += 2
            col += 2
            s_val, i, line, col = _read_string(source, i, line, col, raw=False)
            tokens.append(Token(TT.BYTES, s_val, line, start_col, had_space))
            had_space = False
            at_stmt_start = False
            continue

        # Strings: "..." or '...'
        if ch in ('"', "'"):
            start_col = col
            s_val, i, line, col = _read_string(source, i, line, col, raw=False)
            tokens.append(Token(TT.STR, s_val, line, start_col, had_space))
            had_space = False
            at_stmt_start = False
            continue

        # Template / F-Strings: `...`
        if ch == "`":
            start_col = col
            start_line = line
            i += 1
            col += 1
            buf = []
            while i < n and source[i] != "`":
                if source[i] == "\\" and i + 1 < n:
                    buf.append(source[i : i + 2])
                    i += 2
                    col += 2
                else:
                    if source[i] == "\n":
                        line += 1
                        col = 1
                    else:
                        col += 1
                    buf.append(source[i])
                    i += 1
            if i >= n:
                raise LexError("Unterminated template string (`...`)", start_line, start_col)
            i += 1
            col += 1
            tokens.append(Token(TT.FSTR, "".join(buf), start_line, start_col, had_space))
            had_space = False
            at_stmt_start = False
            continue

        # Numbers
        if ch.isdigit():
            start_col = col
            start_i = i
            is_float = False
            if ch == "0" and i + 1 < n and source[i + 1] in ("x", "X", "o", "O", "b", "B"):
                i += 2
                col += 2
                while i < n and (source[i].isalnum() or source[i] == "_"):
                    i += 1
                    col += 1
            else:
                while i < n and (source[i].isdigit() or source[i] == "_"):
                    i += 1
                    col += 1
                # Check decimal point (make sure it's not `..` range operator!)
                if i < n and source[i] == "." and (i + 1 >= n or source[i + 1] != "."):
                    if i + 1 < n and source[i + 1].isdigit():
                        is_float = True
                        i += 1
                        col += 1
                        while i < n and (source[i].isdigit() or source[i] == "_"):
                            i += 1
                            col += 1
                # Exponent
                if i < n and source[i] in ("e", "E"):
                    is_float = True
                    i += 1
                    col += 1
                    if i < n and source[i] in ("+", "-"):
                        i += 1
                        col += 1
                    while i < n and (source[i].isdigit() or source[i] == "_"):
                        i += 1
                        col += 1
            num_str = source[start_i:i]
            tokens.append(Token(TT.FLOAT if is_float else TT.INT, num_str, line, start_col, had_space))
            had_space = False
            at_stmt_start = False
            continue

        # Identifiers
        if ch.isalpha() or ch == "_":
            start_col = col
            start_i = i
            while i < n and (source[i].isalnum() or source[i] == "_"):
                i += 1
                col += 1
            ident_str = source[start_i:i]
            tokens.append(Token(TT.IDENT, ident_str, line, start_col, had_space))
            had_space = False
            at_stmt_start = False
            continue

        # Multi-character operators & sigils
        matched_multi = False
        for pat, tt in MULTI_CHAR_TOKENS:
            # Definition sigils starting with `+`, `*`, or `~` are only valid at
            # statement start. Inside expressions they must split back into the
            # operator plus `@`/`$` so e.g. `1+@max(2, 3)` works.
            if pat in STATEMENT_ONLY_SIGILS and not at_stmt_start:
                continue
            if source.startswith(pat, i):
                tokens.append(Token(tt, pat, line, col, had_space))
                if tt == TT.HASH_LBRACK:
                    paren_depth += 1
                i += len(pat)
                col += len(pat)
                had_space = False
                matched_multi = True
                at_stmt_start = False
                break
        if matched_multi:
            continue

        # Single-character tokens
        if ch in SINGLE_CHAR_TOKENS:
            tt = SINGLE_CHAR_TOKENS[ch]
            if tt in (TT.LPAREN, TT.LBRACK):
                paren_depth += 1
            elif tt in (TT.RPAREN, TT.RBRACK):
                paren_depth = max(0, paren_depth - 1)
            tokens.append(Token(tt, ch, line, col, had_space))
            i += 1
            col += 1
            had_space = False
            at_stmt_start = tt in (TT.SEMI, TT.LBRACE)
            continue

        raise LexError(f"Unexpected character {ch!r}", line, col)

    tokens.append(Token(TT.EOF, "", line, col, True))
    return tokens


def _read_string(source: str, i: int, line: int, col: int, raw: bool) -> tuple[str, int, int, int]:
    quote = source[i]
    start_line, start_col = line, col
    n = len(source)

    # Check triple quotes
    if source.startswith(quote * 3, i):
        delim = quote * 3
        i += 3
        col += 3
    else:
        delim = quote
        i += 1
        col += 1

    buf: list[str] = []
    while i < n and not source.startswith(delim, i):
        ch = source[i]
        if ch == "\\" and i + 1 < n:
            if raw:
                buf.append(source[i : i + 2])
            else:
                esc = source[i + 1]
                esc_map = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"', "0": "\0"}
                buf.append(esc_map.get(esc, "\\" + esc))
            i += 2
            col += 2
        else:
            if ch == "\n":
                line += 1
                col = 1
            else:
                col += 1
            buf.append(ch)
            i += 1

    if i >= n:
        raise LexError(f"Unterminated string literal ({delim})", start_line, start_col)

    i += len(delim)
    col += len(delim)
    return "".join(buf), i, line, col
