"""Sensor platform for RF Bridge Codes.

Shows the name of the last saved code the bridge heard from a real remote.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from . import device_info
from .const import SIGNAL_CODE_SEEN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the last-seen sensor for an entry."""
    async_add_entities([LastSeenSensor(entry)])


class LastSeenSensor(SensorEntity, RestoreEntity):
    """Name of the last saved code heard from a remote."""

    _attr_has_entity_name = True
    _attr_name = "Last button seen"
    _attr_icon = "mdi:remote"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_last_seen"
        self._attr_device_info = device_info(entry)
        self._attr_extra_state_attributes = {}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_native_value = last.state
            self._attr_extra_state_attributes = dict(last.attributes)
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_CODE_SEEN, self._handle_seen)
        )

    @callback
    def _handle_seen(self, entry_id: str, name: str, new_press: bool) -> None:
        if entry_id != self._entry_id:
            return
        self._attr_native_value = name
        self._attr_extra_state_attributes = {
            "last_seen": dt_util.utcnow().isoformat()
        }
        self.async_write_ha_state()
