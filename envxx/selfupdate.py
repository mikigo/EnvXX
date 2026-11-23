"""Updating envxx itself.

Two install shapes, two upstreams. A frozen binary is a file that envxx owns
and can replace; a pip install is a package that pip owns and must be asked
to upgrade. Deciding which one is running is the first thing every entry
point here does, because the same command means different things.

The Windows constraint shapes the frozen path. A running executable cannot
be overwritten, but it can be renamed: the image is mapped by file identity,
and the name is just a directory entry. So the old binary is moved aside,
the new one takes its place, and the leftover '.old' file is deleted by the
next start, when nothing holds it any more. If any step fails the rename is
undone, because leaving no envxx at all is worse than leaving the old one.

Applications of another manager -- pipx, uv -- are never upgraded through
pip. Those tools keep records of what they installed, and writing into their
environment behind their back makes that record wrong. The command is
printed instead, and only run when the user passes --yes.
"""
from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import NoReturn

from . import __version__
from . import archive, http, store
from .errors import SelfUpdateError
from .platforms import Platform, detect_platform
from .versions import version_key

REPO = "mikigo/EnvXX"
_RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
_RELEASE_TAG_API = f"https://api.github.com/repos/{REPO}/releases/tags/v{{version}}"
_DOWNLOAD = f"https://github.com/{REPO}/releases/download"
_PYPI_JSON = "https://pypi.org/pypi/envxx/json"

# How long a version check may take before it is abandoned. A hint printed at
# startup is never worth making the command wait, so this is deliberately far
# below the 30s the rest of the network layer allows.
NOTICE_TIMEOUT = 2.0
NOTICE_TTL = 24 * 60 * 60
NO_CHECK_ENV = "ENVXX_NO_UPDATE_CHECK"

# A hint printed during a CI job is noise in a log nobody reads.
_CI_ENV = (
    "CI",
    "GITHUB_ACTIONS",
    "GITLAB_CI",
    "TF_BUILD",
    "BUILDKITE",
    "TRAVIS",
    "JENKINS_URL",
    "APPVEYOR",
    "TEAMCITY_VERSION",
    "CIRCLECI",
)

_MANAGER_COMMANDS = {
    "pipx": ["pipx", "upgrade", "envxx"],
    "uv-tool": ["uv", "tool", "upgrade", "envxx"],
}


def _is_windows() -> bool:
    """The one place this module asks which platform it is on.

    Indirected so tests can exercise both replacement shapes on any host:
    assigning os.name would break pathlib, which picks its flavour from it
    at construction time.
    """
    return os.name == "nt"


# ---------------------------------------------------------------------------
# how this copy was installed
# ---------------------------------------------------------------------------
def install_mode() -> str:
    """frozen | pip | pipx | uv-tool | editable | source.

    Only the first two can be updated by envxx itself; the manager ones are
    handed back to the tool that owns them, and the source ones are refused
    because there is no upstream to ask.
    """
    if getattr(sys, "frozen", False):
        return "frozen"

    try:
        dist = importlib.metadata.distribution("envxx")
    except importlib.metadata.PackageNotFoundError:
        # imported from a checkout rather than installed
        return "source"

    # pip writes direct_url.json for installs that did not come from an index;
    # an editable one is a pointer at a working tree, and replacing it with a
    # wheel would silently break the developer's setup. This is checked before
    # the shadow test because an editable install legitimately lives outside
    # site-packages, and reporting it as 'source' would lose that distinction.
    try:
        direct = dist.read_text("direct_url.json")
    except OSError:
        direct = None
    if direct:
        try:
            payload = json.loads(direct)
        except json.JSONDecodeError:
            payload = {}
        if payload.get("dir_info", {}).get("editable"):
            return "editable"

    # A checkout on PYTHONPATH, or a script run from inside the repository,
    # shadows the installed package: this process is running code that pip
    # does not manage, so upgrading the distribution would leave the code
    # actually in use untouched. Say so rather than reporting a successful
    # upgrade that changed nothing.
    try:
        origin = Path(__file__).resolve().parent
        installed = Path(dist.locate_file("envxx")).resolve()
        if origin != installed:
            return "source"
    except (OSError, TypeError, ValueError):
        pass

    prefix = Path(sys.prefix).as_posix()
    if "/pipx/venvs/" in prefix:
        return "pipx"
    if "/uv/tools/" in prefix:
        return "uv-tool"
    return "pip"


def _running_exe() -> Path | None:
    """The frozen binary this process was started from, or None."""
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve()


