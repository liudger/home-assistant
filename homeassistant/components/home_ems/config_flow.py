"""Config flow for the Home Energy Management System integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN, SensorDeviceClass
from homeassistant.const import CONF_NAME
from homeassistant.helpers import selector
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaCommonFlowHandler,
    SchemaConfigFlowHandler,
    SchemaFlowError,
    SchemaFlowFormStep,
    SchemaFlowMenuStep,
)

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
    DEFAULT_HEATING_DURATION,
    DEFAULT_MAX_TEMPERATURE,
    DEFAULT_MIN_SHOWER_TEMPERATURE,
    DEFAULT_MIN_TEMPERATURE,
    DEFAULT_TARGET_TIME,
    DEFAULT_UPDATE_TIME,
    DOMAIN,
)


async def validate_water_heater_input(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate water heater configuration input."""
    # Validate temperature range
    if user_input[CONF_MIN_TEMPERATURE] >= user_input[CONF_MAX_TEMPERATURE]:
        raise SchemaFlowError("invalid_temperature_range")

    # Validate heating duration is positive
    if user_input[CONF_HEATING_DURATION] <= 0:
        raise SchemaFlowError("invalid_heating_duration")

    # Check if device is already configured
    target_device = user_input[CONF_TARGET_DEVICE]
    for entry in handler.parent_handler.hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_TARGET_DEVICE) == target_device:
            raise SchemaFlowError("already_configured")

    return user_input


async def get_water_heater_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Return schema for water heater configuration."""
    return vol.Schema(
        {
            vol.Required(CONF_NAME): selector.TextSelector(),
            vol.Required(CONF_TARGET_DEVICE): selector.DeviceSelector(
                selector.DeviceSelectorConfig(
                    integration="bsblan",
                    multiple=False,
                )
            ),
            vol.Required(CONF_PRICE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=SENSOR_DOMAIN,
                )
            ),
            vol.Required(
                CONF_TARGET_TIME, default=DEFAULT_TARGET_TIME
            ): selector.TimeSelector(),
            vol.Required(
                CONF_MIN_TEMPERATURE,
                default=DEFAULT_MIN_TEMPERATURE,
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=30,
                    max=80,
                    step=1,
                    unit_of_measurement="°C",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_MAX_TEMPERATURE,
                default=DEFAULT_MAX_TEMPERATURE,
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=40,
                    max=90,
                    step=1,
                    unit_of_measurement="°C",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_HEATING_DURATION,
                default=DEFAULT_HEATING_DURATION,
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.5,
                    max=12,
                    step=0.5,
                    unit_of_measurement="hours",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_MIN_SHOWER_TEMPERATURE,
                default=DEFAULT_MIN_SHOWER_TEMPERATURE,
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=35,
                    max=70,
                    step=1,
                    unit_of_measurement="°C",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(CONF_TEMPERATURE_SENSOR): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=SENSOR_DOMAIN,
                    device_class=SensorDeviceClass.TEMPERATURE,
                )
            ),
            vol.Required(
                CONF_UPDATE_TIME,
                default=DEFAULT_UPDATE_TIME,
            ): selector.TimeSelector(),
        }
    )


async def get_options_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Return schema for options flow."""
    # Get current options from the config entry
    options = handler.options if hasattr(handler, "options") else {}

    return vol.Schema(
        {
            vol.Required(
                CONF_PRICE_ENTITY,
                default=options.get(CONF_PRICE_ENTITY),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=SENSOR_DOMAIN,
                    device_class=SensorDeviceClass.MONETARY,
                )
            ),
            vol.Required(
                CONF_TARGET_TIME,
                default=options.get(CONF_TARGET_TIME, DEFAULT_TARGET_TIME),
            ): selector.TimeSelector(),
            vol.Required(
                CONF_MIN_TEMPERATURE,
                default=options.get(CONF_MIN_TEMPERATURE, DEFAULT_MIN_TEMPERATURE),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=30,
                    max=80,
                    step=1,
                    unit_of_measurement="°C",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_MAX_TEMPERATURE,
                default=options.get(CONF_MAX_TEMPERATURE, DEFAULT_MAX_TEMPERATURE),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=40,
                    max=90,
                    step=1,
                    unit_of_measurement="°C",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_HEATING_DURATION,
                default=options.get(CONF_HEATING_DURATION, DEFAULT_HEATING_DURATION),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.5,
                    max=12,
                    step=0.5,
                    unit_of_measurement="hours",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_UPDATE_TIME,
                default=options.get(CONF_UPDATE_TIME, DEFAULT_UPDATE_TIME),
            ): selector.TimeSelector(),
        }
    )


CONFIG_FLOW: dict[str, SchemaFlowFormStep | SchemaFlowMenuStep] = {
    "user": SchemaFlowMenuStep(["water_heater"]),
    "water_heater": SchemaFlowFormStep(
        get_water_heater_schema,
        validate_user_input=validate_water_heater_input,
    ),
}

OPTIONS_FLOW: dict[str, SchemaFlowFormStep | SchemaFlowMenuStep] = {
    "init": SchemaFlowFormStep(get_options_schema),
}


class ConfigFlowHandler(SchemaConfigFlowHandler, domain=DOMAIN):
    """Handle a config or options flow for Home Energy Management System."""

    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW

    VERSION = 1
    MINOR_VERSION = 1

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        """Return config entry title."""
        return options[CONF_NAME]
