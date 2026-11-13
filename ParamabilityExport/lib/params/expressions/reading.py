"""Fusion expression text to a parse tree: the tokens, the parser and the names an expression reads."""
import re

from .errors import ExpressionError
from .units import unit_factor

_NUMBER = re.compile(r"(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?")


def _ident_char(c):
    """Letters, digits and the symbols Fusion allows in names and unit words (`$ " ° µ`)."""
    return c.isalnum() or c in "_$\"°˚"


_TWO_CHAR_OPS = ("<=", ">=", "==", "<>", "!=")
_ONE_CHAR_OPS = "+-*/^%(),;<>"
_COMPARE = {"<": "<", "<=": "<=", ">": ">", ">=": ">=", "==": "==", "<>": "!=", "!=": "!="}
_LOGIC_WORDS = ("and", "or", "not")
_CONSTANTS = ("PI", "π", "E")


# Tokens: ("num", value), ("id", name), ("op", text), ("end",)

def tokenize(text):
    tokens = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c.isdigit() or c == ".":
            m = _NUMBER.match(text, i)
            if not m:
                raise ExpressionError("A number could not be read.")
            tokens.append(("num", float(m.group(0))))
            i = m.end()
        elif _ident_char(c):
            k = i
            while k < n and _ident_char(text[k]):
                k += 1
            tokens.append(("id", text[i:k]))
            i = k
        elif text[i:i + 2] in _TWO_CHAR_OPS:
            tokens.append(("op", text[i:i + 2]))
            i += 2
        elif c in _ONE_CHAR_OPS:
            tokens.append(("op", c))
            i += 1
        else:
            raise ExpressionError(f"The character \"{c}\" is not supported.")
    tokens.append(("end",))
    return tokens


# Parse tree: ("num", v), ("name", s), ("unitword", w), ("unit", a, w), ("const", s), ("neg", a), ("not", a),
# ("bin", op, a, b) for + - * / % ^, ("cmp", op, a, b), ("logic", op, a, b), ("call", f, args)

class _Parser:
    def __init__(self, tokens):
        self.t = tokens
        self.i = 0

    def peek(self):
        return self.t[self.i]

    def take(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def is_op(self, *ops):
        tok = self.peek()
        return tok[0] == "op" and tok[1] in ops

    def is_word(self, *words):
        tok = self.peek()
        return tok[0] == "id" and (tok[1] in words or tok[1].lower() in words and tok[1].isupper())

    def close(self):
        if not self.is_op(")"):
            raise ExpressionError("A bracket is not closed.")
        self.take()

    def parse(self):
        node = self.disjunction()
        if self.peek()[0] != "end":
            raise ExpressionError("The expression has something extra at the end.")
        return node

    def disjunction(self):
        node = self.conjunction()
        while self.is_word("or"):
            self.take()
            node = ("logic", "||", node, self.conjunction())
        return node

    def conjunction(self):
        node = self.negation()
        while self.is_word("and"):
            self.take()
            node = ("logic", "&&", node, self.negation())
        return node

    def negation(self):
        if self.is_word("not"):
            self.take()
            return ("not", self.negation())
        return self.comparison()

    def comparison(self):
        node = self.sum()
        if self.is_op(*_COMPARE):
            op = _COMPARE[self.take()[1]]
            node = ("cmp", op, node, self.sum())
            if self.is_op(*_COMPARE):
                raise ExpressionError("Comparisons cannot be chained. Join them with \"and\".")
        return node

    def sum(self):
        node = self.term()
        while self.is_op("+", "-"):
            op = self.take()[1]
            node = ("bin", op, node, self.term())
        return node

    def term(self):
        node = self.unary()
        while self.is_op("*", "/", "%"):
            op = self.take()[1]
            node = ("bin", op, node, self.unary())
        return node

    def unary(self):
        if self.is_op("-"):
            self.take()
            return ("neg", self.unary())
        if self.is_op("+"):
            self.take()
            return self.unary()
        return self.power()

    def power(self):
        base = self.postfix()
        if self.is_op("^"):
            self.take()
            return ("bin", "^", base, self.exponent())
        return base

    def exponent(self):
        if self.is_op("-"):
            self.take()
            return ("neg", self.exponent())
        if self.is_op("+"):
            self.take()
            return self.exponent()
        return self.power()

    def postfix(self):
        """An operand and the unit words after it (`2 mm`, `(a + b) mm`)."""
        node = self.atom()
        while self.peek()[0] == "id" and not self.is_word(*_LOGIC_WORDS):
            word = self.take()[1]
            if unit_factor(word, loose=True) is None:
                raise ExpressionError(f"The unit \"{word}\" is not a length or an angle.")
            node = ("unit", node, word)
        return node

    def atom(self):
        tok = self.take()
        if tok[0] == "num":
            return ("num", tok[1])
        if tok[0] == "id":
            name = tok[1]
            if self.is_op("("):
                self.take()
                args = []
                if not self.is_op(")"):
                    args.append(self.disjunction())
                    while self.is_op(";", ","):
                        self.take()
                        args.append(self.disjunction())
                self.close()
                if name.lower() == "not" and len(args) == 1:
                    return ("not", args[0])
                return ("call", name.lower(), args)
            if name in _CONSTANTS:
                return ("const", name)
            if unit_factor(name) is not None:
                return ("unitword", name)
            return ("name", name)
        if tok == ("op", "("):
            node = self.disjunction()
            self.close()
            return node
        raise ExpressionError("The expression is not complete.")


def parse(text):
    return _Parser(tokenize(text)).parse()

def _children(node):
    for part in node[1:]:
        if isinstance(part, tuple):
            yield part
        elif isinstance(part, list):
            yield from part


def referenced_names(text):
    """Parameter names an expression reads, in order of first use. An unreadable expression gives an empty list."""
    try:
        tree = parse(text)
    except ExpressionError:
        return []
    out = []
    stack = [tree]
    while stack:
        node = stack.pop()
        if node[0] == "name":
            if node[1] not in out:
                out.append(node[1])
        else:
            stack.extend(reversed(list(_children(node))))
    return out


def scanned_names(text):
    """The words of an expression that may name a parameter, in order of first use, also when the parser refuses the
    text: identifiers that do not start with a digit and are not followed by `(` (a function). Unit words and
    constants are kept, so callers compare the result with the names they know."""
    out = []
    i, n = 0, len(text or "")
    while i < n:
        c = text[i]
        if c.isdigit() or c == ".":
            m = _NUMBER.match(text, i)
            i = m.end() if m else i + 1
            while i < n and _ident_char(text[i]):
                i += 1  # a unit written against its number: `2mm`
        elif _ident_char(c):
            k = i
            while k < n and _ident_char(text[k]):
                k += 1
            word, i = text[i:k], k
            while k < n and text[k].isspace():
                k += 1
            if (k >= n or text[k] != "(") and word not in out:
                out.append(word)
        else:
            i += 1
    return out
