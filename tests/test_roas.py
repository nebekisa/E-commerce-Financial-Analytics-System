"""Tests for src/reporting/roas.py."""

from __future__ import annotations

from decimal import Decimal

import pytest
from config.settings import Settings
from src.reporting.roas import (
    category_to_streamlit_delta,
    classify_roas,
)


def _settings(green: str = "3.0", amber: str = "1.5") -> Settings:
    return Settings(
        roas_green_threshold=Decimal(green),
        roas_amber_threshold=Decimal(amber),
    )


# ---------------------------------------------------------------------- #
# classify_roas                                                           #
# ---------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "roas,expected",
    [
        (10.0, "green"),
        (3.0, "green"),  # exactly at green threshold
        (2.999, "amber"),
        (2.0, "amber"),
        (1.5, "amber"),  # exactly at amber threshold
        (1.499, "red"),
        (0.5, "red"),
        (0.0, "red"),
    ],
)
def test_classify_from_defaults(roas: float, expected: str) -> None:
    assert classify_roas(roas, settings=_settings()) == expected


def test_none_is_neutral() -> None:
    assert classify_roas(None, settings=_settings()) == "neutral"


def test_nan_is_neutral() -> None:
    assert classify_roas(float("nan"), settings=_settings()) == "neutral"


def test_custom_thresholds() -> None:
    s = _settings(green="5.0", amber="2.0")
    assert classify_roas(5.0, settings=s) == "green"
    assert classify_roas(4.9, settings=s) == "amber"
    assert classify_roas(1.9, settings=s) == "red"


# ---------------------------------------------------------------------- #
# category_to_streamlit_delta                                             #
# ---------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "category,prefix",
    [
        ("green", "+"),
        ("amber", "~"),
        ("red", "-"),
    ],
)
def test_delta_has_correct_prefix(category: str, prefix: str) -> None:
    delta = category_to_streamlit_delta(category)  # type: ignore[arg-type]
    assert delta is not None
    assert delta.startswith(prefix)


def test_neutral_has_no_delta() -> None:
    assert category_to_streamlit_delta("neutral") is None
