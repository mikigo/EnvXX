from __future__ import annotations

from ..errors import NetworkError, VersionNotFound
from .base import VersionedProvider, latest_per_line
from .spec import Asset, EntryPoint, InstallPlan, ToolSpec, VersionInfo

# Adoptium publishes a query API in front of the Temurin build farm. The
# feature_releases endpoint takes one major at a time, so the catalogue is
# assembled from the LTS lines plus the newest feature release.
_API = "https://api.adoptium.net/v3"
_PAGE = 50

JDK_SPEC = ToolSpec(
    name="jdk",
    kind="runtime",
    versioned=True,
    summary="Temurin JDK builds from Adoptium",
    selector_prefixes=("jdk", "java", "temurin"),
    entrypoints=(
        # relative to the wrapper directory; macOS inserts Contents/Home below
        EntryPoint("java", "bin/java"),
        EntryPoint("javac", "bin/javac"),
        EntryPoint("jar", "bin/jar"),
    ),
    default_entrypoint="java",
    checksum="api_digest",
)

# host os/arch -> (adoptium os, adoptium architecture)
_ADOPTIUM_PLATFORMS: dict[tuple[str, str], tuple[str, str]] = {
    ("windows", "x64"): ("windows", "x64"),
    ("windows", "arm64"): ("windows", "aarch64"),
    ("linux", "x64"): ("linux", "x64"),
    ("linux", "arm64"): ("linux", "aarch64"),
    ("macos", "x64"): ("mac", "x64"),
    ("macos", "arm64"): ("mac", "aarch64"),
}

# Older LTS lines still get security builds, but offering Java 8 beside 25 is
# noise for a tool whose point is running current software.
_MIN_MAJOR = 17

# used when the availability probe fails, so 'install' still works offline-ish
_FALLBACK_MAJORS = (21, 25)


class JdkProvider(VersionedProvider):
    """Temurin, the Eclipse Adoptium build of OpenJDK."""

    spec = JDK_SPEC

    def __init__(self, platform) -> None:
        super().__init__(platform)
        self._by_version: dict[str, dict] | None = None

    def _os_arch(self) -> tuple[str, str]:
        return _ADOPTIUM_PLATFORMS[(self.platform.os, self.platform.arch)]

    def _majors(self) -> list[int]:
        """LTS lines plus the newest feature release, newest last.

        Walking every available major would mean a request per line; the LTS
        lines and the newest one cover everything a user would ask for.
        """
        from .. import http

        try:
            info = http.get_json(f"{_API}/info/available_releases", "jdk-majors")
        except NetworkError:
            return list(_FALLBACK_MAJORS)

        if not isinstance(info, dict):
            return list(_FALLBACK_MAJORS)

        majors = {int(value) for value in info.get("available_lts_releases") or ()}
        newest = info.get("most_recent_feature_release")
        if isinstance(newest, int):
            majors.add(newest)
        majors = sorted(major for major in majors if major >= _MIN_MAJOR)
        return majors or list(_FALLBACK_MAJORS)

    def _fetch_feature(self, major: int) -> list[dict]:
        from .. import http

        os_name, arch = self._os_arch()
        url = (
            f"{_API}/assets/feature_releases/{major}/ga"
            f"?architecture={arch}&image_type=jdk&os={os_name}"
            f"&project=jdk&page=0&page_size={_PAGE}&sort_order=DESC"
        )
        data = http.get_json(url, f"jdk-{major}-{self.platform.tag}")
        if not isinstance(data, list):
            raise NetworkError("unexpected adoptium feature_releases payload")
        return data

    def _index(self) -> dict[str, dict]:
        """version -> package entry (name, link, checksum, size)."""
        if self._by_version is not None:
            return self._by_version

        index: dict[str, dict] = {}
        builds: dict[str, int] = {}
        for major in self._majors():
            for row in self._fetch_feature(major):
                version = _openjdk_version(row)
                package = _archive_package(row)
                if version is None or package is None:
                    continue
                # one version can come from several builds ('27+35', '27.0.1+1');
                # the highest build number is the newest one
                build = _build_number(row)
                if version in index and build <= builds[version]:
                    continue
                index[version] = package
                builds[version] = build

        if not index:
            raise NetworkError("adoptium returned no jdk builds for this platform")
        self._by_version = index
        return index

    def _fetch_versions(self) -> list[VersionInfo]:
        return [VersionInfo(version=version) for version in self._index()]

    def display_versions(self) -> list[VersionInfo]:
        """One row per major line, newest first: 27, 25, 21, 17.

        Every Adoptium patch release is a full JDK; showing 40 of them hides
        which major lines exist. 'search --all' still lists them.
        """
        return latest_per_line(self.search(), depth=1)

    def plan(self, version: str) -> InstallPlan:
        package = self._index().get(version)
        if package is None:
            raise VersionNotFound(
                f"jdk {version} has no archive build for {self.platform.tag}"
            )

        name = package["name"]
        return InstallPlan(
            version=version,
            asset=Asset(
                url=package["link"],
                filename=name,
                format="zip" if name.endswith(".zip") else "tar.gz",
                sha256=package.get("checksum"),
                size=package.get("size"),
            ),
        )

    def entrypoint_candidates(
        self, name: str, version: str | None = None
    ) -> list[str]:
        """macOS ships a bundle, so the launchers sit under Contents/Home/bin.

        The other two archives put bin/ at the top of the wrapper directory;
        only the bundle layout needs the extra prefix.
        """
        candidates = super().entrypoint_candidates(name, version)
        if self.platform.os != "macos":
            return candidates
        return ["Contents/Home/" + name for name in candidates]


def _openjdk_version(row: dict) -> str | None:
    """'21.0.13+9.0.LTS' -> '21.0.13'; '27.0.1+0' -> '27.0.1'.

    Adoptium's version_data is inconsistent between major lines: the
    human-readable openjdk_version reads '27.0.1.0' for one build and
    '27+35' for another, while the semver field always carries a three-part
    version followed by build metadata. Strip the metadata and that is the
    version worth showing.
    """
    data = row.get("version_data") or {}

    text = str(data.get("semver") or "").strip()
    if text:
        core = text.split("+", 1)[0].strip()
        if core:
            return core

    # older payloads predate semver; the name is the only source then
    legacy = str(data.get("openjdk_version") or "").strip()
    if not legacy:
        return None
    return legacy.split("+", 1)[0].split("-", 1)[0].strip() or None


def _build_number(row: dict) -> int:
    try:
        return int((row.get("version_data") or {}).get("build") or 0)
    except (TypeError, ValueError):
        return 0


def _archive_package(row: dict) -> dict | None:
    """The portable archive for this platform, never the installer.

    Each row carries every matching binary; 'package' is the .zip/.tar.gz and
    'installer' is the .msi/.pkg, which EnvXX has no business running.
    """
    for binary in row.get("binaries") or ():
        if binary.get("image_type") != "jdk":
            continue
        package = binary.get("package")
        if isinstance(package, dict) and package.get("link") and package.get("name"):
            return package
    return None
