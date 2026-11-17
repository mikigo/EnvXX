from __future__ import annotations

from ..errors import NetworkError, VersionNotFound
from .base import VersionedProvider, latest_per_line
from .spec import Asset, EntryPoint, InstallPlan, ToolSpec, VersionInfo

# go.dev serves the release manifest directly; dl.google.com carries the files.
_DL = "https://dl.google.com/go"
_MANIFEST = "https://go.dev/dl/?mode=json&include=all"

GO_SPEC = ToolSpec(
    name="go",
    kind="runtime",
    versioned=True,
    summary="Go toolchain from go.dev",
    selector_prefixes=("go", "golang"),
    entrypoints=(
        EntryPoint("go", "bin/go"),
        EntryPoint("gofmt", "bin/gofmt"),
    ),
    default_entrypoint="go",
    checksum="api_digest",
)

# host os/arch -> (manifest os, manifest arch)
_GO_PLATFORMS: dict[tuple[str, str], tuple[str, str]] = {
    ("windows", "x64"): ("windows", "amd64"),
    ("windows", "arm64"): ("windows", "arm64"),
    ("linux", "x64"): ("linux", "amd64"),
    ("linux", "arm64"): ("linux", "arm64"),
    ("macos", "x64"): ("darwin", "amd64"),
    ("macos", "arm64"): ("darwin", "arm64"),
}


def _tag_to_version(version: str) -> str:
    return version.removeprefix("go").removeprefix("v")


class GoProvider(VersionedProvider):
    """Go, the language toolchain.

    The manifest lists every release with a digest per file, which is why this
    provider needs no checksum sidecar: the sha256 arrives with the catalogue.
    """

    spec = GO_SPEC

    def __init__(self, platform) -> None:
        super().__init__(platform)
        self._files: dict[str, dict] | None = None

    def _index(self) -> dict[str, dict]:
        """version -> {filename, size, sha256} for this platform's archive."""
        if self._files is not None:
            return self._files

        from .. import http

        data = http.get_json(_MANIFEST, "go-index")
        if not isinstance(data, list):
            raise NetworkError("unexpected go.dev manifest payload")

        os_name, arch = _GO_PLATFORMS[(self.platform.os, self.platform.arch)]
        index: dict[str, dict] = {}
        for release in data:
            version = _tag_to_version(str(release.get("version", "")))
            if not version:
                continue
            for entry in release.get("files") or ():
                if entry.get("kind") != "archive":
                    continue
                if entry.get("os") != os_name or entry.get("arch") != arch:
                    continue
                index[version] = entry
                break
        self._files = index
        return index

    def _fetch_versions(self) -> list[VersionInfo]:
        return [
            VersionInfo(
                version=version,
                channel="prerelease" if any(c.isalpha() for c in version) else "stable",
            )
            for version in self._index()
        ]

    def display_versions(self) -> list[VersionInfo]:
        """One row per minor line, newest first: 1.27, 1.26, 1.25, ...

        Go keeps a patch release per line for a long time; listing all of them
        buries the newest under hundreds of rows nobody asks for.
        """
        return latest_per_line(self.search(), depth=2)

    def plan(self, version: str) -> InstallPlan:
        entry = self._index().get(version)
        if not entry:
            raise VersionNotFound(f"go {version} has no build for {self.platform.tag}")

        name = entry["filename"]
        return InstallPlan(
            version=version,
            asset=Asset(
                url=f"{_DL}/{name}",
                filename=name,
                format="zip" if name.endswith(".zip") else "tar.gz",
                sha256=entry.get("sha256"),
                size=entry.get("size"),
            ),
        )

    def entrypoint_candidates(
        self, name: str, version: str | None = None
    ) -> list[str]:
        """Both archive flavours use go/bin/; Windows only adds the suffix."""
        entry = self.spec.entrypoint(name)
        if self.platform.os == "windows":
            return [entry.relpath + ".exe", entry.relpath]
        return [entry.relpath]
