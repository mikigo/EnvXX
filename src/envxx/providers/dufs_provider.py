from __future__ import annotations

import re
from pathlib import Path

from .. import store
from ..errors import NetworkError, VersionNotFound
from ..versions import version_key
from .base import AppProvider
from .spec import Asset, EntryPoint, InstallPlan, ToolSpec, VersionInfo

# dufs itself ships as a bare binary; the UI it serves is a separate project.
_REPO = "https://api.github.com/repos/sigoden/dufs"
_PAGE = 100

# A shadcn-styled replacement for dufs's built-in UI. Its release carries a
# ready-built assets.zip (index.html at the root), which is what --assets wants.
_ASSETS_REPO = "mikigo/dufs-shadcn-assets"

DUFS_SPEC = ToolSpec(
    name="dufs",
    kind="app",
    versioned=True,
    selector_prefixes=("dufs",),
    # both the .zip and .tar.gz archives hold the bare binary, no wrapper dir
    entrypoints=(EntryPoint("dufs", "dufs"),),
    default_entrypoint="dufs",
    checksum="api_digest",
)

_TAG_RE = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)$")


def _asset_name(version: str, triple: str, fmt: str) -> str:
    """dufs-v0.47.0-x86_64-pc-windows-msvc.zip.

    Releases before v0.11.0 shipped under the 'duf-' prefix, which is why the
    match falls back to the triple instead of comparing the full name.
    """
    suffix = ".zip" if fmt == "zip" else ".tar.gz"
    return f"dufs-v{version}-{triple}{suffix}"


class DufsProvider(AppProvider):
    """dufs, a Rust static file server, from its GitHub release archives."""

    spec = DUFS_SPEC

    # -- catalogue -------------------------------------------------------
    def _fetch_versions(self) -> list[VersionInfo]:
        """Tags rather than releases: the payload is far smaller.

        One releases page carries every asset of every platform (~65 KB for
        three releases), while the tags endpoint lists the whole history in
        under 30 KB.
        """
        from .. import http

        versions: list[str] = []
        page = 1
        while True:
            batch = http.get_json(
                f"{_REPO}/tags?per_page={_PAGE}&page={page}",
                f"dufs-tags-{page}",
            )
            if not isinstance(batch, list):
                raise NetworkError("unexpected dufs tags payload")
            if not batch:
                break

            for tag in batch:
                match = _TAG_RE.match(tag.get("name", ""))
                if match:
                    versions.append(match.group("version"))

            if len(batch) < _PAGE:
                break
            page += 1

        if not versions:
            raise NetworkError("dufs has no tagged releases")

        infos = [VersionInfo(version=version, channel="stable") for version in versions]
        infos.sort(key=lambda info: version_key(info.version), reverse=True)
        return infos

    def display_versions(self) -> list[VersionInfo]:
        """Ascending, matching the runtime tools' search ordering."""
        return sorted(self.search(), key=lambda info: version_key(info.version))

    def channels(self) -> list[VersionInfo]:
        return self.search()

    # -- install ---------------------------------------------------------
    def plan(self, version: str) -> InstallPlan:
        from .. import http

        data = http.get_json(
            f"{_REPO}/releases/tags/v{version}",
            f"dufs-release-{version}",
            missing_ok=True,
        )
        if not isinstance(data, dict):
            raise VersionNotFound(f"dufs {version} is not released")

        triple = self.platform.dufs_triple
        fmt = self.platform.dufs_format
        wanted = _asset_name(version, triple, fmt)
        assets = data.get("assets") or []
        asset = next((a for a in assets if a.get("name") == wanted), None)
        if asset is None:
            # fall back to the triple so renamed releases still resolve
            asset = next(
                (a for a in assets if a.get("name", "").find(triple) != -1), None
            )
        if asset is None:
            raise VersionNotFound(
                f"dufs {version} has no build for {self.platform.tag}"
            )

        digest = asset.get("digest") or ""
        sha256 = digest.split(":", 1)[1] if digest.startswith("sha256:") else None

        return InstallPlan(
            version=version,
            asset=Asset(
                url=asset["browser_download_url"],
                filename=asset["name"],
                format=fmt,  # type: ignore[arg-type]
                sha256=sha256,
                size=asset.get("size"),
            ),
            # the archive contains dufs[.exe] at its root
            strip_top=False,
        )

    # -- runtime ---------------------------------------------------------
    def augment_args(self, version: str, args: list[str]) -> list[str]:
        """Point dufs at the shadcn UI unless the user chose their own.

        dufs takes '--assets <path>'; both spellings are checked so
        '--assets=dir' is honoured too. Command-line flags win, and DUFS_ASSETS
        in the environment is left alone.
        """
        if any(
            arg == "--assets" or arg.startswith("--assets=") for arg in args
        ):
            return args

        assets = _ensure_assets()
        if assets is None:
            return args
        return ["--assets", str(assets), *args]


def _ensure_assets() -> Path | None:
    """Download the shadcn UI theme once; None when it cannot be fetched.

    A missing theme is not fatal: dufs falls back to its built-in UI. Being
    offline should not turn 'envxx dufs' into an error.
    """
    import shutil

    from .. import archive, http

    target = store.assets_dir("dufs")
    if (target / "index.html").is_file():
        return target

    try:
        release = http.get_json(
            f"https://api.github.com/repos/{_ASSETS_REPO}/releases/latest",
            "dufs-assets-latest",
        )
        if not isinstance(release, dict):
            return None
        asset = next(
            (a for a in release.get("assets") or [] if a.get("name") == "assets.zip"),
            None,
        )
        if asset is None:
            return None

        digest = asset.get("digest") or ""
        sha256 = digest.split(":", 1)[1] if digest.startswith("sha256:") else None
        store.ensure_dirs()
        download = store.downloads_dir() / f"dufs-assets-{release.get('tag_name', 'latest')}.zip"
        if not download.is_file() or (
            sha256 and http.sha256_file(download) != sha256.lower()
        ):
            http.download(
                asset["browser_download_url"],
                download,
                expected=sha256,
                show_progress=True,
            )

        staging = store.temp_dir("dufs")
        try:
            archive.extract(download, staging, strip_top=False)
            if not (staging / "index.html").is_file():
                return None
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            store.activate(staging, target)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
    except Exception:
        # network hiccup, missing release, bad archive: use dufs's own UI
        return None
    return target
