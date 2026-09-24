"""The RF Bridge Codes integration.

Learns, stores and sends named raw RF codes through an ESPHome rf_bridge
device running Portisch firmware. Learning puts the bridge into bucket
sniffing mode, waits for the B1 frame it reports, converts it to B0 and
saves it - each saved code then gets a button entity. Codes heard from a
real remote outside of learning are matched against the saved ones and
reported through a sensor and an event entity.
"""
from __future__ import annotations

import asyncio
import logging
import time

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .codec import (
    b0_pulse_data,
    b1_to_b0,
    distinct_frames,
    parse_bucket_frames,
    pulse_data,
    with_repeats,
)
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
    LISTEN_WINDOW,
    MAX_VARIANTS,
    PRESS_GAP,
    SEND_SERVICE_SUFFIX,
    SERVICE_ADD_CODE,
    SERVICE_DELETE_CODE,
    SERVICE_LEARN_CODE,
    SERVICE_SEND_CODE,
    SIGNAL_CODE_ADDED,
    SIGNAL_CODE_REMOVED,
    SIGNAL_CODE_SEEN,
    SNIFF_SERVICE_SUFFIX,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.EVENT, Platform.SENSOR]

ADD_CODE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_NAME): cv.string,
        vol.Required(ATTR_CODE): cv.string,
    }
)
NAME_SCHEMA = vol.Schema({vol.Required(ATTR_NAME): cv.string})


def device_info(entry: ConfigEntry) -> DeviceInfo:
    """The one device all of an entry's entities belong to."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Sonoff / Portisch (custom)",
        model="RF Bridge Codes library",
    )


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
        # other codes the same button sends (e.g. its "still held" code),
        # as pulse-data hex, so a press is recognised from any of them
        self._alias_store: Store = Store(
            hass, STORAGE_VERSION, f"rf_bridge_codes_{entry.entry_id}_aliases"
        )
        self.aliases: dict[str, list[str]] = {}
        self._last_seen: dict[str, float] = {}

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
        aliases = await self._alias_store.async_load()
        self.aliases = dict(aliases) if aliases else {}

    async def async_add(
        self, name: str, code: str, also_sent: list[str] | None = None
    ) -> None:
        """Save a code. also_sent: other B0 codes the same button sends."""
        is_new = name not in self.codes
        self.codes[name] = code
        await self._store.async_save(self.codes)
        self.aliases[name] = [
            pulses.hex()
            for other in also_sent or []
            if (pulses := b0_pulse_data(other))
        ]
        await self._alias_store.async_save(self.aliases)
        _LOGGER.info("Saved RF code '%s'", name)
        if is_new:
            async_dispatcher_send(self.hass, SIGNAL_CODE_ADDED, self.entry_id, name)

    async def async_delete(self, name: str) -> None:
        if name not in self.codes:
            raise HomeAssistantError(f"No RF code named '{name}' is saved")
        del self.codes[name]
        await self._store.async_save(self.codes)
        if self.aliases.pop(name, None) is not None:
            await self._alias_store.async_save(self.aliases)
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

    async def async_capture(self, timeout: float = CAPTURE_TIMEOUT) -> list[str]:
        """Wait for a remote press and return the B0 codes it sent.

        Listens for LISTEN_WINDOW after the first code arrives, so a remote
        that follows its first burst with a different "still held" code
        gives back both, in the order they were heard.
        """
        frames: list[bytes] = []
        first_heard = asyncio.Event()

        @callback
        def _on_bucket(event: Event) -> None:
            received = parse_bucket_frames(event.data.get(ATTR_RAW, ""))
            if received:
                frames.extend(received)
                first_heard.set()

        unsub = self.hass.bus.async_listen(EVENT_BUCKET, _on_bucket)
        try:
            sniff = self.sniff_service
            if sniff and self.hass.services.has_service(*sniff.split(".", 1)):
                await self._async_call(sniff, {})
            async with asyncio.timeout(timeout):
                await first_heard.wait()
            await asyncio.sleep(LISTEN_WINDOW)
        except TimeoutError as err:
            raise HomeAssistantError(
                f"No RF signal received within {timeout:.0f} seconds"
            ) from err
        finally:
            unsub()

        codes: list[str] = []
        for frame in distinct_frames(frames)[:MAX_VARIANTS]:
            try:
                codes.append(b1_to_b0(frame, self.repeats))
            except ValueError as err:
                _LOGGER.warning("Skipping captured code: %s", err)
        if not codes:
            raise HomeAssistantError("The captured code is too long to send")
        return codes

    def match(self, raw: str) -> str | None:
        """Name of the saved code a received bucket dump carries, if any."""
        for frame in parse_bucket_frames(raw):
            pulses = pulse_data(frame)
            for name, code in self.codes.items():
                if pulses == b0_pulse_data(code) or pulses.hex() in self.aliases.get(
                    name, []
                ):
                    return name
        return None

    @callback
    def async_handle_bucket(self, event: Event) -> None:
        """Report a saved code heard from a real remote."""
        name = self.match(event.data.get(ATTR_RAW, ""))
        if name is None:
            return
        now = time.monotonic()
        # a held button keeps sending: only the first burst is a new press
        new_press = now - self._last_seen.get(name, -PRESS_GAP) >= PRESS_GAP
        self._last_seen[name] = now
        async_dispatcher_send(
            self.hass, SIGNAL_CODE_SEEN, self.entry_id, name, new_press
        )

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
    entry.async_on_unload(
        hass.bus.async_listen(EVENT_BUCKET, bridge.async_handle_bucket)
    )

    async def async_add_code(call: ServiceCall) -> None:
        await _first_bridge(hass).async_add(call.data[ATTR_NAME], call.data[ATTR_CODE])

    async def async_delete_code(call: ServiceCall) -> None:
        await _first_bridge(hass).async_delete(call.data[ATTR_NAME])

    async def async_send_code(call: ServiceCall) -> None:
        await _first_bridge(hass).async_send(call.data[ATTR_NAME])

    async def async_learn_code(call: ServiceCall) -> None:
        bridge = _first_bridge(hass)
        # no one to ask which variant works here, so use the first one heard
        codes = await bridge.async_capture()
        await bridge.async_add(call.data[ATTR_NAME], codes[0], codes[1:])

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
