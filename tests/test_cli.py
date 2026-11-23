from __future__ import annotations

import errno
import os
from pathlib import Path

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
    venv = store.version_dir("python", "3.11.18", kind="runtime", scoped=False)
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
    monkeypatch.setattr("envxx.cli.store.installed_versions", lambda name, kind="app", scoped=False: ["2.1.325"])

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
    monkeypatch.setattr("envxx.cli.store.installed_versions", lambda name, kind="app", scoped=False: ["22.23.5"])

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
    monkeypatch.setattr("envxx.cli.store.installed_versions", lambda name, kind="app", scoped=False: ["3.11.18"])

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
    root = store.version_dir("python", version, kind="runtime", scoped=False)
    (root / script_dir).mkdir(parents=True)
    (root / script_dir / script_name).write_bytes(b"")

    calls = []
    monkeypatch.setattr(
        "envxx.cli.runner.run",
        lambda p, v, a, entrypoint=None: calls.append((v, a, entrypoint)) or 0,
    )
    monkeypatch.setattr("envxx.cli.store.installed_versions", lambda name, kind="app", scoped=False: [version])

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
    root = store.version_dir("python", version, kind="runtime", scoped=False)
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
    root = store.version_dir("python", version, kind="runtime", scoped=False)
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
    root = store.version_dir("python", version, kind="runtime", scoped=False)
    root.mkdir(parents=True)
    (root / "python.exe").write_bytes(b"")

    provider = PythonProvider(Platform("windows", "x64"))
    with pytest.raises(Exception) as caught:
        resolve_command(provider, version, "nosuch")
    assert "pip install nosuch" in str(caught.value)


# -- selector in front of a management command -------------------------------
@pytest.mark.parametrize(
    "argv,expected",
    [
        # the reported bug: install succeeded, then python was asked to run a
        # script called 'install'
        (["python3.12", "install"], ["python", "install", "3.12"]),
        (["python3.12", "install", "--force"], ["python", "install", "3.12", "--force"]),
        (["python3.12", "uninstall", "-y"], ["python", "uninstall", "3.12", "-y"]),
        (["python3.12", "where"], ["python", "where", "3.12"]),
        # list and search scope over everything, so the version means nothing
        (["python3.12", "list"], ["python", "list"]),
        (["python3.12", "search", "--all"], ["python", "search", "--all"]),
        (["node22", "update"], ["node", "update"]),
    ],
)
def test_a_selector_before_a_command_manages_instead_of_running(
    monkeypatch, argv, expected
):
    from envxx import cli

    seen = {}

    def fake_app(args, standalone_mode=True):
        seen["argv"] = list(args)

    monkeypatch.setattr(cli, "app", fake_app)
    assert cli.main(argv) == 0
    assert seen["argv"] == expected


def test_a_selector_before_a_script_still_runs_it(monkeypatch):
    from envxx import cli

    calls = []
    monkeypatch.setattr(
        cli.runner, "run",
        lambda p, v, a, entrypoint=None: calls.append((v, a, entrypoint)) or 0,
    )
    monkeypatch.setattr(
        "envxx.cli._ensure_installed", lambda provider, query: "3.12.16"
    )

    assert cli.main(["python3.12", "script.py", "--flag"]) == 0
    assert calls == [("3.12.16", ["script.py", "--flag"], None)]


# -- version -----------------------------------------------------------------
def test_version_flag_reports_the_package_version(capsys):
    from envxx import __version__ as package_version

    assert main(["--version"]) == 0
    printed = capsys.readouterr().out.strip()
    assert printed == f"envxx {package_version}"


def test_short_version_flag_is_equivalent(capsys):
    from envxx import __version__ as package_version

    assert main(["-V"]) == 0
    assert capsys.readouterr().out.strip() == f"envxx {package_version}"


def test_version_does_not_reach_a_tool(monkeypatch):
    # 'envxx --version' answers for envxx; only 'envxx <tool> -v' reaches a tool
    from envxx import cli

    calls = []
    monkeypatch.setattr(
        cli.runner, "run",
        lambda p, v, a, entrypoint=None: calls.append((v, a, entrypoint)) or 0,
    )
    assert cli.main(["--version"]) == 0
    assert calls == []


