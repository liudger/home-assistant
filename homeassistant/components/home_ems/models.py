"""Domain models and helpers for the Home EMS integration."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
import math

from homeassistant.util import dt as dt_util

from .const import DEFAULT_BASE_ENERGY, DEFAULT_COOLING_RATE, DEFAULT_ENERGY_PER_DEGREE


@dataclass(frozen=True)
class HeatingConstraints:
    """Bundle common temperature and rate constraints."""

    min_temperature: float
    max_temperature: float
    min_shower_temperature: float
    heating_rate: float
    cooling_rate: float


@dataclass(frozen=True)
class HeatingWindow:
    """Represent a heating window in UTC."""

    start: datetime
    end: datetime

    def duration(self) -> timedelta:
        """Return the duration of the window."""
        return self.end - self.start


def calculate_required_quarters(
    current_temp: float,
    constraints: HeatingConstraints,
    *,
    heating_start_time: datetime | None = None,
    now: datetime | None = None,
) -> int:
    """Calculate how many 15 minute quarters are required to reach target temp."""

    if now is None:
        now = dt_util.now()

    if heating_start_time:
        time_until_heating = (heating_start_time - now).total_seconds() / 3600
        if time_until_heating > 0:
            temp_drop = time_until_heating * constraints.cooling_rate
            temp_at_heating_start = max(
                constraints.min_temperature, current_temp - temp_drop
            )
        else:
            temp_at_heating_start = current_temp
    else:
        temp_at_heating_start = current_temp

    temp_increase_needed = constraints.max_temperature - temp_at_heating_start
    if temp_increase_needed <= 0:
        return 0

    heating_time_hours = temp_increase_needed / constraints.heating_rate
    return max(1, int(heating_time_hours * 4) + 1)


def find_consecutive_window(
    valid_prices: Sequence[tuple[datetime, float]],
    required_quarters: int,
) -> HeatingWindow | None:
    """Return the cheapest consecutive window matching the required quarters."""

    best_window: HeatingWindow | None = None
    best_avg_price = math.inf

    for i in range(len(valid_prices) - required_quarters + 1):
        window_prices = valid_prices[i : i + required_quarters]
        timestamps = sorted(t for t, _ in window_prices)

        if any(
            (timestamps[j + 1] - timestamps[j]).total_seconds() > 900
            for j in range(len(timestamps) - 1)
        ):
            continue

        avg_price = sum(p for _, p in window_prices) / len(window_prices)
        if avg_price < best_avg_price:
            best_avg_price = avg_price
            best_window = HeatingWindow(
                start=timestamps[0],
                end=timestamps[-1] + timedelta(minutes=15),
            )

    return best_window


def has_significant_gaps(quarters: Sequence[tuple[datetime, float]]) -> bool:
    """Return True when quarters contain gaps greater than 15 minutes."""

    timestamps = sorted(t for t, _ in quarters)
    return any(
        (timestamps[i + 1] - timestamps[i]).total_seconds() > 900
        for i in range(len(timestamps) - 1)
    )


def calculate_true_cost(
    quarters: Sequence[tuple[datetime, float]],
    *,
    is_consecutive: bool,
) -> float:
    """Calculate cost including penalties for large gaps."""

    if not quarters:
        return math.inf

    price_sum = sum(price for _, price in quarters)
    base_cost = price_sum * DEFAULT_BASE_ENERGY / len(quarters)

    if is_consecutive:
        return base_cost

    timestamps = sorted(t for t, _ in quarters)
    prices_dict = dict(quarters)
    heat_loss_penalty = 0.0

    for i in range(len(timestamps) - 1):
        gap_seconds = (timestamps[i + 1] - timestamps[i]).total_seconds()
        if gap_seconds <= 900:
            continue

        gap_hours = (gap_seconds - 900) / 3600
        if gap_hours <= 0:
            continue

        temp_drop = min(gap_hours * DEFAULT_COOLING_RATE, 5.0)
        extra_energy = temp_drop * DEFAULT_ENERGY_PER_DEGREE
        reheat_price = prices_dict.get(timestamps[i + 1], price_sum / len(quarters))
        heat_loss_penalty += extra_energy * reheat_price

    return base_cost + heat_loss_penalty


def find_topup_quarter(
    base_window: HeatingWindow,
    *,
    prices: Sequence[tuple[datetime, float]],
    target_datetime: datetime,
    constraints: HeatingConstraints,
    current_temp: float | None = None,
) -> HeatingWindow | None:
    """Return extended window if a top-up is required to stay above minimum temp."""

    if current_temp is None:
        return None

    cooling_duration = (target_datetime - base_window.end).total_seconds() / 3600
    temp_drop = cooling_duration * constraints.cooling_rate
    final_temp = constraints.max_temperature - temp_drop

    if final_temp >= constraints.min_shower_temperature:
        return None

    temp_deficit = constraints.min_shower_temperature - final_temp
    temp_per_quarter = constraints.heating_rate / 4
    topup_quarters = max(1, math.ceil(temp_deficit / temp_per_quarter))

    available_topup = [
        (timestamp, price)
        for timestamp, price in prices
        if base_window.end <= timestamp < target_datetime - timedelta(minutes=15)
    ]

    if not available_topup:
        return None

    topup_quarters = min(topup_quarters, len(available_topup))

    available_topup.sort(key=lambda x: x[1])
    selected = available_topup[:topup_quarters]
    last_timestamp = sorted(t for t, _ in selected)[-1]

    return HeatingWindow(base_window.start, last_timestamp + timedelta(minutes=15))


def build_schedule(window: HeatingWindow) -> dict[str, str]:
    """Convert a heating window into the BSBLan schedule format."""

    start_time_local = dt_util.as_local(window.start)
    end_time_local = dt_util.as_local(window.end)
    time_range = (
        f"{start_time_local.strftime('%H:%M')}-{end_time_local.strftime('%H:%M')}"
    )

    schedule: dict[str, str] = {}
    current_date = start_time_local.date()
    end_date = end_time_local.date()

    if current_date == end_date:
        day_name = start_time_local.strftime("%A").lower()
        schedule[day_name] = time_range
        return schedule

    start_day = start_time_local.strftime("%A").lower()
    end_day = end_time_local.strftime("%A").lower()
    schedule[start_day] = f"{start_time_local.strftime('%H:%M')}-23:59"
    schedule[end_day] = f"00:00-{end_time_local.strftime('%H:%M')}"
    return schedule


def calculate_cost(
    prices: Iterable[tuple[datetime, float]],
    window: HeatingWindow,
) -> float:
    """Estimate the energy cost for the provided window."""

    return sum(
        price for timestamp, price in prices if window.start <= timestamp < window.end
    )
