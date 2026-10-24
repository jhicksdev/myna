"""Recursive-descent and Pratt parser for the Myna programming language."""

from __future__ import annotations
from typing import Optional, Union

from myna.lexer import TT, Token, tokenize
from myna.targets import VALID_TARGETS
import myna.ast_nodes as ast


class ParseError(Exception):
    def __init__(self, msg: str, token: Token, filename: str | None = None):
        self.msg = msg
        self.token = token
        self.filename = filename
        location = f"{filename}:{token.line}:{token.col}" if filename else f"{token.line}:{token.col}"
        super().__init__(f"ParseError at {location} (near {token.value!r}): {msg}")


AUG_ASSIGN_TOKENS = {
    TT.EQ: "=",
    TT.COLON_EQ: ":=",
    TT.PLUS_EQ: "+=",
    TT.MINUS_EQ: "-=",
    TT.STAR_EQ: "*=",
    TT.SLASH_EQ: "/=",
    TT.SLASH_SLASH_EQ: "//=",
    TT.PCT_EQ: "%=",
    TT.STAR_STAR_EQ: "**=",
    TT.AMP_EQ: "&=",
    TT.PIPE_EQ: "|=",
    TT.CARET_EQ: "^=",
    TT.LSHIFT_EQ: "<<=",
    TT.RSHIFT_EQ: ">>=",
}

