"""Tests for src/database/duckdb_engine.py."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from src.database.duckdb_engine import (
    close_database,
    execute_sql_directory,
    execute_sql_file,
    load_dataframe,
    open_database,
    read_table,
)
from src.exceptions import DatabaseError


@pytest.fixture
def conn(tmp_path: Path):
    c = open_database(tmp_path / "test.duckdb")
    yield c
    close_database(c)


def test_open_and_close(tmp_path: Path) -> None:
    c = open_database(tmp_path / "x.duckdb")
    close_database(c)
    assert (tmp_path / "x.duckdb").exists()


def test_open_creates_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "deep" / "x.duckdb"
    c = open_database(path)
    close_database(c)
    assert path.exists()


def test_load_dataframe_creates_table(conn) -> None:
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    load_dataframe(conn, df, "test_table")
    result = read_table(conn, "test_table")
    assert len(result) == 3
    assert list(result.columns) == ["a", "b"]


def test_load_dataframe_is_idempotent(conn) -> None:
    df1 = pd.DataFrame({"a": [1, 2]})
    df2 = pd.DataFrame({"a": [10, 20, 30]})
    load_dataframe(conn, df1, "t")
    load_dataframe(conn, df2, "t")
    result = read_table(conn, "t")
    assert len(result) == 3  # replaced, not appended
    assert list(result["a"]) == [10, 20, 30]


def test_load_empty_dataframe_creates_empty_table(conn) -> None:
    df = pd.DataFrame({"a": pd.Series([], dtype="int64")})
    load_dataframe(conn, df, "empty_table")
    result = read_table(conn, "empty_table")
    assert len(result) == 0


def test_read_nonexistent_table_raises(conn) -> None:
    with pytest.raises(DatabaseError):
        read_table(conn, "does_not_exist")


def test_execute_sql_file(conn, tmp_path: Path) -> None:
    sql = tmp_path / "test.sql"
    sql.write_text("CREATE TABLE t AS SELECT 1 AS x;", encoding="utf-8")
    execute_sql_file(conn, sql)
    result = read_table(conn, "t")
    assert result.iloc[0]["x"] == 1


def test_execute_sql_file_not_found(conn, tmp_path: Path) -> None:
    with pytest.raises(DatabaseError, match="not found"):
        execute_sql_file(conn, tmp_path / "missing.sql")


def test_execute_sql_file_syntax_error(conn, tmp_path: Path) -> None:
    sql = tmp_path / "bad.sql"
    sql.write_text("THIS IS NOT SQL;", encoding="utf-8")
    with pytest.raises(DatabaseError):
        execute_sql_file(conn, sql)


def test_execute_sql_directory_orders_by_filename(conn, tmp_path: Path) -> None:
    (tmp_path / "02_second.sql").write_text("INSERT INTO t SELECT 2;", encoding="utf-8")
    (tmp_path / "01_first.sql").write_text("CREATE TABLE t AS SELECT 1 AS x;", encoding="utf-8")
    execute_sql_directory(conn, tmp_path)
    result = read_table(conn, "t")
    assert list(result["x"]) == [1, 2]


def test_execute_sql_directory_empty(conn, tmp_path: Path) -> None:
    with pytest.raises(DatabaseError, match="No .sql files"):
        execute_sql_directory(conn, tmp_path)


def test_execute_sql_directory_missing(conn, tmp_path: Path) -> None:
    with pytest.raises(DatabaseError, match="directory not found"):
        execute_sql_directory(conn, tmp_path / "missing")
