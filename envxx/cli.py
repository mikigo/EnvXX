from __future__ import annotations

import errno
import json
import os
import re
import shutil
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ._click import ClickExit, ClickNoArgsIsHelp, ClickUsageError

from . import __version__
from . import envvars
from . import install as installer
from . import run as runner
from . import shims
from . import store
from .errors import EnvxxError, UsageError
from .platforms import detect_platform
from .providers import Provider, provider_types, tool_specs
from .providers.spec import ToolSpec
from .versions import best_match, version_key

out = Console()
err = Console(stderr=True)

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

PANEL_MANAGE = "Manage envxx"
PANEL_RUNTIME = "Runtimes"
PANEL_APP = "Portable applications"
PANEL_INSTALLER = "Installer applications"


class _GroupedCommands(typer.core.TyperGroup):
    """Assign every command to a help panel by what it does.

    A flat list of twenty-odd entries gives no clue which install a runtime
    and which manage the store. Typer renders panels from the
    'rich_help_panel' attribute, so this only has to label each command once,
    before the help is drawn.
    """

    def list_commands(self, ctx):
        names = super().list_commands(ctx)
        from .providers import tool_specs

        panels = {spec.name: _panel_for(spec) for spec in tool_specs()}
        for name in names:
            command = self.get_command(ctx, name)
            if command is None or getattr(command, "rich_help_panel", None):
                continue
            command.rich_help_panel = panels.get(name, PANEL_MANAGE)
        return names


def _panel_for(spec: ToolSpec) -> str:
    if spec.installer:
        return PANEL_INSTALLER
    if spec.kind == "runtime":
        return PANEL_RUNTIME
    return PANEL_APP


