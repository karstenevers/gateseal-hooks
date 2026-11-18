import pytest

from gateseal_hooks import token_budget


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def write(root, name, size):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return name


def budgets(root, text):
    (root / ".token-budgets.toml").write_text(text)


def run(capsys, *argv):
    code = token_budget.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out.splitlines(), captured.err


def test_file_at_the_cap_passes(root, capsys):
    name = write(root, "a.py", 36_000)
    assert run(capsys, name) == (0, [], "")


def test_one_byte_over_the_cap_fails(root, capsys):
    name = write(root, "a.py", 36_001)
    code, out, _ = run(capsys, name)
    assert code == 1
    assert out[0] == "a.py: about 9,001 tokens, over the cap of 9,000."
    assert "Do not add or raise a budget to pass this check." in "\n".join(out)


def test_cap_option(root, capsys):
    name = write(root, "a.py", 401)
    code, out, _ = run(capsys, "--cap", "100", name)
    assert code == 1
    assert out[0] == "a.py: about 101 tokens, over the cap of 100."


@pytest.mark.parametrize(
    "name",
    ["uv.lock", "web/package-lock.json", "CHANGELOG.md", "docs/NEWS", "History.rst"],
)
def test_lockfiles_and_changelogs_are_exempt(root, capsys, name):
    write(root, name, 100_000)
    assert run(capsys, name) == (0, [], "")


@pytest.mark.parametrize("name", ["changelog_tool.py", "history.py", "uv.lock.bak"])
def test_names_like_exempt_files_are_checked(root, capsys, name):
    write(root, name, 100_000)
    code, out, _ = run(capsys, name)
    assert code == 1
    assert out[0].startswith(f"{name}: about 25,000 tokens")


def test_file_within_its_budget_passes(root, capsys):
    name = write(root, "big.md", 48_000)
    budgets(root, '[budgets]\n"big.md" = 12000\n')
    assert run(capsys, name) == (0, [], "")


def test_file_over_its_budget_fails(root, capsys):
    name = write(root, "big.md", 48_004)
    budgets(root, '[budgets]\n"big.md" = 12000\n')
    code, out, _ = run(capsys, name)
    assert code == 1
    assert out[0] == (
        "big.md: about 12,001 tokens, over its budget of 12,000. "
        "Split the file. Do not raise its budget."
    )


def test_budget_no_longer_needed_fails(root, capsys):
    name = write(root, "big.md", 36_000)
    budgets(root, '[budgets]\n"big.md" = 12000\n')
    code, out, _ = run(capsys, name)
    assert code == 1
    assert out[0] == (
        "big.md: about 9,000 tokens, within the cap of 9,000. Remove its budget."
    )
    assert out[-1] == "Then commit .token-budgets.toml with the change."


def test_loose_budget_fails_with_the_fitting_budget(root, capsys):
    name = write(root, "big.md", 40_000)
    budgets(root, '[budgets]\n"big.md" = 12000\n')
    code, out, _ = run(capsys, name)
    assert code == 1
    assert out[0] == (
        "big.md: about 10,000 tokens, more than 500 under its budget of 12,000. "
        "Lower its budget to 10,500."
    )


def test_fitting_budget_passes(root, capsys):
    name = write(root, "big.md", 40_000)
    budgets(root, '[budgets]\n"big.md" = 10500\n')
    assert run(capsys, name) == (0, [], "")


def test_loose_budget_of_an_unchanged_file_passes(root, capsys):
    write(root, "big.md", 40_000)
    name = write(root, "small.py", 10)
    budgets(root, '[budgets]\n"big.md" = 12000\n')
    assert run(capsys, name) == (0, [], "")


def test_budget_of_a_missing_file_fails(root, capsys):
    name = write(root, "small.py", 10)
    budgets(root, '[budgets]\n"gone.md" = 12000\n')
    code, out, _ = run(capsys, name)
    assert code == 1
    assert out[0] == "gone.md: has a budget but is not a file. Rename or remove it."


def test_changed_budgets_file_checks_every_budgeted_file(root, capsys):
    write(root, "big.md", 40_000)
    write(root, "loose.md", 40_000)
    budgets(root, '[budgets]\n"big.md" = 9500\n"loose.md" = 12000\n')
    code, out, _ = run(capsys, ".token-budgets.toml")
    assert code == 1
    assert out[0] == (
        "big.md: about 10,000 tokens, over its budget of 9,500. "
        "Split the file. Do not raise its budget."
    )
    assert out[-2].startswith("loose.md: about 10,000 tokens, more than 500 under")


def test_changed_budgets_file_with_a_missing_file_names_it(root, capsys):
    budgets(root, '[budgets]\n"gone.md" = 12000\n')
    code, out, _ = run(capsys, ".token-budgets.toml")
    assert code == 1
    assert out[0] == "gone.md: has a budget but is not a file. Rename or remove it."


def test_budgets_option_names_the_file(root, capsys):
    name = write(root, "big.md", 48_000)
    (root / "limits.toml").write_text('[budgets]\n"big.md" = 12000\n')
    assert run(capsys, "--budgets", "limits.toml", name) == (0, [], "")


@pytest.mark.parametrize(
    ("text", "detail"),
    [
        ("[budgets\n", "cannot read TOML"),
        ('[other]\n"a" = 1\n', "holds tables other than [budgets]"),
        ('budgets = "a"\n', "budgets is not a table"),
        ('[budgets]\n"a.py" = "10"\n', "the budget of a.py is not a positive number"),
        ('[budgets]\n"a.py" = 0\n', "the budget of a.py is not a positive number"),
        ('[budgets]\n"a.py" = true\n', "the budget of a.py is not a positive number"),
    ],
)
def test_bad_budgets_file_fails(root, capsys, text, detail):
    name = write(root, "a.py", 10)
    budgets(root, text)
    code, out, err = run(capsys, name)
    assert (code, out) == (1, [])
    assert err.startswith("token-budget: .token-budgets.toml: ")
    assert detail in err
