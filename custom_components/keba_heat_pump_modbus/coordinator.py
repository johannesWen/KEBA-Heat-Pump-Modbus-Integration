from __future__ import annotations

import logging
from datetime import timedelta
from typing import Dict, List, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .models import ModbusRegister
from .modbus_client import KebaModbusClient

_LOGGER = logging.getLogger(__name__)


class KebaCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Coordinator to poll KEBA heat pump over Modbus."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: KebaModbusClient,
        registers: List[ModbusRegister],
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} coordinator",
            update_interval=timedelta(seconds=scan_interval),
        )
        self._client = client
        self._registers = registers

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch all register values."""
        try:
            return await self.hass.async_add_executor_job(self._client.read_all, self._registers)
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Error updating KEBA Modbus data: {err}") from err
