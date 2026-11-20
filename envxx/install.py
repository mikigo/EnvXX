from __future__ import annotations

import shutil
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
    return dest


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
