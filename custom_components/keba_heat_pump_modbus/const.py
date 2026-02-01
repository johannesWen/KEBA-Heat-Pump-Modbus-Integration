from homeassistant.const import Platform


DOMAIN = "keba_heat_pump_modbus"

try:
    WATER_HEATER_PLATFORM = Platform.WATER_HEATER
except AttributeError:
    WATER_HEATER_PLATFORM = "water_heater"

try:
    CLIMATE_PLATFORM = Platform.CLIMATE
except AttributeError:
    CLIMATE_PLATFORM = "climate"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_UNIT_ID = "unit_id"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_CIRCUITS = "heat_circuits_used"

DEFAULT_PORT = 502
DEFAULT_UNIT_ID = 1
DEFAULT_SCAN_INTERVAL = 30  # seconds
DEFAULT_CIRCUITS = 1
WRITE_DEBOUNCE_SECONDS = 0.5
WRITE_WARNING_THRESHOLD = 30
WRITE_WARNING_WINDOW_SECONDS = 7 * 24 * 60 * 60

DATA_COORDINATOR = "coordinator"
DATA_REGISTERS = "registers"
DATA_CLIENT = "client"

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    CLIMATE_PLATFORM,
    WATER_HEATER_PLATFORM,
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
