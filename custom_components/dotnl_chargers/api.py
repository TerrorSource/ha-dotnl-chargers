"""Client for the NDW DOT-NL open data charge point API."""

from __future__ import annotations

import asyncio
import codecs
import json
import math
import re
import zlib
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from typing import Any

import aiohttp

from .const import (
    API_URL,
    LOCATIONS_DUMP_URL,
    LOOKUP_TIMEOUT,
    MAX_LOOKUP_MATCHES,
    REQUEST_TIMEOUT,
)

_METERS_PER_DEGREE = 111_320


class DotNLError(Exception):
    """Raised when the DOT-NL API cannot be reached or returns bad data."""


@dataclass(frozen=True, slots=True)
class ConnectorGroup:
    """Connectors of one type on a charge point."""

    available: int
    total: int
    connector_type: str | None
    connector_format: str | None
    power_type: str | None
    max_power_kw: float | None

    def as_dict(self) -> dict[str, Any]:
        """Return the group as state attribute data."""
        return {
            "available": self.available,
            "total": self.total,
            "connector_type": self.connector_type,
            "connector_format": self.connector_format,
            "power_type": self.power_type,
            "max_power_kw": self.max_power_kw,
        }


@dataclass(frozen=True, slots=True)
class ChargePoint:
    """A charging location as published by DOT-NL."""

    id: str
    latitude: float
    longitude: float
    address: str | None
    operator: str | None
    owner: str | None
    last_updated: datetime | None
    connectors: list[ConnectorGroup] = field(default_factory=list)

    @property
    def available(self) -> int:
        """Return the number of connectors that are free."""
        return sum(group.available for group in self.connectors)

    @property
    def total(self) -> int:
        """Return the number of connectors."""
        return sum(group.total for group in self.connectors)

    @property
    def name(self) -> str:
        """Return a human readable name."""
        return self.address or self.id

    @property
    def max_power_kw(self) -> float | None:
        """Return the highest power any connector delivers."""
        powers = [g.max_power_kw for g in self.connectors if g.max_power_kw]
        return max(powers) if powers else None

    @property
    def connector_types(self) -> list[str]:
        """Return the distinct connector types."""
        return sorted({g.connector_type for g in self.connectors if g.connector_type})

    def distance_to(self, latitude: float, longitude: float) -> float:
        """Return the distance in meters to the given coordinates."""
        return _distance(latitude, longitude, self.latitude, self.longitude)


@dataclass(frozen=True, slots=True)
class Evse:
    """A single socket (EVSE) of a charge point."""

    uid: str
    evse_id: str | None
    available: bool
    connector_count: int
    connector_type: str | None
    max_power_kw: float | None

    def as_dict(self) -> dict[str, Any]:
        """Return the static description, for storage in the config entry."""
        data = asdict(self)
        del data["available"]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Evse:
        """Restore a socket from the config entry; availability is unknown."""
        return cls(available=False, **data)

    def with_available(self, available: bool) -> Evse:
        """Return a copy with another availability."""
        return replace(self, available=available)


@dataclass(frozen=True, slots=True)
class LocationRef:
    """Where to find a charge point that was looked up by ID."""

    id: str
    latitude: float
    longitude: float


def normalize_id(value: str) -> str:
    """Reduce an EVSE or location ID to comparable form.

    EVSE IDs are written with or without separators (NL*TNM*E123*1,
    NLTNME123*1 or NL-TNM-E123-1) depending on who prints them.
    """
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _match_location(location: dict[str, Any], query: str) -> bool | None:
    """Return True on an exact match, False on a prefix match, else None."""
    location_id = normalize_id(
        f"{location.get('country_code')}{location.get('party_id')}{location.get('id')}"
    )
    evse_ids = [
        normalize_id(evse.get("evse_id") or "") for evse in location.get("evses") or []
    ]
    if query == location_id or query in evse_ids:
        return True
    if any(evse_id.startswith(query) for evse_id in evse_ids):
        return False
    return None


