"""The Home Energy Management System integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import Event, HomeAssistant, callback

from .coordinator import HomeEMSCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type HomeEMSConfigEntry = ConfigEntry[HomeEMSCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: HomeEMSConfigEntry) -> bool:
    """Set up Home Energy Management System from a config entry."""
    # Create coordinator
    coordinator = HomeEMSCoordinator(hass, entry)

    # Perform initial refresh (will be mostly no-op until HA is started)
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator in runtime data
    entry.runtime_data = coordinator

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    # Schedule immediate refresh after HA has fully started
    # This ensures all dependencies (Nordpool, BSBLan) are loaded
    @callback
    def schedule_first_refresh(event: Event) -> None:
        """Trigger refresh once HA has fully started."""
        coordinator.async_set_updated_data(coordinator.data)
        hass.async_create_task(coordinator.async_refresh())

    if hass.is_running:
        # HA already started, refresh immediately
        hass.async_create_task(coordinator.async_refresh())
    else:
        # Wait for HA to finish starting
        entry.async_on_unload(
            hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, schedule_first_refresh
            )
        )

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HomeEMSConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
