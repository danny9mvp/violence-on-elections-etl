"""argparse entry point: python -m violence_etl.cli <command>"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import List, Optional

from sqlalchemy import func, select, text

from violence_etl import io as etl_io
from violence_etl.db import make_engine
from violence_etl.errors import EtlError
from violence_etl.logging_conf import configure_logging
from violence_etl.models import (
    Base,
    BronzeCrimesRaw,
    GoldCrimesByCalendar,
    GoldCrimesByDepartment,
    GoldCrimesByElectoralPeriod,
    GoldTop5Departments,
    SilverCrimes,
    SilverRejectedRows,
)
from violence_etl.pipeline import run_all, run_bronze, run_gold, run_silver
from violence_etl.settings import (
    Settings,
    database_url_display,
    database_url_object,
    get_settings,
)

logger = logging.getLogger("violence_etl.cli")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _apply_global_overrides(args: argparse.Namespace) -> None:
    """Push CLI flags into the environment before get_settings() is called."""
    if args.backend:
        os.environ["ETL_DB_BACKEND"] = args.backend
    if args.sqlite_path:
        os.environ["ETL_SQLITE_PATH"] = args.sqlite_path
    if args.log_level:
        os.environ["ETL_LOG_LEVEL"] = args.log_level


def _alembic_config(settings: Settings):
    from alembic.config import Config

    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    # Pass a URL object through attributes. A string with "%" would be run
    # through ConfigParser interpolation and raise ValueError.
    cfg.attributes["sqlalchemy.url"] = database_url_object(settings)
    return cfg


def cmd_init_db(settings: Settings, args: argparse.Namespace) -> int:
    from alembic import command

    command.upgrade(_alembic_config(settings), "head")
    print("init-db: migrations applied (url={0})".format(database_url_display(settings)))
    return 0


def cmd_download(settings: Settings, args: argparse.Namespace) -> int:
    data = etl_io.download_source(settings.source_url)
    path, sha, written = etl_io.write_landing(settings.bronze_dir, data)
    print("download: {0} bytes sha256={1} landing={2} new={3}".format(
        len(data), sha, path, written
    ))
    return 0


def cmd_ingest_bronze(settings: Settings, args: argparse.Namespace) -> int:
    engine = make_engine(settings=settings)
    result = run_bronze(engine, settings, csv_path=args.csv_path, force=args.force)
    print("ingest-bronze: status={0} raw_rows={1} sha256={2}".format(
        result.get("status"), result.get("raw_rows"), result.get("source_sha256")
    ))
    return 0


def cmd_build_silver(settings: Settings, args: argparse.Namespace) -> int:
    engine = make_engine(settings=settings)
    result = run_silver(engine, settings, sha=args.sha, force=args.force)
    print(
        "build-silver: raw_rows={0} silver_rows={1} rejected={2} "
        "dropped_duplicates={3} total_crimes={4} mode={5}".format(
            result["raw_rows"],
            result["silver_rows"],
            result["rejected_rows"],
            result["dropped_duplicates"],
            result["total_crimes"],
            result["dedup_mode"],
        )
    )
    return 0


def cmd_build_gold(settings: Settings, args: argparse.Namespace) -> int:
    engine = make_engine(settings=settings)
    result = run_gold(engine, export_csv=args.export_csv)
    print("build-gold: grand_total={0} tables={1}".format(
        result["grand_total"],
        {
            "top5": result["gold_top5_departments"],
            "by_department": result["gold_crimes_by_department"],
            "by_calendar": result["gold_crimes_by_calendar"],
            "by_period": result["gold_crimes_by_electoral_period"],
        },
    ))
    return 0


def cmd_run_all(settings: Settings, args: argparse.Namespace) -> int:
    engine = make_engine(settings=settings)
    result = run_all(
        engine,
        settings,
        csv_path=args.csv_path,
        force=args.force,
        export_csv=args.export_csv,
    )
    silver = result["silver"]
    print(
        "run-all: bronze_status={0} raw_rows={1} silver_rows={2} "
        "rejected={3} dropped_duplicates={4} total_crimes={5} gold_grand_total={6}".format(
            result["bronze"].get("status"),
            silver["raw_rows"],
            silver["silver_rows"],
            silver["rejected_rows"],
            silver["dropped_duplicates"],
            silver["total_crimes"],
            result["gold"]["grand_total"],
        )
    )
    return 0


def _drop_alembic_version(engine) -> None:
    """Remove the Alembic bookkeeping table so ``upgrade head`` replays.

    ``Base.metadata.drop_all`` only knows ORM tables, so ``alembic_version``
    survives it. Leaving it at ``head`` would make the following
    ``command.upgrade(cfg, "head")`` a no-op and the database would be left
    with no application tables.
    """
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


def cmd_drop_db(settings: Settings, args: argparse.Namespace) -> int:
    if not args.yes:
        print("drop-db: refusing to run without --yes")
        return 2
    engine = make_engine(settings=settings)
    Base.metadata.drop_all(engine)
    _drop_alembic_version(engine)
    print("drop-db: tables dropped")
    from alembic import command

    command.upgrade(_alembic_config(settings), "head")
    print(
        "drop-db: tables recreated ({0})".format(
            ", ".join(sorted(Base.metadata.tables))
        )
    )
    return 0


def _scalar(engine, stmt) -> int:
    with engine.connect() as conn:
        value = conn.execute(stmt).scalar()
    return int(value or 0)


def cmd_validate(settings: Settings, args: argparse.Namespace) -> int:
    engine = make_engine(settings=settings)
    checks: List[tuple] = []

    bronze_rows = _scalar(engine, select(func.count()).select_from(BronzeCrimesRaw))
    silver_rows = _scalar(engine, select(func.count()).select_from(SilverCrimes))
    rejected_rows = _scalar(engine, select(func.count()).select_from(SilverRejectedRows))
    silver_total = _scalar(engine, select(func.coalesce(func.sum(SilverCrimes.cantidad), 0)))
    dept_total = _scalar(
        engine, select(func.coalesce(func.sum(GoldCrimesByDepartment.total_crimes), 0))
    )
    period_total = _scalar(
        engine, select(func.coalesce(func.sum(GoldCrimesByElectoralPeriod.total_crimes), 0))
    )
    top5_rows = _scalar(engine, select(func.count()).select_from(GoldTop5Departments))
    dept_rows = _scalar(engine, select(func.count()).select_from(GoldCrimesByDepartment))
    period_rows = _scalar(engine, select(func.count()).select_from(GoldCrimesByElectoralPeriod))
    cal_dups = _scalar(
        engine,
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

    with engine.connect() as conn:
        sample = conn.execute(select(SilverCrimes.cod_depto, SilverCrimes.cod_muni).limit(1)).first()

    checks.append(("bronze rows", bronze_rows, bronze_rows > 0))
    checks.append(("silver rows", silver_rows, silver_rows > 0))
    checks.append(("rejected rows", rejected_rows, rejected_rows >= 0))
    checks.append(("silver total == gold dept total",
                   (silver_total, dept_total), silver_total == dept_total))
    checks.append(("gold dept total == gold period total",
                   (dept_total, period_total), dept_total == period_total))
    checks.append(("top5 has 5 rows", top5_rows, top5_rows == 5))
    checks.append(("by-department rows", dept_rows, dept_rows > 0))
    checks.append(("period table has 4 rows", period_rows, period_rows == 4))
    checks.append(("calendar grain unique", cal_dups, cal_dups == 0))
    if sample is not None:
        checks.append(("cod_depto is 2 chars", sample[0], len(str(sample[0])) == 2))
        checks.append(("cod_muni is 5 chars", sample[1], len(str(sample[1])) == 5))

    ok = True
    for name, value, passed in checks:
        ok = ok and passed
        print("{0} {1}: {2}".format("[ok]" if passed else "[FAIL]", name, value))
    print("validate: {0}".format("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="violence_etl.cli")
    parser.add_argument("--backend", choices=["postgres", "sqlite"], default=None)
    parser.add_argument("--sqlite-path", default=None)
    parser.add_argument("--log-level", default=None)

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="run alembic upgrade head")
    sub.add_parser("download", help="download the source CSV and print its sha256")

    p_ingest = sub.add_parser("ingest-bronze", help="load bronze only")
    p_ingest.add_argument("--csv-path", default=None)
    p_ingest.add_argument("--force", action="store_true")

    p_silver = sub.add_parser("build-silver", help="build silver only")
    p_silver.add_argument("--sha", default=None)
    p_silver.add_argument("--force", action="store_true")

    p_gold = sub.add_parser("build-gold", help="build gold only")
    p_gold.add_argument("--export-csv", action="store_true")

    p_all = sub.add_parser("run-all", help="bronze then silver then gold")
    p_all.add_argument("--csv-path", default=None)
    p_all.add_argument("--force", action="store_true")
    p_all.add_argument("--export-csv", action="store_true")

    sub.add_parser("validate", help="print acceptance checks")

    p_drop = sub.add_parser("drop-db", help="drop and recreate all tables (dev only)")
    p_drop.add_argument("--yes", action="store_true")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _apply_global_overrides(args)
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.debug("cli: command=%s backend=%s", args.command, settings.backend)

    dispatch = {
        "init-db": cmd_init_db,
        "download": cmd_download,
        "ingest-bronze": cmd_ingest_bronze,
        "build-silver": cmd_build_silver,
        "build-gold": cmd_build_gold,
        "run-all": cmd_run_all,
        "validate": cmd_validate,
        "drop-db": cmd_drop_db,
    }
    try:
        return dispatch[args.command](settings, args)
    except EtlError as exc:
        logger.error("pipeline error: %s", exc, exc_info=True)
        print("error: {0}".format(exc), file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("unexpected error: %s", exc, exc_info=True)
        print("error: {0}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
