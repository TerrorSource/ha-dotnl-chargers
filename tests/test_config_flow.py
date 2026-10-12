"""Tests for the DOT-NL Chargers config flow."""

from unittest.mock import AsyncMock

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dotnl_chargers.api import DotNLError
from custom_components.dotnl_chargers.const import DOMAIN

ENTRY_DATA = {
    "charge_point_id": "NL-TNM-231",
    "latitude": 51.925552,
    "longitude": 4.477733,
}


async def _start(hass: HomeAssistant, step: str) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": step}
    )
    assert result["type"] is FlowResultType.FORM
    return result["flow_id"]


async def test_flow_by_id(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    """A charge point can be added by entering its EVSE ID."""
    flow_id = await _start(hass, "id")

    result = await hass.config_entries.flow.async_configure(
        flow_id, {"charge_point_id": "abc"}
    )
    assert result["errors"] == {"base": "invalid_id"}

    mock_client.async_find_by_id.side_effect = DotNLError
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"charge_point_id": "NL*TNM*EGL31*1*1049*07*1"}
    )
    assert result["errors"] == {"base": "cannot_connect"}

    mock_client.async_find_by_id.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"charge_point_id": "NL*TNM*EGL31*1*1049*07*1"}
    )
    assert result["step_id"] == "select"

    result = await hass.config_entries.flow.async_configure(
        flow_id, {"charge_point": "NL-TNM-231", "name": "Work"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Work"
    assert result["data"] == ENTRY_DATA


async def test_flow_by_id_not_found(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    """An unknown ID shows an error."""
    flow_id = await _start(hass, "id")
    mock_client.async_find_by_id.return_value = []
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"charge_point_id": "NL*XXX*E000000"}
    )
    assert result["errors"] == {"base": "id_not_found"}


async def test_flow_by_id_already_configured(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    """A charge point cannot be added twice."""
    MockConfigEntry(domain=DOMAIN, unique_id="NL-TNM-231", data=ENTRY_DATA).add_to_hass(
        hass
    )
    flow_id = await _start(hass, "id")
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"charge_point_id": "NL*TNM*EGL31*1*1049*07*1"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_flow_by_map(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    """A charge point can be picked from the ones near a map position."""
    flow_id = await _start(hass, "map")
    location = {"latitude": 51.9256, "longitude": 4.4777, "radius": 300}

    mock_client.async_get_nearby.return_value = []
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"location": location}
    )
    assert result["errors"] == {"base": "no_charge_points"}

    mock_client.async_get_nearby.return_value = [
        mock_client.async_get_charge_point.return_value
    ]
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"location": location}
    )
    assert result["step_id"] == "select"

    result = await hass.config_entries.flow.async_configure(
        flow_id, {"charge_point": "NL-TNM-231"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Schiekade 988"
    assert result["result"].unique_id == "NL-TNM-231"
