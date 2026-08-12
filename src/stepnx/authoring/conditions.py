from __future__ import annotations

import re
from dataclasses import dataclass

from stepnx.core.profiles import profile_capabilities


@dataclass(frozen=True, slots=True)
class ConditionLiteral:
    value: int


@dataclass(frozen=True, slots=True)
class ConditionName:
    name: str


@dataclass(frozen=True, slots=True)
class ConditionUnary:
    operator: str
    operand: ConditionExpression


@dataclass(frozen=True, slots=True)
class ConditionBinary:
    operator: str
    left: ConditionExpression
    right: ConditionExpression


ConditionExpression = (
    ConditionLiteral | ConditionName | ConditionUnary | ConditionBinary
)


@dataclass(frozen=True, slots=True)
class ConditionToken:
    kind: str
    text: str
    offset: int


class ConditionSyntaxError(ValueError):
    def __init__(self, message: str, offset: int) -> None:
        super().__init__(f"{message} at character {offset}")
        self.offset = offset


@dataclass(frozen=True, slots=True)
class ConditionAnalysis:
    source: str
    expression: ConditionExpression | None
    variables: tuple[str, ...]
    unknown_variables: tuple[str, ...]
    error: str | None

    @property
    def is_valid(self) -> bool:
        return self.error is None


_TOKEN = re.compile(
    r"\s*(?:(?P<number>\d+)|(?P<name>[A-Za-z_][A-Za-z_0-9]*)|"
    r"(?P<operator>&&|\|\||<=|>=|==|!=|[()+\-*/%<>!]))"
)

_PRECEDENCE = {
    "||": 1,
    "&&": 2,
    "==": 3,
    "!=": 3,
    "<": 4,
    "<=": 4,
    ">": 4,
    ">=": 4,
    "+": 5,
    "-": 5,
    "*": 6,
    "/": 6,
    "%": 6,
}

_RANK_CONSTANTS = frozenset({"s", "a", "b", "c", "d", "f"})
_BASE_VARIABLES = frozenset(
    {
        "allheart",
        "allitem",
        "allmine",
        "allpotion",
        "allvelocity",
        "bad",
        "good",
        "great",
        "heart",
        "hidden",
        "item",
        "life",
        "maxcombo",
        "mine",
        "miss",
        "misscombo",
        "perfect",
        "potion",
        "rank",
        "score",
        "totalstep",
        "velocity",
    }
    | {
        f"{name}{player}"
        for name in (
            "bad",
            "good",
            "great",
            "maxcombo",
            "miss",
            "misscombo",
            "perfect",
            "totalstep",
        )
        for player in range(4)
    }
)


def condition_variables(profile: str) -> frozenset[str]:
    variables = set(_BASE_VARIABLES)
    capabilities = profile_capabilities(profile)
    for capability, name in (
        ("condition-correct", "correct"),
        ("condition-miss", "miss"),
        ("condition-score", "score"),
        ("condition-gauge", "gauge"),
        ("condition-accuracy", "accuracy"),
        ("condition-minlife", "minlife"),
    ):
        if capability in capabilities:
            variables.add(name)
    return frozenset(variables)


def tokenize_condition(source: str) -> tuple[ConditionToken, ...]:
    tokens: list[ConditionToken] = []
    offset = 0
    while offset < len(source):
        if source[offset:].isspace():
            offset = len(source)
            break
        match = _TOKEN.match(source, offset)
        if match is None:
            raise ConditionSyntaxError("unexpected character", offset)
        kind = match.lastgroup
        text = match.group(kind)
        start = match.start(kind)
        tokens.append(ConditionToken(kind, text, start))
        offset = match.end()
    tokens.append(ConditionToken("eof", "", len(source)))
    return tuple(tokens)


