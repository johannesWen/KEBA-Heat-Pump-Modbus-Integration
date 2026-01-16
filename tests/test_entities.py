import pytest

from custom_components.keba_heat_pump_modbus.binary_sensor import (
    KebaBinarySensor,
    async_setup_entry as setup_binary_sensors,
)
from custom_components.keba_heat_pump_modbus.climate import (
    KebaHeatingCircuitClimate,
    async_setup_entry as setup_climates,
)
from custom_components.keba_heat_pump_modbus.config_flow import (
    ConfigFlow,
    OptionsFlowHandler,
)
from custom_components.keba_heat_pump_modbus.const import (
    CONF_CIRCUITS,
    CONF_SCAN_INTERVAL,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DATA_REGISTERS,
    DOMAIN,
)
from custom_components.keba_heat_pump_modbus.models import ModbusRegister
from custom_components.keba_heat_pump_modbus.number import (
    KebaControl,
    async_setup_entry as setup_numbers,
)
from custom_components.keba_heat_pump_modbus.select import (
    KebaSelect,
    async_setup_entry as setup_selects,
)
from custom_components.keba_heat_pump_modbus.sensor import (
    KebaSensor,
    KebaCopSensor,
    async_setup_entry as setup_sensors,
)
from custom_components.keba_heat_pump_modbus.water_heater import (
    KebaWaterHeater,
    async_setup_entry as setup_water_heaters,
)
from homeassistant.components.climate import HVACMode
from homeassistant.components.water_heater import (
    STATE_ECO,
    STATE_HEAT_PUMP,
    STATE_OFF,
    STATE_PERFORMANCE,
)


class DummyCoordinator:
    def __init__(self, data=None, hass=None):
        self.data = data or {}
        self.refresh_called = False
        self.hass = hass

    async def async_request_refresh(self):
        self.refresh_called = True


class DummyClient:
    def __init__(self):
        self.writes = []

    def write_register(self, reg, value):
        self.writes.append((reg, value))


class DummyHass:
    def __init__(self):
        self.data = {}

    async def async_add_executor_job(self, func, *args, **kwargs):
        return func(*args, **kwargs)


def create_entry(data=None, options=None, entry_id="entry1"):
    from homeassistant.config_entries import ConfigEntry

    return ConfigEntry(data=data, options=options, entry_id=entry_id)


def test_binary_sensor_entity_behaviour():
    coordinator = DummyCoordinator({"bin": 1, "icon": 0})
    entry = create_entry(entry_id="bin1")
    reg = ModbusRegister(
        unique_id="bin",
        name="Binary",
        register_type="input",
        address=1,
        entity_platform="binary_sensor",
        device="system",
        icon="mdi:eye",
        icon_on="mdi:eye-check",
        icon_off="mdi:eye-off",
    )

    entity = KebaBinarySensor(coordinator, entry, reg)

    assert entity.unique_id == "bin1_bin"
    assert entity.device_info["name"] == "System"
    assert entity.is_on is True
    assert entity.icon == "mdi:eye-check"

    coordinator.data["bin"] = 0
    assert entity.is_on is False
    assert entity.icon == "mdi:eye-off"


def test_binary_sensor_setup_filters_platform():
    hass = DummyHass()
    entry = create_entry()
    coordinator = DummyCoordinator()
    registers = [
        ModbusRegister(
            unique_id="bin",
            name="Binary",
            register_type="input",
            address=1,
            entity_platform="binary_sensor",
        ),
        ModbusRegister(
            unique_id="sensor",
            name="Other",
            register_type="input",
            address=2,
            entity_platform="sensor",
        ),
    ]
    hass.data = {DOMAIN: {entry.entry_id: {
        DATA_COORDINATOR: coordinator, DATA_REGISTERS: registers}}}

    added = []

    def _add_entities(entities):
        added.extend(entities)

    import asyncio

    asyncio.run(setup_binary_sensors(hass, entry, _add_entities))

    assert len(added) == 1
    assert isinstance(added[0], KebaBinarySensor)


def test_config_flow_creates_entries_and_options():
    flow = ConfigFlow()

    import asyncio

    form = asyncio.run(flow.async_step_user())
    assert form["step_id"] == "user"

    user_input = {"host": "1.2.3.4", "heat_circuits_used": 2}
    result = asyncio.run(flow.async_step_user(user_input))
    assert result["title"].startswith("KEBA Heat Pump")
    assert flow._unique_id == f"{DOMAIN}_1.2.3.4"

    entry = create_entry(options={CONF_SCAN_INTERVAL: 10, CONF_CIRCUITS: 2})
    options_flow = OptionsFlowHandler(entry)

    options_form = asyncio.run(options_flow.async_step_user())
    assert options_form["step_id"] == "user"

    options_result = asyncio.run(
        options_flow.async_step_user({CONF_SCAN_INTERVAL: 5, CONF_CIRCUITS: 1})
    )
    assert options_result["data"][CONF_SCAN_INTERVAL] == 5


