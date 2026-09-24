from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from homeassistant.components import persistent_notification
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import (
    CARD_FILE_NAME,
    CARD_REGISTERED_KEY,
    CARD_URL_PATH,
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_UNIT_ID,
    CONF_CIRCUITS,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DATA_REGISTERS,
    DEFAULT_CIRCUITS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import KebaCoordinator
from .modbus_client import KebaModbusClient
from .models import ModbusRegister

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the KEBA Heat Pump Modbus integration.

    Registers the bundled Lovelace card once per HA boot, independent of
    any config entry. This lets users add the card to a dashboard before
    they have completed the integration's config flow.
    """
    hass.data.setdefault(DOMAIN, {})
    await _async_register_card(hass)
    return True


async def _async_register_card(hass: HomeAssistant) -> None:
    """Register and auto-load the bundled Lovelace card.

    The card is built from ``frontend/`` at release time and shipped inside
    the integration directory under ``static/``. HACS installs it together
    with the Python code, so users do not need a separate Lovelace resource
    entry. Registration is idempotent and only runs once per HA boot.
    """
    if hass.data[DOMAIN].get(CARD_REGISTERED_KEY):
        return

    card_path = Path(__file__).parent / "static" / CARD_FILE_NAME
    if not card_path.is_file():
        _LOGGER.warning(
            "Bundled Lovelace card not found at %s; the card will not be "
            "auto-loaded. Build it with `npm run build` in the frontend/ "
            "directory. The integration itself remains functional.",
            card_path,
        )
        return

    # Companion apps cache static assets aggressively. Use a content hash
    # as a cache-busting query parameter so updates are picked up without
    # clearing the app cache manually.
    card_url = CARD_URL_PATH
    try:
        digest = hashlib.sha256(card_path.read_bytes()).hexdigest()[:12]
        card_url = f"{CARD_URL_PATH}?v={digest}"
    except OSError:
        _LOGGER.debug(
            "Could not hash the bundled card for cache-busting; "
            "serving the card at its unversioned URL.",
            exc_info=True,
        )

    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL_PATH, str(card_path), cache_headers=True)]
        )
        add_extra_js_url(hass, card_url)
    except KeyError:
        _LOGGER.warning(
            "Frontend integration is not loaded; the bundled Lovelace card "
            "will not be auto-loaded. Enable the frontend integration to use "
            "the card."
        )
        return

    hass.data[DOMAIN][CARD_REGISTERED_KEY] = True
    _LOGGER.info("Bundled Lovelace card registered at %s", card_url)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up KEBA Heat Pump Modbus from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    host = entry.options.get(CONF_HOST, entry.data[CONF_HOST])
    port = entry.options.get(CONF_PORT, entry.data[CONF_PORT])
    unit_id = entry.options.get(CONF_UNIT_ID, entry.data[CONF_UNIT_ID])
    scan_interval = entry.options.get(
        CONF_SCAN_INTERVAL,
        entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )
    num_circuits = entry.options.get(
        CONF_CIRCUITS,
        entry.data.get(CONF_CIRCUITS, DEFAULT_CIRCUITS),
    )

    # 🔁 Load registers in executor (no blocking I/O in event loop)
    registers = await _async_load_registers(hass)

    registers = _filter_circuit_registers(registers, num_circuits)

    def _notify_write_warning(count: int) -> None:
        message = (
            "Modbus write operations exceeded the weekly threshold. Please be careful to avoid excessive writes which can wear out the device's flash memory.\n\n"
            f"Detected {count} writes in the past 7 days."
        )
        title = "KEBA heat pump Modbus write warning"
        notification_id = f"{DOMAIN}_{entry.entry_id}_write_warning"

        def _schedule_notification() -> None:
            persistent_notification.async_create(
                hass,
                message,
                title,
                notification_id=notification_id,
            )

        hass.loop.call_soon_threadsafe(_schedule_notification)

    client = KebaModbusClient(
        host, port, unit_id, warning_callback=_notify_write_warning
    )

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

    # Register the bundled card (idempotent: skips if already registered).
    await _async_register_card(hass)

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


def _filter_circuit_registers(
    registers: List[ModbusRegister], num_circuits: int
) -> List[ModbusRegister]:
    """Return registers for installed circuits only.

    Registers belonging to circuits above ``num_circuits`` are filtered out so
    the corresponding device (and its entities) are not created at all.
    """

    filtered: List[ModbusRegister] = []

    for reg in registers:
        device_key = reg.device or ""

        if device_key.startswith("circuit_"):
            try:
                circuit_index = int(device_key.split("_")[1])
            except (IndexError, ValueError):
                _LOGGER.debug(
                    "Skipping circuit register with unexpected device key: %s",
                    device_key,
                )
                continue

            if circuit_index > num_circuits:
                _LOGGER.debug(
                    "Filtering out register %s for non-installed circuit %s",
                    reg.unique_id,
                    circuit_index,
                )
                continue

        filtered.append(reg)

    return filtered
