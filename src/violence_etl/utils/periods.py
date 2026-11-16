"""Electoral period classification.

Colombian general elections (presidencia and congreso) are every 4 years.
The four labels are ``pre-electoral``, ``electoral``, ``intermediate`` and
``post-electoral``.

Reference cycle that the rule must reproduce exactly::

    pre-electoral: 2013, electoral: 2014, post-electoral: 2015,
    intermediate: 2016, pre-electoral: 2017
"""
from __future__ import annotations

import logging
from typing import Dict, Iterable, Tuple

logger = logging.getLogger(__name__)

ELECTION_YEARS: Tuple[int, ...] = (2002, 2006, 2010, 2014, 2018, 2022, 2026)
CYCLE_ANCHOR = ELECTION_YEARS[0]
CYCLE_LEN = 4
UNCLASSIFIED = "unclassified"

_OFFSET_TO_PERIOD: Dict[int, str] = {
    0: "electoral",
    1: "post-electoral",
    2: "intermediate",
    3: "pre-electoral",
}


def is_cycle_valid(election_years: Iterable[int] = ELECTION_YEARS) -> bool:
    ys = sorted(election_years)
    if len(ys) < 2:
        return True
    return all((b - a) == CYCLE_LEN for a, b in zip(ys, ys[1:]))


def electoral_period(
    year: int, election_years: Iterable[int] = ELECTION_YEARS
) -> str:
    """Map a calendar year to its electoral period label."""
    years = set(election_years)
    if year < CYCLE_ANCHOR - 1:
        return UNCLASSIFIED
    if year in years:
        return "electoral"
    if (year - 1) in years:
        return "post-electoral"
    if (year + 1) in years:
        return "pre-electoral"
    offset = (year - CYCLE_ANCHOR) % CYCLE_LEN
    return _OFFSET_TO_PERIOD[offset]


if not is_cycle_valid():
    logger.warning(
        "ELECTION_YEARS is not spaced exactly %d years apart: %s",
        CYCLE_LEN,
        ELECTION_YEARS,
    )