STMT_TERMINATORS = {TT.NEWLINE, TT.SEMI, TT.RBRACE, TT.EOF}


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def cur(self) -> Token:
        return self.tokens[self.pos]

    def peek(self, offset: int = 1) -> Token:
        idx = min(self.pos + offset, len(self.tokens) - 1)
        return self.tokens[idx]

    def at(self, *types: TT) -> bool:
        return self.cur().type in types

    def match(self, *types: TT) -> Optional[Token]:
        if self.cur().type in types:
            tok = self.cur()
            self.pos += 1
            return tok
        return None

    def expect(self, tt: TT, msg: str = "") -> Token:
        if self.cur().type == tt:
            tok = self.cur()
            self.pos += 1
            return tok
        expected = msg or tt.name
        raise ParseError(f"Expected {expected}, got {self.cur().type.name}", self.cur())

    def skip_seps(self) -> None:
        while self.at(TT.NEWLINE, TT.SEMI):
            self.pos += 1

    def skip_newlines(self) -> None:
        while self.at(TT.NEWLINE):
            self.pos += 1

    def at_stmt_end(self) -> bool:
        return self.cur().type in STMT_TERMINATORS

    # ========================================================================
    # Top-level & Blocks
    # ========================================================================

    def parse_module(self) -> ast.Module:
        stmts: list[ast.Stmt] = []
        module_targets: Optional[set[str]] = None
        self.skip_seps()
        while not self.at(TT.EOF):
            if self._at_target_directive():
                tok = self.cur()
                targets = self._parse_target_clause()
                self.skip_newlines()
                if self.at(TT.LBRACE):
                    body = self.parse_block()
                    stmts.append(ast.TargetBlock(targets=targets, body=body, line=tok.line, col=tok.col))
                else:
                    if module_targets is not None:
                        raise ParseError("duplicate @target module declaration", tok)
                    if any(not self._is_docstring_stmt(stmt) for stmt in stmts):
                        raise ParseError("@target module declaration must precede all code", tok)
                    module_targets = targets
            else:
                stmts.append(self.parse_stmt())
            self.skip_seps()
        return ast.Module(body=stmts, targets=module_targets, line=1, col=1)

    def _at_target_directive(self) -> bool:
        return (
            self.at(TT.AT)
            and self.peek().type == TT.IDENT
            and self.peek().value == "target"
            and self.peek(2).type == TT.LPAREN
        )

    def _parse_target_clause(self) -> set[str]:
        tok = self.expect(TT.AT)
        self.expect(TT.IDENT)
        self.expect(TT.LPAREN, "'(' after @target")
        targets: set[str] = set()
        while not self.at(TT.RPAREN, TT.EOF):
            self.skip_newlines()
            name = self.expect(TT.IDENT, "target name").value
            if name not in VALID_TARGETS:
                allowed = ", ".join(sorted(VALID_TARGETS))
                raise ParseError(f"unknown target {name!r}; expected one of: {allowed}", tok)
            targets.add(name)
            self.skip_newlines()
            if not self.match(TT.COMMA):
                break
        self.expect(TT.RPAREN, "')' after target list")
        if not targets:
            raise ParseError("@target requires at least one target", tok)
        return targets

    @staticmethod
    def _is_docstring_stmt(stmt: ast.Stmt) -> bool:
        return (
            isinstance(stmt, ast.ExprStmt)
            and isinstance(stmt.expr, ast.Literal)
            and stmt.expr.kind in ("str", "raw_str")
        )

    def parse_block(self) -> list[ast.Stmt]:
        self.skip_newlines()
        if self.match(TT.FAT_ARROW):
            tok = self.cur()
            if self.at(
                TT.CARET,
                TT.CARET_STAR,
                TT.CARET_STAR_STAR,
                TT.CARET_BANG,
                TT.CARET_GT,
                TT.BANG_CARET,
                TT.BANG_QMARK,
                TT.TILDE,
            ):
                return [self.parse_stmt()]
            expr = self.parse_expr_list()
            if self.cur().type in AUG_ASSIGN_TOKENS:
                op_tok = self.cur()
                op_str = AUG_ASSIGN_TOKENS[op_tok.type]
                self.pos += 1
                rhs = self.parse_expr_list()
                return [ast.AssignStmt(targets=[expr], value=rhs, type_ann=None, op=op_str, line=tok.line, col=tok.col)]
            return [ast.ExprStmt(expr=expr, line=tok.line, col=tok.col)]

        self.expect(TT.LBRACE, "'{' to start block")
        stmts: list[ast.Stmt] = []
        self.skip_seps()
        while not self.at(TT.RBRACE, TT.EOF):
            stmts.append(self.parse_stmt())
            self.skip_seps()
        self.expect(TT.RBRACE, "'}' to close block")
        return stmts

    # ========================================================================
    # Statements
    # ========================================================================

    def _combine_definition_sigil(self) -> None:
        """Join adjacent definition sigils that follow a same-line `}`.

        The lexer only emits `+@`, `*@`, `~@`, etc. at obvious statement
        starts. After a closing block brace on the same line it emits the
        operator and `@`/`$` separately; this restores the combined token when
        they are adjacent and a definition follows.
        """
        tok = self.cur()
        combined: Optional[TT] = None
        extra = 0
        if tok.type == TT.PLUS:
            nxt = self.peek()
            if not nxt.preceded_by_space and nxt.type in (TT.AT, TT.DOLLAR):
                combined = TT.PLUS_AT if nxt.type == TT.AT else TT.PLUS_DOLLAR
                extra = 1
        elif tok.type == TT.STAR:
            nxt = self.peek()
            if not nxt.preceded_by_space and nxt.type == TT.AT:
                combined = TT.STAR_AT
                extra = 1
        elif tok.type == TT.TILDE:
            nxt = self.peek()
            if not nxt.preceded_by_space and nxt.type == TT.AT:
                combined = TT.TILDE_AT
                extra = 1
            elif not nxt.preceded_by_space and nxt.type == TT.STAR:
                after = self.peek(2)
                if not after.preceded_by_space and after.type == TT.AT:
                    combined = TT.TILDE_STAR_AT
                    extra = 2

        if combined is not None:
            self.tokens[self.pos] = Token(
                combined,
                tok.value + "".join(t.value for t in self.tokens[self.pos + 1 : self.pos + 1 + extra]),
                tok.line,
                tok.col,
                tok.preceded_by_space,
            )
            del self.tokens[self.pos + 1 : self.pos + 1 + extra]

    def parse_stmt(self, decorators: Optional[list[ast.Expr]] = None) -> ast.Stmt:
        self.skip_seps()
        self._combine_definition_sigil()
        tok = self.cur()

        if self._at_target_directive():
            raise ParseError("@target is only allowed at module level", tok)

        # Decorators: #[dec1, dec2]
        if tok.type == TT.HASH_LBRACK:
            decs = self.parse_decorators()
            self.skip_newlines()
            return self.parse_stmt(decorators=decs)

        # Standalone `_` in a statement -> `pass` (unless followed by `=` or `,` etc.)
        if tok.type == TT.IDENT and tok.value == "_" and self.peek().type in STMT_TERMINATORS:
            self.pos += 1
            return ast.NoopStmt(line=tok.line, col=tok.col)

        # Function / Method / Main Guard definitions:
        # @, ~@, *@, ~*@, @/, @$, @?, @=, +@
        if tok.type in (
            TT.AT,
            TT.TILDE_AT,
            TT.STAR_AT,
            TT.TILDE_STAR_AT,
            TT.AT_SLASH,
            TT.AT_DOLLAR,
            TT.AT_QMARK,
            TT.PLUS_AT,
        ):
            # Check `@main { ... }`
            if tok.type == TT.AT and self.peek().type == TT.IDENT and self.peek().value == "main" and self.peek(2).type == TT.LBRACE:
                self.pos += 2
                body = self.parse_block()
                return ast.MainGuardStmt(body=body, line=tok.line, col=tok.col)
            return self.parse_func_def(decorators=decorators or [])

        # `@=` can be either `@= x, y` (global declaration) or `@=prop(v) { ... }` (property setter)
        if tok.type == TT.AT_EQ:
            if self.peek().type == TT.IDENT and self.peek(2).type == TT.LPAREN:
                return self.parse_func_def(decorators=decorators or [])
            return self.parse_global_stmt()

        # `^=` at statement start -> `nonlocal x, y`
        if tok.type == TT.CARET_EQ:
            return self.parse_nonlocal_stmt()

        # Class / Dataclass / Type Alias: $, $$, +$, $=
        if tok.type in (TT.DOLLAR, TT.DOLLAR_DOLLAR, TT.PLUS_DOLLAR):
            return self.parse_class_def(decorators=decorators or [])
        if tok.type == TT.DOLLAR_EQ:
            return self.parse_type_alias()

        # Conditionals & Match: ? cond { ... }, ?.attr { ... }, ?? subject { ... }
        if tok.type in (TT.QMARK, TT.QMARK_DOT):
            return self.parse_if_stmt()
        if tok.type == TT.QMARK_QMARK:
            return self.parse_match_stmt()

        # Loops: % x <- it { ... }, %~ x <- it { ... }, %? cond { ... }
        if tok.type in (TT.PCT, TT.PCT_TILDE):
            return self.parse_for_stmt()
        if tok.type == TT.PCT_QMARK:
            return self.parse_while_stmt()

        # Flow exit: ^, ^*, ^**, ^!, ^>
        if tok.type == TT.CARET:
            return self.parse_return_stmt()
        if tok.type in (TT.CARET_STAR, TT.CARET_STAR_STAR):
            return self.parse_yield_stmt()
        if tok.type == TT.CARET_BANG:
            self.pos += 1
            return ast.BreakStmt(line=tok.line, col=tok.col)
        if tok.type == TT.CARET_GT:
            self.pos += 1
            return ast.ContinueStmt(line=tok.line, col=tok.col)

        # Error handling & context managers: !{, !^, !?, !&, !~&
        if tok.type == TT.BANG and self.peek().type == TT.LBRACE:
            return self.parse_try_stmt()
        if tok.type == TT.BANG_CARET:
            return self.parse_raise_stmt()
        if tok.type == TT.BANG_QMARK:
            return self.parse_assert_stmt()
        if tok.type in (TT.BANG_AMP, TT.BANG_TILDE_AMP):
            return self.parse_with_stmt()

        # Imports: <mod, <mod:{a, b}
        if tok.type == TT.LT:
            return self.parse_import_stmt()

        # Delete vs Await expression statement: `~x`
        # Note: In Myna, `~del x` or `~x` at statement level:
        # Wait: if someone writes `~async_call()` as a statement, is `~` delete or await?
        # Let's handle both cleanly! If it's `~@del x` or `~x` where `x` is not a call, or let's check:
        # Actually, in Python `await f()` is a very common statement (`~f()`), and `del x[k]` or `del x` is also used.
        # How should we distinguish `await f()` vs `del x` if both start with `~`?
        # If the expression inside `~expr` is a Call (`~f()`), it's ALWAYS an expression statement (`await f()`) because you cannot `del f()` in Python!
        # If the expression inside `~expr` is an Ident, Attribute, or Subscript (`~x`, `~x.a`, `~x[0]`), in statement position `~x[0]` is `del x[0]`!
        # And if someone ever awaits a bare variable at statement level, they can write `(~task)` or `_ = ~task`.
        if tok.type == TT.TILDE:
            return self.parse_tilde_stmt()

        # Otherwise: Assignment or Expression statement
        return self.parse_expr_or_assign_stmt()

    def parse_decorators(self) -> list[ast.Expr]:
        self.expect(TT.HASH_LBRACK)
        decs: list[ast.Expr] = []
        while not self.at(TT.RBRACK, TT.EOF):
            self.skip_newlines()
            decs.append(self.parse_expr())
            self.skip_newlines()
            if not self.match(TT.COMMA):
                break
        self.expect(TT.RBRACK, "']' after decorator list")
        return decs

    def parse_func_def(self, decorators: list[ast.Expr]) -> ast.FuncDef:
        tok = self.cur()
        self.pos += 1

        is_async = tok.type in (TT.TILDE_AT, TT.TILDE_STAR_AT)
        is_generator = tok.type in (TT.STAR_AT, TT.TILDE_STAR_AT)
        exported = tok.type == TT.PLUS_AT
        method_kind = "normal"
        if tok.type == TT.AT_SLASH:
            method_kind = "static"
        elif tok.type == TT.AT_DOLLAR:
            method_kind = "classmethod"
        elif tok.type == TT.AT_QMARK:
            method_kind = "property"
        elif tok.type == TT.AT_EQ:
            method_kind = "setter"

        # Allow `@~` or `+@~` combinations if written sequentially
        if self.match(TT.TILDE):
            is_async = True

        name_tok = self.expect(TT.IDENT, "function name")
        name = name_tok.value
        if name == "init" and method_kind == "normal":
            method_kind = "init"

        params: list[ast.Param] = []
        if self.match(TT.LPAREN):
            params = self.parse_param_list()
            self.expect(TT.RPAREN, "')' after parameters")

        return_type: Optional[ast.TypeNode] = None
        if self.match(TT.ARROW):
            return_type = self.parse_type()

        self.skip_newlines()
        if self.match(TT.FAT_ARROW):
            expr = self.parse_expr_list()
            body: list[ast.Stmt] = [ast.ReturnStmt(value=expr, line=tok.line, col=tok.col)]
        else:
            body = self.parse_block()
        return ast.FuncDef(
            name=name,
            params=params,
            return_type=return_type,
            body=body,
            decorators=decorators,
            is_async=is_async,
            is_generator=is_generator,
            method_kind=method_kind,
            exported=exported,
            line=tok.line,
            col=tok.col,
        )

    def parse_param_list(self) -> list[ast.Param]:
        params: list[ast.Param] = []
        self.skip_newlines()
        while not self.at(TT.RPAREN, TT.EOF):
            self.skip_newlines()
            kind = "normal"
            if self.match(TT.STAR_STAR):
                kind = "kwarg"
            elif self.match(TT.STAR):
                if self.at(TT.COMMA, TT.RPAREN):
                    params.append(ast.Param(name="*", kind="kwonly_sep"))
                    self.match(TT.COMMA)
                    self.skip_newlines()
                    continue
                kind = "vararg"
            elif self.match(TT.SLASH):
                params.append(ast.Param(name="/", kind="posonly_sep"))
                self.match(TT.COMMA)
                self.skip_newlines()
                continue

            p_name = self.expect(TT.IDENT, "parameter name").value
            type_ann: Optional[ast.TypeNode] = None
            default: Optional[ast.Expr] = None

            if self.match(TT.COLON):
                type_ann = self.parse_type()
            if self.match(TT.EQ):
                default = self.parse_expr()

            params.append(ast.Param(name=p_name, type_ann=type_ann, default=default, kind=kind))
            self.skip_newlines()
            if not self.match(TT.COMMA):
                break
        return params

    def parse_class_def(self, decorators: list[ast.Expr]) -> ast.ClassDef:
        tok = self.cur()
        self.pos += 1
        is_dataclass = tok.type == TT.DOLLAR_DOLLAR
        exported = tok.type == TT.PLUS_DOLLAR
        if exported and self.match(TT.DOLLAR):
            is_dataclass = True

        name = self.expect(TT.IDENT, "class name").value
        fields: list[ast.Param] = []
        bases: list[ast.Expr] = []

        # Dataclass fields: $$User(id:i, name:s="anon")
        if self.match(TT.LPAREN):
            fields = self.parse_param_list()
            self.expect(TT.RPAREN, "')' after class fields")
            is_dataclass = True

        # Inheritance: $Child < Base1, Base2
        if self.match(TT.LT):
            bases.append(self.parse_expr(stop_before_lbrace=True))
            while self.match(TT.COMMA):
                bases.append(self.parse_expr(stop_before_lbrace=True))

        body: list[ast.Stmt] = []
        self.skip_newlines()
        if self.at(TT.LBRACE):
            body = self.parse_block()

        return ast.ClassDef(
            name=name,
            bases=bases,
            fields=fields,
            body=body,
            decorators=decorators,
            is_dataclass=is_dataclass,
            exported=exported,
            line=tok.line,
            col=tok.col,
        )

    def parse_type_alias(self) -> ast.TypeAliasStmt:
        tok = self.expect(TT.DOLLAR_EQ)
        name = self.expect(TT.IDENT, "type alias name").value
        self.expect(TT.EQ, "'=' in type alias")
        val = self.parse_type()
        return ast.TypeAliasStmt(name=name, value=val, line=tok.line, col=tok.col)

    def parse_global_stmt(self) -> ast.ScopeStmt:
        tok = self.expect(TT.AT_EQ)
        names = [self.expect(TT.IDENT, "variable name").value]
        while self.match(TT.COMMA):
            names.append(self.expect(TT.IDENT, "variable name").value)
        return ast.ScopeStmt(kind="global", names=names, line=tok.line, col=tok.col)

    def parse_nonlocal_stmt(self) -> ast.ScopeStmt:
        tok = self.expect(TT.CARET_EQ)
        names = [self.expect(TT.IDENT, "variable name").value]
        while self.match(TT.COMMA):
            names.append(self.expect(TT.IDENT, "variable name").value)
        return ast.ScopeStmt(kind="nonlocal", names=names, line=tok.line, col=tok.col)

    def parse_if_stmt(self) -> ast.IfStmt:
        tok = self.cur()
        if tok.type == TT.QMARK_DOT:
            # `?.attr ...` -> `if .attr ...`
            self.tokens[self.pos] = Token(TT.DOT, ".", tok.line, tok.col + 1, False)
        else:
            self.expect(TT.QMARK)
        # A parenthesized tuple followed by `=>` opens the branch block, not a
        # lambda: `? (a, b) => ...`. Bare lambdas as the whole condition are
        # ambiguous, so parenthesize them inside another expression instead.
        cond = self.parse_expr(stop_before_lbrace=True, allow_paren_lambda=False)
        body = self.parse_block()
        branches = [ast.IfBranch(cond=cond, body=body)]
        else_body: Optional[list[ast.Stmt]] = None

        while True:
            saved_pos = self.pos
            self.skip_newlines()
            if self.match(TT.COLON_QMARK):
                if self.at(TT.DOT):
                    pass
                elif_cond = self.parse_expr(stop_before_lbrace=True)
                elif_body = self.parse_block()
                branches.append(ast.IfBranch(cond=elif_cond, body=elif_body))
            elif self.match(TT.COLON):
                if self.at(TT.QMARK, TT.QMARK_DOT):
                    if self.cur().type == TT.QMARK_DOT:
                        t2 = self.cur()
                        self.tokens[self.pos] = Token(TT.DOT, ".", t2.line, t2.col + 1, False)
                    else:
                        self.pos += 1
                    elif_cond = self.parse_expr(stop_before_lbrace=True)
                    elif_body = self.parse_block()
                    branches.append(ast.IfBranch(cond=elif_cond, body=elif_body))
                else:
                    else_body = self.parse_block()
                    break
            else:
                self.pos = saved_pos
                break

        return ast.IfStmt(branches=branches, else_body=else_body, line=tok.line, col=tok.col)

    def parse_match_stmt(self) -> ast.MatchStmt:
        tok = self.expect(TT.QMARK_QMARK)
        subject = self.parse_expr(stop_before_lbrace=True)
        self.skip_newlines()
        self.expect(TT.LBRACE, "'{' for match cases")
        cases: list[ast.MatchCase] = []
        self.skip_seps()
        while not self.at(TT.RBRACE, TT.EOF):
            pat = self.parse_expr(min_bp=25, stop_before_lbrace=True)  # Stop before `?` guard or `=>`
            guard: Optional[ast.Expr] = None
            if self.match(TT.QMARK):
                guard = self.parse_expr(stop_before_lbrace=True)
            self.expect(TT.FAT_ARROW, "'=>' in match case")
            if not self.at(TT.RBRACE, TT.EOF):
                if self.at(TT.LBRACE):
                    c_body = self.parse_block()
                else:
                    c_body = [self.parse_stmt()]
            else:
                c_body = [ast.NoopStmt()]
            cases.append(ast.MatchCase(pattern=pat, guard=guard, body=c_body))
            self.skip_seps()
        self.expect(TT.RBRACE, "'}' after match cases")
        return ast.MatchStmt(subject=subject, cases=cases, line=tok.line, col=tok.col)

    def parse_for_stmt(self) -> ast.ForStmt:
        tok = self.cur()
        is_async = tok.type == TT.PCT_TILDE
        self.pos += 1

        target = self.parse_target_list()
        self.expect(TT.LEFT_ARROW, "'<-' in for loop")
        iter_expr = self.parse_expr(stop_before_lbrace=True)
        body = self.parse_block()

        else_body: Optional[list[ast.Stmt]] = None
        saved_pos = self.pos
        self.skip_newlines()
        if self.match(TT.PCT_COLON):
            else_body = self.parse_block()
        else:
            self.pos = saved_pos

        return ast.ForStmt(
            target=target,
            iter=iter_expr,
            body=body,
            else_body=else_body,
            is_async=is_async,
            line=tok.line,
            col=tok.col,
        )

    def parse_while_stmt(self) -> ast.WhileStmt:
        tok = self.expect(TT.PCT_QMARK)
        cond = self.parse_expr(stop_before_lbrace=True, allow_paren_lambda=False)
        body = self.parse_block()

        else_body: Optional[list[ast.Stmt]] = None
        saved_pos = self.pos
        self.skip_newlines()
        if self.match(TT.PCT_COLON):
            else_body = self.parse_block()
        else:
            self.pos = saved_pos

        return ast.WhileStmt(cond=cond, body=body, else_body=else_body, line=tok.line, col=tok.col)

    def parse_return_stmt(self) -> ast.ReturnStmt:
        tok = self.expect(TT.CARET)
        if self.at_stmt_end():
            return ast.ReturnStmt(value=None, line=tok.line, col=tok.col)
        val = self.parse_expr_list()
        return ast.ReturnStmt(value=val, line=tok.line, col=tok.col)

    def parse_yield_stmt(self) -> ast.YieldStmt:
        tok = self.cur()
        is_from = tok.type == TT.CARET_STAR_STAR
        self.pos += 1
        if self.at_stmt_end():
            return ast.YieldStmt(value=None, is_from=is_from, line=tok.line, col=tok.col)
        val = self.parse_expr_list()
        return ast.YieldStmt(value=val, is_from=is_from, line=tok.line, col=tok.col)

    def parse_try_stmt(self) -> ast.TryStmt:
        tok = self.expect(TT.BANG)
        body = self.parse_block()
        handlers: list[ast.ExceptHandler] = []
        else_body: Optional[list[ast.Stmt]] = None
        finally_body: Optional[list[ast.Stmt]] = None

        while True:
            saved_pos = self.pos
            self.skip_newlines()
            if self.match(TT.BANG_BANG):
                exc_type: Optional[ast.Expr] = None
                name: Optional[str] = None
                if not self.at(TT.LBRACE, TT.FAT_ARROW):
                    if self.match(TT.COLON):
                        exc_type = self.parse_expr(stop_before_lbrace=True)
                    elif self.at(TT.IDENT) and self.peek().type in (TT.COLON, TT.LBRACE, TT.FAT_ARROW):
                        name = self.expect(TT.IDENT).value
                        if self.match(TT.COLON):
                            exc_type = self.parse_expr(stop_before_lbrace=True)
                        else:
                            exc_type = ast.Ident(name="Exception", line=tok.line, col=tok.col)
                    else:
                        exc_type = self.parse_expr(stop_before_lbrace=True)
                h_body = self.parse_block()
                handlers.append(ast.ExceptHandler(exc_type=exc_type, name=name, body=h_body))
            elif self.at(TT.BANG_QMARK) and self.peek().type == TT.LBRACE:
                self.pos += 1
                else_body = self.parse_block()
            elif self.match(TT.BANG_COLON):
                finally_body = self.parse_block()
                break
            else:
                self.pos = saved_pos
                break

        return ast.TryStmt(
            body=body,
            handlers=handlers,
            else_body=else_body,
            finally_body=finally_body,
            line=tok.line,
            col=tok.col,
        )

    def parse_raise_stmt(self) -> ast.RaiseStmt:
        tok = self.expect(TT.BANG_CARET)
        if self.at_stmt_end():
            return ast.RaiseStmt(exc=None, cause=None, line=tok.line, col=tok.col)
        exc = self.parse_expr()
        cause: Optional[ast.Expr] = None
        if self.match(TT.LEFT_ARROW):
            cause = self.parse_expr()
        return ast.RaiseStmt(exc=exc, cause=cause, line=tok.line, col=tok.col)

    def parse_assert_stmt(self) -> ast.AssertStmt:
        tok = self.expect(TT.BANG_QMARK)
        test = self.parse_expr()
        msg: Optional[ast.Expr] = None
        if self.match(TT.COMMA):
            msg = self.parse_expr()
        return ast.AssertStmt(test=test, msg=msg, line=tok.line, col=tok.col)

    def parse_with_stmt(self) -> ast.WithStmt:
        tok = self.cur()
        is_async = tok.type == TT.BANG_TILDE_AMP
        self.pos += 1
        items: list[ast.WithItem] = []

        while True:
            first = self.parse_expr(stop_before_lbrace=True)
            if self.match(TT.EQ):
                ctx_expr = self.parse_expr(stop_before_lbrace=True)
                items.append(ast.WithItem(context_expr=ctx_expr, optional_vars=first))
            else:
                items.append(ast.WithItem(context_expr=first, optional_vars=None))
            if not self.match(TT.COMMA):
                break

        body = self.parse_block()
        return ast.WithStmt(items=items, body=body, is_async=is_async, line=tok.line, col=tok.col)

    def parse_import_stmt(self) -> Union[ast.ImportStmt, ast.ImportFromStmt]:
        tok = self.expect(TT.LT)
        level = 0
        while self.at(TT.DOT, TT.DOT_DOT, TT.ELLIPSIS):
            t = self.cur()
            self.pos += 1
            if t.type == TT.DOT:
                level += 1
            elif t.type == TT.DOT_DOT:
                level += 2
            elif t.type == TT.ELLIPSIS:
                level += 3

        mod_name = self._parse_dotted_name() if self.at(TT.IDENT) else None

        # `<mod:{a, b>alias}` or `<.mod:{a}` or `<.:{a}`
        if self.match(TT.COLON):
            names: list[ast.ImportAlias] = []
            if self.match(TT.STAR):
                names.append(ast.ImportAlias(name="*"))
            elif self.match(TT.LBRACE):
                while not self.at(TT.RBRACE, TT.EOF):
                    self.skip_newlines()
                    if self.match(TT.STAR):
                        names.append(ast.ImportAlias(name="*"))
                    else:
                        n = self.expect(TT.IDENT, "imported symbol").value
                        asname = self.expect(TT.IDENT, "alias").value if self.match(TT.GT) else None
                        names.append(ast.ImportAlias(name=n, asname=asname))
                    self.skip_newlines()
                    if not self.match(TT.COMMA):
                        break
                self.expect(TT.RBRACE, "'}' after import list")
            else:
                n = self.expect(TT.IDENT, "imported symbol").value
                asname = self.expect(TT.IDENT, "alias").value if self.match(TT.GT) else None
                names.append(ast.ImportAlias(name=n, asname=asname))
            return ast.ImportFromStmt(module=mod_name, level=level, names=names, line=tok.line, col=tok.col)

        # Standard `<os, numpy>np`
        if mod_name is None:
            raise ParseError("Expected module name after '<'", self.cur())
        asname = self.expect(TT.IDENT, "module alias").value if self.match(TT.GT) else None
        aliases = [ast.ImportAlias(name=mod_name, asname=asname)]
        while self.match(TT.COMMA):
            m = self._parse_dotted_name()
            a = self.expect(TT.IDENT, "module alias").value if self.match(TT.GT) else None
            aliases.append(ast.ImportAlias(name=m, asname=a))
        return ast.ImportStmt(names=aliases, line=tok.line, col=tok.col)

    def _parse_dotted_name(self) -> str:
        parts = [self.expect(TT.IDENT, "identifier").value]
        while self.match(TT.DOT):
            parts.append(self.expect(TT.IDENT, "identifier").value)
        return ".".join(parts)

    def parse_tilde_stmt(self) -> ast.Stmt:
        tok = self.expect(TT.TILDE)
        expr = self.parse_expr()
        # If it's a function call (e.g. `~asyncio.sleep(1)`), it's an `await` expression statement!
        if isinstance(expr, ast.Call):
            return ast.ExprStmt(
                expr=ast.UnaryOp(op="~", operand=expr, line=tok.line, col=tok.col),
                line=tok.line,
                col=tok.col,
            )
        targets = [expr]
        while self.match(TT.COMMA):
            targets.append(self.parse_expr())
        return ast.DeleteStmt(targets=targets, line=tok.line, col=tok.col)

    def parse_expr_or_assign_stmt(self) -> ast.Stmt:
        tok = self.cur()
        first = self.parse_expr_list()

        # Typed assignment: `x: i = 1`
        if self.match(TT.COLON):
            type_ann = self.parse_type()
            self.expect(TT.EQ, "'=' in typed assignment")
            val = self.parse_expr_list()
            return ast.AssignStmt(targets=[first], value=val, type_ann=type_ann, op="=", line=tok.line, col=tok.col)

        # Augmented or normal or chained assignment: `x = y = 1` or `x += 1`
        if self.cur().type in AUG_ASSIGN_TOKENS:
            op_tok = self.cur()
            op_str = AUG_ASSIGN_TOKENS[op_tok.type]
            self.pos += 1
            targets = [first]
            rhs = self.parse_expr_list()
            while op_str == "=" and self.match(TT.EQ):
                targets.append(rhs)
                rhs = self.parse_expr_list()
            return ast.AssignStmt(targets=targets, value=rhs, type_ann=None, op=op_str, line=tok.line, col=tok.col)

        return ast.ExprStmt(expr=first, line=tok.line, col=tok.col)

    def parse_target_list(self) -> ast.Expr:
        first = self.parse_expr(min_bp=35, stop_before_lbrace=True)
        if self.match(TT.COMMA):
            elts = [first]
            while not self.at(TT.LEFT_ARROW, TT.EQ, TT.EOF):
                elts.append(self.parse_expr(min_bp=35, stop_before_lbrace=True))
                if not self.match(TT.COMMA):
                    break
            return ast.TupleExpr(elts=elts, line=first.line, col=first.col)
        return first

    def parse_expr_list(self) -> ast.Expr:
        first = self.parse_expr()
        if self.match(TT.COMMA):
            elts = [first]
            while not self.at_stmt_end() and self.cur().type not in AUG_ASSIGN_TOKENS:
                elts.append(self.parse_expr())
                if not self.match(TT.COMMA):
                    break
            return ast.TupleExpr(elts=elts, line=first.line, col=first.col)
        return first

    # ========================================================================
    # Type Annotations
    # ========================================================================

    def parse_type(self) -> ast.TypeNode:
        t = self._parse_single_type()
        if self.match(TT.PIPE):
            types = [t]
            types.append(self._parse_single_type())
            while self.match(TT.PIPE):
                types.append(self._parse_single_type())
            return ast.UnionType(types=types, line=t.line, col=t.col)
        return t

    def _parse_single_type(self) -> ast.TypeNode:
        tok = self.cur()
        node: ast.TypeNode

        # List type: [T]
        if self.match(TT.LBRACK):
            elem = self.parse_type()
            self.expect(TT.RBRACK, "']' in list type")
            node = ast.ListType(elem=elem, line=tok.line, col=tok.col)
        # Dict or Set type: {K: V} or {T}
        elif self.match(TT.LBRACE):
            first = self.parse_type()
            if self.match(TT.COLON):
                val = self.parse_type()
                self.expect(TT.RBRACE, "'}' in dict type")
                node = ast.DictType(key=first, value=val, line=tok.line, col=tok.col)
            else:
                self.expect(TT.RBRACE, "'}' in set type")
                node = ast.SetType(elem=first, line=tok.line, col=tok.col)
        # Tuple type: (T1, T2)
        elif self.match(TT.LPAREN):
            elems: list[ast.TypeNode] = []
            while not self.at(TT.RPAREN, TT.EOF):
                elems.append(self.parse_type())
                if not self.match(TT.COMMA):
                    break
            self.expect(TT.RPAREN, "')' in tuple type")
            node = ast.TupleType(elems=elems, line=tok.line, col=tok.col)
        else:
            name = self._parse_dotted_name()
            if self.match(TT.LBRACK):
                args: list[ast.TypeNode] = []
                while not self.at(TT.RBRACK, TT.EOF):
                    args.append(self.parse_type())
                    if not self.match(TT.COMMA):
                        break
                self.expect(TT.RBRACK, "']' in generic type")
                node = ast.GenericType(base=name, args=args, line=tok.line, col=tok.col)
            else:
                node = ast.SimpleType(name=name, line=tok.line, col=tok.col)

        # Optional suffix `?`: e.g. `s?` -> `Optional[str]`
        if self.match(TT.QMARK):
            if isinstance(node, (ast.SimpleType, ast.ListType, ast.DictType, ast.SetType, ast.TupleType, ast.GenericType)):
                node.optional = True

        return node

    # ========================================================================
    # Pratt Expression Parser
    # ========================================================================

    def parse_expr(
        self,
        min_bp: int = 0,
        stop_before_lbrace: bool = False,
        allow_paren_lambda: bool = True,
    ) -> ast.Expr:
        left = self.parse_prefix(
            stop_before_lbrace=stop_before_lbrace,
            allow_paren_lambda=allow_paren_lambda,
        )

        while True:
            tok = self.cur()

            if stop_before_lbrace and tok.type == TT.LBRACE:
                break

            # Single-param lambda: `x => expr` (only when `=>` is NOT being used as a block opener)
            if tok.type == TT.FAT_ARROW and isinstance(left, ast.Ident) and min_bp <= 5 and not stop_before_lbrace:
                self.pos += 1
                body = self.parse_expr(min_bp=5, stop_before_lbrace=stop_before_lbrace)
                left = ast.Lambda(params=[ast.Param(name=left.name)], body=body, line=left.line, col=left.col)
                continue

            # Walrus operator `:=` inside expressions (e.g. `?(m := pat.match(s)) { ... }`)
            if tok.type == TT.COLON_EQ and min_bp <= 8:
                self.pos += 1
                rhs = self.parse_expr(min_bp=8, stop_before_lbrace=stop_before_lbrace)
                left = ast.NamedExpr(target=left, value=rhs, line=left.line, col=left.col)
                continue

            # Ternary operator: `cond ? true_expr : false_expr`
            if tok.type == TT.QMARK and min_bp <= 10:
                # Only treat `?` as ternary if we are not stopping before `{` with `{` right after, or inside match guard
                if stop_before_lbrace and self._looks_like_guard_or_block():
                    break
                self.pos += 1
                true_expr = self.parse_expr(min_bp=10, stop_before_lbrace=stop_before_lbrace)
                self.expect(TT.COLON, "':' in ternary expression")
                false_expr = self.parse_expr(min_bp=10, stop_before_lbrace=stop_before_lbrace)
                left = ast.TernaryOp(cond=left, true_expr=true_expr, false_expr=false_expr, line=left.line, col=left.col)
                continue

            # Postfix / Call / Attribute / Subscript / Dict Key Access `d$key` / Dict `.get()` `d$?key`
            if tok.type in (TT.LPAREN, TT.LBRACK, TT.DOT, TT.QMARK_DOT) or (
                tok.type == TT.DOLLAR and not tok.preceded_by_space and (self.peek().type == TT.IDENT or (self.peek().type == TT.QMARK and self.peek(2).type == TT.IDENT))
            ):
                # Important: if `[` is on a new line, it's a new statement `[...]`, not a subscript!
                if tok.type in (TT.LPAREN, TT.LBRACK) and self._preceded_by_newline():
                    break
                if min_bp > 90:
                    break
                left = self.parse_postfix(left)
                continue

            # Range operator `a..b` or `a..b..step`
            if tok.type == TT.DOT_DOT and min_bp <= 45:
                self.pos += 1
                stop = self.parse_expr(min_bp=46, stop_before_lbrace=stop_before_lbrace)
                step: Optional[ast.Expr] = None
                if self.match(TT.DOT_DOT):
                    step = self.parse_expr(min_bp=46, stop_before_lbrace=stop_before_lbrace)
                left = ast.RangeExpr(start=left, stop=stop, step=step, line=left.line, col=left.col)
                continue

            # Infix binary / comparison operators
            bp = self._infix_binding_power(tok.type)
            if bp is None:
                break
            l_bp, r_bp = bp
            if l_bp < min_bp:
                break

            # Special case: chained comparisons (`a < b <= c`, `x === N`, `x <- items`)
            if self._is_comparison_token(tok.type):
                ops: list[str] = []
                comparators: list[ast.Expr] = []
                while self._is_comparison_token(self.cur().type):
                    if stop_before_lbrace and self.cur().type == TT.LBRACE:
                        break
                    c_tok = self.cur()
                    self.pos += 1
                    op_str = self._comparison_op_str(c_tok.type)
                    ops.append(op_str)
                    if op_str == ":?":
                        # Right side of `x :? Type` can be a Myna type shorthand (`i`, `s`, `(i, s)`) or expression
                        rhs = self._parse_isinstance_rhs(stop_before_lbrace=stop_before_lbrace)
                    else:
                        rhs = self.parse_expr(
                            min_bp=r_bp,
                            stop_before_lbrace=stop_before_lbrace,
                            allow_paren_lambda=False,
                        )
                    comparators.append(rhs)
                left = ast.CompareOp(left=left, ops=ops, comparators=comparators, line=left.line, col=left.col)
                continue

            self.pos += 1
            right = self.parse_expr(
                min_bp=r_bp,
                stop_before_lbrace=stop_before_lbrace,
                allow_paren_lambda=False,
            )
            if tok.type == TT.PIPE_GT:
                left = ast.PipeExpr(left=left, right=right, line=left.line, col=left.col)
            else:
                left = ast.BinaryOp(op=tok.value, left=left, right=right, line=left.line, col=left.col)

        return left

    def _preceded_by_newline(self) -> bool:
        return self.pos > 0 and self.tokens[self.pos - 1].type == TT.NEWLINE

    def _looks_like_guard_or_block(self) -> bool:
        # In `?? val { pat ? guard => ... }`, `?` is followed by `guard =>`, not `: false_expr`
        look = self.pos + 1
        depth = 0
        while look < len(self.tokens):
            tt = self.tokens[look].type
            if tt in (TT.LPAREN, TT.LBRACK, TT.LBRACE):
                depth += 1
            elif tt in (TT.RPAREN, TT.RBRACK, TT.RBRACE):
                if depth == 0:
                    return True
                depth -= 1
            elif depth == 0:
                if tt == TT.FAT_ARROW:
                    return True
                if tt == TT.COLON:
                    return False
                if tt in (TT.NEWLINE, TT.SEMI, TT.EOF):
                    return True
            look += 1
        return False

    def _parse_isinstance_rhs(self, stop_before_lbrace: bool) -> ast.Expr:
        return self.parse_expr(
            min_bp=41,
            stop_before_lbrace=stop_before_lbrace,
            allow_paren_lambda=False,
        )

    def parse_prefix(self, stop_before_lbrace: bool = False, allow_paren_lambda: bool = True) -> ast.Expr:
        tok = self.cur()

        # Prefix operators: !, -, +, ~, ~|, #, *, **
        if tok.type in (TT.BANG, TT.MINUS, TT.PLUS, TT.TILDE, TT.TILDE_PIPE, TT.HASH, TT.STAR, TT.STAR_STAR):
            self.pos += 1
            operand = self.parse_expr(min_bp=80, stop_before_lbrace=stop_before_lbrace)
            return ast.UnaryOp(op=tok.value, operand=operand, line=tok.line, col=tok.col)

        # Prefix range `..n` (`range(n)`) vs super attribute `..init(...)` / `..attr`
        if tok.type == TT.DOT_DOT:
            # Only treat `..ident` as `super().ident` inside a class or when followed by `(` (`..init(a)`) or `.` (`..m.x`)
            if (
                self.peek().type == TT.IDENT
                and not self.peek().preceded_by_space
                and (self.peek(2).type in (TT.LPAREN, TT.DOT) or self.peek().value == "init")
            ):
                self.pos += 1
                attr = self.expect(TT.IDENT).value
                return ast.SuperAttr(attr=attr, line=tok.line, col=tok.col)
            self.pos += 1
            stop = self.parse_expr(min_bp=46, stop_before_lbrace=stop_before_lbrace)
            return ast.RangeExpr(start=None, stop=stop, step=None, line=tok.line, col=tok.col)

        # Leading dot `.attr` -> `self.attr`
        if tok.type == TT.DOT:
            self.pos += 1
            attr = self.expect(TT.IDENT, "attribute name after '.'").value
            return ast.SelfAttr(attr=attr, line=tok.line, col=tok.col)

        # Ellipsis `...`
        if tok.type == TT.ELLIPSIS:
            self.pos += 1
            return ast.Literal(value="...", kind="ellipsis", line=tok.line, col=tok.col)

        # Built-in `@` call shorthands in expressions: `@enum`, `@zip`, `@map`, `@flt`, `@srt`, `@rev`, `@sum`, `@min`, `@max`, `@str`, `@int`, `@set`, `@list`, `@dict`
        if tok.type == TT.AT and self.peek().type == TT.IDENT:
            self.pos += 1
            ident = self.expect(TT.IDENT)
            return ast.Ident(name="@" + ident.value, line=tok.line, col=tok.col)

        # Numeric, String, Template literals
        if tok.type == TT.INT:
            self.pos += 1
            return ast.Literal(value=int(tok.value.replace("_", ""), 0), kind="int", line=tok.line, col=tok.col)
        if tok.type == TT.FLOAT:
            self.pos += 1
            return ast.Literal(value=float(tok.value.replace("_", "")), kind="float", line=tok.line, col=tok.col)
        if tok.type == TT.STR:
            self.pos += 1
            return ast.Literal(value=tok.value, kind="str", line=tok.line, col=tok.col)
        if tok.type == TT.RAW_STR:
            self.pos += 1
            return ast.Literal(value=tok.value, kind="raw_str", line=tok.line, col=tok.col)
        if tok.type == TT.BYTES:
            self.pos += 1
            return ast.Literal(value=tok.value, kind="bytes", line=tok.line, col=tok.col)
        if tok.type == TT.FSTR:
            self.pos += 1
            return self._parse_fstring(tok)

        # Identifiers & single-char constants (T, F, N, U)
        if tok.type == TT.IDENT:
            self.pos += 1
            if tok.value == "T":
                return ast.Literal(value=True, kind="bool", line=tok.line, col=tok.col)
            if tok.value == "F":
                return ast.Literal(value=False, kind="bool", line=tok.line, col=tok.col)
            if tok.value == "N":
                return ast.Literal(value=None, kind="none", line=tok.line, col=tok.col)
            if tok.value == "U":
                return ast.Literal(value=None, kind="undefined", line=tok.line, col=tok.col)
            return ast.Ident(name=tok.value, line=tok.line, col=tok.col)

        # Parenthesized expression, Tuple, Generator expression, or Multi-param Lambda `(a, b) => ...`
        if tok.type == TT.LPAREN:
            if allow_paren_lambda and self._looks_like_paren_lambda():
                return self.parse_paren_lambda(stop_before_lbrace=stop_before_lbrace)
            return self.parse_paren_or_tuple_or_genexp()

        # List or List Comprehension: `[...]`
        if tok.type == TT.LBRACK:
            return self.parse_list_or_comp()

        # Dict, Set, Dict Comp, or Set Comp: `{...}`
        if tok.type == TT.LBRACE:
            return self.parse_brace_expr()

        raise ParseError(f"Unexpected token {tok.type.name} ({tok.value!r}) in expression", tok)

    def _looks_like_paren_lambda(self) -> bool:
        # Scan ahead from `(` to its matching `)`. It is a lambda only when the
        # contents are a valid parameter list and the `)` is followed by `=>`.
        # A tuple such as `(a.b, c[0])` followed by an arrow block must not be
        # mistaken for `(a, b) => ...`.
        depth = 0
        i = self.pos
        while i < len(self.tokens):
            t = self.tokens[i].type
            if t == TT.LPAREN:
                depth += 1
            elif t == TT.RPAREN:
                depth -= 1
                if depth == 0:
                    if i + 1 >= len(self.tokens) or self.tokens[i + 1].type != TT.FAT_ARROW:
                        return False
                    return self._tokens_look_like_params(self.pos + 1, i)
            i += 1
        return False

    def _tokens_look_like_params(self, start: int, end: int) -> bool:
        """Validate a token slice against the shape accepted by `parse_param_list`."""
        i = start
        while i < end:
            # Bare `*` / `**` separators and typed varargs.
            if self.tokens[i].type in (TT.STAR, TT.STAR_STAR):
                i += 1
                if i < end and self.tokens[i].type == TT.COMMA:
                    i += 1
                    continue
            elif self.tokens[i].type == TT.SLASH:
                i += 1
                if i < end and self.tokens[i].type == TT.COMMA:
                    i += 1
                    continue

            if i >= end or self.tokens[i].type != TT.IDENT:
                return False
            i += 1

            if i < end and self.tokens[i].type == TT.COLON:
                i = self._skip_param_expr(i + 1, end)
                if i is None:
                    return False
            if i < end and self.tokens[i].type == TT.EQ:
                i = self._skip_param_expr(i + 1, end)
                if i is None:
                    return False

            if i < end:
                if self.tokens[i].type != TT.COMMA:
                    return False
                i += 1
        return True

    def _skip_param_expr(self, start: int, end: int) -> Optional[int]:
        """Return the index of the next top-level comma, or None if unbalanced."""
        depth = 0
        i = start
        while i < end:
            tt = self.tokens[i].type
            if tt in (TT.LPAREN, TT.LBRACK, TT.LBRACE):
                depth += 1
            elif tt in (TT.RPAREN, TT.RBRACK, TT.RBRACE):
                if depth == 0:
                    return None
                depth -= 1
            elif tt == TT.COMMA and depth == 0:
                return i
            i += 1
        return i

    def parse_paren_lambda(self, stop_before_lbrace: bool = False) -> ast.Lambda:
        tok = self.expect(TT.LPAREN)
        params = self.parse_param_list()
        self.expect(TT.RPAREN)
        self.expect(TT.FAT_ARROW)
        body = self.parse_expr(min_bp=5, stop_before_lbrace=stop_before_lbrace)
        return ast.Lambda(params=params, body=body, line=tok.line, col=tok.col)

    def parse_paren_or_tuple_or_genexp(self) -> ast.Expr:
        tok = self.expect(TT.LPAREN)
        self.skip_newlines()
        if self.match(TT.RPAREN):
            return ast.TupleExpr(elts=[], line=tok.line, col=tok.col)

        first = self.parse_expr()
        self.skip_newlines()

        # Generator comprehension: `(expr | x <- it ? cond)`
        if self.at(TT.PIPE) and self._looks_like_comp_clause():
            self.pos += 1
            clauses = self.parse_comp_clauses(TT.RPAREN)
            self.expect(TT.RPAREN, "')' after generator comprehension")
            return ast.GenExp(elt=first, clauses=clauses, line=tok.line, col=tok.col)

        # Tuple: `(a,)` or `(a, b)`
        if self.match(TT.COMMA):
            elts = [first]
            self.skip_newlines()
            while not self.at(TT.RPAREN, TT.EOF):
                elts.append(self.parse_expr())
                self.skip_newlines()
                if not self.match(TT.COMMA):
                    break
                self.skip_newlines()
            self.expect(TT.RPAREN, "')' after tuple")
            return ast.TupleExpr(elts=elts, line=tok.line, col=tok.col)

        self.expect(TT.RPAREN, "')'")
        return first

    def parse_list_or_comp(self) -> ast.Expr:
        tok = self.expect(TT.LBRACK)
        self.skip_newlines()
        if self.match(TT.RBRACK):
            return ast.ListExpr(elts=[], line=tok.line, col=tok.col)

        # Notice: inside `[elt | x <- it]`, `|` could be parsed as bitwise OR if we don't stop before `|` when it's a comprehension!
        first = self.parse_expr_stopping_at_comp_pipe()
        self.skip_newlines()

        if self.match(TT.PIPE):
            clauses = self.parse_comp_clauses(TT.RBRACK)
            self.expect(TT.RBRACK, "']' after list comprehension")
            return ast.ListComp(elt=first, clauses=clauses, line=tok.line, col=tok.col)

        elts = [first]
        while self.match(TT.COMMA):
            self.skip_newlines()
            if self.at(TT.RBRACK):
                break
            elts.append(self.parse_expr())
            self.skip_newlines()
        self.expect(TT.RBRACK, "']' after list")
        return ast.ListExpr(elts=elts, line=tok.line, col=tok.col)

    def parse_brace_expr(self) -> ast.Expr:
        tok = self.expect(TT.LBRACE)
        self.skip_seps()
        if self.match(TT.RBRACE):
            return ast.DictExpr(keys=[], values=[], line=tok.line, col=tok.col)

        # Check if first item is unambiguously a Dict item (`**d`, `=x` var pun, `.x` self-attr pun, or `k: v`)
        if self._starts_dict_entry_only():
            return self._parse_dict_entries(tok)

        first = self.parse_expr_stopping_at_comp_pipe()
        self.skip_seps()

        # Dict literal or Dict comprehension (`{k: v ...}`)
        if self.match(TT.COLON):
            val = self.parse_expr_stopping_at_comp_pipe()
            self.skip_seps()
            if self.match(TT.PIPE):
                clauses = self.parse_comp_clauses(TT.RBRACE)
                self.expect(TT.RBRACE, "'}' after dict comprehension")
                return ast.DictComp(key=first, value=val, clauses=clauses, line=tok.line, col=tok.col)

            first_key = self._normalize_dict_key(first)
            keys: list[Optional[ast.Expr]] = [first_key]
            values: list[ast.Expr] = [val]
            while self.match(TT.COMMA):
                self.skip_seps()
                if self.at(TT.RBRACE):
                    break
                k, v = self._parse_single_dict_entry()
                keys.append(k)
                values.append(v)
                self.skip_seps()
            self.expect(TT.RBRACE, "'}' after dict")
            return ast.DictExpr(keys=keys, values=values, line=tok.line, col=tok.col)

        # Self-field punning `{.id, .title}` or `{.id}` -> Dict (`{"id": self.id, ...}`)
        if isinstance(first, ast.SelfAttr) and not self.at(TT.PIPE):
            keys = [ast.Literal(value=first.attr, kind="str", line=first.line, col=first.col)]
            values = [first]
            while self.match(TT.COMMA):
                self.skip_seps()
                if self.at(TT.RBRACE):
                    break
                k, v = self._parse_single_dict_entry()
                keys.append(k)
                values.append(v)
                self.skip_seps()
            self.expect(TT.RBRACE, "'}' after dict")
            return ast.DictExpr(keys=keys, values=values, line=tok.line, col=tok.col)

        # Set comprehension: `{expr | x <- it}`
        if self.match(TT.PIPE):
            clauses = self.parse_comp_clauses(TT.RBRACE)
            self.expect(TT.RBRACE, "'}' after set comprehension")
            return ast.SetComp(elt=first, clauses=clauses, line=tok.line, col=tok.col)

        # Set literal: `{a, b}`
        elts = [first]
        while self.match(TT.COMMA):
            self.skip_seps()
            if self.at(TT.RBRACE):
                break
            elts.append(self.parse_expr())
            self.skip_seps()
        self.expect(TT.RBRACE, "'}' after set")
        return ast.SetExpr(elts=elts, line=tok.line, col=tok.col)

    def _starts_dict_entry_only(self) -> bool:
        if self.at(TT.STAR_STAR):
            return True
        if self.at(TT.EQ) and self.peek().type == TT.IDENT:
            return True
        return False

    def _normalize_dict_key(self, key_expr: ast.Expr) -> ast.Expr:
        # Bare identifier `{foo: 1}` -> `{"foo": 1}`
        if isinstance(key_expr, ast.Ident) and not key_expr.name.startswith("@"):
            return ast.Literal(value=key_expr.name, kind="str", line=key_expr.line, col=key_expr.col)
        # Dynamic/computed key `{[k]: 1}` -> `{k: 1}`
        if isinstance(key_expr, ast.ListExpr) and len(key_expr.elts) == 1:
            return key_expr.elts[0]
        return key_expr

    def _parse_dict_entries(self, tok: Token) -> ast.DictExpr:
        keys: list[Optional[ast.Expr]] = []
        values: list[ast.Expr] = []
        while not self.at(TT.RBRACE, TT.EOF):
            self.skip_seps()
            if self.at(TT.RBRACE):
                break
            k, v = self._parse_single_dict_entry()
            keys.append(k)
            values.append(v)
            self.skip_seps()
            if not self.match(TT.COMMA):
                break
        self.skip_seps()
        self.expect(TT.RBRACE, "'}' after dict")
        return ast.DictExpr(keys=keys, values=values, line=tok.line, col=tok.col)

    def _parse_single_dict_entry(self) -> tuple[Optional[ast.Expr], ast.Expr]:
        # Dict spread `**d`
        if self.match(TT.STAR_STAR):
            return None, self.parse_expr()
        # Variable pun `=x` -> `"x": x`
        if self.match(TT.EQ):
            id_tok = self.expect(TT.IDENT, "identifier after '=' in dict pun")
            return (
                ast.Literal(value=id_tok.value, kind="str", line=id_tok.line, col=id_tok.col),
                ast.Ident(name=id_tok.value, line=id_tok.line, col=id_tok.col),
            )
        expr = self.parse_expr()
        # Key-value pair `k: v`
        if self.match(TT.COLON):
            return self._normalize_dict_key(expr), self.parse_expr()
        # Self-attribute pun `.x` -> `"x": self.x`
        if isinstance(expr, ast.SelfAttr):
            return (
                ast.Literal(value=expr.attr, kind="str", line=expr.line, col=expr.col),
                expr,
            )
        # Bare identifier pun inside a known dict `{a: 1, b}` -> `"b": b`
        if isinstance(expr, ast.Ident):
            return (
                ast.Literal(value=expr.name, kind="str", line=expr.line, col=expr.col),
                expr,
            )
        raise ParseError("Expected ':' or dict pun ('.attr' or '=var') in dict literal", self.cur())

    def parse_expr_stopping_at_comp_pipe(self) -> ast.Expr:
        # If there is a top-level `| target <- iter` ahead, don't let bitwise `|` consume it!
        # Since bitwise `|` has l_bp = 31, if `_looks_like_comp_clause()` is True when we hit `|`, we stop.
        # Even simpler: check in `_infix_binding_power` if `|` is followed by `... <-`!
        return self.parse_expr()

    def _looks_like_comp_clause(self) -> bool:
        # Current token is TT.PIPE. Look ahead to see if `<-` appears before `]`, `}`, `)`, `;`, `\n` at depth 0
        look = self.pos + 1
        depth = 0
        while look < len(self.tokens):
            t = self.tokens[look].type
            if t in (TT.LPAREN, TT.LBRACK, TT.LBRACE):
                depth += 1
            elif t in (TT.RPAREN, TT.RBRACK, TT.RBRACE):
                if depth == 0:
                    return False
                depth -= 1
            elif depth == 0 and t in (TT.NEWLINE, TT.SEMI, TT.EOF):
                return False
            elif depth == 0 and t == TT.LEFT_ARROW:
                return True
            look += 1
        return False

    def parse_comp_clauses(self, closing_tt: TT) -> list[ast.CompClause]:
        clauses: list[ast.CompClause] = []
        while not self.at(closing_tt, TT.EOF):
            self.skip_seps()
            is_async = bool(self.match(TT.TILDE) or self.match(TT.PCT_TILDE))
            self.match(TT.PCT)
            target = self.parse_target_list()
            self.expect(TT.LEFT_ARROW, "'<-' in comprehension")
            # Parse iter expression without consuming `?` (filter condition) or `%` (nested loop)
            iter_expr = self._parse_comp_iter_expr()
            conds: list[ast.Expr] = []
            while self.match(TT.QMARK):
                conds.append(self._parse_comp_cond_expr())
            clauses.append(ast.CompClause(target=target, iter=iter_expr, conds=conds, is_async=is_async))
            self.skip_seps()
            if not self.at(TT.PCT, TT.PCT_TILDE):
                break
        return clauses

    def _parse_comp_iter_expr(self) -> ast.Expr:
        # Min BP 25 stops before ternary `?` (10); also we stop before `%` or `%~` if it starts a nested comp clause
        return self.parse_expr(min_bp=25)

    def _parse_comp_cond_expr(self) -> ast.Expr:
        # Min BP 18 allows `||` (20) and `&&` (25) inside comprehension filter `? cond`, while stopping before ternary `?` (10)
        return self.parse_expr(min_bp=18)

    def parse_postfix(self, left: ast.Expr) -> ast.Expr:
        tok = self.cur()

        # Dict string key shorthand: `d$key` -> `d["key"]`, `d$?key` -> `d.get("key")`
        if tok.type == TT.DOLLAR:
            self.pos += 1
            if self.match(TT.QMARK):
                key_name = self.expect(TT.IDENT, "key name after '$?'").value
                return ast.Call(
                    func=ast.Attribute(value=left, attr="get", line=tok.line, col=tok.col),
                    args=[ast.Literal(value=key_name, kind="str", line=tok.line, col=tok.col)],
                    keywords=[],
                    line=tok.line,
                    col=tok.col,
                )
            key_name = self.expect(TT.IDENT, "key name after '$'").value
            return ast.Subscript(
                value=left,
                slice=ast.Literal(value=key_name, kind="str", line=tok.line, col=tok.col),
                line=tok.line,
                col=tok.col,
            )

        # Attribute `.attr` or `?.attr`
        if tok.type in (TT.DOT, TT.QMARK_DOT):
            self.pos += 1
            attr = self.expect(TT.IDENT, "attribute name").value
            return ast.Attribute(value=left, attr=attr, optional=(tok.type == TT.QMARK_DOT), line=tok.line, col=tok.col)

        # Call `f(a, k=v)`
        if tok.type == TT.LPAREN:
            self.pos += 1
            args: list[ast.Expr] = []
            keywords: list[tuple[Optional[str], ast.Expr]] = []
            self.skip_newlines()
            while not self.at(TT.RPAREN, TT.EOF):
                self.skip_newlines()
                if self.match(TT.STAR_STAR):
                    keywords.append((None, self.parse_expr()))
                elif self.at(TT.IDENT) and self.peek().type == TT.COLON:
                    # Inline trailing dict shorthand: `f(a, k1: v1, k2: v2)` -> `f(a, {"k1": v1, "k2": v2})`
                    d_keys: list[Optional[ast.Expr]] = []
                    d_vals: list[ast.Expr] = []
                    while not self.at(TT.RPAREN, TT.EOF):
                        self.skip_newlines()
                        k_tok = self.expect(TT.IDENT, "dict key in call")
                        self.expect(TT.COLON, "':' after dict key in call")
                        v_expr = self.parse_expr()
                        d_keys.append(ast.Literal(value=k_tok.value, kind="str", line=k_tok.line, col=k_tok.col))
                        d_vals.append(v_expr)
                        self.skip_newlines()
                        if not self.match(TT.COMMA):
                            break
                    args.append(ast.DictExpr(keys=d_keys, values=d_vals, line=tok.line, col=tok.col))
                    break
                elif self.at(TT.IDENT) and self.peek().type == TT.EQ:
                    k_name = self.expect(TT.IDENT).value
                    self.expect(TT.EQ)
                    k_val = self.parse_expr()
                    keywords.append((k_name, k_val))
                elif self.match(TT.EQ):
                    k_name = self.expect(TT.IDENT, "identifier after '=' in keyword argument pun").value
                    keywords.append((k_name, ast.Ident(name=k_name, line=tok.line, col=tok.col)))
                else:
                    arg_expr = self.parse_expr()
                    # Support generator expression as sole call argument: `sum(x*2 | x <- items)`
                    if not args and not keywords and self.at(TT.PIPE) and self._looks_like_comp_clause():
                        self.pos += 1
                        clauses = self.parse_comp_clauses(TT.RPAREN)
                        args.append(ast.GenExp(elt=arg_expr, clauses=clauses, line=arg_expr.line, col=arg_expr.col))
                        break
                    args.append(arg_expr)
                self.skip_newlines()
                if not self.match(TT.COMMA):
                    break
            self.expect(TT.RPAREN, "')' after arguments")
            return ast.Call(func=left, args=args, keywords=keywords, line=left.line, col=left.col)

        # Subscript / Slice `a[i]`, `a[1:5:2]`, `a[1:, :2]`
        if tok.type == TT.LBRACK:
            self.pos += 1
            self.skip_newlines()
            slice_items: list[ast.Expr] = []
            while not self.at(TT.RBRACK, TT.EOF):
                slice_items.append(self._parse_subscript_item())
                if not self.match(TT.COMMA):
                    break
            self.expect(TT.RBRACK, "']' after subscript")
            sub_slice = slice_items[0] if len(slice_items) == 1 else ast.TupleExpr(elts=slice_items, line=tok.line, col=tok.col)
            return ast.Subscript(value=left, slice=sub_slice, line=left.line, col=left.col)

        return left

    def _parse_subscript_item(self) -> ast.Expr:
        lower: Optional[ast.Expr] = None
        if not self.at(TT.COLON, TT.RBRACK, TT.COMMA):
            lower = self.parse_expr()
        if not self.match(TT.COLON):
            assert lower is not None
            return lower

        upper: Optional[ast.Expr] = None
        if not self.at(TT.COLON, TT.RBRACK, TT.COMMA):
            upper = self.parse_expr()

        step: Optional[ast.Expr] = None
        if self.match(TT.COLON):
            if not self.at(TT.RBRACK, TT.COMMA):
                step = self.parse_expr()

        return ast.Slice(lower=lower, upper=upper, step=step)

    @staticmethod
    def _fstring_position(raw: str, index: int, tok: Token) -> tuple[int, int]:
        """Map an index in the template body back to a source line/column."""
        prefix = raw[:index]
        line_offset = prefix.count("\n")
        line = tok.line + line_offset
        if line_offset:
            col = len(prefix.rsplit("\n", 1)[1]) + 1
        else:
            col = tok.col + 1 + len(prefix)
        return line, col

    def _parse_fstring(self, tok: Token) -> ast.FString:
        raw = tok.value
        parts: list[Union[str, tuple[ast.Expr, Optional[str]]]] = []
        i = 0
        n = len(raw)
        lit_buf: list[str] = []

        while i < n:
            if raw[i] == "{" and i + 1 < n and raw[i + 1] == "{":
                lit_buf.append("{")
                i += 2
                continue
            if raw[i] == "}" and i + 1 < n and raw[i + 1] == "}":
                lit_buf.append("}")
                i += 2
                continue
            if raw[i] == "{":
                if lit_buf:
                    parts.append("".join(lit_buf))
                    lit_buf = []
                i += 1
                expr_start = i
                while expr_start < n and raw[expr_start] in (" ", "\t"):
                    expr_start += 1
                expr_line, expr_col = self._fstring_position(raw, expr_start, tok)
                depth = 1
                expr_chars: list[str] = []
                fmt_spec: Optional[str] = None
                in_quote: Optional[str] = None
                while i < n and depth > 0:
                    c = raw[i]
                    if in_quote:
                        if c == "\\" and i + 1 < n:
                            expr_chars.append(raw[i : i + 2])
                            i += 2
                            continue
                        if c == in_quote:
                            in_quote = None
                        expr_chars.append(c)
                        i += 1
                        continue
                    if c in ('"', "'"):
                        in_quote = c
                        expr_chars.append(c)
                        i += 1
                        continue
                    if c in ("{", "(", "["):
                        depth += 1
                    elif c in ("}", ")", "]"):
                        depth -= 1
                        if depth == 0:
                            i += 1
                            break
                    elif c == ":" and depth == 1 and (i + 1 >= n or raw[i + 1] in (".", "<", ">", "^", "+", "-", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9")):
                        # Format specifier `{x:.2f}`, `{x:>10}`, `{x:04d}`
                        i += 1
                        fmt_buf: list[str] = []
                        while i < n and raw[i] != "}":
                            fmt_buf.append(raw[i])
                            i += 1
                        fmt_spec = "".join(fmt_buf)
                        if i < n and raw[i] == "}":
                            i += 1
                        break
                    expr_chars.append(c)
                    i += 1
                expr_src = "".join(expr_chars).strip()
                sub_expr = parse_expr_str(expr_src, line=expr_line, col=expr_col)
                parts.append((sub_expr, fmt_spec))
            elif raw[i] == "\\" and i + 1 < n:
                esc = raw[i + 1]
                esc_map = {"`": "`", "\\": "\\", "n": "\n", "t": "\t", "r": "\r"}
                lit_buf.append(esc_map.get(esc, "\\" + esc))
                i += 2
            else:
                lit_buf.append(raw[i])
                i += 1

        if lit_buf:
            parts.append("".join(lit_buf))
        return ast.FString(parts=parts, line=tok.line, col=tok.col)

    # ========================================================================
    # Operator Precedence Table
    # ========================================================================

    def _is_comparison_token(self, tt: TT) -> bool:
        return tt in (
            TT.EQ_EQ,
            TT.BANG_EQ,
            TT.LT,
            TT.LT_EQ,
            TT.GT,
            TT.GT_EQ,
            TT.EQ_EQ_EQ,
            TT.BANG_EQ_EQ,
            TT.LEFT_ARROW,
            TT.NOT_LEFT_ARROW,
            TT.COLON_QMARK,
        )

    def _comparison_op_str(self, tt: TT) -> str:
        return {
            TT.EQ_EQ: "==",
            TT.BANG_EQ: "!=",
            TT.LT: "<",
            TT.LT_EQ: "<=",
            TT.GT: ">",
            TT.GT_EQ: ">=",
            TT.EQ_EQ_EQ: "===",
            TT.BANG_EQ_EQ: "!==",
            TT.LEFT_ARROW: "<-",
            TT.NOT_LEFT_ARROW: "!<-",
            TT.COLON_QMARK: ":?",
        }[tt]

    def _infix_binding_power(self, tt: TT) -> Optional[tuple[int, int]]:
        if tt == TT.PIPE and self._looks_like_comp_clause():
            return None
        if tt == TT.PCT and self._looks_like_nested_comp():
            return None
        table: dict[TT, tuple[int, int]] = {
            TT.PIPE_GT: (12, 13),       # |> pipeline
            TT.QMARK_QMARK: (15, 16),   # ?? null-coalesce
            TT.PIPE_PIPE: (20, 21),     # || logical or
            TT.AMP_AMP: (25, 26),       # && logical and
            # Comparisons: 30, 31
            TT.EQ_EQ: (30, 31),
            TT.BANG_EQ: (30, 31),
            TT.LT: (30, 31),
            TT.LT_EQ: (30, 31),
            TT.GT: (30, 31),
            TT.GT_EQ: (30, 31),
            TT.EQ_EQ_EQ: (30, 31),
            TT.BANG_EQ_EQ: (30, 31),
            TT.LEFT_ARROW: (30, 31),
            TT.NOT_LEFT_ARROW: (30, 31),
            TT.COLON_QMARK: (30, 31),
            # Bitwise
            TT.PIPE: (35, 36),          # |
            TT.CARET: (37, 38),         # ^ (infix XOR)
            TT.AMP: (39, 40),           # &
            TT.LSHIFT: (42, 43),        # <<
            TT.RSHIFT: (42, 43),        # >>
            # Arithmetic
            TT.PLUS: (50, 51),          # +
            TT.MINUS: (50, 51),         # -
            TT.STAR: (60, 61),          # *
            TT.SLASH: (60, 61),         # /
            TT.SLASH_SLASH: (60, 61),   # //
            TT.PCT: (60, 61),           # %
            TT.STAR_STAR: (71, 70),     # ** (right-associative)
        }
        return table.get(tt)

    def _looks_like_nested_comp(self) -> bool:
        # In `[x+y | x<-a % y<-b]`, `%` is followed by `y <- b`
        look = self.pos + 1
        if look < len(self.tokens) and self.tokens[look].type == TT.IDENT:
            if look + 1 < len(self.tokens) and self.tokens[look + 1].type in (TT.LEFT_ARROW, TT.COMMA):
                return True
        return False


def parse(source: str) -> ast.Module:
    tokens = tokenize(source)
    parser = Parser(tokens)
    return parser.parse_module()


def parse_expr_str(source: str, line: int = 1, col: int = 1) -> ast.Expr:
    tokens = tokenize(source)
    if line != 1 or col != 1:
        for token in tokens:
            if token.line == 1:
                token.col += col - 1
            token.line += line - 1
    parser = Parser(tokens)
    return parser.parse_expr()
