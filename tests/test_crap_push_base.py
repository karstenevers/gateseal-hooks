"""The baseline at a push compares with the commits the remote already has."""

import subprocess

import pytest
from test_crap_baseline import BASELINE, baseline, run
from test_crap_python import branchy, project

SOURCES = {"m.py": branchy("old", 11) + branchy("new", 12)}


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ("FROM_REF", "TO_REF", "REMOTE_NAME", "REMOTE_BRANCH"):
        monkeypatch.delenv(f"PRE_COMMIT_{name}", raising=False)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "test")
    git("config", "commit.gpgsign", "false")
    project(tmp_path, SOURCES)
    (tmp_path / ".gitignore").write_text("coverage.json\n")
    return tmp_path


def git(*arguments):
    done = subprocess.run(["git", *arguments], check=True, capture_output=True)
    return done.stdout.decode().strip()


def snapshot(root, message):
    (root / f"{message}.txt").write_text(message)
    git("add", "-A")
    git("commit", "-q", "-m", message)
    return git("rev-parse", "HEAD")


def published(name):
    """Record HEAD as the remote's branch name, as a fetch or a push does."""
    git("update-ref", f"refs/remotes/origin/{name}", "HEAD")
    return git("rev-parse", "HEAD")


def push(monkeypatch, old, branch="feature"):
    """Set what pre-commit sets at a push from old to HEAD."""
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", old)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", git("rev-parse", "HEAD"))
    monkeypatch.setenv("PRE_COMMIT_REMOTE_NAME", "origin")
    monkeypatch.setenv("PRE_COMMIT_REMOTE_BRANCH", f"refs/heads/{branch}")


def main_gains_new(root):
    """Branch feature off main, then add an entry on main; return the old tip."""
    baseline(root, {"m.py": {"old": 11}})
    snapshot(root, "C0")
    published("main")
    git("switch", "-q", "-c", "feature")
    snapshot(root, "feature work")
    old = published("feature")
    git("switch", "-q", "main")
    baseline(root, {"m.py": {"old": 11, "new": 12}})
    snapshot(root, "main adds an entry")
    published("main")
    git("switch", "-q", "feature")
    return old


def test_rebase_onto_entries_of_main_passes(root, capsys, monkeypatch):
    old = main_gains_new(root)
    git("rebase", "-q", "main")
    push(monkeypatch, old)
    code, out, _ = run(capsys)
    assert code == 0, out


def test_rebased_branch_that_adds_an_entry_fails(root, capsys, monkeypatch):
    old = main_gains_new(root)
    git("rebase", "-q", "main")
    baseline(root, {"m.py": {"old": 11, "new": 12}, "own.py": {"f": 20}})
    snapshot(root, "feature adds an entry")
    push(monkeypatch, old)
    code, out, _ = run(capsys)
    assert code == 1
    assert f"own.py f: a change may not add an entry to {BASELINE}." in out
    assert not any(line.startswith("m.py new:") for line in out), out


def test_merge_of_entries_of_main_passes(root, capsys, monkeypatch):
    old = main_gains_new(root)
    git("merge", "-q", "--no-edit", "main")
    snapshot(root, "more work")
    push(monkeypatch, old)
    code, out, _ = run(capsys)
    assert code == 0, out


def rewrite_without_a_removal(root):
    """Push a branch that removes an entry, then rewrite it; return the old tip."""
    baseline(root, {"m.py": {"old": 11, "new": 12}, "gone.py": {"f": 20}})
    base = snapshot(root, "C0")
    published("main")
    git("switch", "-q", "-c", "feature")
    baseline(root, {"m.py": {"old": 11, "new": 12}})
    snapshot(root, "remove an entry")
    old = published("feature")
    git("reset", "-q", "--hard", base)
    snapshot(root, "redo without the removal")
    return old


def test_rewrite_that_drops_a_removal_passes(root, capsys, monkeypatch):
    push(monkeypatch, rewrite_without_a_removal(root))
    code, out, _ = run(capsys)
    assert code == 0, out


def test_range_compares_with_its_start(root, capsys, monkeypatch):
    push(monkeypatch, rewrite_without_a_removal(root))
    monkeypatch.delenv("PRE_COMMIT_REMOTE_NAME")
    code, out, _ = run(capsys)
    assert code == 1
    assert f"gone.py f: a change may not add an entry to {BASELINE}." in out


