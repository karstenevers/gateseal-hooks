"""The CRAP score and its report, the same for every language.

CRAP = complexity² × (1 − coverage)³ + complexity, per function.
"""

import math
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


def report(scores: list[Score], limit: float) -> int:
    """Print each score over the limit and a summary; return the exit code."""
    over = sorted(
        (score for score in scores if is_over(score.score, limit)),
        key=lambda score: (score.file, score.function),
    )
    if over:
        print("\n".join(table(over)))
    print(f"{len(scores)} functions scored, {len(over)} over the limit of {limit:g}")
    return 1 if over else 0