def _console_script() -> Path | None:
    """The 'envxx' console script, when this process was started through it.

    A pip upgrade rewrites this file, and on Windows that fails while it is
    the very file being executed. Knowing which one it is lets the upgrade
    move it aside first.
    """
    if getattr(sys, "frozen", False):
        return None
    argv0 = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
    if argv0 is None or argv0.stem.lower() != "envxx":
        return None
    try:
        return argv0.resolve() if argv0.resolve().is_file() else None
    except OSError:
        return None


# ---------------------------------------------------------------------------
# talking to the two upstreams
# ---------------------------------------------------------------------------
def latest_frozen() -> str:
    """Newest published release tag, without its leading 'v'.

    'releases/latest' rather than the tag list on purpose: a tag whose build
    failed has no release, and offering it would download a file that does
    not exist. v1.9.3 is exactly that case.
    """
    payload = http.get_json(_RELEASE_API, "envxx-release-latest")
    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        raise SelfUpdateError("the latest release has no tag to compare against")
    return tag.lstrip("vV")


def latest_pypi() -> str:
    payload = http.get_json(_PYPI_JSON, "envxx-pypi-latest")
    try:
        return str(payload["info"]["version"])
    except (KeyError, TypeError):
        raise SelfUpdateError("unexpected PyPI response for envxx") from None


def latest_for(mode: str) -> str:
    if mode == "frozen":
        return latest_frozen()
    return latest_pypi()


def match_frozen_release(version: str, platform: Platform) -> tuple[str, str | None]:
    """(download url, sha256 or None) for one version on this platform.

    The digest comes from the release payload. GitHub attaches it to every
    uploaded asset, so no separate SHA256SUMS file has to be published; a
    release old enough to lack it is still installable, unverified.
    """
    payload = http.get_json(
        _RELEASE_TAG_API.format(version=version),
        f"envxx-release-{version}",
    )
    wanted = f"{version}-{platform.tag}.zip"
    for asset in payload.get("assets") or []:
        if asset.get("name") != wanted:
            continue
        digest = str(asset.get("digest") or "")
        sha = digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else None
        url = str(
            asset.get("browser_download_url")
            or f"{_DOWNLOAD}/v{version}/{wanted}"
        )
        return url, sha
    raise SelfUpdateError(
        f"release v{version} has no {wanted}; the asset may still be uploading"
    )


# ---------------------------------------------------------------------------
# replacing the binary
# ---------------------------------------------------------------------------
def _staged_binary(staging: Path) -> Path:
    """The one executable an extracted release archive holds."""
    files = [
        path
        for path in staging.rglob("*")
        if path.is_file() and not path.name.startswith(".")
    ]
    if len(files) != 1:
        names = ", ".join(sorted(p.name for p in files)) or "nothing"
        raise SelfUpdateError(f"the release archive holds {names}, expected one file")
    return files[0]


def _install_file(incoming: Path, target: Path, attempts: int = 5) -> None:
    """Put `incoming` at `target`, tolerating a running Windows executable."""
    if not _is_windows():
        os.replace(incoming, target)
        return

    # Renaming the running image is allowed; overwriting it is not. Both files
    # sit in the target's directory already, so these renames stay on one
    # volume.
    retired = target.with_name(target.name + ".old")
    try:
        retired.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise SelfUpdateError(
            f"cannot clear the previous {retired.name}: {exc}"
        ) from exc

    target.rename(retired)
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            os.replace(incoming, target)
            return
        except PermissionError as exc:
            # an on-access scanner can hold the new file for a moment
            last = exc
            if attempt < attempts - 1:
                time.sleep(0.25 * (attempt + 1))
        except OSError as exc:
            last = exc
            break

    # Nothing has taken the target's place, so put the old one back. A failed
    # update must leave a working envxx behind.
    try:
        retired.rename(target)
    except OSError:  # pragma: no cover - target vanished under us
        pass
    incoming.unlink(missing_ok=True)
    raise SelfUpdateError(
        f"cannot replace {target}: {last}. Close every running envxx and retry."
    )


def _verify_binary(path: Path, version: str) -> None:
    """Refuse to install a binary that does not answer with the right version.

    Swapping a working envxx for one that cannot start is far worse than not
    updating, and the only way to know is to run it. This also repeats the
    smoke test CI ran on the same file, on the machine that will use it.
    """
    if not _is_windows():
        path.chmod(path.stat().st_mode | 0o111)
    try:
        result = subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SelfUpdateError(f"the downloaded binary cannot run: {exc}") from None

    got = result.stdout.strip()
    want = f"envxx {version}"
    if got != want:
        raise SelfUpdateError(
            f"the downloaded binary reports {got or 'nothing'!r}, expected {want!r}"
        )


