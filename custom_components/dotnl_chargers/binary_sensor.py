"""Binary sensors for the DOT-NL Chargers integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import Evse
from .coordinator import DotNLConfigEntry, DotNLCoordinator
from .entity import DotNLEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DotNLConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensors of a charge point."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            DotNLAvailableBinarySensor(coordinator),
            *(
                DotNLSocketBinarySensor(coordinator, evse, number)
                for number, evse in enumerate(coordinator.evses.values(), start=1)
            ),
        ]
    )


class DotNLAvailableBinarySensor(DotNLEntity, BinarySensorEntity):
    """On when at least one connector of the charge point is free."""

    _attr_translation_key = "available"

    def __init__(self, coordinator: DotNLCoordinator) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, "available")

    @property
    def is_on(self) -> bool:
        """Return true when a connector is free."""
        return self.coordinator.data.available > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        charge_point = self.coordinator.data
        return {"available": charge_point.available, "total": charge_point.total}


class DotNLSocketBinarySensor(DotNLEntity, BinarySensorEntity):
    """On when one specific socket of the charge point is free."""

    _attr_translation_key = "socket"

    def __init__(self, coordinator: DotNLCoordinator, evse: Evse, number: int) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, f"evse_{evse.uid}")
        self._uid = evse.uid
        self._attr_translation_placeholders = {"number": str(number)}

    @property
    def _evse(self) -> Evse | None:
        return self.coordinator.evses.get(self._uid)

    @property
    def available(self) -> bool:
        """Return if the socket is still part of the charge point."""
        return super().available and self._evse is not None

    @property
    def is_on(self) -> bool | None:
        """Return true when the socket is free."""
        return (evse := self._evse) and evse.available

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the state attributes."""
        if (evse := self._evse) is None:
            return None
        return {
            "evse_id": evse.evse_id,
            "connector_type": evse.connector_type,
            "max_power_kw": evse.max_power_kw,
        }