def _location_id(location: dict[str, Any]) -> str:
    """Return the ID the GeoJSON API uses for an OCPI location."""
    return f"{location.get('country_code')}-{location.get('party_id')}-{location.get('id')}"


def _natural_key(value: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value)]


def _connector_power_kw(connector: dict[str, Any]) -> float | None:
    if power := connector.get("max_electric_power"):
        return round(power / 1000, 1)
    voltage, amperage = connector.get("max_voltage"), connector.get("max_amperage")
    if not voltage or not amperage:
        return None
    phases = 3 if connector.get("power_type") == "AC_3_PHASE" else 1
    return round(voltage * amperage * phases / 1000, 1)


def parse_evses(location: dict[str, Any]) -> list[Evse]:
    """Return the sockets of an OCPI location, in a stable order."""
    evses = []
    for evse in location.get("evses") or []:
        connectors = evse.get("connectors") or []
        if not evse.get("uid") or evse.get("status") == "REMOVED" or not connectors:
            continue
        powers = [power for c in connectors if (power := _connector_power_kw(c))]
        evses.append(
            Evse(
                uid=str(evse["uid"]),
                evse_id=_clean(evse.get("evse_id")),
                available=evse.get("status") == "AVAILABLE",
                connector_count=len(connectors),
                connector_type=_clean(connectors[0].get("standard")),
                max_power_kw=max(powers) if powers else None,
            )
        )
    return sorted(evses, key=lambda evse: _natural_key(evse.evse_id or evse.uid))


