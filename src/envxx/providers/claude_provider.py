from __future__ import annotations

import re
import urllib.parse

from ..errors import NetworkError, VersionNotFound
from ..versions import version_key
from .base import AppProvider
from .spec import Asset, EntryPoint, InstallPlan, ToolSpec, VersionInfo

# Open VSX mirrors the Microsoft marketplace and, unlike it, exposes a plain
# REST API with per-platform builds and a separate .sha256 file.
_API = "https://open-vsx.org/api"
_NAMESPACE = "anthropic"
_NAME = "claude-code"

CLAUDE_SPEC = ToolSpec(
    name="claude",
    kind="app",
    versioned=True,
    summary="Claude Code, unpacked from the Open VSX VSIX",
    selector_prefixes=("claude",),
    entrypoints=(EntryPoint("claude", "resources/native-binary/claude"),),
    default_entrypoint="claude",
    checksum="sha256_file",
)

_PAGE = 100


class ClaudeProvider(AppProvider):
    """Claude Code CLI, taken from the VSCode extension's bundled binary."""

    spec = CLAUDE_SPEC

    def _base(self) -> str:
        platform = self.platform.vsix_platform
        return f"{_API}/{_NAMESPACE}/{_NAME}/{platform}"

    # -- catalogue -------------------------------------------------------
    def _fetch_versions(self) -> list[VersionInfo]:
        """Walk every page of the version list (280+ entries and counting)."""
        from .. import http

        versions: list[str] = []
        offset = 0
        total = 1
        while offset < total:
            url = f"{self._base()}/versions?size={_PAGE}&offset={offset}"
            data = http.get_json(url, f"claude-versions-{self.platform.vsix_platform}-{offset}")
            if not isinstance(data, dict) or "versions" not in data:
                raise NetworkError("unexpected open-vsx versions payload")
            total = int(data.get("totalSize") or 0)
            page = list(data.get("versions") or {})
            if not page:
                break
            versions.extend(page)
            offset += len(page)

        infos = [
            VersionInfo(version=version, channel="stable")
            for version in versions
            if _is_release(version)
        ]
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

        platform = self.platform.vsix_platform
        meta = http.get_json(
            f"{self._base()}/{version}",
            f"claude-meta-{platform}-{version}",
        )
        if not isinstance(meta, dict):
            raise NetworkError("unexpected open-vsx version payload")

        downloads = meta.get("downloads") or {}
        url = downloads.get(platform)
        if not url:
            raise VersionNotFound(
                f"claude {version} has no build for {platform}"
            )
        filename = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        size = (meta.get("downloadSizes") or {}).get(platform)

        return InstallPlan(
            version=version,
            asset=Asset(
                url=url,
                filename=filename,
                format="zip",
                sha256_url=_sha256_url(url),
                size=size,
            ),
            strip_top=True,
        )

    def entrypoint_candidates(
        self, name: str, version: str | None = None
    ) -> list[str]:
        base = "resources/native-binary/claude"
        if self.platform.os == "windows":
            return [base + ".exe"]
        return [base]


def _is_release(version: str) -> bool:
    """Skip the odd non-semver tag that the gallery sometimes carries."""
    return bool(re.match(r"^\d+\.\d+\.\d+$", version))


def _sha256_url(vsix_url: str) -> str:
    """Open VSX publishes '<name>.vsix' and '<name>.sha256' side by side."""
    if vsix_url.endswith(".vsix"):
        return vsix_url[: -len(".vsix")] + ".sha256"
    return vsix_url + ".sha256"
