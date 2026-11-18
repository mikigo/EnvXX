from __future__ import annotations

from .base import AppProvider, Provider, VersionedProvider
from .bun_provider import BunProvider
from .cc_switch_provider import CcSwitchProvider
from .claude_provider import ClaudeProvider
from .dufs_provider import DufsProvider
from .go_provider import GoProvider
from .jdk_provider import JdkProvider
from .mobaxterm_provider import MobaXtermProvider
from .node_provider import NodeProvider
from .opencode_provider import OpencodeProvider
from .python_provider import PythonProvider
from .spec import Asset, EntryPoint, InstallPlan, ToolSpec, VersionInfo
from .uv_provider import UvProvider

_PROVIDER_TYPES: dict[str, type[Provider]] = {
    "python": PythonProvider,
    "node": NodeProvider,
    "go": GoProvider,
    "jdk": JdkProvider,
    "uv": UvProvider,
    "bun": BunProvider,
    "claude": ClaudeProvider,
    "opencode": OpencodeProvider,
    "cc-switch": CcSwitchProvider,
    "xterm": MobaXtermProvider,
    "dufs": DufsProvider,
}


def provider_types() -> dict[str, type[Provider]]:
    return dict(_PROVIDER_TYPES)


def tool_specs() -> list[ToolSpec]:
    return [provider.spec for provider in _PROVIDER_TYPES.values()]


def provider_for(name: str, platform) -> Provider:
    return _PROVIDER_TYPES[name](platform)


__all__ = [
    "Asset",
    "AppProvider",
    "BunProvider",
    "CcSwitchProvider",
    "DufsProvider",
    "EntryPoint",
    "GoProvider",
    "InstallPlan",
    "JdkProvider",
    "MobaXtermProvider",
    "NodeProvider",
    "OpencodeProvider",
    "Provider",
    "ToolSpec",
    "UvProvider",
    "VersionedProvider",
    "VersionInfo",
    "provider_for",
    "provider_types",
    "tool_specs",
]
