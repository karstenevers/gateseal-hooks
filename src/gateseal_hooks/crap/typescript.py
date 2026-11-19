"""Fail when a TypeScript or JavaScript function's CRAP score is over the limit.

Coverage comes from an Istanbul JSON report, as Vitest, Jest and c8 write it,
complexity from tree-sitter.
"""

import os
import re
import sys
from collections.abc import Collection, Iterator
from dataclasses import dataclass
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
# The pinned grammar cannot parse `export type * from` or `for (using x of y)`.
# Blanking the last group of each match keeps every position.
GAP = rb"(?:\s|/\*(?:[^*]|\*(?!/))*\*/|//[^\n]*\n)"
UNPARSED = (
    re.compile(rb"(?<![\w$.])export" + GAP + rb"+(type)(?=" + GAP + rb"*\*)"),
    re.compile(
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
    ),
)

# A line counted from 1 and a column in UTF-16 units, as Istanbul counts them.
Position = tuple[int, int]
Hit = tuple[Position | None, int]


@dataclass(eq=False)
class Unit:
    """A scored function and what the report counts in its code.

    calls is None when the report lists none of the unit's functions.
    """

    name: str
    line: int
    complexity: int = 1
    statements: int = 0
    covered: int = 0
    branches: int = 0
    covered_branches: int = 0
    calls: int | None = None


@dataclass(frozen=True)
class Span:
    """Where a function starts, where its code starts and where it ends."""

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


def position(lines: list[bytes], point: tuple[int, int]) -> Position:
    """Turn tree-sitter's byte column into Istanbul's UTF-16 column."""
    row, column = point
    prefix = lines[row][:column] if row < len(lines) else b""
    return row + 1, len(prefix.decode("utf-8", "replace").encode("utf-16-le")) // 2


def owner(spans: list[Span], at: Position | None, c8: bool = False) -> Span | None:
    """Return the innermost function whose code holds at.

    A function's code is its parameters and its body. Its first character is
    not its code: there the code around it creates the function. Each
    statement, branch, call count and decision belongs to the owner of its start.

    c8 starts a function's code at the function's first character.
    """
    if at is None:
        return None
    inside = [
        span
        for span in spans
        if (span.start <= at if c8 else span.code <= at != span.start) and at < span.end
    ]
    return max(inside, key=lambda span: span.start, default=None)


def parameters(node: Node) -> Node | None:
    """Return the parameters of a function, where its code starts."""
    if node.type not in FUNCTIONS:
        return None
    return node.child_by_field_name("parameters") or node.child_by_field_name(
        "parameter"
    )


def unit_of(
    node: Node,
    scope: tuple[str, ...],
    around: Span | None,
    seen: dict[str, int],
    line: int,
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
    return Unit(numbered, line), scope


def spans_of(root: Node, lines: list[bytes]) -> list[Span]:
    """Return each function in source order, with each decision counted."""
    spans: list[Span] = []
    seen: dict[str, int] = {}
    stack: list[tuple[Node, tuple[str, ...]]] = [(root, ())]
    while stack:
        node, scope = stack.pop()
        code = parameters(node)
        if code is not None:
            start = position(lines, node.start_point)
            unit, scope = unit_of(node, scope, owner(spans, start), seen, start[0])
            end = position(lines, node.end_point)
            spans.append(Span(start, position(lines, code.start_point), end, unit))
        elif holder := scope_name(node):
            scope = (*scope, holder)
        elif decisions(node):
            inside = owner(spans, position(lines, node.start_point))
            if inside is not None:
                inside.unit.complexity += 1
        stack.extend((child, scope) for child in reversed(node.children))
    return spans


def blanked(match: re.Match[bytes]) -> bytes:
    kept = match[0][: match.start(1) - match.start()]
    return kept + re.sub(rb"[^\n]", b" ", match[1])


def parse(file: str) -> list[Span]:
    try:
        source = Path(file).read_bytes()
    except OSError as error:
        raise InputError(file, f"cannot read the source: {error}") from error
    parser = Parser(GRAMMARS[Path(file).suffix.lower()])
    tree = parser.parse(source)
    if tree.root_node.has_error:
        parsed = source
        for pattern in UNPARSED:
            parsed = pattern.sub(blanked, parsed)
        tree = parser.parse(parsed)
    if tree.root_node.has_error:
        raise InputError(file, "cannot parse the source with tree-sitter")
    return spans_of(tree.root_node, source.split(b"\n"))


def start_of(
    value: object, path: str, where: str, edge: str = "start"
) -> Position | None:
    """Return where an Istanbul location starts or ends, or None for an empty one."""
    start = as_object(value, path, where).get(edge)
    if start is None:
        return None
    start = as_object(start, path, where)
    if start.get("line") is None:
        return None
    line = as_count(start.get("line"), path, f"{where} line")
    column = start.get("column")
    if column is None:  # Istanbul writes no column for the end of a line
        return line, 0 if edge == "start" else sys.maxsize
    if isinstance(column, bool) or not isinstance(column, int):
        raise InputError(path, f"{where} column is not a number")
    return line, max(column, 0)  # c8 writes -1 for the start of a line


def statement_hits(entry: dict[str, object], path: str, file: str) -> Iterator[Hit]:
    where = f"{file} statementMap"
    hits = as_object(entry.get("s"), path, f"{file} s")
    for key, location in as_object(entry.get("statementMap"), path, where).items():
        yield start_of(location, path, where), as_count(hits.get(key), path, where)


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
            start_of(location, path, where)
            for location in (branch.get("loc"), *locations)
        )
        at = next((start for start in starts if start), None)
        for count in counts:
            yield at, as_count(count, path, where)


