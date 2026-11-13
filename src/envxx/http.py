from __future__ import annotations

import hashlib
import json
import os
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


def apply_mirror(url: str) -> str:
    for prefix, env_var in _MIRRORS:
        replacement = os.environ.get(env_var)
        if replacement and url.startswith(prefix):
            return replacement.rstrip("/") + "/" + url[len(prefix) :]
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


def _get(client_: httpx.Client, url: str, **kwargs: Any) -> httpx.Response:
    last: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            response = client_.get(url, headers=_auth_headers(url), **kwargs)
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


def _request_json(url: str) -> Any:
    with client() as http:
        response = _get(http, apply_mirror(url))
        if response.status_code == 404:
            raise NetworkError(f"not found: {url}")
        if response.status_code in (403, 429):
            raise NetworkError(
                f"rate limited by {url} (set GITHUB_TOKEN to raise the limit)"
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise NetworkError(f"HTTP {response.status_code} from {url}") from exc
        return response.json()


def get_json(url: str, cache_key: str, ttl: int = DEFAULT_TTL) -> Any:
    cached = store.cache_dir() / f"{cache_key}.json"
    if cached.is_file() and time.time() - cached.stat().st_mtime < ttl:
        try:
            return json.loads(cached.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    data = _request_json(url)

    cached.parent.mkdir(parents=True, exist_ok=True)
    tmp = cached.with_suffix(".json.part")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(cached)
    return data


def get_text(url: str) -> str:
    with client() as http:
        response = _get(http, apply_mirror(url))
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise NetworkError(f"HTTP {response.status_code} from {url}") from exc
        return response.text


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
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    if part.exists():
        part.unlink()

    with client() as http:
        with http.stream("GET", apply_mirror(url), headers=_auth_headers(url)) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or 0)
            with _progress(dest.name, total, show_progress) as tick, open(part, "wb") as out:
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


def _progress(label: str, total: int, enabled: bool):
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
    task = progress.add_task(label, total=total or None)

    class _Ticker:
        def __enter__(self_inner):
            return lambda n: progress.advance(task, n)

        def __exit__(self_inner, *exc):
            progress.stop()
            return False

    return _Ticker()
