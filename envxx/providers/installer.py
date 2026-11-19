from __future__ import annotations

from ..errors import UnsupportedPlatform
from .base import AppProvider
from .spec import Asset, InstallPlan

# Every platform gets an installer that its OS knows how to open. These are
# not archives: there is nothing to extract, and running them would install
# software outside the store, which is the opposite of what envxx promises.
_INSTALLER_SUFFIX = {
    "windows": ".exe",
    "macos": ".dmg",
}


class InstallerProvider(AppProvider):
    """Base for tools distributed only as an installer.

    A publisher that ships .exe/.dmg/.deb installs into the system rather than
    yielding a directory of binaries. envxx cannot honour "delete the folder
    to uninstall" for those, so it does the one honest thing: fetch the
    installer, print where it is, and let the user decide.

    Subclasses provide the version catalogue and the download URL. Everything
    about entrypoints is irrelevant and stays unimplemented.
    """

    def plan_for(self, version: str, url: str, filename: str) -> InstallPlan:
        return InstallPlan(
            version=version,
            asset=Asset(url=url, filename=filename, format="exe"),
            download_only=True,
        )

    def require_platform(self, *supported: str) -> None:
        if self.platform.os not in supported:
            raise UnsupportedPlatform(
                f"{self.spec.name} has no installer for {self.platform.tag}"
            )
