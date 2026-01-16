from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DATA_COORDINATOR, DATA_REGISTERS, DEVICE_NAME_MAP
from .models import ModbusRegister
from .coordinator import KebaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: KebaCoordinator = data[DATA_COORDINATOR]
    registers: List[ModbusRegister] = data[DATA_REGISTERS]

    entities: List[SensorEntity] = []

    for reg in registers:
        if reg.entity_platform != "sensor":
            continue
        entities.append(KebaSensor(coordinator, entry, reg))

    register_ids = {reg.unique_id for reg in registers}
    if {
        "heat_power_consumption",
        "flow_temperature",
        "reflux_temperature",
    }.issubset(register_ids):
        entities.append(KebaFlowRateSensor(coordinator, entry))

    async_add_entities(entities)


class KebaSensor(CoordinatorEntity[KebaCoordinator], SensorEntity):
    """Sensor for a single KEBA Modbus datapoint."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: KebaCoordinator, entry: ConfigEntry, reg: ModbusRegister
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._reg = reg

        self._attr_unique_id = f"{entry.entry_id}_{reg.unique_id}"
        self._attr_name = reg.name

        # Common HA attributes
        self._attr_native_unit_of_measurement = reg.unit_of_measurement
        self._attr_icon = reg.icon
        self._attr_device_class = reg.device_class
        self._attr_state_class = reg.state_class
        self._attr_entity_category = reg.entity_category
        self._attr_entity_registry_enabled_default = reg.enabled_default
        if reg.precision is not None:
            self._attr_suggested_display_precision = reg.precision

    @property
    def device_info(self) -> Dict[str, Any]:
        device_key = self._reg.device or "heat_pump"
        device_name = DEVICE_NAME_MAP.get(
            device_key, device_key.replace("_", " ").title()
        )

        return {
            "identifiers": {(DOMAIN, f"{self._entry.entry_id}_{device_key}")},
            "name": f"{device_name}",
            "manufacturer": "KEBA",
            "model": "Heat Pump (Modbus)",
            "configuration_url": None,
        }

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._reg.unique_id)


class KebaFlowRateSensor(CoordinatorEntity[KebaCoordinator], SensorEntity):
    """Derived flow rate sensor based on heat power and delta temperature."""

    _attr_has_entity_name = True
    _attr_name = "Flow Rate"
    _attr_native_unit_of_measurement = "L/h"
    _attr_icon = "mdi:waves"
    _attr_state_class = "measurement"
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: KebaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_flow_rate"

    @property
    def device_info(self) -> Dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, f"{self._entry.entry_id}_heat_pump")},
            "name": "Heat Pump",
            "manufacturer": "KEBA",
            "model": "Heat Pump (Modbus)",
            "configuration_url": None,
        }

    @property
    def native_value(self) -> Optional[float]:
        if self.coordinator.data is None:
            return None

        heat_power = self.coordinator.data.get("heat_power_consumption")
        flow_temp = self.coordinator.data.get("flow_temperature")
        reflux_temp = self.coordinator.data.get("reflux_temperature")

        if heat_power is None or flow_temp is None or reflux_temp is None:
            return None

        delta_temp = flow_temp - reflux_temp
        if delta_temp <= 0:
            return None

        return round((heat_power * 3600) / (4186 * delta_temp), 1)
