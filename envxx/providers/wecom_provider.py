from __future__ import annotations

import re

from ..errors import NetworkError
from .installer import InstallerProvider
from .spec import InstallPlan, ToolSpec, VersionInfo

# WeCom has no published version list either. Its download page links a
# stable redirect endpoint that answers with a 302 to the current build, and
# the file name in that Location header carries the version.
_REDIRECT = "https://work.weixin.qq.com/wework_admin/commdownload?platform={}"
_LOCATION_RE = re.compile(r"WeCom_(?P<version>\d+(?:\.\d+)+)[_.]")

WECOM_SPEC = ToolSpec(
    name="wecom",
    kind="app",
    versioned=True,
    summary="WeCom (enterprise WeChat) installer for Windows",
    selector_prefixes=("wecom", "wechatwork"),
    installer=True,
    checksum="none",
)

# host os/arch -> the platform token the redirect endpoint expects
_PLATFORMS = {
    ("windows", "x64"): "win",
    ("windows", "arm64"): "win",
    ("macos", "x64"): "mac",
    ("macos", "arm64"): "mac_arm64",
}

_EXT = {"windows": ".exe", "macos": ".dmg"}


class WecomProvider(InstallerProvider):
    """WeCom, from the redirect endpoint on work.weixin.qq.com.

    The endpoint only ever points at the newest build for a platform, so the
    catalogue has exactly one entry, like WeChat. Older builds are not
    reachable by a guessable URL.
    """

    spec = WECOM_SPEC

    def __init__(self, platform) -> None:
        super().__init__(platform)
        self.require_platform("windows", "macos")
        self._platform_token = _PLATFORMS[(platform.os, platform.arch)]

    def _resolve(self) -> tuple[str, str]:
        """(version, final download URL) for the current build."""
        from .. import http

        url = _REDIRECT.format(self._platform_token)
        target = http.redirect_target(url)
        match = _LOCATION_RE.search(target)
        if not match:
            raise NetworkError(
                f"could not read a WeCom version from {target}"
            )
        return match.group("version"), target

    def _fetch_versions(self) -> list[VersionInfo]:
        version, _ = self._resolve()
        return [VersionInfo(version=version)]

    def plan(self, version: str) -> InstallPlan:
        resolved_version, url = self._resolve()
        # plan() is only ever asked for a version the catalogue offered; if
        # upstream moved on between the two calls, follow the redirect
        if resolved_version != version:
            version = resolved_version
        name = url.rsplit("/", 1)[-1].split("?")[0]
        return self.plan_for(version, url, name)
