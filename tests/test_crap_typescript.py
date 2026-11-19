"""crap-score-typescript on recorded reports and on small sources.

The fixtures hold cases.ts, edges.ts and legacy.js, the tests that ran them
(cases.test.ts and edges.test.ts), and the coverage that Vitest 5.1.1 with V8
and with Istanbul recorded for them. c8 12.0.0 with the Node test runner
recorded cases.ts and legacy.js. Each expected row is worked out by hand from
the source and its test.
"""

import json
import shutil
import textwrap
from pathlib import Path

import pytest

from gateseal_hooks.crap import typescript

FIXTURES = Path(__file__).parent / "fixtures" / "typescript"

CASES = [
    ("src/cases.ts", "testedSimple", "1.00", 1, "100.0%"),
    ("src/cases.ts", "untestedBranchy", "42.00", 6, "0.0%"),
    ("src/cases.ts", "partlyTested", "3.79", 3, "55.6%"),
    ("src/cases.ts", "outerWithNested", "2.00", 2, "100.0%"),
    ("src/cases.ts", "outerWithNested.clamp", "3.79", 3, "55.6%"),
    ("src/cases.ts", "outerWithUncalledCallback", "17.13", 5, "21.4%"),
    ("src/cases.ts", "identity", "1.00", 1, "100.0%"),
    ("src/cases.ts", "uncalledOneLiner", "6.00", 2, "0.0%"),
    ("src/cases.ts", "calledOneLiner", "2.15", 2, "66.7%"),
    ("src/cases.ts", "Account.deposit", "2.15", 2, "66.7%"),
    ("src/cases.ts", "Account.withdraw", "30.00", 5, "0.0%"),
    ("src/cases.ts", "Account.render", "12.00", 3, "0.0%"),
    ("src/cases.ts", "handlers.onSave", "20.00", 4, "0.0%"),
    ("src/cases.ts", "handlers.onLoad", "12.00", 3, "0.0%"),
    ("src/cases.ts", "wrap", "1.00", 1, "100.0%"),
    ("src/cases.ts", "wrapped", "20.00", 4, "0.0%"),
    ("src/cases.ts", "default", "12.00", 3, "0.0%"),
]
LEGACY = [
    ("src/legacy.js", "jsTested", "2.15", 2, "66.7%"),
    ("src/legacy.js", "jsUntestedBranchy", "30.00", 5, "0.0%"),
]
# Each shape here once needed a rule of its own. A function's coverage is its
# covered statements and branches over all of them.
EDGES = [
    ("src/edges.ts", "paren", "2.15", 2, "66.7%"),
    ("src/edges.ts", "cast", "6.00", 2, "0.0%"),
    ("src/edges.ts", "angle", "2.15", 2, "66.7%"),
    ("src/edges.ts", "checked", "6.00", 2, "0.0%"),
    ("src/edges.ts", "sure", "2.15", 2, "66.7%"),
    # The statement that returns handler is factory's: 1 of 1.
    ("src/edges.ts", "factory", "1.00", 1, "100.0%"),
    ("src/edges.ts", "factory.handler", "2.26", 2, "60.0%"),
    ("src/edges.ts", "made", "1.00", 1, "100.0%"),
    ("src/edges.ts", "made.inner", "2.00", 1, "0.0%"),
    ("src/edges.ts", "later", "1.00", 1, "100.0%"),
    ("src/edges.ts", "later.wait", "2.26", 2, "60.0%"),
    # 3 of 3 statements, 1 of 2 arms of `?:` and 1 of 2 operands of `||`.
    ("src/edges.ts", "choose", "3.21", 3, "71.4%"),
    ("src/edges.ts", "choose.one", "1.00", 1, "100.0%"),
    ("src/edges.ts", "choose.two", "2.00", 1, "0.0%"),
    ("src/edges.ts", "choose.left", "1.00", 1, "100.0%"),
    ("src/edges.ts", "choose.right", "2.00", 1, "0.0%"),
    # The inner arrow has no name, so its statement and branches are curried's.
    ("src/edges.ts", "curried", "3.69", 2, "25.0%"),
    # thunk ran, but Vitest reports its call and its own statement at the
    # variable name, outside the function. Only the inner statement is left.
    ("src/edges.ts", "thunk", "2.00", 1, "0.0%"),
    ("src/edges.ts", "pass", "2.00", 1, "0.0%"),
    ("src/edges.ts", "named", "1.00", 1, "100.0%"),
    ("src/edges.ts", "named.inner", "1.00", 1, "100.0%"),
    ("src/edges.ts", "held", "1.00", 1, "100.0%"),
    ("src/edges.ts", "held.cb", "2.00", 1, "0.0%"),
    # The default value did not run: 1 of 2 statements, 0 of 1 branches.
    ("src/edges.ts", "passed", "1.30", 1, "33.3%"),
    ("src/edges.ts", "unpack", "1.00", 1, "100.0%"),
    ("src/edges.ts", "unpack.handle", "2.15", 2, "66.7%"),
    ("src/edges.ts", "unpack.renamed", "2.00", 1, "0.0%"),
    ("src/edges.ts", "unpack.first", "6.00", 2, "0.0%"),
    # The decisions in the method name are keyed's: 1 statement, 3 of 4 branches.
    ("src/edges.ts", "keyed", "3.07", 3, "80.0%"),
    ("src/edges.ts", 'keyed.[a && b ? "on" : "off"]', "2.00", 1, "0.0%"),
    ("src/edges.ts", "Box.handler", "2.26", 2, "60.0%"),
    # Vitest rewrites `using` to a block and a declaration, 2 more statements
    # that did not run: 3 of 7 statements, 0 of 2 branches.
    ("src/edges.ts", "dispose", "5.67", 3, "33.3%"),
    ("src/edges.ts", "idle", "2.00", 1, "0.0%"),
    ("src/edges.ts", "idle.nested", "2.00", 1, "0.0%"),
    ("src/edges.ts", "packed", "1.02", 1, "75.0%"),
    ("src/edges.ts", "packed.inner", "1.00", 1, "100.0%"),
    # An empty function has only its call count.
    ("src/edges.ts", "noop", "1.00", 1, "100.0%"),
    ("src/edges.ts", "unused", "2.00", 1, "0.0%"),
    # after follows characters that are 4 bytes and 2 UTF-16 units each.
    ("src/edges.ts", "after", "1.00", 1, "100.0%"),
]
EXACT = CASES + EDGES + LEGACY
# V8 cannot see a default value or a method name run. It gives a default
# value's branch the count of the code around it, and a method name's
# branches no count.
V8 = {
    "held": ("1.12", 1, "50.0%"),
    "passed": ("1.04", 1, "66.7%"),
    "unpack": ("1.02", 1, "71.4%"),
    "keyed": ("7.61", 3, "20.0%"),
}
# c8 counts whole lines and leaves out unnamed callbacks, so it is coarser.
COARSE = {
    "partlyTested": ("4.46", 3, "45.5%"),
    "outerWithNested.clamp": ("4.46", 3, "45.5%"),
    "outerWithUncalledCallback": ("9.96", 5, "41.7%"),
    "calledOneLiner": ("2.50", 2, "50.0%"),
    "Account.deposit": ("2.21", 2, "62.5%"),
    "wrapped": ("14.72", 4, "12.5%"),
    "jsTested": ("2.06", 2, "75.0%"),
}


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def recorded(root, name):
    """Copy the cases to root/src and return the report with absolute paths."""
    (root / "src").mkdir()
    for source in ("cases.ts", "edges.ts", "legacy.js"):
        shutil.copy(FIXTURES / source, root / "src" / source)
    document = json.loads((FIXTURES / f"{name}.json").read_text())
    report = root / "coverage-final.json"
    absolute = {str(root / key): entry for key, entry in document.items()}
    report.write_text(json.dumps(absolute))
    return report


