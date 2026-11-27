"""The baseline: functions that may stay over the limit, each up to its entry.

A change may lower or remove an entry, but not add or raise one. When
PRE_COMMIT_FROM_REF names a commit, as pre-commit sets it for a push or a
range, the file is compared with its versions at the commits that the change
builds on. An entry may stay at the highest score that any of them holds. A
baseline that none of them holds is being adopted, so nothing is compared.
"""

import math
import os
import subprocess
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from gateseal_hooks.crap.inputs import InputError, as_object
from gateseal_hooks.crap.score import Score, is_over

Key = tuple[str, str]
"""A function's file and name, as the scores name them."""


def parse_entries(text: str, path: str) -> dict[Key, float]:
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise InputError(path, f"cannot read TOML: {error}") from error
    if set(document) != {"baseline"}:
        raise InputError(path, "must hold only a [baseline] table")
    entries: dict[Key, float] = {}
    for file, functions in as_object(document["baseline"], path, "baseline").items():
        where = f'baseline."{file}"'
        for name, score in as_object(functions, path, where).items():
            if (
                isinstance(score, bool)
                or not isinstance(score, int | float)
                or not math.isfinite(score)
                or score < 0
            ):
                raise InputError(path, f"{where}.{name} is not a score")
            entries[(Path(file).as_posix(), name)] = float(score)
    return entries


def git(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *arguments], capture_output=True, check=False)


def bases(path: str, start: str) -> list[str]:
    """Return the commits that the change from start builds on.

    In a range, that is its start. At a push, they are the commits that the
    remote already has and the pushed commits build on, so entries that a
    rebase or a merge brings from another branch are not new, and neither are
    those of a rewritten branch's old tip. The remote's tip of the pushed
    branch is start, so its tracking ref, which may be stale, is no base. A
    push of commits that the remote already has builds on its own end.
    """
    if git("rev-parse", "--verify", "--quiet", f"{start}^{{commit}}").returncode:
        raise InputError(path, f"PRE_COMMIT_FROM_REF {start} is not a commit")
    remote = os.environ.get("PRE_COMMIT_REMOTE_NAME")
    if not remote:
        return [start]
    end = os.environ.get("PRE_COMMIT_TO_REF") or "HEAD"
    branch = os.environ.get("PRE_COMMIT_REMOTE_BRANCH", "").removeprefix("refs/heads/")
    stale = [f"--exclude={remote}/{branch}"] if branch else []
    listed = git(
        "rev-list", "--boundary", end, "--not", start, *stale, f"--remotes={remote}"
    )
    found = [line[1:] for line in listed.stdout.decode().split() if line[0] == "-"]
    return found or [end]


def entries_at(path: str, commit: str) -> dict[Key, float] | None:
    shown = git("show", f"{commit}:./{path}")
    if shown.returncode:
        return None
    return parse_entries(shown.stdout.decode("utf-8"), f"{path} at {commit}")


def based_entries(path: str, start: str) -> dict[Key, float] | None:
    """Return each entry at its highest score in the bases that hold the file.

    When none holds it, but start does, as after a rebase of a branch that
    adopted the baseline onto one that has none, compare with start.
    """
    based: dict[Key, float] | None = None
    for commit in bases(path, start):
        entries = entries_at(path, commit)
        if entries is None:
            continue
        based = based or {}
        for key, score in entries.items():
            based[key] = max(score, based.get(key, score))
    return entries_at(path, start) if based is None else based


@dataclass(frozen=True)
class Baseline:
    path: str
    entries: Mapping[Key, float]
    based: Mapping[Key, float] | None

    def allows(self, score: Score) -> bool:
        entry = self.entries.get((score.file, score.function))
        return entry is not None and not is_over(score.score, entry)

    def findings(self, scores: list[Score], limit: float) -> list[str]:
        """Name each entry that a score outgrew, that is due to go, or that is new.

        Only entries of the scored files are compared with the scores.
        """
        found: list[str] = []
        scored = {(score.file, score.function): score for score in scores}
        files = {file for file, _ in scored}
        remove = f"remove its entry from {self.path}."
        for key, entry in sorted(self.entries.items()):
            file, name = key
            score = scored.get(key)
            if file not in files:
                continue
            if score is None:
                found.append(f"{file} {name}: no such function; {remove}")
            elif not is_over(score.score, limit):
                found.append(
                    f"{file} {name}: score {score.score:.2f} is within the limit of "
                    f"{limit:g}; {remove}"
                )
            elif is_over(score.score, entry):
                found.append(
                    f"{file} {name}: score {score.score:.2f} is over its baseline "
                    f"entry of {entry:.2f}."
                )
        return found + self.growth()

    def growth(self) -> list[str]:
        """Name each entry that the change adds or raises."""
        if self.based is None:
            return []
        found: list[str] = []
        for (file, name), entry in sorted(self.entries.items()):
            before = self.based.get((file, name))
            if before is None:
                found.append(
                    f"{file} {name}: a change may not add an entry to {self.path}."
                )
            elif entry > before:
                found.append(
                    f"{file} {name}: a change may not raise its entry in {self.path} "
                    f"from {before:.2f} to {entry:.2f}."
                )
        return found


def load_baseline(path: str) -> Baseline:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return Baseline(path, {}, None)
    except (OSError, UnicodeDecodeError) as error:
        raise InputError(path, f"cannot read: {error}") from error
    start = os.environ.get("PRE_COMMIT_FROM_REF", "")
    based = based_entries(path, start) if start else None
    return Baseline(path, parse_entries(text, path), based)
