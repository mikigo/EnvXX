from __future__ import annotations

import os
import time

import pytest

from envxx import store
from envxx.errors import LockTimeout
from envxx.store import install_lock


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv(store.HOME_ENV, str(tmp_path / "home"))
    return tmp_path / "home"


def test_installed_versions_ignores_hidden():
    store.ensure_dirs()
    store.version_dir("python", "3.11.9").mkdir(parents=True)
    (store.tool_dir("python") / ".tmp-deadbeef").mkdir()

    assert store.installed_versions("python") == ["3.11.9"]


def test_remove_version():
    store.ensure_dirs()
    store.version_dir("node", "22.14.0").mkdir(parents=True)
    store.remove_version("node", "22.14.0")
    assert not store.version_dir("node", "22.14.0").exists()
    assert store.installed_versions("node") == []


def test_install_lock_is_exclusive():
    store.ensure_dirs()
    with install_lock("node", "22.14.0", timeout=0.3, poll=0.05):
        with pytest.raises(LockTimeout):
            with install_lock("node", "22.14.0", timeout=0.1, poll=0.02):
                pass
    # released afterwards
    with install_lock("node", "22.14.0", timeout=1.0):
        pass


def test_install_lock_reclaims_dead_owner():
    store.ensure_dirs()
    lock_path = store.locks_dir() / "node-22.14.0.lock"
    lock_path.write_text("999999999", encoding="utf-8")  # no such process

    with install_lock("node", "22.14.0", timeout=1.0, poll=0.02):
        assert lock_path.is_file()
    assert not lock_path.exists()


def test_install_lock_reclaims_ancient_lock():
    store.ensure_dirs()
    lock_path = store.locks_dir() / "node-22.14.0.lock"
    lock_path.write_text("", encoding="utf-8")
    old = time.time() - 7 * 60 * 60
    os.utime(lock_path, (old, old))

    with install_lock("node", "22.14.0", timeout=1.0, poll=0.02):
        pass


def test_home_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv(store.HOME_ENV, str(tmp_path / "custom"))
    assert store.home() == tmp_path / "custom"


# -- project stores ----------------------------------------------------------
def _make_project(tmp_path, marker=True):
    """A directory tree with an initialised .envxx at its root."""
    root = tmp_path / "proj"
    sub = root / "src" / "deep"
    sub.mkdir(parents=True)
    home = root / ".envxx"
    home.mkdir()
    if marker:
        (home / store.MARKER).write_text('{"schema": 1}', encoding="utf-8")
    return root, sub, home


def test_project_store_is_found_from_a_subdirectory(monkeypatch, tmp_path):
    monkeypatch.delenv(store.HOME_ENV, raising=False)
    root, sub, home = _make_project(tmp_path)
    monkeypatch.chdir(sub)

    # walking upwards is what makes the command behave the same below the root
    assert store.home() == home
    assert store.home_origin() == "project"


def test_a_directory_without_the_marker_is_not_a_store(monkeypatch, tmp_path):
    monkeypatch.delenv(store.HOME_ENV, raising=False)
    monkeypatch.setattr(store.Path, "home", classmethod(lambda cls: tmp_path / "user"))
    root, sub, _ = _make_project(tmp_path, marker=False)
    monkeypatch.chdir(sub)

    # a stray .envxx must not hijack the store for everything below it
    assert store.home() == tmp_path / "user" / ".envxx"
    assert store.home_origin() == "global"


def test_envxx_home_beats_a_project_store(monkeypatch, tmp_path):
    root, sub, _ = _make_project(tmp_path)
    monkeypatch.chdir(sub)
    monkeypatch.setenv(store.HOME_ENV, str(tmp_path / "pinned"))

    assert store.home() == tmp_path / "pinned"
    assert store.home_origin() == "env"


def test_the_global_store_is_never_treated_as_project_level(
    monkeypatch, tmp_path
):
    monkeypatch.delenv(store.HOME_ENV, raising=False)
    user = tmp_path / "user"
    global_home = user / ".envxx"
    global_home.mkdir(parents=True)
    (global_home / store.MARKER).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(store.Path, "home", classmethod(lambda cls: user))
    monkeypatch.chdir(user)

    # the global store is its own origin even when sitting at the cwd
    assert store.home() == global_home
    assert store.home_origin() == "global"


def test_display_path_names_the_root_in_use(monkeypatch, tmp_path):
    root, sub, home = _make_project(tmp_path)
    monkeypatch.chdir(sub)
    monkeypatch.delenv(store.HOME_ENV, raising=False)

    assert store.display_path(home / "tools" / "uv") == "./.envxx/tools/uv"

    monkeypatch.setenv(store.HOME_ENV, str(home))
    assert store.display_path(home / "tools" / "uv") == str(home / "tools" / "uv")


def test_init_creates_the_layout_and_is_idempotent(tmp_path):
    root = tmp_path / "fresh"
    root.mkdir()

    path, created = store.init_project(root)

    assert created
    assert path == root / ".envxx"
    for sub in ("tools", "downloads", "cache", ".locks"):
        assert (path / sub).is_dir()
    assert (path / store.MARKER).is_file()

    again, created_again = store.init_project(root)
    assert again == path and created_again is False


def test_init_refuses_a_directory_it_did_not_create(tmp_path):
    root = tmp_path / "someone-else"
    (root / ".envxx").mkdir(parents=True)
    (root / ".envxx" / "important.txt").write_text("keep me", encoding="utf-8")

    with pytest.raises(ValueError, match="was not created by envxx"):
        store.init_project(root)
    assert (root / ".envxx" / "important.txt").read_text(encoding="utf-8") == "keep me"


def test_init_refuses_a_file_named_envxx(tmp_path):
    root = tmp_path / "odd"
    root.mkdir()
    (root / ".envxx").write_text("not a dir", encoding="utf-8")

    with pytest.raises(ValueError, match="is a file"):
        store.init_project(root)
