from __future__ import annotations

import logging
from typing import Any, Dict, List

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DATA_CLIENT,
    DATA_COORDINATOR,
    DATA_REGISTERS,
    DEVICE_NAME_MAP,
    DOMAIN,
)
from .coordinator import KebaCoordinator
from .modbus_client import KebaModbusClient
from .models import ModbusRegister
from .write_utils import DebouncedRegisterWriter, values_equal

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: KebaCoordinator = data[DATA_COORDINATOR]
    registers: List[ModbusRegister] = data[DATA_REGISTERS]
    client: KebaModbusClient = data[DATA_CLIENT]

    entities: List[KebaControl] = []

    for reg in registers:
        if reg.entity_platform != "controls":
            continue
        entities.append(KebaControl(coordinator, entry, reg, client))

    async_add_entities(entities)


class KebaControl(CoordinatorEntity[KebaCoordinator], NumberEntity):
    """Number entity representing a writable KEBA Modbus register."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: KebaCoordinator,
        entry: ConfigEntry,
        reg: ModbusRegister,
        client: KebaModbusClient,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._reg = reg
        self._client = client

        self._attr_unique_id = f"{entry.entry_id}_{reg.unique_id}"
        self._attr_name = reg.name

        self._attr_native_unit_of_measurement = reg.unit_of_measurement
        self._attr_icon = reg.icon
        self._attr_device_class = reg.device_class
        self._attr_entity_category = reg.entity_category
        self._attr_entity_registry_enabled_default = reg.enabled_default
        self._attr_native_step = reg.native_step if reg.native_step else 0.1
        self._attr_native_min_value = reg.native_min_value
        self._attr_native_max_value = reg.native_max_value
        self._debounced_writer = DebouncedRegisterWriter(
            hass=coordinator.hass,
            coordinator=self.coordinator,
            client=self._client,
            reg=self._reg,
            current_value=self._current_value,
        )

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

    def _current_value(self) -> Any:
        return self.native_value

    async def async_set_native_value(self, value: float) -> None:
        if values_equal(self.native_value, value, self._reg.precision):
            return
        await self._debounced_writer.schedule(value)

    async def async_will_remove_from_hass(self) -> None:
        self._debounced_writer.cancel()
