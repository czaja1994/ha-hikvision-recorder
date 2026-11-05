"""The Hikvision Recorder integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.httpx_client import get_async_client

from .api import HikvisionNvrClient, NvrAuthError, NvrError
from .const import PLATFORMS, RETRY_DELAYS
from .coordinator import HikRecorderConfigEntry, HikRecorderCoordinator
from .entity import build_device_info


async def async_setup_entry(hass: HomeAssistant, entry: HikRecorderConfigEntry) -> bool:
    """Set up one NVR."""
    client = HikvisionNvrClient(
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        get_async_client(hass, verify_ssl=False),
        retry_delays=RETRY_DELAYS,
    )
    try:
        device = await client.get_device_info()
        cameras = await client.get_cameras()
    except NvrAuthError as err:
        if err.status_code == 401:
            raise ConfigEntryAuthFailed(str(err)) from err
        raise ConfigEntryNotReady(str(err)) from err
    except NvrError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = HikRecorderCoordinator(hass, entry, client, device, cameras)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # Register the device up front so it exists even though no entity has been
    # added yet.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **build_device_info(device)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HikRecorderConfigEntry) -> bool:
    """Unload an NVR."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
