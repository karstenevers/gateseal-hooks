"""Fail when a file is over the token cap or over its own budget.

A file's tokens are its size in bytes divided by 4, rounded up. A file passes
at the cap or below. A file in the budgets file passes at its budget instead,
which records a file that was already over the cap when the repository
adopted it. Such a file may not grow past its budget.
"""

import argparse
import os
import subprocess
import sys
import tomllib
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import cast

BYTES_PER_TOKEN = 4
BUDGET_STEP = 500

LOCKFILES = frozenset(
    {
        ".terraform.lock.hcl",
        "Cargo.lock",
        "Gemfile.lock",
        "Package.resolved",
        "Pipfile.lock",
        "Podfile.lock",
        "bun.lock",
        "composer.lock",
        "deno.lock",
        "flake.lock",
        "go.sum",
        "gradle.lockfile",
        "mix.lock",
        "npm-shrinkwrap.json",
        "package-lock.json",
        "packages.lock.json",
        "pdm.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "pubspec.lock",
        "uv.lock",
        "yarn.lock",
    }
)
CHANGELOGS = frozenset({"changelog", "changes", "history", "news"})
CHANGELOG_SUFFIXES = frozenset({"", ".adoc", ".markdown", ".md", ".rst", ".txt"})

SPLIT_ADVICE = """\
Split each file above into files well under the cap:
  - Move each group of code with one responsibility into its own module.
  - Keep the public entry point where it is and import from the new modules.
  - Split a long test file by the behaviour it tests.
Do not add or raise a budget to pass this check. A budget only records a file
that was over the cap when the repository adopted it."""
BUDGETS_ADVICE = "Then commit {budgets} with the change."


class InputError(Exception):
    pass


def tokens(size: int) -> int:
    return -(-size // BYTES_PER_TOKEN)


def fitting_budget(count: int) -> int:
    """Return the smallest budget step above count."""
    return (count // BUDGET_STEP + 1) * BUDGET_STEP


def is_exempt(path: str) -> bool:
    """Lockfiles are generated and changelogs only grow, so the cap skips them."""
    name = Path(path).name
    stem, dot, suffix = name.lower().partition(".")
    return name in LOCKFILES or (
        stem in CHANGELOGS and dot + suffix in CHANGELOG_SUFFIXES
    )


def load_budgets(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise InputError(f"{path}: cannot read TOML: {error}") from error
    if set(document) - {"budgets"}:
        raise InputError(f"{path}: holds tables other than [budgets]")
    table = document.get("budgets", {})
    if not isinstance(table, dict):
        raise InputError(f"{path}: budgets is not a table")
    budgets: dict[str, int] = {}
    for name, value in cast(dict[str, object], table).items():
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise InputError(f"{path}: the budget of {name} is not a positive number")
        budgets[Path(name).as_posix()] = value
    return budgets


def size_findings(
    paths: Iterable[str], cap: int, budgets: dict[str, int]
) -> Iterator[str]:
    for path in sorted(set(paths)):
        if is_exempt(path):
            continue
        count = tokens(Path(path).stat().st_size)
        budget = budgets.get(path)
        if budget is None:
            if count > cap:
                yield f"{path}: about {count:,} tokens, over the cap of {cap:,}."
        elif count > budget:
            yield (
                f"{path}: about {count:,} tokens, over its budget of {budget:,}. "
                "Split the file. Do not raise its budget."
            )


def in_git(paths: list[str]) -> set[str]:
    """Return the paths in Git's index; outside a repository, those on disk."""
    if not paths:
        return set()  # git ls-files with no path lists every file
    command = ["git", "--literal-pathspecs", "ls-files", "-z", "--", *paths]
    try:
        listed = subprocess.run(command, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return {path for path in paths if Path(path).is_file()}
    return {Path(os.fsdecode(name)).as_posix() for name in listed.split(b"\0") if name}


def budget_findings(
    paths: Iterable[str], cap: int, budgets: dict[str, int]
) -> Iterator[str]:
    checked = set(paths)
    tracked = in_git(sorted(budgets))
    for path, budget in sorted(budgets.items()):
        # A sparse checkout leaves a file in the index but not on disk.
        if path not in tracked:
            yield f"{path}: has a budget but is not a file in Git. Rename or remove it."
            continue
        if path not in checked:
            continue
        count = tokens(Path(path).stat().st_size)
        if count <= cap:
            yield (
                f"{path}: about {count:,} tokens, within the cap of {cap:,}. "
                "Remove its budget."
            )
        elif budget - count > BUDGET_STEP:
            yield (
                f"{path}: about {count:,} tokens, more than {BUDGET_STEP:,} under "
                f"its budget of {budget:,}. Lower its budget to "
                f"{fitting_budget(count):,}."
            )


def arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cap", type=int, default=9000, help="highest passing tokens")
    parser.add_argument(
        "--budgets",
        type=Path,
        default=Path(".token-budgets.toml"),
        help="TOML file with a [budgets] table of path = tokens",
    )
    parser.add_argument("files", nargs="*", help="files to check")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    options = arguments(argv)
    cap = cast(int, options.cap)
    budgets_path = cast(Path, options.budgets)
    files = [Path(file).as_posix() for file in cast(list[str], options.files)]
    try:
        budgets = load_budgets(budgets_path)
    except InputError as error:
        print(f"token-budget: {error}", file=sys.stderr)
        return 1
    if budgets_path in {Path(file) for file in files}:
        files = [*files, *(path for path in budgets if Path(path).is_file())]
    oversized = list(size_findings(files, cap, budgets))
    stale = list(budget_findings(files, cap, budgets))
    if oversized:
        print("\n".join([*oversized, SPLIT_ADVICE]))
    if stale:
        print("\n".join([*stale, BUDGETS_ADVICE.format(budgets=budgets_path)]))
    return 1 if oversized or stale else 0
