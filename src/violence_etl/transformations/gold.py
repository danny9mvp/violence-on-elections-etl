"""Gold layer: small denormalized tables for direct SQL or BI queries.

Gold is built by full refresh (delete then aggregate-insert) inside one
transaction so it always converges to the same content.
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.engine import Engine

import violence_etl.db.models.gold_crimes_by_calendar
from violence_etl.config.settings import Settings, get_settings
from violence_etl.db.models.gold_crimes_by_department import GoldCrimesByDepartment
from violence_etl.db.models.gold_crimes_by_electoral_period import GoldCrimesByElectoralPeriod
from violence_etl.db.models.gold_top_50_departments import GoldTop5Departments
from violence_etl.db.models.silver_crimes import SilverCrimes
from violence_etl.storage.factory import get_artifact_storage

logger = logging.getLogger(__name__)

# Presentation order for electoral periods in the gold table (documented in README).
PERIOD_ORDER: Dict[str, int] = {
    "post-electoral": 1,
    "intermediate": 2,
    "pre-electoral": 3,
    "electoral": 4,
}


def _read_silver_for_gold(engine: Engine) -> pd.DataFrame:
    stmt = select(
        SilverCrimes.cod_depto,
        SilverCrimes.departamento,
        SilverCrimes.year,
        SilverCrimes.quarter,
        SilverCrimes.month,
        SilverCrimes.weekday_num,
        SilverCrimes.weekday_name,
        SilverCrimes.electoral_period,
        SilverCrimes.cantidad,
    )
    return pd.read_sql(stmt, engine)


def build_gold(
    engine: Engine,
    export_csv: bool = False,
    export_dir: str = "data/gold",
    settings: Optional[Settings] = None,
) -> Dict[str, object]:
    started = time.time()
    df = _read_silver_for_gold(engine)
    grand_total = int(df["cantidad"].sum()) if not df.empty else 0

    # a. top 5 departments by total crimes.
    by_dept = (
        df.groupby(["cod_depto", "departamento"], as_index=False)["cantidad"]
        .sum()
        .rename(columns={"cantidad": "total_crimes"})
    )
    by_dept = by_dept.sort_values(
        ["total_crimes", "departamento"], ascending=[False, True]
    ).reset_index(drop=True)
    top5 = by_dept.head(5).copy()
    top5.insert(0, "rank", range(1, len(top5) + 1))

    # b. total crimes by department.
    dept_records = by_dept.to_dict("records")

    # c. total crimes by year, quarter, month, weekday.
    by_cal = (
        df.groupby(
            ["year", "quarter", "month", "weekday_num", "weekday_name"],
            as_index=False,
        )["cantidad"]
        .sum()
        .rename(columns={"cantidad": "total_crimes"})
    )
    cal_records = by_cal.to_dict("records")

    # d. total crimes by electoral period.
    by_period = (
        df.groupby("electoral_period", as_index=False)
        .agg(
            year_min=("year", "min"),
            year_max=("year", "max"),
            total_crimes=("cantidad", "sum"),
        )
    )
    period_records: List[Dict[str, object]] = []
    for rec in by_period.to_dict("records"):
        period = rec["electoral_period"]
        total = int(rec["total_crimes"])
        pct = round((100.0 * total / grand_total), 2) if grand_total else 0.0
        period_records.append(
            {
                "electoral_period": period,
                "period_order": PERIOD_ORDER.get(period, 99),
                "year_min": int(rec["year_min"]),
                "year_max": int(rec["year_max"]),
                "total_crimes": total,
                "pct_of_total": Decimal(str(pct)),
            }
        )
    period_records.sort(key=lambda r: r["period_order"])

    top5_records = [
        {
            "rank": int(r["rank"]),
            "cod_depto": r["cod_depto"],
            "departamento": r["departamento"],
            "total_crimes": int(r["total_crimes"]),
        }
        for r in top5.to_dict("records")
    ]

    with engine.begin() as conn:
        conn.execute(delete(GoldTop5Departments))
        conn.execute(delete(GoldCrimesByDepartment))
        conn.execute(delete(violence_etl.db.models.gold_crimes_by_calendar.GoldCrimesByCalendar))
        conn.execute(delete(GoldCrimesByElectoralPeriod))
        if top5_records:
            conn.execute(GoldTop5Departments.__table__.insert(), top5_records)
        if dept_records:
            conn.execute(GoldCrimesByDepartment.__table__.insert(), dept_records)
        if cal_records:
            conn.execute(violence_etl.db.models.gold_crimes_by_calendar.GoldCrimesByCalendar.__table__.insert(), cal_records)
        if period_records:
            conn.execute(
                GoldCrimesByElectoralPeriod.__table__.insert(), period_records
            )

    if export_csv:
        s = settings or get_settings()
        storage = get_artifact_storage(s)
        storage.export_gold_csvs(
            export_dir, top5_records, dept_records, cal_records, period_records
        )

    result = {
        "grand_total": grand_total,
        "gold_top5_departments": len(top5_records),
        "gold_crimes_by_department": len(dept_records),
        "gold_crimes_by_calendar": len(cal_records),
        "gold_crimes_by_electoral_period": len(period_records),
        "elapsed_seconds": round(time.time() - started, 3),
    }
    logger.info(
        "gold: grand_total=%d top5=%d by_department=%d by_calendar=%d "
        "by_period=%d elapsed=%.2fs",
        grand_total,
        result["gold_top5_departments"],
        result["gold_crimes_by_department"],
        result["gold_crimes_by_calendar"],
        result["gold_crimes_by_electoral_period"],
        result["elapsed_seconds"],
    )
    return result
