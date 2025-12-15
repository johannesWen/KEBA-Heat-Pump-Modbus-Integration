import asyncio

from custom_components.keba_heat_pump_modbus.__init__ import _async_load_registers
from custom_components.keba_heat_pump_modbus.models import ModbusRegister


class DummyHass:
    def __init__(self):
        self.executor_calls = 0

    async def async_add_executor_job(self, func):
        self.executor_calls += 1
        return func()


def test_async_load_registers_reads_default_files():
    hass = DummyHass()

    registers = asyncio.run(_async_load_registers(hass))

    assert registers
    assert all(isinstance(reg, ModbusRegister) for reg in registers)
    assert hass.executor_calls == 1
