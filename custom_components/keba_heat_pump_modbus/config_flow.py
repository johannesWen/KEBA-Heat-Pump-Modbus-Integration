from __future__ import annotations

from typing import Any, Dict

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_UNIT_ID,
    CONF_SCAN_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_UNIT_ID,
    DEFAULT_SCAN_INTERVAL,
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for KEBA Heat Pump Modbus."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Dict[str, Any] | None = None
    ):
        """Handle the first step of the flow."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]

            # Ensure we don't add the same device twice
            await self.async_set_unique_id(f"{DOMAIN}_{host}")
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"KEBA Heat Pump ({host})",
                data=user_input,
            )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Optional(CONF_UNIT_ID, default=DEFAULT_UNIT_ID): int,
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                ): int,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow for KEBA Heat Pump Modbus."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(
        self, user_input: Dict[str, Any] | None = None
    ):
        """Manage the options."""
        return await self.async_step_user(user_input)

    async def async_step_user(
        self, user_input: Dict[str, Any] | None = None
    ):
        """Handle options step."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            # Only scan interval right now
            return self.async_create_entry(
                title="",
                data=user_input,
            )

        current_scan = self._entry.options.get(
            CONF_SCAN_INTERVAL,
            self._entry.data.get(
                CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
            ),
        )

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL, default=current_scan
                ): int,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )
