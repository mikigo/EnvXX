from __future__ import annotations

import errno
import os
import re
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ._click import ClickExit, ClickNoArgsIsHelp, ClickUsageError

from . import install as installer
from . import run as runner
from . import store
from .errors import EnvxxError, UsageError
from .platforms import detect_platform
from .providers import Provider, provider_types, tool_specs
from .providers.spec import ToolSpec
from .versions import best_match, version_key

out = Console()
err = Console(stderr=True)

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    context_settings=CONTEXT_SETTINGS,
    help=(
        "Portable copies of python, node, claude and friends. "
        "Everything lives in ~/.envxx; delete the folder to uninstall."
    ),
    epilog=(
        "Examples:\n"
        "envxx python3.11 -m pip install requests\n"
        "envxx node22 -v\n"
        "envxx claude\n"
        "envxx node search"
    ),
)

# tool catalogues such as claude's run to hundreds of entries
SEARCH_LIMIT = 10


# ---------------------------------------------------------------------------
# registry-driven parsing
# ---------------------------------------------------------------------------
def _selector_table() -> list[tuple[re.Pattern[str], ToolSpec]]:
    table = []
    for spec in tool_specs():
        if not spec.versioned:
            continue
        for prefix in sorted(spec.selector_prefixes, key=len, reverse=True):
            pattern = re.compile(rf"^{re.escape(prefix)}(\d+(?:\.\d+){{0,2}})$")
            table.append((pattern, spec))
    return table


def _match_selector(token: str) -> tuple[ToolSpec, str] | None:
    for pattern, spec in _selector_table():
        match = pattern.match(token)
        if match:
            return spec, match.group(1)
    return None


def _find_spec(name: str) -> ToolSpec | None:
    for spec in tool_specs():
        if spec.name == name or name in spec.aliases:
            return spec
    return None


def _provider(spec: ToolSpec) -> Provider:
    return provider_types()[spec.name](detect_platform())


# ---------------------------------------------------------------------------
# version resolution
# ---------------------------------------------------------------------------
def _ensure_installed(provider: Provider, query: str | None) -> str:
    """An installed match wins; otherwise resolve remotely and install it."""
    installed = store.installed_versions(provider.spec.name)
    if query is None:
        if installed:
            return max(installed, key=version_key)
    else:
        match = best_match(installed, query)
        if match:
            return match

    version = provider.resolve(query)
    if not store.is_installed(provider.spec.name, version):
        installer.install(provider, version)
    return version


def _split_entrypoint(spec: ToolSpec, args: list[str]) -> tuple[str | None, list[str]]:
    """'envxx node22 npm run dev' -> ('npm', ['run', 'dev']).

    Without this, 'npm' looks like an argument to node and node tries to load
    a module by that name. Only the non-default entrypoints count, so
    'envxx node22 script.js' still passes the file to node untouched.
    """
    names = {entry.name for entry in spec.entrypoints} - {spec.default_entrypoint}
    if args and args[0] in names:
        return args[0], args[1:]
    return None, args


def _split_target(target: str) -> tuple[str, str | None, str | None]:
    """'node@22:npm' -> ('node', '22', 'npm')."""
    name, _, rest = target.partition("@")
    if not rest:
        name, _, rest = target.partition(":")
        return name, None, rest or None
    query, sep, entry = rest.partition(":")
    return name, query or None, (entry or None) if sep else None


def _dispatch_run(token: str, rest: list[str]) -> int:
    """Handle 'python3.11 ...', 'node22 ...', bare app names and 'envxx run'."""
    if token == "run":
        if not rest:
            raise UsageError("usage: envxx run <tool>[@version][:entrypoint] -- <args>")
        target, *args = rest
        if args and args[0] == "--":
            args = args[1:]
        name, query, entry = _split_target(target)
        spec = _find_spec(name)
        if spec is None:
            raise UsageError(f"unknown tool: {name}")
        provider = _provider(spec)
        version = _ensure_installed(provider, query)
        return runner.run(provider, version, args, entrypoint=entry)

    matched = _match_selector(token)
    if matched:
        spec, query = matched
        provider = _provider(spec)
        version = _ensure_installed(provider, query)
        entry, args = _split_entrypoint(spec, rest)
        return runner.run(provider, version, args, entrypoint=entry)

    spec = _find_spec(token)
    if spec is not None:
        provider = _provider(spec)
        version = _ensure_installed(provider, None)
        entry, args = _split_entrypoint(spec, rest)
        return runner.run(provider, version, args, entrypoint=entry)

    raise UsageError(f"unknown command: {token}")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _fmt_size(size: int | None) -> str:
    if not size:
        return ""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024
    return ""


