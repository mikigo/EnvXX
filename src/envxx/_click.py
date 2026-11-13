"""Click exception types, wherever Typer gets them from.

Newer Typer releases vendor Click as ``typer._click``; older ones depend on
the real ``click`` package. The type raised must be the one Typer raises, so
prefer the vendored copy when present.
"""

from __future__ import annotations

import typer

ClickExit = typer.Exit

try:  # Typer >= 0.16
    from typer._click.core import UsageError as ClickUsageError
except ImportError:  # pragma: no cover - older Typer with real click
    from click.core import UsageError as ClickUsageError  # type: ignore

__all__ = ["ClickExit", "ClickUsageError"]
