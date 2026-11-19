from __future__ import annotations

import re

from ..errors import NetworkError, UnsupportedPlatform
from .base import AppProvider
from .spec import Asset, EntryPoint, InstallPlan, ToolSpec, VersionInfo

# MarkText is an Electron app published with electron-builder, so every
# platform gets a .zip next to the installer. Linux ships tar.gz instead.
_REPO = "https://api.github.com/repos/marktext/marktext"
_DOWNLOAD = "https://github.com/marktext/marktext/releases/download"
_PAGE = 30

MARKTEXT_SPEC = ToolSpec(
    name="marktext",
    kind="app",
    versioned=True,
    summary="MarkText markdown editor from GitHub releases",
    selector_prefixes=("marktext", "mt"),
    entrypoints=(EntryPoint("marktext", "marktext"),),
    default_entrypoint="marktext",
    # the release carries SHA256SUMS.txt in '<hex>  <name>' form
    checksum="shasums_file",
)

_TAG_RE = re.compile(r"^v(?P<version>\d+(?:\.\d+)+)(?:-rc\.\d+)?$")

# host os/arch -> the token electron-builder puts in the asset name, and the
# archive extension. macOS also has a .zip; Linux does not.
_ASSETS = {
    ("windows", "x64"): ("win-x64", ".zip"),
    ("windows", "arm64"): ("win-arm64", ".zip"),
    ("macos", "x64"): ("mac-x64", ".zip"),
    ("macos", "arm64"): ("mac-arm64", ".zip"),
    ("linux", "x64"): ("linux", ".tar.gz"),
    ("linux", "arm64"): ("linux-arm64", ".tar.gz"),
}


class MarktextProvider(AppProvider):
    """MarkText, the portable archive from marktext/marktext.

    The Windows and macOS zips are flat: marktext.exe and its Electron
    runtime files sit at the archive root, so nothing is stripped. The Linux
    tarball uses the same flat layout.
    """

    spec = MARKTEXT_SPEC

    def __init__(self, platform) -> None:
        super().__init__(platform)
        self._token = _ASSETS.get((platform.os, platform.arch))

    # -- catalogue -------------------------------------------------------
    def _fetch_versions(self) -> list[VersionInfo]:
        """Stable releases only; the v0.24 line is still release candidates."""
        from .. import http

        result: list[VersionInfo] = []
        page = 1
        while True:
            batch = http.get_json(
                f"{_REPO}/releases?per_page={_PAGE}&page={page}",
                f"marktext-releases-{page}",
            )
            if not isinstance(batch, list):
                raise NetworkError("unexpected marktext releases payload")
            if not batch:
                break

            for release in batch:
                if release.get("prerelease") or release.get("draft"):
                    continue
                tag = str(release.get("tag_name", ""))
                match = _TAG_RE.match(tag)
                # the tag regex tolerates an -rc suffix, so filter it here
                if not match or "rc" in tag.lower():
                    continue
                version = match.group("version")
                if self._token is not None:
                    wanted = self._asset_name(version, *self._token)
                    names = {str(a.get("name", "")) for a in release.get("assets") or ()}
                    if wanted not in names:
                        continue
                result.append(
                    VersionInfo(
                        version=version,
                        released=str(release.get("published_at", ""))[:10] or None,
                    )
                )

            if len(batch) < _PAGE:
                break
            page += 1

        if not result:
            raise NetworkError("marktext has no stable releases")
        return result

    @staticmethod
    def _asset_name(version: str, token: str, ext: str) -> str:
        return f"marktext-{token}-{version}{ext}"

    def plan(self, version: str) -> InstallPlan:
        if self._token is None:
            raise UnsupportedPlatform(
                f"marktext has no build for {self.platform.tag}"
            )
        token, ext = self._token
        name = self._asset_name(version, token, ext)
        return InstallPlan(
            version=version,
            asset=Asset(
                url=f"{_DOWNLOAD}/v{version}/{name}",
                filename=name,
                format="zip" if ext == ".zip" else "tar.gz",
                sha256_url=f"{_DOWNLOAD}/v{version}/SHA256SUMS.txt",
                sha256_filename=name,
            ),
            # the archives are flat: marktext.exe sits at the root
            strip_top=False,
        )

    def entrypoint_candidates(
        self, name: str, version: str | None = None
    ) -> list[str]:
        entry = self.spec.entrypoint(name)
        if self.platform.os == "windows":
            return [entry.relpath + ".exe", entry.relpath]
        return [entry.relpath]