app = typer.Typer(
    cls=_GroupedCommands,
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
        "envxx node search\n"
        "envxx python3.10 set-path    # afterwards just 'python3.10'"
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
def _scoped(spec: ToolSpec) -> bool:
    """Whether this tool's store operations address the project store.

    True only for a runtime inside an initialised project. Applications stay
    in the global store wherever they are run from, and a runtime outside a
    project has no project store to address.
    """
    return spec.kind == "runtime" and store.project_store() is not None


def _installed_versions(provider: Provider) -> list[str]:
    """Versions already on disk for this tool, project store first.

    A runtime can be installed in a project store or the global one, and a
    run should use whichever has the version asked for. Applications only
    ever live in the global store, so there is one place to look.
    """
    spec = provider.spec
    if spec.kind != "runtime" or store.project_store() is None:
        return store.installed_versions(spec.name, kind=spec.kind)

    # project versions win on a tie, so union with project first
    seen: list[str] = []
    for scoped in (True, False):
        for version in store.installed_versions(
            spec.name, kind=spec.kind, scoped=scoped
        ):
            if version not in seen:
                seen.append(version)
    return seen


def _ensure_installed(provider: Provider, query: str | None) -> str:
    """An installed match wins; otherwise resolve remotely and install it."""
    installed = _installed_versions(provider)
    if query is None:
        if installed:
            return max(installed, key=version_key)
    else:
        match = best_match(installed, query)
        if match:
            return match

    version = provider.resolve(query)
    kind = provider.spec.kind
    scoped = kind == "runtime"
    if not store.is_installed(provider.spec.name, version, kind=kind, scoped=scoped):
        installer.install(provider, version)
    return version


def _split_entrypoint(
    provider: Provider, version: str, args: list[str]
) -> tuple[str | None, list[str]]:
    """'envxx node22 npm run dev' -> ('npm', ['run', 'dev']).

    Without this, 'npm' looks like an argument to node and node tries to load
    a module by that name. Only the non-default entrypoints count, so
    'envxx node22 script.js' still passes the file to node untouched.

    A console script that pip installed into the runtime counts too, which is
    what makes 'envxx python3.11 envxx' work after 'pip install -e .'.
    """
    spec = provider.spec
    if not args:
        return None, args

    head = args[0]
    declared = {entry.name for entry in spec.entrypoints} - {spec.default_entrypoint}
    if head in declared:
        return head, args[1:]
    if spec.script_dirs and provider.script_path(version, head) is not None:
        return head, args[1:]
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
        entry, args = _split_entrypoint(provider, version, rest)
        return runner.run(provider, version, args, entrypoint=entry)

    spec = _find_spec(token)
    if spec is not None:
        provider = _provider(spec)
        version = _ensure_installed(provider, None)
        entry, args = _split_entrypoint(provider, version, rest)
        return runner.run(provider, version, args, entrypoint=entry)

    raise UsageError(f"unknown command: {token}")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _installer_path_of(provider: Provider, version: str | None) -> str:
    """The downloaded installer file, resolved the same way 'install' would."""
    resolved = provider.resolve(version)
    path = store.installer_path(provider.plan(resolved).asset.filename)
    if not path.is_file():
        raise UsageError(
            f"{provider.spec.name} {resolved} has not been downloaded yet; "
            f"run 'envxx {provider.spec.name} install {resolved}'"
        )
    return str(path)


def _list_installers(spec: ToolSpec) -> None:
    """Show downloaded installers.

    An installer never lands in tools/, so 'installed' would always be false.
    What the user wants to know is which installers are sitting in downloads/
    waiting to be run.
    """
    provider = _provider(spec)
    table = Table(title=f"{spec.name} installers", header_style="bold")
    table.add_column("version")
    table.add_column("file")
    table.add_column("size", justify="right")

    found = 0
    try:
        versions = provider.search()
    except EnvxxError:
        versions = []

    for info in versions:
        try:
            path = store.installer_path(provider.plan(info.version).asset.filename)
        except EnvxxError:
            continue
        if not path.is_file():
            continue
        found += 1
        table.add_row(
            info.version, _display_path(path), _fmt_size(path.stat().st_size)
        )

    if not found:
        err.print(f"[dim]no {spec.name} installers downloaded[/dim]")
        return
    out.print(table)
    err.print("[dim]double-click a file above to install it[/dim]")


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
    """Show paths inside the store relative to whichever root is in use."""
    return store.display_path(path)


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
# Names that manage the store rather than run the tool. A selector in front of
# one of them ('python3.12 install') used to fall through to execution, so the
# word became a script path and python died looking for a file called install.
MANAGE_COMMANDS = (
    "search", "list", "install", "uninstall", "update", "where", "rm", "set-path",
)

# Of those, the ones that take a version argument. 'list' and 'search' scope
# over every installed or published version, so a selector in front of them
# carries no meaning and is simply dropped.
VERSIONED_COMMANDS = ("install", "uninstall", "where", "rm", "set-path")


def _add_tool_commands(group: typer.Typer, spec: ToolSpec) -> None:
    @group.command("search")
    def search(all_versions: bool = typer.Option(False, "--all", help="show every version")) -> None:
        """Remote versions available for this platform."""
        provider = _provider(spec)
        # providers with huge catalogues serve a short recent list by default
        # and only walk the whole thing when --all is explicit
        if all_versions:
            infos = provider.search_all()
        else:
            infos = provider.display_versions()
        # every catalogue is newest first, so an app list only needs trimming
        installed = set(_installed_versions(provider))
        hidden = 0
        if spec.kind == "app" and not all_versions and len(infos) > SEARCH_LIMIT:
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
        if spec.installer:
            _list_installers(spec)
            return
        # a runtime's list shows the project store when there is one: that is
        # the set a run from this directory actually uses, and mixing in the
        # global installs would hide which of them belong to the project
        scoped = spec.kind == "runtime" and store.project_store() is not None
        versions = store.installed_versions(
            spec.name, kind=spec.kind, scoped=scoped
        )
        if not versions:
            err.print(f"[dim]no {spec.name} versions installed[/dim]")
            return
        table = Table(title=f"{spec.name} installed", header_style="bold")
        table.add_column("version")
        table.add_column("path")
        table.add_column("size", justify="right")
        for version in sorted(versions, key=version_key, reverse=True):
            path = store.version_dir(
                spec.name, version, kind=spec.kind, scoped=scoped
            )
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
        scoped = _scoped(spec)
        if force and store.is_installed(
            spec.name, resolved, kind=spec.kind, scoped=scoped
        ):
            store.remove_version(
                spec.name, resolved, kind=spec.kind, scoped=scoped
            )
        installer.install(provider, resolved)

    # apps get an 'rm' shorthand below; listing both with the same description
    # is just noise, so keep 'uninstall' working but out of the help
    @group.command("uninstall", hidden=spec.kind == "app")
    def uninstall_cmd(
        version: str | None = typer.Argument(None, help="version to remove"),
        yes: bool = typer.Option(False, "--yes", "-y", help="skip confirmation"),
    ) -> None:
        """Remove an installed version."""
        scoped = _scoped(spec)
        versions = store.installed_versions(
            spec.name, kind=spec.kind, scoped=scoped
        )
        if not versions:
            raise UsageError(f"no {spec.name} versions installed")
        target = best_match(versions, version) if version else max(versions, key=version_key)
        if not target:
            raise UsageError(f"{spec.name} {version} is not installed")
        if not yes and not typer.confirm(f"remove {spec.name} {target}?", default=False):
            raise typer.Abort()
        store.remove_version(spec.name, target, kind=spec.kind, scoped=scoped)
        out.print(f"removed {spec.name} {target}")

    if spec.kind == "app":
        # 'rm' is the usual shorthand for an app-style tool
        group.command("rm", help="Remove an installed version.")(uninstall_cmd)

        @group.command("update")
        def update_cmd() -> None:
            """Install the newest version and point the default at it."""
            provider = _provider(spec)
            latest = provider.default_version()
            scoped = _scoped(spec)
            installed = store.installed_versions(
                spec.name, kind=spec.kind, scoped=scoped
            )
            if latest in installed:
                out.print(f"{spec.name} {latest} is already the latest")
            else:
                installer.install(provider, latest)
            older = sorted(
                (v for v in installed if v != latest), key=version_key, reverse=True
            )
            if older:
                joined = ", ".join(older)
                err.print(
                    f"[dim]older versions still on disk: {joined}"
                    f" (envxx {spec.name} rm {older[0]} to remove)[/dim]"
                )

    @group.command("where")
    def where_cmd(version: str | None = typer.Argument(None)) -> None:
        """Print the absolute path of an installed launcher."""
        provider = _provider(spec)
        if spec.installer:
            typer.echo(_installer_path_of(provider, version))
            return
        installed = _installed_versions(provider)
        resolved = best_match(installed, version) if version else (
            max(installed, key=version_key) if installed else None
        )
        if not resolved:
            raise UsageError(f"{spec.name} {version or ''} is not installed".strip())
        # a path is meant to be copied into an editor or a script, so no rich
        # wrapping: at 80 columns it would break the path across two lines
        typer.echo(runner.which(provider, resolved))

    # an installer has no binary to point a shim at, so the command would
    # only ever fail; hiding it keeps the help honest
    @group.command("set-path", hidden=spec.installer)
    def set_path_shim(
        version: str | None = typer.Argument(
            None, help="version to point at (default: the newest installed)"
        ),
        remove: bool = typer.Option(False, "--remove", help="delete the shim"),
    ) -> None:
        """Create a launcher in the bin directory so the tool can be called by name."""
        if spec.installer:
            raise UsageError(
                f"{spec.name} is an installer; it has no command to put on PATH"
            )
        provider = _provider(spec)

        # A shim is a PATH entry, and PATH is machine-wide. A runtime that
        # only exists inside this project would produce a command that breaks
        # the moment the checkout is removed, so it is refused rather than
        # silently written against the wrong store.
        if spec.kind == "runtime" and store.project_store() is not None:
            raise UsageError(
                f"{spec.name} is project-scoped here; a PATH shim must point at "
                f"a global install.\n"
                f"run this from outside the project, or install globally with "
                f"'envxx {spec.name} install' after setting ENVXX_HOME"
            )

        if remove:
            target = version
            removed = []
            for installed_version in _installed_versions(provider):
                if target and not best_match([installed_version], target):
                    continue
                label = target or _default_label(provider, installed_version)
                removed.extend(shims.remove(spec.name, label))
            if not removed:
                raise UsageError(f"no {spec.name} shim to remove")
            for path in removed:
                out.print(f"removed {_display_path(path)}")
            return

        resolved = shims.require_installed(provider, version)
        # the command is named after what the user asked for ('python3.10'),
        # not the resolved patch, so a patch upgrade does not orphan it
        label = version or _default_label(provider, resolved)
        written = shims.create(provider, resolved, label=label)
        name = shims.shim_name(spec.name, label)
        for path in written:
            out.print(f"created {_display_path(path)}")

        folder = shims.shim_dir()
        on_path = any(
            Path(entry).expanduser() == folder
            for entry in envvars.read_path().split(os.pathsep)
            if entry
        )
        if not on_path:
            err.print(
                f"[dim]{folder} is not on PATH yet; "
                f"run 'envxx set-path {folder}' to add it[/dim]"
            )
        else:
            _remind_new_shell()
            out.print(f"[dim]run '{name}' once the terminal is reopened[/dim]")


def _default_label(provider: Provider, resolved: str) -> str:
    """Shim name when the user gave no version: the minor line for runtimes.

    'envxx python3.10 set-path' and 'envxx python set-path' both end up with a
    label that survives the next patch release.
    """
    if provider.spec.kind != "runtime":
        return ""
    parts = resolved.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else resolved


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
# project store
# ---------------------------------------------------------------------------
def _ignore_line() -> str:
    return store.PROJECT_DIR + "/"


def _ensure_ignored(root: Path) -> str | None:
    """Add the project store to root's .gitignore. Returns a message or None.

    A project store holds executables under tools/, so a stray `git add .`
    would commit binaries that anyone else running envxx in that checkout
    would then execute. Writing the ignore line is the one place envxx can
    prevent that without refusing to work.
    """
    path = root / ".gitignore"
    line = _ignore_line()
    if path.is_file():
        text = path.read_text(encoding="utf-8", errors="replace")
    else:
        text = ""

    present = {
        entry.strip().rstrip("/")
        for entry in text.splitlines()
        if entry.strip() and not entry.strip().startswith("#")
    }
    if store.PROJECT_DIR in present:
        return None

    prefix = "" if not text or text.endswith("\n") else "\n"
    path.write_text(f"{text}{prefix}{line}\n", encoding="utf-8")
    return f"added {line} to {path.name}"


def _migrate_store(path: Path) -> list[tuple[str, str]]:
    """Move a pre-layout-2 store into runtime/ and app/ once.

    Called from init and from startup, so an existing store is converted the
    first time it is used rather than sitting invisible under the old
    'tools/' directory that nothing reads any more.
    """
    if not store.store_needs_migration(path):
        return []
    runtime_names = {spec.name for spec in tool_specs() if spec.kind == "runtime"}
    return store.migrate_layout(
        path, runtime_names, global_store=store.global_home()
    )


def _migrate_any_store() -> None:
    """Convert whichever stores this invocation can see.

    A runtime install may target the project store or the global one, so both
    are checked; each one records that it is done in its marker file.
    """
    seen: set[Path] = set()
    for candidate in (store.project_store(), store.global_home()):
        if candidate is None or candidate in seen:
            continue
        seen.add(candidate)
        _migrate_store(candidate)


@app.command("init")
def init_cmd(
    directory: Path | None = typer.Argument(
        None, help="where to create .envxx (default: current directory)"
    ),
) -> None:
    """Create a project-local .envxx, used in preference to the global one."""
    root = (directory or Path.cwd()).resolve()
    if not root.is_dir():
        raise UsageError(f"not a directory: {root}")

    try:
        path, created = store.init_project(root)
    except (ValueError, OSError) as exc:
        raise UsageError(str(exc)) from None

    if not created:
        out.print(f"{path} already initialised")
    else:
        out.print(f"initialised {path}")
        note = _ensure_ignored(root)
        if note:
            out.print(f"[dim]{note}[/dim]")

    moved = _migrate_store(path)
    if moved:
        for tool, kind in moved:
            out.print(f"[dim]moved {tool} to {kind}/[/dim]")

    out.print(
        "[dim]runtimes installed from here stay in this directory; "
        "applications always go to the global store[/dim]"
    )


# ---------------------------------------------------------------------------
# environment variables
# ---------------------------------------------------------------------------
@app.command("set-env")
def set_env_cmd(
    name: str | None = typer.Argument(None, help="variable name"),
    value: str | None = typer.Argument(None, help="value to store"),
    unset: bool = typer.Option(False, "--unset", help="remove the variable"),
    system: bool = typer.Option(False, "--system", help="for every user (needs admin)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="print the change only"),
    list_values: bool = typer.Option(False, "--list", help="show envxx-managed names"),
) -> None:
    """Set a permanent environment variable for the current user."""
    if list_values:
        _print_backups("env")
        return
    if not name:
        raise UsageError("usage: envxx set-env NAME VALUE [--unset] [--system]")

    if unset:
        if dry_run:
            out.print(f"would unset {name}")
            return
        gone = envvars.unset_env(name, system=system)
        out.print(f"unset {name}" if gone else f"{name} was not set by envxx")
        _remind_new_shell()
        return

    if value is None:
        raise UsageError("a value is required unless --unset is given")

    if dry_run:
        out.print(f"would set {name}={value}")
        return
    previous = envvars.set_env(name, value, system=system)
    if previous is not None and previous != value:
        out.print(f"[dim]previous value: {previous}[/dim]")
    out.print(f"set {name}={value}")
    _remind_new_shell()


@app.command("set-path")
def set_path_cmd(
    path: str | None = typer.Argument(
        None, help="directory to add (relative paths are expanded)"
    ),
    remove: bool = typer.Option(False, "--remove", help="take the directory off PATH"),
    append: bool = typer.Option(
        False, "--append", help="add at the end instead of the front"
    ),
    system: bool = typer.Option(False, "--system", help="for every user (needs admin)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="print the change only"),
    list_values: bool = typer.Option(False, "--list", help="show envxx-managed paths"),
) -> None:
    """Put a directory on the permanent PATH, in front by default."""
    if list_values:
        _print_backups("path")
        return
    if not path:
        raise UsageError("usage: envxx set-path PATH [--remove] [--system]")

    if dry_run:
        target = str(Path(path).expanduser())
        out.print(f"would {'remove' if remove else 'add'} {target}")
        return

    if remove:
        gone = envvars.remove_path(path, system=system)
        out.print(f"removed {path} from PATH" if gone else f"{path} is not on PATH")
    else:
        expanded, changed = envvars.set_path(path, system=system, append=append)
        if changed:
            position = "at the end of" if append else "to the front of"
            out.print(f"added {expanded} {position} PATH")
        else:
            # saying "reopen your terminal" here would suggest something
            # changed when the entry was already there
            out.print(f"{expanded} is already on PATH")
            return
    _remind_new_shell()


def _shim_target(path: Path) -> str:
    """The executable a shim points at, as an absolute path.

    The stored value is relative so the store can move; what the user needs
    to see is the file the command will actually run.
    """
    relative = shims.target_of(path)
    if not relative:
        return ""
    return str((path.parent / relative).resolve())


def _remind_new_shell() -> None:
    """Explain what it takes for the new value to be visible.

    Windows hands every process the environment block of the process that
    started it, and Explorer caches its own copy. A terminal opened from an
    Explorer that has not refreshed yet therefore still sees the old PATH,
    which reads as "the command does not exist" rather than "reopen
    something". A command that works without reopening removes the doubt.
    """
    if os.name == "nt":
        err.print(
            "[dim]already-running terminals keep their old environment. "
            "Open a new one, or refresh this one with:[/dim]"
        )
        err.print(
            '[dim]  powershell: $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")[/dim]'
        )
        err.print('[dim]  cmd:        refreshenv   (or just close and reopen)[/dim]')
        return
    err.print(
        "[dim]open a new shell, or run 'source ~/.profile' in this one[/dim]"
    )


def _print_backups(kind: str) -> None:
    entries = [p for p in envvars.backups() if p.name.startswith(f"{kind}-")]
    if not entries:
        err.print(f"[dim]envxx has not set any {kind} values[/dim]")
        return

    table = Table(title=f"{kind} values set by envxx", header_style="bold")
    table.add_column("name")
    table.add_column("value")
    table.add_column("when")
    for path in entries[:20]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        table.add_row(
            str(data.get("name", "")),
            str(data.get("previous", "")) or "[dim](unset)[/dim]",
            str(data.get("at", "")),
        )
    out.print(table)


@app.command("bin")
def bin_cmd() -> None:
    """List the launcher shims in the bin directory and how to put them on PATH."""
    found = shims.existing()
    folder = shims.shim_dir()

    if not found:
        err.print("[dim]no shims yet; 'envxx <tool> set-path' creates one[/dim]")
        return

    # a command has one file per platform convention (bat and cmd on
    # Windows); listing both rows would read as two separate commands
    grouped: dict[str, list[Path]] = {}
    for path in found:
        grouped.setdefault(path.stem, []).append(path)

    # Plain lines, not a rich table: a table is laid out to the terminal
    # width and truncates a long path, which is the one thing the reader
    # needs whole. Two aligned columns still read fine.
    table = Table(title="envxx bin", header_style="bold", box=None, pad_edge=False)
    table.add_column("command", no_wrap=True)
    table.add_column("runs", no_wrap=True)
    for name in sorted(grouped):
        table.add_row(name, _shim_target(grouped[name][0]))
    # a Console wider than any terminal: rich shrinks a table to the output
    # width, and a path cut in half is exactly what the reader cannot use
    wide = Console(width=max(200, shutil.get_terminal_size().columns))
    wide.print(table)

    on_path = any(
        Path(entry).expanduser() == folder for entry in envvars.read_path().split(os.pathsep)
        if entry
    )
    if not on_path:
        err.print(
            f"[dim]{folder} is not on PATH; "
            f"run 'envxx set-path {folder}' to add it[/dim]"
        )


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

    # answered before dispatch: 'envxx --version' must not be mistaken for a
    # flag meant for a tool, and there is no tool named by it anyway
    if argv and argv[0] in ("--version", "-V"):
        typer.echo(f"envxx {__version__}")
        return 0

    # a store made before the runtime/app split would otherwise be invisible
    # to every command below, since nothing reads 'tools/' any more
    try:
        _migrate_any_store()
    except OSError:
        # an unwritable store is a problem for the command that needs it, not
        # for 'envxx --help'
        pass

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

            # 'python3.12 install' spells a command and a version in one word.
            # Treat it as 'python install 3.12' rather than as Python being
            # asked to run a script named install. Commands that scope over
            # everything ('list', 'search') only need the version dropped.
            selector = _match_selector(token)
            manage = (
                selector is not None
                and bool(rest)
                and rest[0] in MANAGE_COMMANDS
            )
            if manage:
                spec, query = selector
                if rest[0] in VERSIONED_COMMANDS:
                    argv = [spec.name, rest[0], query, *rest[1:]]
                else:
                    argv = [spec.name, *rest]

            should_run = (
                token == "run"
                or (selector is not None and not manage)
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