def test_entry_raised_past_every_base_fails(root, capsys, monkeypatch):
    old = main_gains_new(root)
    git("merge", "-q", "--no-edit", "main")
    baseline(root, {"m.py": {"old": 11, "new": 13}})
    snapshot(root, "raise an entry")
    push(monkeypatch, old)
    code, out, _ = run(capsys)
    assert code == 1
    assert (
        f"m.py new: a change may not raise its entry in {BASELINE} from 12.00 to "
        "13.00." in out
    )


def test_rebase_of_a_branch_that_adopted_the_baseline_checks_it(
    root, capsys, monkeypatch
):
    snapshot(root, "C0")
    published("main")
    git("switch", "-q", "-c", "feature")
    baseline(root, {"m.py": {"old": 11, "new": 12}})
    snapshot(root, "adopt a baseline")
    old = published("feature")
    git("switch", "-q", "main")
    snapshot(root, "main moves on")
    published("main")
    git("switch", "-q", "feature")
    git("rebase", "-q", "main")
    baseline(root, {"m.py": {"old": 11, "new": 12}, "own.py": {"f": 20}})
    snapshot(root, "feature adds an entry")
    push(monkeypatch, old)
    code, out, _ = run(capsys)
    assert code == 1
    assert f"own.py f: a change may not add an entry to {BASELINE}." in out


def test_stale_tracking_ref_of_the_destination_is_no_base(root, capsys, monkeypatch):
    baseline(root, {"m.py": {"old": 11, "new": 12}})
    reset = snapshot(root, "C0")
    published("main")
    git("switch", "-q", "-c", "feature")
    baseline(root, {"m.py": {"old": 11, "new": 12}, "gone.py": {"f": 20}})
    snapshot(root, "add an entry that the remote then drops")
    published("feature")
    snapshot(root, "more work")
    push(monkeypatch, reset)
    code, out, _ = run(capsys)
    assert code == 1
    assert f"gone.py f: a change may not add an entry to {BASELINE}." in out


def test_fast_forward_to_published_commits_passes(root, capsys, monkeypatch):
    baseline(root, {"m.py": {"old": 11}})
    old = snapshot(root, "C0")
    published("main")
    git("switch", "-q", "-c", "feature")
    published("feature")
    git("switch", "-q", "main")
    baseline(root, {"m.py": {"old": 11, "new": 12}})
    snapshot(root, "main adds an entry")
    published("main")
    git("switch", "-q", "feature")
    git("merge", "-q", "--ff-only", "main")
    push(monkeypatch, old)
    code, out, _ = run(capsys)
    assert code == 0, out


def test_shallow_history_compares_with_the_old_tip(root, capsys, monkeypatch):
    baseline(root, {"m.py": {"old": 11, "new": 12}})
    snapshot(root, "C0")
    published("main")
    git("switch", "-q", "-c", "feature")
    old = snapshot(root, "feature work")
    published("feature")
    git("reset", "-q", "--hard", "main")
    shallow = snapshot(root, "redo the work")
    (root / ".git" / "shallow").write_text(shallow + "\n")
    baseline(root, {"m.py": {"old": 11, "new": 12}, "own.py": {"f": 20}})
    snapshot(root, "feature adds an entry")
    push(monkeypatch, old)
    code, out, _ = run(capsys)
    assert code == 1
    assert f"own.py f: a change may not add an entry to {BASELINE}." in out


def test_rebase_keeps_the_entries_that_the_old_tip_published(root, capsys, monkeypatch):
    snapshot(root, "C0")
    published("main")
    git("switch", "-q", "-c", "feature")
    baseline(root, {"m.py": {"old": 11, "new": 12}})
    snapshot(root, "adopt a baseline on the branch")
    old = published("feature")
    git("switch", "-q", "main")
    baseline(root, {"m.py": {"old": 11}})
    snapshot(root, "main adopts its own baseline")
    published("main")
    git("switch", "-q", "feature")
    git("rebase", "-q", "-X", "theirs", "main")
    baseline(root, {"m.py": {"old": 11, "new": 12}})
    snapshot(root, "keep both entries")
    push(monkeypatch, old)
    code, out, _ = run(capsys)
    assert code == 0, out
