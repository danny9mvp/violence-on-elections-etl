"""Expected CSV header contract for the source dataset.

The header is fixed by the Socrata export and every field is quoted. Keeping
the contract in one place means the bronze loader fails fast on a mismatch
instead of silently loading shifted columns.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from violence_etl.exceptions.schema_exception import SchemaException

# Exact expected header, in order, case sensitive.
EXPECTED_HEADER: Tuple[str, ...] = (
    "FECHA HECHO",
    "COD_DEPTO",
    "DEPARTAMENTO",
    "COD_MUNI",
    "MUNICIPIO",
    "ZONA",
    "CANTIDAD",
)

# Maps the source column name to the bronze raw column name.
COLUMN_MAP: Dict[str, str] = {
    "FECHA HECHO": "fecha_hecho_raw",
    "COD_DEPTO": "cod_depto_raw",
    "DEPARTAMENTO": "departamento_raw",
    "COD_MUNI": "cod_muni_raw",
    "MUNICIPIO": "municipio_raw",
    "ZONA": "zona_raw",
    "CANTIDAD": "cantidad_raw",
}


def validate_header(header) -> None:
    """Raise SchemaError unless ``header`` matches EXPECTED_HEADER exactly."""
    actual: List[str] = list(header)
    expected: List[str] = list(EXPECTED_HEADER)
    if actual != expected:
        raise SchemaException(
            "Unexpected CSV header.\n  expected: {0}\n  actual:   {1}".format(
                expected, actual
            )
        )
