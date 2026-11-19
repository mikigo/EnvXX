from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx

from . import store
from .errors import ChecksumError, NetworkError

DEFAULT_TTL = 24 * 60 * 60
_RETRIES = 3
_TIMEOUT = httpx.Timeout(30.0, read=120.0)

# Officials prefix -> env var holding a replacement prefix.
_MIRRORS = (
    ("https://api.github.com/", "ENVXX_GITHUB_API"),
    ("https://github.com/", "ENVXX_GITHUB_MIRROR"),
    ("https://raw.githubusercontent.com/", "ENVXX_GITHUB_RAW"),
    ("https://nodejs.org/dist/", "ENVXX_NODE_DIST"),
)

# Release assets some projects republish under their own CDN. The CDN keeps
# the 'v{tag}/{filename}' tail, so a plain prefix swap is not enough and the
# env var (default value below) is the only override. An empty value turns it
# off and uses github.com directly.
_RELEASE_MIRRORS: dict[str, tuple[str, str]] = {
    "farion1231/cc-switch": ("ENVXX_CCSWITCH_MIRROR", "https://dl.ccswitch.io"),
}
_RELEASE_RE = re.compile(
    r"^https://github\.com/(?P<repo>[^/]+/[^/]+)/releases/download/(?P<tail>.+)$"
)


def apply_mirror(url: str) -> str:
    for prefix, env_var in _MIRRORS:
        replacement = os.environ.get(env_var)
        if replacement and url.startswith(prefix):
            return replacement.rstrip("/") + "/" + url[len(prefix) :]

    match = _RELEASE_RE.match(url)
    if match:
        entry = _RELEASE_MIRRORS.get(match.group("repo"))
        if entry:
            env_var, default = entry
            base = os.environ.get(env_var, default)
            if base:
                return base.rstrip("/") + "/" + match.group("tail")
    return url


def _auth_headers(url: str) -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith(("https://api.github.com/", "https://github.com/")):
        return {"Authorization": f"Bearer {token}"}
    return {}


def client() -> httpx.Client:
    return httpx.Client(
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": "envxx"},
    )


def _get(
    client_: httpx.Client, url: str, method: str = "GET", **kwargs: Any
) -> httpx.Response:
    last: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            response = client_.request(
                method, url, headers=_auth_headers(url), **kwargs
            )
            if response.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"server error {response.status_code}",
                    request=response.request,
                    response=response,
                )
            return response
        except httpx.HTTPError as exc:
            last = exc
            if attempt < _RETRIES - 1:
                time.sleep(1.0 + attempt)
    raise NetworkError(f"failed to fetch {url}: {last}")


def _rate_limit_hint(response: httpx.Response) -> str:
    """Tell the user when the quota comes back instead of just 'rate limited'."""
    reset = response.headers.get("x-ratelimit-reset")
    if not reset or not reset.isdigit():
        return ""
    remaining = max(0, int(reset) - int(time.time()))
    minutes = (remaining + 59) // 60
    return f"; quota resets in about {minutes} min"


