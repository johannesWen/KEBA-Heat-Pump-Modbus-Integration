from __future__ import annotations

import logging
from typing import Any, Dict, List

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

    entities: List[KebaSensor] = []

    for reg in registers:
        if reg.entity_platform != "sensor":
            continue
        entities.append(KebaSensor(coordinator, entry, reg))

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
