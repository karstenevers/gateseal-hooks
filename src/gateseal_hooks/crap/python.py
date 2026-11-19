"""Fail when a Python function's CRAP score is over the limit.

Coverage comes from coverage.py's JSON report with branch coverage, complexity
from `ast`.
"""

import ast
import sys
from collections.abc import Collection, Iterator
from pathlib import Path

from gateseal_hooks.crap.inputs import (
    InputError,
    arguments,
    as_count,
    as_list,
    as_object,
    load_json,
)
from gateseal_hooks.crap.score import Score, crap, report, share

Definition = ast.FunctionDef | ast.AsyncFunctionDef

SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def decisions(node: ast.AST) -> int:
    match node:
        case (
            ast.If()
            | ast.For()
            | ast.AsyncFor()
            | ast.While()
            | ast.ExceptHandler()
            | ast.match_case()
            | ast.IfExp()
        ):
            return 1
        case ast.BoolOp(values=values):
            return len(values) - 1
        case ast.comprehension(ifs=ifs):
            return len(ifs)
        case _:
            return 0


def definition_time(nested: Definition) -> list[ast.expr]:
    """Return the parts of a nested def that the enclosing code runs."""
    defaults = [default for default in nested.args.kw_defaults if default]
    return [*nested.decorator_list, *nested.args.defaults, *defaults]


def own_nodes(function: Definition) -> Iterator[ast.AST]:
    """Yield the nodes that run in a call of function, a nested class body too."""
    stack: list[ast.AST] = list(function.body)
    while stack:
        node = stack.pop()
        if isinstance(node, Definition):
            stack.extend(definition_time(node))
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def complexity(function: Definition) -> int:
    return 1 + sum(decisions(node) for node in own_nodes(function))


def parse_source(path: str) -> dict[str, list[Definition]]:
    """Return each def in path under the dotted name coverage.py gives its region."""
    try:
        tree = ast.parse(Path(path).read_bytes(), filename=path)
    except (OSError, SyntaxError, ValueError) as error:
        raise InputError(path, f"cannot parse Python source: {error}") from error
    named: dict[str, list[Definition]] = {}
    for name, node in definitions(tree):
        named.setdefault(name, []).append(node)
    return named


def definitions(tree: ast.AST) -> Iterator[tuple[str, Definition]]:
    """Yield each def under its dotted name, in source order, without recursion."""
    stack: list[tuple[ast.AST, str]] = [(tree, "")]
    while stack:
        node, scope = stack.pop()
        if isinstance(node, SCOPES):
            name = scope + node.name
            if not isinstance(node, ast.ClassDef):
                yield name, node
            scope = name + "."
        children = reversed(list(ast.iter_child_nodes(node)))
        stack.extend((child, scope) for child in children)


def body_lines(function: Definition) -> set[int]:
    last = function.body[-1]
    return set(range(function.body[0].lineno, (last.end_lineno or last.lineno) + 1))


def own_lines(function: Definition) -> set[int]:
    """Return the lines coverage.py counts in function: its body less nested defs."""
    nested = (
        node
        for node in ast.walk(function)
        if node is not function
        and isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    )
    return body_lines(function).difference(*map(body_lines, nested))


def branch_sources(value: object, path: str, where: str) -> list[int]:
    """Return the line each branch of a coverage.py branch list leaves from."""
    sources: list[int] = []
    for arc in as_list(value, path, where):
        pair = as_list(arc, path, where)
        if len(pair) != 2:
            raise InputError(path, f"{where} holds a branch that is not a pair")
        sources.append(as_count(pair[0], path, where))
    return sources


