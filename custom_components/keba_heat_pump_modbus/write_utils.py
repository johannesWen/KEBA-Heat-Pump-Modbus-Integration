from __future__ import annotations

import asyncio
from typing import Callable

from homeassistant.core import HomeAssistant

from .coordinator import KebaCoordinator
from .modbus_client import KebaModbusClient
from .models import ModbusRegister


def values_equal(
    current: float | int | bool | str | None,
    new: float | int | bool | str,
    precision: int | None,
) -> bool:
    if current is None:
        return False
    if isinstance(current, str) or isinstance(new, str):
        return str(current) == str(new)
    if isinstance(current, bool) or isinstance(new, bool):
        return bool(current) == bool(new)
    if isinstance(current, (int, float)) and isinstance(new, (int, float)):
        if precision is not None:
            return round(float(current), precision) == round(float(new), precision)
        return float(current) == float(new)
    return current == new


class DebouncedRegisterWriter:
    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: KebaCoordinator,
        client: KebaModbusClient,
        reg: ModbusRegister,
        current_value: Callable[[], float | int | bool | str | None],
        delay: float | None = None,
    ) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self._client = client
        self._reg = reg
        self._current_value = current_value
        if delay is None:
            # Read at runtime so tests can monkeypatch const.WRITE_DEBOUNCE_SECONDS.
            from .const import WRITE_DEBOUNCE_SECONDS

            delay = WRITE_DEBOUNCE_SECONDS
        self._delay = float(delay)
        self._pending_task: asyncio.Task[None] | None = None
        self._pending_value: float | int | bool | str | None = None

    def cancel(self) -> None:
        if self._pending_task is not None:
            self._pending_task.cancel()
            self._pending_task = None

    async def schedule(self, value: float | int | bool | str) -> None:
        if values_equal(self._current_value(), value, self._reg.precision):
            return
        self._pending_value = value

        # For unit tests (often using asyncio.run) and for callers that want immediate
        # writes, allow delay=0 to execute synchronously.
        if self._delay <= 0:
            await self._write_pending()
            return

        if self._pending_task is not None:
            self._pending_task.cancel()
        create_task = getattr(self._hass, "async_create_task", None)
        if callable(create_task):
            self._pending_task = create_task(self._delayed_write())
        else:
            # Fallback for lightweight test stubs that don't implement hass.async_create_task.
            self._pending_task = asyncio.create_task(self._delayed_write())

    async def _write_pending(self) -> None:
        value = self._pending_value
        if value is None:
            return
        if values_equal(self._current_value(), value, self._reg.precision):
            return
        await self._hass.async_add_executor_job(
            self._client.write_register, self._reg, value
        )
        await self._coordinator.async_request_refresh()

    async def _delayed_write(self) -> None:
        try:
            await asyncio.sleep(self._delay)
        except asyncio.CancelledError:
            return
        await self._write_pending()
