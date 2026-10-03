"""DuckDB engine: connection management and DataFrame I/O.

Responsibilities:
    - Open/close a DuckDB file connection.
    - Load pandas DataFrames into DuckDB tables (CREATE OR REPLACE).
    - Execute .sql files in order, resolving views/tables they create.
    - Read results back as pandas DataFrames.

Design decisions:
    - ONE connection per process, passed explicitly. No global singleton.
      DuckDB's connection is not thread-safe, and explicit passing makes
      ownership obvious.
    - Table creation uses CREATE OR REPLACE TABLE, which is idempotent: a
      re-run with the same input produces the same state.
    - SQL files are read from disk, not embedded as Python strings. This
      keeps the SQL diffable and reviewable.
    - Views are recreated on every run so they always reflect current tables.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
from src.exceptions import DatabaseError
from src.utils.logging_config import get_logger

log = get_logger(__name__)


def open_database(database_path: Path) -> duckdb.DuckDBPyConnection:
    """Open (or create) a DuckDB database file and return the connection."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        conn = duckdb.connect(str(database_path))
    except duckdb.Error as exc:
        raise DatabaseError(
            "Failed to open DuckDB database",
            path=str(database_path),
            error=str(exc),
        ) from exc

    log.info(
        "Opened DuckDB database",
        extra={"context": {"path": str(database_path)}},
    )
    return conn


def close_database(conn: duckdb.DuckDBPyConnection) -> None:
    """Close a DuckDB connection. Safe to call multiple times."""
    try:
        conn.close()
    except duckdb.Error as exc:
        log.warning(
            "Error closing DuckDB connection",
            extra={"context": {"error": str(exc)}},
        )


def load_dataframe(
    conn: duckdb.DuckDBPyConnection,
    df: pd.DataFrame,
    table_name: str,
) -> None:
    """Load a pandas DataFrame into a DuckDB table, replacing any existing table.

    Uses DuckDB's native registration: the DataFrame is registered as a view
    and then materialized into a real table. This is the fastest path for
    small-to-medium DataFrames (up to a few million rows).
    """
    if df.empty:
        log.warning(
            "Loading empty DataFrame into %s; table will have schema but no rows",
            table_name,
            extra={"context": {"table": table_name}},
        )

    try:
        # DuckDB can query a pandas DataFrame directly via its variable name
        # if we use the `SELECT * FROM df` idiom. `from_df` is the modern API.
        conn.register("_tmp_df", df)
        conn.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM _tmp_df")
        conn.unregister("_tmp_df")
    except duckdb.Error as exc:
        raise DatabaseError(
            "Failed to load DataFrame into DuckDB",
            table=table_name,
            rows=len(df),
            error=str(exc),
        ) from exc

    log.info(
        "Loaded DataFrame into %s",
        table_name,
        extra={"context": {"table": table_name, "rows": len(df)}},
    )


def execute_sql_file(
    conn: duckdb.DuckDBPyConnection,
    sql_path: Path,
) -> None:
    """Execute a SQL file. All statements in the file run in one call."""
    if not sql_path.exists():
        raise DatabaseError("SQL file not found", path=str(sql_path))

    sql_text = sql_path.read_text(encoding="utf-8")

    try:
        conn.execute(sql_text)
    except duckdb.Error as exc:
        raise DatabaseError(
            "Failed to execute SQL file",
            path=str(sql_path),
            error=str(exc),
        ) from exc

    log.info(
        "Executed SQL file",
        extra={"context": {"path": sql_path.name}},
    )


def execute_sql_directory(
    conn: duckdb.DuckDBPyConnection,
    sql_dir: Path,
) -> None:
    """Execute every .sql file in a directory, sorted by filename.

    Sorting by filename means the numeric prefixes (01_, 02_, ...) define
    the execution order. This is deliberate: the order is versioned in the
    repository, not hardcoded in Python.
    """
    if not sql_dir.exists():
        raise DatabaseError("SQL directory not found", path=str(sql_dir))

    sql_files = sorted(sql_dir.glob("*.sql"))
    if not sql_files:
        raise DatabaseError("No .sql files found in directory", path=str(sql_dir))

    for sql_file in sql_files:
        execute_sql_file(conn, sql_file)

    log.info(
        "Executed %d SQL files",
        len(sql_files),
        extra={"context": {"count": len(sql_files), "files": [f.name for f in sql_files]}},
    )


def read_table(
    conn: duckdb.DuckDBPyConnection,
    table_or_view_name: str,
) -> pd.DataFrame:
    """Read an entire table or view as a pandas DataFrame."""
    try:
        return conn.execute(f"SELECT * FROM {table_or_view_name}").fetchdf()
    except duckdb.Error as exc:
        raise DatabaseError(
            "Failed to read from DuckDB",
            object=table_or_view_name,
            error=str(exc),
        ) from exc


# Expected dtypes for the cleaned tables. Used to normalize empty or
# underspecified DataFrames before loading.
_CLEANED_TABLE_SCHEMAS: dict[str, dict[str, str]] = {
    "shopify_orders_clean": {
        "order_id": "string",
        "calendar_date": "datetime64[ns]",
        "created_at_utc": "datetime64[ns, UTC]",
        "financial_status": "string",
        "gross_amount": "float64",
        "discount_amount": "float64",
        "net_amount": "float64",
        "taxes": "float64",
        "shipping_fees": "float64",
        "reporting_currency": "string",
    },
    "meta_ads_clean": {
        "calendar_date": "datetime64[ns]",
        "campaign_name": "string",
        "spend_amount": "float64",
        "impressions": "Int64",
        "link_clicks": "Int64",
        "reporting_currency": "string",
    },
}
