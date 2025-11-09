"""Coordinator for Home Energy Management System."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
import math
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_HEATING_DURATION,
    CONF_MAX_TEMPERATURE,
    CONF_MIN_SHOWER_TEMPERATURE,
    CONF_MIN_TEMPERATURE,
    CONF_PRICE_ENTITY,
    CONF_TARGET_DEVICE,
    CONF_TARGET_TIME,
    CONF_TEMPERATURE_SENSOR,
    CONF_UPDATE_TIME,
    DEFAULT_BASE_ENERGY,
    DEFAULT_COOLING_RATE,
    DEFAULT_ENERGY_PER_DEGREE,
    DEFAULT_HEATING_RATE,
    DEFAULT_MIN_SHOWER_TEMPERATURE,
    DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


class HomeEMSCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to manage energy optimization."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{config_entry.entry_id}",
            update_interval=timedelta(hours=1),  # Check hourly
            config_entry=config_entry,
        )
        self.config_entry = config_entry
        self._last_schedule_update: datetime | None = None
        self._next_schedule: dict[str, str] | None = None
        self._estimated_cost: float | None = None
        self._learned_heating_rate: float | None = None
        self._learned_cooling_rate: float | None = None
        self._temperature_history: list[tuple[datetime, float]] = []

    @property
    def price_entity_id(self) -> str:
        """Return the price entity ID."""
        assert self.config_entry is not None
        return self.config_entry.options[CONF_PRICE_ENTITY]

    @property
    def target_device_id(self) -> str:
        """Return the target device ID."""
        assert self.config_entry is not None
        return self.config_entry.data[CONF_TARGET_DEVICE]

    @property
    def target_time(self) -> str:
        """Return the target ready time."""
        assert self.config_entry is not None
        return self.config_entry.options[CONF_TARGET_TIME]

    @property
    def heating_duration(self) -> float:
        """Return the heating duration in hours."""
        assert self.config_entry is not None
        return self.config_entry.options[CONF_HEATING_DURATION]

    @property
    def min_temperature(self) -> float:
        """Return the minimum temperature."""
        assert self.config_entry is not None
        return self.config_entry.options[CONF_MIN_TEMPERATURE]

    @property
    def max_temperature(self) -> float:
        """Return the maximum temperature."""
        assert self.config_entry is not None
        return self.config_entry.options[CONF_MAX_TEMPERATURE]

    @property
    def update_time(self) -> str:
        """Return the daily update time."""
        assert self.config_entry is not None
        return self.config_entry.options[CONF_UPDATE_TIME]

    @property
    def min_shower_temperature(self) -> float:
        """Return the minimum acceptable shower temperature."""
        assert self.config_entry is not None
        return self.config_entry.options.get(
            CONF_MIN_SHOWER_TEMPERATURE, DEFAULT_MIN_SHOWER_TEMPERATURE
        )

    @property
    def temperature_sensor_id(self) -> str | None:
        """Return the temperature sensor entity ID."""
        assert self.config_entry is not None
        return self.config_entry.options.get(CONF_TEMPERATURE_SENSOR)

    @property
    def heating_rate(self) -> float:
        """Return the heating rate (°C per hour)."""
        return self._learned_heating_rate or DEFAULT_HEATING_RATE

    @property
    def cooling_rate(self) -> float:
        """Return the cooling rate (°C per hour)."""
        return self._learned_cooling_rate or DEFAULT_COOLING_RATE

    @property
    def next_schedule(self) -> dict[str, str] | None:
        """Return the next calculated schedule."""
        return self._next_schedule

    @property
    def estimated_cost(self) -> float | None:
        """Return the estimated cost for the schedule."""
        return self._estimated_cost

    @property
    def last_schedule_update(self) -> datetime | None:
        """Return when the schedule was last updated."""
        return self._last_schedule_update

    @property
    def status(self) -> str:
        """Return the current status of the coordinator."""
        if self.last_update_success is False:
            return "error"
        if self._next_schedule is not None:
            return "active"
        return "idle"

    @property
    def next_schedule_time(self) -> datetime | None:
        """Return the start time of the next heating schedule."""
        if not self._next_schedule:
            return None
        try:
            # Parse time string from schedule (format: "HH:MM")
            time_str = next(iter(self._next_schedule.keys()))
            hour, minute = map(int, time_str.split(":"))
            now = dt_util.now()
            schedule_time = now.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
        except (ValueError, StopIteration) as err:
            _LOGGER.warning("Failed to parse schedule time: %s", err)
            return None
        else:
            # If time has already passed today, it must be tomorrow
            if schedule_time < now:
                schedule_time += timedelta(days=1)
            return schedule_time

    @property
    def last_update(self) -> datetime | None:
        """Return the last update timestamp."""
        return self._last_schedule_update

    def _get_current_temperature(self) -> float | None:
        """Get current water temperature from sensor."""
        if not self.temperature_sensor_id:
            # Try to find temperature sensor in device entities
            temp_sensor = self._find_temperature_sensor()
            if not temp_sensor:
                _LOGGER.warning("No temperature sensor configured or found")
                return None
        else:
            temp_sensor = self.temperature_sensor_id

        state = self.hass.states.get(temp_sensor)
        if not state:
            _LOGGER.warning("Temperature sensor %s not found", temp_sensor)
            return None

        try:
            return float(state.state)
        except (ValueError, TypeError) as err:
            _LOGGER.warning("Invalid temperature value: %s", err)
            return None

    def _find_temperature_sensor(self) -> str | None:
        """Find temperature sensor for the water heater device."""
        device_registry = dr.async_get(self.hass)
        device_entry = device_registry.async_get(self.target_device_id)

        if not device_entry:
            return None

        # Look for entities associated with this device
        entity_registry = er.async_get(self.hass)
        entities = er.async_entries_for_device(entity_registry, self.target_device_id)

        # Find temperature sensor entity
        for entity in entities:
            if entity.domain == "sensor" and "temperature" in entity.entity_id.lower():
                return entity.entity_id

        return None

    def _update_temperature_history(self, temperature: float) -> None:
        """Update temperature history for learning heating/cooling rates."""
        now = dt_util.now()
        self._temperature_history.append((now, temperature))

        # Keep only last 24 hours of data
        cutoff = now - timedelta(hours=24)
        self._temperature_history = [
            (ts, temp) for ts, temp in self._temperature_history if ts > cutoff
        ]

    def _learn_heating_rate(self) -> None:
        """Learn heating rate from temperature history."""
        if len(self._temperature_history) < 2:
            return

        # Find heating periods (temperature increasing)
        heating_rates = []

        for i in range(1, len(self._temperature_history)):
            time_prev, temp_prev = self._temperature_history[i - 1]
            time_curr, temp_curr = self._temperature_history[i]

            time_diff_hours = (time_curr - time_prev).total_seconds() / 3600
            temp_diff = temp_curr - temp_prev

            # Heating if temperature increased
            if temp_diff > 0.5 and time_diff_hours > 0.1:
                rate = temp_diff / time_diff_hours
                # Sanity check: reasonable heating rate (5-40°C/hour)
                if 5 <= rate <= 40:
                    heating_rates.append(rate)

        if heating_rates:
            # Use median to avoid outliers
            heating_rates.sort()
            median_rate = heating_rates[len(heating_rates) // 2]
            self._learned_heating_rate = median_rate
            _LOGGER.info("Learned heating rate: %.1f°C/hour", median_rate)

    def _learn_cooling_rate(self) -> None:
        """Learn cooling rate from temperature history."""
        if len(self._temperature_history) < 2:
            return

        # Find cooling periods (temperature decreasing, no heating)
        cooling_rates = []

        for i in range(1, len(self._temperature_history)):
            time_prev, temp_prev = self._temperature_history[i - 1]
            time_curr, temp_curr = self._temperature_history[i]

            time_diff_hours = (time_curr - time_prev).total_seconds() / 3600
            temp_diff = temp_curr - temp_prev

            # Cooling if temperature decreased
            if temp_diff < -0.2 and time_diff_hours > 0.5:
                rate = abs(temp_diff) / time_diff_hours
                # Sanity check: reasonable cooling rate (0.1-3°C/hour)
                if 0.1 <= rate <= 3:
                    cooling_rates.append(rate)

        if cooling_rates:
            # Use median to avoid outliers
            cooling_rates.sort()
            median_rate = cooling_rates[len(cooling_rates) // 2]
            self._learned_cooling_rate = median_rate
            _LOGGER.info("Learned cooling rate: %.1f°C/hour", median_rate)

    def _calculate_required_quarters(self, current_temp: float) -> int:
        """Calculate required heating quarters based on current temperature.

        Args:
            current_temp: Current water temperature

        Returns:
            Number of quarter-hour periods needed
        """
        target_temp = self.max_temperature
        temp_increase_needed = target_temp - current_temp

        if temp_increase_needed <= 0:
            return 0

        # Calculate heating time needed
        heating_time_hours = temp_increase_needed / self.heating_rate

        # Convert to quarters (round up)
        required_quarters = max(1, int(heating_time_hours * 4) + 1)

        _LOGGER.debug(
            "Temperature rise needed: %.1f°C, heating time: %.2f hours, quarters: %d",
            temp_increase_needed,
            heating_time_hours,
            required_quarters,
        )

        return required_quarters

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from price entity and calculate optimal schedule."""
        now = dt_util.now()

        # Track current temperature for learning
        current_temp = self._get_current_temperature()
        if current_temp is not None:
            self._update_temperature_history(current_temp)
            # Learn heating and cooling rates from history
            self._learn_heating_rate()
            self._learn_cooling_rate()

        update_time_str = self.update_time

        # Parse update time
        try:
            update_hour, update_minute = map(int, update_time_str.split(":"))
            today_update = now.replace(
                hour=update_hour, minute=update_minute, second=0, microsecond=0
            )
        except (ValueError, AttributeError) as err:
            _LOGGER.error("Invalid update time format: %s", update_time_str)
            raise UpdateFailed(f"Invalid update time: {err}") from err

        # Check if we should update the schedule
        should_update = False

        if self._last_schedule_update is None:
            should_update = True
            _LOGGER.debug("First run - will calculate schedule")
        elif now >= today_update and (
            self._last_schedule_update < today_update
            or self._last_schedule_update.date() < now.date()
        ):
            should_update = True
            _LOGGER.debug("Daily update time reached - will recalculate schedule")

        if should_update:
            try:
                success = await self._calculate_and_apply_schedule()
                if success:
                    self._last_schedule_update = now
                else:
                    _LOGGER.info(
                        "Price data not yet available, will retry on next update"
                    )
            except Exception as err:
                _LOGGER.exception("Failed to calculate/apply schedule")
                raise UpdateFailed(f"Schedule calculation failed: {err}") from err

        return {
            "status": "active" if self._next_schedule else "idle",
            "next_schedule": self._next_schedule,
            "estimated_cost": self._estimated_cost,
            "last_update": self._last_schedule_update,
        }

    async def _calculate_and_apply_schedule(self) -> bool:
        """Calculate optimal schedule and apply it to the device.

        Returns True if schedule was successfully calculated and applied,
        False if price data is not yet available.
        """
        _LOGGER.info("Calculating optimal heating schedule")

        # Get price data
        prices = await self._get_price_data()
        if not prices:
            _LOGGER.warning("No price data available yet")
            return False

        # Check if we have sufficient price data (need data until target time)
        if not self._has_sufficient_price_data(prices):
            _LOGGER.warning("Insufficient price data available, will retry later")
            return False

        # Calculate optimal heating window
        optimal_window = self._find_cheapest_window(prices)
        if not optimal_window:
            _LOGGER.warning("Could not find optimal heating window")
            return False

        # Build schedule
        schedule = self._build_schedule(optimal_window)
        self._next_schedule = schedule

        # Calculate estimated cost
        self._estimated_cost = self._calculate_cost(prices, optimal_window)

        # Apply schedule to device
        await self._apply_schedule_to_device(schedule)

        _LOGGER.info(
            "Scheduled heating: %s, estimated cost: %.2f",
            optimal_window,
            self._estimated_cost or 0,
        )
        return True

    def _has_sufficient_price_data(self, prices: list[tuple[datetime, float]]) -> bool:
        """Check if we have sufficient price data to calculate schedule."""
        if not prices:
            return False

        # Parse target time
        try:
            target_hour, target_minute = map(int, self.target_time.split(":"))
        except (ValueError, AttributeError):
            return False

        # Get target datetime (tomorrow if target time already passed today)
        now = dt_util.now()
        target_datetime = now.replace(
            hour=target_hour, minute=target_minute, second=0, microsecond=0
        )
        if target_datetime <= now:
            target_datetime += timedelta(days=1)

        # Check if we have price data up to target time
        latest_price_time = max(timestamp for timestamp, _ in prices)
        return latest_price_time >= target_datetime

    async def _get_price_data(self) -> list[tuple[datetime, float]]:
        """Get price data from the price entity."""
        price_entity = self.hass.states.get(self.price_entity_id)
        if not price_entity:
            _LOGGER.error("Price entity %s not found", self.price_entity_id)
            return []

        prices: list[tuple[datetime, float]] = []

        # Try to get prices from attributes (common for Tibber, NordPool)
        # These integrations provide quarter-hourly data
        if "today" in price_entity.attributes:
            today_prices = price_entity.attributes["today"]
            for entry in today_prices:
                if isinstance(entry, dict) and "start" in entry and "value" in entry:
                    timestamp = dt_util.parse_datetime(entry["start"])
                    if timestamp:
                        prices.append((timestamp, float(entry["value"])))

        if "tomorrow" in price_entity.attributes:
            tomorrow_prices = price_entity.attributes["tomorrow"]
            for entry in tomorrow_prices:
                if isinstance(entry, dict) and "start" in entry and "value" in entry:
                    timestamp = dt_util.parse_datetime(entry["start"])
                    if timestamp:
                        prices.append((timestamp, float(entry["value"])))

        # Also try raw_today and raw_tomorrow (alternative attribute names)
        if "raw_today" in price_entity.attributes:
            raw_today = price_entity.attributes["raw_today"]
            for entry in raw_today:
                if isinstance(entry, dict) and "start" in entry and "value" in entry:
                    timestamp = dt_util.parse_datetime(entry["start"])
                    if timestamp:
                        prices.append((timestamp, float(entry["value"])))

        if "raw_tomorrow" in price_entity.attributes:
            raw_tomorrow = price_entity.attributes["raw_tomorrow"]
            for entry in raw_tomorrow:
                if isinstance(entry, dict) and "start" in entry and "value" in entry:
                    timestamp = dt_util.parse_datetime(entry["start"])
                    if timestamp:
                        prices.append((timestamp, float(entry["value"])))

        # If no attribute prices, log current price for debugging
        if not prices:
            try:
                current_price = float(price_entity.state)
                _LOGGER.warning(
                    "Price entity has no quarter-hourly data. Current price: %.2f",
                    current_price,
                )
            except (ValueError, TypeError):
                _LOGGER.error(
                    "Could not get price data from entity %s", self.price_entity_id
                )

        return prices

    def _find_cheapest_window(
        self, prices: list[tuple[datetime, float]]
    ) -> tuple[datetime, datetime] | None:
        """Find the cheapest heating window with dynamic quarter calculation."""
        if not prices:
            return None

        # Get current temperature to calculate required heating
        current_temp = self._get_current_temperature()
        if current_temp is None:
            _LOGGER.warning("Cannot get current temperature, using fixed duration")
            required_quarters = max(1, int(self.heating_duration * 4))
        else:
            # Calculate required quarters dynamically based on current temp
            required_quarters = self._calculate_required_quarters(current_temp)
            _LOGGER.info(
                "Current temp: %.1f°C, target: %.1f°C, required quarters: %d",
                current_temp,
                self.max_temperature,
                required_quarters,
            )

        # Parse target time
        try:
            target_hour, target_minute = map(int, self.target_time.split(":"))
        except (ValueError, AttributeError):
            _LOGGER.error("Invalid target time format: %s", self.target_time)
            return None

        # Get target datetime (tomorrow if target time already passed today)
        now = dt_util.now()
        target_datetime = now.replace(
            hour=target_hour, minute=target_minute, second=0, microsecond=0
        )
        if target_datetime <= now:
            target_datetime += timedelta(days=1)

        # Calculate when heating needs to END considering cooling
        # We want temp >= min_shower_temperature at target_time
        min_end_temp = self.min_shower_temperature
        target_heat_temp = self.max_temperature

        # Calculate acceptable cooling window
        max_cooling_time_hours = (target_heat_temp - min_end_temp) / self.cooling_rate
        latest_heating_end = target_datetime - timedelta(hours=max_cooling_time_hours)

        # Heating must start before this time
        heating_duration_hours = required_quarters * 0.25
        latest_heating_start = latest_heating_end - timedelta(
            hours=heating_duration_hours
        )

        _LOGGER.debug(
            "Latest heating start: %s, end: %s (allows %.1f°C cooling to target time)",
            latest_heating_start,
            latest_heating_end,
            max_cooling_time_hours * self.cooling_rate,
        )

        # Filter prices that are within valid window
        valid_prices = [
            (timestamp, price)
            for timestamp, price in prices
            if now <= timestamp <= latest_heating_start
        ]

        if not valid_prices:
            _LOGGER.warning(
                "No valid price data found between now and %s", latest_heating_start
            )
            return None

        # Sort by price
        valid_prices.sort(key=lambda x: x[1])

        # Try to find best consecutive window
        # (required_quarters already calculated above based on current temperature)
        consecutive_window = self._find_consecutive_window(
            valid_prices, required_quarters
        )

        # Try to find non-consecutive cheapest quarters
        non_consecutive_quarters = valid_prices[:required_quarters]

        # Smart decision: compare true costs including heat loss
        if consecutive_window and self._has_significant_gaps(non_consecutive_quarters):
            consecutive_cost = self._calculate_true_cost(
                [
                    valid_prices[i]
                    for i in range(len(valid_prices))
                    if valid_prices[i][0] >= consecutive_window[0]
                    and valid_prices[i][0] < consecutive_window[1]
                ],
                is_consecutive=True,
            )

            non_consecutive_cost = self._calculate_true_cost(
                non_consecutive_quarters,
                is_consecutive=False,
            )

            _LOGGER.debug(
                "Cost comparison - Consecutive: %.2f, Non-consecutive: %.2f",
                consecutive_cost,
                non_consecutive_cost,
            )

            # Choose cheaper option
            if non_consecutive_cost < consecutive_cost:
                _LOGGER.info(
                    "Choosing non-consecutive window (saves %.2f)",
                    consecutive_cost - non_consecutive_cost,
                )
                timestamps = sorted(t for t, _ in non_consecutive_quarters)
                base_window = (timestamps[0], timestamps[-1] + timedelta(minutes=15))

                # Check if we need a top-up quarter to prevent excessive cooling
                topup_window = self._find_topup_quarter(
                    base_window, prices, target_datetime, current_temp
                )
                return topup_window if topup_window else base_window

            _LOGGER.info("Choosing consecutive window (more efficient)")
            return consecutive_window

        # If we found consecutive window, use it
        if consecutive_window:
            return consecutive_window

        # Fallback: use cheapest quarters even if not consecutive
        _LOGGER.info("No consecutive window found, using cheapest quarters")
        timestamps = sorted(t for t, _ in non_consecutive_quarters)
        base_window = (timestamps[0], timestamps[-1] + timedelta(minutes=15))

        # Check if we need a top-up quarter to prevent excessive cooling
        topup_window = self._find_topup_quarter(
            base_window, prices, target_datetime, current_temp
        )
        if topup_window:
            return topup_window

        return base_window

    def _find_topup_quarter(
        self,
        base_window: tuple[datetime, datetime],
        prices: list[tuple[datetime, float]],
        target_datetime: datetime,
        current_temp: float | None,
    ) -> tuple[datetime, datetime] | None:
        """Find if a top-up quarter is needed to prevent temperature drop below minimum.

        Args:
            base_window: The initially scheduled heating window (start, end)
            prices: All available price data
            target_datetime: When the water needs to be ready
            current_temp: Current water temperature

        Returns:
            Modified window with top-up quarter if needed, or None if no top-up needed
        """
        if current_temp is None:
            return None

        # Calculate expected temperature at target time
        heating_end = base_window[1]
        cooling_duration = (target_datetime - heating_end).total_seconds() / 3600
        temp_drop = cooling_duration * self.cooling_rate
        final_temp = self.max_temperature - temp_drop

        # Check if temperature will drop below minimum
        if final_temp >= self.min_shower_temperature:
            _LOGGER.debug(
                "No top-up needed: final temp %.1f°C >= min %.1f°C",
                final_temp,
                self.min_shower_temperature,
            )
            return None

        # Temperature will be too low - need a top-up quarter
        temp_deficit = self.min_shower_temperature - final_temp
        _LOGGER.info(
            "Top-up needed: final temp %.1f°C < min %.1f°C (deficit: %.1f°C)",
            final_temp,
            self.min_shower_temperature,
            temp_deficit,
        )

        # Calculate how many quarters we need to add
        # Each quarter adds heating_rate/4 degrees
        temp_per_quarter = self.heating_rate / 4
        topup_quarters = max(1, math.ceil(temp_deficit / temp_per_quarter))

        _LOGGER.debug(
            "Need %d top-up quarter(s) to add %.1f°C",
            topup_quarters,
            topup_quarters * temp_per_quarter,
        )

        # Find the cheapest quarters between heating_end and target_time
        # These quarters will provide a last-minute boost
        available_topup = [
            (timestamp, price)
            for timestamp, price in prices
            if heating_end <= timestamp < target_datetime - timedelta(minutes=15)
        ]

        if len(available_topup) < topup_quarters:
            _LOGGER.warning(
                "Not enough time slots for top-up heating (need %d, have %d)",
                topup_quarters,
                len(available_topup),
            )
            # Return the best we can do
            if not available_topup:
                return None
            topup_quarters = len(available_topup)

        # Sort by price and take the cheapest
        available_topup.sort(key=lambda x: x[1])
        selected_topup = available_topup[:topup_quarters]

        # Get all timestamps (base + topup)
        all_timestamps = sorted([base_window[0]] + [t for t, _ in selected_topup])

        _LOGGER.info(
            "Adding %d top-up quarter(s) at %s (avg price: %.3f)",
            topup_quarters,
            ", ".join(t.strftime("%H:%M") for t, _ in selected_topup),
            sum(p for _, p in selected_topup) / len(selected_topup),
        )

        # Return extended window covering base heating + top-up
        return (base_window[0], all_timestamps[-1] + timedelta(minutes=15))

    def _find_consecutive_window(
        self,
        valid_prices: list[tuple[datetime, float]],
        required_quarters: int,
    ) -> tuple[datetime, datetime] | None:
        """Find the best consecutive heating window."""
        best_window = None
        best_avg_price = math.inf

        for i in range(len(valid_prices) - required_quarters + 1):
            window_prices = valid_prices[i : i + required_quarters]

            # Check if periods are consecutive (quarters are 15 minutes = 900 seconds)
            timestamps = [t for t, _ in window_prices]
            timestamps.sort()

            is_consecutive = True
            for j in range(len(timestamps) - 1):
                time_diff = (timestamps[j + 1] - timestamps[j]).total_seconds()
                # Allow up to 900 seconds (15 minutes) between consecutive quarters
                if time_diff > 900:
                    is_consecutive = False
                    break

            if is_consecutive:
                avg_price = sum(p for _, p in window_prices) / len(window_prices)
                if avg_price < best_avg_price:
                    best_avg_price = avg_price
                    # End time is last quarter start + 15 minutes
                    best_window = (
                        timestamps[0],
                        timestamps[-1] + timedelta(minutes=15),
                    )

        return best_window

    def _has_significant_gaps(self, quarters: list[tuple[datetime, float]]) -> bool:
        """Check if there are significant gaps between quarters."""
        timestamps = sorted(t for t, _ in quarters)

        for i in range(len(timestamps) - 1):
            gap_seconds = (timestamps[i + 1] - timestamps[i]).total_seconds()
            # Gap longer than 15 minutes (not consecutive)
            if gap_seconds > 900:
                return True

        return False

    def _calculate_true_cost(
        self,
        quarters: list[tuple[datetime, float]],
        is_consecutive: bool,
    ) -> float:
        """Calculate true cost including heat loss penalty for gaps.

        Args:
            quarters: List of (timestamp, price) tuples
            is_consecutive: Whether quarters are consecutive

        Returns:
            Total cost in currency units
        """
        if not quarters:
            return math.inf

        # Base cost: sum of prices * base energy
        price_sum = sum(price for _, price in quarters)
        base_cost = price_sum * DEFAULT_BASE_ENERGY / len(quarters)

        if is_consecutive:
            return base_cost

        # Calculate heat loss penalty for gaps
        timestamps = sorted(t for t, _ in quarters)
        prices_dict = dict(quarters)

        heat_loss_penalty = 0.0

        for i in range(len(timestamps) - 1):
            gap_seconds = (timestamps[i + 1] - timestamps[i]).total_seconds()

            # Only penalize gaps longer than 15 minutes
            if gap_seconds > 900:
                gap_hours = (gap_seconds - 900) / 3600  # Subtract the normal 15 min

                # Only penalize if gap exceeds comfort threshold
                if gap_hours > 0:
                    # Calculate temperature drop during gap
                    temp_drop = min(gap_hours * DEFAULT_COOLING_RATE, 5.0)  # Cap at 5°C

                    # Calculate extra energy needed to compensate
                    extra_energy = temp_drop * DEFAULT_ENERGY_PER_DEGREE

                    # Price for reheating (use price after the gap)
                    reheat_price = prices_dict.get(
                        timestamps[i + 1], price_sum / len(quarters)
                    )

                    penalty = extra_energy * reheat_price
                    heat_loss_penalty += penalty

                    _LOGGER.debug(
                        "Gap detected: %.1f hours, temp drop: %.1f°C, penalty: %.2f",
                        gap_hours,
                        temp_drop,
                        penalty,
                    )

        return base_cost + heat_loss_penalty

    def _build_schedule(self, window: tuple[datetime, datetime]) -> dict[str, str]:
        """Build schedule dict for DHW service."""
        start_time, end_time = window

        # Format: "HH:MM-HH:MM"
        time_range = f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}"

        # Determine which day(s) the schedule applies to
        schedule: dict[str, str] = {}

        current_date = start_time.date()
        end_date = end_time.date()

        # Handle schedule spanning multiple days
        if current_date == end_date:
            day_name = start_time.strftime("%A").lower()
            schedule[day_name] = time_range
        else:
            # Start day gets start time to midnight
            day_name = start_time.strftime("%A").lower()
            schedule[day_name] = f"{start_time.strftime('%H:%M')}-23:59"

            # End day gets midnight to end time
            day_name = end_time.strftime("%A").lower()
            schedule[day_name] = f"00:00-{end_time.strftime('%H:%M')}"

        return schedule

    def _calculate_cost(
        self,
        prices: list[tuple[datetime, float]],
        window: tuple[datetime, datetime],
    ) -> float:
        """Calculate estimated cost for the heating window."""
        start_time, end_time = window

        total_cost = 0.0
        for timestamp, price in prices:
            if start_time <= timestamp < end_time:
                # Assume 1 kWh per hour (this is a simplification)
                total_cost += price

        return total_cost

    async def _apply_schedule_to_device(self, schedule: dict[str, str]) -> None:
        """Apply the calculated schedule to the target device."""
        # Get device information
        device_registry = dr.async_get(self.hass)
        device_entry = device_registry.async_get(self.target_device_id)

        if not device_entry:
            raise HomeAssistantError(
                f"Device {self.target_device_id} not found in registry"
            )

        _LOGGER.debug("Applying schedule to device %s: %s", device_entry.name, schedule)

        # Call BSBLan service to set hot water schedule
        try:
            await self.hass.services.async_call(
                "bsblan",
                "set_hot_water_schedule",
                {
                    "device": self.target_device_id,
                    "schedule": schedule,
                },
                blocking=True,
            )
            _LOGGER.info(
                "Successfully applied schedule to device %s", device_entry.name
            )
        except Exception as err:
            _LOGGER.error("Failed to apply schedule: %s", err)
            raise HomeAssistantError(f"Failed to apply schedule: {err}") from err
