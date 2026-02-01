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


def test_async_load_registers_reads_single_json_when_directory_missing(monkeypatch):
    import io

    from custom_components.keba_heat_pump_modbus import __init__ as integration

    monkeypatch.setattr(integration.os.path, "isdir", lambda _p: False)

    def fake_open(path, mode="r", encoding=None, **kwargs):  # noqa: ANN001
        assert path.endswith("modbus_registers.json")
        return io.StringIO(
            '{"registers": [{"unique_id": "x", "name": "X", "register_type": "input", "address": 1}]}'
        )

    monkeypatch.setattr("builtins.open", fake_open)

    hass = DummyHass()

    registers = asyncio.run(integration._async_load_registers(hass))

    assert len(registers) == 1
    assert registers[0].unique_id == "x"
