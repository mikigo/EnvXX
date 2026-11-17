from __future__ import annotations

import re

from ..errors import NetworkError, VersionNotFound
from .base import VersionedProvider
from .spec import Asset, EntryPoint, InstallPlan, ToolSpec, VersionInfo

_RELEASES = "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"

PYTHON_SPEC = ToolSpec(
    name="python",
    kind="runtime",
    versioned=True,
    summary="CPython builds from python-build-standalone",
    selector_prefixes=("python", "py"),
    entrypoints=(
        EntryPoint("python", "python"),
        # install_only archives ship pip as a module, not a launcher script
        EntryPoint("pip", "pip", kind="cmd", module="pip"),
    ),
    default_entrypoint="python",
    # 'pip install -e .' leaves envxx.exe in Scripts/ (bin/ on Unix), and a
    # user expects 'envxx python3.11 envxx' to find it without a spec entry
    script_dirs=("Scripts", "bin"),
    checksum="api_digest",
)

# cpython-3.11.18+20261110-x86_64-pc-windows-msvc-install_only.tar.gz
# The triple is matched against the platform list rather than with a fixed
# pattern: it has 3-4 dash-separated parts and variants contain dashes too.
_ASSET_RE = re.compile(
    r"^cpython-(?P<version>\d+\.\d+\.\d+(?:[a-z]+\d+)?)"
    r"\+(?P<build>\d+)"
    r"-(?P<rest>.+)\.tar\.gz$"
)

# preference order when several variants exist for one triple
_VARIANT_ORDER = (
    "install_only",
    "install_only_stripped",
    "shared-install_only",
    "shared-install_only_stripped",
)

_PRERELEASE_RE = re.compile(r"[a-z]")


def _split_triple(rest: str, triples: tuple[str, ...]) -> tuple[str, str] | None:
    """Split '<triple>-<variant>' using the known platform triples."""
    for triple in sorted(triples, key=len, reverse=True):
        if rest.startswith(triple + "-"):
            return triple, rest[len(triple) + 1 :]
    return None


def _variant_rank(variant: str) -> int:
    try:
        return _VARIANT_ORDER.index(variant)
    except ValueError:
        return len(_VARIANT_ORDER)


class PythonProvider(VersionedProvider):
    spec = PYTHON_SPEC

    def __init__(self, platform) -> None:
        super().__init__(platform)
        self._by_version: dict[str, list[tuple[int, dict]]] | None = None
        self._released: str | None = None

    def _index(self) -> dict[str, list[tuple[int, dict]]]:
        """version -> [(variant rank, asset)] for this platform, non-freethreaded."""
        if self._by_version is not None:
            return self._by_version

        from .. import http

        data = http.get_json(_RELEASES, "python-index")
        assets = data.get("assets") if isinstance(data, dict) else None
        if not isinstance(assets, list):
            raise NetworkError("unexpected python-build-standalone payload")

        if data.get("published_at"):
            self._released = str(data["published_at"])[:10]

        triples = set(self.platform.python_triples)
        index: dict[str, list[tuple[int, dict]]] = {}
        for asset in assets:
            match = _ASSET_RE.match(asset.get("name", ""))
            if not match:
                continue
            split = _split_triple(match.group("rest"), triples)
            if split is None:
                continue
            variant = split[1]
            if "freethreaded" in variant:
                continue
            index.setdefault(match.group("version"), []).append(
                (_variant_rank(variant), asset)
            )
        self._by_version = index
        return index

    def _fetch_versions(self) -> list[VersionInfo]:
        result = []
        for version in self._index():
            channel = "prerelease" if _PRERELEASE_RE.search(version) else "stable"
            result.append(
                VersionInfo(version=version, channel=channel, released=self._released)
            )
        # order is set by the base class; only the contents matter here
        return result

    def plan(self, version: str) -> InstallPlan:
        candidates = self._index().get(version)
        if not candidates:
            raise VersionNotFound(
                f"python {version} has no build for {self.platform.tag}"
            )
        _, asset = min(candidates, key=lambda item: item[0])

        digest = asset.get("digest") or ""
        sha256 = digest.split(":", 1)[1] if digest.startswith("sha256:") else None

        return InstallPlan(
            version=version,
            asset=Asset(
                url=asset["browser_download_url"],
                filename=asset["name"],
                format="tar.gz",
                sha256=sha256,
                size=asset.get("size"),
            ),
        )

    def entrypoint_candidates(
        self, name: str, version: str | None = None
    ) -> list[str]:
        """Windows keeps launchers at the root, POSIX uses bin/ with pip3 naming."""
        entry = self.spec.entrypoint(name)
        if self.platform.os == "windows":
            if entry.kind == "cmd":
                return ["Scripts/pip.exe", "Scripts/pip3.exe", "Scripts/pip"]
            return ["python.exe", "python"]
        if entry.kind == "cmd":
            return ["bin/pip3", "bin/pip", "bin/pip3.11"]
        return ["bin/python3", "bin/python"]