def _display_path(path: Path) -> str:
    """Show paths inside the store relative to it, so tables stay readable."""
    try:
        return "~/.envxx/" + path.relative_to(store.home()).as_posix()
    except ValueError:
        return str(path)


def _dir_size(path: Path) -> int:
    total = 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file() and not entry.is_symlink():
                total += entry.stat().st_size
        except OSError:
            pass
    return total


# ---------------------------------------------------------------------------
# per-tool subcommands
# ---------------------------------------------------------------------------
def _add_tool_commands(group: typer.Typer, spec: ToolSpec) -> None:
    @group.command("search")
    def search(all_versions: bool = typer.Option(False, "--all", help="show every version")) -> None:
        """Remote versions available for this platform."""
        provider = _provider(spec)
        # providers with huge catalogues serve a short recent list by default
        # and only walk the whole thing when --all is explicit
        if all_versions and hasattr(provider, "search_all"):
            infos = provider.search_all()
        else:
            infos = provider.display_versions()
        installed = set(store.installed_versions(spec.name))
        hidden = 0
        if spec.kind == "app":
            # app catalogues are long and only the newest matter: newest first,
            # top SEARCH_LIMIT unless --all
            infos = list(reversed(infos))
            if not all_versions and len(infos) > SEARCH_LIMIT:
                hidden = len(infos) - SEARCH_LIMIT
                infos = infos[:SEARCH_LIMIT]

        table = Table(title=f"{spec.name} available", header_style="bold")
        table.add_column("version")
        table.add_column("channel")
        # catalogues that carry no publication dates (claude, cc-switch) would
        # only get an empty column, so show it when at least one row has one
        show_released = any(info.released for info in infos)
        if show_released:
            table.add_column("released")
        table.add_column("installed")
        for info in infos:
            status = "[green]yes[/green]" if info.version in installed else "[dim]-[/dim]"
            cells = [info.version, info.notes or info.channel]
            if show_released:
                cells.append(info.released or "")
            cells.append(status)
            table.add_row(*cells)
        out.print(table)
        if hidden:
            err.print(f"[dim]{hidden} more, use --all to list them[/dim]")
        if not infos:
            err.print(f"[yellow]no {spec.name} versions for this platform[/yellow]")

    @group.command("list")
    def list_cmd() -> None:
        """Versions already downloaded."""
        versions = store.installed_versions(spec.name)
        if not versions:
            err.print(f"[dim]no {spec.name} versions installed[/dim]")
            return
        table = Table(title=f"{spec.name} installed", header_style="bold")
        table.add_column("version")
        table.add_column("path")
        table.add_column("size", justify="right")
        for version in sorted(versions, key=version_key, reverse=True):
            path = store.version_dir(spec.name, version)
            table.add_row(version, _display_path(path), _fmt_size(_dir_size(path)))
        out.print(table)

    @group.command("install")
    def install_cmd(
        version: str | None = typer.Argument(
            None if spec.kind == "app" else ...,
            help="e.g. 3.11, 3.11.9, 22" + (", defaults to latest" if spec.kind == "app" else ""),
        ),
        force: bool = typer.Option(False, "--force", help="reinstall if present"),
    ) -> None:
        """Download and install a version."""
        provider = _provider(spec)
        resolved = provider.resolve(version)
        if force and store.is_installed(spec.name, resolved):
            store.remove_version(spec.name, resolved)
        installer.install(provider, resolved)

    # apps get an 'rm' shorthand below; listing both with the same description
    # is just noise, so keep 'uninstall' working but out of the help
    @group.command("uninstall", hidden=spec.kind == "app")
    def uninstall_cmd(
        version: str | None = typer.Argument(None, help="version to remove"),
        yes: bool = typer.Option(False, "--yes", "-y", help="skip confirmation"),
    ) -> None:
        """Remove an installed version."""
        versions = store.installed_versions(spec.name)
        if not versions:
            raise UsageError(f"no {spec.name} versions installed")
        target = best_match(versions, version) if version else max(versions, key=version_key)
        if not target:
            raise UsageError(f"{spec.name} {version} is not installed")
        if not yes and not typer.confirm(f"remove {spec.name} {target}?", default=False):
            raise typer.Abort()
        store.remove_version(spec.name, target)
        out.print(f"removed {spec.name} {target}")

    if spec.kind == "app":
        # 'rm' is the usual shorthand for an app-style tool
        group.command("rm", help="Remove an installed version.")(uninstall_cmd)

        @group.command("update")
        def update_cmd() -> None:
            """Install the newest version and point the default at it."""
            provider = _provider(spec)
            latest = provider.default_version()
            installed = store.installed_versions(spec.name)
            if latest in installed:
                out.print(f"{spec.name} {latest} is already the latest")
            else:
                installer.install(provider, latest)
            older = [v for v in installed if v != latest]
            if older:
                joined = ", ".join(sorted(older, key=version_key, reverse=True))
                err.print(
                    f"[dim]older versions still on disk: {joined}"
                    f" (envxx {spec.name} rm {older[0]} to remove)[/dim]"
                )

    @group.command("where")
    def where_cmd(version: str | None = typer.Argument(None)) -> None:
        """Print the absolute path of an installed launcher."""
        provider = _provider(spec)
        installed = store.installed_versions(spec.name)
        resolved = best_match(installed, version) if version else (
            max(installed, key=version_key) if installed else None
        )
        if not resolved:
            raise UsageError(f"{spec.name} {version or ''} is not installed".strip())
        out.print(runner.which(provider, resolved))


