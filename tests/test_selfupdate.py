"""Updating envxx itself.

Both upgrade paths write outside the store -- one replaces the executable, the
other hands a command to pip -- so these tests substitute the boundaries and
assert the decisions: which upstream is consulted, what is refused, and what
happens when a step fails halfway.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
import pytest

from envxx import selfupdate, store
from envxx.errors import SelfUpdateError
from envxx.platforms import Platform


@pytest.fixture
def win():
    return Platform("windows", "x64")


@pytest.fixture
def linux():
    return Platform("linux", "x64")


def _release(version: str, platform: Platform, digest: str | None = "sha256:" + "a" * 64):
    asset = {"name": f"{version}-{platform.tag}.zip"}
    if digest is not None:
        asset["digest"] = digest
    asset["browser_download_url"] = (
        f"https://github.com/mikigo/EnvXX/releases/download/v{version}/"
        f"{version}-{platform.tag}.zip"
    )
    return {"tag_name": f"v{version}", "assets": [asset]}


# -- which install is this ---------------------------------------------------
def test_a_frozen_binary_is_recognised(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert selfupdate.install_mode() == "frozen"


def test_an_editable_install_is_recognised(monkeypatch):
    """Replacing a developer's checkout with a wheel would break their setup."""
    monkeypatch.delattr(sys, "frozen", raising=False)

    class _Dist:
        def read_text(self, name):
            return json.dumps({"dir_info": {"editable": True}})

    monkeypatch.setattr(
        selfupdate.importlib.metadata, "distribution", lambda name: _Dist()
    )
    assert selfupdate.install_mode() == "editable"


def test_a_pipx_environment_is_recognised(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)

    class _Dist:
        def read_text(self, name):
            return None

        def locate_file(self, name):
            return Path(selfupdate.__file__).parent

    monkeypatch.setattr(
        selfupdate.importlib.metadata, "distribution", lambda name: _Dist()
    )
    monkeypatch.setattr(sys, "prefix", "/home/u/.local/pipx/venvs/envxx")
    assert selfupdate.install_mode() == "pipx"


def test_a_uv_tool_environment_is_recognised(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)

    class _Dist:
        def read_text(self, name):
            return None

        def locate_file(self, name):
            return Path(selfupdate.__file__).parent

    monkeypatch.setattr(
        selfupdate.importlib.metadata, "distribution", lambda name: _Dist()
    )
    monkeypatch.setattr(sys, "prefix", "/home/u/.local/share/uv/tools/envxx")
    assert selfupdate.install_mode() == "uv-tool"


def test_an_uninstalled_checkout_is_source(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)

    def missing(name):
        raise selfupdate.importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(selfupdate.importlib.metadata, "distribution", missing)
    assert selfupdate.install_mode() == "source"


def test_a_checkout_shadowing_the_installed_package_is_source(monkeypatch, tmp_path):
    """PYTHONPATH pointing at a working tree runs code pip does not manage.

    Upgrading the distribution would report success while the code actually in
    use stayed exactly where it was.
    """
    monkeypatch.delattr(sys, "frozen", raising=False)
    installed = tmp_path / "site-packages" / "envxx"
    installed.mkdir(parents=True)

    class _Dist:
        def read_text(self, name):
            return None

        def locate_file(self, name):
            return installed

    monkeypatch.setattr(
        selfupdate.importlib.metadata, "distribution", lambda name: _Dist()
    )
    # this module really is being imported from a checkout, so the two differ
    assert selfupdate.install_mode() == "source"


def test_an_editable_install_is_not_mistaken_for_a_shadow(monkeypatch, tmp_path):
    """An editable install also lives outside site-packages; it must keep its
    own answer so the user is told the right thing."""
    monkeypatch.delattr(sys, "frozen", raising=False)

    class _Dist:
        def read_text(self, name):
            return json.dumps({"dir_info": {"editable": True}})

        def locate_file(self, name):
            return tmp_path / "whatever"

    monkeypatch.setattr(
        selfupdate.importlib.metadata, "distribution", lambda name: _Dist()
    )
    assert selfupdate.install_mode() == "editable"


