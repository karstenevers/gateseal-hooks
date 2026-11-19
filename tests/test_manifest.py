import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_typescript_hook_pins_the_parsers_of_the_typescript_extra():
    hooks = yaml.safe_load((ROOT / ".pre-commit-hooks.yaml").read_text())
    hook = next(hook for hook in hooks if hook["id"] == "crap-score-typescript")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert (
        hook["additional_dependencies"]
        == project["optional-dependencies"]["typescript"]
    )


def test_every_hook_entry_is_a_command_of_the_package():
    hooks = yaml.safe_load((ROOT / ".pre-commit-hooks.yaml").read_text())
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
    assert {hook["entry"] for hook in hooks} == set(scripts)
