"""Command line and JSON input checks that every CRAP reader shares."""

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import cast


class InputError(Exception):
    def __init__(self, path: str, detail: str) -> None:
        super().__init__(f"{path}: {detail}")


def as_object(value: object, path: str, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise InputError(path, f"{where} is not a JSON object")
    return cast(dict[str, object], value)


def as_list(value: object, path: str, where: str) -> list[object]:
    if not isinstance(value, list):
        raise InputError(path, f"{where} is not a JSON array")
    return cast(list[object], value)


def as_count(value: object, path: str, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InputError(path, f"{where} is not a count")
    return value


def load_json(path: str) -> object:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InputError(path, f"cannot read JSON: {error}") from error


def finite(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise argparse.ArgumentTypeError(f"{text} is not a finite number")
    return value


@dataclass(frozen=True)
class Options:
    coverage: str
    limit: float
    files: list[str]


def arguments(
    argv: list[str] | None, description: str | None, default_coverage: str
) -> Options:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--coverage", default=default_coverage, help="coverage report")
    parser.add_argument("--limit", type=finite, default=10, help="highest passing")
    parser.add_argument("files", nargs="*", help="score only these files")
    options = parser.parse_args(argv)
    return Options(
        cast(str, options.coverage),
        cast(float, options.limit),
        cast(list[str], options.files),
    )
