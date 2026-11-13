from __future__ import annotations

import pytest

from envxx import store
from envxx.cli import _match_selector, _split_target, main
from envxx.errors import UsageError


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv(store.HOME_ENV, str(tmp_path / "home"))
    return tmp_path / "home"


@pytest.mark.parametrize(
    "token,expected",
    [
        ("python3.11", ("python", "3.11")),
        ("python3", ("python", "3")),
        ("python3.11.9", ("python", "3.11.9")),
        ("py3.12", ("python", "3.12")),
        ("node22", ("node", "22")),
        ("node", None),
        ("python", None),
        ("nodejs22", ("node", "22")),
        ("python search", None),
        ("python3.11-m", None),
    ],
)
def test_match_selector(token, expected):
    matched = _match_selector(token)
    if expected is None:
        assert matched is None
    else:
        spec, query = matched
        assert (spec.name, query) == expected


@pytest.mark.parametrize(
    "target,expected",
    [
        ("node", ("node", None, None)),
        ("node@22", ("node", "22", None)),
        ("node@22:npm", ("node", "22", "npm")),
        ("node:npm", ("node", None, "npm")),
        ("python@3.11:pip", ("python", "3.11", "pip")),
    ],
)
def test_split_target(target, expected):
    assert _split_target(target) == expected


def test_run_without_target_errors():
    assert main(["run"]) == 1


def test_unknown_command_errors():
    assert main(["nope"]) == 2


def test_bare_runtime_goes_to_subcommands():
    # 'envxx node' must not try to execute node; it shows subcommand help.
    assert main(["node", "--help"]) == 0


def test_module_fallback_pip(tmp_path, monkeypatch):
    from envxx.platforms import Platform
    from envxx.providers.python_provider import PythonProvider
    from envxx.run import resolve_command

    monkeypatch.setenv(store.HOME_ENV, str(tmp_path / "home"))
    venv = store.version_dir("python", "3.11.18")
    venv.mkdir(parents=True)
    (venv / "python.exe").write_bytes(b"")

    provider = PythonProvider(Platform("windows", "x64"))
    exe, leading = resolve_command(provider, "3.11.18", "pip")
    assert exe.name == "python.exe"
    assert leading == ["-m", "pip"]


def test_copy_short_help_flag():
    # -h must work at every level, not just --help
    assert main(["-h"]) == 0
    assert main(["python", "-h"]) == 0
    assert main(["node", "-h"]) == 0
    assert main(["python", "search", "-h"]) == 0


def test_selector_does_not_match_subcommand_names():
    from envxx.cli import _match_selector

    for token in ("python", "node", "list", "search", "nodejs"):
        assert _match_selector(token) is None