def read_version(exe: Path) -> str:
    """Ask a binary what version it is, in a process that is not this one."""
    result = subprocess.run(
        [str(exe), "--version"], capture_output=True, text=True, timeout=60
    )
    text = result.stdout.strip()
    return text.split()[-1] if text.startswith("envxx ") else ""


def upgrade_frozen(version: str, *, quiet: bool = False) -> str:
    """Download `version` and replace this binary with it. Returns its path."""
    exe = _running_exe()
    if exe is None:  # pragma: no cover - guarded by the caller
        raise SelfUpdateError("this is not a frozen envxx binary")

    platform = detect_platform()
    url, sha = match_frozen_release(version, platform)
    filename = f"{version}-{platform.tag}.zip"

    with store.install_lock("envxx", version):
        dest = store.downloads_dir() / filename
        if dest.is_file() and sha and http.sha256_file(dest) != sha:
            dest.unlink()
        if not dest.is_file():
            http.download(url, dest, expected=sha, show_progress=not quiet)

        staging = store.global_home() / ".update" / version
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        archive.extract(dest, staging, strip_top=True)

        try:
            source = _staged_binary(staging)
            _verify_binary(source, version)
            # Copy beside the target first: the store and the binary can be on
            # different volumes, and a rename across volumes is a copy anyway,
            # done at the moment we still want a rollback to be possible.
            incoming = exe.with_name(exe.name + ".new")
            shutil.copy2(source, incoming)
            try:
                _install_file(incoming, exe)
            except BaseException:
                incoming.unlink(missing_ok=True)
                raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    return str(exe)


def sweep_stale() -> None:
    """Delete '.old' files a previous update could not remove.

    The old binary is still mapped while the process that replaced it runs,
    so the file has to survive until the next start. Failure is ignored: a
    leftover file is untidy, never a reason for a command to fail.
    """
    candidates = [p for p in (_running_exe(), _console_script()) if p is not None]
    for path in candidates:
        stale = path.with_name(path.name + ".old")
        try:
            stale.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# pip, and the tools that wrap it
# ---------------------------------------------------------------------------
def _pip_run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pip", *args],
        capture_output=True,
        text=True,
        timeout=1800,
    )


def pip_target_version() -> str | None:
    """What pip itself would install, or None when pip is too old to say.

    Resolving through pip rather than reading PyPI keeps a private index, a
    mirror or a --pre preference working: the version compared against is the
    same one the install would pick.
    """
    report = Path(store.cache_dir()) / "pip-self-update-report.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    result = _pip_run(
        ["install", "--upgrade", "--dry-run", "--quiet", "--report", str(report), "envxx"]
    )
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
        return str(payload["install"][0]["metadata"]["version"])
    except (OSError, json.JSONDecodeError, KeyError, IndexError, TypeError):
        return None
    finally:
        report.unlink(missing_ok=True)


def _pip_failure_hint(text: str) -> str:
    """Turn pip's wall of text into the one line that applies."""
    lowered = text.lower()
    if "externally-managed-environment" in lowered:
        return (
            "this Python is managed by the system package manager; "
            "install envxx with pipx, or into a virtual environment"
        )
    if "no module named pip" in lowered:
        return "this environment has no pip; use 'uv pip install --python ...' instead"
    if "permission denied" in lowered or "access is denied" in lowered:
        return "pip could not write to its install directory (try --user, or a venv)"
    return ""


def upgrade_with_pip() -> str:
    """Upgrade the installed package through pip. Returns the new version."""
    target = pip_target_version()
    if target is not None and version_key(target) <= version_key(__version__):
        return __version__

    # Windows refuses to overwrite the console script while this process is
    # executing it, so the first attempt can fail for a reason that has
    # nothing to do with the package. Moving that file aside first makes the
    # retry possible.
    result = _pip_run(["install", "--upgrade", "envxx"])
    if result.returncode != 0:
        script = _console_script()
        if script is None:
            _raise_pip_failure(result.stderr)
        retired = script.with_name(script.name + ".old")
        try:
            retired.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            _raise_pip_failure(result.stderr)
        try:
            script.rename(retired)
        except OSError:
            _raise_pip_failure(result.stderr)

        retry = _pip_run(["install", "--upgrade", "envxx"])
        if retry.returncode != 0:
            # put the working launcher back before reporting why
            try:
                retired.rename(script)
            except OSError:  # pragma: no cover
                pass
            _raise_pip_failure(retry.stderr)
        try:
            retired.unlink()
        except OSError:
            pass

    return _installed_version() or (target or "")


