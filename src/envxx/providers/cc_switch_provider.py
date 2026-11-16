from __future__ import annotations

import re

from ..errors import NetworkError, VersionNotFound
from ..versions import version_key
from .base import AppProvider
from .spec import Asset, EntryPoint, InstallPlan, ToolSpec, VersionInfo

# cc-switch publishes portable archives on GitHub only. dl.ccswitch.io mirrors
# the same files under a stable tag path but carries no catalogue, and only
# from v4.0.29 onward, so it is a download mirror at best (see http.py).
_REPO = "https://api.github.com/repos/farion1231/cc-switch"
_PAGE = 100

CC_SWITCH_SPEC = ToolSpec(
    name="cc-switch",
    kind="app",
    versioned=True,
    selector_prefixes=("cc-switch",),
    entrypoints=(EntryPoint("cc-switch", "cc-switch"),),
    default_entrypoint="cc-switch",
    checksum="api_digest",
)

_TAG_RE = re.compile(r"^v(?P<version>\d+(?:\.\d+)+)$")


def _tag_to_version(tag: str) -> str | None:
    match = _TAG_RE.match(tag)
    return match.group("version") if match else None


class CcSwitchProvider(AppProvider):
    """CC Switch, the Claude Code / Codex config switcher desktop app."""

    spec = CC_SWITCH_SPEC

    # -- catalogue -------------------------------------------------------
    def _fetch_versions(self) -> list[VersionInfo]:
        """All tagged releases, newest first.

        The releases endpoint embeds every asset of every platform and weighs
        megabytes per page; the tags endpoint carries the same version list in
        a few tens of kilobytes, so the catalogue comes from there.
        """
        from .. import http

        versions: set[str] = set()
        page = 1
        while True:
            batch = http.get_json(
                f"{_REPO}/tags?per_page={_PAGE}&page={page}",
                f"cc-switch-tags-{page}",
            )
            if not isinstance(batch, list):
                raise NetworkError("unexpected cc-switch tags payload")
            if not batch:
                break

            for tag in batch:
                version = _tag_to_version(tag.get("name", ""))
                if version is not None:
                    versions.add(version)

            if len(batch) < _PAGE:
                break
            page += 1

        if not versions:
            raise NetworkError("cc-switch has no tagged releases")

        infos = [VersionInfo(version=version, channel="stable") for version in versions]
        infos.sort(key=lambda info: version_key(info.version), reverse=True)
        return infos

    def display_versions(self) -> list[VersionInfo]:
        """Ascending, matching the runtime tools' search ordering."""
        return sorted(self.search(), key=lambda info: version_key(info.version))

    def channels(self) -> list[VersionInfo]:
        return self.search()

    # -- install ---------------------------------------------------------
    def _pick_asset(self, assets: list[dict]) -> dict | None:
        """Find this platform's portable archive.

        Asset names changed over time (CC-Switch-Windows-Portable.zip before
        v3.5.0, CC-Switch-v3.5.0-Windows-Portable.zip after), so match on the
        suffix rather than a fixed filename. Installers (.msi/.deb/.rpm) are
        deliberately skipped: only self-contained artifacts are usable here.
        """
        suffix = self.platform.cc_switch_suffix
        for asset in assets:
            name = asset.get("name", "")
            if name.endswith(suffix) and not name.endswith(".sig"):
                return asset
        return None

    def plan(self, version: str) -> InstallPlan:
        from .. import http

        data = http.get_json(
            f"{_REPO}/releases/tags/v{version}",
            f"cc-switch-release-{version}",
            missing_ok=True,
        )
        if not isinstance(data, dict):
            raise VersionNotFound(f"cc-switch {version} is not released")

        asset = self._pick_asset(data.get("assets") or [])
        if asset is None:
            raise VersionNotFound(
                f"cc-switch {version} has no portable build for {self.platform.tag}"
            )

        digest = asset.get("digest") or ""
        sha256 = digest.split(":", 1)[1] if digest.startswith("sha256:") else None

        return InstallPlan(
            version=version,
            asset=Asset(
                url=asset["browser_download_url"],
                filename=asset["name"],
                format=self.platform.cc_switch_format,  # type: ignore[arg-type]
                sha256=sha256,
                size=asset.get("size"),
            ),
            # archives hold the launcher at the root, the macOS build only
            # nests it inside the .app bundle
            strip_top=False,
            # AppImages are single files whose release name carries the version
            single_name=self.platform.cc_switch_single_name,
        )

    def entrypoint_candidates(
        self, name: str, version: str | None = None
    ) -> list[str]:
        launcher = self.platform.cc_switch_launcher
        if self.platform.os == "windows" and not launcher.endswith(".exe"):
            return [launcher, launcher + ".exe"]
        return [launcher]
