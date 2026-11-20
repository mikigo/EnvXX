from __future__ import annotations

from .base import AppProvider, Provider, VersionedProvider
from .cc_switch_provider import CcSwitchProvider
from .claude_provider import ClaudeProvider
from .dbeaver_provider import DbeaverProvider
from .dufs_provider import DufsProvider
from .git_provider import GitProvider
from .go_provider import GoProvider
from .jdk_provider import JdkProvider
from .marktext_provider import MarktextProvider
from .mobaxterm_provider import MobaXtermProvider
from .node_provider import NodeProvider
from .notepad_minus_minus_provider import NotepadMinusMinusProvider
from .opencode_provider import OpencodeProvider
from .python_provider import PythonProvider
from .sevenzip_provider import SevenZipProvider
from .spec import Asset, EntryPoint, InstallPlan, ToolSpec, VersionInfo
from .vscode_provider import VscodeProvider
from .wechat_provider import WechatProvider
from .wecom_provider import WecomProvider
from .windows_terminal_provider import WindowsTerminalProvider

_PROVIDER_TYPES: dict[str, type[Provider]] = {
    "python": PythonProvider,
    "node": NodeProvider,
    "go": GoProvider,
    "jdk": JdkProvider,
    "claude": ClaudeProvider,
    "opencode": OpencodeProvider,
    "cc-switch": CcSwitchProvider,
    "xterm": MobaXtermProvider,
    "wt": WindowsTerminalProvider,
    "notepad--": NotepadMinusMinusProvider,
    "marktext": MarktextProvider,
    "dbeaver": DbeaverProvider,
    "git": GitProvider,
    "vscode": VscodeProvider,
    "7zip": SevenZipProvider,
    "wechat": WechatProvider,
    "wecom": WecomProvider,
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
    "CcSwitchProvider",
    "DbeaverProvider",
    "DufsProvider",
    "EntryPoint",
    "GitProvider",
    "GoProvider",
    "InstallPlan",
    "JdkProvider",
    "MarktextProvider",
    "MobaXtermProvider",
    "NodeProvider",
    "NotepadMinusMinusProvider",
    "OpencodeProvider",
    "Provider",
    "ToolSpec",
    "VersionedProvider",
    "VersionInfo",
    "WecomProvider",
    "WechatProvider",
    "VscodeProvider",
    "SevenZipProvider",
    "WindowsTerminalProvider",
    "provider_for",
    "provider_types",
    "tool_specs",
]
