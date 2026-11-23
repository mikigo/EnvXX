"""Persistent environment variables and PATH entries.

EnvXX's promise is that everything lives in one directory and deleting it
uninstalls the tool. Writing to the system's environment breaks that promise
unless it is done carefully, so every mutation here backs up the previous
value first and can be undone.

The platform split is not cosmetic. Windows keeps the user environment in the
registry and broadcasts a message so new processes pick it up; POSIX systems
keep it in shell startup files, which only new shells read. Neither can change
the environment of a terminal that is already open, and both say so.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import store
from .errors import UsageError

HOME_ENV = store.HOME_ENV

# Windows truncates a registry value at 1024 characters in some consumers and
# setx refuses anything longer outright, so PATH is edited in place instead.
_PATH_NAME = "PATH"


def _backup_dir() -> Path:
    return store.home() / ".backup"


def _snapshot(kind: str, name: str, previous: str | None) -> Path:
    """Record a value before changing it, so --restore has something to use."""
    folder = _backup_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = folder / f"{kind}-{name}-{stamp}.json"
    path.write_text(
        json.dumps(
            {"kind": kind, "name": name, "previous": previous, "at": stamp},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _expand(value: str) -> str:
    """Turn a relative path into an absolute one.

    A relative entry in PATH is resolved against whatever directory the
    reading process happens to be in, which is almost never the one that
    wrote it. Expanding once at write time is the only way the entry means
    what the user intended.
    """
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return str(path)


def _reject_path_name(name: str) -> None:
    if name.upper() == _PATH_NAME:
        raise UsageError(
            "use 'envxx set-path' for PATH: replacing it wholesale would "
            "drop every existing entry"
        )


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------
def _win_scope(system: bool):
    import winreg

    return (
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
    ) if system else (winreg.HKEY_CURRENT_USER, "Environment")


def _win_read(name: str, system: bool) -> str | None:
    import winreg

    root, subkey = _win_scope(system)
    try:
        with winreg.OpenKey(root, subkey) as key:
            value, _ = winreg.QueryValueEx(key, name)
    except FileNotFoundError:
        return None
    return str(value)


def _win_write(name: str, value: str, system: bool) -> None:
    import winreg

    root, subkey = _win_scope(system)
    with winreg.CreateKeyEx(root, subkey, 0, winreg.KEY_SET_VALUE) as key:
        # REG_EXPAND_SZ so a value containing %OTHER% keeps expanding; a plain
        # path works the same either way
        kind = winreg.REG_EXPAND_SZ
        winreg.SetValueEx(key, name, 0, kind, value)


def _win_delete(name: str, system: bool) -> bool:
    import winreg

    root, subkey = _win_scope(system)
    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, name)
            return True
    except FileNotFoundError:
        return False


def _win_broadcast() -> None:
    """Tell running programs the environment changed.

    Without this only processes started from a fresh login see the update;
    Explorer caches the environment block it hands to new processes.

    SendMessageTimeout rather than SendMessage: the plain call blocks until
    every top-level window answers, and one hung application is enough to
    make 'envxx set_env' hang forever. The registry write has already
    happened at this point, so a timed-out broadcast is not worth failing for.
    """
    import ctypes

    HWND_BROADCAST = 0xFFFF
    WM_SETTINGCHANGE = 0x001A
    SMTO_ABORTIFHUNG = 0x0002
    try:
        ctypes.windll.user32.SendMessageTimeoutW(  # type: ignore[attr-defined]
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
            SMTO_ABORTIFHUNG, 2000, None,
        )
    except OSError:
        pass


# ---------------------------------------------------------------------------
# POSIX
# ---------------------------------------------------------------------------
def _shell_rc_files() -> list[Path]:
    """Startup files this login shell would read, most specific first."""
    home = Path.home()
    files: list[Path] = []
    shell = os.environ.get("SHELL", "")

    if "zsh" in shell:
        files.append(home / ".zshrc")
    if "bash" in shell or not shell:
        files.extend([home / ".bashrc", home / ".bash_profile"])
    files.append(home / ".profile")
    return files


def _marker(name: str) -> tuple[str, str]:
    begin = f"# >>> envxx: {name} >>>"
    end = f"# <<< envxx: {name} <<<"
    return begin, end


def _posix_read_rc(name: str) -> str | None:
    begin, _ = _marker(name)
    for rc in _shell_rc_files():
        if not rc.is_file():
            continue
        text = rc.read_text(encoding="utf-8", errors="replace")
        if begin not in text:
            continue
        match = re.search(
            re.escape(begin) + r"\n(.*?)\n# <<< envxx: " + re.escape(name),
            text,
            re.S,
        )
        if match:
            return match.group(1)
    return None


def _posix_write_rc(name: str, line: str) -> Path:
    """Put one export line inside a marked block in the user's startup file."""
    rc = _shell_rc_files()[0]
    rc.touch(exist_ok=True)
    text = rc.read_text(encoding="utf-8", errors="replace")
    begin, end = _marker(name)
    block = f"{begin}\n{line}\n{end}\n"

    if begin in text:
        text = re.sub(
            re.escape(begin) + r".*?" + re.escape(end) + r"\n?",
            block,
            text,
            flags=re.S,
        )
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += block
    rc.write_text(text, encoding="utf-8")
    return rc


