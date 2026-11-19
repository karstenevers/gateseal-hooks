"""Fail when a TypeScript or JavaScript function's CRAP score is over the limit.

Coverage comes from an Istanbul JSON report, as Vitest, Jest and c8 write it,
complexity from tree-sitter.
"""

import os
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

# A line counted from 1 and a column in UTF-16 units, as Istanbul counts them.
Position = tuple[int, int]
Hit = tuple[Position | None, int]


@dataclass
class Unit:
    name: str
    start: Position
    body: Position
    end: Position
    complexity: int = 1


@dataclass
class Tally:
    statements: int = 0
    covered: int = 0
    branches: int = 0
    covered_branches: int = 0
    calls: tuple[Position, int] | None = None

    def call(self, at: Position, count: int) -> None:
        """Keep the earliest function in the report that this unit declares."""
        if self.calls is None or at < self.calls[0]:
            self.calls = (at, count)


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
    """Istanbul starts `() => (x)`'s body at x, inside the parentheses."""
    while node.type == "parenthesized_expression" and node.named_children:
        node = node.named_children[0]
    return node


def units_of(root: Node, lines: list[bytes]) -> list[Unit]:
    """Return each named function in source order, named name#2 when repeated."""
    units: list[Unit] = []
    seen: dict[str, int] = {}
    stack: list[tuple[Node, tuple[str, ...], Unit | None]] = [(root, (), None)]
    while stack:
        node, scope, unit = stack.pop()
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
                )
                units.append(unit)
                scope = (*scope, name)
        else:
            named = scope_name(node)
            if named:
                scope = (*scope, named)
            if unit is not None:
                unit.complexity += decisions(node)
        stack.extend((child, scope, unit) for child in reversed(node.children))
    return units


def parse(file: str) -> list[Unit]:
    try:
        source = Path(file).read_bytes()
    except OSError as error:
        raise InputError(file, f"cannot read the source: {error}") from error
    tree = Parser(GRAMMARS[Path(file).suffix.lower()]).parse(source)
    if tree.root_node.has_error:
        raise InputError(file, "cannot parse the source with tree-sitter")
    return units_of(tree.root_node, source.split(b"\n"))


def start_of(value: object, path: str, where: str) -> Position | None:
    """Return where an Istanbul location starts, or None for an empty one."""
    start = as_object(value, path, where).get("start")
    if start is None:
        return None
    start = as_object(start, path, where)
    if start.get("line") is None:
        return None
    line = as_count(start.get("line"), path, f"{where} line")
    column = start.get("column", 0)
    if column is None:
        return line, 0
    if isinstance(column, bool) or not isinstance(column, int):
        raise InputError(path, f"{where} column is not a number")
    return line, max(column, 0)  # c8 writes -1 for the start of a line


def owner(units: list[Unit], at: Position | None) -> Unit | None:
    """Return the innermost unit that holds at."""
    inside = [unit for unit in units if at and unit.start <= at < unit.end]
    return max(inside, key=lambda unit: unit.start, default=None)


def declared(units: list[Unit], at: Position) -> Unit | None:
    """Return the unit whose signature holds at, or that starts later on its line."""
    for unit in units:
        if unit.start <= at <= unit.body:
            return unit
    later = [unit for unit in units if unit.start[0] == at[0] and at < unit.start]
    return min(later, key=lambda unit: unit.start, default=None)


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


def function_hits(entry: dict[str, object], path: str, file: str) -> Iterator[Hit]:
    where = f"{file} fnMap"
    calls = as_object(entry.get("f"), path, f"{file} f")
    for key, value in as_object(entry.get("fnMap"), path, where).items():
        at = start_of(as_object(value, path, where).get("loc"), path, where)
        yield at, as_count(calls.get(key), path, f"{file} f")


def tallies(
    units: list[Unit], entry: dict[str, object], path: str, file: str
) -> dict[str, Tally]:
    found = {unit.name: Tally() for unit in units}
    for at, count in statement_hits(entry, path, file):
        if (unit := owner(units, at)) is not None:
            found[unit.name].statements += 1
            found[unit.name].covered += count > 0
    for at, count in branch_hits(entry, path, file):
        if (unit := owner(units, at)) is not None:
            found[unit.name].branches += 1
            found[unit.name].covered_branches += count > 0
    for at, count in function_hits(entry, path, file):
        if at is not None and (unit := declared(units, at)) is not None:
            found[unit.name].call(at, count)
    return found


def coverage(unit: Unit, tally: Tally, path: str, file: str) -> float:
    """A function the report says never ran scores 0%, whatever its lines say."""
    if tally.calls is not None and tally.calls[1] == 0:
        return 0.0
    if tally.statements or tally.branches:
        return share(
            tally.covered, tally.statements, tally.covered_branches, tally.branches
        )
    if tally.calls is not None:
        return 1.0
    raise InputError(
        path, f"has no data for {unit.name} on {file} line {unit.start[0]}"
    )


def read_report(path: str, only: Collection[str] = ()) -> list[Score]:
    """Score each function in the report; with only, just those in the files named."""
    document = as_object(load_json(path), path, "the report")
    entries = {
        Path(os.path.relpath(os.path.abspath(key))).as_posix(): value
        for key, value in document.items()
        if Path(key).suffix.lower() in GRAMMARS
    }
    wanted = {Path(file).as_posix() for file in only}
    for file in sorted(wanted - set(entries)):
        if Path(file).suffix.lower() in GRAMMARS and parse(file):
            raise InputError(
                path,
                f"does not measure {file}. Add it to the test tool's coverage, "
                "or leave it out with the hook's files or exclude",
            )
    scores: list[Score] = []
    for file, value in sorted(entries.items()):
        if wanted and file not in wanted:
            continue
        units = parse(file)
        entry = as_object(value, path, file)
        found = tallies(units, entry, path, file)
        for unit in units:
            # c8 --all writes `"all": true` for a file the tests never loaded.
            unloaded = entry.get("all") is True
            measured = 0.0 if unloaded else coverage(unit, found[unit.name], path, file)
            score = crap(unit.complexity, measured)
            scores.append(Score(file, unit.name, score, unit.complexity, measured))
    return scores


def main(argv: list[str] | None = None) -> int:
    options = arguments(argv, __doc__, default_coverage="coverage/coverage-final.json")
    try:
        scores = read_report(options.coverage, options.files)
    except InputError as error:
        print(f"crap-score-typescript: {error}", file=sys.stderr)
        return 1
    return report(scores, options.limit)
