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
EXPRESSIONS = frozenset(
    {"function_expression", "function", "generator_function", "arrow_function"}
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
# Where a function's code starts and ends, whether it starts at the function's
# start or else at its body, and its calls.
Call = tuple[Position | None, Position | None, bool, int]


@dataclass
class Unit:
    name: str
    start: Position
    body: Position
    end: Position
    expression: bool
    complexity: int = 1
    # A computed method name, which runs where the method is defined.
    key: tuple[Position, Position] | None = None


@dataclass
class Tally:
    statements: int = 0
    covered: int = 0
    branches: int = 0
    covered_branches: int = 0
    calls: tuple[tuple[bool, Position], int] | None = None

    def call(self, at: Position, exact: bool, count: int) -> None:
        """Keep the unit's own entry, else the earliest.

        `function f(g = () => 1) {}` holds the callback's entry in f's signature.
        """
        rank = (not exact, at)
        if self.calls is None or rank < self.calls[0]:
            self.calls = (rank, count)


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


def own_name(node: Node, enclosed: bool) -> str | None:
    """Name a function; a callback inside a function has none and joins it."""
    named = text(node.child_by_field_name("name"))
    if named:
        return named
    holder = holder_name(node, through_calls=not enclosed)
    return holder or (None if enclosed else "(anonymous)")


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


def unwrapped(node: Node) -> Node:
    """Vitest erases types first, so it starts the body of `() => <T>(x)` at x."""
    while node.type in TRANSPARENT:
        inner = [child for child in node.named_children if child.type != "comment"]
        node = inner[-1] if node.type == "type_assertion" else inner[0]
    return node


def computed_key(node: Node, lines: list[bytes]) -> tuple[Position, Position] | None:
    key = node.child_by_field_name("name")
    if key is None or key.type != "computed_property_name":
        return None
    return position(lines, key.start_point), position(lines, key.end_point)


def units_of(root: Node, lines: list[bytes]) -> list[Unit]:
    """Return each named function in source order, named name#2 when repeated."""
    units: list[Unit] = []
    seen: dict[str, int] = {}
    stack: list[tuple[Node, tuple[str, ...], Unit | None]] = [(root, (), None)]
    while stack:
        node, scope, unit = stack.pop()
        outer = (scope, unit)
        body = node.child_by_field_name("body") if node.type in FUNCTIONS else None
        if body is not None:
            name = own_name(node, enclosed=unit is not None)
            if name is not None:
                dotted = ".".join((*scope, name))
                seen[dotted] = seen.get(dotted, 0) + 1
                unit = Unit(
                    dotted if seen[dotted] == 1 else f"{dotted}#{seen[dotted]}",
                    position(lines, node.start_point),
                    position(lines, unwrapped(body).start_point),
                    position(lines, node.end_point),
                    node.type in EXPRESSIONS,
                    key=computed_key(node, lines),
                )
                units.append(unit)
                scope = (*scope, name)
        else:
            named = scope_name(node)
            if named:
                scope = (*scope, named)
            if unit is not None:
                unit.complexity += decisions(node)
        # A computed method name runs where the method is defined.
        stack.extend(
            (child, *outer)
            if child.type == "computed_property_name"
            else (child, scope, unit)
            for child in reversed(node.children)
        )
    return units


def blanked(match: re.Match[bytes]) -> bytes:
    kept = match[0][: match.start(1) - match.start()]
    return kept + re.sub(rb"[^\n]", b" ", match[1])


def parse(file: str) -> list[Unit]:
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
    return units_of(tree.root_node, source.split(b"\n"))


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


def owner(
    units: list[Unit], at: Position | None, statement: bool = False
) -> Unit | None:
    """Return the innermost unit that holds at.

    A statement that starts where a function expression starts, such as the
    return in `() => function f() {}`, runs in the code around it.
    """
    inside = [unit for unit in units if at and holds(unit, at, statement)]
    return max(inside, key=lambda unit: unit.start, default=None)


def holds(unit: Unit, at: Position, statement: bool = False) -> bool:
    if not unit.start <= at < unit.end:
        return False
    if unit.key is not None and unit.key[0] <= at < unit.key[1]:
        return False
    return not (statement and unit.expression and at == unit.start)


def declared(units: list[Unit], at: Position, starts: bool) -> tuple[Unit, bool] | None:
    """Return the unit whose own entry this is, else the innermost signature holding it.

    The signature of `function f(g = function h() {})` holds h.
    """
    for unit in units:
        if at == (unit.start if starts else unit.body):
            return unit, True
    holding = [unit for unit in units if unit.start <= at <= unit.body]
    inner = max(holding, key=lambda unit: unit.start, default=None)
    return None if inner is None else (inner, False)


def statement_hits(entry: dict[str, object], path: str, file: str) -> Iterator[Hit]:
    where = f"{file} statementMap"
    hits = as_object(entry.get("s"), path, f"{file} s")
    for key, location in as_object(entry.get("statementMap"), path, where).items():
        yield start_of(location, path, where), as_count(hits.get(key), path, where)


def branch_hits(entry: dict[str, object], path: str, file: str) -> Iterator[Hit]:
    where = f"{file} branchMap"
    arms = as_object(entry.get("b"), path, f"{file} b")
    for key, value in as_object(entry.get("branchMap"), path, where).items():
        branch = as_object(value, path, where)
        counts = as_list(arms.get(key), path, f"{file} b")
        locations = as_list(branch.get("locations"), path, where)
        if len(counts) != len(locations):
            raise InputError(path, f"{where} {key} has {len(counts)} counts")
        # The arms of `c ? function a() {} : b` start in the functions, but
        # the decision is made where the branch starts.
        decision = start_of(branch.get("loc"), path, where)
        for location, count in zip(locations, counts, strict=True):
            at = decision or start_of(location, path, where)
            yield at, as_count(count, path, where)


def function_hits(entry: dict[str, object], path: str, file: str) -> Iterator[Call]:
    """Istanbul starts a function at its body and its decl at its name.

    c8 starts both at the function's start, so `() => function f() {}`'s body and
    f start at the same place.
    """
    where = f"{file} fnMap"
    calls = as_object(entry.get("f"), path, f"{file} f")
    for key, value in as_object(entry.get("fnMap"), path, where).items():
        function = as_object(value, path, where)
        at = start_of(function.get("loc"), path, where)
        end = start_of(function.get("loc"), path, where, "end")
        starts = at == start_of(function.get("decl", {}), path, where)
        yield at, end, starts, as_count(calls.get(key), path, f"{file} f")


def tallies(
    units: list[Unit], entry: dict[str, object], path: str, file: str
) -> dict[str, Tally]:
    found = {unit.name: Tally() for unit in units}
    for at, count in statement_hits(entry, path, file):
        if (unit := owner(units, at, statement=True)) is not None:
            found[unit.name].statements += 1
            found[unit.name].covered += count > 0
    for at, count in branch_hits(entry, path, file):
        if (unit := owner(units, at)) is not None:
            found[unit.name].branches += 1
            found[unit.name].covered_branches += count > 0
    for at, _, starts, count in function_hits(entry, path, file):
        if at is not None and (match := declared(units, at, starts)) is not None:
            found[match[0].name].call(at, match[1], count)
    return found


def coverage(unit: Unit, tally: Tally, path: str, file: str) -> float:
    if tally.statements or tally.branches:
        return share(
            tally.covered, tally.statements, tally.covered_branches, tally.branches
        )
    if tally.calls is not None:
        return 1.0
    raise InputError(
        path, f"has no data for {unit.name} on {file} line {unit.start[0]}"
    )


def never_ran(
    units: list[Unit], found: dict[str, Tally], idle: list[tuple[Position, Position]]
) -> list[Unit]:
    """Return each unit the report says never ran.

    Each function inside one also never ran, whatever its own lines say, as
    does each function without calls of its own in code the report says never
    ran, such as c8's `<instance_members_initializer>` for a class no test built.
    """

    def calls(unit: Unit) -> int | None:
        tally = found[unit.name].calls
        return None if tally is None else tally[1]

    silent = [unit for unit in units if calls(unit) == 0]
    return [
        unit
        for unit in units
        if any(holds(outer, unit.start) for outer in silent)
        or (not calls(unit) and any(start <= unit.start < end for start, end in idle))
    ]


def relative(name: str) -> str:
    return Path(os.path.relpath(os.path.abspath(name))).as_posix()


def file_scores(path: str, file: str, value: object) -> list[Score]:
    units = parse(file)
    entry = as_object(value, path, file)
    found = tallies(units, entry, path, file)
    # c8 --all writes `"all": true` for a file the tests never loaded.
    idle = [
        (at, end)
        for at, end, _, count in function_hits(entry, path, file)
        if at and end and not count
    ]
    silent = units if entry.get("all") is True else never_ran(units, found, idle)
    scores: list[Score] = []
    for unit in units:
        if unit in silent:
            measured = 0.0
        else:
            measured = coverage(unit, found[unit.name], path, file)
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