def rows(scores):
    return [
        (s.file, s.function, f"{s.score:.2f}", s.complexity, f"{s.coverage:.1%}")
        for s in scores
    ]


def replaced(exact, other):
    return [(file, name, *other.get(name, row)) for file, name, *row in exact]


@pytest.mark.parametrize(
    ("name", "differs"), [("vitest-v8", V8), ("vitest-istanbul", {})]
)
def test_recorded_report_scores_every_case(root, name, differs):
    expected = replaced(EXACT, differs)
    assert rows(typescript.read_report(str(recorded(root, name)))) == expected


def test_c8_report_scores_every_case_more_coarsely(root):
    expected = replaced(CASES + LEGACY, COARSE)
    assert rows(typescript.read_report(str(recorded(root, "c8")))) == expected


def test_main_fails_on_the_cases_over_the_limit(root, capsys):
    report = recorded(root, "vitest-v8")
    code = typescript.main(["--coverage", str(report)])
    out = capsys.readouterr().out.splitlines()
    assert code == 1
    assert [line.split()[1] for line in out[1:-1]] == [
        "Account.render",
        "Account.withdraw",
        "default",
        "handlers.onLoad",
        "handlers.onSave",
        "outerWithUncalledCallback",
        "untestedBranchy",
        "wrapped",
        "jsUntestedBranchy",
    ]
    assert out[-1] == "58 functions scored, 9 over the limit of 10"


