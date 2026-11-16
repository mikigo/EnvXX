from __future__ import annotations

import re

from ..errors import NetworkError, VersionNotFound
from ..versions import version_key
from .base import AppProvider
from .spec import Asset, EntryPoint, InstallPlan, ToolSpec, VersionInfo

# The project moved from sst/opencode to anomalyco/opencode; the old path
# still redirects, so this URL keeps working either way.
_REPO = "https://api.github.com/repos/sst/opencode"
_FEED = "https://github.com/sst/opencode/releases.atom"
_PAGE = 100

OPENCODE_SPEC = ToolSpec(
    name="opencode",
    kind="app",
    versioned=True,
    selector_prefixes=("opencode",),
    # both archives hold a single binary at the root, no wrapper directory
    entrypoints=(EntryPoint("opencode", "opencode"),),
    default_entrypoint="opencode",
    checksum="api_digest",
)

_TAG_RE = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)$")
_FEED_ID_RE = re.compile(
    r"<id>tag:github\.com,2008:Repository/\d+/(?P<tag>[^<]+)</id>"
)


class OpencodeProvider(AppProvider):
    """opencode CLI, taken straight from the official GitHub release archives."""

    spec = OPENCODE_SPEC

    def __init__(self, platform) -> None:
        super().__init__(platform)
        self._full_catalogue: bool = False

    # -- catalogue -------------------------------------------------------
    def _fetch_versions(self) -> list[VersionInfo]:
        """Recent releases from the public atom feed, whole history on demand.

        The API allows 60 unauthenticated requests per hour and a single
        releases page weighs ~6 MB because every asset of every platform is
        embedded, while this repository has hundreds of releases. The atom
        feed is one small request that does not count against that quota, so
        it serves the default listing; the full history is only walked when
        'search --all' asks for it.
        """
        if self._full_catalogue:
            return self._all_versions()
        return self._recent_versions()

    def _recent_versions(self) -> list[VersionInfo]:
        from .. import http

        text = http.get_text(_FEED, "opencode-releases-feed")
        versions = {
            match.group("tag")[1:]
            for match in _FEED_ID_RE.finditer(text)
            if _TAG_RE.match(match.group("tag"))
        }
        if not versions:
            raise NetworkError("unexpected opencode releases feed")
        infos = [VersionInfo(version=version, channel="stable") for version in versions]
        infos.sort(key=lambda info: version_key(info.version), reverse=True)
        return infos

    def _all_versions(self) -> list[VersionInfo]:
        from .. import http

        versions: set[str] = set()
        page = 1
        while True:
            batch = http.get_json(
                f"{_REPO}/tags?per_page={_PAGE}&page={page}",
                f"opencode-tags-{page}",
            )
            if not isinstance(batch, list):
                raise NetworkError("unexpected opencode tags payload")
            if not batch:
                break

            for tag in batch:
                match = _TAG_RE.match(tag.get("name", ""))
                if match:
                    versions.add(match.group("version"))

            if len(batch) < _PAGE:
                break
            page += 1

        infos = [VersionInfo(version=version, channel="stable") for version in versions]
        infos.sort(key=lambda info: version_key(info.version), reverse=True)
        return infos

    def search_all(self) -> list[VersionInfo]:
        """Whole release history; expensive, so only 'search --all' uses it."""
        self._full_catalogue = True
        self._versions = None
        return self.search()

    def display_versions(self) -> list[VersionInfo]:
        """Ascending, matching the runtime tools' search ordering."""
        return sorted(self.search(), key=lambda info: version_key(info.version))

    def channels(self) -> list[VersionInfo]:
        return self.search()

    # -- install ---------------------------------------------------------
    def plan(self, version: str) -> InstallPlan:
        """Fetch one release's assets directly, skipping catalogue lookups."""
        from .. import http

        data = http.get_json(
            f"{_REPO}/releases/tags/v{version}",
            f"opencode-release-{version}",
            missing_ok=True,
        )
        if not isinstance(data, dict):
            raise VersionNotFound(f"opencode {version} is not released")

        wanted = self.platform.opencode_asset
        asset = next(
            (a for a in data.get("assets") or [] if a.get("name") == wanted),
            None,
        )
        if asset is None:
            raise VersionNotFound(
                f"opencode {version} has no build for {self.platform.tag}"
            )

        digest = asset.get("digest") or ""
        sha256 = digest.split(":", 1)[1] if digest.startswith("sha256:") else None

        return InstallPlan(
            version=version,
            asset=Asset(
                url=asset["browser_download_url"],
                filename=asset["name"],
                format=self.platform.opencode_format,  # type: ignore[arg-type]
                sha256=sha256,
                size=asset.get("size"),
            ),
            # the archives contain the binary itself, not a wrapper folder
            strip_top=False,
        )