for _spec in tool_specs():
    _group = typer.Typer(
        add_completion=False,
        no_args_is_help=True,
        context_settings=CONTEXT_SETTINGS,
        help=_spec.summary,
    )
    _add_tool_commands(_group, _spec)
    app.add_typer(_group, name=_spec.name)


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
def _pipe_is_gone(exc: OSError) -> bool:
    """True when the error means the reader went away mid-write.

    A downstream reader that exits early ('envxx --help | head') closes the
    pipe; writing there raises EPIPE on Unix but EINVAL on Windows, and rich
    only recognises BrokenPipeError.
    """
    if exc.errno == errno.EPIPE:
        return True
    return os.name == "nt" and exc.errno == errno.EINVAL


def _silence_streams() -> None:
    """Point stdout/stderr at devnull so the interpreter's exit flush is quiet.

    Without this the final flush of the already-broken stream prints a second
    'Exception ignored in ... OSError' block after we have recovered.
    """
    devnull = os.open(os.devnull, os.O_WRONLY)
    for stream in (sys.stdout, sys.stderr):
        try:
            os.dup2(devnull, stream.fileno())
        except (OSError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    try:
        if argv:
            token, rest = argv[0], argv[1:]
            spec = _find_spec(token)
            # 'node -v' passes a flag, so it means "execute", not "manage";
            # bare 'node', 'node list' and 'node --help' belong to envxx.
            flag_run = (
                spec is not None
                and bool(rest)
                and rest[0].startswith("-")
                and rest[0] not in ("-h", "--help")
            )
            bare_app_run = spec is not None and spec.kind == "app" and not rest
            should_run = (
                token == "run"
                or _match_selector(token) is not None
                or flag_run
                or bare_app_run
            )
            if should_run:
                return _dispatch_run(token, rest)
        app(args=argv, standalone_mode=False)
        return 0
    except EnvxxError as exc:
        err.print(f"[red]error:[/red] {exc}")
        return 1
    except ClickNoArgsIsHelp:
        # click raises this with 'ctx.get_help()' as the message, but Typer's
        # rich help writes straight to stdout, so the message is empty and
        # only a bare 'error:' would be left over. The help is already on
        # screen; just report the usage status code.
        return 2
    except ClickUsageError as exc:
        err.print(f"[red]error:[/red] {exc.format_message()}")
        return 2
    except ClickExit as exc:
        return exc.exit_code
    except typer.Abort:
        return 130
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        if not _pipe_is_gone(exc):
            raise
        # The reader stopped listening ('envxx --help | head'). The command
        # itself did its job, so report success and leave it at that.
        _silence_streams()
        return 0


if __name__ == "__main__":
    sys.exit(main())
