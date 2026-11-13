from __future__ import annotations

import re

_VERSION_RE = re.compile(r"^[vV]?(\d+(?:\.\d+)*)")


def parse_version(value: str) -> tuple[int, ...]:
    """Parse '3.11.9' / 'v22.14.0' into a tuple of ints."""
    match = _VERSION_RE.match(value.strip())
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
