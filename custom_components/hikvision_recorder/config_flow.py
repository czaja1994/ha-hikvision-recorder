"""Config flow for the Hikvision Recorder integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.httpx_client import get_async_client

from .api import HikvisionNvrClient, NvrAuthError, NvrError
from .const import DOMAIN, RETRY_DELAYS
from .parsing import NvrDeviceInfo

_LOGGER = logging.getLogger(__name__)


async def _validate(
    hass: HomeAssistant, host: str, username: str, password: str
) -> NvrDeviceInfo:
    """Fetch device info; raises NvrError subclasses."""
    client = HikvisionNvrClient(
        host,
        username,
        password,
        get_async_client(hass, verify_ssl=False),
        retry_delays=RETRY_DELAYS,
    )
    return await client.get_device_info()


def _error_key(err: NvrError) -> str:
    return "invalid_auth" if isinstance(err, NvrAuthError) else "cannot_connect"


class HikRecorderConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hikvision Recorder."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                device = await _validate(
                    self.hass,
                    user_input[CONF_HOST],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except NvrError as err:
                errors["base"] = _error_key(err)
            else:
                await self.async_set_unique_id(device.serial)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=device.name, data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                device = await _validate(
                    self.hass,
                    entry.data[CONF_HOST],
                    entry.data[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except NvrError as err:
                errors["base"] = _error_key(err)
            else:
                await self.async_set_unique_id(device.serial)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"host": entry.data[CONF_HOST]},
            errors=errors,
        )
