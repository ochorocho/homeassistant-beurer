"""The Beurer BLE (BF720) integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_ADDRESS, CONF_PIN, CONF_USER_INDEX, CONF_USERS
from .coordinator import BeurerCoordinator
from .device import UserCredential

PLATFORMS: list[Platform] = [Platform.SENSOR]

type BeurerConfigEntry = ConfigEntry[BeurerCoordinator]


def _users_from_entry(entry: BeurerConfigEntry) -> list[UserCredential]:
    return [
        UserCredential(user_index=user[CONF_USER_INDEX], pin=user[CONF_PIN])
        for user in entry.options.get(CONF_USERS, [])
    ]


async def async_setup_entry(hass: HomeAssistant, entry: BeurerConfigEntry) -> bool:
    """Set up Beurer BLE from a config entry."""
    coordinator = BeurerCoordinator(
        hass, entry.data[CONF_ADDRESS], _users_from_entry(entry)
    )
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(coordinator.async_start())
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: BeurerConfigEntry) -> None:
    """Reload when the user list (options) changes."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: BeurerConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
