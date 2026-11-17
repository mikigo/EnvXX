from __future__ import annotations

import errno
import os

import pytest

from envxx import store
from envxx.cli import _match_selector, _split_target, main
from envxx.errors import UsageError


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv(store.HOME_ENV, str(tmp_path / "home"))
    return tmp_path / "home"


def test_pipe_is_gone_recognises_epipe_and_windows_einval():
    from envxx.cli import _pipe_is_gone

    assert _pipe_is_gone(OSError(errno.EPIPE, "broken pipe"))
    # Windows reports a closed pipe as EINVAL, not EPIPE
    assert _pipe_is_gone(OSError(errno.EINVAL, "invalid argument")) == (os.name == "nt")
    assert not _pipe_is_gone(OSError(errno.ENOENT, "missing"))


def test_closed_pipe_exits_quietly(monkeypatch):
    # 'envxx --help | head' makes the writer hit a closed pipe mid-render;
    # that must not surface as a traceback
    from envxx import cli

    # Windows says EINVAL here, Unix says EPIPE; the test has to speak the
    # platform's dialect or it checks the wrong branch on one of them
    closed_pipe = errno.EINVAL if os.name == "nt" else errno.EPIPE

    def boom(*_args, **_kwargs):
        raise OSError(closed_pipe, "closed pipe")

    monkeypatch.setattr(cli, "_silence_streams", lambda: None)
    monkeypatch.setattr(cli, "app", boom)
    # the reader chose to stop early, so this is not a failure of the command
    assert cli.main(["--help"]) == 0


def test_other_oserrors_are_not_swallowed(monkeypatch):
    # a missing file must still blow up; only the closed-pipe shape is special
    from envxx import cli

    def boom(*_args, **_kwargs):
        raise OSError(errno.ENOENT, "missing")

    monkeypatch.setattr(cli, "app", boom)
    with pytest.raises(OSError):
        cli.main(["--help"])


def test_top_level_help_describes_each_tool(monkeypatch, capsys):
    # the command list used to read 'node runtimes' / 'claude builds', which
    # says nothing about where the thing comes from
    assert main([]) == 2
    printed = capsys.readouterr().out
    for spec_summary in (
        "python-build-standalone",
        "nodejs.org",
        "Open VSX",
        "MobaXterm",
    ):
        assert spec_summary in printed
    assert "node runtimes" not in printed
    assert "claude builds" not in printed


def test_no_args_shows_help_without_an_empty_error(capsys):
    # Typer's rich help goes to stdout, so click's NoArgsIsHelpError carries an
    # empty message; echoing it would print a stray 'error:' line
    assert main([]) == 2
    printed = capsys.readouterr()
    assert "Usage:" in printed.out
    assert "error" not in printed.err


def test_bare_subgroup_shows_help_without_an_empty_error(capsys):
    assert main(["node"]) == 2
    printed = capsys.readouterr()
    assert "Usage:" in printed.err or "Usage:" in printed.out
    assert "error:" not in printed.err


def test_unknown_subcommand_still_reports_the_error(capsys):
    assert main(["node", "nonsense"]) == 2
    assert "No such command" in capsys.readouterr().err


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


def _stub_claude(monkeypatch, count=25):
    from envxx.platforms import Platform
    from envxx.providers.claude_provider import ClaudeProvider
    from envxx.providers.spec import VersionInfo

    versions = [VersionInfo(version=f"2.1.{n}") for n in range(count)]

    class Stub(ClaudeProvider):
        def _fetch_versions(self):
            return list(reversed(versions))

    monkeypatch.setattr("envxx.cli._provider", lambda spec: Stub(Platform("windows", "x64")))
    return versions


def test_claude_search_hides_versions_beyond_the_limit(monkeypatch, capsys):
    _stub_claude(monkeypatch, count=25)
    assert main(["claude", "search"]) == 0
    printed = capsys.readouterr()
    assert "2.1.24" in printed.out          # newest first
    assert "2.1.15" in printed.out
    assert "2.1.14" not in printed.out
    assert "15 more, use --all" in printed.err


def test_claude_search_all_shows_everything(monkeypatch, capsys):
    _stub_claude(monkeypatch, count=25)
    assert main(["claude", "search", "--all"]) == 0
    printed = capsys.readouterr()
    assert "2.1.0" in printed.out
    assert "more, use --all" not in printed.err


def test_runtime_search_is_newest_first(monkeypatch, capsys):
    from envxx.platforms import Platform
    from envxx.providers.node_provider import NodeProvider
    from envxx.providers.spec import VersionInfo

    class Stub(NodeProvider):
        def _fetch_versions(self):
            return [VersionInfo(version=v) for v in ("20.19.0", "22.14.0", "24.22.3")]

    monkeypatch.setattr("envxx.cli._provider", lambda spec: Stub(Platform("windows", "x64")))
    assert main(["node", "search"]) == 0
    out = capsys.readouterr().out
    assert out.index("24.22.3") < out.index("22.14.0") < out.index("20.19.0")


