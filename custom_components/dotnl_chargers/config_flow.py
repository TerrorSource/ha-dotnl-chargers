"""Config flow for the DOT-NL Chargers integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_LATITUDE,
    CONF_LOCATION,
    CONF_LONGITUDE,
    CONF_NAME,
    CONF_RADIUS,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    LocationSelector,
    LocationSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import ChargePoint, DotNLClient, DotNLError, normalize_id
from .const import (
    CONF_CHARGE_POINT,
    CONF_CHARGE_POINT_ID,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SEARCH_RADIUS,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MAX_SEARCH_RADIUS,
    MIN_LOOKUP_LENGTH,
    MIN_SCAN_INTERVAL,
    POLL_FALLBACK_RADIUS,
)


def _label(charge_point: ChargePoint, distance: float | None = None) -> str:
    parts = [charge_point.name]
    if charge_point.operator:
        parts.append(charge_point.operator)
    connectors = f"{charge_point.total}×"
    if charge_point.max_power_kw:
        connectors += f" {charge_point.max_power_kw:g} kW"
    parts.append(connectors)
    if distance is not None:
        parts.append(f"{distance:.0f} m")
    return " · ".join(parts)


class DotNLConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow: find a charge point by ID or on the map."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._charge_points: dict[str, ChargePoint] = {}
        self._options: list[SelectOptionDict] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> DotNLOptionsFlow:
        """Return the options flow."""
        return DotNLOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask how the user wants to find the charge point."""
        return self.async_show_menu(step_id="user", menu_options=["id", "map"])

    async def async_step_id(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Look up a charge point by its EVSE ID or DOT-NL location ID."""
        errors: dict[str, str] = {}

        if user_input is not None:
            query = user_input[CONF_CHARGE_POINT_ID]
            if len(normalize_id(query)) < MIN_LOOKUP_LENGTH:
                errors["base"] = "invalid_id"
            else:
                client = DotNLClient(async_get_clientsession(self.hass))
                try:
                    charge_points = [
                        charge_point
                        for ref in await client.async_find_by_id(query)
                        if (
                            charge_point := await client.async_get_charge_point(
                                ref.id,
                                ref.latitude,
                                ref.longitude,
                                POLL_FALLBACK_RADIUS,
                            )
                        )
                    ]
                except DotNLError:
                    errors["base"] = "cannot_connect"
                else:
                    configured = self._async_current_ids()
                    if not charge_points:
                        errors["base"] = "id_not_found"
                    elif all(cp.id in configured for cp in charge_points):
                        return self.async_abort(reason="already_configured")
                    else:
                        self._charge_points = {
                            cp.id: cp for cp in charge_points if cp.id not in configured
                        }
                        self._options = [
                            SelectOptionDict(value=cp.id, label=_label(cp))
                            for cp in self._charge_points.values()
                        ]
                        return await self.async_step_select()

        return self.async_show_form(
            step_id="id",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_CHARGE_POINT_ID): str}), user_input
            ),
            errors=errors,
        )

    async def async_step_map(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask where to look for charge points."""
        errors: dict[str, str] = {}

        if user_input is not None:
            location = user_input[CONF_LOCATION]
            latitude = location[CONF_LATITUDE]
            longitude = location[CONF_LONGITUDE]
            radius = min(
                location.get(CONF_RADIUS, DEFAULT_SEARCH_RADIUS), MAX_SEARCH_RADIUS
            )
            client = DotNLClient(async_get_clientsession(self.hass))
            try:
                charge_points = await client.async_get_nearby(
                    latitude, longitude, radius
                )
            except DotNLError:
                errors["base"] = "cannot_connect"
            else:
                configured = self._async_current_ids()
                nearby = sorted(
                    (
                        (charge_point.distance_to(latitude, longitude), charge_point)
                        for charge_point in charge_points
                        if charge_point.id not in configured
                    ),
                    key=lambda item: item[0],
                )
                if nearby:
                    self._charge_points = {cp.id: cp for _, cp in nearby}
                    self._options = [
                        SelectOptionDict(value=cp.id, label=_label(cp, distance))
                        for distance, cp in nearby
                    ]
                    return await self.async_step_select()
                errors["base"] = "no_charge_points"

        default_location = (user_input or {}).get(
            CONF_LOCATION,
            {
                CONF_LATITUDE: self.hass.config.latitude,
                CONF_LONGITUDE: self.hass.config.longitude,
                CONF_RADIUS: DEFAULT_SEARCH_RADIUS,
            },
        )
        return self.async_show_form(
            step_id="map",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LOCATION, default=default_location
                    ): LocationSelector(LocationSelectorConfig(radius=True)),
                }
            ),
            errors=errors,
        )

    async def async_step_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick one of the charge points that were found."""
        if user_input is not None:
            charge_point = self._charge_points[user_input[CONF_CHARGE_POINT]]
            await self.async_set_unique_id(charge_point.id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input.get(CONF_NAME) or charge_point.name,
                data={
                    CONF_CHARGE_POINT_ID: charge_point.id,
                    CONF_LATITUDE: charge_point.latitude,
                    CONF_LONGITUDE: charge_point.longitude,
                },
            )

        return self.async_show_form(
            step_id="select",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CHARGE_POINT, default=self._options[0]["value"]
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=self._options, mode=SelectSelectorMode.LIST
                        )
                    ),
                    vol.Optional(CONF_NAME): str,
                }
            ),
        )


class DotNLOptionsFlow(OptionsFlow):
    """Handle the options of a charge point."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=MAX_SCAN_INTERVAL,
                            step=10,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )
