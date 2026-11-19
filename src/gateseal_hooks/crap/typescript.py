"""Fail when a TypeScript or JavaScript function's CRAP score is over the limit.

Coverage comes from an Istanbul JSON report, as Vitest and Jest write it,
complexity from tree-sitter.
"""

import os
import re
import sys
from bisect import bisect_right
from collections.abc import Collection, Iterator
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from gateseal_hooks.crap.inputs import (
    InputError,
    arguments,
    as_count,
    as_list,
    as_object,
    load_json,
)
from gateseal_hooks.crap.score import Score, crap, report, share

TYPESCRIPT = Language(tree_sitter_typescript.language_typescript())
TSX = Language(tree_sitter_typescript.language_tsx())
JAVASCRIPT = Language(tree_sitter_javascript.language())
GRAMMARS = {
    ".ts": TYPESCRIPT,
    ".mts": TYPESCRIPT,
    ".cts": TYPESCRIPT,
    ".tsx": TSX,
    ".js": JAVASCRIPT,
    ".mjs": JAVASCRIPT,
    ".cjs": JAVASCRIPT,
    ".jsx": JAVASCRIPT,
}
FUNCTIONS = frozenset(
    {
        "function_declaration",
        "generator_function_declaration",
        "function_expression",
        "function",
        "generator_function",
        "arrow_function",
        "method_definition",
    }
)
CLASSES = frozenset({"class_declaration", "abstract_class_declaration", "class"})
NAMESPACES = frozenset({"internal_module", "module"})
# A function in one of these is named after the field that holds it.
HOLDERS = {
    "variable_declarator": ("value", "name"),
    "pair": ("value", "key"),
    "object_assignment_pattern": ("right", "left"),
    "assignment_pattern": ("right", "left"),
    "required_parameter": ("value", "pattern"),
    "optional_parameter": ("value", "pattern"),
    "public_field_definition": ("value", "name"),
    "field_definition": ("value", "property"),
    "assignment_expression": ("right", "left"),
}
TRANSPARENT = frozenset(
    {
        "parenthesized_expression",
        "as_expression",
        "satisfies_expression",
        "non_null_expression",
        "type_assertion",
        "instantiation_expression",
    }
)
CALLS = frozenset({"arguments", "call_expression"})
DECISIONS = frozenset(
    {
        "if_statement",
        "for_statement",
        "for_in_statement",
        "while_statement",
        "do_statement",
        "catch_clause",
        "ternary_expression",
        "switch_case",
    }
)
SHORT_CIRCUIT = frozenset({"&&", "||", "??", "&&=", "||=", "??="})
# The pinned grammar cannot parse `for (using x of y)`. Blanking `using` keeps
# every position.
GAP = rb"(?:\s|/\*(?:[^*]|\*(?!/))*\*/|//[^\n]*\n)"
USING_LOOP = re.compile(
    rb"(?<![\w$.])for"
    + GAP
    + rb"*(?:await"
    + GAP
    + rb"*)?\("
    + GAP
    + rb"*((?:await"
    + GAP
    + rb"+)?using)(?="
    + GAP
    + rb"+[\w$\x80-\xff])"
)
# Istanbul ends a line where ECMAScript does, tree-sitter only at a line feed.
LINE_END = re.compile(rb"\r\n|[\n\r]|\xe2\x80[\xa8\xa9]")

# A line counted from 1 and a column in UTF-16 units, as Istanbul counts them.
Position = tuple[int, int]
Hit = tuple[Position | None, int]


@dataclass(eq=False)
class Unit:
    """A scored function and what the report counts in its code.

    calls is None when the report lists none of the unit's functions.
    """

    name: str
    complexity: int = 1
    statements: int = 0
    covered: int = 0
    branches: int = 0
    covered_branches: int = 0
    calls: int | None = None


@dataclass(frozen=True)
class Span:
    """Where a function starts, where its code starts and where its body ends."""

    start: Position
    code: Position
    end: Position
    unit: Unit


def text(node: Node | None) -> str | None:
    if node is None or node.text is None:
        return None
    return node.text.decode("utf-8", "replace")


def holder_name(node: Node, through_calls: bool) -> str | None:
    """Name the variable, property, field or export that holds node."""
    child, parent = node, node.parent
    while parent is not None:
        kind = parent.type
        holder = HOLDERS.get(kind)
        if holder and parent.child_by_field_name(holder[0]) == child:
            return text(parent.child_by_field_name(holder[1]))
        if kind == "export_statement":
            return "default"
        if kind not in TRANSPARENT and not (through_calls and kind in CALLS):
            return None
        child, parent = parent, parent.parent
    return None


def scope_name(node: Node) -> str | None:
    if node.type in CLASSES:
        return text(node.child_by_field_name("name")) or holder_name(node, False)
    if node.type == "object":
        return holder_name(node, False)
    if node.type in NAMESPACES:
        return text(node.child_by_field_name("name"))
    return None


def decisions(node: Node) -> int:
    if node.type in DECISIONS:
        return 1
    if node.type in ("binary_expression", "augmented_assignment_expression"):
        return int(text(node.child_by_field_name("operator")) in SHORT_CIRCUIT)
    return 0


def position(source: bytes, starts: list[int], byte: int) -> Position:
    """Turn a byte offset into Istanbul's line and UTF-16 column."""
    row = bisect_right(starts, byte) - 1
    prefix = source[starts[row] : byte].decode("utf-8", "replace")
    return row + 1, len(prefix.encode("utf-16-le")) // 2


def holds(span: Span, at: Position | None) -> bool:
    """Return whether at is in the function's code.

    A function's code is its parameters and its body. Its first character is
    not its code: there the code around it creates the function.
    """
    return at is not None and span.code <= at < span.end and at != span.start


def owner(spans: list[Span], at: Position | None) -> Span | None:
    """Return the innermost function whose code holds at.

    Each statement, branch and decision belongs to the owner of its start.
    """
    inside = [span for span in spans if holds(span, at)]
    return max(inside, key=lambda span: span.start, default=None)


def declared(
    spans: list[Span], start: Position, end: Position, body: Position | None
) -> Span | None:
    """Return the function that an Istanbul function entry names.

    The entry runs from start, in the function's declaration, to end, at or
    after the function's end on its last line. It names the innermost function
    in that range whose code holds the entry's body. Vitest puts a place that
    it cannot map on the nearest place it can. When that puts the body before
    the function, the entry names the first function with its parameters after
    start.
    """
    within = [span for span in spans if end[0] == span.end[0] and span.end <= end]
    after = [span for span in within if start <= span.code]
    return owner(within, body) or min(after, key=lambda span: span.start, default=None)


def parameters(node: Node) -> Node | None:
    """Return the parameters of a function, where its code starts."""
    if node.type not in FUNCTIONS:
        return None
    return node.child_by_field_name("parameters") or node.child_by_field_name(
        "parameter"
    )


def body(node: Node) -> Node:
    """Return the body of a function without what is around its value.

    Istanbul ends a function where that value ends, before a `)` that closes
    the body and before a type that `as` gives it. In `<T>value` the value
    comes last.
    """
    inner = node.child_by_field_name("body") or node
    while inner.type in TRANSPARENT:
        parts = [child for child in inner.named_children if child.type != "comment"]
        inner = parts[-1 if inner.type == "type_assertion" else 0]
    return inner


def unit_of(
    node: Node, scope: tuple[str, ...], around: Span | None, seen: dict[str, int]
) -> tuple[Unit, tuple[str, ...]]:
    """Return a function's unit and the scope of the names inside the function.

    A function with a name gets a unit, named name#2 when the name repeats. A
    function without a name inside another function shares that one's unit.
    """
    name = text(node.child_by_field_name("name")) or holder_name(
        node, through_calls=around is None
    )
    if name is None and around is not None:
        return around.unit, scope
    scope = (*scope, name or "(anonymous)")
    dotted = ".".join(scope)
    seen[dotted] = seen.get(dotted, 0) + 1
    numbered = dotted if seen[dotted] == 1 else f"{dotted}#{seen[dotted]}"
    return Unit(numbered), scope


def spans_of(root: Node, source: bytes) -> list[Span]:
    """Return each function in source order, with each decision counted."""
    starts = [0, *(match.end() for match in LINE_END.finditer(source))]
    at = partial(position, source, starts)
    spans: list[Span] = []
    seen: dict[str, int] = {}
    stack: list[tuple[Node, tuple[str, ...]]] = [(root, ())]
    while stack:
        node, scope = stack.pop()
        code = parameters(node)
        if code is not None:
            start = at(node.start_byte)
            unit, scope = unit_of(node, scope, owner(spans, start), seen)
            end = at(body(node).end_byte)
            spans.append(Span(start, at(code.start_byte), end, unit))
        elif holder := scope_name(node):
            scope = (*scope, holder)
        elif decisions(node):
            inside = owner(spans, at(node.start_byte))
            if inside is not None:
                inside.unit.complexity += 1
        stack.extend((child, scope) for child in reversed(node.children))
    return spans


def blanked(match: re.Match[bytes]) -> bytes:
    kept = match[0][: match.start(1) - match.start()]
    return kept + re.sub(rb"[^\n]", b" ", match[1])


def scorable(root: Node) -> bool:
    """Return whether no syntax error in the tree can change a score.

    The pinned grammar lacks some syntax, such as `export type * from`. An
    error outside each function hides no function when the text it skips
    holds no `(` and no `=>`.
    """
    stack = [(root, False)]
    while stack:
        node, skipped = stack.pop()
        if node.is_missing or (node.has_error and node.type in FUNCTIONS):
            return False
        if skipped and node.type in ("(", "=>"):
            return False
        skipped = skipped or node.is_error
        stack.extend((child, skipped) for child in node.children)
    return True


def parse(file: str) -> list[Span]:
    try:
        source = Path(file).read_bytes()
    except OSError as error:
        raise InputError(file, f"cannot read the source: {error}") from error
    parser = Parser(GRAMMARS[Path(file).suffix.lower()])
    for text in (source, USING_LOOP.sub(blanked, source)):
        root = parser.parse(text).root_node
        if not root.has_error or scorable(root):
            return spans_of(root, source)
    raise InputError(file, "cannot parse the source with tree-sitter")


def place(value: object, path: str, where: str, edge: str = "start") -> Position | None:
    """Return where an Istanbul location starts or ends, or None for an empty one."""
    point = as_object(value, path, where).get(edge)
    if point is None:
        return None
    point = as_object(point, path, where)
    if point.get("line") is None:
        return None
    line = as_count(point.get("line"), path, f"{where} line")
    if edge == "end" and point.get("column") is None:
        return line, sys.maxsize  # Istanbul writes no column for the end of a line
    return line, as_count(point.get("column"), path, f"{where} column")


def statement_hits(entry: dict[str, object], path: str, file: str) -> Iterator[Hit]:
    where = f"{file} statementMap"
    hits = as_object(entry.get("s"), path, f"{file} s")
    for key, location in as_object(entry.get("statementMap"), path, where).items():
        yield place(location, path, where), as_count(hits.get(key), path, where)


def branch_hits(entry: dict[str, object], path: str, file: str) -> Iterator[Hit]:
    """Yield each arm's count at the start of its decision.

    The arms of `c ? function a() {} : b` start in other functions, but the
    decision is made where the branch starts.
    """
    where = f"{file} branchMap"
    arms = as_object(entry.get("b"), path, f"{file} b")
    for key, value in as_object(entry.get("branchMap"), path, where).items():
        branch = as_object(value, path, where)
        counts = as_list(arms.get(key), path, f"{file} b")
        locations = as_list(branch.get("locations"), path, where)
        if len(counts) != len(locations):
            raise InputError(path, f"{where} {key} has {len(counts)} counts")
        starts = (
            place(location, path, where) for location in (branch.get("loc"), *locations)
        )
        at = next((start for start in starts if start), None)
        for count in counts:
            yield at, as_count(count, path, where)


def tally_calls(
    spans: list[Span], entry: dict[str, object], path: str, file: str
) -> dict[Position | None, Position]:
    """Add each function's calls to the unit of the function it declares.

    Vitest gives the start of an arrow function no place of its own. When an
    arrow's whole body is such an arrow, Vitest reports the body, and with it
    the arrow's own statement, at a place before the arrow's code. That
    statement ran as often as the arrow.

    When a class sets its fields in its constructor, as with legacy
    decorators, Vitest reports the statement that makes a field's arrow at the
    entry's start, in the arrow's parameters. Return each such place with the
    start of its arrow, where that statement is.
    """
    made: dict[Position | None, Position] = {}
    where = f"{file} fnMap"
    calls = as_object(entry.get("f"), path, f"{file} f")
    for key, value in as_object(entry.get("fnMap"), path, where).items():
        function = as_object(value, path, where)
        count = as_count(calls.get(key), path, where)
        start = place(function.get("decl"), path, where)
        body = place(function.get("loc"), path, where)
        end = place(function.get("loc"), path, where, "end")
        span = declared(spans, start, end, body) if start and end else None
        if span is None or start is None:
            continue
        span.unit.calls = (span.unit.calls or 0) + count
        if not holds(span, body):
            span.unit.statements += 1
            span.unit.covered += count > 0
        if holds(span, start) and start != body:
            made[start] = span.start
    return made


def tally(spans: list[Span], entry: dict[str, object], path: str, file: str) -> None:
    """Count each statement, branch and call of the report in its function's unit."""
    made = tally_calls(spans, entry, path, file)
    for at, count in statement_hits(entry, path, file):
        if (span := owner(spans, made.get(at, at))) is not None:
            span.unit.statements += 1
            span.unit.covered += count > 0
    for at, count in branch_hits(entry, path, file):
        if (span := owner(spans, at)) is not None:
            span.unit.branches += 1
            span.unit.covered_branches += count > 0


def coverage(unit: Unit) -> float:
    """Return the share of the unit's statements and branches that ran.

    A function scores 0 when the report says that it never ran, or says nothing
    about it. One without statements or branches, such as an empty function,
    scores 1 when it ran.
    """
    if unit.calls == 0 or not (unit.calls or unit.statements or unit.branches):
        return 0.0
    return share(unit.covered, unit.statements, unit.covered_branches, unit.branches)


def relative(name: str) -> str:
    return Path(os.path.relpath(os.path.abspath(name))).as_posix()


def file_scores(path: str, file: str, value: object) -> list[Score]:
    entry = as_object(value, path, file)
    if "all" in entry:
        raise InputError(
            path,
            f"has a c8 entry for {file}. c8 counts whole lines. Use Vitest, "
            "or Jest with its default coverage provider",
        )
    spans = parse(file)
    tally(spans, entry, path, file)
    scores: list[Score] = []
    # A unit comes once for its function and once for each callback in it.
    for unit in dict.fromkeys(span.unit for span in spans):
        measured = coverage(unit)
        score = crap(unit.complexity, measured)
        scores.append(Score(file, unit.name, score, unit.complexity, measured))
    return scores


def read_report(path: str, only: Collection[str] = ()) -> list[Score]:
    """Score each function in the report; with only, just those in the files named."""
    document = as_object(load_json(path), path, "the report")
    entries = {
        relative(key): value
        for key, value in document.items()
        if Path(key).suffix.lower() in GRAMMARS
    }
    wanted = {relative(file) for file in only}
    for file in sorted(wanted - set(entries)):
        if Path(file).suffix.lower() in GRAMMARS and parse(file):
            raise InputError(
                path,
                f"does not measure {file}. Add it to the test tool's coverage, "
                "or leave it out with the hook's files or exclude",
            )
    return [
        score
        for file, value in sorted(entries.items())
        if not wanted or file in wanted
        for score in file_scores(path, file, value)
    ]


def main(argv: list[str] | None = None) -> int:
    options = arguments(argv, __doc__, default_coverage="coverage/coverage-final.json")
    try:
        scores = read_report(options.coverage, options.files)
    except InputError as error:
        print(f"crap-score-typescript: {error}", file=sys.stderr)
        return 1
    return report(scores, options.limit)
