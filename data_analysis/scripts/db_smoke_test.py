#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine

from common import ensure_output_dir, write_json
from db_connectors import connection_plan, driver_status_for_scheme, explain_driver_risks, read_sql_query


def _fixture_rows() -> list[tuple[int, str, float, str]]:
    return [
        (1, "north", 120.5, "2026-01-01"),
        (2, "south", 98.0, "2026-01-02"),
        (3, "north", 143.2, "2026-01-03"),
        (4, "west", 87.4, "2026-01-04"),
        (5, "south", 111.3, "2026-01-05"),
    ]


def _create_sqlite_fixture(path: Path) -> str:
    if path.exists():
        path.unlink()
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE metrics (
              id INTEGER PRIMARY KEY,
              region TEXT,
              revenue REAL,
              order_date TEXT
            )
            """
        )
        connection.executemany(
            "INSERT INTO metrics (id, region, revenue, order_date) VALUES (?, ?, ?, ?)",
            _fixture_rows(),
        )
        connection.commit()
    finally:
        connection.close()
    return f"sqlite:///{path}"


def _create_duckdb_fixture(path: Path) -> str:
    import duckdb  # type: ignore

    if path.exists():
        path.unlink()
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
            """
            CREATE TABLE metrics (
              id INTEGER,
              region VARCHAR,
              revenue DOUBLE,
              order_date VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO metrics VALUES (?, ?, ?, ?)",
            _fixture_rows(),
        )
    finally:
        connection.close()
    return f"duckdb:///{path}"


def _run_basic_query(db_url: str) -> dict[str, Any]:
    query = """
    SELECT
      COUNT(*) AS row_count,
      ROUND(SUM(revenue), 2) AS revenue_sum,
      COUNT(DISTINCT region) AS region_count
    FROM metrics
    """
    plan = connection_plan(db_url)
    risks = explain_driver_risks(db_url)
    frame = read_sql_query(db_url, query)
    row = frame.iloc[0].to_dict()
    return {
        "db_url": db_url,
        "scheme": plan["scheme"],
        "plan": plan,
        "risks": risks,
        "query_result": row,
        "passed": int(row["row_count"]) == 5 and float(row["region_count"]) == 3.0,
    }


def _run_live_probe(name: str, db_url: str | None) -> dict[str, Any]:
    scheme = name if name != "postgres" else "postgresql"
    base = {
        "name": name,
        "db_url": db_url,
        "driver_status": driver_status_for_scheme(scheme),
        "plan": connection_plan(db_url) if db_url else None,
        "risks": explain_driver_risks(db_url) if db_url else [],
    }
    if not db_url:
        base["status"] = "skipped"
        base["reason"] = "No live URL provided."
        return base
    try:
        frame = read_sql_query(db_url, "SELECT 1 AS smoke_value")
        base["status"] = "passed"
        base["query_result"] = frame.iloc[0].to_dict()
    except Exception as exc:
        base["status"] = "failed"
        base["error"] = str(exc)
    return base


def _run_dialect_probe(name: str) -> dict[str, Any]:
    urls = {
        "postgres": "postgresql+psycopg://user:pass@localhost/db",
        "mysql": "mysql+pymysql://user:pass@localhost/db",
        "mssql": "mssql+pyodbc://user:pass@localhost/db",
    }
    url = urls[name]
    try:
        engine = create_engine(url)
        return {
            "name": name,
            "status": "passed",
            "dialect": engine.dialect.name,
            "driver": engine.driver,
        }
    except Exception as exc:
        return {
            "name": name,
            "status": "failed",
            "error": str(exc),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run multi-database smoke tests for the data-analysis skill.")
    parser.add_argument("--output-dir")
    parser.add_argument("--postgres-url")
    parser.add_argument("--mysql-url")
    parser.add_argument("--mssql-url")
    args = parser.parse_args()

    run_dir = ensure_output_dir(args.output_dir, prefix="db-smoke-test")
    sqlite_url = _create_sqlite_fixture(run_dir / "fixture.sqlite")
    duckdb_url = _create_duckdb_fixture(run_dir / "fixture.duckdb")

    report = {
        "local_tests": {
            "sqlite": _run_basic_query(sqlite_url),
            "duckdb": _run_basic_query(duckdb_url),
        },
        "driver_matrix": {
            scheme: driver_status_for_scheme(scheme)
            for scheme in ["sqlite", "duckdb", "postgresql", "mysql", "mssql"]
        },
        "live_probes": {
            "postgres": _run_live_probe("postgres", args.postgres_url or os.getenv("DATA_ANALYSIS_POSTGRES_URL")),
            "mysql": _run_live_probe("mysql", args.mysql_url or os.getenv("DATA_ANALYSIS_MYSQL_URL")),
            "mssql": _run_live_probe("mssql", args.mssql_url or os.getenv("DATA_ANALYSIS_MSSQL_URL")),
        },
        "dialect_probes": {
            "postgres": _run_dialect_probe("postgres"),
            "mysql": _run_dialect_probe("mysql"),
            "mssql": _run_dialect_probe("mssql"),
        },
    }
    write_json(run_dir / "db_smoke_test_report.json", report)
    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