def _location_ref(location: dict[str, Any]) -> LocationRef | None:
    try:
        return LocationRef(
            id=_location_id(location),
            latitude=float(location["coordinates"]["latitude"]),
            longitude=float(location["coordinates"]["longitude"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


async def _iter_json_array(chunks: AsyncIterator[bytes]) -> AsyncIterator[Any]:
    """Yield the items of a gzipped JSON array without holding it in memory."""
    decompressor = zlib.decompressobj(zlib.MAX_WBITS | 16)
    text_decoder = codecs.getincrementaldecoder("utf-8")()
    json_decoder = json.JSONDecoder()
    buffer = ""
    async for chunk in chunks:
        buffer += text_decoder.decode(decompressor.decompress(chunk))
        position = 0
        while True:
            while position < len(buffer) and buffer[position] in "[], \t\r\n":
                position += 1
            try:
                item, position = json_decoder.raw_decode(buffer, position)
            except json.JSONDecodeError:
                break
            yield item
        buffer = buffer[position:]


def _distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the equirectangular distance in meters, fine for a few km."""
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return math.hypot(x, y) * 6_371_000


def bounding_box(
    latitude: float, longitude: float, radius: float
) -> tuple[float, float, float, float]:
    """Return (min_lon, min_lat, max_lon, max_lat) around a point."""
    d_lat = radius / _METERS_PER_DEGREE
    d_lon = radius / (_METERS_PER_DEGREE * math.cos(math.radians(latitude)))
    return (
        longitude - d_lon,
        latitude - d_lat,
        longitude + d_lon,
        latitude + d_lat,
    )


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_group(data: dict[str, Any]) -> ConnectorGroup:
    power = data.get("power_max")
    return ConnectorGroup(
        available=int(data.get("available") or 0),
        total=int(data.get("total") or 0),
        connector_type=_clean(data.get("connector_type")),
        connector_format=_clean(data.get("connector_format")),
        power_type=_clean(data.get("power_type")),
        max_power_kw=round(power / 1000, 1) if power else None,
    )


def parse_feature(feature: dict[str, Any]) -> ChargePoint:
    """Convert a GeoJSON feature into a ChargePoint."""
    try:
        longitude, latitude = feature["geometry"]["coordinates"][:2]
        props = feature.get("properties") or {}
        return ChargePoint(
            id=str(feature["id"]),
            latitude=float(latitude),
            longitude=float(longitude),
            address=_clean(props.get("address")),
            operator=_clean(props.get("operator_name")),
            owner=_clean(props.get("owner_name")),
            last_updated=_parse_datetime(props.get("last_updated")),
            connectors=[
                _parse_group(group) for group in props.get("availabilities") or []
            ],
        )
    except (KeyError, TypeError, ValueError) as err:
        raise DotNLError(f"Unexpected charge point data: {err!r}") from err


class DotNLClient:
    """Minimal async client for the DOT-NL GeoJSON API."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialize the client."""
        self._session = session

    async def async_get_nearby(
        self, latitude: float, longitude: float, radius: float
    ) -> list[ChargePoint]:
        """Return the charge points within a square around a point."""
        bbox = bounding_box(latitude, longitude, radius)
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT.total_seconds()):
                response = await self._session.get(
                    API_URL,
                    params={"bbox": ",".join(f"{value:.6f}" for value in bbox)},
                )
                response.raise_for_status()
                data = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise DotNLError(f"Error communicating with DOT-NL: {err!r}") from err

        if not isinstance(data, dict) or not isinstance(data.get("features"), list):
            raise DotNLError("Unexpected response from DOT-NL")
        return [parse_feature(feature) for feature in data["features"]]

    async def async_get_charge_point(
        self, charge_point_id: str, latitude: float, longitude: float, radius: float
    ) -> ChargePoint | None:
        """Return a single charge point, looked up near its known position."""
        for charge_point in await self.async_get_nearby(latitude, longitude, radius):
            if charge_point.id == charge_point_id:
                return charge_point
        return None

    async def _async_iter_locations(self) -> AsyncIterator[dict[str, Any]]:
        """Stream the locations of the national OCPI dataset."""
        async with self._session.get(
            LOCATIONS_DUMP_URL, headers={"Accept-Encoding": "identity"}
        ) as response:
            response.raise_for_status()
            # Small chunks keep each slice of parsing work short.
            async for location in _iter_json_array(response.content.iter_chunked(8192)):
                if isinstance(location, dict):
                    yield location

    async def async_find_by_id(self, query: str) -> list[LocationRef]:
        """Look up charge points by EVSE ID or DOT-NL location ID.

        An exact match returns that single location, otherwise all locations
        that have an EVSE ID starting with the query are returned.
        """
        query = normalize_id(query)
        prefix_matches: list[LocationRef] = []
        try:
            async with (
                asyncio.timeout(LOOKUP_TIMEOUT.total_seconds()),
                aclosing(self._async_iter_locations()) as locations,
            ):
                async for location in locations:
                    if (exact := _match_location(location, query)) is None:
                        continue
                    if (ref := _location_ref(location)) is None:
                        continue
                    if exact:
                        return [ref]
                    if len(prefix_matches) < MAX_LOOKUP_MATCHES:
                        prefix_matches.append(ref)
        except (aiohttp.ClientError, TimeoutError, zlib.error, ValueError) as err:
            raise DotNLError(f"Error reading the DOT-NL dataset: {err!r}") from err
        return prefix_matches

    async def async_get_evses(self, location_ids: set[str]) -> dict[str, list[Evse]]:
        """Return the sockets of the given charge points.

        Stops reading the dataset as soon as all charge points were seen.
        """
        found: dict[str, list[Evse]] = {}
        try:
            async with (
                asyncio.timeout(LOOKUP_TIMEOUT.total_seconds()),
                aclosing(self._async_iter_locations()) as locations,
            ):
                async for location in locations:
                    if (location_id := _location_id(location)) in location_ids:
                        found[location_id] = parse_evses(location)
                        if len(found) == len(location_ids):
                            break
        except (aiohttp.ClientError, TimeoutError, zlib.error, ValueError) as err:
            raise DotNLError(f"Error reading the DOT-NL dataset: {err!r}") from err
        return found
