"""Sensor platform for Home Energy Management System."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import CURRENCY_EURO, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HomeEMSConfigEntry
from .coordinator import HomeEMSCoordinator


@dataclass(frozen=True, kw_only=True)
class HomeEMSSensorEntityDescription(SensorEntityDescription):
    """Describes Home EMS sensor entity."""

    value_fn: Callable[[HomeEMSCoordinator], StateType | datetime]
    available_fn: Callable[[HomeEMSCoordinator], bool] = lambda _: True


SENSORS: tuple[HomeEMSSensorEntityDescription, ...] = (
    HomeEMSSensorEntityDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=["idle", "active", "error"],
        value_fn=lambda coordinator: coordinator.status,
    ),
    HomeEMSSensorEntityDescription(
        key="next_schedule_time",
        translation_key="next_schedule_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda coordinator: coordinator.next_schedule_time,
        available_fn=lambda coordinator: coordinator.next_schedule_time is not None,
    ),
    HomeEMSSensorEntityDescription(
        key="estimated_cost",
        translation_key="estimated_cost",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda coordinator: coordinator.estimated_cost,
        available_fn=lambda coordinator: coordinator.estimated_cost is not None,
    ),
    HomeEMSSensorEntityDescription(
        key="last_update",
        translation_key="last_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: coordinator.last_update,
        available_fn=lambda coordinator: coordinator.last_update is not None,
    ),
    HomeEMSSensorEntityDescription(
        key="price_entity",
        translation_key="price_entity",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: (
            coordinator.config_entry.data.get("price_entity")
            if coordinator.config_entry
            else None
        ),
    ),
    HomeEMSSensorEntityDescription(
        key="target_device",
        translation_key="target_device",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: (
            coordinator.config_entry.data.get("target_device")
            if coordinator.config_entry
            else None
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeEMSConfigEntry,
    async_add_entities: AddEntitiesCallback,  # pylint: disable=hass-argument-type
) -> None:
    """Set up Home EMS sensor platform."""
    coordinator = entry.runtime_data

    async_add_entities(
        HomeEMSSensor(coordinator, description) for description in SENSORS
    )


class HomeEMSSensor(CoordinatorEntity[HomeEMSCoordinator], SensorEntity):
    """Representation of a Home EMS sensor."""

    _attr_has_entity_name = True
    entity_description: HomeEMSSensorEntityDescription

    def __init__(
        self,
        coordinator: HomeEMSCoordinator,
        description: HomeEMSSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        assert coordinator.config_entry is not None
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> StateType | datetime:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return super().available and self.entity_description.available_fn(
            self.coordinator
        )