def _posix_remove_rc(name: str) -> bool:
    begin, end = _marker(name)
    removed = False
    for rc in _shell_rc_files():
        if not rc.is_file():
            continue
        text = rc.read_text(encoding="utf-8", errors="replace")
        if begin not in text:
            continue
        rc.write_text(
            re.sub(
                re.escape(begin) + r".*?" + re.escape(end) + r"\n?",
                "",
                text,
                flags=re.S,
            ),
            encoding="utf-8",
        )
        removed = True
    return removed


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def is_windows() -> bool:
    return os.name == "nt"


def supports_system_scope() -> bool:
    """macOS dropped /etc/launchd.conf, so system scope is refused there."""
    return is_windows() or os.environ.get("ENVXX_TEST_POSIX", "") == "linux"


def read_env(name: str, system: bool = False) -> str | None:
    if is_windows():
        return _win_read(name, system)
    return _posix_read_rc(name)


def set_env(name: str, value: str, system: bool = False) -> str | None:
    """Set one variable permanently. Returns the previous value, if any."""
    _reject_path_name(name)
    if system and not supports_system_scope():
        raise UsageError("system scope is not supported on this platform")

    previous = read_env(name, system)
    _snapshot("env", name, previous)

    if is_windows():
        _win_write(name, value, system)
        _win_broadcast()
    else:
        rc = _posix_write_rc(name, f'export {name}="{value}"')
        return previous
    return previous


def unset_env(name: str, system: bool = False) -> bool:
    _reject_path_name(name)
    previous = read_env(name, system)
    _snapshot("env", name, previous)

    if is_windows():
        gone = _win_delete(name, system)
        if gone:
            _win_broadcast()
        return gone
    return _posix_remove_rc(name)


def read_path(system: bool = False) -> str:
    return read_env(_PATH_NAME, system) or ""


def _split_path(value: str) -> list[str]:
    return [part for part in value.split(os.pathsep) if part]


def set_path(
    directory: str, system: bool = False, *, append: bool = False
) -> tuple[str, bool]:
    """Put a directory on PATH. Returns (expanded path, whether it changed).

    Prepended by default: a directory the user just asked to add is the one
    they want to win, and later entries in PATH lose to earlier ones. An
    entry already present is left where it is, so running the command twice
    does not reorder a PATH or grow it with duplicates.
    """
    if system and not supports_system_scope():
        raise UsageError("system scope is not supported on this platform")

    expanded = _expand(directory)
    current = read_path(system)
    entries = _split_path(current)

    if any(Path(entry).expanduser() == Path(expanded) for entry in entries):
        return expanded, False

    _snapshot("path", _PATH_NAME, current)
    if append:
        entries = [*entries, expanded]
    else:
        entries = [expanded, *entries]

    if is_windows():
        _win_write(_PATH_NAME, os.pathsep.join(entries), system)
        _win_broadcast()
    else:
        _posix_write_rc(_PATH_NAME, f'export PATH="{expanded}:$PATH"')
    return expanded, True


def remove_path(directory: str, system: bool = False) -> bool:
    """Drop a directory from PATH, matching on the expanded form."""
    expanded = _expand(directory)
    current = read_path(system)
    entries = _split_path(current)
    kept = [e for e in entries if Path(e).expanduser() != Path(expanded)]
    if len(kept) == len(entries):
        return False

    _snapshot("path", _PATH_NAME, current)
    if is_windows():
        _win_write(_PATH_NAME, os.pathsep.join(kept), system)
        _win_broadcast()
    else:
        _posix_remove_rc(_PATH_NAME)
    return True


def backups() -> list[Path]:
    folder = _backup_dir()
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.json"), reverse=True)
