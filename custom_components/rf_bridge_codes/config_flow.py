"""Config flow for RF Bridge Codes.

Setup auto-detects the ESPHome send action. The options flow ("Configure"
on the integration) is where codes are learned, tested and deleted.
"""
from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    ATTR_NAME,
    CAPTURE_TIMEOUT,
    CONF_RAW_PARAM,
    CONF_REPEATS,
    CONF_SEND_SERVICE,
    DEFAULT_RAW_PARAM,
    DEFAULT_REPEATS,
    DEFAULT_SEND_SERVICE,
    DOMAIN,
    SEND_SERVICE_SUFFIX,
)


class RfBridgeCodesConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for RF Bridge Codes."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Pick the ESPHome send action (pre-filled when one is found)."""
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
                    data={
                        CONF_SEND_SERVICE: send_service,
                        CONF_RAW_PARAM: DEFAULT_RAW_PARAM,
                    },
                )

        found = sorted(
            f"esphome.{name}"
            for name in self.hass.services.async_services().get("esphome", {})
            if name.endswith(SEND_SERVICE_SUFFIX)
        )
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SEND_SERVICE,
                    default=found[0] if found else DEFAULT_SEND_SERVICE,
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=found,
                        custom_value=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
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
    """Learn, test and delete codes, and change the repeat count."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry
        self._name: str | None = None
        self._capture: asyncio.Task[list[str]] | None = None
        self._codes: list[str] = []
        self._tried = 0
        self._error = ""

    @property
    def _bridge(self):
        return self.hass.data[DOMAIN][self._entry.entry_id]

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        menu = ["learn", "delete", "settings"]
        if not self._bridge.codes:
            menu.remove("delete")
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_learn(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[ATTR_NAME].strip()
            if not name:
                errors[ATTR_NAME] = "empty_name"
            else:
                self._name = name
                return await self.async_step_capture()

        return self.async_show_form(
            step_id="learn",
            data_schema=vol.Schema({vol.Required(ATTR_NAME): str}),
            errors=errors,
        )

    async def async_step_capture(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if self._capture is None:
            self._capture = self.hass.async_create_task(self._bridge.async_capture())
        if not self._capture.done():
            return self.async_show_progress(
                step_id="capture",
                progress_action="capture",
                progress_task=self._capture,
                description_placeholders={
                    "name": self._name,
                    "timeout": str(CAPTURE_TIMEOUT),
                },
            )

        capture, self._capture = self._capture, None
        try:
            self._codes = capture.result()
            self._tried = 0
        except HomeAssistantError as err:
            self._error = str(err)
            return self.async_show_progress_done(next_step_id="capture_failed")
        return self.async_show_progress_done(next_step_id="review")

    async def async_step_review(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Let the user try each captured code, then save the one that works."""
        count = len(self._codes)
        options = {
            f"test_{i}": f"Try code {i + 1}" if count > 1 else "Try it"
            for i in range(count)
        }
        options["save"] = f"Save code {self._tried + 1}" if count > 1 else "Save"
        options["capture"] = "Listen again"
        return self.async_show_menu(
            step_id="review",
            menu_options=options,
            description_placeholders={
                "name": self._name,
                "tip": (
                    f"Your remote sent {count} different codes. Try each one, "
                    "then save the one that worked. Save uses the one you "
                    "tried last."
                    if count > 1
                    else "Try it, then save it if it worked."
                ),
            },
        )

    async def _async_try(self, index: int) -> config_entries.ConfigFlowResult:
        self._tried = index
        await self._bridge.async_send_raw(self._codes[index])
        return await self.async_step_review()

    # one step per offered code (up to MAX_VARIANTS)
    async def async_step_test_0(self, user_input=None):
        return await self._async_try(0)

    async def async_step_test_1(self, user_input=None):
        return await self._async_try(1)

    async def async_step_test_2(self, user_input=None):
        return await self._async_try(2)

    async def async_step_test_3(self, user_input=None):
        return await self._async_try(3)

    async def async_step_save(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        await self._bridge.async_add(self._name, self._codes[self._tried])
        return self.async_create_entry(data=dict(self._entry.options))

    async def async_step_capture_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        return self.async_abort(
            reason="capture_failed", description_placeholders={"error": self._error}
        )

    async def async_step_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            await self._bridge.async_delete(user_input[ATTR_NAME])
            return self.async_create_entry(data=dict(self._entry.options))

        schema = vol.Schema(
            {
                vol.Required(ATTR_NAME): SelectSelector(
                    SelectSelectorConfig(options=sorted(self._bridge.codes))
                )
            }
        )
        return self.async_show_form(step_id="delete", data_schema=schema)

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={
                    **self._entry.options,
                    CONF_REPEATS: int(user_input[CONF_REPEATS]),
                }
            )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_REPEATS,
                    default=self._entry.options.get(CONF_REPEATS, DEFAULT_REPEATS),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=20, step=1, mode=NumberSelectorMode.BOX
                    )
                )
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)
