from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import store
from .errors import InstallError
from .providers import Provider

# npm.cmd cannot be exec'd directly by subprocess on Windows; it needs cmd /c.
_CMD_INTERPRETERS = ("cmd", "/c")


def _prepare_argv(exe: Path, args: list[str]) -> list[str]:
    if os.name == "nt" and exe.suffix.lower() in (".cmd", ".bat"):
        return [*_CMD_INTERPRETERS, str(exe), *args]
    return [str(exe), *args]


def env_for(provider: Provider, version: str) -> dict[str, str]:
    """Child env with the version's launcher dirs prepended to PATH."""
    env = dict(os.environ)
    root = store.version_dir(provider.spec.name, version)
    prefixes = []
    for sub in ("Scripts", "bin"):
        path = root / sub
        if path.is_dir():
            prefixes.append(path)
    prefixes.append(root)

    existing = env.get("PATH", "")
    env["PATH"] = os.pathsep.join([str(p) for p in prefixes] + [existing])
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    return env


def resolve_command(
    provider: Provider,
    version: str,
    entrypoint: str | None = None,
) -> tuple[Path, list[str]]:
    """Return (executable, leading args) for an entrypoint.

    Falls back to '<default launcher> -m <module>' when the tool ships no
    launcher file (pip in python-build-standalone install_only archives).
    """
    name = entrypoint or provider.spec.default_entrypoint
    exe = provider.entrypoint_path(version, name)
    if exe.exists():
        return exe, []

    fallback = provider.module_fallback(name)
    if fallback:
        launcher_name, module = fallback
        launcher = provider.entrypoint_path(version, launcher_name)
        if launcher.exists():
            return launcher, ["-m", module]

    raise InstallError(f"{provider.spec.name} {version} has no {name} at {exe}")


def run(
    provider: Provider,
    version: str,
    args: list[str],
    entrypoint: str | None = None,
) -> int:
    exe, leading = resolve_command(provider, version, entrypoint)
    args = provider.augment_args(version, args)

    try:
        completed = subprocess.run(
            _prepare_argv(exe, [*leading, *args]), env=env_for(provider, version)
        )
    except KeyboardInterrupt:
        return 130
    except FileNotFoundError as exc:
        raise InstallError(f"cannot execute {exe}: {exc}") from None
    return completed.returncode


def which(provider: Provider, version: str, entrypoint: str | None = None) -> str:
    exe, leading = resolve_command(provider, version, entrypoint)
    return " ".join([str(exe), *leading])
