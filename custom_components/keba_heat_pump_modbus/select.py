from __future__ import annotations

import logging
from typing import Any, Dict, List

from homeassistant.components.select import SelectEntity
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

    entities: List[KebaSelect] = []

    for reg in registers:
        if reg.entity_platform != "select":
            continue

        if not reg.value_map:
            _LOGGER.warning(
                "Select entity %s has no value_map; skipping", reg.unique_id
            )
            continue

        entities.append(KebaSelect(coordinator, entry, reg, client))

    async_add_entities(entities)


class KebaSelect(CoordinatorEntity[KebaCoordinator], SelectEntity):
    """Select entity representing a writable KEBA Modbus register with a value map."""

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
        self._options = list(reg.value_map.values()) if reg.value_map else []

        self._attr_unique_id = f"{entry.entry_id}_{reg.unique_id}"
        self._attr_name = reg.name
        self._attr_icon = reg.icon
        self._attr_device_class = reg.device_class
        self._attr_entity_category = reg.entity_category
        self._attr_entity_registry_enabled_default = reg.enabled_default
        self._attr_options = self._options

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
    def current_option(self) -> str | None:
        if self.coordinator.data is None:
            return None

        value = self.coordinator.data.get(self._reg.unique_id)
        return value if value in self._options else None

    async def async_select_option(self, option: str) -> None:
        if not self._reg.value_map:
            raise ValueError(f"No value_map defined for {self._reg.unique_id}")

        raw_value: int | None = None
        for key, val in self._reg.value_map.items():
            if val == option:
                try:
                    raw_value = int(key)
                except ValueError as err:  # noqa: BLE001
                    raise ValueError(
                        f"Invalid register key '{key}' for option '{option}'"
                    ) from err
                break

        if raw_value is None:
            raise ValueError(f"Invalid option '{option}' for {self._reg.unique_id}")

        await self.hass.async_add_executor_job(
            self._client.write_register, self._reg, raw_value
        )
        await self.coordinator.async_request_refresh()
