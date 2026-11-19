import subprocess

import pytest
from test_crap_python import branchy, project
from test_crap_typescript import recorded

from gateseal_hooks.crap import python as crap
from gateseal_hooks.crap import typescript

BASELINE = ".crap-baseline.toml"


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PRE_COMMIT_FROM_REF", raising=False)
    return tmp_path


def baseline(root, entries):
    lines = []
    for file, functions in entries.items():
        lines.append(f'[baseline."{file}"]')
        lines += [f"{name} = {score}" for name, score in functions.items()]
    (root / BASELINE).write_text("\n".join(lines) + "\n")


def run(capsys, *arguments):
    code = crap.main(["--coverage", "coverage.json", *arguments])
    captured = capsys.readouterr()
    return code, captured.out.splitlines(), captured.err


def commit(root, monkeypatch):
    def git(*arguments):
        subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True)

    if not (root / ".git").exists():
        git("init", "-q")
        git("config", "user.email", "test@example.com")
        git("config", "user.name", "test")
        git("config", "commit.gpgsign", "false")
    git("add", "-A")
    git("commit", "-q", "--allow-empty", "-m", "base")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True
    )
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", head.stdout.decode().strip())


def test_config_sets_the_limit(root, capsys):
    project(root, {"m.py": branchy("big", 12)})
    (root / "crap.toml").write_text("limit = 15\n")
    code, out, _ = run(capsys, "--config", "crap.toml")
    assert code == 0
    assert out[-1] == "1 functions scored, 0 over the limit of 15"


@pytest.mark.parametrize(
    "content",
    ['limit = "15"\n', "limit = true\n", "limit = nan\n", "limit = 15\nextra = 1\n"],
)
def test_config_without_a_finite_limit_alone_is_refused(root, content):
    project(root, {"m.py": branchy("f", 1)})
    (root / "crap.toml").write_text(content)
    with pytest.raises(SystemExit) as refused:
        crap.main(["--coverage", "coverage.json", "--config", "crap.toml"])
    assert refused.value.code == 2


def test_config_and_limit_together_are_refused(root):
    project(root, {"m.py": branchy("f", 1)})
    (root / "crap.toml").write_text("limit = 15\n")
    with pytest.raises(SystemExit) as refused:
        crap.main(["--config", "crap.toml", "--limit", "15"])
    assert refused.value.code == 2


def test_missing_config_is_refused(root):
    with pytest.raises(SystemExit) as refused:
        crap.main(["--config", "absent.toml"])
    assert refused.value.code == 2


def test_offender_up_to_its_entry_passes(root, capsys):
    project(root, {"m.py": branchy("ok", 1) + branchy("over", 11)})
    baseline(root, {"m.py": {"over": 11.0}})
    code, out, _ = run(capsys)
    assert code == 0
    assert out == ["2 functions scored, 0 over the limit of 10, 1 on the baseline"]


def test_offender_past_its_entry_fails(root, capsys):
    project(root, {"m.py": branchy("over", 12)})
    baseline(root, {"m.py": {"over": 11.5}})
    code, out, _ = run(capsys)
    assert code == 1
    assert "m.py over: score 12.00 is over its baseline entry of 11.50." in out, out


def test_entry_of_a_function_within_the_limit_must_go(root, capsys):
    project(root, {"m.py": branchy("fixed", 3)})
    baseline(root, {"m.py": {"fixed": 14}})
    code, out, _ = run(capsys)
    assert code == 1
    assert (
        f"m.py fixed: score 3.00 is within the limit of 10; remove its entry from "
        f"{BASELINE}." in out
    )


def test_entry_of_a_removed_function_must_go(root, capsys):
    project(root, {"m.py": branchy("kept", 1)})
    baseline(root, {"m.py": {"gone": 14}})
    code, out, _ = run(capsys)
    assert code == 1
    assert f"m.py gone: no such function; remove its entry from {BASELINE}." in out


