"""Platform stub; entities are added in a later task."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import HikRecorderConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HikRecorderConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up entities (none yet)."""
