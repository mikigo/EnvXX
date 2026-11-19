from __future__ import annotations

import json
import re
from urllib.parse import unquote

from ..errors import NetworkError, VersionNotFound
from .base import VersionedProvider, latest_per_line
from .spec import Asset, EntryPoint, InstallPlan, ToolSpec, VersionInfo

# Astral publishes a flat NDJSON index of every python-build-standalone
# artifact. uv reads the same file (crates/uv-python-managed/fetch-download-
# metadata.py), and it exists because the GitHub release API is a poor fit:
# each release embeds hundreds of assets across platforms, so asking for the
# full catalogue means many megabytes per page and many pages, while this is
# one 20 MB document listing all 500-odd builds with their sha256.
_INDEX = "https://releases.astral.sh/github/versions/main/v1/python-build-standalone.ndjson"

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
    # the index reports a sha256 for every artifact
    checksum="api_digest",
)

# preference order when several variants exist for one version
_VARIANT_ORDER = (
    "install_only",
    "install_only_stripped",
    "shared+install_only",
    "shared+install_only_stripped",
)

_PRERELEASE_RE = re.compile(r"[a-z]")


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

    def _index(self) -> dict[str, list[tuple[int, dict]]]:
        """version -> [(variant rank, artifact)] for this platform.

        Keyed by the bare version ('3.10.22'); the build date is part of the
        artifact URL, not the key, because a version that was rebuilt twice
        is still one installable version as far as the user is concerned.
        """
        if self._by_version is not None:
            return self._by_version

        from .. import http

        text = http.get_text(_INDEX, "python-index")
        index: dict[str, list[tuple[int, dict]]] = {}

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                # one malformed row should not discard the other 500
                continue

            version = str(row.get("version", "")).split("+", 1)[0]
            if not version:
                continue

            for artifact in row.get("artifacts") or ():
                if artifact.get("platform") != self.platform.python_triples[0]:
                    continue
                variant = str(artifact.get("variant", ""))
                if "freethreaded" in variant:
                    continue
                if artifact.get("archive_format") != "tar.gz":
                    continue
                index.setdefault(version, []).append(
                    (_variant_rank(variant), artifact)
                )

        if not index:
            raise NetworkError(
                f"no python-build-standalone builds for {self.platform.tag}"
            )
        self._by_version = index
        return index

    def _fetch_versions(self) -> list[VersionInfo]:
        result = []
        for version in self._index():
            channel = "prerelease" if _PRERELEASE_RE.search(version) else "stable"
            result.append(VersionInfo(version=version, channel=channel))
        # order is set by the base class; only the contents matter here
        return result

    def display_versions(self) -> list[VersionInfo]:
        """One row per minor line, newest first: 3.13, 3.12, 3.11, ...

        The index has every patch of every line back to 3.8, which is far more
        than a search listing can show. 'search --all' still returns them.
        """
        return latest_per_line(self.search(), depth=2)

    def plan(self, version: str) -> InstallPlan:
        candidates = self._index().get(version)
        if not candidates:
            raise VersionNotFound(
                f"python {version} has no build for {self.platform.tag}"
            )
        _, artifact = min(candidates, key=lambda item: item[0])

        url = str(artifact["url"])
        # the URL percent-encodes the '+' between version and build date
        name = unquote(url.rsplit("/", 1)[-1].split("?")[0])
        return InstallPlan(
            version=version,
            asset=Asset(
                url=url,
                filename=unquote(name),
                format="tar.gz",
                sha256=artifact.get("sha256"),
            ),
        )

    def entrypoint_candidates(
        self, name: str, version: str | None = None
    ) -> list[str]:
        """Windows keeps launchers at the root; POSIX uses bin/ with pip3 naming."""
        entry = self.spec.entrypoint(name)
        if self.platform.os == "windows":
            if entry.kind == "cmd":
                return ["Scripts/pip.exe", "Scripts/pip3.exe", "Scripts/pip"]
            return ["python.exe", "python"]
        if entry.kind == "cmd":
            return ["bin/pip3", "bin/pip"]
        return ["bin/python3", "bin/python"]


def _variant_rank(variant: str) -> int:
    try:
        return _VARIANT_ORDER.index(variant)
    except ValueError:
        return len(_VARIANT_ORDER)
