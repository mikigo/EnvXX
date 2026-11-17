from __future__ import annotations

import re

from ..errors import NetworkError
from .base import VersionedProvider, latest_per_line
from .spec import Asset, EntryPoint, InstallPlan, ToolSpec, VersionInfo

# bun tags read 'bun-v1.4.4'; the version is the part after 'bun-v'.
_REPO = "https://api.github.com/repos/oven-sh/bun"
_PAGE = 100

BUN_SPEC = ToolSpec(
    name="bun",
    kind="runtime",
    versioned=True,
    summary="Bun JavaScript runtime from GitHub releases",
    selector_prefixes=("bun",),
    entrypoints=(
        # the standalone zip carries bun.exe only; 'bunx' is a symlink that
        # only npm installs create, so 'envxx bun 1.4.4 x <pkg>' is the way
        EntryPoint("bun", "bun"),
    ),
    default_entrypoint="bun",
    checksum="shasums_file",
)

# host os/arch -> (asset os token, asset arch token)
_BUN_ASSETS: dict[tuple[str, str], tuple[str, str]] = {
    ("windows", "x64"): ("windows", "x64"),
    ("windows", "arm64"): ("windows", "aarch64"),
    ("linux", "x64"): ("linux", "x64"),
    ("linux", "arm64"): ("linux", "aarch64"),
    ("macos", "x64"): ("darwin", "x64"),
    ("macos", "arm64"): ("darwin", "aarch64"),
}

_TAG_RE = re.compile(r"^bun-v(?P<version>\d+(?:\.\d+)+)$")


class BunProvider(VersionedProvider):
    """Bun, from the official GitHub release zips.

    The zips hold one versioned directory per platform
    ('bun-windows-x64/bun.exe'), so the install strips that wrapper.
    """

    spec = BUN_SPEC

    def _fetch_versions(self) -> list[VersionInfo]:
        from .. import http

        versions: list[str] = []
        page = 1
        while True:
            batch = http.get_json(
                f"{_REPO}/tags?per_page={_PAGE}&page={page}",
                f"bun-tags-{page}",
            )
            if not isinstance(batch, list):
                raise NetworkError("unexpected bun tags payload")
            if not batch:
                break

            for tag in batch:
                match = _TAG_RE.match(str(tag.get("name", "")))
                if match:
                    versions.append(match.group("version"))

            if len(batch) < _PAGE:
                break
            page += 1

        if not versions:
            raise NetworkError("bun has no tagged releases")

        return [VersionInfo(version=version) for version in versions]

    def display_versions(self) -> list[VersionInfo]:
        """One row per minor line, newest first: 1.4, 1.3, 1.2, ..."""
        return latest_per_line(self.search(), depth=2)

    def _asset_name(self, version: str) -> str:
        os_token, arch_token = _BUN_ASSETS[(self.platform.os, self.platform.arch)]
        return f"bun-{os_token}-{arch_token}.zip"

    def plan(self, version: str) -> InstallPlan:
        tag = f"bun-v{version}"
        name = self._asset_name(version)
        base = "https://github.com/oven-sh/bun/releases/download"
        return InstallPlan(
            version=version,
            asset=Asset(
                url=f"{base}/{tag}/{name}",
                filename=name,
                format="zip",
                # one digest list covers every asset of the release
                sha256_url=f"{base}/{tag}/SHASUMS256.txt",
                sha256_filename=name,
            ),
        )

    def entrypoint_candidates(
        self, name: str, version: str | None = None
    ) -> list[str]:
        """The wrapper directory is stripped, leaving the binaries at the root."""
        entry = self.spec.entrypoint(name)
        if self.platform.os == "windows":
            return [entry.relpath + ".exe", entry.relpath]
        return [entry.relpath]
