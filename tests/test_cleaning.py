"""Tests for src/transformation/cleaning.py.

Money and date parsing are the two places where silent corruption is most
likely. Every test here asserts a specific, intentional behavior for a
specific input shape.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from src.transformation.cleaning import (
    normalize_campaign_series,
    normalize_status_series,
    parse_date_series,
    parse_money_series,
    parse_timestamp_series,
    to_reporting_date,
)

# ---------------------------------------------------------------------- #
# parse_money_series                                                      #
# ---------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("150.00", 150.0),
        ("150", 150.0),
        ("0", 0.0),
        ("0.00", 0.0),
        ("1,250.50", 1250.50),
        ("1,250,000.00", 1_250_000.00),
        ("$150.00", 150.0),
        ("$1,250.50", 1250.50),
        ("ETB 150.00", 150.0),
        ("$1,250.00 ETB", 1250.0),
        ("  150.00  ", 150.0),
        ("(150.00)", -150.0),
        ("(1,250.50)", -1250.50),
        ("-150.00", -150.0),
        ("1 250.50", 1250.50),  # space as thousands separator
    ],
)
def test_parse_money_valid(raw: str, expected: float) -> None:
    result = parse_money_series(pd.Series([raw]))
    assert result.iloc[0] == pytest.approx(expected)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "abc",
        "N/A",
        "null",
        "1,25",  # ambiguous: 1.25 or 125?
        "1,2345",  # not a thousands group
        "$",
        "ETB",
    ],
)
def test_parse_money_invalid_yields_na(raw: str) -> None:
    result = parse_money_series(pd.Series([raw]))
    assert pd.isna(result.iloc[0])


def test_parse_money_handles_null() -> None:
    result = parse_money_series(pd.Series([None, pd.NA]))
    assert result.isna().all()


def test_parse_money_handles_empty_series() -> None:
    result = parse_money_series(pd.Series([], dtype="string"))
    assert len(result) == 0
    assert result.dtype == "Float64"


def test_parse_money_preserves_length_and_index() -> None:
    s = pd.Series(["10.00", "20.00", "30.00"], index=[100, 200, 300])
    result = parse_money_series(s)
    assert list(result.index) == [100, 200, 300]
    assert list(result) == [10.0, 20.0, 30.0]


def test_parse_money_mixed_valid_invalid() -> None:
    s = pd.Series(["10.00", "bad", "30.00"])
    result = parse_money_series(s)
    assert result.iloc[0] == 10.0
    assert pd.isna(result.iloc[1])
    assert result.iloc[2] == 30.0


def test_parse_money_does_not_silently_zero_invalid() -> None:
    """The most important property: bad input is NA, never 0.

    Uses pd.isna rather than `!= 0` because pandas nullable dtypes return
    pd.NA (not False) from comparisons with NA. `assert pd.NA != 0` raises
    TypeError, which is a test bug, not a code bug.
    """
    result = parse_money_series(pd.Series(["abc"]))
    assert pd.isna(result.iloc[0])
    assert result.dtype == "Float64"


def test_parse_money_rejects_non_series() -> None:
    with pytest.raises(TypeError):
        parse_money_series(["10.00"])  # type: ignore[arg-type]


# ---------------------------------------------------------------------- #
# parse_timestamp_series                                                  #
# ---------------------------------------------------------------------- #


def test_parse_timestamp_iso_z() -> None:
    s = pd.Series(["2026-09-01T22:30:00Z"])
    result = parse_timestamp_series(s)
    assert result.iloc[0] == pd.Timestamp("2026-09-01 22:30:00", tz="UTC")


def test_parse_timestamp_with_utc_suffix() -> None:
    s = pd.Series(["2026-09-01 22:30:00 UTC"])
    result = parse_timestamp_series(s)
    assert result.iloc[0] == pd.Timestamp("2026-09-01 22:30:00", tz="UTC")


def test_parse_timestamp_with_numeric_offset() -> None:
    s = pd.Series(["2026-09-01 22:30:00+0300"])
    result = parse_timestamp_series(s)
    assert result.iloc[0] == pd.Timestamp("2026-09-01 19:30:00", tz="UTC")


def test_parse_timestamp_naive_assumed_utc() -> None:
    s = pd.Series(["2026-09-01 22:30:00"])
    result = parse_timestamp_series(s)
    assert result.iloc[0] == pd.Timestamp("2026-09-01 22:30:00", tz="UTC")


def test_parse_timestamp_date_only() -> None:
    s = pd.Series(["2026-09-01"])
    result = parse_timestamp_series(s)
    assert result.iloc[0] == pd.Timestamp("2026-09-01 00:00:00", tz="UTC")


def test_parse_timestamp_invalid_yields_nat() -> None:
    s = pd.Series(["not-a-date", "", None])
    result = parse_timestamp_series(s)
    assert result.isna().all()


def test_parse_timestamp_mixed_formats() -> None:
    """Multiple formats in one Series; each parsed correctly."""
    s = pd.Series(
        [
            "2026-09-01T22:30:00Z",
            "2026-09-02 10:00:00 UTC",
            "2026-09-03 05:00:00+0300",
            "2026-09-04",
        ]
    )
    result = parse_timestamp_series(s)
    assert result.iloc[0] == pd.Timestamp("2026-09-01 22:30:00", tz="UTC")
    assert result.iloc[1] == pd.Timestamp("2026-09-02 10:00:00", tz="UTC")
    assert result.iloc[2] == pd.Timestamp("2026-09-03 02:00:00", tz="UTC")
    assert result.iloc[3] == pd.Timestamp("2026-09-04 00:00:00", tz="UTC")


def test_parse_timestamp_preserves_index() -> None:
    s = pd.Series(
        ["2026-09-01T22:30:00Z", "2026-09-02T10:00:00Z"],
        index=[42, 84],
    )
    result = parse_timestamp_series(s)
    assert list(result.index) == [42, 84]


def test_parse_timestamp_already_tz_aware() -> None:
    s = pd.Series(pd.to_datetime(["2026-09-01 22:30:00+03:00"]))
    result = parse_timestamp_series(s)
    assert result.iloc[0] == pd.Timestamp("2026-09-01 19:30:00", tz="UTC")


def test_parse_timestamp_empty_series() -> None:
    result = parse_timestamp_series(pd.Series([], dtype="string"))
    assert len(result) == 0


# ---------------------------------------------------------------------- #
# to_reporting_date — the timezone boundary cases                          #
# ---------------------------------------------------------------------- #


def test_to_reporting_date_same_day() -> None:
    """20:30 UTC on Sep 1 = 23:30 Addis on Sep 1."""
    ts = pd.Series([pd.Timestamp("2026-09-01 20:30:00", tz="UTC")])
    result = to_reporting_date(ts, reporting_timezone="Africa/Addis_Ababa")
    assert result.iloc[0] == date(2026, 9, 1)


def test_to_reporting_date_crosses_midnight() -> None:
    """22:30 UTC on Sep 1 = 01:30 Addis on Sep 2. This is the trap."""
    ts = pd.Series([pd.Timestamp("2026-09-01 22:30:00", tz="UTC")])
    result = to_reporting_date(ts, reporting_timezone="Africa/Addis_Ababa")
    assert result.iloc[0] == date(2026, 9, 2)


def test_to_reporting_date_exactly_midnight_utc() -> None:
    """00:00 UTC = 03:00 Addis same calendar day."""
    ts = pd.Series([pd.Timestamp("2026-09-01 00:00:00", tz="UTC")])
    result = to_reporting_date(ts, reporting_timezone="Africa/Addis_Ababa")
    assert result.iloc[0] == date(2026, 9, 1)


def test_to_reporting_date_preserves_nat() -> None:
    ts = pd.Series([pd.NaT, pd.Timestamp("2026-09-01 22:30:00", tz="UTC")])
    ts = ts.astype("datetime64[ns, UTC]")
    result = to_reporting_date(ts, reporting_timezone="Africa/Addis_Ababa")
    assert pd.isna(result.iloc[0])
    assert result.iloc[1] == date(2026, 9, 2)


def test_to_reporting_date_rejects_naive_series() -> None:
    ts = pd.Series(pd.to_datetime(["2026-09-01 22:30:00"]))  # naive
    with pytest.raises(TypeError, match="tz-aware"):
        to_reporting_date(ts, reporting_timezone="Africa/Addis_Ababa")


# ---------------------------------------------------------------------- #
# parse_date_series                                                       #
# ---------------------------------------------------------------------- #


def test_parse_date_iso() -> None:
    result = parse_date_series(pd.Series(["2026-09-01", "2026-09-02"]))
    assert result.iloc[0] == date(2026, 9, 1)
    assert result.iloc[1] == date(2026, 9, 2)


def test_parse_date_slash_variant() -> None:
    result = parse_date_series(pd.Series(["2026/09/01"]))
    assert result.iloc[0] == date(2026, 9, 1)


def test_parse_date_invalid_yields_none() -> None:
    result = parse_date_series(pd.Series(["not-a-date", "", None]))
    assert result.isna().all()


def test_parse_date_rejects_us_style() -> None:
    """MM/DD/YYYY is ambiguous and must not be guessed."""
    result = parse_date_series(pd.Series(["09/01/2026"]))
    assert pd.isna(result.iloc[0])


def test_parse_date_empty_series() -> None:
    result = parse_date_series(pd.Series([], dtype="string"))
    assert len(result) == 0


# ---------------------------------------------------------------------- #
# normalize_status_series                                                 #
# ---------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("paid", "paid"),
        ("Paid", "paid"),
        ("PAID", "paid"),
        (" Partially Refunded ", "partially_refunded"),
        ("partially_refunded", "partially_refunded"),
        ("partially-refunded", "partially_refunded"),
        ("PARTIALLY_REFUNDED", "partially_refunded"),
        ("  cancelled  ", "cancelled"),
    ],
)
def test_normalize_status(raw: str, expected: str) -> None:
    result = normalize_status_series(pd.Series([raw]))
    assert result.iloc[0] == expected


def test_normalize_status_preserves_na() -> None:
    result = normalize_status_series(pd.Series([None, "paid"]))
    assert pd.isna(result.iloc[0])
    assert result.iloc[1] == "paid"


# ---------------------------------------------------------------------- #
# normalize_campaign_series                                               #
# ---------------------------------------------------------------------- #


def test_normalize_campaign_strips_and_collapses_whitespace() -> None:
    result = normalize_campaign_series(pd.Series(["  Summer   Sale  "]))
    assert result.iloc[0] == "Summer Sale"


def test_normalize_campaign_preserves_casing() -> None:
    result = normalize_campaign_series(pd.Series(["Summer Sale", "summer sale"]))
    assert result.iloc[0] == "Summer Sale"
    assert result.iloc[1] == "summer sale"


def test_normalize_campaign_empty_to_na() -> None:
    result = normalize_campaign_series(pd.Series(["", "   ", "Summer"]))
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[1])
    assert result.iloc[2] == "Summer"
