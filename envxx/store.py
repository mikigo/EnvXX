from __future__ import annotations

import errno
import json
import os
import shutil
import stat
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .errors import LockTimeout

HOME_ENV = "ENVXX_HOME"

# Name of the directory a project opts into, and the file that proves envxx
# created it. The marker matters because any directory could be called
# '.envxx'; without it a stray one would hijack the store for everything
# below it.
PROJECT_DIR = ".envxx"
MARKER = ".project"
SCHEMA = 1


def global_home() -> Path:
    """The machine-wide store, overridable per invocation.

    ENVXX_HOME covers two different needs: relocating the store somewhere
    else, and giving a test or a CI job its own sandbox. Both mean "this is
    the global store for this process", so the override belongs here rather
    than only in home().
    """
    override = os.environ.get(HOME_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / PROJECT_DIR


def _is_project_store(path: Path) -> bool:
    return (path / MARKER).is_file()


def project_store(start: Path | None = None) -> Path | None:
    """The nearest initialised .envxx at or above start, if any.

    Walking upwards means 'envxx node22' behaves the same in the project root
    and in a subdirectory. The home directory is excluded on purpose: its
    .envxx *is* the global store, and treating it as project-level would make
    the same directory report two different origins.
    """
    current = (start or Path.cwd()).resolve()
    stop = Path.home().resolve()
    for candidate in (current, *current.parents):
        if candidate == stop:
            return None
        store = candidate / PROJECT_DIR
        if store.is_dir() and _is_project_store(store):
            return store
    return None


def home() -> Path:
    """Root of the envxx store for a project-scoped tool.

    ENVXX_HOME wins because it is set deliberately per invocation; a project
    store is discovered from the working directory and is a convenience, not
    a request. CI that pins ENVXX_HOME therefore keeps working inside a
    checkout that happens to carry a .envxx.
    """
    if os.environ.get(HOME_ENV):
        return global_home()
    return project_store() or global_home()


def home_origin() -> str:
    """Where home() came from: 'env', 'project' or 'global'.

    The CLI shows paths relative to whichever root is in use, and the three
    cases look different: '~/.envxx/...', './.envxx/...', or an absolute path
    the user chose themselves.
    """
    if os.environ.get(HOME_ENV):
        return "env"
    return "project" if project_store() else "global"


def display_path(path: Path) -> str:
    """Render a store path in terms the reader can map to a location.

    Two roots are in play now: a project store for runtimes and the global
    one for everything else, and a single listing can mix them. Each path is
    matched against whichever root contains it rather than assuming the one
    home() happens to return.
    """
    if os.environ.get(HOME_ENV):
        return str(path)

    project = project_store()
    if project is not None:
        try:
            return "./.envxx/" + path.relative_to(project).as_posix()
        except ValueError:
            pass
    try:
        return "~/.envxx/" + path.relative_to(global_home()).as_posix()
    except ValueError:
        return str(path)


def init_project(root: Path | None = None) -> tuple[Path, bool]:
    """Create a project store under root (default: cwd).

    Returns (store_path, created). Idempotent: an initialised store is
    reported untouched. A '.envxx' that envxx did not make is refused rather
    than absorbed, since filling someone else's directory with tool binaries
    is not something the user asked for.
    """
    base = (root or Path.cwd()).resolve()
    store = base / PROJECT_DIR

    if store.is_file():
        raise ValueError(f"{store} is a file, not a directory")
    if store.is_dir():
        if _is_project_store(store):
            return store, False
        raise ValueError(
            f"{store} already exists but was not created by envxx "
            f"(no {MARKER}); move it aside or remove it first"
        )

    store.mkdir(parents=True)
    # only runtimes are project-scoped; downloads/ and cache/ stay in the
    # global store so two checkouts do not fetch the same archive twice
    (store / "runtime").mkdir()
    _write_marker(store)
    return store, True


def kind_dir(kind: str, scoped: bool = False) -> Path:
    """Where tools of one kind live: '<home>/runtime' or '<home>/app'.

    'scoped' means the caller is willing to use a project store, which only
    runtimes get: a project pins the interpreter it needs, but an application
    like a text editor is a machine-wide thing with no reason to be
    duplicated per checkout.

    ENVXX_HOME turns project discovery off entirely. It means "this process
    uses exactly this store", which is what a test sandbox or a CI job needs;
    honouring a project store while an explicit override is set would make
    the override a suggestion rather than an instruction.
    """
    if os.environ.get(HOME_ENV):
        return global_home() / kind
    root = project_store() if scoped else global_home()
    if root is None:
        root = global_home()
    return root / kind


def layout_version() -> int:
    """The directory layout a store uses.

    1 was '<home>/tools/<tool>'; 2 splits by kind into '<home>/runtime' and
    '<home>/app', so a project can hold runtimes without taking applications
    with it. Stored in the marker so a store is migrated once and never
    rescanned.
    """
    return 2


def _marker_data(store: Path) -> dict:
    try:
        data = json.loads((store / MARKER).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_marker(store: Path) -> None:
    (store / MARKER).write_text(
        json.dumps({"schema": SCHEMA, "layout": layout_version()}) + "\n",
        encoding="utf-8",
    )


def migrate_layout(
    store: Path, runtime_names: set[str], global_store: Path | None = None
) -> list[tuple[str, str]]:
    """Move '<store>/tools/<tool>' into its layout-2 home.

    Runs are divided by kind and by store:

    - a runtime stays in whichever store it already sits in, just under
      runtime/ instead of tools/
    - an application always belongs to the global store, so one found in a
      project store is moved there rather than left where nothing will read
      it

    Runs once per store, recorded in the marker. Moving is cheap (a rename on
    the same volume), and the alternative is that every install made before
    layout 2 silently disappears from 'list'.
    """
    tools = store / "tools"
    if not tools.is_dir():
        _write_marker(store)
        return []

    is_global = global_store is not None and store.resolve() == global_store.resolve()

    moved: list[tuple[str, str]] = []
    for entry in sorted(tools.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        kind = "runtime" if entry.name in runtime_names else "app"
        if kind == "app" and not is_global and global_store is not None:
            destination = global_store / "app" / entry.name
        else:
            destination = store / kind / entry.name

        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            # a newer copy already exists; the old one is dead weight but
            # deleting it is not ours to decide
            continue
        try:
            entry.rename(destination)
            moved.append((entry.name, kind))
        except OSError:
            # a locked file or a different volume leaves the old copy behind;
            # the tool is then simply absent, which 'list' will show honestly
            continue

    # only drop the old container once it is empty, so a failed move does not
    # take the remaining tools with it
    try:
        tools.rmdir()
    except OSError:
        pass

    _write_marker(store)
    return moved


def store_needs_migration(store: Path) -> bool:
    """True for a store created before layout 2."""
    if not _is_project_store(store):
        return False
    data = _marker_data(store)
    if data.get("layout") == layout_version():
        return False
    # an unversioned store with no tools/ is simply empty; stamping it is
    # cheaper than treating it as legacy
    return (store / "tools").is_dir()


def cache_dir() -> Path:
    return global_home() / "cache"


def downloads_dir() -> Path:
    """Shared by every store on the machine, project ones included.

    A project install still extracts into its own runtime/, but the archive
    it came from is cached once: the same CPython build is 20 MB and there is
    no reason for two checkouts to fetch it twice.
    """
    return global_home() / "downloads"


def installer_path(filename: str) -> Path:
    """Where a downloaded installer lives.

    Installers are not unpacked, so downloads/ is their final home rather
    than a cache. The file keeps the publisher's name; it is something the
    user opens, not an internal artefact.
    """
    return downloads_dir() / filename


def locks_dir() -> Path:
    return global_home() / ".locks"


def shims_dir() -> Path:
    return global_home() / "shims"


def tool_dir(tool: str, kind: str = "app", scoped: bool = False) -> Path:
    """Where one tool's versions live.

    'kind' picks runtime/ or app/; 'scoped' picks the project store or the
    global one. They are separate on purpose: an application is always
    global, but a runtime outside a project is global too — it just lives
    under runtime/ there, not app/.
    """
    if kind not in ("runtime", "app"):
        raise ValueError(f"unknown kind: {kind}")
    return kind_dir(kind, scoped=scoped) / tool


def version_dir(
    tool: str, version: str, kind: str = "app", scoped: bool = False
) -> Path:
    return tool_dir(tool, kind=kind, scoped=scoped) / version


def assets_dir(tool: str, kind: str = "app", scoped: bool = False) -> Path:
    """Side artefacts a tool needs at runtime (e.g. dufs UI themes).

    Dot-prefixed so 'installed_versions' never mistakes them for a version.
    """
    return tool_dir(tool, kind=kind, scoped=scoped) / ".assets"


def installed_versions(
    tool: str, kind: str = "app", scoped: bool = False
) -> list[str]:
    """Version directories present for this tool in one location.

    Callers that care about both locations ask twice; the CLI unions them for
    runtimes so a project store and the global one are both visible.
    """
    root = tool_dir(tool, kind=kind, scoped=scoped)
    if not root.is_dir():
        return []
    return sorted(
        entry.name
        for entry in root.iterdir()
        if entry.is_dir() and not entry.name.startswith(".")
    )


def is_installed(
    tool: str, version: str, kind: str = "app", scoped: bool = False
) -> bool:
    return version_dir(tool, version, kind=kind, scoped=scoped).is_dir()


def ensure_dirs(scoped: bool = False) -> None:
    """Create the directories an install needs.

    downloads/ and cache/ belong to the machine, so they are made once in
    the global store even when the install itself is project-scoped.
    """
    root = project_store() if scoped else None
    paths = [cache_dir(), downloads_dir(), locks_dir()]
    if root is not None:
        paths.append(root / "runtime")
    else:
        paths.append(global_home() / "app")
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def remove_version(
    tool: str, version: str, kind: str = "app", scoped: bool = False
) -> None:
    """Delete a version directory, making read-only files writable first.

    rmtree with ignore_errors would leave the directory behind on Windows
    whenever something in it is read-only (extracted archives keep their
    mode bits), and the caller would then see a directory that exists but
    is incomplete. Clear the flag instead and let a real failure surface.
    """
    root = version_dir(tool, version, kind=kind, scoped=scoped)
    if not root.is_dir():
        return

    def _force_writable(function: object, path: str, _exc: object) -> None:
        # the retry gets one chance after the read-only bit is cleared
        os.chmod(path, stat.S_IWRITE)
        function(path)  # type: ignore[operator]

    if os.name == "nt":
        # onerror is deprecated in 3.12 but onexc does not exist before it,
        # and this project still supports 3.10
        shutil.rmtree(root, onerror=_force_writable)
    else:
        shutil.rmtree(root)


def temp_dir(tool: str, kind: str = "app", scoped: bool = False) -> Path:
    """Hidden staging directory next to version dirs, so rename stays on one volume."""
    path = tool_dir(tool, kind=kind, scoped=scoped) / f".tmp-{uuid.uuid4().hex}"
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


def _pid_alive(pid: int) -> bool:
    """Best-effort process liveness check.

    os.kill(pid, 0) is not usable on Windows: CPython implements it as
    TerminateProcess, so probing would kill the process.
    """
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _lock_is_stale(lock_path: Path, max_age: float) -> bool:
    """A lock whose owner died (or that is absurdly old) can be reclaimed."""
    try:
        owner = lock_path.read_text(encoding="utf-8").strip()
        mtime = lock_path.stat().st_mtime
    except OSError:
        return False
    if owner.isdigit() and not _pid_alive(int(owner)):
        return True
    return time.time() - mtime > max_age


@contextmanager
def install_lock(
    tool: str,
    version: str,
    timeout: float = 600.0,
    poll: float = 0.2,
    stale_after: float = 6 * 60 * 60,
):
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
            # the previous owner may have been killed mid-install
            if _lock_is_stale(lock_path, stale_after):
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue
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
