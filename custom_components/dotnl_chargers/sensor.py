"""Sensors for the DOT-NL Chargers integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import ChargePoint, Evse
from .const import STATE_AVAILABLE, STATE_OCCUPIED
from .coordinator import DotNLConfigEntry, DotNLCoordinator
from .entity import DotNLEntity


@dataclass(frozen=True, kw_only=True)
class DotNLSensorEntityDescription(SensorEntityDescription):
    """Describes a DOT-NL sensor."""

    value_fn: Callable[[ChargePoint], int | str | datetime | None]
    attributes_fn: Callable[[ChargePoint], dict[str, Any]] | None = None


def _availability_attributes(charge_point: ChargePoint) -> dict[str, Any]:
    return {
        "total": charge_point.total,
        "address": charge_point.address,
        "operator": charge_point.operator,
        "owner": charge_point.owner,
        "max_power_kw": charge_point.max_power_kw,
        "connectors": [group.as_dict() for group in charge_point.connectors],
        "charge_point_id": charge_point.id,
        ATTR_LATITUDE: charge_point.latitude,
        ATTR_LONGITUDE: charge_point.longitude,
    }


def _state(available: bool) -> str:
    return STATE_AVAILABLE if available else STATE_OCCUPIED


SENSORS: tuple[DotNLSensorEntityDescription, ...] = (
    DotNLSensorEntityDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=[STATE_AVAILABLE, STATE_OCCUPIED],
        value_fn=lambda charge_point: _state(charge_point.available > 0),
        attributes_fn=lambda charge_point: {
            "available": charge_point.available,
            "total": charge_point.total,
        },
    ),
    DotNLSensorEntityDescription(
        key="available_connectors",
        translation_key="available_connectors",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda charge_point: charge_point.available,
        attributes_fn=_availability_attributes,
    ),
    DotNLSensorEntityDescription(
        key="total_connectors",
        translation_key="total_connectors",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda charge_point: charge_point.total,
    ),
    DotNLSensorEntityDescription(
        key="last_updated",
        translation_key="last_updated",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda charge_point: charge_point.last_updated,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DotNLConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors of a charge point."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            *(DotNLSensor(coordinator, description) for description in SENSORS),
            *(
                DotNLSocketSensor(coordinator, evse, number)
                for number, evse in enumerate(coordinator.evses.values(), start=1)
            ),
        ]
    )


class DotNLSensor(DotNLEntity, SensorEntity):
    """Sensor of a charge point."""

    entity_description: DotNLSensorEntityDescription

    def __init__(
        self,
        coordinator: DotNLCoordinator,
        description: DotNLSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | str | datetime | None:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the state attributes."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)


class DotNLSocketSensor(DotNLEntity, SensorEntity):
    """Whether one specific socket of the charge point is free."""

    _attr_translation_key = "socket"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [STATE_AVAILABLE, STATE_OCCUPIED]

    def __init__(self, coordinator: DotNLCoordinator, evse: Evse, number: int) -> None:
        """Initialize the sensor."""
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
    def native_value(self) -> str | None:
        """Return whether the socket is free."""
        return _state(evse.available) if (evse := self._evse) else None

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
