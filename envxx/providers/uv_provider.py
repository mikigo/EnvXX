from __future__ import annotations

import re

from ..errors import NetworkError
from .base import VersionedProvider, latest_per_line
from .spec import Asset, EntryPoint, InstallPlan, ToolSpec, VersionInfo

# uv releases are tagged without a prefix ('0.13.8'), which makes the tags
# endpoint usable directly as the catalogue.
_REPO = "https://api.github.com/repos/astral-sh/uv"
_DOWNLOAD = "https://github.com/astral-sh/uv/releases/download"
_PAGE = 100

UV_SPEC = ToolSpec(
    name="uv",
    kind="runtime",
    versioned=True,
    summary="uv, the Python package manager and resolver",
    selector_prefixes=("uv",),
    # uv, uvx and uvw ship side by side in the same archive
    entrypoints=(
        EntryPoint("uv", "uv"),
        EntryPoint("uvx", "uvx"),
    ),
    default_entrypoint="uv",
    checksum="shasums_file",
)

# host os/arch -> rust target triple, as spelled in uv asset names
_UV_ASSETS: dict[tuple[str, str], str] = {
    ("windows", "x64"): "x86_64-pc-windows-msvc",
    ("windows", "arm64"): "aarch64-pc-windows-msvc",
    ("linux", "x64"): "x86_64-unknown-linux-gnu",
    ("linux", "arm64"): "aarch64-unknown-linux-gnu",
    ("macos", "x64"): "x86_64-apple-darwin",
    ("macos", "arm64"): "aarch64-apple-darwin",
}

_VERSION_RE = re.compile(r"^\d+(?:\.\d+)+$")


class UvProvider(VersionedProvider):
    """uv, from its GitHub release archives.

    The archives hold the binaries at the top level with no wrapper
    directory, so installs must not strip a leading path.
    """

    spec = UV_SPEC

    def _fetch_versions(self) -> list[VersionInfo]:
        from .. import http

        versions: list[str] = []
        page = 1
        while True:
            batch = http.get_json(
                f"{_REPO}/tags?per_page={_PAGE}&page={page}",
                f"uv-tags-{page}",
            )
            if not isinstance(batch, list):
                raise NetworkError("unexpected uv tags payload")
            if not batch:
                break

            for tag in batch:
                name = str(tag.get("name", ""))
                if _VERSION_RE.match(name):
                    versions.append(name)

            if len(batch) < _PAGE:
                break
            page += 1

        if not versions:
            raise NetworkError("uv has no tagged releases")

        return [VersionInfo(version=version) for version in versions]

    def display_versions(self) -> list[VersionInfo]:
        """One row per minor line, newest first: 0.13, 0.12, 0.11, ...

        uv cuts a release most weeks; the full history is hundreds of rows and
        only the newest patch of a line is worth installing.
        """
        return latest_per_line(self.search(), depth=2)

    def _asset_name(self, version: str) -> str:
        triple = _UV_ASSETS[(self.platform.os, self.platform.arch)]
        # Windows ships a zip, everything else a tarball
        suffix = ".zip" if self.platform.os == "windows" else ".tar.gz"
        return f"uv-{triple}{suffix}"

    def plan(self, version: str) -> InstallPlan:
        name = self._asset_name(version)
        return InstallPlan(
            version=version,
            asset=Asset(
                url=f"{_DOWNLOAD}/{version}/{name}",
                filename=name,
                format="zip" if name.endswith(".zip") else "tar.gz",
                # every asset has a '<name>.sha256' beside it holding the digest
                sha256_url=f"{_DOWNLOAD}/{version}/{name}.sha256",
            ),
            strip_top=False,
        )

    def entrypoint_candidates(
        self, name: str, version: str | None = None
    ) -> list[str]:
        """Binaries sit at the archive root; Windows only adds .exe."""
        entry = self.spec.entrypoint(name)
        if self.platform.os == "windows":
            return [entry.relpath + ".exe"]
        return [entry.relpath]
