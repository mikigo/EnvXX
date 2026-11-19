from __future__ import annotations

import re

from ..errors import NetworkError
from .installer import InstallerProvider
from .spec import InstallPlan, ToolSpec, VersionInfo

# 7-Zip has no API; its download page lists the current build's files and the
# version is encoded in their names (7z2606-x64.exe). The page is the only
# place that says which build is current.
_PAGE = "https://7-zip.org/download.html"
_ASSET_RE = re.compile(
    r'href="https://github\.com/ip7z/7zip/releases/download/'
    r'(?P<tag>[\d.]+)/7z(?P<build>\d+)(?P<arch>-x64|-arm64)?\.exe"'
)

ZIP7_SPEC = ToolSpec(
    name="7zip",
    kind="app",
    versioned=True,
    summary="7-Zip installer from 7-zip.org",
    selector_prefixes=("7zip", "7z"),
    installer=True,
    checksum="none",
)

# host arch -> the suffix in the file name. 7-Zip calls the arm64 build
# '-arm64' and leaves the 32-bit one bare, so x64 is '-x64'.
_ARCH_SUFFIX = {"x64": "-x64", "arm64": "-arm64"}


class SevenZipProvider(InstallerProvider):
    """7-Zip, the Windows installer from 7-zip.org.

    The version in the page is a build number ('2606' for 26.06), so it is
    reformatted into dotted form to sort alongside other tools.
    """

    spec = ZIP7_SPEC

    def __init__(self, platform) -> None:
        super().__init__(platform)
        self.require_platform("windows")

    def _page(self) -> dict[str, dict[str, str]]:
        """version -> {arch suffix: download url}, current build only."""
        from .. import http

        text = http.get_text(_PAGE, "7zip-download-page")
        found: dict[str, dict[str, str]] = {}
        for match in _ASSET_RE.finditer(text):
            tag = match.group("tag")
            build = match.group("build")
            version = _build_to_version(build)
            suffix = match.group("arch") or ""
            found.setdefault(version, {})[suffix] = match.group(0).split('"')[1]

        if not found:
            raise NetworkError("could not find a 7-Zip installer on its page")
        return found

    def _fetch_versions(self) -> list[VersionInfo]:
        return [VersionInfo(version=version) for version in self._page()]

    def plan(self, version: str) -> InstallPlan:
        suffix = _ARCH_SUFFIX[self.platform.arch]
        files = self._page().get(version)
        if not files or suffix not in files:
            raise NetworkError(
                f"7-Zip {version} has no {self.platform.arch} installer"
            )
        url = files[suffix]
        name = url.rsplit("/", 1)[-1]
        return self.plan_for(version, url, name)


def _build_to_version(build: str) -> str:
    """'2606' -> '26.06'.

    7-Zip encodes the version without a separator, so the last two digits are
    the minor part. Anything shorter is left alone rather than guessed at.
    """
    if len(build) < 3:
        return build
    return f"{build[:-2]}.{build[-2:]}"
