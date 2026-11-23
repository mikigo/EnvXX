from __future__ import annotations

import re

from ..errors import NetworkError, UnsupportedPlatform
from ..versions import version_key
from .base import AppProvider
from .spec import Asset, InstallPlan, ToolSpec, VersionInfo

# Git for Windows publishes an installer, a PortableGit self-extracting exe
# and a MinGit zip. The installer is the one the project's own download page
# points at and the one the user expects; it also registers git in the shell
# the way the upstream project intends, which a hand-unpacked tree does not.
_REPO = "https://api.github.com/repos/git-for-windows/git"
_DOWNLOAD = "https://github.com/git-for-windows/git/releases/download"
_PAGE = 30

GIT_SPEC = ToolSpec(
    name="git",
    kind="app",
    versioned=True,
    summary="Git for Windows installer from git-scm.com",
    selector_prefixes=("git",),
    installer=True,
    checksum="none",
)

# The tag keeps its '.windows.N' suffix: it is part of the identity, not
# noise. v2.56.0.windows.1 and .4 are different builds of the same upstream
# version, and only the full tag says which file to fetch.
_TAG_RE = re.compile(r"^v(?P<version>\d+(?:\.\d+)+\.windows\.\d+)$")

# host arch -> the suffix in the installer name
_ARCH = {"x64": "64-bit", "arm64": "arm64"}


class GitProvider(AppProvider):
    """Git for Windows, fetched as the official installer.

    The installer is left for the user to run: it writes to Program Files,
    adds shell integration and sets up the credential manager, all of which
    are decisions for the person installing, not for envxx.
    """

    spec = GIT_SPEC

    def __init__(self, platform) -> None:
        super().__init__(platform)
        if platform.os != "windows":
            raise UnsupportedPlatform(
                f"git for windows ships Windows builds only, "
                f"not available for {platform.tag}"
            )
        self._arch = _ARCH.get(platform.arch)
        if self._arch is None:
            raise UnsupportedPlatform(f"git has no build for {platform.tag}")

    # -- catalogue -------------------------------------------------------
    def _fetch_versions(self) -> list[VersionInfo]:
        from .. import http

        result: list[VersionInfo] = []
        page = 1
        while True:
            batch = http.get_json(
                f"{_REPO}/releases?per_page={_PAGE}&page={page}",
                f"git-releases-{page}",
            )
            if not isinstance(batch, list):
                raise NetworkError("unexpected git-for-windows releases payload")
            if not batch:
                break

            for release in batch:
                if release.get("prerelease") or release.get("draft"):
                    continue
                match = _TAG_RE.match(str(release.get("tag_name", "")))
                if not match:
                    continue
                version = match.group("version")
                names = {str(a.get("name", "")) for a in release.get("assets") or ()}
                if self._asset_name(version) not in names:
                    continue
                result.append(VersionInfo(version=version))

            if len(batch) < _PAGE:
                break
            page += 1

        if not result:
            raise NetworkError("git-for-windows has no release with an installer")
        return result

    def _asset_name(self, version: str) -> str:
        """Map a tag's version part to the installer's file name.

        The first repackaging of a version drops its number: tag
        'v2.56.0.windows.1' ships 'Git-2.56.0-64-bit.exe', while
        'v2.56.0.windows.4' ships 'Git-2.56.0.4-64-bit.exe'.
        """
        base, _, repack = version.partition(".windows.")
        if repack and repack != "1":
            base = f"{base}.{repack}"
        return f"Git-{base}-{self._arch}.exe"

    def plan(self, version: str) -> InstallPlan:
        name = self._asset_name(version)
        return InstallPlan(
            version=version,
            asset=Asset(
                url=f"{_DOWNLOAD}/v{version}/{name}",
                filename=name,
                # an installer: downloaded and offered to the user, never
                # unpacked and never run by envxx on its own
                format="exe",
            ),
            download_only=True,
        )

    def display_versions(self) -> list[VersionInfo]:
        """One row per upstream version, newest first.

        The repackagings of one version are near-identical, so showing four
        of them hides which upstream versions exist. The grouping key is the
        part before '.windows.', which latest_per_line cannot express because
        the repackaging number is baked into version_key.
        """
        best: dict[str, VersionInfo] = {}
        for info in self.search():
            base = info.version.split(".windows.")[0]
            current = best.get(base)
            if current is None or version_key(info.version) > version_key(
                current.version
            ):
                best[base] = info
        return sorted(
            best.values(), key=lambda info: version_key(info.version), reverse=True
        )
