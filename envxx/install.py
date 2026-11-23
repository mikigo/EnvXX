from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console

from . import archive, http, store
from .errors import InstallError
from .providers import Provider
from .providers.spec import Asset

console = Console(stderr=True)


def _expected_sha256(asset: Asset, checksum: str) -> str | None:
    if asset.sha256:
        return asset.sha256
    if not asset.sha256_url:
        return None

    text = http.get_text(asset.sha256_url)
    if checksum == "sha256_file":
        # a file holding nothing but the hex digest
        candidate = text.strip().split()[0] if text.strip() else ""
        if len(candidate) == 64:
            return candidate.lower()
        found = http.parse_sha256_sum(text, asset.sha256_filename or asset.filename)
        if found:
            return found
        raise InstallError(f"no checksum in {asset.sha256_url}")
    if checksum == "shasums_file":
        found = http.parse_sha256_sum(text, asset.sha256_filename or asset.filename)
        if not found:
            raise InstallError(
                f"no checksum for {asset.filename} in {asset.sha256_url}"
            )
        return found
    return http.parse_sha256_sum(text, asset.sha256_filename or asset.filename)


def _cache_name(version: str, filename: str) -> str:
    """Downloads for different versions must not share one cache file.

    python, node and claude embed the version in the asset name; opencode
    ships the same filename for every release, so qualify those.
    """
    if version in filename:
        return filename
    return f"{version}-{filename}"


def install(provider: Provider, version: str, *, quiet: bool = False) -> Path:
    """Install a version and return its directory. No-op if already present.

    A version directory only counts as installed when its entrypoints are
    actually there. An interrupted download, a full disk or a deleted file
    can leave the directory in place while the binary is missing, and
    trusting the directory alone would make that state permanent: install
    would keep saying nothing is wrong and the launch would keep failing.
    """
    tool = provider.spec.name
    # runtimes may live in a project store; applications never do
    kind = provider.spec.kind
    scoped = kind == "runtime"
    plan = provider.plan(version)

    # An installer is fetched, never unpacked or run: the user double-clicks
    # it. Everything below this point assumes a portable tree, so this case
    # leaves before any of it.
    if plan.download_only:
        return _fetch_installer(provider, plan, quiet=quiet)

    target = store.version_dir(tool, version, kind=kind, scoped=scoped)
    if _is_complete(provider, version, target):
        return target
    if target.is_dir():
        if not quiet:
            console.print(
                f"[yellow]{tool} {version} is present but incomplete, reinstalling[/yellow]"
            )
        store.remove_version(tool, version, kind=kind, scoped=scoped)

    store.ensure_dirs(scoped=scoped)
    with store.install_lock(tool, version):
        # another process may have finished while we waited
        if _is_complete(provider, version, target):
            return target
        if target.is_dir():
            store.remove_version(tool, version, kind=kind, scoped=scoped)

        asset = plan.asset
        if not quiet:
            console.print(f"[dim]installing {tool} {version} ({asset.filename})[/dim]")

        dest = store.downloads_dir() / _cache_name(version, asset.filename)
        expected = _expected_sha256(asset, provider.spec.checksum)
        if dest.is_file() and expected and http.sha256_file(dest) != expected.lower():
            dest.unlink()
        if not dest.is_file():
            http.download(asset.url, dest, expected=expected, show_progress=not quiet)

        staging = store.temp_dir(tool, kind=kind, scoped=scoped)
        try:
            if asset.format == "exe":
                archive.copy_single(dest, staging, name=plan.single_name)
            else:
                archive.extract(dest, staging, strip_top=plan.strip_top)

            _verify_entrypoints(provider, version, staging)

            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                store.remove_version(tool, version, kind=kind, scoped=scoped)
            store.activate(staging, target)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    if not quiet:
        console.print(
            f"[green]installed[/green] {tool} {version} -> "
            f"{store.display_path(target)}"
        )
    return target


def _fetch_installer(provider: Provider, plan, *, quiet: bool) -> Path:
    """Download an installer and return where it landed.

    Nothing is unpacked and nothing is executed. Keeping the file in
    downloads/ means a second run is free, and the caller prints the path so
    the user can open it from their file manager.
    """
    asset = plan.asset
    store.ensure_dirs()
    # the original file name, not the de-duplicated cache name: this file is
    # handed to a person to open, and '26.06-7z2606-x64.exe' is not what the
    # publisher shipped or what the user expects to see
    dest = store.installer_path(asset.filename)

    if not quiet:
        console.print(
            f"[dim]downloading {provider.spec.name} {plan.version} "
            f"({asset.filename})[/dim]"
        )

    expected = _expected_sha256(asset, provider.spec.checksum)
    if dest.is_file() and expected and http.sha256_file(dest) != expected.lower():
        dest.unlink()
    if not dest.is_file():
        http.download(asset.url, dest, expected=expected, show_progress=not quiet)

    if not quiet:
        # the absolute path, not the store-relative one: this is meant to be
        # opened in a file manager or pasted into a shell
        console.print(f"[green]downloaded[/green] {dest}")

    launch_installer(dest, quiet=quiet)
    return dest


def _host() -> str:
    """Which desktop convention this process is running under.

    Indirected for the same reason as shims._is_windows: os.name cannot be
    patched in a test on Windows without breaking pathlib, so leaving the
    comparison inline means the two non-Windows branches are unreachable on a
    Windows host and the Windows branch is unreachable on the Ubuntu runner.
    That asymmetry is invisible until CI runs.
    """
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _opener_argv(host: str, path: Path) -> list[str] | None:
    """The command that hands a file to the desktop, or None for the shell API.

    Windows gets None: os.startfile uses the file association directly and
    starts no console window, which a subprocess call would flash.
    """
    if host == "windows":
        return None
    if host == "macos":
        return ["open", str(path)]
    return ["xdg-open", str(path)]


def _open_with_desktop(path: Path, host: str | None = None) -> None:
    argv = _opener_argv(host or _host(), path)
    if argv is None:
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(argv)


def launch_installer(path: Path, *, quiet: bool) -> bool:
    """Hand the downloaded installer to the desktop so the user can run it.

    Opening it is the point of downloading an installer, but it must never
    happen silently in a script: the runner waits for a click, which would
    hang CI. A non-interactive run therefore only prints where the file is.

    Returns whether it was opened.
    """
    if quiet or not sys.stdin.isatty():
        return False

    try:
        _open_with_desktop(path)
    except OSError as exc:
        console.print(f"[yellow]could not open the installer:[/yellow] {exc}")
        return False

    console.print(
        "[dim]the installer window is open; finish or close it when ready[/dim]"
    )
    return True


def _is_complete(provider: Provider, version: str, target: Path) -> bool:
    if not target.is_dir():
        return False
    try:
        _verify_entrypoints(provider, version, target)
    except InstallError:
        return False
    return True


def _verify_entrypoints(provider: Provider, version: str, staging: Path) -> None:
    """Fail loudly instead of activating a broken layout."""
    entry = provider.spec.entrypoint()
    candidates = provider.entrypoint_candidates(entry.name, version)
    if not any((staging / name).exists() for name in candidates):
        raise InstallError(
            f"archive for {provider.spec.name} {version} has no {entry.name} "
            f"(looked for {', '.join(candidates)})"
        )
