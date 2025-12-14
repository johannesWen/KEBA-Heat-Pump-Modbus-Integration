from homeassistant.const import Platform


DOMAIN = "keba_heat_pump_modbus"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_UNIT_ID = "unit_id"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_CIRCUITS = "circuits_installed"

DEFAULT_PORT = 502
DEFAULT_UNIT_ID = 1
DEFAULT_SCAN_INTERVAL = 30  # seconds
DEFAULT_CIRCUITS = 1

DATA_COORDINATOR = "coordinator"
DATA_REGISTERS = "registers"
DATA_CLIENT = "client"

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
]

DEVICE_NAME_MAP = {
    "system": "System",
    "heat_pump": "Heat Pump",
    "dhw_tank": "Hot Water Tank",
    "buffer_tank1": "Buffer Tank",
    "circuit_1": "Heating Circuit 1",
    "circuit_2": "Heating Circuit 2",
    "circuit_3": "Heating Circuit 3",
    "circuit_4": "Heating Circuit 4",
}
