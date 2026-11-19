"""The CRAP score and its report, the same for every language.

CRAP = complexity² × (1 − coverage)³ + complexity, per function.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Score:
    file: str
    function: str
    score: float
    complexity: int
    coverage: float


def crap(complexity: int, coverage: float) -> float:
    return complexity**2 * (1 - coverage) ** 3 + complexity


def share(covered: int, statements: int, covered_branches: int, branches: int) -> float:
    """Return the share of statements and branches covered; 1.0 when there are none."""
    total = statements + branches
    return 1.0 if total == 0 else (covered + covered_branches) / total


def is_over(score: float, limit: float) -> bool:
    """Float error alone never puts a score equal to the limit over it."""
    return score > limit and not math.isclose(score, limit)


def table(scores: list[Score]) -> list[str]:
    rows = [("file", "function", "score", "complexity", "coverage")]
    rows += [
        (
            score.file,
            score.function,
            f"{score.score:.2f}",
            str(score.complexity),
            f"{score.coverage * 100:.1f}%",
        )
        for score in scores
    ]
    widths = [max(len(row[column]) for row in rows) for column in range(5)]
    return [
        "  ".join(
            cell.rjust(width) if column >= 2 else cell.ljust(width)
            for column, (cell, width) in enumerate(zip(row, widths, strict=True))
        )
        for row in rows
    ]


def report(
    scores: list[Score],
    limit: float,
    allows: Callable[[Score], bool],
    findings: list[str],
) -> int:
    """Print each score over the limit that allows refuses, findings and a summary.

    Return the exit code.
    """
    over = sorted(
        (score for score in scores if is_over(score.score, limit)),
        key=lambda score: (score.file, score.function),
    )
    failing = [score for score in over if not allows(score)]
    if failing:
        print("\n".join(table(failing)))
    for finding in findings:
        print(finding)
    allowed = len(over) - len(failing)
    print(
        f"{len(scores)} functions scored, {len(failing)} over the limit of {limit:g}"
        + (f", {allowed} on the baseline" if allowed else "")
    )
    return 1 if failing or findings else 0
