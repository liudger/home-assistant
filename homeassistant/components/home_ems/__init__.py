"""The Home Energy Management System integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import HomeEMSCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type HomeEMSConfigEntry = ConfigEntry[HomeEMSCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: HomeEMSConfigEntry) -> bool:
    """Set up Home Energy Management System from a config entry."""
    # Create coordinator
    coordinator = HomeEMSCoordinator(hass, entry)

    # Perform initial refresh
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator in runtime data
    entry.runtime_data = coordinator

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HomeEMSConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
