from __future__ import annotations

import logging
from typing import Any, Dict, List

from homeassistant.components.water_heater import (
    STATE_ECO,
    STATE_HEAT_PUMP,
    STATE_OFF,
    STATE_PERFORMANCE,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_CLIENT, DATA_COORDINATOR, DATA_REGISTERS, DEVICE_NAME_MAP, DOMAIN
from .coordinator import KebaCoordinator
from .modbus_client import KebaModbusClient
from .models import ModbusRegister

_LOGGER = logging.getLogger(__name__)

_OPERATION_TO_VALUE = {
    "off": 0,
    STATE_OFF: 0,
    "automatic": 1,
    STATE_ECO: 1,
    "on": 2,
    STATE_HEAT_PUMP: 2,
    "manual": 3,
    STATE_PERFORMANCE: 3,
}
_STRING_TO_VALUE = {key.lower(): value for key, value in _OPERATION_TO_VALUE.items()}
_VALUE_TO_OPERATION = {
    0: STATE_OFF,
    1: STATE_ECO,
    2: STATE_HEAT_PUMP,
    3: STATE_PERFORMANCE,
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: KebaCoordinator = data[DATA_COORDINATOR]
    registers: List[ModbusRegister] = data[DATA_REGISTERS]
    client: KebaModbusClient = data[DATA_CLIENT]

    entities: List[KebaWaterHeater] = []

    current_temp_reg = _get_register(registers, "temperature_top_dhw_tank1")
    target_temp_reg = _get_register(registers, "temperature_top_set_dhw_tank1")
    mode_reg = _get_register(registers, "operating_mode_dhw_tank1")

    if current_temp_reg and target_temp_reg and mode_reg:
        entities.append(
            KebaWaterHeater(
                coordinator=coordinator,
                entry=entry,
                current_temp_reg=current_temp_reg,
                target_temp_reg=target_temp_reg,
                mode_reg=mode_reg,
                client=client,
            )
        )
    else:
        _LOGGER.warning("Missing one or more DHW tank registers; water heater not created")

    async_add_entities(entities)


def _get_register(registers: List[ModbusRegister], unique_id: str) -> ModbusRegister | None:
    for reg in registers:
        if reg.unique_id == unique_id:
            return reg
    return None


class KebaWaterHeater(CoordinatorEntity[KebaCoordinator], WaterHeaterEntity):
    """Water heater entity for the domestic hot water tank."""

    _attr_has_entity_name = True
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
    )
    _attr_operation_list = [STATE_OFF, STATE_ECO, STATE_HEAT_PUMP, STATE_PERFORMANCE]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        coordinator: KebaCoordinator,
        entry: ConfigEntry,
        current_temp_reg: ModbusRegister,
        target_temp_reg: ModbusRegister,
        mode_reg: ModbusRegister,
        client: KebaModbusClient,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._current_temp_reg = current_temp_reg
        self._target_temp_reg = target_temp_reg
        self._mode_reg = mode_reg
        self._client = client

        self._attr_unique_id = f"{entry.entry_id}_{mode_reg.unique_id}_water_heater"
        self._attr_name = "Hot Water Tank"
        self._attr_icon = "mdi:water-boiler"

        self._attr_min_temp = (
            target_temp_reg.native_min_value
            if target_temp_reg.native_min_value is not None
            else None
        )
        self._attr_max_temp = (
            target_temp_reg.native_max_value
            if target_temp_reg.native_max_value is not None
            else None
        )
        self._attr_target_temperature_step = (
            float(target_temp_reg.native_step)
            if target_temp_reg.native_step is not None
            else 0.5
        )

    @property
    def device_info(self) -> Dict[str, Any]:
        device_key = self._target_temp_reg.device or "dhw_tank"
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
    def current_temperature(self) -> float | None:
        if self.coordinator.data is None:
            return None
        value = self.coordinator.data.get(self._current_temp_reg.unique_id)
        return float(value) if value is not None else None

    @property
    def target_temperature(self) -> float | None:
        if self.coordinator.data is None:
            return None
        value = self.coordinator.data.get(self._target_temp_reg.unique_id)
        return float(value) if value is not None else None

    @property
    def current_operation(self) -> str | None:
        if self.coordinator.data is None:
            return None
        raw_mode = self.coordinator.data.get(self._mode_reg.unique_id)
        if raw_mode is None:
            return None

        if isinstance(raw_mode, str):
            normalized = raw_mode.lower()
            if normalized in _STRING_TO_VALUE:
                value = _STRING_TO_VALUE[normalized]
                return _VALUE_TO_OPERATION.get(value)
        elif isinstance(raw_mode, (int, float)):
            return _VALUE_TO_OPERATION.get(int(raw_mode))

        return None

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if ATTR_TEMPERATURE not in kwargs:
            return
        temperature = float(kwargs[ATTR_TEMPERATURE])
        await self.hass.async_add_executor_job(
            self._client.write_register, self._target_temp_reg, temperature
        )
        await self.coordinator.async_request_refresh()

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        normalized = operation_mode.lower()
        if normalized not in _STRING_TO_VALUE:
            raise ValueError(f"Unsupported operation mode: {operation_mode}")
        mode_value = _STRING_TO_VALUE[normalized]
        await self.hass.async_add_executor_job(
            self._client.write_register, self._mode_reg, mode_value
        )
        await self.coordinator.async_request_refresh()
