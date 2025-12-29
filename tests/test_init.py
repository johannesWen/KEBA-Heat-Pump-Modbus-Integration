import pytest

from custom_components.keba_heat_pump_modbus.__init__ import _filter_circuit_registers
from custom_components.keba_heat_pump_modbus.models import ModbusRegister


def test_filter_circuit_registers_limits_to_installed_circuits():
    registers = [
        ModbusRegister(unique_id="sys", name="System", register_type="input", address=0, device="system"),
        ModbusRegister(
            unique_id="c1", name="Circuit 1", register_type="input", address=1, device="circuit_1"
        ),
        ModbusRegister(
            unique_id="c2", name="Circuit 2", register_type="input", address=2, device="circuit_2"
        ),
        ModbusRegister(
            unique_id="c3", name="Circuit 3", register_type="input", address=3, device="circuit_3"
        ),
        ModbusRegister(
            unique_id="bad", name="Broken", register_type="input", address=4, device="circuit_x"
        ),
    ]

    filtered = _filter_circuit_registers(registers, num_circuits=2)

    ids = [reg.unique_id for reg in filtered]
    assert "sys" in ids
    assert "c1" in ids
    assert "c2" in ids
    assert "c3" not in ids  # circuit_3 filtered out
    assert "bad" not in ids  # invalid circuit key ignored


def test_filter_circuit_registers_keeps_exact_match():
    registers = [
        ModbusRegister(unique_id="c1", name="Circuit 1", register_type="input", address=1, device="circuit_1"),
        ModbusRegister(unique_id="c2", name="Circuit 2", register_type="input", address=2, device="circuit_2"),
    ]

    filtered = _filter_circuit_registers(registers, num_circuits=2)

    assert len(filtered) == 2
    assert filtered == registers


def test_filter_circuit_registers_handles_missing_index():
    registers = [
        ModbusRegister(
            unique_id="bad",
            name="Bad",
            register_type="input",
            address=1,
            device="circuit_",
        ),
        ModbusRegister(
            unique_id="sys",
            name="System",
            register_type="input",
            address=2,
            device="system",
        ),
    ]

    filtered = _filter_circuit_registers(registers, num_circuits=1)

    assert [reg.unique_id for reg in filtered] == ["sys"]


def test_async_unload_entry_closes_client():
    import asyncio

    class DummyClient:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class DummyConfigEntries:
        async def async_unload_platforms(self, *_args, **_kwargs):
            return True

    class DummyHass:
        def __init__(self):
            self.data = {}
            self.config_entries = DummyConfigEntries()

        async def async_add_executor_job(self, func, *args, **kwargs):
            return func(*args, **kwargs)

    from custom_components.keba_heat_pump_modbus.__init__ import (
        async_unload_entry,
    )
    from custom_components.keba_heat_pump_modbus.const import (
        DATA_CLIENT,
        DOMAIN,
    )
    from homeassistant.config_entries import ConfigEntry

    hass = DummyHass()
    entry = ConfigEntry(entry_id="entry1")
    client = DummyClient()
    hass.data = {DOMAIN: {entry.entry_id: {DATA_CLIENT: client}}}

    result = asyncio.run(async_unload_entry(hass, entry))

    assert result is True
    assert client.closed is True