def test_number_entity_write_and_setup(monkeypatch):
    hass = DummyHass()
    entry = create_entry()
    coordinator = DummyCoordinator({"num": 42}, hass=hass)
    client = DummyClient()
    reg = ModbusRegister(
        unique_id="num",
        name="Number",
        register_type="holding",
        address=5,
        entity_platform="controls",
    )
    hass.data = {
        DOMAIN: {
            entry.entry_id: {
                DATA_COORDINATOR: coordinator,
                DATA_REGISTERS: [reg],
                DATA_CLIENT: client,
            }
        }
    }

    added = []

    def _add_entities(entities):
        added.extend(entities)

    import asyncio

    asyncio.run(setup_numbers(hass, entry, _add_entities))

    assert len(added) == 1
    entity: KebaControl = added[0]
    assert entity.native_value == 42

    asyncio.run(entity.async_set_native_value(55))
    assert client.writes == [(reg, 55)]
    assert coordinator.refresh_called is True


def test_select_entity_options_and_validation():
    hass = DummyHass()
    entry = create_entry()
    coordinator = DummyCoordinator({"sel": "Off"}, hass=hass)
    client = DummyClient()
    valid_reg = ModbusRegister(
        unique_id="sel",
        name="Select",
        register_type="holding",
        address=6,
        entity_platform="select",
        value_map={"0": "Off", "1": "On"},
    )
    invalid_reg = ModbusRegister(
        unique_id="skip",
        name="Skip",
        register_type="holding",
        address=7,
        entity_platform="select",
        value_map=None,
    )
    hass.data = {
        DOMAIN: {
            entry.entry_id: {
                DATA_COORDINATOR: coordinator,
                DATA_REGISTERS: [valid_reg, invalid_reg],
                DATA_CLIENT: client,
            }
        }
    }

    added = []

    def _add_entities(entities):
        added.extend(entities)

    import asyncio

    asyncio.run(setup_selects(hass, entry, _add_entities))

    assert len(added) == 1
    entity: KebaSelect = added[0]
    assert entity.current_option == "Off"

    asyncio.run(entity.async_select_option("On"))
    assert client.writes == [(valid_reg, 1)]
    assert coordinator.refresh_called is True

    with pytest.raises(ValueError):
        asyncio.run(entity.async_select_option("Unknown"))


def test_select_rejects_invalid_value_map_key():
    hass = DummyHass()
    entry = create_entry()
    coordinator = DummyCoordinator({"sel": "Bad"}, hass=hass)
    client = DummyClient()
    reg = ModbusRegister(
        unique_id="sel",
        name="Select",
        register_type="holding",
        address=6,
        entity_platform="select",
        value_map={"bad": "Bad"},
    )
    entity = KebaSelect(coordinator, entry, reg, client)

    import asyncio

    with pytest.raises(ValueError):
        asyncio.run(entity.async_select_option("Bad"))


def test_sensor_entity_native_value_and_setup():
    hass = DummyHass()
    entry = create_entry()
    coordinator = DummyCoordinator(
        {
            "sensor": 12.5,
            "heat_power_consumption": 200.0,
            "electrical_power_consumption": 100.0,
        },
        hass=hass,
    )
    reg = ModbusRegister(
        unique_id="sensor",
        name="Temperature",
        register_type="input",
        address=10,
        entity_platform="sensor",
        unit_of_measurement="°C",
        precision=2,
    )
    hass.data = {
        DOMAIN: {
            entry.entry_id: {
                DATA_COORDINATOR: coordinator,
                DATA_REGISTERS: [reg],
            }
        }
    }

    added = []

    def _add_entities(entities):
        added.extend(entities)

    import asyncio

    asyncio.run(setup_sensors(hass, entry, _add_entities))

    assert len(added) == 2
    entity: KebaSensor = added[0]
    cop_entity: KebaCopSensor = added[1]
    assert entity.native_value == 12.5
    assert entity.device_info["name"] == "Heat Pump"
    assert cop_entity.native_value == 2.0


