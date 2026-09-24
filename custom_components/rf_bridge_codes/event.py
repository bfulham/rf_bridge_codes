"""Event platform for RF Bridge Codes.

Fires once per press of a real remote button that matches a saved code, so
automations can react even when the same button is pressed twice in a row.
"""
from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import device_info
from .const import DOMAIN, SIGNAL_CODE_ADDED, SIGNAL_CODE_REMOVED, SIGNAL_CODE_SEEN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the remote button event entity for an entry."""
    async_add_entities([RemoteButtonEvent(hass, entry)])


class RemoteButtonEvent(EventEntity):
    """A remote button matching a saved code was pressed."""

    _attr_has_entity_name = True
    _attr_name = "Remote button"
    _attr_icon = "mdi:remote"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry_id = entry.entry_id
        self._bridge = hass.data[DOMAIN][entry.entry_id]
        self._attr_unique_id = f"{entry.entry_id}_remote_button"
        self._attr_device_info = device_info(entry)
        self._attr_event_types = sorted(self._bridge.codes)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        for signal in (SIGNAL_CODE_ADDED, SIGNAL_CODE_REMOVED):
            self.async_on_remove(
                async_dispatcher_connect(self.hass, signal, self._handle_codes_changed)
            )
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_CODE_SEEN, self._handle_seen)
        )

    @callback
    def _handle_codes_changed(self, entry_id: str, name: str) -> None:
        if entry_id != self._entry_id:
            return
        self._attr_event_types = sorted(self._bridge.codes)
        self.async_write_ha_state()

    @callback
    def _handle_seen(self, entry_id: str, name: str, new_press: bool) -> None:
        if entry_id != self._entry_id or not new_press:
            return
        self._trigger_event(name)
        self.async_write_ha_state()
