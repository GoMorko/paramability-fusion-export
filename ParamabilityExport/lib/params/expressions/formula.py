"""App formula text to an output node tree (the forms `render` writes)."""
import re

from .errors import ExpressionError

_PREC_COMPARE = ("<", "<=", ">", ">=", "==", "!=")


def parse_formula(formula):
    """Output node tree of an app formula in the forms `render` writes (a choice as `?:`, no `if` keyword)."""
    tokens = tokenize_formula(formula)
    pos = [0]

    def peek():
        return tokens[pos[0]]

    def take():
        pos[0] += 1
        return tokens[pos[0] - 1]

    def op(*texts):
        tok = peek()
        return tok[0] == "op" and tok[1] in texts

    def expect(text, message):
        if not op(text):
            raise ExpressionError(message)
        take()

    def choice():
        test = either()
        if op("?"):
            take()
            a = choice()
            expect(":", "A choice has no \":\".")
            return ("cond", test, a, choice())
        return test

    def either():
        node = both()
        while op("||"):
            take()
            node = ("logic", "||", node, both())
        return node

    def both():
        node = compare()
        while op("&&"):
            take()
            node = ("logic", "&&", node, compare())
        return node

    def compare():
        node = sum_()
        if op(*_PREC_COMPARE):
            node = ("cmp", take()[1], node, sum_())
        return node

    def sum_():
        node = term()
        while op("+", "-"):
            node = ("bin", take()[1], node, term())
        return node

    def term():
        node = unary()
        while op("*", "/"):
            node = ("bin", take()[1], node, unary())
        return node

    def unary():
        if op("-", "!"):
            return ("neg" if take()[1] == "-" else "not", unary())
        return atom()

    def atom():
        tok = take()
        if tok[0] == "num":
            return ("num", tok[1])
        if tok[0] == "id":
            if op("("):
                take()
                args = []
                if not op(")"):
                    args.append(choice())
                    while op(","):
                        take()
                        args.append(choice())
                expect(")", "A bracket is not closed.")
                return ("call", tok[1], args)
            return ("name", tok[1])
        if tok == ("op", "("):
            node = choice()
            expect(")", "A bracket is not closed.")
            return node
        raise ExpressionError("The formula is not complete.")

    node = choice()
    if peek()[0] != "end":
        raise ExpressionError("The formula has something extra at the end.")
    return node


_FORMULA_TOKEN = re.compile(r"\s*(?:(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?|([A-Za-z_][A-Za-z0-9_]*)|(<=|>=|==|!=|&&|\|\||.))")


def tokenize_formula(formula):
    """Tokens of an app formula: ("num", v), ("id", name), ("op", text), ("end",)."""
    out = []
    pos = 0
    text = formula.rstrip()
    while pos < len(text):
        m = _FORMULA_TOKEN.match(text, pos)
        if not m:
            break
        pos = m.end()
        if m.group(1) is not None:
            out.append(("num", float(m.group(1) + (m.group(2) or ""))))
        elif m.group(3) is not None:
            out.append(("id", m.group(3)))
        else:
            out.append(("op", m.group(4)))
    out.append(("end",))
    return out