def test_entry_of_a_file_left_out_is_not_checked(root, capsys):
    project(root, {"a.py": branchy("over", 11), "b.py": branchy("ok", 1)})
    baseline(root, {"a.py": {"other": 14}})
    code, out, _ = run(capsys, "b.py")
    assert (code, out) == (0, ["1 functions scored, 0 over the limit of 10"])


def test_baseline_option_reads_another_file(root, capsys):
    project(root, {"m.py": branchy("over", 11)})
    (root / "other.toml").write_text('[baseline."m.py"]\nover = 11\n')
    code, _, _ = run(capsys, "--baseline", "other.toml")
    assert code == 0


@pytest.mark.parametrize(
    "content",
    [
        "baseline = 1\n",
        '[baseline]\n"m.py" = 1\n',
        '[baseline."m.py"]\nover = "11"\n',
        '[baseline."m.py"]\nover = -1\n',
        '[baseline."m.py"]\nover = inf\n',
        "[other]\n",
        "not toml",
    ],
)
def test_malformed_baseline_fails_naming_the_file(root, capsys, content):
    project(root, {"m.py": branchy("over", 11)})
    (root / BASELINE).write_text(content)
    code, _, error = run(capsys)
    assert code == 1
    assert error.startswith(f"crap-score-python: {BASELINE}: "), error


def test_change_that_adds_an_entry_fails(root, capsys, monkeypatch):
    project(root, {"m.py": branchy("old", 11) + branchy("new", 12)})
    baseline(root, {"m.py": {"old": 11}})
    commit(root, monkeypatch)
    baseline(root, {"m.py": {"old": 11, "new": 12}})
    code, out, _ = run(capsys)
    assert code == 1
    assert f"m.py new: a change may not add an entry to {BASELINE}." in out


def test_change_that_raises_an_entry_fails(root, capsys, monkeypatch):
    project(root, {"m.py": branchy("old", 12)})
    baseline(root, {"m.py": {"old": 11}})
    commit(root, monkeypatch)
    baseline(root, {"m.py": {"old": 12}})
    code, out, _ = run(capsys)
    assert code == 1
    assert (
        f"m.py old: a change may not raise its entry in {BASELINE} from 11.00 to "
        "12.00." in out
    )


def test_change_that_lowers_or_removes_entries_passes(root, capsys, monkeypatch):
    project(root, {"m.py": branchy("a", 11) + branchy("b", 1)})
    baseline(root, {"m.py": {"a": 13, "b": 14}})
    commit(root, monkeypatch)
    baseline(root, {"m.py": {"a": 11}})
    code, out, _ = run(capsys)
    assert code == 0, out


def test_baseline_that_the_base_lacks_is_adopted(root, capsys, monkeypatch):
    project(root, {"m.py": branchy("old", 11)})
    commit(root, monkeypatch)
    baseline(root, {"m.py": {"old": 11}})
    code, out, _ = run(capsys)
    assert code == 0, out


def test_unknown_base_commit_fails(root, capsys, monkeypatch):
    project(root, {"m.py": branchy("old", 11)})
    commit(root, monkeypatch)
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", "0" * 40)
    baseline(root, {"m.py": {"old": 11}})
    code, _, error = run(capsys)
    assert code == 1
    assert f"PRE_COMMIT_FROM_REF {'0' * 40} is not a commit" in error


def test_typescript_scores_honor_the_baseline(root, capsys):
    report = str(recorded(root, "jest"))
    over = [s for s in typescript.read_report(report) if s.score > 10]
    assert typescript.main(["--coverage", report]) == 1
    entries: dict[str, dict[str, float]] = {}
    for score in over:
        entries.setdefault(score.file, {})[f'"{score.function}"'] = score.score
    baseline(root, entries)
    capsys.readouterr()
    assert typescript.main(["--coverage", report]) == 0
    assert capsys.readouterr().out.endswith(f"{len(over)} on the baseline\n")
