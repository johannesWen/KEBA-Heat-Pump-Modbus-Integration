import asyncio
from typing import Any, cast

from custom_components.keba_heat_pump_modbus.models import ModbusRegister
from custom_components.keba_heat_pump_modbus.write_utils import (
    DebouncedRegisterWriter,
    values_equal,
)


def test_values_equal_handles_types_and_precision():
    assert values_equal(None, 1, None) is False

    assert values_equal("a", "a", None) is True
    assert values_equal("a", "b", None) is False

    assert values_equal(True, 1, None) is True
    assert values_equal(False, 0, None) is True
    assert values_equal(False, 1, None) is False

    assert values_equal(1.234, 1.235, 2) is False
    assert values_equal(1.234, 1.2339, 2) is True

    assert values_equal(5.0, 5, None) is True
    assert values_equal(5.0, 6, None) is False


class _DummyCoordinator:
    def __init__(self):
        self.refresh_called = False

    async def async_request_refresh(self):
        self.refresh_called = True


class _DummyClient:
    def __init__(self):
        self.writes: list[tuple[ModbusRegister, object]] = []

    def write_register(self, reg: ModbusRegister, value):
        self.writes.append((reg, value))


class _DummyHassNoCreateTask:
    async def async_add_executor_job(self, func, *args, **kwargs):
        return func(*args, **kwargs)


class _DummyHassWithCreateTask(_DummyHassNoCreateTask):
    def async_create_task(self, coro):
        return asyncio.create_task(coro)


def test_debounced_writer_delay_zero_writes_immediately():
    hass = cast(Any, _DummyHassNoCreateTask())
    coordinator = _DummyCoordinator()
    client = _DummyClient()
    reg = ModbusRegister(
        unique_id="w",
        name="Writable",
        register_type="holding",
        address=1,
        data_type="uint16",
    )

    current = 10

    def current_value():
        return current

    writer = DebouncedRegisterWriter(
        hass=hass,
        coordinator=cast(Any, coordinator),
        client=cast(Any, client),
        reg=reg,
        current_value=current_value,
        delay=0,
    )

    async def _run():
        nonlocal current
        await writer.schedule(11)
        assert client.writes == [(reg, 11)]
        assert coordinator.refresh_called is True

        # If the state catches up, redundant writes are skipped.
        current = 11
        coordinator.refresh_called = False
        await writer.schedule(11)
        assert client.writes == [(reg, 11)]
        assert coordinator.refresh_called is False

    asyncio.run(_run())


def test_debounced_writer_cancel_prevents_delayed_write():
    hass = cast(Any, _DummyHassNoCreateTask())
    coordinator = _DummyCoordinator()
    client = _DummyClient()
    reg = ModbusRegister(
        unique_id="w",
        name="Writable",
        register_type="holding",
        address=1,
        data_type="uint16",
    )

    current = 0

    def current_value():
        return current

    writer = DebouncedRegisterWriter(
        hass=hass,
        coordinator=cast(Any, coordinator),
        client=cast(Any, client),
        reg=reg,
        current_value=current_value,
        delay=0.05,
    )

    async def _run():
        await writer.schedule(1)
        writer.cancel()
        await asyncio.sleep(0.06)
        assert client.writes == []

        # Now allow it to run once.
        await writer.schedule(2)
        await asyncio.sleep(0.06)
        assert client.writes == [(reg, 2)]

    asyncio.run(_run())


def test_debounced_writer_uses_hass_async_create_task_when_available():
    hass = cast(Any, _DummyHassWithCreateTask())
    coordinator = _DummyCoordinator()
    client = _DummyClient()
    reg = ModbusRegister(
        unique_id="w",
        name="Writable",
        register_type="holding",
        address=1,
        data_type="uint16",
    )

    def current_value():
        return 0

    writer = DebouncedRegisterWriter(
        hass=hass,
        coordinator=cast(Any, coordinator),
        client=cast(Any, client),
        reg=reg,
        current_value=current_value,
        delay=0.01,
    )

    async def _run():
        await writer.schedule(3)
        await asyncio.sleep(0.02)
        assert client.writes == [(reg, 3)]

    asyncio.run(_run())
