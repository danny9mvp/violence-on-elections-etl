from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select

from violence_etl.bronze import ingest_bronze
from violence_etl.gold import build_gold
from violence_etl.models import (
    GoldCrimesByCalendar,
    GoldCrimesByDepartment,
    GoldCrimesByElectoralPeriod,
    GoldTop5Departments,
    SilverCrimes,
)
from violence_etl.silver import build_silver


def _prepare(engine, settings, sample_csv):
    ingest_bronze(engine, settings, csv_path=sample_csv)
    build_silver(engine, settings)
    return build_gold(engine)


def _scalar(engine, stmt):
    with engine.connect() as conn:
        return conn.execute(stmt).scalar()


def test_top5_rows_and_ranks(sqlite_engine, settings_sqlite, sample_csv):
    _prepare(sqlite_engine, settings_sqlite, sample_csv)
    with sqlite_engine.connect() as conn:
        rows = conn.execute(
            select(GoldTop5Departments).order_by(GoldTop5Departments.rank)
        ).fetchall()
    assert len(rows) == 5
    assert [r.rank for r in rows] == [1, 2, 3, 4, 5]
    # Ordered by total desc, tie broken by departamento asc.
    assert [r.departamento for r in rows] == [
        "BOGOTA",
        "ANTIOQUIA",
        "VALLE",
        "BOLIVAR",
        "ATLANTICO",
    ]
    assert [r.total_crimes for r in rows] == [9, 8, 8, 4, 3]


def test_top5_is_monotonic(sqlite_engine, settings_sqlite, sample_csv):
    _prepare(sqlite_engine, settings_sqlite, sample_csv)
    with sqlite_engine.connect() as conn:
        totals = [
            r[0]
            for r in conn.execute(
                select(GoldTop5Departments.total_crimes).order_by(GoldTop5Departments.rank)
            )
        ]
    assert totals == sorted(totals, reverse=True)


def test_by_department_matches_silver_total(sqlite_engine, settings_sqlite, sample_csv):
    _prepare(sqlite_engine, settings_sqlite, sample_csv)
    silver_total = _scalar(
        sqlite_engine, select(func.coalesce(func.sum(SilverCrimes.cantidad), 0))
    )
    dept_total = _scalar(
        sqlite_engine, select(func.coalesce(func.sum(GoldCrimesByDepartment.total_crimes), 0))
    )
    assert int(dept_total) == int(silver_total) == 32


def test_by_department_has_all_departments(sqlite_engine, settings_sqlite, sample_csv):
    _prepare(sqlite_engine, settings_sqlite, sample_csv)
    count = _scalar(sqlite_engine, select(func.count()).select_from(GoldCrimesByDepartment))
    assert int(count) == 5
    # Sum of the top-5 table equals only the top 5 of the full department table.
    top5_sum = _scalar(
        sqlite_engine, select(func.coalesce(func.sum(GoldTop5Departments.total_crimes), 0))
    )
    assert int(top5_sum) == 32


def test_by_calendar_grain_is_unique(sqlite_engine, settings_sqlite, sample_csv):
    _prepare(sqlite_engine, settings_sqlite, sample_csv)
    dups = _scalar(
        sqlite_engine,
        select(func.count()).select_from(
            select(GoldCrimesByCalendar.year)
            .group_by(
                GoldCrimesByCalendar.year,
                GoldCrimesByCalendar.quarter,
                GoldCrimesByCalendar.month,
                GoldCrimesByCalendar.weekday_num,
            )
            .having(func.count() > 1)
            .subquery()
        ),
    )
    assert int(dups) == 0
    cal_total = _scalar(
        sqlite_engine, select(func.coalesce(func.sum(GoldCrimesByCalendar.total_crimes), 0))
    )
    assert int(cal_total) == 32


