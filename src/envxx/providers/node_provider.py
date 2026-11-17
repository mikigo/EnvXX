from __future__ import annotations

from ..errors import NetworkError
from ..versions import version_key
from .base import VersionedProvider, latest_per_line
from .spec import Asset, EntryPoint, InstallPlan, ToolSpec, VersionInfo

_DIST = "https://nodejs.org/dist"
_INDEX = f"{_DIST}/index.json"

# older LTS lines predate the platform builds this tool targets
MIN_MAJOR = 20

NODE_SPEC = ToolSpec(
    name="node",
    kind="runtime",
    versioned=True,
    summary="Node.js releases from nodejs.org",
    selector_prefixes=("node", "nodejs"),
    entrypoints=(
        EntryPoint("node", "node"),
        EntryPoint("npm", "npm", kind="cmd"),
        EntryPoint("npx", "npx", kind="cmd"),
    ),
    default_entrypoint="node",
    checksum="shasums_file",
)


def _latest_per_major(infos: list[VersionInfo]) -> list[VersionInfo]:
    """Keep the highest patch of each major line, newest first."""
    return latest_per_line(infos, depth=1)


class NodeProvider(VersionedProvider):
    spec = NODE_SPEC

    def _fetch_versions(self) -> list[VersionInfo]:
        from .. import http

        data = http.get_json(_INDEX, "node-index")
        if not isinstance(data, list):
            raise NetworkError("unexpected node index payload")

        key = self.platform.node_files_key
        result: list[VersionInfo] = []
        for entry in data:
            if not entry.get("lts"):
                continue
            if key not in entry.get("files", ()):
                continue
            version = entry["version"].lstrip("v")
            major = version_key(version)[:1]
            if not major or major[0] < MIN_MAJOR:
                continue
            result.append(
                VersionInfo(
                    version=version,
                    channel="lts",
                    lts=True,
                    released=entry.get("date"),
                    notes=str(entry.get("lts")),
                )
            )
        # the base class sorts; returning in any order keeps this readable
        return result

    def display_versions(self) -> list[VersionInfo]:
        """One row per major line, newest first: 26, 24, 22, 20."""
        return _latest_per_major(self.search())

    def plan(self, version: str) -> InstallPlan:
        tag = f"v{version}"
        name = f"node-{tag}-{self.platform.node_asset_os}{self.platform.node_archive_ext}"
        return InstallPlan(
            version=version,
            asset=Asset(
                url=f"{_DIST}/{tag}/{name}",
                filename=name,
                format="zip" if name.endswith(".zip") else "tar.gz",
                sha256_url=f"{_DIST}/{tag}/SHASUMS256.txt",
                sha256_filename=name,
            ),
        )

    def entrypoint_candidates(
        self, name: str, version: str | None = None
    ) -> list[str]:
        """Windows archives keep binaries at the root; POSIX archives use bin/."""
        entry = self.spec.entrypoint(name)
        if self.platform.os == "windows":
            if entry.kind == "cmd":
                return [entry.relpath + ".cmd", entry.relpath + ".exe"]
            return [entry.relpath + ".exe"]
        return [f"bin/{entry.relpath}"]
