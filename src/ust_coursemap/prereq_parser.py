import re
from dataclasses import dataclass
from typing import Any, Optional

COURSE_CODE_RE = re.compile(r"([A-Z]{4})\s*(\d{4}[A-Z]?)")
TOKEN_RE = re.compile(r"([A-Z]{4}\s*\d{4}[A-Z]?|AND|OR|\(|\))")


@dataclass
class _Token:
    kind: str
    value: str


def normalize_course_code(value: str) -> str:
    compact = re.sub(r"\s+", "", value.upper())
    match = re.fullmatch(r"([A-Z]{4})(\d{4}[A-Z]?)", compact)
    if not match:
        return value.strip().upper()
    return f"{match.group(1)} {match.group(2)}"


def _cleanup_expression_text(text: str) -> str:
    cleaned = text.upper()
    cleaned = cleaned.replace("&", " AND ")
    cleaned = cleaned.replace("/", " OR ")
    cleaned = cleaned.replace(";", " AND ")
    cleaned = cleaned.replace(",", " AND ")
    cleaned = cleaned.replace("[", " (")
    cleaned = cleaned.replace("]", ") ")

    # Remove noisy phrases while keeping course codes and operators.
    noise_patterns = [
        r"\bPREREQUISITE[S]?\b",
        r"\bCOREQUISITE[S]?\b",
        r"\bEXCLUSION[S]?\b",
        r"\bPRIOR\s+TO\s+TAKING\b",
        r"\bPASS\s+IN\b",
        r"\bA\s+GRADE\s+OF\b",
        r"\bAT\s+LEAST\b",
        r"\bOR\s+ABOVE\b",
        r"\bOR\s+EQUIVALENT\b",
        r"\bEQUIVALENT\b",
        r"\bANY\s+OF\b",
        r"\bONE\s+OF\b",
        r"\bEITHER\b",
        r"\bFOR\s+NON-[A-Z]+\s+STUDENTS\b",
    ]
    for pattern in noise_patterns:
        cleaned = re.sub(pattern, " ", cleaned)

    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _tokenize(text: str) -> list[_Token]:
    cleaned = _cleanup_expression_text(text)
    raw_tokens = [x.group(0) for x in TOKEN_RE.finditer(cleaned)]

    tokens: list[_Token] = []
    for raw in raw_tokens:
        if raw in {"AND", "OR", "(", ")"}:
            tokens.append(_Token(kind=raw, value=raw))
            continue

        normalized = normalize_course_code(raw)
        if COURSE_CODE_RE.fullmatch(normalized.replace(" ", "")):
            tokens.append(_Token(kind="COURSE", value=normalized))

    if not tokens:
        return []

    return _insert_implicit_and(tokens)


def _insert_implicit_and(tokens: list[_Token]) -> list[_Token]:
    out: list[_Token] = []
    for idx, token in enumerate(tokens):
        if idx > 0:
            prev = tokens[idx - 1]
            if (
                prev.kind in {"COURSE", ")"}
                and token.kind in {"COURSE", "("}
            ):
                out.append(_Token(kind="AND", value="AND"))
        out.append(token)
    return out


def _precedence(op: str) -> int:
    if op == "AND":
        return 2
    if op == "OR":
        return 1
    return 0


def _to_rpn(tokens: list[_Token]) -> list[_Token]:
    output: list[_Token] = []
    operators: list[_Token] = []

    for token in tokens:
        if token.kind == "COURSE":
            output.append(token)
        elif token.kind in {"AND", "OR"}:
            while operators and operators[-1].kind in {"AND", "OR"} and _precedence(operators[-1].kind) >= _precedence(token.kind):
                output.append(operators.pop())
            operators.append(token)
        elif token.kind == "(":
            operators.append(token)
        elif token.kind == ")":
            while operators and operators[-1].kind != "(":
                output.append(operators.pop())
            if operators and operators[-1].kind == "(":
                operators.pop()

    while operators:
        op = operators.pop()
        if op.kind in {"AND", "OR"}:
            output.append(op)
    return output


def _node_course(code: str) -> dict[str, Any]:
    return {"type": "course", "course_code": code}


def _node_op(op: str, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    op_type = "and" if op == "AND" else "or"
    children: list[dict[str, Any]] = []

    # Flatten same-level operators to keep the tree concise.
    if left.get("type") == op_type:
        children.extend(left.get("children", []))
    else:
        children.append(left)

    if right.get("type") == op_type:
        children.extend(right.get("children", []))
    else:
        children.append(right)

    return {"type": op_type, "children": children}


def _from_rpn(tokens: list[_Token]) -> Optional[dict[str, Any]]:
    stack: list[dict[str, Any]] = []

    for token in tokens:
        if token.kind == "COURSE":
            stack.append(_node_course(token.value))
            continue

        if token.kind in {"AND", "OR"} and len(stack) >= 2:
            right = stack.pop()
            left = stack.pop()
            stack.append(_node_op(token.kind, left, right))

    if not stack:
        return None

    # If malformed input leaves extra elements, combine by AND conservatively.
    node = stack[0]
    for extra in stack[1:]:
        node = _node_op("AND", node, extra)
    return node


def parse_requirement_expression(text: str) -> Optional[dict[str, Any]]:
    tokens = _tokenize(text)
    if not tokens:
        return None
    rpn = _to_rpn(tokens)
    return _from_rpn(rpn)


def parse_exclusions(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for match in COURSE_CODE_RE.finditer(text.upper()):
        code = normalize_course_code("".join(match.groups()))
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def collect_course_codes_from_tree(tree: Optional[dict[str, Any]]) -> list[str]:
    if tree is None:
        return []

    if tree.get("type") == "course":
        code = tree.get("course_code")
        return [code] if isinstance(code, str) else []

    codes: list[str] = []
    for child in tree.get("children", []):
        for code in collect_course_codes_from_tree(child):
            if code not in codes:
                codes.append(code)
    return codes
