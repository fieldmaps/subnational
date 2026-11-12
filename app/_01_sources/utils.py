"""Shared HTTP and catalog-path helpers for the sources stage."""

from pathlib import Path

import httpx2
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.config import CATALOG_DIR, HTTP_TIMEOUT

from .config import DOWNLOAD_CHUNK_SIZE, HTTP_CONNECT_TIMEOUT


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx2.TransportError):
        return True
    return isinstance(exc, httpx2.HTTPStatusError) and exc.response.is_server_error


_retry = retry(
    retry=retry_if_exception(_retryable),
    stop=stop_after_attempt(5),
    wait=wait_exponential(min=2, max=60),
    reraise=True,
)


def _client() -> httpx2.Client:
    return httpx2.Client(
        follow_redirects=True,
        timeout=httpx2.Timeout(HTTP_TIMEOUT, connect=HTTP_CONNECT_TIMEOUT),
    )


@_retry
def get_json(url: str) -> dict | list:
    """GET url and return its JSON body."""
    with _client() as client:
        r = client.get(url)
        r.raise_for_status()
        return r.json()


@_retry
def download(url: str, dest: Path, size: int | None = None) -> Path:
    """Stream url to dest, skipping when dest already has the remote size."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with _client() as client:
        if size is None:
            head = client.head(url)
            head.raise_for_status()
            size = int(head.headers.get("content-length", -1))
        if dest.exists() and dest.stat().st_size == size:
            return dest
        part = dest.with_name(dest.name + ".part")
        with client.stream("GET", url) as r:
            r.raise_for_status()
            with part.open("wb") as f:
                f.writelines(r.iter_bytes(chunk_size=DOWNLOAD_CHUNK_SIZE))
    part.replace(dest)
    return dest


def catalog_path(src: str, tier: str, key: str) -> Path:
    """Return catalog/{src}/{base}/{key}_{tier}.parquet, creating its folder."""
    path = CATALOG_DIR / src / key.split("_", maxsplit=1)[0] / f"{key}_{tier}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def meta_path(src: str, key: str) -> Path:
    """Return the collection's {base}_metadata.json sidecar path."""
    base = key.split("_", maxsplit=1)[0]
    return catalog_path(src, "original", base).with_name(f"{base}_metadata.json")