def test_named_files_limit_the_scores(root):
    report = recorded(root, "vitest-v8")
    scores = typescript.read_report(str(report), ["src/legacy.js"])
    assert [s.function for s in scores] == ["jsTested", "jsUntestedBranchy"]


def write(root, name, source):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).lstrip())
    return name


def statement(line, column, hits):
    return {"start": {"line": line, "column": column}}, hits


def report_of(root, file, statements=(), functions=(), branches=(), c8=False, **extra):
    """Write an Istanbul report for file with the given statements and functions.

    Each branch is (location, arm locations, arm counts). c8 writes "all" in
    each file's entry.
    """
    entry = {
        "statementMap": {str(i): s[0] for i, s in enumerate(statements)},
        "s": {str(i): s[1] for i, s in enumerate(statements)},
        "branchMap": {
            str(i): {"loc": b[0], "locations": b[1]} for i, b in enumerate(branches)
        },
        "b": {str(i): b[2] for i, b in enumerate(branches)},
        "fnMap": {str(i): {"loc": f[0]} for i, f in enumerate(functions)},
        "f": {str(i): f[1] for i, f in enumerate(functions)},
        **({"all": False} if c8 else {}),
        **extra,
    }
    report = root / "coverage-final.json"
    report.write_text(json.dumps({str(root / file): entry}))
    return str(report)


def test_named_file_the_report_does_not_measure_fails(root):
    report = report_of(root, write(root, "a.ts", "export const f = () => 1;\n"))
    new = write(root, "b.ts", "export function g(): number {\n  return 1;\n}\n")
    with pytest.raises(typescript.InputError, match="does not measure b.ts"):
        typescript.read_report(report, ["a.ts", new])


def test_named_file_without_functions_needs_no_coverage(root):
    report = report_of(root, write(root, "a.ts", "export const x = 1;\n"))
    types = write(root, "types.ts", "export interface Shape {\n  sides: number;\n}\n")
    assert typescript.read_report(report, [types]) == []


def test_source_that_does_not_parse_fails(root):
    name = write(root, "broken.ts", "export function f(a: number) {\n  if (a > 0 {\n")
    with pytest.raises(typescript.InputError, match="broken.ts: cannot parse"):
        typescript.read_report(report_of(root, name))


def test_function_without_data_in_the_report_fails(root):
    name = write(root, "a.ts", "export const f = (x: number) => (x > 0 ? 1 : 2);\n")
    with pytest.raises(typescript.InputError, match="has no data for f on a.ts line 1"):
        typescript.read_report(report_of(root, name))


ONE_LINER = "export const f = (x: number) => (x > 0 ? 1 : 2);\n"


DEFAULT = "export function outer(cb = function inner() {}) { return cb(); }\n"


def test_c8_function_in_a_default_gets_its_own_calls(root):
    def at(line, column):
        return {"start": {"line": line, "column": column}}

    calls = [(at(1, 7), 1), (at(1, 27), 1)]
    name = write(root, "a.ts", DEFAULT)
    report = report_of(root, name, [statement(1, 50, 1)], calls, c8=True)
    assert rows(typescript.read_report(report)) == [
        ("a.ts", "outer", "1.00", 1, "100.0%"),
        ("a.ts", "outer.inner", "1.00", 1, "100.0%"),
    ]