def lines_coverage(
    entry: dict[str, object], lines: set[int] | None, path: str, where: str
) -> float:
    """Return the share of the entry's statements and branches that ran.

    The entry is a file or a region of coverage.py. With lines, only what is
    on these lines counts.
    """
    executed, missing = (
        {
            as_count(line, path, f"{where} {name}")
            for line in as_list(entry.get(name), path, f"{where} {name}")
        }
        for name in ("executed_lines", "missing_lines")
    )
    hit, missed = (
        branch_sources(entry.get(name), path, f"{where} {name}")
        for name in ("executed_branches", "missing_branches")
    )
    if lines is None:
        lines = executed | missing | set(hit + missed)
    taken = [line for line in hit if line in lines]
    listed = taken + [line for line in missed if line in lines]
    # A line that branches has 2 branches or more. coverage.py lists only one
    # when `# pragma: no branch` waives the other, and that one counts as
    # covered. It lists none for such a line that never ran.
    waived = sum(listed.count(line) == 1 for line in set(listed))
    return share(
        len(executed & lines),
        len((executed | missing) & lines),
        len(taken) + waived,
        len(listed) + waived,
    )


def score_file(
    file: str, entry: dict[str, object], report_path: str
) -> Iterator[Score]:
    functions = as_object(entry.get("functions"), report_path, f"{file} functions")
    named = parse_source(str(Path.cwd() / file))
    for name, value in functions.items():
        if name == "":
            continue
        where = f"{file} function {name}"
        region = as_object(value, report_path, where)
        if "start_line" not in region:
            raise InputError(
                report_path, "has no start_line; make it with coverage.py 7.13.1+"
            )
        line = as_count(region.get("start_line"), report_path, f"{where} start_line")
        found = named.pop(name, [])
        if line not in {node.lineno for node in found}:
            raise InputError(
                report_path, f"{where} starts on line {line}, not a def of that name"
            )
        yield from name_scores(file, name, found, line, entry, region, report_path)
    if named:
        name, found = min(named.items(), key=lambda item: item[1][0].lineno)
        raise InputError(
            report_path, f"{file} line {found[0].lineno} defines {name} with no region"
        )


def name_scores(
    file: str,
    name: str,
    found: list[Definition],
    line: int,
    entry: dict[str, object],
    region: dict[str, object],
    report_path: str,
) -> Iterator[Score]:
    """Score the defs that share name; later ones are named name#2, name#3.

    coverage.py reports one region per name, for the def that starts on line.
    Another def of that name, such as a property's getter beside its setter,
    is measured the same way from the file's lines.
    """
    shares = [
        lines_coverage(region, None, report_path, f"{file} function {name}")
        if node.lineno == line
        else lines_coverage(entry, own_lines(node), report_path, file)
        for node in found
    ]
    for index, (node, measured) in enumerate(zip(found, shares, strict=True), 1):
        count = complexity(node)
        key = name if index == 1 else f"{name}#{index}"
        yield Score(file, key, crap(count, measured), count, measured)


def read_report(path: str, only: Collection[str] = ()) -> list[Score]:
    """Score each function in the report; with only, just those in the files named."""
    report = as_object(load_json(path), path, "the report")
    meta = as_object(report.get("meta"), path, "meta")
    if meta.get("format") != 3:
        raise InputError(path, "is not a coverage.py JSON report of format 3")
    if meta.get("branch_coverage") is not True:
        raise InputError(path, "was measured without branch coverage")
    files = as_object(report.get("files"), path, "files")
    wanted = {Path(file) for file in only}
    unmeasured = wanted - {Path(file) for file in files}
    if unmeasured:
        raise InputError(
            path,
            f"does not measure {min(unmeasured)}. Add it to coverage.py's source, "
            "or leave it out with the hook's files or exclude",
        )
    return [
        score
        for file, entry in files.items()
        if not wanted or Path(file) in wanted
        for score in score_file(file, as_object(entry, path, file), path)
    ]


def main(argv: list[str] | None = None) -> int:
    options = arguments(argv, __doc__, default_coverage="coverage.json")
    try:
        scores = read_report(options.coverage, options.files)
    except InputError as error:
        print(f"crap-score-python: {error}", file=sys.stderr)
        return 1
    return report(scores, options.limit)
