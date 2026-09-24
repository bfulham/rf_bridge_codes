"""Button platform for RF Bridge Codes.

Each saved RF code gets its own button entity - pressing it sends that
code out through the configured ESPHome raw-send service.
"""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_CODE_ADDED, SIGNAL_CODE_REMOVED

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up RF Bridge Codes button entities for an entry."""
    bridge = hass.data[DOMAIN][entry.entry_id]

    existing: dict[str, RfBridgeCodeButton] = {}

    def _make_button(name: str) -> RfBridgeCodeButton:
        button = RfBridgeCodeButton(hass, entry, name)
        existing[name] = button
        return button

    async_add_entities([_make_button(name) for name in bridge.codes])

    @callback
    def _handle_added(added_entry_id: str, name: str) -> None:
        if added_entry_id != entry.entry_id or name in existing:
            return
        async_add_entities([_make_button(name)])

    @callback
    def _handle_removed(removed_entry_id: str, name: str) -> None:
        if removed_entry_id != entry.entry_id:
            return
        button = existing.pop(name, None)
        if button is None:
            return
        # drop the registry entry too, or the button lingers as unavailable
        registry = er.async_get(hass)
        if button.entity_id and registry.async_get(button.entity_id):
            registry.async_remove(button.entity_id)
        else:
            hass.async_create_task(button.async_remove())

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_CODE_ADDED, _handle_added)
    )
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_CODE_REMOVED, _handle_removed)
    )


class RfBridgeCodeButton(ButtonEntity):
    """A button that transmits one saved RF code."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:remote"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, name: str) -> None:
        self._hass = hass
        self._entry = entry
        self._code_name = name
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{name}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Sonoff / Portisch (custom)",
            model="RF Bridge Codes library",
        )

    async def async_press(self) -> None:
        """Send this code through the configured ESPHome service."""
        bridge = self._hass.data[DOMAIN][self._entry.entry_id]
        await bridge.async_send(self._code_name)
