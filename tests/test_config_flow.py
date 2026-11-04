"""Config flow tests."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hikvision_recorder.const import DOMAIN

from .fake_nvr import FakeNvr

USER_INPUT = {CONF_HOST: "nvr.test", CONF_USERNAME: "admin", CONF_PASSWORD: "secret"}


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_user_flow_creates_entry(hass: HomeAssistant, patch_nvr: FakeNvr) -> None:
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Network Video Recorder"
    assert result["data"] == USER_INPUT
    assert result["result"].unique_id == "TESTSERIAL0001"
    await hass.async_block_till_done()


async def test_user_flow_invalid_auth(hass: HomeAssistant, patch_nvr: FakeNvr) -> None:
    patch_nvr.username = "someone-else"
    result = await hass.config_entries.flow.async_configure(
        (await _start(hass))["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, patch_nvr: FakeNvr
) -> None:
    patch_nvr.busy_responses = 10
    result = await hass.config_entries.flow.async_configure(
        (await _start(hass))["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    # The form can be resubmitted once the NVR is reachable again.
    patch_nvr.busy_responses = 0
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()


async def test_user_flow_already_configured(
    hass: HomeAssistant, patch_nvr: FakeNvr
) -> None:
    MockConfigEntry(
        domain=DOMAIN, unique_id="TESTSERIAL0001", data=USER_INPUT
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_configure(
        (await _start(hass))["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_password(hass: HomeAssistant, patch_nvr: FakeNvr) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="TESTSERIAL0001",
        data={**USER_INPUT, CONF_PASSWORD: "old"},
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data == {**USER_INPUT, CONF_PASSWORD: "new"}
    await hass.async_block_till_done()


async def test_reauth_invalid_auth_keeps_form(
    hass: HomeAssistant, patch_nvr: FakeNvr
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="TESTSERIAL0001", data=USER_INPUT)
    entry.add_to_hass(hass)
    patch_nvr.username = "someone-else"

    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data[CONF_PASSWORD] == "secret"
