from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path

from ..platforms import Platform
from ..versions import best_match
from .spec import EntryPoint, InstallPlan, ToolSpec, VersionInfo

# A console script name as package tooling writes it: 'envxx', 'pip-compile'.
# No separators, and the first character cannot be a dot, so '..' cannot be
# spelled to walk out of the version directory.
_SCRIPT_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")


class Provider(ABC):
    spec: ToolSpec

    def __init__(self, platform: Platform) -> None:
        self.platform = platform
        self._versions: list[VersionInfo] | None = None

    # -- remote catalogue ------------------------------------------------
    @abstractmethod
    def _fetch_versions(self) -> list[VersionInfo]:
        """Remote versions available for the current platform, newest first."""

    def search(self) -> list[VersionInfo]:
        if self._versions is None:
            self._versions = self._fetch_versions()
        return self._versions

    def display_versions(self) -> list[VersionInfo]:
        """Rows for 'envxx <tool> search'. Defaults to the full catalogue."""
        return self.search()

    # -- install planning ------------------------------------------------
    @abstractmethod
    def plan(self, version: str) -> InstallPlan:
        """Asset + install details for an exact version."""

    # -- entrypoints -----------------------------------------------------
    def entrypoint_candidates(self, name: str, version: str | None = None) -> list[str]:
        """Relative paths to try inside a version dir, first existing wins.

        Vendors that put the version in the binary name ('MobaXterm_Personal_
        26.6.exe') write '{version}' into the spec; it is filled in once the
        caller knows which version it is looking at.
        """
        entry = self.spec.entrypoint(name)
        relpath = entry.relpath
        if version is not None:
            relpath = relpath.replace("{version}", version)
        if self.platform.os == "windows":
            if entry.kind == "cmd":
                return [relpath + ".cmd", relpath + ".exe", relpath]
            return [relpath + self.platform.exe_suffix, relpath]
        return [relpath]

    def entrypoint_path(self, version: str, name: str | None = None) -> Path:
        from .. import store

        entry: EntryPoint = self.spec.entrypoint(name)
        root = store.version_dir(self.spec.name, version)
        candidates = self.entrypoint_candidates(entry.name, version)
        for relpath in candidates:
            path = root / relpath
            if path.exists():
                return path
        return root / candidates[0]

    def script_path(self, version: str, name: str) -> Path | None:
        """A console script that pip (or a package manager) left in the version dir.

        'envxx python3.11 envxx' after 'envxx python3.11 pip install -e .' is
        the main case: the script exists but the spec cannot list every package
        that might be installed into the runtime, so it is discovered by name.
        A plain name only -- no path separators, so it cannot climb out of
        the version directory.
        """
        if not self.spec.script_dirs or not _SCRIPT_NAME_RE.match(name):
            return None
        from .. import store

        root = store.version_dir(self.spec.name, version)
        for sub in self.spec.script_dirs:
            for suffix in self.platform.script_suffixes:
                path = root / sub / (name + suffix)
                if path.is_file():
                    return path
        return None

    def module_fallback(self, name: str | None = None) -> tuple[str, str] | None:
        """(launcher entrypoint, module) to use when no launcher file exists.

        python-build-standalone ships pip only as an importable module, so
        'pip' is served by '<python> -m pip'.
        """
        entry = self.spec.entrypoint(name)
        if not entry.module:
            return None
        return self.spec.default_entrypoint, entry.module

    # -- execution -------------------------------------------------------
    def augment_args(self, version: str, args: list[str]) -> list[str]:
        """Adjust the argv handed to the launcher before it runs.

        Tools that need a companion resource (dufs and its UI assets) inject
        the flag here, so 'envxx dufs' works without the user spelling it out.
        """
        return args

    # -- version selection -----------------------------------------------
    def available_versions(self) -> list[str]:
        return [info.version for info in self.search()]

    def default_version(self) -> str:
        """Highest stable version, or highest of anything if only prereleases exist.

        Independent of display ordering: 'search' sorts ascending for python,
        descending for node.
        """
        from ..versions import version_key

        infos = self.search()
        if not infos:
            from ..errors import VersionNotFound

            raise VersionNotFound(
                f"no {self.spec.name} versions available for {self.platform.tag}"
            )
        stable = [info.version for info in infos if info.channel != "prerelease"]
        return max(stable or self.available_versions(), key=version_key)

    def resolve(self, query: str | None) -> str:
        if not query:
            return self.default_version()

        infos = self.search()
        stable = [info.version for info in infos if info.channel != "prerelease"]
        # explicit prerelease queries (3.16.0a2) still get a chance
        has_suffix = any(ch.isalpha() for ch in query)
        pools = [stable, self.available_versions()] if not has_suffix else [self.available_versions()]

        for pool in pools:
            match = best_match(pool, query)
            if match is not None:
                return match

        from ..errors import VersionNotFound

        raise VersionNotFound(
            f"{self.spec.name} {query} is not available for {self.platform.tag}"
        )


class VersionedProvider(Provider):
    """Runtime with many side-by-side versions (python, node, go, jdk)."""


class AppProvider(Provider):
    """Single-version or channel-based application (reserved for later tools)."""

    def channels(self) -> list[VersionInfo]:
        return self.search()
