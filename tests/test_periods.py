from __future__ import annotations

from violence_etl.periods import (
    ELECTION_YEARS,
    UNCLASSIFIED,
    electoral_period,
    is_cycle_valid,
)

# The authoritative mapping table from docs/PLAN.md, 2003..2026.
EXPECTED = {
    2003: "post-electoral",
    2004: "intermediate",
    2005: "pre-electoral",
    2006: "electoral",
    2007: "post-electoral",
    2008: "intermediate",
    2009: "pre-electoral",
    2010: "electoral",
    2011: "post-electoral",
    2012: "intermediate",
    2013: "pre-electoral",
    2014: "electoral",
    2015: "post-electoral",
    2016: "intermediate",
    2017: "pre-electoral",
    2018: "electoral",
    2019: "post-electoral",
    2020: "intermediate",
    2021: "pre-electoral",
    2022: "electoral",
    2023: "post-electoral",
    2024: "intermediate",
    2025: "pre-electoral",
    2026: "electoral",
}


def test_full_mapping_table_2003_to_2026():
    for year in range(2003, 2027):
        assert electoral_period(year) == EXPECTED[year], year


def test_reference_cycle():
    assert electoral_period(2013) == "pre-electoral"
    assert electoral_period(2014) == "electoral"
    assert electoral_period(2015) == "post-electoral"
    assert electoral_period(2016) == "intermediate"
    assert electoral_period(2017) == "pre-electoral"


def test_election_years_are_electoral():
    for year in ELECTION_YEARS:
        assert electoral_period(year) == "electoral"


def test_2002_and_2026_are_electoral():
    assert electoral_period(2002) == "electoral"
    assert electoral_period(2026) == "electoral"


def test_2001_is_pre_electoral():
    assert electoral_period(2001) == "pre-electoral"


def test_2000_is_unclassified():
    assert electoral_period(2000) == UNCLASSIFIED


def test_cycle_is_valid_for_default_years():
    assert is_cycle_valid() is True


def test_cycle_invalid_when_not_every_four_years():
    assert is_cycle_valid((2002, 2006, 2011, 2014)) is False


def test_no_unmapped_year_in_dataset_range():
    for year in range(2003, 2027):
        assert electoral_period(year) != UNCLASSIFIED