def _installed_version() -> str:
    """The version now on disk, read by a process that has not loaded it.

    This interpreter imported the old envxx at startup, so asking it what
    version is installed would answer with the one just replaced.
    """
    import tempfile

    try:
        result = subprocess.run(
            [sys.executable, "-I", "-c", "import envxx; print(envxx.__version__)"],
            capture_output=True,
            text=True,
            timeout=120,
            # -I keeps the working directory off sys.path, but be explicit:
            # a checkout beside the caller must not shadow the installed one
            cwd=tempfile.gettempdir(),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _raise_pip_failure(text: str) -> NoReturn:
    """Turn pip's output into one actionable error and stop."""
    hint = _pip_failure_hint(text)
    tail = "\n".join(line for line in text.strip().splitlines()[-8:] if line.strip())
    message = "pip could not upgrade envxx"
    if hint:
        message += f": {hint}"
    if tail:
        message += f"\n{tail}"
    raise SelfUpdateError(message)


def manager_command(mode: str) -> list[str] | None:
    return _MANAGER_COMMANDS.get(mode)


def run_manager_upgrade(mode: str) -> str:
    """Let pipx or uv do the upgrade in its own environment."""
    cmd = manager_command(mode)
    if cmd is None:
        raise SelfUpdateError(f"no upgrade command known for {mode}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except FileNotFoundError:
        raise SelfUpdateError(
            f"{cmd[0]} is not on PATH; run '{' '.join(cmd)}' yourself"
        ) from None
    except (OSError, subprocess.SubprocessError) as exc:
        raise SelfUpdateError(f"{cmd[0]} could not run: {exc}") from None

    if result.returncode != 0:
        tail = "\n".join(
            line for line in result.stderr.strip().splitlines()[-8:] if line.strip()
        )
        raise SelfUpdateError(
            f"'{' '.join(cmd)}' failed"
            + (f"\n{tail}" if tail else "")
        )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# the startup hint
# ---------------------------------------------------------------------------
def _notice_cache() -> Path:
    return store.cache_dir() / "envxx-latest.json"


def _notice_enabled() -> bool:
    if os.environ.get(NO_CHECK_ENV):
        return False
    if any(os.environ.get(name) for name in _CI_ENV):
        return False
    try:
        return sys.stderr.isatty()
    except (AttributeError, ValueError):
        return False


def _quick_latest(mode: str) -> str | None:
    """The newest version, from a cache or one short request.

    Deliberately not http.get_json: that retries and allows 30 seconds, which
    is fine for a command the user asked for and unacceptable for a hint
    printed on top of one they did not.
    """
    cache = _notice_cache()
    try:
        if cache.is_file() and time.time() - cache.stat().st_mtime < NOTICE_TTL:
            payload = json.loads(cache.read_text(encoding="utf-8"))
            version = str(payload.get("version") or "")
            if version:
                return version
    except (OSError, json.JSONDecodeError):
        pass

    url = _RELEASE_API if mode == "frozen" else _PYPI_JSON
    try:
        with http.client(timeout=NOTICE_TIMEOUT) as client:
            response = client.get(http.apply_mirror(url))
        if response.status_code != 200:
            return None
        payload = response.json()
        version = (
            str(payload.get("tag_name") or "").lstrip("vV")
            if mode == "frozen"
            else str(payload["info"]["version"])
        )
    except Exception:
        # a hint is not worth failing a command over, whatever went wrong
        return None

    if not version:
        return None
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".json.part")
        tmp.write_text(json.dumps({"version": version}), encoding="utf-8")
        tmp.replace(cache)
    except OSError:
        pass
    return version


def notice() -> str | None:
    """A one-line 'a newer envxx exists', or None. Never raises."""
    try:
        if not _notice_enabled():
            return None
        mode = install_mode()
        if mode in ("source", "editable"):
            return None
        version = _quick_latest(mode)
        if version is None or version_key(version) <= version_key(__version__):
            return None
        return (
            f"envxx {version} is available (you have {__version__}); "
            f"run 'envxx self-update'"
        )
    except Exception:  # pragma: no cover - the hint must never break a command
        return None
