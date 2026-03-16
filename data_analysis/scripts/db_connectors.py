#!/usr/bin/env python3
from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from common import ensure_modules

SCHEME_ALIASES = {
    "": "sqlite",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "mysql": "mysql",
    "mssql": "mssql",
    "sqlite": "sqlite",
    "duckdb": "duckdb",
}

DRIVER_CANDIDATES = {
    "sqlite": ["sqlite3 (builtin)"],
    "duckdb": ["duckdb (native connector)", "duckdb-engine (optional SQLAlchemy path)"],
    "postgresql": ["psycopg", "psycopg2"],
    "mysql": ["pymysql", "MySQLdb"],
    "mssql": ["pyodbc", "pymssql"],
}


def normalize_scheme(db_url: str) -> str:
    parsed = urlparse(db_url)
    scheme = (parsed.scheme or "sqlite").lower()
    return SCHEME_ALIASES.get(scheme, scheme)


def _sqlite_path_from_url(db_url: str) -> str:
    parsed = urlparse(db_url)
    scheme = normalize_scheme(db_url)
    if scheme != "sqlite":
        raise ValueError(f"Unsupported sqlite URL: {db_url}")
    if db_url == "sqlite:///:memory:":
        return ":memory:"
    if db_url.startswith("sqlite:///"):
        return db_url.replace("sqlite:///", "", 1)
    return parsed.path or db_url


def _duckdb_path_from_url(db_url: str) -> str:
    parsed = urlparse(db_url)
    scheme = normalize_scheme(db_url)
    if scheme != "duckdb":
        raise ValueError(f"Unsupported DuckDB URL: {db_url}")
    if db_url == "duckdb:///:memory:":
        return ":memory:"
    if db_url.startswith("duckdb:///"):
        return db_url.replace("duckdb:///", "", 1)
    if parsed.path:
        return parsed.path
    return ":memory:"


def driver_status_for_scheme(scheme: str) -> dict[str, Any]:
    normalized = SCHEME_ALIASES.get(scheme, scheme)
    candidates = DRIVER_CANDIDATES.get(normalized, [])
    status = []
    for candidate in candidates:
        builtin = candidate.endswith("(builtin)")
        optional = "optional" in candidate
        module_name = candidate.split(" ", 1)[0]
        import_error = None
        if builtin:
            available = True
        else:
            try:
                importlib.import_module(module_name.replace("-", "_"))
                available = True
            except Exception as exc:
                available = False
                import_error = str(exc)
        status.append(
            {
                "driver": candidate,
                "module": module_name,
                "available": available,
                "builtin": builtin,
                "optional": optional,
                "import_error": import_error,
            }
        )
    return {
        "scheme": normalized,
        "drivers": status,
        "any_available": any(item["available"] for item in status) if status else False,
    }


def connection_plan(db_url: str) -> dict[str, Any]:
    scheme = normalize_scheme(db_url)
    supported = scheme in {"sqlite", "postgresql", "mysql", "mssql", "duckdb"}
    if scheme == "sqlite":
        requires = ["sqlite3 (builtin)", "pandas"]
        strategy = "sqlite_native"
    elif scheme == "duckdb":
        requires = ["duckdb", "pandas"]
        strategy = "duckdb_native"
    else:
        requires = ["pandas", "sqlalchemy", "database driver"]
        strategy = "sqlalchemy_engine"
    return {
        "db_url": db_url,
        "scheme": scheme,
        "supported": supported,
        "requires": requires,
        "strategy": strategy,
        "driver_status": driver_status_for_scheme(scheme),
    }


def _append_limit(query: str, limit: int | None) -> str:
    if limit and "limit" not in query.lower():
        return f"{query.rstrip().rstrip(';')} LIMIT {limit}"
    return query


def _sqlalchemy_url(db_url: str) -> str:
    if db_url.startswith("postgres://"):
        return db_url.replace("postgres://", "postgresql://", 1)
    return db_url


def read_sql_query(db_url: str, query: str, limit: int | None = None):
    query = _append_limit(query, limit)
    scheme = normalize_scheme(db_url)

    if scheme == "sqlite":
        db_path = _sqlite_path_from_url(db_url)
        connection = sqlite3.connect(db_path)
        try:
            ensure_modules(["pandas"], "sqlite query reads")
            import pandas as pd  # type: ignore

            return pd.read_sql_query(query, connection)
        finally:
            connection.close()

    if scheme == "duckdb":
        ensure_modules(["duckdb", "pandas"], "duckdb query reads")
        import duckdb  # type: ignore
        import pandas as pd  # type: ignore

        db_path = _duckdb_path_from_url(db_url)
        connection = duckdb.connect(database=db_path, read_only=False)
        try:
            relation = connection.sql(query)
            return relation.df()
        finally:
            connection.close()

    ensure_modules(["pandas", "sqlalchemy"], f"{scheme} query reads")
    import pandas as pd  # type: ignore
    from sqlalchemy import create_engine  # type: ignore

    engine = create_engine(_sqlalchemy_url(db_url))
    with engine.connect() as connection:
        return pd.read_sql_query(query, connection)


def explain_driver_risks(db_url: str) -> list[str]:
    scheme = normalize_scheme(db_url)
    risks: list[str] = []
    driver_status = driver_status_for_scheme(scheme)
    if scheme == "mssql":
        risks.append("SQL Server often needs both a Python driver and a system ODBC driver manager.")
    if scheme == "mysql":
        risks.append("MySQL needs a SQLAlchemy-compatible driver such as pymysql or mysqlclient.")
    if scheme == "postgresql":
        risks.append("PostgreSQL needs a SQLAlchemy-compatible driver such as psycopg.")
    if scheme == "duckdb":
        risks.append("DuckDB is supported natively; SQLAlchemy integration is optional rather than required.")
    if scheme == "sqlite":
        db_path = _sqlite_path_from_url(db_url)
        if db_path != ":memory:" and not Path(db_path).exists():
            risks.append(f"SQLite database path does not exist yet: {db_path}")
    if driver_status["drivers"] and not driver_status["any_available"]:
        candidate_names = ", ".join(item["driver"] for item in driver_status["drivers"])
        risks.append(f"No compatible Python database driver is currently available for `{scheme}`. Expected one of: {candidate_names}.")
    return risks
