"""The RF Bridge Codes integration.

Learns, stores and sends named raw RF codes through an ESPHome rf_bridge
device running Portisch firmware. Learning puts the bridge into bucket
sniffing mode, waits for the B1 frame it reports, converts it to B0 and
saves it - each saved code then gets a button entity.
"""
from __future__ import annotations

import asyncio
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .codec import b1_to_b0, best_frame, parse_bucket_frames, with_repeats
from .const import (
    ATTR_CODE,
    ATTR_NAME,
    ATTR_RAW,
    CAPTURE_TIMEOUT,
    CONF_RAW_PARAM,
    CONF_REPEATS,
    CONF_SEND_SERVICE,
    DEFAULT_RAW_PARAM,
    DEFAULT_REPEATS,
    DOMAIN,
    EVENT_BUCKET,
    SEND_SERVICE_SUFFIX,
    SERVICE_ADD_CODE,
    SERVICE_DELETE_CODE,
    SERVICE_LEARN_CODE,
    SERVICE_SEND_CODE,
    SIGNAL_CODE_ADDED,
    SIGNAL_CODE_REMOVED,
    SNIFF_SERVICE_SUFFIX,
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
NAME_SCHEMA = vol.Schema({vol.Required(ATTR_NAME): cv.string})


class RfBridge:
    """Saved codes for one config entry plus the actions that use them."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.entry_id = entry.entry_id
        self.send_service: str = entry.data[CONF_SEND_SERVICE]
        self.raw_param: str = entry.data.get(CONF_RAW_PARAM, DEFAULT_RAW_PARAM)
        self._store: Store = Store(
            hass, STORAGE_VERSION, f"rf_bridge_codes_{entry.entry_id}"
        )
        self.codes: dict[str, str] = {}

    @property
    def repeats(self) -> int:
        return int(self.entry.options.get(CONF_REPEATS, DEFAULT_REPEATS))

    @property
    def sniff_service(self) -> str | None:
        if not self.send_service.endswith(SEND_SERVICE_SUFFIX):
            return None
        return self.send_service[: -len(SEND_SERVICE_SUFFIX)] + SNIFF_SERVICE_SUFFIX

    async def async_load(self) -> None:
        data = await self._store.async_load()
        self.codes = dict(data) if data else {}

    async def async_add(self, name: str, code: str) -> None:
        is_new = name not in self.codes
        self.codes[name] = code
        await self._store.async_save(self.codes)
        _LOGGER.info("Saved RF code '%s'", name)
        if is_new:
            async_dispatcher_send(self.hass, SIGNAL_CODE_ADDED, self.entry_id, name)

    async def async_delete(self, name: str) -> None:
        if name not in self.codes:
            raise HomeAssistantError(f"No RF code named '{name}' is saved")
        del self.codes[name]
        await self._store.async_save(self.codes)
        _LOGGER.info("Deleted RF code '%s'", name)
        async_dispatcher_send(self.hass, SIGNAL_CODE_REMOVED, self.entry_id, name)

    async def async_send(self, name: str) -> None:
        code = self.codes.get(name)
        if code is None:
            raise HomeAssistantError(f"No RF code named '{name}' is saved")
        await self.async_send_raw(code)

    async def async_send_raw(self, code: str) -> None:
        await self._async_call(
            self.send_service, {self.raw_param: with_repeats(code, self.repeats)}
        )

    async def async_capture(self, timeout: float = CAPTURE_TIMEOUT) -> str:
        """Wait for the next remote press and return it as a B0 code."""
        result: asyncio.Future[str] = self.hass.loop.create_future()

        @callback
        def _on_bucket(event: Event) -> None:
            frame = best_frame(parse_bucket_frames(event.data.get(ATTR_RAW, "")))
            if frame is None or result.done():
                return
            try:
                result.set_result(b1_to_b0(frame, self.repeats))
            except ValueError as err:
                result.set_exception(HomeAssistantError(str(err)))

        unsub = self.hass.bus.async_listen(EVENT_BUCKET, _on_bucket)
        try:
            sniff = self.sniff_service
            if sniff and self.hass.services.has_service(*sniff.split(".", 1)):
                await self._async_call(sniff, {})
            async with asyncio.timeout(timeout):
                return await result
        except TimeoutError as err:
            raise HomeAssistantError(
                f"No RF signal received within {timeout:.0f} seconds"
            ) from err
        finally:
            unsub()

    async def _async_call(self, service: str, data: dict) -> None:
        if "." not in service:
            raise HomeAssistantError(
                f"'{service}' is not a valid domain.service string"
            )
        domain, name = service.split(".", 1)
        await self.hass.services.async_call(domain, name, data, blocking=True)


def _first_bridge(hass: HomeAssistant) -> RfBridge:
    # services act on the first configured entry (most setups have one bridge)
    bridges = hass.data.get(DOMAIN)
    if not bridges:
        raise HomeAssistantError("RF Bridge Codes is not set up")
    return next(iter(bridges.values()))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up RF Bridge Codes from a config entry."""
    bridge = RfBridge(hass, entry)
    await bridge.async_load()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = bridge

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def async_add_code(call: ServiceCall) -> None:
        await _first_bridge(hass).async_add(call.data[ATTR_NAME], call.data[ATTR_CODE])

    async def async_delete_code(call: ServiceCall) -> None:
        await _first_bridge(hass).async_delete(call.data[ATTR_NAME])

    async def async_send_code(call: ServiceCall) -> None:
        await _first_bridge(hass).async_send(call.data[ATTR_NAME])

    async def async_learn_code(call: ServiceCall) -> None:
        bridge = _first_bridge(hass)
        await bridge.async_add(call.data[ATTR_NAME], await bridge.async_capture())

    # only register the services once, even if multiple bridges are configured
    if not hass.services.has_service(DOMAIN, SERVICE_ADD_CODE):
        hass.services.async_register(
            DOMAIN, SERVICE_ADD_CODE, async_add_code, schema=ADD_CODE_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_DELETE_CODE, async_delete_code, schema=NAME_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_SEND_CODE, async_send_code, schema=NAME_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_LEARN_CODE, async_learn_code, schema=NAME_SCHEMA
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
