"""Fixtures for the DOT-NL Chargers tests."""

from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.dotnl_chargers.api import (
    ChargePoint,
    ConnectorGroup,
    Evse,
    LocationRef,
)


def make_charge_point(available: int = 1, **kwargs) -> ChargePoint:
    """Return a charge point with two sockets."""
    data = {
        "id": "NL-TNM-231",
        "latitude": 51.925552,
        "longitude": 4.477733,
        "address": "Schiekade 988",
        "operator": "Shell Recharge",
        "owner": "Shell Recharge",
        "last_updated": datetime(2026, 10, 12, 14, 52, 22, tzinfo=UTC),
        "connectors": [
            ConnectorGroup(available, 2, "IEC_62196_T2", "SOCKET", "AC3", 11.0)
        ],
    }
    return ChargePoint(**(data | kwargs))


def make_evses(*available: bool) -> list[Evse]:
    """Return one socket per given availability."""
    return [
        Evse(
            f"EGL31-07-{n}",
            f"NL*TNM*EGL31*1*1049*07*{n}",
            free,
            1,
            "IEC_62196_T2",
            11.0,
        )
        for n, free in enumerate(available, start=1)
    ]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in all tests."""


@pytest.fixture
def mock_client() -> Generator[AsyncMock]:
    """Mock the DOT-NL client."""
    with (
        patch(
            "custom_components.dotnl_chargers.coordinator.DotNLClient", autospec=True
        ) as client_class,
        patch("custom_components.dotnl_chargers.config_flow.DotNLClient", client_class),
    ):
        client = client_class.return_value
        charge_point = make_charge_point()
        client.async_get_nearby.return_value = [
            make_charge_point(id="NL-TNM-1", address="Far away", latitude=51.9280),
            charge_point,
        ]
        client.async_get_charge_point.return_value = charge_point
        client.async_get_evses.return_value = {charge_point.id: make_evses(True, False)}
        client.async_find_by_id.return_value = [
            LocationRef(charge_point.id, charge_point.latitude, charge_point.longitude)
        ]
        yield client
