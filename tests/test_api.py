"""Tests for the DOT-NL API client helpers."""

import gzip
import json
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.dotnl_chargers.api import (
    DotNLClient,
    DotNLError,
    _iter_json_array,
    _match_location,
    _retry_delay,
    bounding_box,
    normalize_id,
    parse_evses,
    parse_feature,
)

LOCATION = {
    "id": "231",
    "country_code": "NL",
    "party_id": "TNM",
    "coordinates": {"latitude": "51.9255520", "longitude": "4.4777330"},
    "evses": [{"evse_id": "NLTNMEGL31*1*1049*07*2"}, {"evse_id": None}],
}


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("NL*TNM*EGL31*1*1049*07*2", True),
        ("nl-tnm-egl31-1-1049-07-2", True),
        ("NL-TNM-231", True),
        ("NLTNMEGL31*1*1049*07", False),
        ("NLTNME9999", None),
    ],
)
def test_match_location(query: str, expected: bool | None) -> None:
    """EVSE IDs match regardless of notation, prefixes match loosely."""
    assert _match_location(LOCATION, normalize_id(query)) is expected


async def test_iter_json_array_handles_split_chunks() -> None:
    """Items are yielded even when chunk borders fall inside an object."""
    items = [{"id": i, "name": "ë" * i, "nested": [{"a": "]}"}]} for i in range(50)]
    payload = gzip.compress(json.dumps(items).encode())

    async def chunks():
        for start in range(0, len(payload), 7):
            yield payload[start : start + 7]

    assert [item async for item in _iter_json_array(chunks())] == items


def test_parse_feature() -> None:
    """A GeoJSON feature is converted and connector groups are summed."""
    charge_point = parse_feature(
        {
            "id": "NL-EFL-1",
            "geometry": {"type": "Point", "coordinates": [4.85469, 52.396149]},
            "properties": {
                "address": "zekeringstraat 17a",
                "last_updated": "2026-10-12T04:42:57.882Z",
                "operator_name": "E-Flux by Road ",
                "owner_name": None,
                "availabilities": [
                    {"available": 1, "total": 1, "power_max": 13800.0},
                    {"available": 0, "total": 2, "power_max": 22080.0},
                ],
            },
        }
    )
    assert (charge_point.available, charge_point.total) == (1, 3)
    assert charge_point.operator == "E-Flux by Road"
    assert charge_point.max_power_kw == 22.1
    assert charge_point.last_updated is not None


def test_bounding_box() -> None:
    """The box is centered and wider in longitude than in latitude."""
    min_lon, min_lat, max_lon, max_lat = bounding_box(52.0, 5.0, 1000)
    assert (min_lat + max_lat) / 2 == pytest.approx(52.0)
    assert max_lon - min_lon > max_lat - min_lat


def test_parse_evses() -> None:
    """Sockets are ordered by number and removed ones are left out."""
    connector = {
        "standard": "IEC_62196_T2",
        "power_type": "AC_3_PHASE",
        "max_voltage": 230,
        "max_amperage": 16,
        "max_electric_power": None,
    }
    evses = parse_evses(
        {
            "evses": [
                {"uid": "X*10", "evse_id": "NL*X*E1*10", "status": "CHARGING"},
                {
                    "uid": "X*2",
                    "evse_id": "NL*X*E1*2",
                    "status": "CHARGING",
                    "connectors": [connector],
                },
                {
                    "uid": "X*1",
                    "evse_id": "NL*X*E1*1",
                    "status": "AVAILABLE",
                    "connectors": [connector],
                },
                {"uid": "X*3", "status": "REMOVED", "connectors": [connector]},
            ]
        }
    )
    assert [(evse.uid, evse.available) for evse in evses] == [
        ("X*1", True),
        ("X*2", False),
    ]
    assert evses[0].max_power_kw == 11.0


def _response(status: int, headers: dict[str, str] | None = None) -> MagicMock:
    response = MagicMock(status=status, headers=headers or {})
    response.json = AsyncMock(
        return_value={"type": "FeatureCollection", "features": []}
    )
    if status >= 400:
        response.raise_for_status.side_effect = aiohttp.ClientResponseError(
            MagicMock(), (), status=status
        )
    return response


async def test_rate_limit_is_retried() -> None:
    """A 429 is retried after the wait DOT-NL asks for."""
    busy = _response(429, {"Retry-After": "1", "X-Retry-In": "71.462116ms"})
    session = MagicMock()
    session.get = AsyncMock(side_effect=[busy, busy, _response(200)])
    with patch("asyncio.sleep", AsyncMock()) as sleep:
        assert await DotNLClient(session).async_get_nearby(52.0, 5.0, 25) == []
    assert session.get.call_count == 3
    assert all(0.07 < call.args[0] < 1.1 for call in sleep.call_args_list)

    session.get = AsyncMock(return_value=busy)
    with patch("asyncio.sleep", AsyncMock()), pytest.raises(DotNLError):
        await DotNLClient(session).async_get_nearby(52.0, 5.0, 25)
    assert session.get.call_count == 5


def test_retry_delay() -> None:
    """The wait comes from X-Retry-In, then Retry-After, and is capped."""
    assert 0.07 < _retry_delay({"X-Retry-In": "71.462116ms"}, 0) < 0.6
    assert 1.0 < _retry_delay({"Retry-After": "1"}, 0) < 1.6
    assert 5.0 < _retry_delay({"Retry-After": "120"}, 0) < 5.6
    assert 0.25 < _retry_delay({}, 0) < 0.8
