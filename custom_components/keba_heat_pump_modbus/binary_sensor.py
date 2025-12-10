from __future__ import annotations

from typing import Any, Dict, List

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DATA_REGISTERS, DEVICE_NAME_MAP, DOMAIN
from .coordinator import KebaCoordinator
from .models import ModbusRegister


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up KEBA binary sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: KebaCoordinator = data[DATA_COORDINATOR]
    registers: List[ModbusRegister] = data[DATA_REGISTERS]

    entities: List[KebaBinarySensor] = []

    for reg in registers:
        if reg.entity_platform != "binary_sensor":
            continue
        entities.append(KebaBinarySensor(coordinator, entry, reg))

    async_add_entities(entities)


class KebaBinarySensor(CoordinatorEntity[KebaCoordinator], BinarySensorEntity):
    """Binary sensor for a single KEBA Modbus datapoint."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: KebaCoordinator, entry: ConfigEntry, reg: ModbusRegister
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._reg = reg

        self._attr_unique_id = f"{entry.entry_id}_{reg.unique_id}"
        self._attr_name = reg.name

        self._attr_icon = reg.icon
        self._attr_device_class = reg.device_class
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
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        value = self.coordinator.data.get(self._reg.unique_id)
        return bool(value) if value is not None else None
