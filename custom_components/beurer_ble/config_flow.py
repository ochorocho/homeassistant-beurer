"""Config flow for the Beurer BLE (BF720) integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

from .const import (
    BEURER_COMPANY_ID,
    CONF_ADDRESS,
    CONF_NAME,
    CONF_PIN,
    CONF_USER_INDEX,
    CONF_USERS,
    DOMAIN,
    LOCAL_NAME_PREFIX,
)


def _is_beurer(info: BluetoothServiceInfoBleak) -> bool:
    return (info.name or "").upper().startswith(LOCAL_NAME_PREFIX) or (
        BEURER_COMPANY_ID in info.manufacturer_data
    )


def _user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "")): str,
            vol.Required(CONF_USER_INDEX, default=defaults.get(CONF_USER_INDEX, 1)): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=255)
            ),
            vol.Required(CONF_PIN, default=defaults.get(CONF_PIN)): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=9999)
            ),
        }
    )


class BeurerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Beurer BLE."""

    VERSION = 1

    def __init__(self) -> None:
        self._address: str | None = None
        self._name: str = "Beurer BF720"
        self._discovered: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a device discovered via Bluetooth."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._address = discovery_info.address
        self._name = discovery_info.name or self._name
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered device before setting it up."""
        if user_input is not None:
            return await self.async_step_add_user()
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._name},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual setup: pick from discovered Beurer scales."""
        if user_input is not None:
            self._address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(self._address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self._name = self._discovered.get(self._address, self._name)
            return await self.async_step_add_user()

        current = self._async_current_ids()
        for info in async_discovered_service_info(self.hass):
            if info.address not in current and _is_beurer(info):
                self._discovered[info.address] = info.name or info.address
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(self._discovered)}),
        )

    async def async_step_add_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the first on-scale user (index + consent PIN)."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._name,
                data={CONF_ADDRESS: self._address, CONF_NAME: self._name},
                options={CONF_USERS: [user_input]},
            )
        return self.async_show_form(step_id="add_user", data_schema=_user_schema())

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        """Return the options flow."""
        return BeurerOptionsFlow(config_entry)


class BeurerOptionsFlow(OptionsFlow):
    """Add or remove on-scale users."""

    def __init__(self, config_entry) -> None:
        """Store the entry under a private name (avoids the reserved attribute)."""
        self._entry = config_entry

    @property
    def _users(self) -> list[dict[str, Any]]:
        return list(self._entry.options.get(CONF_USERS, []))

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the add/remove menu."""
        return self.async_show_menu(step_id="init", menu_options=["add_user", "remove_user"])

    async def async_step_add_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a user slot."""
        errors: dict[str, str] = {}
        if user_input is not None:
            users = self._users
            if any(u[CONF_USER_INDEX] == user_input[CONF_USER_INDEX] for u in users):
                errors["base"] = "index_exists"
            else:
                users.append(user_input)
                return self.async_create_entry(title="", data={CONF_USERS: users})
        return self.async_show_form(
            step_id="add_user", data_schema=_user_schema(), errors=errors
        )

    async def async_step_remove_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove a user slot."""
        users = self._users
        if not users:
            return self.async_abort(reason="no_users")
        if user_input is not None:
            remaining = [
                u for u in users if str(u[CONF_USER_INDEX]) != user_input["user_index"]
            ]
            return self.async_create_entry(title="", data={CONF_USERS: remaining})
        choices = {
            str(u[CONF_USER_INDEX]): f"{u.get(CONF_NAME) or 'User'} (index {u[CONF_USER_INDEX]})"
            for u in users
        }
        return self.async_show_form(
            step_id="remove_user",
            data_schema=vol.Schema({vol.Required("user_index"): vol.In(choices)}),
        )
