"""Tests for the DOT-NL API client helpers."""

import gzip
import json

import pytest

from custom_components.dotnl_chargers.api import (
    _iter_json_array,
    _match_location,
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