def test_calendar_columns_present(sqlite_engine, settings_sqlite, sample_csv):
    _prepare(sqlite_engine, settings_sqlite, sample_csv)
    with sqlite_engine.connect() as conn:
        row = conn.execute(
            select(GoldCrimesByCalendar).where(
                (GoldCrimesByCalendar.year == 2024)
                & (GoldCrimesByCalendar.month == 12)
            )
        ).first()
    assert row.quarter == 4
    assert row.weekday_num == 3
    assert row.weekday_name == "Wednesday"


def test_by_period_rows_and_pct(sqlite_engine, settings_sqlite, sample_csv):
    _prepare(sqlite_engine, settings_sqlite, sample_csv)
    with sqlite_engine.connect() as conn:
        rows = conn.execute(
            select(GoldCrimesByElectoralPeriod).order_by(
                GoldCrimesByElectoralPeriod.period_order
            )
        ).fetchall()
    assert len(rows) == 4
    assert {r.electoral_period for r in rows} == {
        "pre-electoral",
        "electoral",
        "post-electoral",
        "intermediate",
    }
    total_pct = sum(Decimal(str(r.pct_of_total)) for r in rows)
    assert abs(total_pct - Decimal("100.00")) <= Decimal("0.1")
    period_total = sum(r.total_crimes for r in rows)
    assert period_total == 32


def test_gold_full_refresh_is_deterministic(sqlite_engine, settings_sqlite, sample_csv):
    ingest_bronze(sqlite_engine, settings_sqlite, csv_path=sample_csv)
    build_silver(sqlite_engine, settings_sqlite)
    first = build_gold(sqlite_engine)
    second = build_gold(sqlite_engine)
    assert first["grand_total"] == second["grand_total"] == 32
    dept_count = _scalar(sqlite_engine, select(func.count()).select_from(GoldCrimesByDepartment))
    assert int(dept_count) == 5


def test_top5_truncates_when_more_departments_exist(
    sqlite_engine, settings_sqlite, many_depts_csv
):
    ingest_bronze(sqlite_engine, settings_sqlite, csv_path=many_depts_csv)
    build_silver(sqlite_engine, settings_sqlite)
    out = build_gold(sqlite_engine)

    # Seven departments in total, only the top five are kept.
    assert out["gold_crimes_by_department"] == 7
    assert out["gold_top5_departments"] == 5

    with sqlite_engine.connect() as conn:
        rows = conn.execute(
            select(GoldTop5Departments).order_by(GoldTop5Departments.rank)
        ).fetchall()
    assert [r.rank for r in rows] == [1, 2, 3, 4, 5]
    assert [r.departamento for r in rows] == [
        "CAUCA",
        "CALDAS",
        "ANTIOQUIA",
        "ATLANTICO",
        "BOGOTA",
    ]
    assert [r.total_crimes for r in rows] == [7, 6, 5, 4, 3]


def test_period_order_matches_expected_labels(sqlite_engine, settings_sqlite, sample_csv):
    _prepare(sqlite_engine, settings_sqlite, sample_csv)
    with sqlite_engine.connect() as conn:
        actual = {
            r.electoral_period: r.period_order
            for r in conn.execute(select(GoldCrimesByElectoralPeriod))
        }
    assert actual == {
        "post-electoral": 1,
        "intermediate": 2,
        "pre-electoral": 3,
        "electoral": 4,
    }


def test_export_csv_branch_writes_all_files(
    sqlite_engine, settings_sqlite, sample_csv, tmp_path
):
    import os

    ingest_bronze(sqlite_engine, settings_sqlite, csv_path=sample_csv)
    build_silver(sqlite_engine, settings_sqlite)
    export_dir = tmp_path / "gold"
    out = build_gold(sqlite_engine, export_csv=True, export_dir=str(export_dir))

    assert out["grand_total"] == 32
    for name in [
        "gold_top5_departments.csv",
        "gold_crimes_by_department.csv",
        "gold_crimes_by_calendar.csv",
        "gold_crimes_by_electoral_period.csv",
    ]:
        path = os.path.join(str(export_dir), name)
        assert os.path.exists(path), name
