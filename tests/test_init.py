import pytest

from custom_components.keba_heat_pump_modbus.__init__ import _filter_circuit_registers
from custom_components.keba_heat_pump_modbus.models import ModbusRegister


def test_filter_circuit_registers_limits_to_installed_circuits():
    registers = [
        ModbusRegister(unique_id="sys", name="System",
                       register_type="input", address=0, device="system"),
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
        ModbusRegister(unique_id="c1", name="Circuit 1",
                       register_type="input", address=1, device="circuit_1"),
        ModbusRegister(unique_id="c2", name="Circuit 2",
                       register_type="input", address=2, device="circuit_2"),
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


def test_async_setup_entry_populates_data_and_schedules_warning(monkeypatch):
    import asyncio

    from custom_components.keba_heat_pump_modbus import __init__ as integration
    from custom_components.keba_heat_pump_modbus.const import (
        CONF_HOST,
        CONF_PORT,
        CONF_UNIT_ID,
        DATA_CLIENT,
        DATA_COORDINATOR,
        DATA_REGISTERS,
        DOMAIN,
        PLATFORMS,
    )
    from homeassistant.config_entries import ConfigEntry

    notifications: list[dict] = []

    def fake_async_create(hass, message, title=None, notification_id=None):  # noqa: ANN001
        notifications.append(
            {
                "message": message,
                "title": title,
                "notification_id": notification_id,
            }
        )

    monkeypatch.setattr(integration.persistent_notification,
                        "async_create", fake_async_create)

    class DummyLoop:
        def call_soon_threadsafe(self, func, *args, **kwargs):
            func(*args, **kwargs)

    class DummyConfigEntries:
        def __init__(self):
            self.forwarded: list[tuple] = []

        async def async_forward_entry_setups(self, entry, platforms):
            self.forwarded.append((entry, platforms))

    class DummyHass:
        def __init__(self):
            self.data = {}
            self.loop = DummyLoop()
            self.config_entries = DummyConfigEntries()

        async def async_add_executor_job(self, func, *args, **kwargs):
            return func(*args, **kwargs)

    class FakeClient:
        def __init__(self, host, port, unit_id, warning_callback=None):
            self.host = host
            self.port = port
            self.unit_id = unit_id
            self.warning_callback = warning_callback

    class FakeCoordinator:
        def __init__(self, hass, client, registers, scan_interval):
            self.hass = hass
            self.client = client
            self.registers = registers
            self.scan_interval = scan_interval
            self.first_refresh = False

        async def async_config_entry_first_refresh(self):
            self.first_refresh = True

    async def fake_load_registers(_hass):
        return []

    monkeypatch.setattr(integration, "KebaModbusClient", FakeClient)
    monkeypatch.setattr(integration, "KebaCoordinator", FakeCoordinator)
    monkeypatch.setattr(
        integration, "_async_load_registers", fake_load_registers)

    hass = DummyHass()
    entry = ConfigEntry(
        data={CONF_HOST: "localhost", CONF_PORT: 502, CONF_UNIT_ID: 1},
        entry_id="entry1",
    )

    ok = asyncio.run(integration.async_setup_entry(hass, entry))

    assert ok is True
    assert DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]
    stored = hass.data[DOMAIN][entry.entry_id]
    assert set(stored.keys()) == {DATA_CLIENT,
                                  DATA_COORDINATOR, DATA_REGISTERS}
    assert stored[DATA_COORDINATOR].first_refresh is True
    assert hass.config_entries.forwarded == [(entry, PLATFORMS)]

    # Exercise the warning notification callback path.
    stored[DATA_CLIENT].warning_callback(42)
    assert notifications
    assert notifications[0]["notification_id"] == f"{DOMAIN}_{entry.entry_id}_write_warning"


def test_async_unload_entry_handles_missing_data():
    import asyncio

    from custom_components.keba_heat_pump_modbus.__init__ import async_unload_entry
    from custom_components.keba_heat_pump_modbus.const import DOMAIN
    from homeassistant.config_entries import ConfigEntry

    class DummyConfigEntries:
        async def async_unload_platforms(self, *_args, **_kwargs):
            return True

    class DummyHass:
        def __init__(self):
            self.data = {DOMAIN: {}}
            self.config_entries = DummyConfigEntries()

        async def async_add_executor_job(self, func, *args, **kwargs):
            return func(*args, **kwargs)

    hass = DummyHass()
    entry = ConfigEntry(entry_id="missing")

    assert asyncio.run(async_unload_entry(hass, entry)) is True
