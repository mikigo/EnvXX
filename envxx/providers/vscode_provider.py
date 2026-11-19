from __future__ import annotations

from ..errors import NetworkError
from .installer import InstallerProvider
from .spec import InstallPlan, ToolSpec, VersionInfo

# Microsoft publishes a version list and a redirect endpoint that always
# serves the newest build for a platform, so no scraping is involved.
_API = "https://update.code.visualstudio.com/api/releases/stable"
_DOWNLOAD = "https://update.code.visualstudio.com"

VSCODE_SPEC = ToolSpec(
    name="vscode",
    kind="app",
    versioned=True,
    summary="Visual Studio Code installer from code.visualstudio.com",
    selector_prefixes=("vscode", "code"),
    installer=True,
    checksum="none",
)

# host os/arch -> the 'latest/<target>/stable' platform token. Windows uses
# the user-scope installer so it does not need an administrator prompt.
_TARGETS = {
    ("windows", "x64"): "win32-x64-user",
    ("windows", "arm64"): "win32-arm64-user",
    ("linux", "x64"): "linux-deb-x64",
    ("linux", "arm64"): "linux-deb-arm64",
    ("macos", "x64"): "darwin",
    ("macos", "arm64"): "darwin-arm64",
}

# the endpoint answers with Content-Disposition naming the file; these are
# the names for the current layout, used when the header is unavailable
_FILENAMES = {
    ("windows", "x64"): "VSCodeUserSetup-x64-{version}.exe",
    ("windows", "arm64"): "VSCodeUserSetup-arm64-{version}.exe",
    ("linux", "x64"): "code_{version}_amd64.deb",
    ("linux", "arm64"): "code_{version}_arm64.deb",
    ("macos", "x64"): "VSCode-darwin.zip",
    ("macos", "arm64"): "VSCode-darwin-arm64.zip",
}


class VscodeProvider(InstallerProvider):
    """VS Code, fetched from its release endpoint.

    macOS gets a .zip even though the site offers a .dmg: the redirect target
    for darwin is already the archive, and handing over a zip keeps the
    downloaded artifact identical across platforms where possible.
    """

    spec = VSCODE_SPEC

    def __init__(self, platform) -> None:
        super().__init__(platform)
        key = (platform.os, platform.arch)
        self._target = _TARGETS[key]

    def _fetch_versions(self) -> list[VersionInfo]:
        from .. import http

        data = http.get_json(_API, "vscode-releases")
        if not isinstance(data, list):
            raise NetworkError("unexpected vscode releases payload")
        return [VersionInfo(version=str(v)) for v in data if _is_version(v)]

    def plan(self, version: str) -> InstallPlan:
        name = _FILENAMES[(self.platform.os, self.platform.arch)].format(
            version=version
        )
        # the endpoint pins a version with '<version>/<target>/stable'
        url = f"{_DOWNLOAD}/{version}/{self._target}/stable"
        return self.plan_for(version, url, name)


def _is_version(value: object) -> bool:
    parts = str(value).split(".")
    return len(parts) >= 2 and all(part.isdigit() for part in parts)