class _Parser:
    def __init__(self, tokens: tuple[ConditionToken, ...]) -> None:
        self.tokens = tokens
        self.index = 0

    @property
    def current(self) -> ConditionToken:
        return self.tokens[self.index]

    def advance(self) -> ConditionToken:
        token = self.current
        self.index += 1
        return token

    def expression(self, minimum_precedence: int = 1) -> ConditionExpression:
        token = self.advance()
        if token.kind == "number":
            left: ConditionExpression = ConditionLiteral(int(token.text))
        elif token.kind == "name":
            left = ConditionName(token.text)
        elif token.text in ("+", "-", "!"):
            left = ConditionUnary(token.text, self.expression(7))
        elif token.text == "(":
            left = self.expression()
            if self.current.text != ")":
                raise ConditionSyntaxError("expected ')'", self.current.offset)
            self.advance()
        else:
            raise ConditionSyntaxError("expected value", token.offset)

        while self.current.kind == "operator":
            operator = self.current.text
            precedence = _PRECEDENCE.get(operator)
            if precedence is None or precedence < minimum_precedence:
                break
            self.advance()
            right = self.expression(precedence + 1)
            left = ConditionBinary(operator, left, right)
        return left


def parse_condition(source: str) -> ConditionExpression | None:
    if not source.strip():
        return None
    parser = _Parser(tokenize_condition(source))
    expression = parser.expression()
    if parser.current.kind != "eof":
        raise ConditionSyntaxError("unexpected token", parser.current.offset)
    return expression


def _names(expression: ConditionExpression | None) -> tuple[str, ...]:
    if expression is None or isinstance(expression, ConditionLiteral):
        return ()
    if isinstance(expression, ConditionName):
        return (expression.name,)
    if isinstance(expression, ConditionUnary):
        return _names(expression.operand)
    return (*_names(expression.left), *_names(expression.right))


def analyze_condition(source: str, profile: str = "nxa-native") -> ConditionAnalysis:
    try:
        expression = parse_condition(source)
    except ConditionSyntaxError as exc:
        return ConditionAnalysis(source, None, (), (), str(exc))
    variables = tuple(dict.fromkeys(_names(expression)))
    accepted = condition_variables(profile)
    unknown = tuple(
        name for name in variables if name.casefold() not in accepted | _RANK_CONSTANTS
    )
    return ConditionAnalysis(source, expression, variables, unknown, None)


def evaluate_condition(
    expression: ConditionExpression | None,
    values: dict[str, int],
) -> int:
    """Evaluate a parsed condition against explicit values; never evaluates source code."""

    normalized = {key.casefold(): int(value) for key, value in values.items()}
    ranks = {"f": 0, "d": 1, "c": 2, "b": 3, "a": 4, "s": 5}

    def evaluate(node: ConditionExpression) -> int:
        if isinstance(node, ConditionLiteral):
            return node.value
        if isinstance(node, ConditionName):
            key = node.name.casefold()
            if key in ranks:
                return ranks[key]
            if key not in normalized:
                raise KeyError(node.name)
            return normalized[key]
        if isinstance(node, ConditionUnary):
            value = evaluate(node.operand)
            return {
                "+": lambda: value,
                "-": lambda: -value,
                "!": lambda: int(not value),
            }[node.operator]()
        left = evaluate(node.left)
        if node.operator == "&&":
            return int(bool(left) and bool(evaluate(node.right)))
        if node.operator == "||":
            return int(bool(left) or bool(evaluate(node.right)))
        right = evaluate(node.right)
        operations = {
            "+": lambda: left + right,
            "-": lambda: left - right,
            "*": lambda: left * right,
            "/": lambda: left // right,
            "%": lambda: left % right,
            "<": lambda: int(left < right),
            "<=": lambda: int(left <= right),
            ">": lambda: int(left > right),
            ">=": lambda: int(left >= right),
            "==": lambda: int(left == right),
            "!=": lambda: int(left != right),
        }
        return operations[node.operator]()

    return 1 if expression is None else evaluate(expression)
