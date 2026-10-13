"""Tests for setup and entities of the DOT-NL Chargers integration."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.dotnl_chargers.api import DotNLError
from custom_components.dotnl_chargers.const import DOMAIN

from .conftest import make_charge_point, make_evses
from .test_config_flow import ENTRY_DATA

COORDINATOR = "custom_components.dotnl_chargers.coordinator"


async def _tick(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_entities(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    """Entities follow the availability of the charge point."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Schiekade 988",
        unique_id="NL-TNM-231",
        data=ENTRY_DATA,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    available = hass.states.get("sensor.schiekade_988_available_connectors")
    assert available.state == "1"
    assert available.attributes["total"] == 2
    assert available.attributes["connectors"][0]["max_power_kw"] == 11.0
    assert hass.states.get("binary_sensor.schiekade_988_available").state == "on"
    assert hass.states.get("sensor.schiekade_988_total_connectors").state == "2"
    assert (
        hass.states.get("sensor.schiekade_988_last_updated").state
        == "2026-10-12T14:52:22+00:00"
    )

    mock_client.async_get_charge_point.return_value = make_charge_point(available=0)
    await _tick(hass)
    assert hass.states.get("sensor.schiekade_988_available_connectors").state == "0"
    assert hass.states.get("binary_sensor.schiekade_988_available").state == "off"

    # A failed poll keeps the last known state...
    mock_client.async_get_charge_point.side_effect = DotNLError("boom")
    await _tick(hass)
    assert hass.states.get("binary_sensor.schiekade_988_available").state == "off"
    mock_client.async_get_charge_point.side_effect = None
    mock_client.async_get_charge_point.return_value = None
    mock_client.async_get_charge_point.reset_mock()
    await _tick(hass)
    assert mock_client.async_get_charge_point.call_count == 2
    assert hass.states.get("binary_sensor.schiekade_988_available").state == "off"

    # ...until the data is too old.
    with patch(f"{COORDINATOR}.STALE_AFTER", timedelta(0)):
        await _tick(hass)
    state = hass.states.get("binary_sensor.schiekade_988_available").state
    assert state == "unavailable"

    # And it recovers on the next successful poll.
    mock_client.async_get_charge_point.return_value = make_charge_point(available=2)
    await _tick(hass)
    assert hass.states.get("binary_sensor.schiekade_988_available").state == "on"

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_sockets(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    """Each socket has its own sensor; the dataset is only read when needed."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Schiekade 988",
        unique_id="NL-TNM-231",
        data=ENTRY_DATA,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    def sockets() -> list[str]:
        return [
            hass.states.get(f"binary_sensor.schiekade_988_socket_{n}").state
            for n in (1, 2)
        ]

    # 1 of 2 free: the dataset tells which one, and the sockets are remembered.
    assert sockets() == ["on", "off"]
    assert mock_client.async_get_evses.call_count == 1
    assert [evse["uid"] for evse in entry.data["evses"]] == [
        "EGL31-07-1",
        "EGL31-07-2",
    ]
    state = hass.states.get("binary_sensor.schiekade_988_socket_1")
    assert state.attributes["evse_id"] == "NL*TNM*EGL31*1*1049*07*1"

    # Nothing changed: no new lookup.
    await _tick(hass)
    assert mock_client.async_get_evses.call_count == 1

    # All free or none free needs no lookup either.
    mock_client.async_get_charge_point.return_value = make_charge_point(available=2)
    await _tick(hass)
    assert sockets() == ["on", "on"]
    mock_client.async_get_charge_point.return_value = make_charge_point(available=0)
    await _tick(hass)
    assert sockets() == ["off", "off"]
    assert mock_client.async_get_evses.call_count == 1

    # 1 of 2 again, but the dataset still shows the old situation: retried.
    mock_client.async_get_charge_point.return_value = make_charge_point(available=1)
    mock_client.async_get_evses.return_value = {
        entry.unique_id: make_evses(False, False)
    }
    await _tick(hass)
    assert sockets() == ["off", "off"]
    mock_client.async_get_evses.return_value = {
        entry.unique_id: make_evses(False, True)
    }
    await _tick(hass)
    assert sockets() == ["off", "on"]
    assert mock_client.async_get_evses.call_count == 3

    # A failing lookup keeps the last known sockets.
    mock_client.async_get_charge_point.return_value = make_charge_point(
        available=1, last_updated=dt_util.utcnow()
    )
    mock_client.async_get_evses.side_effect = DotNLError("boom")
    await _tick(hass)
    assert sockets() == ["off", "on"]


async def test_sockets_restored(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    """After a restart the stored sockets avoid reading the dataset."""
    mock_client.async_get_charge_point.return_value = make_charge_point(available=2)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Schiekade 988",
        unique_id="NL-TNM-231",
        data=ENTRY_DATA | {"evses": [e.as_dict() for e in make_evses(False, False)]},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.schiekade_988_socket_2").state == "on"
    mock_client.async_get_evses.assert_not_called()


async def test_setup_retry(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    """Setup is retried when DOT-NL is unreachable."""
    mock_client.async_get_charge_point.side_effect = DotNLError("boom")
    entry = MockConfigEntry(domain=DOMAIN, unique_id="x", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
