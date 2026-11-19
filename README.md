Plain [pre-commit](https://pre-commit.com) hooks, usable with or without [gateseal](https://github.com/karstenevers/gateseal).

| Hook | It fails when | Runs |
| --- | --- | --- |
| `token-budget` | a file is too large to read and review in one piece | at each commit |
| `crap-score-python` | a Python function is both complex and poorly tested | in CI, after the tests |
| `crap-score-typescript` | the same, for TypeScript and JavaScript | in CI, after the tests |

## Use the hooks

Add this to `.pre-commit-config.yaml`. Set `rev` to a commit of this repository.

```yaml
repos:
  - repo: https://github.com/karstenevers/gateseal-hooks
    rev: <commit>
    hooks:
      - id: token-budget
      - id: crap-score-python
        files: ^src/
```

To set an option, add it to `args` and end the list with `--`, for example `args: [--limit, "15", --]`. Then a file name that starts with `-` is not read as an option.

Each hook needs Python 3.11 or later. `crap-score-typescript` also installs the tree-sitter parsers, the others need no other package.

## token-budget

The hook estimates each changed file at 1 token for each 4 bytes. A file passes at 9,000 tokens or less. This is a hard limit: the commit stops until the file is split. A soft warning would not help, because pre-commit hides the output of a hook that passes.

Lockfiles, such as `uv.lock`, and changelogs are exempt.

**Adopt it in a repository with large files.** Run the hook on every file once:

```sh
pre-commit run token-budget --all-files
```

Record each file it lists in `.token-budgets.toml`, at the next 500 above its size:

```toml
[budgets]
"README.md" = 12500
```

A file with a budget may not grow past it. When it shrinks by more than 500 tokens, the hook asks you to lower its budget. When it fits the cap, the hook asks you to remove it. Do not add a budget for a new file. Split the file.

A commit checks only the files it changes. Also run the hook on all files in CI, so it catches a removed budget or a file that left Git.

**Options.** `--cap 12000` sets another cap. `--budgets path.toml` reads the budgets from another file.

## crap-score-python

The CRAP score shows where a change most often breaks something:

```text
CRAP = complexity² × (1 − coverage)³ + complexity
```

Complexity is 1 plus each `if`, loop, `except`, `match` case, `and`, `or` and conditional in the function. Coverage is the share of its lines and branches that the tests run. A function passes at a score of 10 or less. So a fully tested function may have a complexity of 10, and an untested one a complexity of 2.

The hook reads a JSON report from coverage.py 7.13.1 or later, so it does not run at each commit. Run it after the tests, for example in CI:

```sh
coverage run --branch -m pytest
coverage json
pre-commit run crap-score-python --hook-stage manual --all-files
```

Run coverage.py from the repository root, so the report names files the way pre-commit does. The hook scores only the files pre-commit gives it. With `files: ^src/` it skips the tests. To score only the files that a pull request changes, run it with `--from-ref origin/main --to-ref HEAD` in place of `--all-files`. The hook fails when the report does not measure a file it gets. Add the file to coverage.py's `source`, or leave it out with `files` or `exclude`.

**Options.** `--coverage path.json` reads another report. `--limit 15` sets another limit.

## crap-score-typescript

The same check for TypeScript and JavaScript, with the same formula and limit. It reads the Istanbul JSON report that Vitest and Jest write, `coverage/coverage-final.json`:

```sh
npx vitest run --coverage --coverage.reporter=json
pre-commit run crap-score-typescript --hook-stage manual --all-files
```

Complexity is 1 plus each `if`, loop, `catch`, `case`, `? :`, `&&`, `||` and `??` in the function. Optional chaining such as `a?.b` does not count. Each named function is scored on its own: functions, methods, arrow functions in a variable, a class field or an object, and functions nested inside them. A callback without a name counts in the function around it. A function that the report says never ran scores 0%, and so does each function inside it.

The hook fails when a source file does not parse, or when the report has no data for a function. Leave test files out with `exclude`, as they are not in the report. c8 reports work, but count whole lines, so their scores are less exact than those from Vitest or Jest.

The parsers come from three pinned packages, which pre-commit installs with the hook. Nothing is downloaded when it runs.

**Options.** `--coverage path.json` reads another report. `--limit 15` sets another limit.

## Mutation testing

Use the hooks that [pytestmut](https://github.com/martincjespersen/pytestmut) ships. They must run in your project's own environment, because they import your code and run your tests.

## Develop

```sh
uv sync --locked
uv run ruff check .
uv run pyright
uv run pytest
```

The tests marked `integration` install the hooks with pre-commit, which needs the network.

## Security

Do not open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