def test_cop_sensor_handles_missing_or_invalid_values():
    coordinator = DummyCoordinator(
        {
            "heat_power_consumption": 120.0,
            "electrical_power_consumption": 0.0,
        }
    )
    entry = create_entry()
    cop_entity = KebaCopSensor(coordinator, entry)

    assert cop_entity.device_info["name"] == "Heat Pump"

    assert cop_entity.native_value is None

    coordinator.data["electrical_power_consumption"] = 60.0
    assert cop_entity.native_value == 2.0

    coordinator.data["heat_power_consumption"] = "unknown"
    assert cop_entity.native_value is None


def _create_water_heater_registers():
    return (
        ModbusRegister(
            unique_id="temperature_top_dhw_tank1",
            name="Top Temperature",
            register_type="input",
            address=11,
            entity_platform="sensor",
            device="dhw_tank",
        ),
        ModbusRegister(
            unique_id="temperature_top_set_dhw_tank1",
            name="Target Temperature",
            register_type="holding",
            address=12,
            entity_platform="controls",
            device="dhw_tank",
            native_min_value=35,
            native_max_value=65,
            native_step=0.5,
        ),
        ModbusRegister(
            unique_id="operating_mode_dhw_tank1",
            name="Operating Mode",
            register_type="holding",
            address=13,
            entity_platform="controls",
            device="dhw_tank",
        ),
    )


def test_water_heater_setup_and_properties():
    hass = DummyHass()
    entry = create_entry()
    current_reg, target_reg, mode_reg = _create_water_heater_registers()
    coordinator = DummyCoordinator(
        {
            current_reg.unique_id: 50.0,
            target_reg.unique_id: 55.0,
            mode_reg.unique_id: 2,
        },
        hass=hass,
    )
    client = DummyClient()

    hass.data = {
        DOMAIN: {
            entry.entry_id: {
                DATA_COORDINATOR: coordinator,
                DATA_REGISTERS: [current_reg, target_reg, mode_reg],
                DATA_CLIENT: client,
            }
        }
    }

    added = []

    def _add_entities(entities):
        added.extend(entities)

    import asyncio

    asyncio.run(setup_water_heaters(hass, entry, _add_entities))

    assert len(added) == 1
    entity: KebaWaterHeater = added[0]
    assert entity.unique_id == f"{entry.entry_id}_{mode_reg.unique_id}_water_heater"
    assert entity.current_temperature == 50.0
    assert entity.target_temperature == 55.0
    assert entity.current_operation == STATE_HEAT_PUMP
    assert entity.operation_list == [
        STATE_OFF, STATE_ECO, STATE_HEAT_PUMP, STATE_PERFORMANCE]

    # String mode values are normalized
    coordinator.data[mode_reg.unique_id] = "auto"
    assert entity.current_operation == STATE_ECO

    # Set target temperature writes to client and refreshes
    asyncio.run(entity.async_set_temperature(**{"temperature": 60}))
    assert client.writes[0] == (target_reg, 60.0)
    assert coordinator.refresh_called is True

    # Set operation mode writes mapped value
    coordinator.refresh_called = False
    asyncio.run(entity.async_set_operation_mode(STATE_PERFORMANCE))
    assert client.writes[1] == (mode_reg, 3)
    assert coordinator.refresh_called is True

    # Invalid mode raises
    with pytest.raises(ValueError):
        asyncio.run(entity.async_set_operation_mode("unsupported"))


def test_water_heater_setup_skips_when_missing_registers():
    hass = DummyHass()
    entry = create_entry()
    coordinator = DummyCoordinator(hass=hass)
    client = DummyClient()
    registers = [
        ModbusRegister(
            unique_id="temperature_top_dhw_tank1",
            name="Top Temperature",
            register_type="input",
            address=11,
            entity_platform="sensor",
            device="dhw_tank",
        )
    ]
    hass.data = {
        DOMAIN: {
            entry.entry_id: {
                DATA_COORDINATOR: coordinator,
                DATA_REGISTERS: registers,
                DATA_CLIENT: client,
            }
        }
    }

    added = []

    def _add_entities(entities):
        added.extend(entities)

    import asyncio

    asyncio.run(setup_water_heaters(hass, entry, _add_entities))

    assert added == []


def test_water_heater_handles_missing_temperature_key():
    hass = DummyHass()
    entry = create_entry()
    current_reg, target_reg, mode_reg = _create_water_heater_registers()
    coordinator = DummyCoordinator(
        {
            current_reg.unique_id: None,
            target_reg.unique_id: None,
            mode_reg.unique_id: "mystery",
        },
        hass=hass,
    )
    client = DummyClient()
    entity = KebaWaterHeater(
        coordinator=coordinator,
        entry=entry,
        current_temp_reg=current_reg,
        target_temp_reg=target_reg,
        mode_reg=mode_reg,
        client=client,
    )

    assert entity.current_temperature is None
    assert entity.target_temperature is None
    assert entity.current_operation is None

    import asyncio

    asyncio.run(entity.async_set_temperature())
    assert client.writes == []


