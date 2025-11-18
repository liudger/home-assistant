"""Tests for Home EMS domain models."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.home_ems.models import (
    HeatingConstraints,
    HeatingWindow,
    build_schedule,
    calculate_required_quarters,
    calculate_true_cost,
    find_consecutive_window,
    has_significant_gaps,
)
from homeassistant.util import dt as dt_util


def _utc(hour: int, minute: int = 0) -> datetime:
    """Helper to build timezone-aware datetimes."""

    return datetime(2025, 1, 1, hour, minute, tzinfo=dt_util.UTC)


def test_calculate_required_quarters_accounts_for_cooling() -> None:
    """Cooling before heating should increase required quarters."""

    constraints = HeatingConstraints(
        min_temperature=40,
        max_temperature=50,
        min_shower_temperature=45,
        heating_rate=20,
        cooling_rate=1,
    )
    now = _utc(0)
    heating_start = now + timedelta(hours=1)

    quarters = calculate_required_quarters(
        current_temp=45,
        constraints=constraints,
        heating_start_time=heating_start,
        now=now,
    )

    assert quarters == 2


def test_build_schedule_single_day() -> None:
    """Schedules within a day should map to the local day key."""

    window = HeatingWindow(start=_utc(10), end=_utc(11, 30))
    schedule = build_schedule(window)

    start_local = dt_util.as_local(window.start)
    expected_key = start_local.strftime("%A").lower()
    expected_range = (
        f"{start_local.strftime('%H:%M')}"
        f"-{dt_util.as_local(window.end).strftime('%H:%M')}"
    )

    assert schedule == {expected_key: expected_range}


def test_find_consecutive_window_picks_lowest_average() -> None:
    """Ensure the lowest average consecutive window is selected."""

    base = _utc(6)
    prices = [
        (base, 0.5),
        (base + timedelta(minutes=15), 0.6),
        (base + timedelta(minutes=30), 0.2),
        (base + timedelta(minutes=45), 0.3),
    ]

    window = find_consecutive_window(prices, required_quarters=2)
    assert window
    assert window.start == base + timedelta(minutes=30)
    assert window.end == base + timedelta(minutes=60)


def test_has_significant_gaps_detects_gap() -> None:
    """Gaps larger than 15 minutes should be detected."""

    base = _utc(8)
    quarters = [
        (base, 0.4),
        (base + timedelta(minutes=45), 0.5),
    ]

    assert has_significant_gaps(quarters)


def test_calculate_true_cost_penalizes_gaps() -> None:
    """Non-consecutive windows should incur additional penalty."""

    base = _utc(9)
    quarters = [
        (base, 0.4),
        (base + timedelta(minutes=45), 0.4),
    ]

    non_consecutive = calculate_true_cost(quarters, is_consecutive=False)
    consecutive = calculate_true_cost(quarters, is_consecutive=True)

    assert non_consecutive > consecutive
