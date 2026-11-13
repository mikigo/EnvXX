from __future__ import annotations

import errno
import os
import shutil
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .errors import LockTimeout

HOME_ENV = "ENVXX_HOME"


def home() -> Path:
    """Root of the envxx store, ~/.envxx unless ENVXX_HOME is set."""
    override = os.environ.get(HOME_ENV)
    return Path(override).expanduser() if override else Path.home() / ".envxx"


def tools_dir() -> Path:
    return home() / "tools"


def cache_dir() -> Path:
    return home() / "cache"


def downloads_dir() -> Path:
    return home() / "downloads"


def locks_dir() -> Path:
    return home() / ".locks"


def shims_dir() -> Path:
    return home() / "shims"


def tool_dir(tool: str) -> Path:
    return tools_dir() / tool


def version_dir(tool: str, version: str) -> Path:
    return tool_dir(tool) / version


def installed_versions(tool: str) -> list[str]:
    """Version directories present on disk, newest-looking first is left to caller."""
    root = tool_dir(tool)
    if not root.is_dir():
        return []
    return sorted(
        entry.name
        for entry in root.iterdir()
        if entry.is_dir() and not entry.name.startswith(".")
    )


def is_installed(tool: str, version: str) -> bool:
    return version_dir(tool, version).is_dir()


def ensure_dirs() -> None:
    for path in (tools_dir(), cache_dir(), downloads_dir(), locks_dir()):
        path.mkdir(parents=True, exist_ok=True)


def remove_version(tool: str, version: str) -> None:
    shutil.rmtree(version_dir(tool, version), ignore_errors=True)


def temp_dir(tool: str) -> Path:
    """Hidden staging directory next to version dirs, so rename stays on one volume."""
    path = tool_dir(tool) / f".tmp-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def activate(staging: Path, target: Path, attempts: int = 5) -> None:
    """Move a staged install into place.

    On Windows an on-access virus scanner can hold a handle to the freshly
    written executables for a moment, which makes the directory rename fail
    with a permission error. Retry briefly, then fall back to copying.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            staging.rename(target)
            return
        except PermissionError as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(0.25 * (attempt + 1))

    shutil.copytree(staging, target, dirs_exist_ok=True)
    shutil.rmtree(staging, ignore_errors=True)
    if not target.is_dir():  # pragma: no cover - copy failure surfaces here
        raise last  # type: ignore[misc]


@contextmanager
def install_lock(tool: str, version: str, timeout: float = 600.0, poll: float = 0.2):
    """Cross-process lock so two concurrent installs of the same version serialize."""
    locks_dir().mkdir(parents=True, exist_ok=True)
    lock_path = locks_dir() / f"{tool}-{version}.lock"
    deadline = time.monotonic() + timeout
    fd: int | None = None
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise LockTimeout(
                    f"another envxx process is installing {tool} {version}"
                ) from None
            time.sleep(poll)
        except OSError as exc:  # pragma: no cover - unusual fs errors
            if exc.errno == errno.EEXIST:
                continue
            raise
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
