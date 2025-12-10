from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_UNIT_ID,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DATA_REGISTERS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import KebaCoordinator
from .modbus_client import KebaModbusClient
from .models import ModbusRegister

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up via YAML is not supported; config flow only."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up KEBA Heat Pump Modbus from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    unit_id = entry.data[CONF_UNIT_ID]
    scan_interval = entry.options.get(
        CONF_SCAN_INTERVAL,
        entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )

    # 🔁 Load registers in executor (no blocking I/O in event loop)
    registers = await _async_load_registers(hass)

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

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    data = hass.data[DOMAIN].pop(entry.entry_id, None)
    if data is not None:
        client: KebaModbusClient = data.get(DATA_CLIENT)
        if client:
            await hass.async_add_executor_job(client.close)

    return unload_ok


async def _async_load_registers(hass: HomeAssistant) -> List[ModbusRegister]:
    """Load Modbus register descriptions from JSON files in a worker thread."""
    base_path = os.path.dirname(__file__)
    register_dir = os.path.join(base_path, "modbus_registers")
    json_path = os.path.join(base_path, "modbus_registers.json")

    def _load() -> List[ModbusRegister]:
        regs: List[ModbusRegister] = []

        if os.path.isdir(register_dir):
            for file_name in sorted(os.listdir(register_dir)):
                if not file_name.endswith(".json"):
                    continue

                file_path = os.path.join(register_dir, file_name)
                with open(file_path, "r", encoding="utf-8") as f:
                    data: Dict[str, Any] = json.load(f)

                for item in data.get("registers", []):
                    regs.append(ModbusRegister(**item))

                _LOGGER.debug(
                    "Loaded %s Modbus registers from %s",
                    len(data.get("registers", [])),
                    file_path,
                )
            _LOGGER.info(
                "Loaded %s Modbus registers from %s", len(regs), register_dir
            )
        else:
            with open(json_path, "r", encoding="utf-8") as f:
                data: Dict[str, Any] = json.load(f)

            for item in data.get("registers", []):
                regs.append(ModbusRegister(**item))

            _LOGGER.info(
                "Loaded %s Modbus registers from %s", len(regs), json_path
            )

        return regs

    # Run _load() in executor pool
    return await hass.async_add_executor_job(_load)
