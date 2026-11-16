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
