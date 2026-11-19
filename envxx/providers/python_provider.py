from __future__ import annotations

import re

from ..errors import NetworkError, VersionNotFound
from ..versions import version_key
from .base import VersionedProvider
from .spec import Asset, EntryPoint, InstallPlan, ToolSpec, VersionInfo

_RELEASES = "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"

# Older versions are no longer rebuilt by newer releases: 3.8/3.9/3.10 stopped
# appearing once upstream dropped them, and their last builds sit in a
# date-tagged release further back. Walking that history costs a few MB per
# page, so it happens only when a query actually asks for a version the newest
# release does not carry.
_RELEASES_PAGE = "https://api.github.com/repos/astral-sh/python-build-standalone/releases"
# Each release lists several hundred platform assets, so one page is a few
# megabytes and can take a minute on a slow link. Smaller pages keep a single
# failed request from costing the whole hunt.
_HISTORY_PAGE = 5
# how far back to walk when hunting a dropped version line
_HISTORY_LIMIT = 120

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
        # versions found by walking the release history, keyed like the index
        self._history: dict[str, list[tuple[int, dict]]] = {}

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

        self._by_version = self._assets_to_index(assets)
        return self._by_version

    def _assets_to_index(self, assets: list[dict]) -> dict[str, list[tuple[int, dict]]]:
        """Keep the assets for this platform, skipping freethreaded variants."""
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

    # -- older releases --------------------------------------------------
    def _load_history(self, wanted_line: tuple[int, ...]) -> None:
        """Walk old releases until one carries `wanted_line`'s last build.

        Upstream stops rebuilding a version line once it goes out of support,
        so 3.8/3.9/3.10 live only in older date-tagged releases. Each page is
        a few MB of assets, which is why this runs only when a query actually
        asks for a missing line and not on every 'search'.

        Stops at the first release that carries the line: that release holds
        the newest build of it, and anything further back is older still.
        """
        from .. import http

        line_len = len(wanted_line)
        seen = 0
        page = 1
        while seen < _HISTORY_LIMIT:
            try:
                batch = http.get_json(
                    f"{_RELEASES_PAGE}?per_page={_HISTORY_PAGE}&page={page}",
                    f"python-history-{page}",
                )
            except NetworkError:
                # one unreachable page should not sink the hunt; the caller
                # reports VersionNotFound if the rest never mentions the line
                return
            if not isinstance(batch, list):
                raise NetworkError("unexpected python-build-standalone history")
            if not batch:
                return

            for release in batch:
                assets = release.get("assets")
                if not isinstance(assets, list):
                    continue
                index = self._assets_to_index(assets)
                if not index:
                    continue

                hit = [
                    version
                    for version in index
                    if version_key(version)[:line_len] == wanted_line
                ]
                if hit:
                    # keep the newest build of the line found in this release
                    best = max(hit, key=version_key)
                    self._history[best] = index[best]
                    return

            seen += len(batch)
            if len(batch) < _HISTORY_PAGE:
                return
            page += 1

    def _find_older(self, query: str) -> str | None:
        """The newest build matching `query`, read from the release history."""
        wanted = version_key(query)
        if not wanted:
            return None

        def matches() -> list[str]:
            return [
                version
                for version in self._history
                if version_key(version)[: len(wanted)] == wanted
            ]

        found = matches()
        if not found:
            self._load_history(wanted)
            found = matches()
        return max(found, key=version_key) if found else None

    def resolve(self, query: str | None) -> str:
        try:
            return super().resolve(query)
        except VersionNotFound:
            if not query:
                raise
            # only a missing version line is worth the cost of reading
            # history; a typo or an unbuildable platform should fail fast
            found = self._find_older(query)
            if found is None:
                raise
            return found

    def plan(self, version: str) -> InstallPlan:
        candidates = self._index().get(version) or self._history.get(version)
        if not candidates:
            # 'plan' can be called straight after a successful resolve that
            # came from history; anything else still needs the full lookup
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
