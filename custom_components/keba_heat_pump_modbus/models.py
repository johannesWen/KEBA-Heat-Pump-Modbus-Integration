from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


RegisterType = Literal["holding", "input"]
EntityPlatform = Literal["sensor", "binary_sensor", "controls", "select"]


@dataclass
class ModbusRegister:
    unique_id: str
    name: str
    register_type: RegisterType  # "holding" or "input"
    address: int  # Modbus register address (0-based)
    length: int = 1  # number of 16-bit registers (1 for 16-bit, 2 for 32-bit, etc.)
    data_type: str = "uint16"  # "uint16", "int16", "uint32", "int32", "float32"
    unit_of_measurement: str | None = None
    scale: float = 1.0
    offset: float = 0.0
    precision: int | None = None
    device: str = "heat_pump"  # logical device group (heat_pump, dhw_tank, buffer_tank, circuit_1, ...)
    icon: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    entity_category: str | None = None  # "diagnostic", "config", etc.
    enabled_default: bool = True
    entity_platform: EntityPlatform = "sensor"  # sensor / binary_sensor
    # Optional mapping for enumerations or binary values:
    value_map: dict[str, Any] | None = (
        None  # map raw values -> state (as string/bool/etc.)
    )
    native_min_value: float | int | None = None
    native_max_value: float | int | None = None
    native_step: float | int | None = None
