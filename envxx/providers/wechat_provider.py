from __future__ import annotations

import re

from ..errors import NetworkError
from .installer import InstallerProvider
from .spec import InstallPlan, ToolSpec, VersionInfo

# Tencent serves the desktop build from a CDN and puts the version in the
# file name (WeChatWin_4.2.0.exe). The landing page links the current build,
# so that is the only source for the version.
_PAGE = "https://pc.weixin.qq.com/"
_DOWNLOAD_RE = re.compile(
    r"https://dldir\d*v\d*\.qq\.com/weixin/Universal/Windows/"
    r"WeChatWin_(?P<version>\d+(?:\.\d+)+)\.exe"
)

WECHAT_SPEC = ToolSpec(
    name="wechat",
    kind="app",
    versioned=True,
    summary="WeChat desktop installer for Windows",
    selector_prefixes=("wechat", "weixin"),
    installer=True,
    checksum="none",
)


class WechatProvider(InstallerProvider):
    """WeChat, the Windows desktop installer from pc.weixin.qq.com.

    Tencent publishes no version history and no API: the landing page names
    one build, and that is what the catalogue contains. Pinning an older
    version would mean guessing a CDN path that may not exist, so only the
    current build is offered.
    """

    spec = WECHAT_SPEC

    def __init__(self, platform) -> None:
        super().__init__(platform)
        self.require_platform("windows")

    def _fetch_versions(self) -> list[VersionInfo]:
        from .. import http

        text = http.get_text(_PAGE, "wechat-download-page")
        match = _DOWNLOAD_RE.search(text)
        if not match:
            raise NetworkError("could not find the WeChat installer on its page")
        return [VersionInfo(version=match.group("version"))]

    def plan(self, version: str) -> InstallPlan:
        name = f"WeChatWin_{version}.exe"
        url = (
            "https://dldir1v6.qq.com/weixin/Universal/Windows/"
            f"{name}"
        )
        return self.plan_for(version, url, name)
