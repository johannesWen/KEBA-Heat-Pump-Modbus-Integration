import sys
import types
from datetime import timedelta


def _ensure_voluptuous_stub() -> None:
    try:
        import voluptuous  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    vol = types.ModuleType("voluptuous")

    class _Schema:
        def __init__(self, schema):
            self.schema = schema

        def __call__(self, value):
            return value

    def _identity(val):
        return val

    vol.Schema = _Schema
    vol.Required = lambda key, default=None: key
    vol.Optional = lambda key, default=None: key
    vol.All = lambda *funcs: _identity
    vol.Coerce = lambda typ: typ
    vol.Range = lambda min=None, max=None: _identity

    sys.modules["voluptuous"] = vol


def _create_homeassistant_stub() -> None:
    if "homeassistant" in sys.modules:
        return

    ha = types.ModuleType("homeassistant")

    components = types.ModuleType("homeassistant.components")
    class _BaseEntity:
        _attr_has_entity_name = False

        @property
        def name(self):  # pragma: no cover - convenience
            return getattr(self, "_attr_name", None)

        @property
        def unique_id(self):  # pragma: no cover - convenience
            return getattr(self, "_attr_unique_id", None)

    binary_sensor_mod = types.ModuleType("homeassistant.components.binary_sensor")
    class BinarySensorEntity(_BaseEntity):
        pass

    number_mod = types.ModuleType("homeassistant.components.number")
    class NumberEntity(_BaseEntity):
        pass

    select_mod = types.ModuleType("homeassistant.components.select")
    class SelectEntity(_BaseEntity):
        pass

    sensor_mod = types.ModuleType("homeassistant.components.sensor")
    class SensorEntity(_BaseEntity):
        pass

    water_heater_mod = types.ModuleType("homeassistant.components.water_heater")

    climate_mod = types.ModuleType("homeassistant.components.climate")

    class ClimateEntityFeature:
        TARGET_TEMPERATURE = 1
        PRESET_MODE = 2

    class HVACMode:
        OFF = "off"
        HEAT = "heat"

    class ClimateEntity(_BaseEntity):
        _attr_hvac_modes = []
        _attr_preset_modes = []

        @property
        def hvac_modes(self):
            return getattr(self, "_attr_hvac_modes", [])

        @property
        def preset_modes(self):
            return getattr(self, "_attr_preset_modes", [])

    class WaterHeaterEntityFeature:
        TARGET_TEMPERATURE = 1
        OPERATION_MODE = 2

    class WaterHeaterEntity(_BaseEntity):
        _attr_operation_list = []

        @property
        def operation_list(self):
            return getattr(self, "_attr_operation_list", [])

    STATE_OFF = "off"
    STATE_ECO = "eco"
    STATE_HEAT_PUMP = "heat_pump"
    STATE_PERFORMANCE = "performance"

    binary_sensor_mod.BinarySensorEntity = BinarySensorEntity
    number_mod.NumberEntity = NumberEntity
    select_mod.SelectEntity = SelectEntity
    sensor_mod.SensorEntity = SensorEntity
    water_heater_mod.WaterHeaterEntity = WaterHeaterEntity
    water_heater_mod.WaterHeaterEntityFeature = WaterHeaterEntityFeature
    water_heater_mod.STATE_OFF = STATE_OFF
    water_heater_mod.STATE_ECO = STATE_ECO
    water_heater_mod.STATE_HEAT_PUMP = STATE_HEAT_PUMP
    water_heater_mod.STATE_PERFORMANCE = STATE_PERFORMANCE
    climate_mod.ClimateEntity = ClimateEntity
    climate_mod.ClimateEntityFeature = ClimateEntityFeature
    climate_mod.HVACMode = HVACMode

    components.binary_sensor = binary_sensor_mod
    components.number = number_mod
    components.select = select_mod
    components.sensor = sensor_mod
    components.water_heater = water_heater_mod
    components.climate = climate_mod

    const = types.ModuleType("homeassistant.const")

    class Platform:
        SENSOR = "sensor"
        BINARY_SENSOR = "binary_sensor"
        NUMBER = "number"
        SELECT = "select"
        CLIMATE = "climate"

    class UnitOfTemperature:
        CELSIUS = "°C"

    ATTR_TEMPERATURE = "temperature"

    const.Platform = Platform
    const.UnitOfTemperature = UnitOfTemperature
    const.ATTR_TEMPERATURE = ATTR_TEMPERATURE

    core = types.ModuleType("homeassistant.core")

    class HomeAssistant:
        def __init__(self):
            self.data = {}
            self.config_entries = types.SimpleNamespace(async_forward_entry_setups=lambda *args, **kwargs: None)

        async def async_add_executor_job(self, func, *args, **kwargs):
            return func(*args, **kwargs)

    def callback(func):
        return func

    core.HomeAssistant = HomeAssistant
    core.callback = callback

    typing_mod = types.ModuleType("homeassistant.helpers.typing")
    typing_mod.ConfigType = dict

    config_entries = types.ModuleType("homeassistant.config_entries")

    class ConfigEntry:
        def __init__(self, data=None, options=None, entry_id="test"):
            self.data = data or {}
            self.options = options or {}
            self.entry_id = entry_id

    class ConfigFlow:
        VERSION = 1

        def __init_subclass__(cls, **kwargs):  # noqa: D401, ANN001
            return super().__init_subclass__()

        async def async_set_unique_id(self, unique_id: str):
            self._unique_id = unique_id

        def _abort_if_unique_id_configured(self):
            return None

        def async_create_entry(self, title: str, data: dict):
            return {"title": title, "data": data}

        def async_show_form(self, step_id: str, data_schema, errors: dict):
            return {"step_id": step_id, "data_schema": data_schema, "errors": errors}

    class OptionsFlow:
        def async_create_entry(self, title: str, data: dict):
            return {"title": title, "data": data}

        def async_show_form(self, step_id: str, data_schema, errors: dict):
            return {"step_id": step_id, "data_schema": data_schema, "errors": errors}

    config_entries.ConfigEntry = ConfigEntry
    config_entries.ConfigFlow = ConfigFlow
    config_entries.OptionsFlow = OptionsFlow

    helpers = types.ModuleType("homeassistant.helpers")

    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    def _add_entities_callback(entities):
        return entities

    entity_platform.AddEntitiesCallback = type("AddEntitiesCallback", (), {})
    helpers.entity_platform = entity_platform

    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")

    class UpdateFailed(Exception):
        pass

    class CoordinatorEntity:
        def __init__(self, coordinator=None):
            self.coordinator = coordinator
            self.hass = getattr(coordinator, "hass", None)

        __class_getitem__ = classmethod(lambda cls, item: cls)

    class DataUpdateCoordinator:
        __class_getitem__ = classmethod(lambda cls, item: cls)

        def __init__(self, hass, logger, name, update_interval: timedelta):
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval

        async def async_config_entry_first_refresh(self):
            await self._async_update_data()

        async def _async_update_data(self):
            raise NotImplementedError

    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.UpdateFailed = UpdateFailed
    update_coordinator.CoordinatorEntity = CoordinatorEntity

    helpers.update_coordinator = update_coordinator

    ha.const = const
    ha.components = components
    ha.core = core
    ha.helpers = helpers
    ha.config_entries = config_entries

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.components"] = components
    sys.modules["homeassistant.components.binary_sensor"] = binary_sensor_mod
    sys.modules["homeassistant.components.number"] = number_mod
    sys.modules["homeassistant.components.select"] = select_mod
    sys.modules["homeassistant.components.sensor"] = sensor_mod
    sys.modules["homeassistant.components.water_heater"] = water_heater_mod
    sys.modules["homeassistant.components.climate"] = climate_mod
    sys.modules["homeassistant.const"] = const
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.typing"] = typing_mod
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator
    sys.modules["homeassistant.helpers.entity_platform"] = entity_platform
    sys.modules["homeassistant.config_entries"] = config_entries


