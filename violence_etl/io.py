"""Download, hash and read helpers for the source CSV."""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import logging
import os
from typing import Optional, Tuple

import pandas as pd
import requests

from violence_etl.errors import DownloadError

logger = logging.getLogger(__name__)

SOURCE_STEM = "yi5j-5fe9"
CHUNK_SIZE = 1024 * 1024


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def utc_stamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def download_source(url: str, timeout: int = 120) -> bytes:
    """Download the source dataset following redirects, into memory."""
    try:
        resp = requests.get(url, allow_redirects=True, stream=True, timeout=timeout)
        resp.raise_for_status()
        chunks = []
        for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
            if chunk:
                chunks.append(chunk)
        return b"".join(chunks)
    except requests.RequestException as exc:  # pragma: no cover - network path
        raise DownloadError("Could not download {0}: {1}".format(url, exc)) from exc


def landing_path(bronze_dir: str, sha: str) -> str:
    return os.path.join(bronze_dir, "landing", "{0}.csv".format(sha))


def write_landing(bronze_dir: str, data: bytes) -> Tuple[str, str, bool]:
    """Write the verbatim bytes to landing/<sha256>.csv if not already present.

    Returns (path, sha, written).
    """
    sha = sha256_bytes(data)
    path = landing_path(bronze_dir, sha)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        return path, sha, False
    with open(path, "wb") as fh:
        fh.write(data)
    return path, sha, True


def write_run_raw_copy(bronze_dir: str, data: bytes) -> str:
    """Write a run-stamped copy under raw/ and return its path."""
    raw_dir = os.path.join(bronze_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    path = os.path.join(raw_dir, "{0}_{1}.csv".format(SOURCE_STEM, utc_stamp()))
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def read_csv(path: str) -> pd.DataFrame:
    """Read the source CSV as all-text with empty strings preserved.

    ``keep_default_na=False`` stops pandas turning empty cells into NaN, and
    ``QUOTE_ALL`` matches the source ``csv.QUOTE_ALL`` dialect.
    """
    return pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
        quoting=csv.QUOTE_ALL,
    )


def file_sha_or_none(path: Optional[str]) -> Optional[str]:
    if not path or not os.path.exists(path):
        return None
    return sha256_file(path)
