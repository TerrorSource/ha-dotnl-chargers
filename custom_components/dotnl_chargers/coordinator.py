"""Data update coordinator for the DOT-NL Chargers integration."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ChargePoint, DotNLClient, DotNLError, Evse
from .const import (
    CONF_CHARGE_POINT_ID,
    CONF_EVSES,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_EVSE_RETRIES,
    POLL_FALLBACK_RADIUS,
    POLL_RADIUS,
    STALE_AFTER,
)

_LOGGER = logging.getLogger(__name__)

type DotNLConfigEntry = ConfigEntry[DotNLCoordinator]


class EvseStore:
    """Read the national dataset once for all charge points that need it.

    The status of individual sockets is only published in a ~17 MB file, so
    lookups that happen at the same time share a single pass over it.
    """

    def __init__(self, client: DotNLClient) -> None:
        """Initialize the store."""
        self._client = client
        self._ids: set[str] = set()
        self._fetch: tuple[frozenset[str], asyncio.Future[dict[str, list[Evse]]]] | None
        self._fetch = None

    def register(self, charge_point_id: str) -> None:
        """Include a charge point in future passes."""
        self._ids.add(charge_point_id)

    def unregister(self, charge_point_id: str) -> None:
        """Stop looking up a charge point."""
        self._ids.discard(charge_point_id)

    async def async_get(self, charge_point_id: str) -> list[Evse] | None:
        """Return the current sockets of a charge point."""
        while self._fetch is not None and charge_point_id not in self._fetch[0]:
            await asyncio.wait([self._fetch[1]])
        if self._fetch is None:
            ids = frozenset(self._ids | {charge_point_id})
            self._fetch = (ids, asyncio.ensure_future(self._async_fetch(ids)))
        return (await asyncio.shield(self._fetch[1])).get(charge_point_id)

    async def _async_fetch(self, ids: frozenset[str]) -> dict[str, list[Evse]]:
        try:
            return await self._client.async_get_evses(set(ids))
        finally:
            self._fetch = None


class DotNLCoordinator(DataUpdateCoordinator[ChargePoint]):
    """Poll DOT-NL for the availability of one charge point."""

    config_entry: DotNLConfigEntry

    def __init__(self, hass: HomeAssistant, entry: DotNLConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = DotNLClient(async_get_clientsession(hass))
        self.charge_point_id: str = entry.data[CONF_CHARGE_POINT_ID]
        self._latitude: float = entry.data[CONF_LATITUDE]
        self._longitude: float = entry.data[CONF_LONGITUDE]

        self.evses: dict[str, Evse] = {
            evse.uid: evse
            for evse in map(Evse.from_dict, entry.data.get(CONF_EVSES, []))
        }
        if DOMAIN not in hass.data:
            hass.data[DOMAIN] = EvseStore(self.client)
        self._store: EvseStore = hass.data[DOMAIN]
        self._store.register(self.charge_point_id)
        entry.async_on_unload(lambda: self._store.unregister(self.charge_point_id))
        self._evses_known = CONF_EVSES in entry.data
        self._resolved: tuple[int, datetime | None] | None = None
        self._last_success: datetime | None = None
        self._retries = 0

    async def _async_update_data(self) -> ChargePoint:
        try:
            charge_point = await self._async_fetch_charge_point()
        except UpdateFailed as err:
            if (
                self._last_success is None
                or dt_util.utcnow() - self._last_success >= STALE_AFTER
            ):
                raise
            _LOGGER.debug("Keeping last known data of %s: %s", self.name, err)
            return self.data
        self._last_success = dt_util.utcnow()
        return charge_point

    async def _async_fetch_charge_point(self) -> ChargePoint:
        try:
            charge_point = await self.client.async_get_charge_point(
                self.charge_point_id, self._latitude, self._longitude, POLL_RADIUS
            )
            if charge_point is None:
                charge_point = await self.client.async_get_charge_point(
                    self.charge_point_id,
                    self._latitude,
                    self._longitude,
                    POLL_FALLBACK_RADIUS,
                )
        except DotNLError as err:
            raise UpdateFailed(str(err)) from err

        if charge_point is None:
            raise UpdateFailed(
                f"Charge point {self.charge_point_id} is no longer published by DOT-NL"
            )

        # Follow upstream coordinate corrections so the next poll hits the small box.
        self._latitude = charge_point.latitude
        self._longitude = charge_point.longitude

        await self._async_update_evses(charge_point)
        return charge_point

    async def _async_update_evses(self, charge_point: ChargePoint) -> None:
        """Work out which sockets are free.

        The API only reports how many connectors are free. When all or none
        are, that settles every socket; only in between do we have to read the
        national dataset to see which ones.
        """
        signature = (charge_point.available, charge_point.last_updated)
        if self._evses_known and signature == self._resolved:
            return

        connectors = sum(evse.connector_count for evse in self.evses.values())
        if self._evses_known and charge_point.available in (0, connectors):
            self._set_evses(
                [
                    evse.with_available(charge_point.available > 0)
                    for evse in self.evses.values()
                ]
            )
            self._resolved = signature
            return

        try:
            evses = await self._store.async_get(self.charge_point_id)
        except DotNLError as err:
            if not self._evses_known:
                raise UpdateFailed(str(err)) from err
            _LOGGER.debug("Could not update sockets of %s: %s", self.name, err)
            return
        if evses is None:
            if not self._evses_known:
                raise UpdateFailed(
                    f"Charge point {self.charge_point_id} is not in the DOT-NL dataset"
                )
            return

        self._set_evses(evses)
        free = sum(evse.connector_count for evse in evses if evse.available)
        self._retries += 1
        # The dataset can trail the API by a minute; look again on the next poll.
        if free == charge_point.available or self._retries >= MAX_EVSE_RETRIES:
            self._resolved = signature
            self._retries = 0

    def _set_evses(self, evses: list[Evse]) -> None:
        self.evses = {evse.uid: evse for evse in evses}
        self._evses_known = True
        stored = [evse.as_dict() for evse in evses]
        if stored != self.config_entry.data.get(CONF_EVSES):
            # Entities are created per socket; the update listener reloads the
            # entry when sockets were added or replaced.
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_EVSES: stored},
            )
