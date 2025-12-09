from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.const import Platform

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_UNIT_ID,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DATA_COORDINATOR,
    DATA_REGISTERS,
    DATA_CLIENT,
    PLATFORMS,
)
from .models import ModbusRegister
from .modbus_client import KebaModbusClient
from .coordinator import KebaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up via YAML is not supported; config flow only."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up KEBA Modbus from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    unit_id = entry.data[CONF_UNIT_ID]
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))

    registers = _load_registers()

    client = KebaModbusClient(host, port, unit_id)

    coordinator = KebaCoordinator(
        hass=hass,
        client=client,
        registers=registers,
        scan_interval=scan_interval,
    )

    # First refresh to populate data
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CLIENT: client,
        DATA_COORDINATOR: coordinator,
        DATA_REGISTERS: registers,
    }

    await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR])

    data = hass.data[DOMAIN].pop(entry.entry_id, None)
    if data is not None:
        client: KebaModbusClient = data.get(DATA_CLIENT)
        if client:
            await hass.async_add_executor_job(client.close)

    return unload_ok


def _load_registers() -> List[ModbusRegister]:
    """Load Modbus register descriptions from modbus_registers.json."""
    base_path = os.path.dirname(__file__)
    json_path = os.path.join(base_path, "modbus_registers.json")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    registers: List[ModbusRegister] = []
    for item in data.get("registers", []):
        registers.append(ModbusRegister(**item))

    _LOGGER.info("Loaded %s Modbus registers from %s", len(registers), json_path)
    return registers
