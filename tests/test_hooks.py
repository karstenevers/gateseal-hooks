import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

HOOKS = Path(__file__).resolve().parents[1]
FIXTURES = HOOKS / "tests" / "fixtures" / "typescript"


@pytest.fixture(scope="module")
def environment(tmp_path_factory):
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("COVERAGE_", "GIT_"))
    }
    env["PRE_COMMIT_HOME"] = str(tmp_path_factory.mktemp("pre-commit-home"))
    return env


@pytest.fixture
def repository(tmp_path, environment):
    def git(*arguments):
        subprocess.run(["git", *arguments], cwd=tmp_path, env=environment, check=True)

    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "test")
    git("config", "commit.gpgsign", "false")
    return tmp_path


def try_hook(repository, environment, hook, *options):
    subprocess.run(["git", "add", "-A"], cwd=repository, env=environment, check=True)
    command = ["pre_commit", "try-repo", str(HOOKS), hook, *options]
    return subprocess.run(
        [sys.executable, "-m", *command],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_token_budget_fails_a_file_over_the_cap(repository, environment):
    (repository / "small.py").write_text("x = 1\n")
    (repository / "big.md").write_bytes(b"word " * 8_000)
    result = try_hook(repository, environment, "token-budget", "--all-files")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "big.md: about 10,000 tokens, over the cap of 9,000." in result.stdout
    assert "small.py" not in result.stdout


def test_token_budget_passes_a_budgeted_file(repository, environment):
    (repository / "big.md").write_bytes(b"word " * 8_000)
    (repository / ".token-budgets.toml").write_text('[budgets]\n"big.md" = 10500\n')
    result = try_hook(repository, environment, "token-budget", "--all-files")
    assert result.returncode == 0, result.stdout + result.stderr


def test_token_budget_runs_when_a_commit_only_deletes_a_budgeted_file(
    repository, environment
):
    (repository / "big.md").write_bytes(b"word " * 8_000)
    (repository / ".token-budgets.toml").write_text('[budgets]\n"big.md" = 10500\n')
    subprocess.run(["git", "add", "-A"], cwd=repository, env=environment, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "add"],
        cwd=repository,
        env=environment,
        check=True,
    )
    (repository / "big.md").unlink()
    result = try_hook(repository, environment, "token-budget")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "big.md: has a budget but is not a file in Git." in result.stdout


def test_crap_score_python_reads_a_real_coverage_report(repository, environment):
    (repository / "shapes.py").write_text(
        textwrap.dedent(
            """
            def sides(kind):
                if kind == "triangle":
                    return 3
                if kind == "square":
                    return 4
                return 0


            def untested(a, b, c):
                if a and b:
                    return 1
                return 2 if c else 3
            """
        ).lstrip()
    )
    (repository / "drive.py").write_text(
        "from shapes import sides\n\nassert sides('square') == 4\n"
    )
    for command in (
        ["run", "--branch", "--source", ".", "drive.py"],
        ["json", "-o", "coverage.json"],
    ):
        subprocess.run(
            [sys.executable, "-m", "coverage", *command],
            cwd=repository,
            env=environment,
            check=True,
            capture_output=True,
        )
    result = try_hook(
        repository,
        environment,
        "crap-score-python",
        "--all-files",
        "--hook-stage",
        "manual",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "shapes.py  untested  20.00           4      0.0%" in result.stdout
    assert "2 functions scored, 1 over the limit of 10" in result.stdout


def test_crap_score_typescript_reads_a_recorded_report(repository, environment):
    (repository / "src").mkdir()
    for source in ("cases.ts", "legacy.js"):
        shutil.copy(FIXTURES / source, repository / "src" / source)
    document = json.loads((FIXTURES / "vitest-v8.json").read_text())
    report = {str(repository / key): entry for key, entry in document.items()}
    (repository / "coverage").mkdir()
    (repository / "coverage" / "coverage-final.json").write_text(json.dumps(report))
    result = try_hook(
        repository,
        environment,
        "crap-score-typescript",
        "--all-files",
        "--hook-stage",
        "manual",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "untestedBranchy" in result.stdout
    assert "19 functions scored, 9 over the limit of 10" in result.stdout
