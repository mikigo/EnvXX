from __future__ import annotations

import re

_VERSION_RE = re.compile(r"^[vV]?(\d+(?:\.\d+)*)")

# Git for Windows repackages one upstream version several times and puts the
# repackaging number after a word: '2.56.0.windows.4'. Dropping that tail
# makes four different builds compare equal, so it is folded into the key as
# extra numeric components separated by a large gap.
_REPACK_RE = re.compile(r"^[vV]?(\d+(?:\.\d+)*)[.-][a-z]+\.(\d+)$")
_REPACK_GAP = 10_000


def parse_version(value: str) -> tuple[int, ...]:
    """Parse '3.11.9' / 'v22.14.0' into a tuple of ints.

    A repackaging suffix keeps its number: '2.56.0.windows.4' parses as
    (2, 56, 0, 100000, 4), which sorts above .1 of the same version and still
    compares below 2.56.1.
    """
    text = value.strip()

    repack = _REPACK_RE.match(text)
    if repack:
        base = tuple(int(part) for part in repack.group(1).split("."))
        return (*base, _REPACK_GAP, int(repack.group(2)))

    match = _VERSION_RE.match(text)
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def version_key(value: str) -> tuple[int, ...]:
    return parse_version(value)


def is_exact_query(query: str) -> bool:
    return len(parse_version(query)) >= 3


def best_match(candidates: list[str], query: str) -> str | None:
    """Pick the highest version whose leading components equal the query.

    '3.11' matches 3.11.x, '3' matches 3.x, '3.11.9' matches only itself.
    """
    wanted = parse_version(query)
    if not wanted:
        return None
    hits = [
        candidate
        for candidate in candidates
        if parse_version(candidate)[: len(wanted)] == wanted
    ]
    if not hits:
        return None
    return max(hits, key=version_key)