def _create_pymodbus_stub() -> None:
    if "pymodbus" in sys.modules:
        return

    pymodbus = types.ModuleType("pymodbus")
    client_mod = types.ModuleType("pymodbus.client")
    exceptions_mod = types.ModuleType("pymodbus.exceptions")

    class ModbusException(Exception):
        pass

    class ModbusTcpClient:
        def __init__(self, host: str, port: int = 502):
            self.host = host
            self.port = port
            self.connected = False

        def connect(self):
            self.connected = True
            return True

        def close(self):
            self.connected = False

        def read_holding_registers(self, address, count=None):
            raise NotImplementedError

        def read_input_registers(self, address, count=None):
            raise NotImplementedError

        def write_register(self, address, value):
            raise NotImplementedError

    client_mod.ModbusTcpClient = ModbusTcpClient
    exceptions_mod.ModbusException = ModbusException

    pymodbus.client = client_mod
    pymodbus.exceptions = exceptions_mod

    sys.modules["pymodbus"] = pymodbus
    sys.modules["pymodbus.client"] = client_mod
    sys.modules["pymodbus.exceptions"] = exceptions_mod


def pytest_sessionstart(session):
    _ensure_voluptuous_stub()
    _create_homeassistant_stub()
    _create_pymodbus_stub()