def function_hits(
    entry: dict[str, object], path: str, file: str
) -> Iterator[tuple[Position | None, Position | None, int]]:
    """Yield where each function's range starts and ends, and its calls."""
    where = f"{file} fnMap"
    calls = as_object(entry.get("f"), path, f"{file} f")
    for key, value in as_object(entry.get("fnMap"), path, where).items():
        location = as_object(value, path, where).get("loc")
        at = start_of(location, path, where)
        end = start_of(location, path, where, "end")
        yield at, end, as_count(calls.get(key), path, f"{file} f")


def tally(
    spans: list[Span], entry: dict[str, object], path: str, file: str, c8: bool
) -> None:
    """Count each statement, branch and call of the report in its owner's unit."""
    for at, count in statement_hits(entry, path, file):
        if (span := owner(spans, at, c8)) is not None:
            span.unit.statements += 1
            span.unit.covered += count > 0
    for at, count in branch_hits(entry, path, file):
        if (span := owner(spans, at, c8)) is not None:
            span.unit.branches += 1
            span.unit.covered_branches += count > 0
    for at, _, count in function_hits(entry, path, file):
        if (span := owner(spans, at, c8)) is not None:
            span.unit.calls = (span.unit.calls or 0) + count


def idle_c8(
    entry: dict[str, object], path: str, file: str
) -> list[tuple[Position, Position]]:
    """Return each range that a c8 report says never ran."""
    return [
        (at, end)
        for at, end, count in function_hits(entry, path, file)
        if at and end and not count
    ]


def within(ranges: list[tuple[Position, Position]], at: Position) -> bool:
    return any(start <= at < end for start, end in ranges)


def never_ran_c8(
    spans: list[Span], entry: dict[str, object], path: str, file: str
) -> None:
    """Set the calls of each function that a c8 report says never ran to 0.

    c8 leaves a function inside one that never ran out of its report. It
    reports a class that no test built as one range without calls, and a file
    that no test loaded with `"all": true`.
    """
    idle = idle_c8(entry, path, file)
    own = {id(span.unit): span for span in reversed(spans)}.values()
    silent = [(span.start, span.end) for span in own if span.unit.calls == 0]
    for span in own:
        if (
            entry.get("all") is True
            or within(silent, span.start)
            or (not span.unit.calls and within(idle, span.start))
        ):
            span.unit.calls = 0


def coverage(unit: Unit, path: str, file: str) -> float:
    """Return the share of the unit's statements and branches that ran.

    A function that the report says never ran scores 0. One without statements
    or branches, such as an empty function, scores 1 when it ran.
    """
    if unit.calls == 0:
        return 0.0
    if unit.calls is None and not unit.statements + unit.branches:
        raise InputError(
            path, f"has no data for {unit.name} on {file} line {unit.line}"
        )
    return share(unit.covered, unit.statements, unit.covered_branches, unit.branches)


def relative(name: str) -> str:
    return Path(os.path.relpath(os.path.abspath(name))).as_posix()


def file_scores(path: str, file: str, value: object) -> list[Score]:
    spans = parse(file)
    entry = as_object(value, path, file)
    c8 = "all" in entry
    tally(spans, entry, path, file, c8)
    if c8:
        never_ran_c8(spans, entry, path, file)
    scores: list[Score] = []
    # A unit comes once for its function and once for each callback in it.
    for unit in dict.fromkeys(span.unit for span in spans):
        measured = coverage(unit, path, file)
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
