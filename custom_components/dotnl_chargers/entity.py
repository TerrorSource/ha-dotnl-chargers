"""Base entity for the DOT-NL Chargers integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DotNLCoordinator


class DotNLEntity(CoordinatorEntity[DotNLCoordinator]):
    """Base class for entities of a charge point."""

    _attr_has_entity_name = True
    _attr_attribution = "Data provided by NDW (DOT-NL)"

    def __init__(self, coordinator: DotNLCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        charge_point = coordinator.data
        self._attr_unique_id = f"{charge_point.id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, charge_point.id)},
            name=coordinator.config_entry.title,
            manufacturer=charge_point.operator,
            model=", ".join(charge_point.connector_types) or None,
            entry_type=DeviceEntryType.SERVICE,
        )
