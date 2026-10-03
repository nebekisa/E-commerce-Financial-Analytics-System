"""ROAS classification for the dashboard.

The client-defined thresholds map a ROAS value to a display category:
    roas >= green_threshold    -> "green"
    roas >= amber_threshold    -> "amber"
    roas <  amber_threshold    -> "red"
    roas is None or NA         -> "neutral"  (undefined, e.g., no ad spend)

The thresholds are configured in Settings and are client preferences, not
universal business standards. The module name says "roas" but the function
is generic enough to classify any non-negative ratio.

Design decisions:
    - Returns a string label, not a hex color. The UI layer maps labels to
      colors. This keeps the module UI-agnostic.
    - None and NaN are handled explicitly. A missing ROAS is not the same as
      a low ROAS. The dashboard shows "—" for neutral, not "red".
    - Exactly at threshold counts as "at threshold" (>= not >). So ROAS = 3.0
      with green_threshold = 3.0 is green.
"""

from __future__ import annotations

from typing import Literal

from config.settings import Settings

RoasCategory = Literal["green", "amber", "red", "neutral"]


def classify_roas(
    roas: float | None,
    *,
    settings: Settings,
) -> RoasCategory:
    """Classify a ROAS value against the configured thresholds.

    Args:
        roas: The ROAS value, or None if undefined (e.g., ad spend was 0).
        settings: Source of the green and amber thresholds.

    Returns:
        "green" if roas >= green_threshold
        "amber" if roas >= amber_threshold (and < green_threshold)
        "red" if roas < amber_threshold
        "neutral" if roas is None or NaN
    """
    if roas is None:
        return "neutral"
    # NaN is not None, so check explicitly. NaN != NaN, so `roas != roas`
    # would also work, but `math.isnan` is clearer.
    import math

    if math.isnan(roas):
        return "neutral"

    green = float(settings.roas_green_threshold)
    amber = float(settings.roas_amber_threshold)

    if roas >= green:
        return "green"
    if roas >= amber:
        return "amber"
    return "red"


def category_to_streamlit_delta(category: RoasCategory) -> str | None:
    """Map a category to the `delta` string Streamlit metric uses for color.

    Streamlit's st.metric colors the delta text green when it starts with "+"
    and red when it starts with "-". We can't set arbitrary colors on the
    delta, but we can use this convention to convey the ROAS category.

    Returns:
        "+ On target" for green
        "~ Watch"     for amber
        "- Below"     for red
        None          for neutral (no delta shown)
    """
    if category == "green":
        return "+ On target"
    if category == "amber":
        return "~ Watch"
    if category == "red":
        return "- Below"
    return None
