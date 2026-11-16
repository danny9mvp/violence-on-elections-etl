from __future__ import annotations

import pytest

from violence_etl.exceptions.schema_exception import SchemaException
from violence_etl.utils.schema import COLUMN_MAP, EXPECTED_HEADER, validate_header


def test_expected_header_exact():
    assert EXPECTED_HEADER == (
        "FECHA HECHO",
        "COD_DEPTO",
        "DEPARTAMENTO",
        "COD_MUNI",
        "MUNICIPIO",
        "ZONA",
        "CANTIDAD",
    )


def test_column_map_covers_every_header_field():
    assert set(COLUMN_MAP) == set(EXPECTED_HEADER)
    assert all(v.endswith("_raw") for v in COLUMN_MAP.values())


def test_validate_header_accepts_exact_order():
    validate_header(list(EXPECTED_HEADER))


def test_validate_header_rejects_wrong_order():
    swapped = list(EXPECTED_HEADER)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    with pytest.raises(SchemaException):
        validate_header(swapped)


def test_validate_header_rejects_extra_column():
    with pytest.raises(SchemaException):
        validate_header(list(EXPECTED_HEADER) + ["EXTRA"])


def test_validate_header_rejects_lowercase():
    with pytest.raises(SchemaException):
        validate_header([c.lower() for c in EXPECTED_HEADER])