def test_the_version_is_declared_once():
    """pyproject must read the version from the package, not restate it."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    text = (root / "pyproject.toml").read_text(encoding="utf-8")

    assert 'dynamic = ["version"]' in text
    assert '[tool.hatch.version]' in text
    # a hardcoded [project] version would drift from envxx.__version__
    assert "\nversion = " not in text.split("[tool.hatch.version]")[0]


# -- release consistency -----------------------------------------------------
def _git_tags(root) -> list[str]:
    import subprocess

    result = subprocess.run(
        ["git", "tag", "--list", "v*"],
        cwd=root, capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip("not a git checkout")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def test_the_version_is_not_behind_the_newest_tag():
    """__version__ may lead the newest tag by a bump, never trail it.

    Between "bump the version" and "create the tag" the two differ on
    purpose, so an equality check would fail during that window. What must
    never happen is the reverse: a tag released for 1.6.0 while the code
    still says 1.5.0, which is what CI rejects and what this catches early.
    """
    from envxx import __version__

    root = Path(__file__).resolve().parent.parent
    tags = _git_tags(root)
    if not tags:
        pytest.skip("no release tags yet")

    from envxx.versions import version_key

    newest = max(tags, key=lambda t: version_key(t.lstrip("v")))
    assert version_key(__version__) >= version_key(newest.lstrip("v")), (
        f"newest tag is {newest} but __version__ is {__version__}; "
        f"the code is behind a published release"
    )


def test_release_script_is_committed_executable():
    """scripts/release.sh derives the tag from __version__, removing the copy.

    The mode recorded in git is what matters: Windows cannot set the bit on
    disk, so checking os.access here would skip the assertion exactly where
    the file is written, and only CI would notice the script is not runnable.
    """
    import subprocess

    root = Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "release.sh").is_file()

    result = subprocess.run(
        ["git", "ls-files", "-s", "scripts/release.sh"],
        cwd=root, capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        pytest.skip("not a git checkout")
    mode = result.stdout.split()[0]
    assert mode == "100755", (
        f"release.sh is committed as {mode}, not 100755; "
        f"run 'git update-index --chmod=+x scripts/release.sh'"
    )


def test_the_workflow_checks_the_tag_against_the_version():
    """A forgotten bump must fail CI before anything is published."""
    root = Path(__file__).resolve().parent.parent
    workflow = (root / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert "envxx.__version__" in workflow
    # the check has to run on tag pushes only; a manual run has no tag to compare
    assert "startsWith(github.ref, 'refs/tags/')" in workflow


def test_the_build_passes_pyinstaller_an_absolute_shim_path():
    """--specpath makes every relative path in --add-data resolve against the
    spec directory, not the working directory.

    The build step named the shim relatively while also writing the spec into
    build/, so PyInstaller looked for build/envxx/data/envxx-shim.exe. That
    file does not exist, and all six platform builds failed on it — after the
    tests had already gone green, which is why the tag shipped nothing.
    """
    root = Path(__file__).resolve().parent.parent
    workflow = (root / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    build_step = workflow.split("- name: build", 1)[1].split("- name:", 1)[0]

    add_data = [
        line.strip()
        for line in build_step.splitlines()
        if "--add-data" in line
    ]
    assert add_data, "the build no longer ships the shim binary"
    for line in add_data:
        assert "$GITHUB_WORKSPACE/" in line or line.startswith("/"), (
            "a relative --add-data path is resolved against --specpath, "
            f"not the checkout: {line}"
        )
    # the flag and the value have to stay on the same line for '>' folding
    assert "envxx/data/envxx-shim.exe:envxx/data" in add_data[0]


# -- help grouping -----------------------------------------------------------
def test_help_splits_commands_into_panels(capsys):
    """A flat list of twenty tools hides which ones install a runtime."""
    from envxx.cli import (
        PANEL_APP,
        PANEL_INSTALLER,
        PANEL_MANAGE,
        PANEL_RUNTIME,
    )

    main(["--help"])
    printed = capsys.readouterr().out

    for panel in (PANEL_MANAGE, PANEL_RUNTIME, PANEL_APP, PANEL_INSTALLER):
        assert panel in printed, f"missing panel: {panel}"


def test_each_tool_lands_in_the_panel_matching_its_kind():
    from envxx.cli import (
        PANEL_APP,
        PANEL_INSTALLER,
        PANEL_RUNTIME,
        _panel_for,
    )
    from envxx.providers import tool_specs

    panels = {spec.name: _panel_for(spec) for spec in tool_specs()}

    # runtimes and the two application shapes must not share a panel
    assert panels["python"] == PANEL_RUNTIME
    assert panels["node"] == PANEL_RUNTIME
    assert panels["claude"] == PANEL_APP
    assert panels["git"] == PANEL_INSTALLER
    assert panels["vscode"] == PANEL_INSTALLER


def test_manage_commands_are_not_listed_as_tools():
    """init, set_env and the rest belong to envxx, not to any provider."""
    from envxx.providers import tool_specs

    names = {spec.name for spec in tool_specs()}
    for command in ("init", "set-env", "set-path", "bin"):
        assert command not in names
