# IO Strategy

## File Routing

Use this scale-aware default:

| Format | Small / Medium | Large | Notes |
| --- | --- | --- | --- |
| CSV / TSV | `pandas` | `polars` or `duckdb` | Prefer chunking for wide or large files |
| Excel | `pandas` + `openpyxl` | convert first | Excel is not the right runtime format for very large data |
| Parquet / Feather | `pandas` or `polars` | `polars` or `duckdb` | Prefer lazy scans |
| JSON / JSONL | `pandas` | `polars` or staged parsing | Normalize nested structures early |

## Container Inputs

Before rejecting an input as "unsupported", check whether it is a common container around a supported tabular file:

- directory paths: auto-select the most likely data file when there is a single dominant candidate
- `.zip`: inspect members and select the most likely tabular payload
- `.csv.gz`, `.tsv.gz`, `.jsonl.gz`, `.json.bz2`, `.csv.xz`: treat as compressed variants of the underlying logical format

If multiple viable files exist inside a directory or archive, record the auto-selection in `read_plan.json` and warn that other files may still matter for joins.

## Size Heuristics

- under 150 MB: `pandas` is usually fine
- 150 MB to 1.5 GB: prefer `polars` or `duckdb`
- over 1.5 GB: push work down to `duckdb`, database SQL, or chunked processing

## Excel Rule

One worksheet supports at most `1,048,576` rows. If the user says the Excel file contains tens of millions of rows, treat that as a data logistics issue and recommend:

- export to CSV
- convert to Parquet
- ingest into DuckDB or a database

## Database Priority

Default support order:

1. `sqlite3` builtin
2. native `duckdb` connector for `duckdb:///...`
3. `SQLAlchemy` for PostgreSQL / MySQL / SQL Server
4. engine-specific connectors only when necessary

## Database Connector Rules

- `sqlite:///...`: use builtin `sqlite3` + `pandas.read_sql_query`
- `duckdb:///...`: use native `duckdb.connect(...).sql(...).df()`; do not require `duckdb-engine`
- `postgresql://...`: prefer `psycopg`
- `mysql://...`: prefer `pymysql` or `mysqlclient`
- `mssql://...`: prefer `pyodbc`, noting that the system ODBC layer may also be required
- normalize `postgres://...` to `postgresql://...` before handing it to SQLAlchemy

## Smoke Test

Use:

```bash
python3 scripts/db_smoke_test.py --output-dir outputs/smoke-db
```

This does three things:

1. creates local SQLite and DuckDB fixtures and reads them end-to-end
2. records the current Python driver matrix for all supported SQL schemes
3. optionally probes live PostgreSQL / MySQL / SQL Server URLs if provided by CLI flag or environment variable

## Database Read Rules

- push filters, aggregations, and joins into SQL when practical
- sample before full-table export
- always record query text or query source
- do not load full production tables if a smaller aggregate answers the question
- if a backend is not live-tested, say whether the gap is due to missing driver, missing server, or missing credentials
