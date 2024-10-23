"""BSBLAN platform to control a compatible Water Heater Device."""

from __future__ import annotations

from typing import Any

from bsblan import BSBLANError

from homeassistant.components.water_heater import (
    STATE_ECO,
    STATE_ELECTRIC,
    STATE_OFF,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, STATE_ON, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BSBLanData
from .const import DOMAIN
from .entity import BSBLanEntity

PARALLEL_UPDATES = 1

# Mapping between BSBLan and HA operation modes
OPERATION_MODES = {
    "auto": STATE_ELECTRIC,  # Normal automatic operation
    "reduced": STATE_ECO,  # Energy saving mode
    "off": STATE_OFF,  # Protection mode
    "on": STATE_ON,  # Continuous comfort mode
}

OPERATION_MODES_REVERSE = {v: k for k, v in OPERATION_MODES.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up BSBLAN water heater based on a config entry."""
    data: BSBLanData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BSBLANWaterHeater(data)])


class BSBLANWaterHeater(BSBLanEntity, WaterHeaterEntity):
    """Defines a BSBLAN water heater entity."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
    )

    def __init__(self, data: BSBLanData) -> None:
        """Initialize BSBLAN water heater."""
        super().__init__(data.coordinator, data)
        self._attr_unique_id = f"{format_mac(data.device.MAC)}-water_heater"
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_operation_list = list(OPERATION_MODES_REVERSE.keys())

        # Set temperature limits based on device capabilities
        self._attr_min_temp = float(data.coordinator.data.dhw.reduced_setpoint.value)
        self._attr_max_temp = float(data.coordinator.data.dhw.nominal_setpoint.value)

    @property
    def current_operation(self) -> str | None:
        """Return current operation."""
        current_mode = self.coordinator.data.dhw.operating_mode.value
        return OPERATION_MODES.get(current_mode)

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        if self.coordinator.data.dhw.nominal_setpoint.value == "---":
            return None
        return float(self.coordinator.data.dhw.nominal_setpoint.value)

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        if self.coordinator.data.dhw.nominal_setpoint.value == "---":
            return None
        return float(self.coordinator.data.dhw.nominal_setpoint.value)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        try:
            await self.coordinator.client.set_hot_water(nominal_setpoint=temperature)
        except BSBLANError as err:
            raise HomeAssistantError(
                "Failed to set target temperature for water heater",
                translation_domain=DOMAIN,
                translation_key="set_temperature_error",
            ) from err

        await self.coordinator.async_request_refresh()

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set new operation mode."""
        bsblan_mode = OPERATION_MODES_REVERSE.get(operation_mode)
        if bsblan_mode is None:
            raise HomeAssistantError(
                f"Invalid operation mode: {operation_mode}",
                translation_domain=DOMAIN,
                translation_key="invalid_operation_mode",
            )

        try:
            await self.coordinator.client.set_hot_water(operating_mode=bsblan_mode)
        except BSBLANError as err:
            raise HomeAssistantError(
                "Failed to set operation mode for water heater",
                translation_domain=DOMAIN,
                translation_key="set_operation_mode_error",
            ) from err

        await self.coordinator.async_request_refresh()