def test_search_hides_the_released_column_when_dates_are_missing(monkeypatch, capsys):
    from envxx.platforms import Platform
    from envxx.providers.claude_provider import ClaudeProvider
    from envxx.providers.spec import VersionInfo

    class Stub(ClaudeProvider):
        def _fetch_versions(self):
            return [VersionInfo(version="2.1.325"), VersionInfo(version="2.1.323")]

    monkeypatch.setattr("envxx.cli._provider", lambda spec: Stub(Platform("windows", "x64")))
    assert main(["claude", "search"]) == 0
    assert "released" not in capsys.readouterr().out


def test_search_shows_the_released_column_when_dates_exist(monkeypatch, capsys):
    from envxx.platforms import Platform
    from envxx.providers.node_provider import NodeProvider
    from envxx.providers.spec import VersionInfo

    class Stub(NodeProvider):
        def _fetch_versions(self):
            return [
                VersionInfo(version="22.14.0", released="2025-02-11"),
                VersionInfo(version="20.19.0", released="2025-03-24"),
            ]

    monkeypatch.setattr("envxx.cli._provider", lambda spec: Stub(Platform("windows", "x64")))
    assert main(["node", "search"]) == 0
    printed = capsys.readouterr().out
    assert "released" in printed
    assert "2025-02-11" in printed


def test_search_omits_blank_dates_when_other_rows_have_them(monkeypatch, capsys):
    from envxx.platforms import Platform
    from envxx.providers.node_provider import NodeProvider
    from envxx.providers.spec import VersionInfo

    class Stub(NodeProvider):
        def _fetch_versions(self):
            return [
                VersionInfo(version="22.14.0", released="2025-02-11"),
                VersionInfo(version="20.19.0", released=None),
            ]

    monkeypatch.setattr("envxx.cli._provider", lambda spec: Stub(Platform("windows", "x64")))
    assert main(["node", "search"]) == 0
    printed = capsys.readouterr().out
    assert "released" in printed
    assert "20.19.0" in printed


def test_app_tools_expose_rm_and_update():
    from envxx.cli import app

    group = next(g for g in app.registered_groups if g.name == "claude")
    names = {command.name for command in group.typer_instance.registered_commands}
    assert {"install", "uninstall", "rm", "update", "search", "list", "where"} <= names


def test_runtime_tools_have_no_app_only_commands():
    from envxx.cli import app

    group = next(g for g in app.registered_groups if g.name == "node")
    names = {command.name for command in group.typer_instance.registered_commands}
    assert "update" not in names
    assert "rm" not in names


def test_cc_switch_is_registered_as_an_app():
    from envxx.cli import app

    group = next(g for g in app.registered_groups if g.name == "cc-switch")
    names = {command.name for command in group.typer_instance.registered_commands}
    assert {"install", "uninstall", "rm", "update", "search", "list", "where"} <= names


def test_cc_switch_selector_runs_a_pinned_version():
    # apps declare selector prefixes too, so 'cc-switch4.0' runs 4.0.x
    from envxx.cli import _match_selector

    matched = _match_selector("cc-switch4.0")
    assert matched is not None
    spec, query = matched
    assert spec.name == "cc-switch"
    assert query == "4.0"
    assert _match_selector("cc-switch") is None


def test_claude_flag_run_dispatches_to_the_binary(monkeypatch):
    from envxx.cli import _dispatch_run

    calls = []
    monkeypatch.setattr("envxx.cli._provider", lambda spec: type(
        "P", (), {"spec": spec, "resolve": lambda self, q: "2.1.325"}
    )())
    monkeypatch.setattr("envxx.cli.runner.run", lambda p, v, a, entrypoint=None: calls.append((v, a, entrypoint)) or 0)
    monkeypatch.setattr("envxx.cli.store.installed_versions", lambda name: ["2.1.325"])

    assert _dispatch_run("claude", ["--version"]) == 0
    assert calls == [("2.1.325", ["--version"], None)]


@pytest.mark.parametrize(
    "token,rest,expected_entry,expected_args",
    [
        # 'npm' is a sibling launcher, not an argument to node
        ("node22", ["npm", "run", "dev"], "npm", ["run", "dev"]),
        ("node22", ["npx", "create-vite"], "npx", ["create-vite"]),
        # a script path is an argument, and so is a flag
        ("node22", ["script.js"], None, ["script.js"]),
        ("node22", ["-v"], None, ["-v"]),
        # 'node' itself is the default, so it stays out of the way
        ("node22", ["node", "x.js"], None, ["node", "x.js"]),
    ],
)
def test_dispatch_run_reads_a_launcher_before_the_default(
    monkeypatch, token, rest, expected_entry, expected_args
):
    from envxx.cli import _dispatch_run

    calls = []
    monkeypatch.setattr("envxx.cli._provider", lambda spec: type(
        "P", (), {"spec": spec, "resolve": lambda self, q: "22.23.5"}
    )())
    monkeypatch.setattr(
        "envxx.cli.runner.run",
        lambda p, v, a, entrypoint=None: calls.append((v, a, entrypoint)) or 0,
    )
    monkeypatch.setattr("envxx.cli.store.installed_versions", lambda name: ["22.23.5"])

    assert _dispatch_run(token, rest) == 0
    assert calls == [("22.23.5", expected_args, expected_entry)]


