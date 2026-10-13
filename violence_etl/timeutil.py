"""Small time helpers shared by the layers.

Kept dependency-free and timezone-explicit so behavior is identical on
Python 3.8 and 3.14.
"""
from __future__ import annotations

import datetime


def naive_utc_now() -> datetime.datetime:
    """Current UTC time as a naive ``datetime`` (stored without tzinfo)."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
