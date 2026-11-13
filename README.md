# EnvXX

Portable multi-runtime manager. Downloads self-contained builds of Python,
Node.js and friends into `~/.envxx`, with no system-wide installation and no
registry changes.

```console
$ envxx python3.11 -c "print('hello')"
installing python 3.11.18 (cpython-3.11.18+20261110-x86_64-pc-windows-msvc-install_only.tar.gz)
hello
```

## Install

```console
$ uv tool install envxx        # or: pipx install envxx
```

Or run it from a checkout:

```console
$ uv venv && uv pip install -e ".[dev]"
$ python -m envxx --help
```

## Usage

Create and use a runtime on demand. A missing version is downloaded, verified
and installed the first time you ask for it, then reused afterwards.

```console
$ envxx python3.11 -m pip install requests   # pip via 'python -m pip'
$ envxx node22 --version
$ envxx run node@22:npm -- install express   # pick a specific entrypoint
```

Manage what is on disk:

```console
$ envxx python search        # remote versions for this platform
$ envxx python list          # downloaded versions
$ envxx python install 3.12  # install without running it
$ envxx python uninstall 3.11
$ envxx python where 3.11    # absolute path of the launcher
```

Version selectors accept a full version (`python3.11.9`), a minor line
(`python3.11`) or a bare major (`node22`). A partial version picks the highest
installed match, otherwise the highest matching remote version.

## Layout

```
~/.envxx/
├─ tools/python/3.11.18/
├─ tools/node/22.14.0/
├─ cache/            # remote version indexes, 24h TTL
├─ downloads/        # verified archives
├─ .locks/           # per-version install locks
└─ shims/            # reserved for PATH shims
```

Set `ENVXX_HOME` to relocate the store. `GITHUB_TOKEN` raises GitHub API rate
limits; `ENVXX_GITHUB_API`, `ENVXX_GITHUB_MIRROR`, `ENVXX_GITHUB_RAW` and
`ENVXX_NODE_DIST` point downloads at a mirror.

## Sources

Python builds come from
[python-build-standalone](https://github.com/astral-sh/python-build-standalone)
(`install_only` archives, checksum from the release asset digest). Node.js
comes from [nodejs.org/dist](https://nodejs.org/dist), LTS releases only,
verified against `SHASUMS256.txt`.

## Adding a tool

A tool is a `ToolSpec` plus a `Provider` subclass registered in
`envxx/providers/__init__.py`. The spec declares the command prefixes,
entrypoints and checksum style; the CLI, installer and `list` pick it up with
no further changes.

## Development

```console
$ python -m pytest -q
```
