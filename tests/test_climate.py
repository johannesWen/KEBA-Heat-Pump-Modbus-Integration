from custom_components.keba_heat_pump_modbus.climate import _collect_circuit_registers
from custom_components.keba_heat_pump_modbus.models import ModbusRegister


def test_collect_circuit_registers_ignores_reduced_setpoint():
    registers = [
        ModbusRegister(
            unique_id="actual_room_temperature_circuit_1",
            name="Actual Room Temperature",
            register_type="input",
            address=1,
            device="circuit_1",
        ),
        ModbusRegister(
            unique_id="room_set_temperature_reduced_circuit_1",
            name="Reduced Room Set Temperature",
            register_type="holding",
            address=2,
            device="circuit_1",
        ),
        ModbusRegister(
            unique_id="room_set_temperature_circuit_1",
            name="Room Set Temperature",
            register_type="holding",
            address=3,
            device="circuit_1",
        ),
        ModbusRegister(
            unique_id="operating_mode_circuit_1",
            name="Operating Mode",
            register_type="holding",
            address=4,
            device="circuit_1",
        ),
    ]

    circuits = _collect_circuit_registers(registers)

    assert "circuit_1" in circuits
    assert circuits["circuit_1"]["current_temp"].unique_id == "actual_room_temperature_circuit_1"
    assert circuits["circuit_1"]["target_temp"].unique_id == "room_set_temperature_circuit_1"
    assert circuits["circuit_1"]["mode"].unique_id == "operating_mode_circuit_1"