# -- the frozen upstream -----------------------------------------------------
def test_the_latest_release_is_read_from_releases_latest(monkeypatch):
    """Not from the tag list: v1.9.3 was tagged but never built, and its
    download would 404."""
    seen = {}

    def fake_json(url, cache_key, ttl=86400, missing_ok=False):
        seen["url"] = url
        return {"tag_name": "v1.9.5", "assets": []}

    monkeypatch.setattr(selfupdate.http, "get_json", fake_json)

    assert selfupdate.latest_frozen() == "1.9.5"
    assert seen["url"].endswith("/releases/latest")


def test_the_pypi_index_is_the_package_upstream(monkeypatch):
    def fake_json(url, cache_key, ttl=86400, missing_ok=False):
        assert "pypi.org" in url
        return {"info": {"version": "1.9.5"}}

    monkeypatch.setattr(selfupdate.http, "get_json", fake_json)
    assert selfupdate.latest_for("pip") == "1.9.5"


def test_the_release_asset_and_digest_are_matched_by_platform(monkeypatch, linux, win):
    payload = _release("1.9.5", linux)

    monkeypatch.setattr(
        selfupdate.http, "get_json", lambda *a, **k: payload
    )

    url, sha = selfupdate.match_frozen_release("1.9.5", linux)
    assert url.endswith("1.9.5-linux-x64.zip")
    assert sha == "a" * 64

    with pytest.raises(SelfUpdateError, match="no 1.9.5-windows-x64.zip"):
        selfupdate.match_frozen_release("1.9.5", win)


def test_a_release_without_a_digest_is_still_installable(monkeypatch, linux):
    payload = _release("1.9.5", linux, digest=None)
    monkeypatch.setattr(selfupdate.http, "get_json", lambda *a, **k: payload)

    _, sha = selfupdate.match_frozen_release("1.9.5", linux)
    assert sha is None


# -- replacing the binary ----------------------------------------------------
def _write_exe(path: Path, text: str = "old") -> Path:
    path.write_text(text)
    return path


def test_a_posix_replacement_is_a_plain_replace(tmp_path, monkeypatch):
    monkeypatch.setattr(selfupdate, "_is_windows", lambda: False)
    target = _write_exe(tmp_path / "envxx")
    incoming = _write_exe(tmp_path / "envxx.new", "new")

    selfupdate._install_file(incoming, target)

    assert target.read_text() == "new"
    assert not incoming.exists()


def test_a_windows_replacement_renames_then_replaces(tmp_path, monkeypatch):
    """The running image cannot be overwritten but can be renamed."""
    monkeypatch.setattr(selfupdate, "_is_windows", lambda: True)
    target = _write_exe(tmp_path / "envxx.exe")
    incoming = _write_exe(tmp_path / "envxx.exe.new", "new")

    selfupdate._install_file(incoming, target)

    assert target.read_text() == "new"
    assert (tmp_path / "envxx.exe.old").read_text() == "old"
    assert not incoming.exists()


def test_a_failed_windows_replace_puts_the_old_binary_back(tmp_path, monkeypatch):
    """The one outcome that must never happen is no envxx at all."""
    monkeypatch.setattr(selfupdate, "_is_windows", lambda: True)
    monkeypatch.setattr(selfupdate.time, "sleep", lambda _s: None)
    target = _write_exe(tmp_path / "envxx.exe")
    incoming = _write_exe(tmp_path / "envxx.exe.new", "new")

    def refuse(src, dst):
        raise PermissionError("in use")

    monkeypatch.setattr(selfupdate.os, "replace", refuse)

    with pytest.raises(SelfUpdateError, match="Close every running envxx"):
        selfupdate._install_file(incoming, target)

    assert target.read_text() == "old"
    assert not (tmp_path / "envxx.exe.old").exists()


