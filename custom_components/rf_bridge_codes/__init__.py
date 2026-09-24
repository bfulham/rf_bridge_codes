"""The RF Bridge Codes integration.

Stores named raw RF codes (captured from an ESPHome rf_bridge/Portisch
device) and lets you send them back out again - either from a script/
automation via a service call, or by pressing the button entity this
integration creates for each saved code.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store

from .const import (
    ATTR_CODE,
    ATTR_NAME,
    CONF_RAW_PARAM,
    CONF_SEND_SERVICE,
    DOMAIN,
    SERVICE_ADD_CODE,
    SERVICE_DELETE_CODE,
    SERVICE_SEND_CODE,
    SIGNAL_CODE_ADDED,
    SIGNAL_CODE_REMOVED,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BUTTON]

ADD_CODE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_NAME): cv.string,
        vol.Required(ATTR_CODE): cv.string,
    }
)
DELETE_CODE_SCHEMA = vol.Schema({vol.Required(ATTR_NAME): cv.string})
SEND_CODE_SCHEMA = vol.Schema({vol.Required(ATTR_NAME): cv.string})


class RfBridgeCodesStore:
    """Thin wrapper around a persisted {name: code} mapping for one entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store = Store(hass, STORAGE_VERSION, f"rf_bridge_codes_{entry_id}")
        self.codes: dict[str, str] = {}

    async def async_load(self) -> None:
        data = await self._store.async_load()
        self.codes = dict(data) if data else {}

    async def async_save(self) -> None:
        await self._store.async_save(self.codes)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up RF Bridge Codes from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    store = RfBridgeCodesStore(hass, entry.entry_id)
    await store.async_load()

    hass.data[DOMAIN][entry.entry_id] = {
        "store": store,
        "send_service": entry.data[CONF_SEND_SERVICE],
        "raw_param": entry.data[CONF_RAW_PARAM],
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _do_send(entry_id: str, name: str) -> None:
        data = hass.data[DOMAIN][entry_id]
        code = data["store"].codes.get(name)
        if code is None:
            raise HomeAssistantError(f"No RF code named '{name}' is saved")

        send_service: str = data["send_service"]
        raw_param: str = data["raw_param"]
        if "." not in send_service:
            raise HomeAssistantError(
                f"Configured send service '{send_service}' is not a valid "
                "domain.service string"
            )
        service_domain, service_name = send_service.split(".", 1)

        await hass.services.async_call(
            service_domain,
            service_name,
            {raw_param: code},
            blocking=True,
        )

    async def async_add_code(call: ServiceCall) -> None:
        name = call.data[ATTR_NAME]
        code = call.data[ATTR_CODE]

        # first configured entry is used when the service is called
        # without specifying which one (most setups only have one bridge)
        entry_id = next(iter(hass.data[DOMAIN]))
        data = hass.data[DOMAIN][entry_id]
        data["store"].codes[name] = code
        await data["store"].async_save()
        _LOGGER.info("Saved RF code '%s'", name)
        async_dispatcher_send_local(hass, SIGNAL_CODE_ADDED, entry_id, name)

    async def async_delete_code(call: ServiceCall) -> None:
        name = call.data[ATTR_NAME]
        entry_id = next(iter(hass.data[DOMAIN]))
        data = hass.data[DOMAIN][entry_id]
        if name not in data["store"].codes:
            raise HomeAssistantError(f"No RF code named '{name}' is saved")
        del data["store"].codes[name]
        await data["store"].async_save()
        _LOGGER.info("Deleted RF code '%s'", name)
        async_dispatcher_send_local(hass, SIGNAL_CODE_REMOVED, entry_id, name)

    async def async_send_code(call: ServiceCall) -> None:
        name = call.data[ATTR_NAME]
        entry_id = next(iter(hass.data[DOMAIN]))
        await _do_send(entry_id, name)

    # only register the services once, even if multiple bridges are configured
    if not hass.services.has_service(DOMAIN, SERVICE_ADD_CODE):
        hass.services.async_register(
            DOMAIN, SERVICE_ADD_CODE, async_add_code, schema=ADD_CODE_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_DELETE_CODE, async_delete_code, schema=DELETE_CODE_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_SEND_CODE, async_send_code, schema=SEND_CODE_SCHEMA
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


def async_dispatcher_send_local(hass: HomeAssistant, signal: str, *args: Any) -> None:
    """Small local import wrapper to avoid a module-level circular import."""
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    async_dispatcher_send(hass, signal, *args)
