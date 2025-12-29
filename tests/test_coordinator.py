import asyncio

import pytest

from custom_components.keba_heat_pump_modbus.coordinator import KebaCoordinator
from custom_components.keba_heat_pump_modbus.models import ModbusRegister
from homeassistant.helpers.update_coordinator import UpdateFailed


class DummyClient:
    def __init__(self, data=None, exc=None):
        self.data = data or {}
        self.exc = exc

    def read_all(self, _registers):
        if self.exc:
            raise self.exc
        return self.data


class DummyHass:
    def __init__(self, exc=None):
        self.exc = exc

    async def async_add_executor_job(self, func, *args, **kwargs):
        if self.exc:
            raise self.exc
        return func(*args, **kwargs)


def test_coordinator_updates_data():
    hass = DummyHass()
    client = DummyClient({"a": 1})
    registers = [
        ModbusRegister(
            unique_id="a",
            name="A",
            register_type="input",
            address=0,
        )
    ]
    coordinator = KebaCoordinator(hass, client, registers, scan_interval=30)

    data = asyncio.run(coordinator._async_update_data())

    assert data == {"a": 1}


def test_coordinator_raises_update_failed():
    hass = DummyHass()
    client = DummyClient(exc=RuntimeError("boom"))
    coordinator = KebaCoordinator(hass, client, [], scan_interval=30)

    with pytest.raises(UpdateFailed):
        asyncio.run(coordinator._async_update_data())
