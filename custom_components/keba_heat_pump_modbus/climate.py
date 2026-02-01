from __future__ import annotations

import logging
from typing import Any, Dict, List

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
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
from .write_utils import DebouncedRegisterWriter, values_equal

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: KebaCoordinator = data[DATA_COORDINATOR]
    registers: List[ModbusRegister] = data[DATA_REGISTERS]
    client: KebaModbusClient = data[DATA_CLIENT]

    entities: List[KebaHeatingCircuitClimate] = []
    circuits = _collect_circuit_registers(registers)
    for device_key, circuit_regs in circuits.items():
        current_temp_reg = circuit_regs.get("current_temp")
        target_temp_reg = circuit_regs.get("target_temp")
        mode_reg = circuit_regs.get("mode")
        if current_temp_reg and target_temp_reg and mode_reg:
            entities.append(
                KebaHeatingCircuitClimate(
                    coordinator=coordinator,
                    entry=entry,
                    current_temp_reg=current_temp_reg,
                    target_temp_reg=target_temp_reg,
                    mode_reg=mode_reg,
                    client=client,
                    device_key=device_key,
                )
            )
        else:
            _LOGGER.debug(
                "Skipping climate entity for %s due to missing registers", device_key
            )

    async_add_entities(entities)


def _collect_circuit_registers(
    registers: List[ModbusRegister],
) -> dict[str, dict[str, ModbusRegister]]:
    circuits: dict[str, dict[str, ModbusRegister]] = {}
    for reg in registers:
        device_key = reg.device or ""
        if not device_key.startswith("circuit_"):
            continue

        circuit_regs = circuits.setdefault(device_key, {})
        if reg.unique_id.startswith("actual_room_temperature_"):
            circuit_regs["current_temp"] = reg
        elif reg.unique_id.startswith(
            "room_set_temperature_"
        ) and not reg.unique_id.startswith("room_set_temperature_reduced_"):
            circuit_regs["target_temp"] = reg
        elif reg.unique_id.startswith("operating_mode_"):
            circuit_regs["mode"] = reg

    return circuits


class KebaHeatingCircuitClimate(CoordinatorEntity[KebaCoordinator], ClimateEntity):
    """Climate entity for a heating circuit."""

    _attr_has_entity_name = True
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]

    def __init__(
        self,
        coordinator: KebaCoordinator,
        entry: ConfigEntry,
        current_temp_reg: ModbusRegister,
        target_temp_reg: ModbusRegister,
        mode_reg: ModbusRegister,
        client: KebaModbusClient,
        device_key: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._current_temp_reg = current_temp_reg
        self._target_temp_reg = target_temp_reg
        self._mode_reg = mode_reg
        self._client = client
        self._device_key = device_key

        self._attr_unique_id = f"{entry.entry_id}_{device_key}_climate"
        self._attr_name = "Thermostat"

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

        self._value_to_preset: dict[int, str] = {}
        self._preset_to_value: dict[str, int] = {}
        self._preset_lookup: dict[str, str] = {}
        self._off_mode_value: int | None = None
        self._heat_mode_value: int | None = None

        value_map = mode_reg.value_map or {}
        for raw_key, raw_value in value_map.items():
            if raw_value is None:
                continue
            try:
                value = int(raw_key)
            except (TypeError, ValueError):
                continue
            preset = str(raw_value)
            self._value_to_preset[value] = preset
            self._preset_to_value[preset.lower()] = value
            self._preset_lookup[preset.lower()] = preset

        if self._preset_to_value:
            self._attr_preset_modes = list(self._value_to_preset.values())
            self._off_mode_value = self._preset_to_value.get("standby")
            self._heat_mode_value = self._preset_to_value.get("day")
            if self._heat_mode_value is None:
                for value, preset in self._value_to_preset.items():
                    if preset.lower() != "standby":
                        self._heat_mode_value = value
                        break
        self._debounced_writer = DebouncedRegisterWriter(
            hass=coordinator.hass,
            coordinator=self.coordinator,
            client=self._client,
            reg=self._target_temp_reg,
            current_value=self._current_target_temperature,
        )

    @property
    def device_info(self) -> Dict[str, Any]:
        device_name = DEVICE_NAME_MAP.get(
            self._device_key, self._device_key.replace("_", " ").title()
        )

        return {
            "identifiers": {(DOMAIN, f"{self._entry.entry_id}_{self._device_key}")},
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

    def _current_target_temperature(self) -> float | None:
        return self.target_temperature

    @property
    def hvac_mode(self) -> HVACMode | None:
        raw_mode = self._raw_mode_value()
        if raw_mode is None:
            return None
        if self._off_mode_value is not None and raw_mode == self._off_mode_value:
            return HVACMode.OFF
        return HVACMode.HEAT

    @property
    def preset_mode(self) -> str | None:
        raw_mode = self._raw_mode_value()
        if raw_mode is None:
            return None
        preset = self._value_to_preset.get(raw_mode)
        return preset

    def _raw_mode_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        raw_mode = self.coordinator.data.get(self._mode_reg.unique_id)
        if raw_mode is None:
            return None
        if isinstance(raw_mode, str):
            normalized = raw_mode.lower()
            if normalized in self._preset_to_value:
                return self._preset_to_value[normalized]
        elif isinstance(raw_mode, (int, float)):
            return int(raw_mode)
        return None

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if ATTR_TEMPERATURE not in kwargs:
            return
        temperature = float(kwargs[ATTR_TEMPERATURE])
        if values_equal(
            self.target_temperature, temperature, self._target_temp_reg.precision
        ):
            return
        await self._debounced_writer.schedule(temperature)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        normalized = preset_mode.lower()
        if normalized not in self._preset_to_value:
            raise ValueError(f"Unsupported preset mode: {preset_mode}")
        mode_value = self._preset_to_value[normalized]
        if values_equal(self._raw_mode_value(), mode_value, None):
            return
        await self.hass.async_add_executor_job(
            self._client.write_register, self._mode_reg, mode_value
        )
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            if self._off_mode_value is None:
                raise ValueError("No standby mode available for this circuit")
            mode_value = self._off_mode_value
        elif hvac_mode == HVACMode.HEAT:
            if self._heat_mode_value is None:
                raise ValueError("No heating mode available for this circuit")
            mode_value = self._heat_mode_value
        else:
            raise ValueError(f"Unsupported HVAC mode: {hvac_mode}")

        if values_equal(self._raw_mode_value(), mode_value, None):
            return
        await self.hass.async_add_executor_job(
            self._client.write_register, self._mode_reg, mode_value
        )
        await self.coordinator.async_request_refresh()

    async def async_will_remove_from_hass(self) -> None:
        self._debounced_writer.cancel()
