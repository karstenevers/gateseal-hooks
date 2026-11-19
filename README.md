Plain [pre-commit](https://pre-commit.com) hooks, usable with or without [gateseal](https://github.com/karstenevers/gateseal).

| Hook | It fails when | Runs |
| --- | --- | --- |
| `token-budget` | a file is too large to read and review in one piece | at each commit |
| `crap-score-python` | a Python function is both complex and poorly tested | in CI, after the tests |

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

Each hook needs Python 3.11 or later and no other package.

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

It scores only the files pre-commit gives it. With `files: ^src/` it skips the tests. To score only the files that a pull request changes, run it with `--from-ref origin/main --to-ref HEAD` in place of `--all-files`. The hook fails when the report does not measure a file it gets. Add the file to coverage.py's `source`, or leave it out with `files` or `exclude`.

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