def _create_climate_registers():
    return (
        ModbusRegister(
            unique_id="actual_room_temperature_circuit_1",
            name="Actual Room Temperature",
            register_type="input",
            address=1,
            entity_platform="sensor",
            device="circuit_1",
        ),
        ModbusRegister(
            unique_id="room_set_temperature_circuit_1",
            name="Room Set Temperature",
            register_type="holding",
            address=4,
            entity_platform="controls",
            device="circuit_1",
            native_min_value=5,
            native_max_value=30,
            native_step=0.5,
        ),
        ModbusRegister(
            unique_id="operating_mode_circuit_1",
            name="Operating Mode",
            register_type="holding",
            address=7,
            entity_platform="select",
            device="circuit_1",
            value_map={"0": "Standby", "2": "Day", "3": "Night"},
        ),
    )


def test_climate_setup_and_properties():
    hass = DummyHass()
    entry = create_entry()
    current_reg, target_reg, mode_reg = _create_climate_registers()
    coordinator = DummyCoordinator(
        {
            current_reg.unique_id: 20.0,
            target_reg.unique_id: 22.5,
            mode_reg.unique_id: 2,
        },
        hass=hass,
    )
    client = DummyClient()

    hass.data = {
        DOMAIN: {
            entry.entry_id: {
                DATA_COORDINATOR: coordinator,
                DATA_REGISTERS: [current_reg, target_reg, mode_reg],
                DATA_CLIENT: client,
            }
        }
    }

    added = []

    def _add_entities(entities):
        added.extend(entities)

    import asyncio

    asyncio.run(setup_climates(hass, entry, _add_entities))

    assert len(added) == 1
    entity: KebaHeatingCircuitClimate = added[0]
    assert entity.unique_id == f"{entry.entry_id}_circuit_1_climate"
    assert entity.current_temperature == 20.0
    assert entity.target_temperature == 22.5
    assert entity.hvac_mode == HVACMode.HEAT
    assert entity.preset_mode == "Day"
    assert entity.preset_modes == ["Standby", "Day", "Night"]

    coordinator.data[mode_reg.unique_id] = "standby"
    assert entity.hvac_mode == HVACMode.OFF
    assert entity.preset_mode == "Standby"

    asyncio.run(entity.async_set_temperature(**{"temperature": 23}))
    assert client.writes[0] == (target_reg, 23.0)
    assert coordinator.refresh_called is True

    coordinator.refresh_called = False
    asyncio.run(entity.async_set_preset_mode("Night"))
    assert client.writes[1] == (mode_reg, 3)
    assert coordinator.refresh_called is True

    coordinator.refresh_called = False
    asyncio.run(entity.async_set_hvac_mode(HVACMode.OFF))
    assert client.writes[2] == (mode_reg, 0)
    assert coordinator.refresh_called is True

    with pytest.raises(ValueError):
        asyncio.run(entity.async_set_preset_mode("Unknown"))


def test_climate_without_standby_raises_on_off_mode():
    hass = DummyHass()
    entry = create_entry()
    current_reg = ModbusRegister(
        unique_id="actual_room_temperature_circuit_2",
        name="Actual Room Temperature",
        register_type="input",
        address=11,
        entity_platform="sensor",
        device="circuit_2",
    )
    target_reg = ModbusRegister(
        unique_id="room_set_temperature_circuit_2",
        name="Room Set Temperature",
        register_type="holding",
        address=12,
        entity_platform="controls",
        device="circuit_2",
        native_min_value=5,
        native_max_value=30,
        native_step=0.5,
    )
    mode_reg = ModbusRegister(
        unique_id="operating_mode_circuit_2",
        name="Operating Mode",
        register_type="holding",
        address=13,
        entity_platform="select",
        device="circuit_2",
        value_map={"2": "Day"},
    )
    coordinator = DummyCoordinator(
        {current_reg.unique_id: 18.0, target_reg.unique_id: 21.0,
            mode_reg.unique_id: "day"},
        hass=hass,
    )
    client = DummyClient()
    entity = KebaHeatingCircuitClimate(
        coordinator=coordinator,
        entry=entry,
        current_temp_reg=current_reg,
        target_temp_reg=target_reg,
        mode_reg=mode_reg,
        client=client,
        device_key="circuit_2",
    )

    assert entity.hvac_mode == HVACMode.HEAT

    import asyncio

    with pytest.raises(ValueError):
        asyncio.run(entity.async_set_hvac_mode(HVACMode.OFF))
