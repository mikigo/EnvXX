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
    """Install a version and return its directory. No-op if already present."""
    tool = provider.spec.name
    target = store.version_dir(tool, version)
    if target.is_dir():
        return target

    store.ensure_dirs()
    with store.install_lock(tool, version):
        if target.is_dir():  # another process finished while we waited
            return target

        plan = provider.plan(version)
        asset = plan.asset
        if not quiet:
            console.print(f"[dim]installing {tool} {version} ({asset.filename})[/dim]")

        dest = store.downloads_dir() / _cache_name(version, asset.filename)
        expected = _expected_sha256(asset, provider.spec.checksum)
        if dest.is_file() and expected and http.sha256_file(dest) != expected.lower():
            dest.unlink()
        if not dest.is_file():
            http.download(asset.url, dest, expected=expected, show_progress=not quiet)

        staging = store.temp_dir(tool)
        try:
            if asset.format == "exe":
                archive.copy_single(dest, staging, name=plan.single_name)
            else:
                archive.extract(dest, staging, strip_top=plan.strip_top)

            _verify_entrypoints(provider, version, staging)

            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                store.remove_version(tool, version)
            store.activate(staging, target)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    if not quiet:
        try:
            shown = "~/.envxx/" + target.relative_to(store.home()).as_posix()
        except ValueError:
            shown = str(target)
        console.print(f"[green]installed[/green] {tool} {version} -> {shown}")
    return target


def _verify_entrypoints(provider: Provider, version: str, staging: Path) -> None:
    """Fail loudly instead of activating a broken layout."""
    entry = provider.spec.entrypoint()
    candidates = provider.entrypoint_candidates(entry.name, version)
    if not any((staging / name).exists() for name in candidates):
        raise InstallError(
            f"archive for {provider.spec.name} {version} has no {entry.name} "
            f"(looked for {', '.join(candidates)})"
        )
