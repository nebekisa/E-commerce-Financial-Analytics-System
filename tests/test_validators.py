"""Tests for src/validation/validators.py."""

from __future__ import annotations

import pandas as pd
import pytest
from src.exceptions import DataQualityError
from src.validation.validators import (
    check_rejection_threshold,
    validate_required_values,
    validate_unique_order_ids,
)


def _df(**cols: list[object]) -> pd.DataFrame:
    return pd.DataFrame(cols)


# ---------------------------------------------------------------------- #
# validate_required_values                                                #
# ---------------------------------------------------------------------- #


def test_all_valid_rows_accepted() -> None:
    df = _df(order_id=["1", "2"], amount=["10.00", "20.00"])
    result = validate_required_values(df, required_fields=["order_id", "amount"], source="test")
    assert len(result.accepted) == 2
    assert len(result.rejected) == 0
    assert result.report.rows_accepted == 2
    assert result.report.rows_rejected == 0


def test_missing_required_value_rejected() -> None:
    df = _df(order_id=["1", None, "3"], amount=["10.00", "20.00", "30.00"])
    result = validate_required_values(df, required_fields=["order_id", "amount"], source="test")
    assert len(result.accepted) == 2
    assert len(result.rejected) == 1
    assert result.rejected.iloc[0]["rejection_reason"] == "missing_required_value"
    assert result.report.rejection_reasons["missing_required_value"] == 1


def test_whitespace_only_value_is_missing() -> None:
    df = _df(order_id=["1", "   ", "3"])
    result = validate_required_values(df, required_fields=["order_id"], source="test")
    assert len(result.accepted) == 2
    assert len(result.rejected) == 1


def test_empty_row_rejected_with_specific_reason() -> None:
    df = pd.DataFrame(
        {
            "order_id": ["1", None, "3"],
            "amount": ["10.00", None, "30.00"],
        }
    )
    result = validate_required_values(df, required_fields=["order_id", "amount"], source="test")
    assert len(result.rejected) == 1
    assert result.rejected.iloc[0]["rejection_reason"] == "empty_row"


def test_empty_dataframe_returns_empty_result() -> None:
    df = pd.DataFrame({"order_id": pd.Series(dtype="string")})
    result = validate_required_values(df, required_fields=["order_id"], source="test")
    assert len(result.accepted) == 0
    assert len(result.rejected) == 0
    assert result.report.rows_received == 0


# ---------------------------------------------------------------------- #
# validate_unique_order_ids                                               #
# ---------------------------------------------------------------------- #


def test_duplicate_order_ids_keep_first() -> None:
    df = _df(order_id=["1", "2", "2", "3"])
    result = validate_unique_order_ids(
        df,
        id_field="order_id",
        source="test",
        report=validate_required_values(df, required_fields=["order_id"], source="test").report,
    )
    assert list(result.accepted["order_id"]) == ["1", "2", "3"]
    assert len(result.rejected) == 1
    assert result.rejected.iloc[0]["rejection_reason"] == "duplicate_order_id"


def test_no_duplicates_all_accepted() -> None:
    df = _df(order_id=["1", "2", "3"])
    report = validate_required_values(df, required_fields=["order_id"], source="test").report
    result = validate_unique_order_ids(df, id_field="order_id", source="test", report=report)
    assert len(result.accepted) == 3
    assert len(result.rejected) == 0


# ---------------------------------------------------------------------- #
# check_rejection_threshold                                               #
# ---------------------------------------------------------------------- #


def test_threshold_not_exceeded_passes() -> None:
    from src.validation.validators import DQReport

    report = DQReport(source="test", rows_received=100, rows_rejected=3)
    check_rejection_threshold(report, threshold=0.05)  # 3% < 5%, no raise


def test_threshold_exceeded_raises() -> None:
    from src.validation.validators import DQReport

    report = DQReport(source="test", rows_received=100, rows_rejected=10)
    with pytest.raises(DataQualityError) as exc_info:
        check_rejection_threshold(report, threshold=0.05)
    assert exc_info.value.context["rows_rejected"] == 10


def test_zero_rows_does_not_raise() -> None:
    from src.validation.validators import DQReport

    report = DQReport(source="test", rows_received=0, rows_rejected=0)
    check_rejection_threshold(report, threshold=0.05)
