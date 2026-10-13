"""Typed exceptions for the ETL pipeline."""
from __future__ import annotations


class EtlError(Exception):
    """Base class for every error raised by this package."""


class SchemaError(EtlError):
    """The source CSV header does not match the expected contract."""


class DownloadError(EtlError):
    """The source dataset could not be downloaded."""


class LoadError(EtlError):
    """A layer failed while writing to the warehouse."""
