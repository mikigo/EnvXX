from __future__ import annotations

import re

from ..errors import NetworkError, UnsupportedPlatform, VersionNotFound
from ..versions import best_match, version_key
from .base import AppProvider
from .spec import Asset, EntryPoint, InstallPlan, ToolSpec, VersionInfo

# Only the current and the previous stable build are linked from the page, and
# the download prefix (2662026100713843) is an opaque build id rather than
# something derivable from the version, so the URL has to be scraped.
_PAGE = "https://mobaxterm.mobatek.net/download-home-edition.html"

MOBAXTERM_SPEC = ToolSpec(
    name="xterm",
    kind="app",
    versioned=True,
    summary="MobaXterm portable, Windows only",
    selector_prefixes=("xterm",),
    # the binary name carries the version; '{version}' is filled in on lookup
    entrypoints=(EntryPoint("xterm", "MobaXterm_Personal_{version}"),),
    default_entrypoint="xterm",
    # mobatek publishes neither a checksum file nor an API with digests
    checksum="none",
)

_PORTABLE_RE = re.compile(
    r"https://download\.mobatek\.net/\d+/MobaXterm_Portable_v(?P<version>\d+(?:\.\d+)+)\.zip"
)
_VERSION_LINE_RE = re.compile(
    r'<p class="version_titre">Version (?P<version>\d+(?:\.\d+)+) \((?P<date>[0-9-]+)\)</p>'
)


class MobaXtermProvider(AppProvider):
    """MobaXterm Home Edition, the portable zip from mobatek.net."""

    spec = MOBAXTERM_SPEC

    def __init__(self, platform) -> None:
        super().__init__(platform)
        # Mobatek only publishes Windows builds
        if platform.os != "windows":
            raise UnsupportedPlatform(
                f"xterm is a Windows application, not available for {platform.tag}"
            )

    # -- catalogue -------------------------------------------------------
    def _page(self) -> tuple[dict[str, str], dict[str, str]]:
        """(version -> download url, version -> release date) from the page."""
        from .. import http

        text = http.get_text(_PAGE, "mobaxterm-download-page")
        urls = {match.group("version"): match.group(0) for match in _PORTABLE_RE.finditer(text)}
        dates = {
            match.group("version"): match.group("date")
            for match in _VERSION_LINE_RE.finditer(text)
        }
        if not urls:
            raise NetworkError("could not find a MobaXterm portable download")
        return urls, dates

    def _fetch_versions(self) -> list[VersionInfo]:
        """Every version from the changelog, marked by whether it is linked.

        The changelog carries the full history with dates; only the two newest
        builds have a download URL, so the rest are listed as archived.
        """
        urls, dates = self._page()
        infos = [
            VersionInfo(
                version=version,
                channel="stable" if version in urls else "archived",
                released=dates.get(version),
            )
            for version in set(urls) | set(dates)
        ]
        infos.sort(key=lambda info: version_key(info.version), reverse=True)
        return infos

    def display_versions(self) -> list[VersionInfo]:
        """Ascending, matching the runtime tools' search ordering."""
        return sorted(self.search(), key=lambda info: version_key(info.version))

    def channels(self) -> list[VersionInfo]:
        return self.search()

    def resolve(self, query: str | None) -> str:
        """Only the builds the page links can actually be downloaded."""
        urls, _ = self._page()
        downloadable = sorted(urls, key=version_key)
        if query is None:
            return downloadable[-1]

        match = best_match(downloadable, query)
        if match is None:
            raise VersionNotFound(
                f"xterm {query} cannot be downloaded: mobatek.net links only "
                f"{', '.join(reversed(downloadable))}"
            )
        return match

    def default_version(self) -> str:
        """The changelog lists versions that are no longer downloadable."""
        return self.resolve(None)

    # -- install ---------------------------------------------------------
    def plan(self, version: str) -> InstallPlan:
        urls, _ = self._page()
        url = urls.get(version)
        if url is None:
            raise VersionNotFound(f"xterm {version} has no download link")

        return InstallPlan(
            version=version,
            asset=Asset(
                url=url,
                filename=url.rsplit("/", 1)[-1],
                format="zip",
            ),
            # the zip holds the .exe and its plugins at the root
            strip_top=False,
        )