def test_c8_entry_where_a_function_starts_an_arrow_body_is_its_own(root):
    source = """\
        export const factory = () => function handler(x: number): number {
          return x > 0 ? 1 : 2;
        };
        """
    lines = [statement(line, 0, 1) for line in (1, 2, 3)]
    calls = [(statement(1, 23, 0)[0], 1), (statement(1, 29, 0)[0], 0)]
    report = report_of(root, write(root, "a.ts", source), lines, calls, c8=True)
    assert rows(typescript.read_report(report)) == [
        ("a.ts", "factory", "1.00", 1, "100.0%"),
        ("a.ts", "factory.handler", "6.00", 2, "0.0%"),
    ]


def test_many_comments_after_export_parse_quickly(root):
    source = "export " + "/* c */ " * 40 + "function f() {\n  return 1;\n}\n"
    assert names(typescript.parse(write(root, "a.ts", source))) == ["f"]


def test_field_function_of_a_class_c8_never_built_scores_zero(root):
    source = """\
        export class Widget {
          handler = (x: number): number => {
            if (x > 0) return 1;
            return 2;
          };
        }
        """
    hits = [1, 1, 0, 0, 1, 1]
    lines = [statement(line, 0, hit) for line, hit in enumerate(hits, 1)]
    initializer = {"start": {"line": 2, "column": 2}, "end": {"line": 5, "column": 3}}
    report = report_of(
        root, write(root, "a.ts", source), lines, [(initializer, 0)], c8=True
    )
    assert rows(typescript.read_report(report)) == [
        ("a.ts", "Widget.handler", "6.00", 2, "0.0%"),
    ]


def test_method_c8_saw_called_inside_a_never_built_class_keeps_its_calls(root):
    source = """\
        export class Widget {
          a = () => 1;
          static make(): number {
            return 1;
          }
          b = () => 2;
        }
        """
    hits = [1, 0, 1, 1, 1, 0, 1]
    lines = [statement(line, 0, hit) for line, hit in enumerate(hits, 1)]
    initializer = {"start": {"line": 2, "column": 2}, "end": {"line": 6, "column": 14}}
    calls = [(initializer, 0), (statement(3, 2, 0)[0], 1)]
    report = report_of(root, write(root, "a.ts", source), lines, calls, c8=True)
    assert rows(typescript.read_report(report)) == [
        ("a.ts", "Widget.a", "2.00", 1, "0.0%"),
        ("a.ts", "Widget.make", "1.00", 1, "100.0%"),
        ("a.ts", "Widget.b", "2.00", 1, "0.0%"),
    ]


def names(spans):
    return [unit.name for unit in dict.fromkeys(span.unit for span in spans)]


def test_source_the_grammar_parses_is_not_rewritten(root):
    source = 'const s = "for (await /*";\nconst t = "*/ using x of y";\n'
    assert typescript.parse(write(root, "a.ts", source)) == []


def test_function_inside_one_that_never_ran_scores_zero(root):
    # c8 leaves nested out of fnMap and counts whole lines from column 0.
    source = """\
        export function outer(): number {
          function nested() { return 1; }
          return nested();
        }
        """
    lines = [statement(line, 0, 0) for line in (1, 2, 3, 4)]
    calls = [(statement(1, 7, 0)[0], 0)]
    report = report_of(root, write(root, "a.ts", source), lines, calls, c8=True)
    assert rows(typescript.read_report(report)) == [
        ("a.ts", "outer", "2.00", 1, "0.0%"),
        ("a.ts", "outer.nested", "2.00", 1, "0.0%"),
    ]


def test_exact_positions_as_jest_writes_them_follow_the_same_rule(root):
    # Vitest never reports a hit where an arrow starts, Jest does: the
    # statement that creates thunk, then the one that returns the inner arrow.
    source = "export const thunk = () => () => 1;\n"
    lines = [statement(1, 21, 1), statement(1, 27, 1), statement(1, 33, 0)]
    calls = [(statement(1, 27, 0)[0], 1), (statement(1, 33, 0)[0], 0)]
    report = report_of(root, write(root, "a.ts", source), lines, calls)
    assert rows(typescript.read_report(report)) == [
        ("a.ts", "thunk", "1.12", 1, "50.0%")
    ]


def test_absolute_file_name_matches_the_report(root):
    name = write(root, "a.ts", "export const f = () => 1;\n")
    report = report_of(root, name, functions=[(statement(1, 23, 0)[0], 1)])
    assert len(typescript.read_report(report, [str(root / name)])) == 1