def test_sweep_removes_a_leftover_old_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    exe = _write_exe(tmp_path / "envxx.exe")
    stale = _write_exe(tmp_path / "envxx.exe.old", "previous")
    monkeypatch.setattr(sys, "executable", str(exe))

    selfupdate.sweep_stale()

    assert not stale.exists()
    assert exe.exists()


def test_sweep_ignores_a_file_it_cannot_delete(tmp_path, monkeypatch):
    """Untidy is never a reason for the command in front of it to fail."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    exe = _write_exe(tmp_path / "envxx.exe")
    _write_exe(tmp_path / "envxx.exe.old", "previous")
    monkeypatch.setattr(sys, "executable", str(exe))

    def locked(self):
        raise PermissionError("held open")

    monkeypatch.setattr(Path, "unlink", locked)
    selfupdate.sweep_stale()  # must not raise


# -- verifying what was downloaded -------------------------------------------
def test_a_binary_reporting_the_wrong_version_is_refused(tmp_path, monkeypatch):
    """Swapping a working envxx for a broken one is worse than not updating."""
    source = _write_exe(tmp_path / "envxx")
    monkeypatch.setattr(
        selfupdate.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"stdout": "envxx 1.9.0"})(),
    )

    with pytest.raises(SelfUpdateError, match="reports 'envxx 1.9.0'"):
        selfupdate._verify_binary(source, "1.9.5")


def test_a_verified_binary_is_accepted(tmp_path, monkeypatch):
    source = _write_exe(tmp_path / "envxx")
    monkeypatch.setattr(
        selfupdate.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"stdout": "envxx 1.9.5"})(),
    )
    selfupdate._verify_binary(source, "1.9.5")


def test_an_archive_holding_the_wrong_number_of_files_is_refused(tmp_path):
    staging = tmp_path / "stage"
    staging.mkdir()
    (staging / "envxx").write_text("a")
    (staging / "extra.txt").write_text("b")

    with pytest.raises(SelfUpdateError, match="expected one file"):
        selfupdate._staged_binary(staging)


# -- pip ---------------------------------------------------------------------
def test_pip_resolves_the_target_through_its_own_report(monkeypatch, tmp_path):
    """A private index or --pre preference must decide the version, not us."""
    written = {}

    def fake_run(cmd, **kwargs):
        report = kwargs.get("capture_output") and None
        args = cmd
        if "--report" in args:
            path = Path(args[args.index("--report") + 1])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"install": [{"metadata": {"version": "9.9.9"}}]}),
                encoding="utf-8",
            )
            written["report"] = path
        return type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(selfupdate, "_pip_run", fake_run)
    monkeypatch.setattr(selfupdate.store, "cache_dir", lambda: tmp_path)

    assert selfupdate.pip_target_version() == "9.9.9"
    assert not written["report"].exists(), "the report is a scratch file"


def test_an_old_pip_without_report_falls_through(monkeypatch, tmp_path):
    monkeypatch.setattr(selfupdate.store, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        selfupdate,
        "_pip_run",
        lambda args: type("R", (), {"returncode": 2, "stderr": "no such option"})(),
    )

    assert selfupdate.pip_target_version() is None


def test_pip_upgrades_with_upgrade_flag(monkeypatch):
    calls = []

    def fake_run(args):
        calls.append(args)
        return type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(selfupdate, "_pip_run", fake_run)
    monkeypatch.setattr(selfupdate, "pip_target_version", lambda: "9.9.9")
    monkeypatch.setattr(selfupdate, "_installed_version", lambda: "9.9.9")

    assert selfupdate.upgrade_with_pip() == "9.9.9"
    assert calls == [["install", "--upgrade", "envxx"]]


def test_pip_is_not_invoked_when_already_current(monkeypatch):
    calls = []
    monkeypatch.setattr(
        selfupdate, "_pip_run", lambda args: calls.append(args)
    )
    monkeypatch.setattr(selfupdate, "pip_target_version", lambda: "1.9.5")

    from envxx import __version__

    assert selfupdate.upgrade_with_pip() == __version__
    assert calls == []


def test_a_locked_console_script_is_moved_aside_and_retried(tmp_path, monkeypatch):
    """On Windows the running script cannot be rewritten; pip can after it
    has been renamed out of the way."""
    script = tmp_path / "envxx.exe"
    _write_exe(script, "launcher")
    monkeypatch.setattr(selfupdate, "_console_script", lambda: script)
    monkeypatch.setattr(selfupdate, "pip_target_version", lambda: "9.9.9")
    monkeypatch.setattr(selfupdate, "_installed_version", lambda: "9.9.9")

    attempts = {"n": 0}

    def fake_run(args):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return type(
                "R", (), {"returncode": 1, "stderr": "Permission denied", "stdout": ""}
            )()
        return type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(selfupdate, "_pip_run", fake_run)

    assert selfupdate.upgrade_with_pip() == "9.9.9"
    assert attempts["n"] == 2
    assert not (tmp_path / "envxx.exe.old").exists()


def test_a_retry_that_fails_restores_the_launcher(tmp_path, monkeypatch):
    script = tmp_path / "envxx.exe"
    _write_exe(script, "launcher")
    monkeypatch.setattr(selfupdate, "_console_script", lambda: script)
    monkeypatch.setattr(selfupdate, "pip_target_version", lambda: "9.9.9")
    monkeypatch.setattr(
        selfupdate,
        "_pip_run",
        lambda args: type(
            "R", (), {"returncode": 1, "stderr": "ERROR: denied", "stdout": ""}
        )(),
    )

    with pytest.raises(SelfUpdateError, match="pip could not upgrade envxx"):
        selfupdate.upgrade_with_pip()

    assert script.read_text() == "launcher"


def test_an_externally_managed_python_gets_advice_not_a_breaking_flag():
    hint = selfupdate._pip_failure_hint(
        "error: externally-managed-environment\n"
        "This environment is externally managed"
    )
    assert "pipx" in hint
    assert "break-system-packages" not in hint


# -- pipx and uv -------------------------------------------------------------
def test_pipx_is_only_run_when_asked(tmp_path, monkeypatch, capsys):
    from envxx.cli import main

    monkeypatch.setattr(selfupdate, "install_mode", lambda: "pipx")
    monkeypatch.setattr(
        selfupdate,
        "run_manager_upgrade",
        lambda mode: pytest.fail("pipx must not run without --yes"),
    )

    assert main(["self-update"]) == 0
    printed = capsys.readouterr().out
    assert "pipx upgrade envxx" in printed
    assert "--yes" in printed


def test_pipx_runs_with_yes(monkeypatch, capsys):
    from envxx.cli import main

    ran = []
    monkeypatch.setattr(selfupdate, "install_mode", lambda: "pipx")
    monkeypatch.setattr(selfupdate, "latest_for", lambda mode: "9.9.9")
    monkeypatch.setattr(selfupdate, "run_manager_upgrade", ran.append)

    assert main(["self-update", "--yes"]) == 0
    assert ran == ["pipx"]


def test_uv_tool_uses_uv(monkeypatch):
    assert selfupdate.manager_command("uv-tool") == ["uv", "tool", "upgrade", "envxx"]
    assert selfupdate.manager_command("pip") is None


def test_a_missing_manager_is_reported(monkeypatch):
    def missing(*a, **k):
        raise FileNotFoundError()

    monkeypatch.setattr(selfupdate.subprocess, "run", missing)
    with pytest.raises(SelfUpdateError, match="is not on PATH"):
        selfupdate.run_manager_upgrade("pipx")


# -- refusing what cannot work ----------------------------------------------
def test_an_editable_install_is_refused_with_the_right_command(monkeypatch, capsys):
    from envxx.cli import main

    monkeypatch.setattr(selfupdate, "install_mode", lambda: "editable")

    assert main(["self-update"]) == 1
    # rich wraps the message at the terminal width, splitting 'git pull'
    printed = "".join(capsys.readouterr().err.split())
    assert "gitpull" in printed


def test_check_reports_without_writing(monkeypatch, capsys):
    from envxx.cli import main

    monkeypatch.setattr(selfupdate, "install_mode", lambda: "frozen")
    monkeypatch.setattr(selfupdate, "latest_for", lambda mode: "9.9.9")
    monkeypatch.setattr(
        selfupdate, "upgrade_frozen", lambda v: pytest.fail("--check must not update")
    )

    assert main(["self-update", "--check"]) == 0
    assert "9.9.9 is available" in capsys.readouterr().out


def test_dry_run_names_the_action_without_taking_it(monkeypatch, capsys):
    from envxx.cli import main

    monkeypatch.setattr(selfupdate, "install_mode", lambda: "frozen")
    monkeypatch.setattr(selfupdate, "latest_for", lambda mode: "9.9.9")
    monkeypatch.setattr(
        selfupdate, "upgrade_frozen", lambda v: pytest.fail("--dry-run must not update")
    )
    monkeypatch.setattr("envxx.cli.detect_platform", lambda: Platform("linux", "x64"))

    assert main(["self-update", "--dry-run"]) == 0
    assert "would download 9.9.9-linux-x64.zip" in capsys.readouterr().out


# -- the startup hint --------------------------------------------------------
def test_no_hint_without_a_terminal(monkeypatch, capsys):
    """The hint must be decided before any network work, so a pipe is cheap."""
    from envxx.cli import _print_update_notice

    monkeypatch.setattr(
        selfupdate, "_quick_latest", lambda mode: pytest.fail("a pipe must not be waited on")
    )
    _print_update_notice(["node22", "-v"])


def test_the_hint_is_suppressed_by_the_environment(monkeypatch):
    monkeypatch.setenv(selfupdate.NO_CHECK_ENV, "1")

    class _Tty:
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stderr", _Tty())
    monkeypatch.setattr(
        selfupdate, "_quick_latest", lambda mode: pytest.fail("check was disabled")
    )
    assert selfupdate.notice() is None


def test_ci_does_not_get_the_hint(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    class _Tty:
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stderr", _Tty())
    monkeypatch.setattr(
        selfupdate, "_quick_latest", lambda mode: pytest.fail("CI needs no hint")
    )
    assert selfupdate.notice() is None


def test_a_cached_answer_costs_no_request(tmp_path, monkeypatch):
    cache = tmp_path / "envxx-latest.json"
    cache.write_text(json.dumps({"version": "9.9.9"}), encoding="utf-8")
    monkeypatch.setattr(selfupdate, "_notice_cache", lambda: cache)
    monkeypatch.setattr(
        selfupdate.http, "client", lambda **k: pytest.fail("cached, so no request")
    )

    assert selfupdate._quick_latest("frozen") == "9.9.9"


def test_a_refused_request_produces_no_hint(monkeypatch):
    """An offline machine must not see an error from the hint."""
    monkeypatch.setattr(selfupdate, "NOTICE_TTL", 0)
    monkeypatch.setattr(selfupdate, "_notice_cache", lambda: Path("/nonexistent/x.json"))

    def boom(*a, **k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(selfupdate.http, "client", boom)
    assert selfupdate._quick_latest("frozen") is None


def test_machine_readable_commands_get_no_hint(monkeypatch):
    from envxx.cli import _print_update_notice

    monkeypatch.setattr(
        selfupdate, "notice", lambda: pytest.fail("'where' output is copied verbatim")
    )
    _print_update_notice(["where"])
    _print_update_notice(["bin"])


def test_the_hint_names_the_command_that_fixes_it(monkeypatch):
    from envxx import __version__
    from envxx.cli import main

    monkeypatch.setattr(selfupdate, "install_mode", lambda: "frozen")
    monkeypatch.setattr(selfupdate, "notice", lambda: "envxx 9.9.9 is available")
    monkeypatch.setattr(
        "envxx.providers.tool_specs", lambda: []
    )
    main(["--help"])
    # --help is one of the commands the hint skips