def test_python_entrypoint_shorthand(monkeypatch):
    # 'envxx python3.11 pip install x' should hit pip, not 'python pip install x'
    from envxx.cli import _dispatch_run

    calls = []
    monkeypatch.setattr("envxx.cli._provider", lambda spec: type(
        "P", (), {"spec": spec, "resolve": lambda self, q: "3.11.18"}
    )())
    monkeypatch.setattr(
        "envxx.cli.runner.run",
        lambda p, v, a, entrypoint=None: calls.append((v, a, entrypoint)) or 0,
    )
    monkeypatch.setattr("envxx.cli.store.installed_versions", lambda name: ["3.11.18"])

    assert _dispatch_run("python3.11", ["pip", "install", "requests"]) == 0
    assert calls == [("3.11.18", ["install", "requests"], "pip")]


def _force_platform(monkeypatch, os_name: str) -> None:
    """Pin the host platform so a test can lay out either runtime.

    The lookup itself branches on the platform (Scripts/name.exe against
    bin/name), so a test that only ever writes one layout passes on Windows
    and fails on Linux.
    """
    from envxx.platforms import Platform

    monkeypatch.setattr(
        "envxx.cli.detect_platform", lambda: Platform(os_name, "x64")
    )


@pytest.mark.parametrize(
    "os_name,script_dir,script_name",
    [
        ("windows", "Scripts", "envxx.exe"),
        ("linux", "bin", "envxx"),
    ],
)
def test_console_script_installed_by_pip_is_found(
    tmp_path, monkeypatch, os_name, script_dir, script_name
):
    # 'envxx python3.11 pip install -e .' then 'envxx python3.11 envxx' used to
    # hand 'envxx' to python as a script path, which died with Errno 2
    from envxx.cli import _dispatch_run

    _force_platform(monkeypatch, os_name)

    version = "3.11.18"
    root = store.version_dir("python", version)
    (root / script_dir).mkdir(parents=True)
    (root / script_dir / script_name).write_bytes(b"")

    calls = []
    monkeypatch.setattr(
        "envxx.cli.runner.run",
        lambda p, v, a, entrypoint=None: calls.append((v, a, entrypoint)) or 0,
    )
    monkeypatch.setattr("envxx.cli.store.installed_versions", lambda name: [version])

    assert _dispatch_run("python3.11", ["envxx", "--version"]) == 0
    assert calls == [(version, ["--version"], "envxx")]


@pytest.mark.parametrize(
    "os_name,script_dir,script_name",
    [
        ("windows", "Scripts", "black.exe"),
        ("linux", "bin", "black"),
    ],
)
def test_a_name_that_is_not_a_console_script_stays_an_argument(
    tmp_path, monkeypatch, os_name, script_dir, script_name
):
    # an ordinary script path must still reach python untouched
    from envxx.cli import _match_selector, _provider, _split_entrypoint

    _force_platform(monkeypatch, os_name)

    version = "3.11.18"
    root = store.version_dir("python", version)
    (root / script_dir).mkdir(parents=True)
    (root / script_dir / script_name).write_bytes(b"")

    spec, _ = _match_selector("python3.11")
    provider = _provider(spec)
    entry, args = _split_entrypoint(provider, version, ["script.py", "-v"])
    assert entry is None
    assert args == ["script.py", "-v"]

    entry, args = _split_entrypoint(provider, version, ["black", "--check", "."])
    assert entry == "black"
    assert args == ["--check", "."]


def test_script_lookup_refuses_names_that_climb_out(tmp_path):
    version = "3.11.18"
    root = store.version_dir("python", version)
    (root / "Scripts").mkdir(parents=True)
    # a file placed outside the runtime must not be reachable by name
    (root.parent / "outside.exe").write_bytes(b"")

    from envxx.cli import _match_selector, _provider, _split_entrypoint

    spec, _ = _match_selector("python3.11")
    provider = _provider(spec)

    for name in ("../outside", "..\\outside", "Scripts/envxx", "/etc/passwd"):
        assert provider.script_path(version, name) is None
        entry, args = _split_entrypoint(provider, version, [name])
        assert entry is None
        assert args == [name]


def test_missing_console_script_names_the_fix(tmp_path, monkeypatch):
    from envxx.platforms import Platform
    from envxx.providers.python_provider import PythonProvider
    from envxx.run import resolve_command

    version = "3.11.18"
    root = store.version_dir("python", version)
    root.mkdir(parents=True)
    (root / "python.exe").write_bytes(b"")

    provider = PythonProvider(Platform("windows", "x64"))
    with pytest.raises(Exception) as caught:
        resolve_command(provider, version, "nosuch")
    assert "pip install nosuch" in str(caught.value)