def _request_json(url: str, missing_ok: bool = False) -> Any:
    with client() as http:
        response = _get(http, apply_mirror(url))
        if response.status_code == 404:
            if missing_ok:
                return None
            raise NetworkError(f"not found: {url}")
        if response.status_code in (403, 429):
            raise NetworkError(
                f"GitHub API rate limit reached for {url}"
                f"{_rate_limit_hint(response)}"
                f" (set GITHUB_TOKEN for 5000 requests/hour)"
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise NetworkError(f"HTTP {response.status_code} from {url}") from exc
        return response.json()


def get_json(url: str, cache_key: str, ttl: int = DEFAULT_TTL, missing_ok: bool = False) -> Any:
    cached = store.cache_dir() / f"{cache_key}.json"
    if cached.is_file() and time.time() - cached.stat().st_mtime < ttl:
        try:
            return json.loads(cached.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    data = _request_json(url, missing_ok=missing_ok)
    if data is None:
        return None

    cached.parent.mkdir(parents=True, exist_ok=True)
    tmp = cached.with_suffix(".json.part")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(cached)
    return data


def get_text(url: str, cache_key: str | None = None, ttl: int = DEFAULT_TTL) -> str:
    cached = store.cache_dir() / f"{cache_key}.txt" if cache_key else None
    if cached is not None and cached.is_file() and time.time() - cached.stat().st_mtime < ttl:
        try:
            return cached.read_text(encoding="utf-8")
        except OSError:
            pass

    with client() as http:
        response = _get(http, apply_mirror(url))
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise NetworkError(f"HTTP {response.status_code} from {url}") from exc
        text = response.text

    if cached is not None:
        cached.parent.mkdir(parents=True, exist_ok=True)
        tmp = cached.with_suffix(".txt.part")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(cached)
    return text


def redirect_target(url: str) -> str:
    """Follow redirects with a HEAD and return the final URL.

    Some publishers expose only a stable entry point and put the version in
    the file the redirect lands on. A HEAD keeps 800 MB of installer off the
    wire just to read a version number.
    """
    with client() as http:
        response = _get(http, apply_mirror(url), method="HEAD")
        if response.status_code >= 400:
            raise NetworkError(f"HTTP {response.status_code} from {url}")
        return str(response.url)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_sha256_sum(text: str, filename: str) -> str | None:
    """Look up a digests file in the '<hex>  <name>' format."""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == filename:
            return parts[0].lower()
    return None


def download(
    url: str,
    dest: Path,
    expected: str | None = None,
    show_progress: bool = True,
    resume: bool = True,
) -> Path:
    """Fetch url into dest, resuming a previous partial download when possible."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    if not resume:
        part.unlink(missing_ok=True)
    offset = part.stat().st_size if part.is_file() else 0

    # a mirror may only carry recent releases, so keep the official URL as the
    # last resort rather than failing the install
    sources = [apply_mirror(url)]
    if sources[0] != url:
        sources.append(url)

    with client() as http:
        headers = dict(_auth_headers(url))
        if offset:
            headers["Range"] = f"bytes={offset}-"
        for index, source in enumerate(sources):
            is_last = index == len(sources) - 1
            with http.stream("GET", source, headers=headers) as response:
                if response.status_code == 404 and not is_last:
                    continue
                if offset and response.status_code == 200:
                    # server ignored the Range header, start over
                    offset = 0
                    part.unlink(missing_ok=True)
                response.raise_for_status()
                total = int(response.headers.get("content-length") or 0)
                if response.status_code == 206:
                    total += offset
                mode = "ab" if offset and response.status_code == 206 else "wb"
                with _progress(dest.name, total, show_progress, initial=offset) as tick, \
                        open(part, mode) as out:
                    for chunk in response.iter_bytes(1024 * 256):
                        out.write(chunk)
                        tick(len(chunk))

    if expected:
        actual = sha256_file(part)
        if actual != expected.lower():
            part.unlink(missing_ok=True)
            raise ChecksumError(
                f"checksum mismatch for {dest.name}: expected {expected}, got {actual}"
            )
    part.replace(dest)
    return dest


class _noop_progress:
    def __enter__(self):
        return lambda _n: None

    def __exit__(self, *exc):
        return False


def _progress(label: str, total: int, enabled: bool, initial: int = 0):
    if not enabled or not os.isatty(2):
        return _noop_progress()

    from rich.console import Console
    from rich.progress import (
        BarColumn,
        DownloadColumn,
        Progress,
        TextColumn,
        TimeRemainingColumn,
        TransferSpeedColumn,
    )

    progress = Progress(
        TextColumn("[dim]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        transient=True,
        console=Console(stderr=True),
    )
    progress.start()
    task = progress.add_task(label, total=total or None, completed=initial)

    class _Ticker:
        def __enter__(self_inner):
            return lambda n: progress.advance(task, n)

        def __exit__(self_inner, *exc):
            progress.stop()
            return False

    return _Ticker()
