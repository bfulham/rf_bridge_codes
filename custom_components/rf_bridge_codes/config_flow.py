"""Config flow for RF Bridge Codes."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    CONF_RAW_PARAM,
    CONF_SEND_SERVICE,
    DEFAULT_RAW_PARAM,
    DEFAULT_SEND_SERVICE,
    DOMAIN,
)


class RfBridgeCodesConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for RF Bridge Codes."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            send_service = user_input[CONF_SEND_SERVICE].strip()
            if "." not in send_service:
                errors["base"] = "invalid_service"
            else:
                await self.async_set_unique_id(send_service)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"RF Bridge Codes ({send_service})",
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SEND_SERVICE, default=DEFAULT_SEND_SERVICE
                ): str,
                vol.Required(
                    CONF_RAW_PARAM, default=DEFAULT_RAW_PARAM
                ): str,
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> RfBridgeCodesOptionsFlow:
        """Get the options flow."""
        return RfBridgeCodesOptionsFlow(config_entry)


class RfBridgeCodesOptionsFlow(config_entries.OptionsFlow):
    """Handle options for RF Bridge Codes (change the send service later)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self._config_entry.data
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SEND_SERVICE,
                    default=current.get(CONF_SEND_SERVICE, DEFAULT_SEND_SERVICE),
                ): str,
                vol.Required(
                    CONF_RAW_PARAM,
                    default=current.get(CONF_RAW_PARAM, DEFAULT_RAW_PARAM),
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