def test_branch_without_a_location_counts_at_its_first_arm(root):
    # A statement without a location is in no function.
    source = "export function f(x: number): number {\n  return x > 0 ? 1 : 2;\n}\n"
    arms = [{"start": {"line": 2, "column": None}}, {"start": {"line": None}}]
    name = write(root, "a.ts", source)
    report = report_of(root, name, [({}, 1)], branches=[({}, arms, [1, 0])])
    assert rows(typescript.read_report(report)) == [("a.ts", "f", "2.50", 2, "50.0%")]


def test_blanked_syntax_keeps_utf16_columns(root):
    line = "export async function f(xs: AsyncDisposable[]) {"
    line += " for (await /* é */ using x of xs) {} const g = () => 1; return g; }"
    spans = typescript.parse(write(root, "a.ts", line + "\n"))
    assert [(s.unit.name, s.start) for s in spans] == [
        ("f", (1, utf16(line, "async"))),
        ("f.g", (1, utf16(line, "() =>"))),
    ]


@pytest.mark.parametrize(
    ("branch", "detail"),
    [
        (({"start": {"line": 1, "column": 32}}, [{}], [1, 0]), "has 2 counts"),
        (({"start": {"line": 1, "column": "32"}}, [{}], [1]), "column is not a number"),
    ],
)
def test_bad_branch_fails(root, branch, detail):
    report = report_of(root, write(root, "a.ts", ONE_LINER), branches=[branch])
    with pytest.raises(typescript.InputError, match=detail):
        typescript.read_report(report)


@pytest.mark.parametrize(
    ("document", "detail"),
    [
        ([], "the report is not a JSON object"),
        (
            {"a.ts": {"statementMap": {"0": {"start": {"line": 1}}}, "s": {"0": -1}}},
            "statementMap is not a count",
        ),
    ],
)
def test_report_of_the_wrong_shape_fails(root, document, detail):
    write(root, "a.ts", "export const f = () => 1;\n")
    (root / "report.json").write_text(json.dumps(document))
    with pytest.raises(typescript.InputError, match=detail):
        typescript.read_report("report.json")


def test_file_c8_never_loaded_scores_zero(root):
    source = "export const f = (x: number) => x;\nexport const g = (x: number) => x;\n"
    empty = {"start": {"line": 1, "column": 0}}
    report = report_of(
        root,
        write(root, "a.ts", source),
        [statement(1, 0, 0), statement(2, 0, 0)],
        [(empty, 0)],
        all=True,
    )
    assert rows(typescript.read_report(report)) == [
        ("a.ts", "f", "2.00", 1, "0.0%"),
        ("a.ts", "g", "2.00", 1, "0.0%"),
    ]


def test_source_the_report_names_but_that_is_missing_fails(root):
    report = report_of(root, "gone.ts")
    with pytest.raises(typescript.InputError, match="gone.ts: cannot read the source"):
        typescript.read_report(report)


def test_main_prints_an_input_error_and_fails(root, capsys):
    code = typescript.main(["--coverage", "missing.json"])
    assert code == 1
    assert capsys.readouterr().err.startswith("crap-score-typescript: missing.json: ")


def utf16(line, needle):
    return len(line[: line.index(needle)].encode("utf-16-le")) // 2


def complexities(root, name, source):
    write(root, name, source)
    return {span.unit.name: span.unit.complexity for span in typescript.parse(name)}


COMPLEXITY = {
    "generics in tsx": (
        "generics.tsx",
        """
        export const first = <T,>(items: T[]): T | undefined =>
          items.length > 0 ? items[0] : undefined;
        export const load = async <T extends object>(read: () => Promise<T>) => {
          try {
            return await read();
          } catch {
            return null;
          }
        };
        export function View({ items }: { items: string[] }) {
          return <ul>{items.length > 0 && items.map((i) => (i ? <b>{i}</b> : 0))}</ul>;
        }
        """,
        {"first": 2, "load": 2, "View": 3},
    ),
    "modern syntax": (
        "modern.ts",
        """
        enum Color { Red, Green }
        declare function ext(a: number): void;
        function over(a: string): string;
        function over(a: unknown): unknown { return a ?? 1; }
        abstract class Base<const T extends readonly unknown[]> {
          accessor count = 0;
          static #secret = 1;
          abstract run(): void;
          @log() decorated(@inject() dep: A): void { if (dep) { c(); } }
          static { if (Base.#secret > 0) { Base.#secret ||= 2; } }
        }
        const config = { port: 80 } satisfies Record<string, number>;
        async function dispose() {
          await using res = getRes();
          for await (const x of res) { if (x) break; }
        }
        type Fn = <T>(x: T) => T extends string ? 1 : 2;
        export const typed = <const T,>(x: T) => x;
        """,
        {"over": 2, "Base.decorated": 2, "dispose": 3, "typed": 1},
    ),
    "generators, getters, constructors and namespaces": (
        "other.ts",
        """
        export function* walk(n: number): Generator<number> {
          for (let i = 0; i < n; i++) {
            if (i % 2 === 0 && i > 2) {
              yield i;
            }
          }
        }
        var legacyVar = function (a: number) { return a > 1 || a < -1 ? 1 : 0; };
        export default class Service {
          static create(): Service { return new Service(); }
          get size(): number { return this.items.length > 0 ? 1 : 0; }
          set size(value: number) { this.items.length = value; }
          constructor(private items: number[] = []) { if (items.length) { throw 1; } }
        }
        export namespace Tools { export function pick(a: number) { return a ? 1 : 2; } }
        """,
        {
            "walk": 4,
            "legacyVar": 3,
            "Service.create": 1,
            "Service.size": 2,
            "Service.size#2": 1,
            "Service.constructor": 2,
            "Tools.pick": 2,
        },
    ),
    "optional chaining is not a decision, ?? and ??= are": (
        "chains.ts",
        """
        export function f(a?: { b?: { c?: number } }, d?: number) {
          d ??= a?.b?.c ?? 0;
          return d;
        }
        """,
        {"f": 3},
    ),
    "each case is a decision, default is not": (
        "switch.js",
        """
        export function pick(n) {
          switch (n) {
            case 1:
              return "one";
            case 2:
              return "two";
            default:
              return "many";
          }
        }
        """,
        {"pick": 3},
    ),
    "a class field in JavaScript": (
        "field.js",
        """
        export class Box {
          open = (lid) => (lid ? 1 : 0);
        }
        """,
        {"Box.open": 2},
    ),
    "a callback in a function joins it, a named inner function does not": (
        "nested.ts",
        """
        export function outer(items: number[]) {
          const inner = (n: number) => (n > 0 ? n : 0);
          return items.map((n) => (n ? inner(n) : 0));
        }
        """,
        {"outer": 2, "outer.inner": 2},
    ),
    "syntax the pinned grammar lacks, type assertions and instantiations": (
        "types.ts",
        """
        export type * from "./shapes";
        export /* all */ type
          // of them
          * as Shapes from "./shapes";
        export function outer() {
          const cast = <Handler>((n: number) => (n > 0 ? n : 0));
          const bound = (<T,>(x: T) => (x ? x : null))<number>;
          return [cast, bound];
        }
        export async function dispose(items: Disposable[], later: AsyncDisposable[]) {
          for (using item of items) {}
          for (using π of items) {}
          for (await /* each */ using
            // item
            item of later) {}
        }
        """,
        {"dispose": 4, "outer": 1, "outer.bound": 2, "outer.cast": 2},
    ),
    "a computed method name counts where the method is defined": (
        "computed.ts",
        """
        export function make(on: boolean) {
          return { [on ? "on" : "off"](): number { return 1; } };
        }
        """,
        {"make": 2, 'make.[on ? "on" : "off"]': 1},
    ),
    "a default value names its function": (
        "destructure.ts",
        """
        export function make(options: { handle?: (x: number) => number }) {
          const { handle = (x: number) => (x > 0 ? x : 0) } = options;
          const { use: renamed = () => 1 } = options;
          const [first = (x: number) => (x ? 1 : 0)] = [];
          return [handle, renamed, first];
        }
        export function given(cb = () => 1, other?: () => void) {
          return [cb, other];
        }
        """,
        {
            "given": 1,
            "given.cb": 1,
            "make": 1,
            "make.first": 2,
            "make.handle": 2,
            "make.renamed": 1,
        },
    ),
}


@pytest.mark.parametrize(
    ("name", "source", "expected"), COMPLEXITY.values(), ids=COMPLEXITY.keys()
)
def test_complexity(root, name, source, expected):
    assert complexities(root, name, source) == expected
