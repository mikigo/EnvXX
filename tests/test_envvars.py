"""Shims and persistent environment variables.

Both modules touch state outside the store (PATH, the registry, shell rc
files), so these tests substitute the platform layer rather than the store:
what matters is the decision the code makes, not that Windows really wrote a
registry key.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from envxx import envvars, shims, store
from envxx.errors import UsageError


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv(store.HOME_ENV, str(tmp_path / "home"))
    store.ensure_dirs()
    return tmp_path / "home"


# -- relative paths ----------------------------------------------------------
def test_a_relative_directory_is_expanded_when_written(tmp_path, monkeypatch):
    """PATH entries are read from arbitrary directories, so 'tools' alone
    would resolve against whatever cwd the reader happened to have."""
    monkeypatch.chdir(tmp_path)
    assert envvars._expand("tools") == str((tmp_path / "tools").resolve())


def test_an_absolute_directory_is_left_alone(tmp_path):
    absolute = tmp_path / "already"
    assert envvars._expand(str(absolute)) == str(absolute)


def test_a_home_relative_directory_is_expanded(tmp_path, monkeypatch):
    # expanduser() reads USERPROFILE on Windows and HOME elsewhere; patching
    # the function keeps the test independent of which one this machine uses
    monkeypatch.setattr(
        Path, "expanduser", lambda self: tmp_path / self.name if str(self).startswith("~") else self
    )
    assert envvars._expand("~/bin") == str(tmp_path / "bin")


# -- refusing to replace PATH ------------------------------------------------
def test_set_env_refuses_to_replace_path():
    """A wholesale PATH replacement silently drops every existing entry."""
    with pytest.raises(UsageError, match="set-path"):
        envvars.set_env("PATH", "C:/only/this")


def test_set_env_refuses_path_in_any_case():
    with pytest.raises(UsageError):
        envvars.set_env("Path", "C:/only/this")


# -- backups -----------------------------------------------------------------
def test_every_write_records_the_previous_value(home, monkeypatch):
    monkeypatch.setattr(envvars, "_win_write", lambda n, v, s: None)
    monkeypatch.setattr(envvars, "_win_broadcast", lambda: None)
    monkeypatch.setattr(envvars, "_win_read", lambda n, s=False: "before")
    monkeypatch.setattr(envvars, "is_windows", lambda: True)

    envvars.set_env("FOO", "after")

    saved = envvars.backups()
    assert len(saved) == 1
    import json

    data = json.loads(saved[0].read_text(encoding="utf-8"))
    assert data["name"] == "FOO"
    assert data["previous"] == "before"


# -- shims -------------------------------------------------------------------
class _StubProvider:
    class spec:
        name = "python"
        kind = "runtime"


def _fake_target(monkeypatch, exe: Path):
    monkeypatch.setattr(
        shims, "_target_command", lambda provider, version: (exe, [])
    )


@pytest.fixture
def on_windows(monkeypatch):
    """Pin the shim format regardless of the host running the tests.

    shims.create branches on the host platform. A test that assumes the
    Windows form without saying so passes locally and fails on the Ubuntu
    runner, which is exactly how this suite broke once.
    """
    monkeypatch.setattr(shims, "_is_windows", lambda: True)


@pytest.fixture
def on_posix(monkeypatch):
    monkeypatch.setattr(shims, "_is_windows", lambda: False)


def test_shim_dir_is_always_the_global_store(home):
    """PATH belongs to the machine, so a project store never gets a bin/."""
    assert shims.shim_dir() == store.global_home() / "bin"


def test_a_posix_shim_execs_relative_to_itself(home, on_posix, monkeypatch):
    """The shell form must be covered on every host, not only on Linux."""
    exe = store.version_dir("python", "3.12.16", kind="runtime", scoped=False)
    exe = exe / "bin" / "python3"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    _fake_target(monkeypatch, exe)
    monkeypatch.setattr(envvars, "is_windows", lambda: False)

    written = shims.create(_StubProvider(), "3.12.16", label="3.12")

    path = written[0]
    assert path.name == "python3.12"
    body = path.read_text(encoding="utf-8")
    assert shims.SH_MARKER in body
    # relative, so moving the whole store keeps the shim working
    assert "$(dirname \"$0\")/" in body
    assert str(exe) not in body
    # the executable bit only exists on a POSIX filesystem; the shell form is
    # still worth checking on Windows, where chmod cannot express it
    if os.name != "nt":
        assert path.stat().st_mode & 0o111


def test_a_windows_shim_is_an_exe_carrying_a_relative_target(home, monkeypatch, on_windows):
    """A .bat would lose quoting; the exe launcher keeps argv intact."""
    exe = store.version_dir("python", "3.12.16", kind="runtime", scoped=False)
    exe = exe / "python.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    _fake_target(monkeypatch, exe)

    written = shims.create(_StubProvider(), "3.12.16", label="3.12")

    assert [p.name for p in written] == ["python3.12.exe"]
    data = written[0].read_bytes()
    # the launcher is our binary with the path appended after the PE image
    assert data.startswith(b"MZ")
    marker = b"@@ENVXX-TARGET@@"
    # the marker also appears as a compiled-in string literal inside the PE
    # image, so the trailer is the last occurrence, not the first
    offset = data.rindex(marker) + len(marker)
    stored = data[offset:].split(b"\n", 1)[0].decode()
    assert "12.16" in stored
    assert ":" not in stored, "the stored target must be relative, not absolute"
    assert not stored.startswith("/"), "a rooted path would not survive a move"


def test_the_shim_is_named_after_the_requested_line(home, monkeypatch, on_windows):
    """python3.10, not the resolved python3.10.22: a patch release must not
    orphan the command."""
    exe = store.version_dir("python", "3.10.22", kind="runtime", scoped=False)
    exe = exe / "python.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    _fake_target(monkeypatch, exe)

    written = shims.create(_StubProvider(), "3.10.22", label="3.10")

    assert all("3.10.22" not in p.name for p in written)
    assert "python3.10" in written[0].name


def test_remove_deletes_only_envxx_shims(home, monkeypatch, on_windows):
    exe = store.version_dir("python", "3.12.16", kind="runtime", scoped=False)
    exe = exe / "python.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    _fake_target(monkeypatch, exe)
    shims.create(_StubProvider(), "3.12.16", label="3.12")

    folder = shims.shim_dir()
    # a user's own file with the same name must survive
    (folder / "python3.12.bat").write_text("@echo off\nmine\n", encoding="utf-8")

    removed = shims.remove("python", "3.12")

    assert (folder / "python3.12.bat").exists()
    assert (folder / "python3.12.bat").read_text(encoding="utf-8").endswith("mine\n")
    # the .cmd was ours, so it went
    assert not (folder / "python3.12.cmd").exists()
    assert removed


def test_existing_lists_only_generated_files(home, monkeypatch, on_windows):
    exe = store.version_dir("python", "3.12.16", kind="runtime", scoped=False)
    exe = exe / "python.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    _fake_target(monkeypatch, exe)
    shims.create(_StubProvider(), "3.12.16", label="3.12")

    folder = shims.shim_dir()
    (folder / "not-ours.txt").write_text("hello", encoding="utf-8")

    found = [p.name for p in shims.existing()]
    assert "not-ours.txt" not in found
    assert all(name.startswith("python3.12") for name in found)


def test_require_installed_rejects_a_missing_version(home, monkeypatch):
    monkeypatch.setattr(
        "envxx.store.installed_versions", lambda *a, **k: ["3.12.16"]
    )
    with pytest.raises(UsageError):
        shims.require_installed(_StubProvider(), "3.11")


def test_require_installed_defaults_to_the_newest(home, monkeypatch):
    monkeypatch.setattr(
        "envxx.store.installed_versions", lambda *a, **k: ["3.11.18", "3.12.16"]
    )
    assert shims.require_installed(_StubProvider(), None) == "3.12.16"


# -- shims always point at the global store ----------------------------------
def test_a_runtime_shim_ignores_the_project_store(tmp_path, monkeypatch):
    """PATH is machine-wide, so a shim must not point into a checkout.

    Pointing it at a project's runtime makes the command die the moment that
    directory is removed, and stores a long ../ path in the launcher.
    """
    from envxx.platforms import Platform
    from envxx.providers.python_provider import PythonProvider

    root = tmp_path / "proj"
    project_runtime = root / ".envxx" / "runtime" / "python" / "3.10.22"
    project_runtime.mkdir(parents=True)
    (root / ".envxx" / store.MARKER).write_text(
        '{"schema": 1, "layout": 2}', encoding="utf-8"
    )
    global_runtime = tmp_path / "home" / "runtime" / "python" / "3.10.22"
    global_runtime.mkdir(parents=True)
    (project_runtime / "python.exe").write_text("")
    (global_runtime / "python.exe").write_text("")

    monkeypatch.setenv(store.HOME_ENV, str(tmp_path / "home"))
    monkeypatch.chdir(root)

    exe, _ = shims._target_command(PythonProvider(Platform("windows", "x64")), "3.10.22")

    assert exe.is_relative_to(tmp_path / "home")
    assert not exe.is_relative_to(root)


def test_require_installed_only_considers_the_global_store(home, monkeypatch):
    seen = []

    def fake_installed(tool, kind="app", scoped=False):
        seen.append(scoped)
        return ["3.10.22"]

    monkeypatch.setattr(store, "installed_versions", fake_installed)
    shims.require_installed(_StubProvider(), None)

    assert seen == [False], "a shim must resolve against the global store"


# -- project scope and shims -------------------------------------------------
def test_set_path_refuses_a_project_scoped_runtime(tmp_path, monkeypatch, capsys):
    """A shim is a PATH entry; PATH outlives the checkout it was made in."""
    from envxx.cli import main

    root = tmp_path / "proj"
    (root / ".envxx" / "runtime" / "python" / "3.10.22").mkdir(parents=True)
    (root / ".envxx" / store.MARKER).write_text(
        '{"schema": 1, "layout": 2}', encoding="utf-8"
    )
    monkeypatch.setenv(store.HOME_ENV, str(tmp_path / "home"))
    monkeypatch.chdir(root)

    assert main(["python3.10", "set-path"]) == 1
    printed = capsys.readouterr()
    assert "project-scoped" in printed.err
    assert not (tmp_path / "home" / "bin").exists()


def test_set_path_is_hidden_for_installers(capsys):
    """An installer has no binary, so the command cannot do anything."""
    from envxx.cli import main

    main(["git", "--help"])
    assert "set-path" not in capsys.readouterr().out

    main(["python", "--help"])
    assert "set-path" in capsys.readouterr().out


def test_bin_prints_the_whole_path(tmp_path, monkeypatch, capsys):
    """A truncated path is useless: the reader is meant to copy it."""
    from envxx.cli import main

    home = tmp_path / "home"
    exe = home / "runtime" / "python" / "3.10.22" / "python.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.setenv(store.HOME_ENV, str(home))

    folder = shims.shim_dir()
    folder.mkdir(parents=True)
    (folder / "python3.10.exe").write_bytes(
        b"MZ" + b"\n@@ENVXX-TARGET@@../runtime/python/3.10.22/python.exe\n"
    )

    assert main(["bin"]) == 0
    printed = capsys.readouterr().out
    assert str(exe) in printed


def test_the_reminder_names_a_way_to_refresh_without_reopening(capsys):
    """A user who opened a new terminal and still sees nothing needs a
    command, not a suggestion to open another one."""
    from envxx.cli import _remind_new_shell

    _remind_new_shell()
    printed = capsys.readouterr().err
    if os.name == "nt":
        assert "GetEnvironmentVariable" in printed
    else:
        assert "source" in printed


# -- PATH ordering -----------------------------------------------------------
def test_set_path_prepends_by_default(tmp_path, monkeypatch):
    """A directory the user just asked for should win over the rest of PATH."""
    monkeypatch.setattr(envvars, "is_windows", lambda: True)
    written = {}
    monkeypatch.setattr(
        envvars, "_win_write", lambda n, v, s: written.setdefault("value", v)
    )
    monkeypatch.setattr(envvars, "_win_broadcast", lambda: None)
    monkeypatch.setattr(envvars, "_win_read", lambda n, s=False: r"C:\existing")

    envvars.set_path(str(tmp_path / "new"))

    assert written["value"].split(os.pathsep)[0].endswith("new")


def test_set_path_append_puts_it_last(tmp_path, monkeypatch):
    monkeypatch.setattr(envvars, "is_windows", lambda: True)
    written = {}
    monkeypatch.setattr(
        envvars, "_win_write", lambda n, v, s: written.setdefault("value", v)
    )
    monkeypatch.setattr(envvars, "_win_broadcast", lambda: None)
    monkeypatch.setattr(envvars, "_win_read", lambda n, s=False: r"C:\existing")

    envvars.set_path(str(tmp_path / "new"), append=True)

    assert written["value"].split(os.pathsep)[-1].endswith("new")


def test_re_adding_does_not_reorder(tmp_path, monkeypatch):
    """Running it twice must not move an entry that is already there."""
    target = tmp_path / "mine"
    monkeypatch.setattr(envvars, "is_windows", lambda: True)
    monkeypatch.setattr(envvars, "_win_broadcast", lambda: None)
    monkeypatch.setattr(
        envvars, "_win_read", lambda n, s=False: os.pathsep.join([r"C:\a", str(target)])
    )
    written = {}
    monkeypatch.setattr(
        envvars, "_win_write", lambda n, v, s: written.setdefault("value", v)
    )

    expanded, changed = envvars.set_path(str(target))

    assert changed is False
    assert "value" not in written, "an unchanged PATH must not be rewritten"
