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

from .api import ChargePoint
from .coordinator import DotNLConfigEntry, DotNLCoordinator
from .entity import DotNLEntity


@dataclass(frozen=True, kw_only=True)
class DotNLSensorEntityDescription(SensorEntityDescription):
    """Describes a DOT-NL sensor."""

    value_fn: Callable[[ChargePoint], int | datetime | None]
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


SENSORS: tuple[DotNLSensorEntityDescription, ...] = (
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
    async_add_entities(
        DotNLSensor(entry.runtime_data, description) for description in SENSORS
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
    def native_value(self) -> int | datetime | None:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the state attributes."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)
