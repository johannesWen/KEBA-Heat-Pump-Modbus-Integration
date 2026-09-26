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
    vol.Length = lambda max=None, min=None: _identity

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

        async def async_added_to_hass(self):
            pass

        async def async_will_remove_from_hass(self):
            pass

        async def async_remove(self):
            pass

        def async_write_ha_state(self):
            pass

    binary_sensor_mod = types.ModuleType(
        "homeassistant.components.binary_sensor")

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

    persistent_notification_mod = types.ModuleType(
        "homeassistant.components.persistent_notification"
    )

    def async_create(hass, message, title=None, notification_id=None):  # noqa: ANN001
        # Tests only need this to exist; no-op.
        return None

    http_mod = types.ModuleType("homeassistant.components.http")

    class StaticPathConfig:
        def __init__(self, url_path, path, cache_headers=True):
            self.url_path = url_path
            self.path = path
            self.cache_headers = cache_headers

    http_mod.StaticPathConfig = StaticPathConfig

    frontend_mod = types.ModuleType("homeassistant.components.frontend")

    def add_extra_js_url(_hass, _url):  # noqa: ANN001
        pass

    frontend_mod.add_extra_js_url = add_extra_js_url

    water_heater_mod = types.ModuleType(
        "homeassistant.components.water_heater")

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
    components.persistent_notification = persistent_notification_mod
    components.http = http_mod
    components.frontend = frontend_mod
    components.water_heater = water_heater_mod
    components.climate = climate_mod

    persistent_notification_mod.async_create = async_create

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
    ATTR_ENTITY_ID = "entity_id"
    STATE_UNAVAILABLE = "unavailable"
    STATE_UNKNOWN = "unknown"

    const.Platform = Platform
    const.UnitOfTemperature = UnitOfTemperature
    const.ATTR_TEMPERATURE = ATTR_TEMPERATURE
    const.ATTR_ENTITY_ID = ATTR_ENTITY_ID
    const.STATE_UNAVAILABLE = STATE_UNAVAILABLE
    const.STATE_UNKNOWN = STATE_UNKNOWN

    core = types.ModuleType("homeassistant.core")

    class HomeAssistant:
        def __init__(self):
            self.data = {}
            self.states = types.SimpleNamespace(get=lambda *_a, **_kw: None)
            self.config_entries = types.SimpleNamespace(
                async_forward_entry_setups=lambda *args, **kwargs: None)
            self.services = types.SimpleNamespace(
                has_service=lambda *args, **kwargs: False,
                async_register=lambda *args, **kwargs: None,
            )

        async def async_add_executor_job(self, func, *args, **kwargs):
            return func(*args, **kwargs)

        async def async_create_task(self, coro):
            await coro

        async def async_call(self, *args, **kwargs):
            return None

    def callback(func):
        return func

    class ServiceCall:
        def __init__(self, domain=None, service=None, data=None):
            self.domain = domain
            self.service = service
            self.data = data or {}

    class State:
        def __init__(self, entity_id=None, state=None, attributes=None):
            self.entity_id = entity_id
            self.state = state
            self.attributes = attributes or {}

    class Event:
        def __init__(self, event_type=None, data=None):
            self.event_type = event_type
            self.data = data or {}

    core.HomeAssistant = HomeAssistant
    core.callback = callback
    core.ServiceCall = ServiceCall
    core.State = State
    core.Event = Event

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

    update_coordinator = types.ModuleType(
        "homeassistant.helpers.update_coordinator")

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

    entity_mod = types.ModuleType("homeassistant.helpers.entity")

    class Entity:
        _attr_has_entity_name = False
        _attr_extra_state_attributes = None
        _attr_unique_id = None
        _attr_name = None
        entity_id = None

        @property
        def name(self):
            return getattr(self, "_attr_name", None)

        @property
        def unique_id(self):
            return getattr(self, "_attr_unique_id", None)

        @property
        def extra_state_attributes(self):
            return getattr(self, "_attr_extra_state_attributes", None)

        def async_write_ha_state(self):
            pass

        async def async_added_to_hass(self):
            pass

        async def async_will_remove_from_hass(self):
            pass

        async def async_remove(self):
            pass

    entity_mod.Entity = Entity
    helpers.entity = entity_mod

    config_validation_mod = types.ModuleType(
        "homeassistant.helpers.config_validation")

    def _entity_id(value):
        return str(value)

    config_validation_mod.entity_id = _entity_id
    config_validation_mod.boolean = bool
    config_validation_mod.string = str
    helpers.config_validation = config_validation_mod

    entity_registry_mod = types.ModuleType(
        "homeassistant.helpers.entity_registry")

    class EntityRegistry:
        def __init__(self):
            self._entries = {}

        def async_get_entity_id(self, platform, domain, unique_id):
            return self._entries.get((platform, domain, unique_id))

        def async_get(self, hass):
            return self

    entity_registry_mod.async_get = lambda hass: entity_registry_mod.Registry()
    entity_registry_mod.Registry = EntityRegistry
    helpers.entity_registry = entity_registry_mod

    event_mod = types.ModuleType("homeassistant.helpers.event")

    def async_track_time_interval(hass, action, interval):
        return lambda: None

    event_mod.async_track_time_interval = async_track_time_interval
    helpers.event = event_mod

    storage_mod = types.ModuleType("homeassistant.helpers.storage")

    class Store:
        def __init__(self, hass, version, key):
            self.hass = hass
            self.version = version
            self.key = key
            self._data = None

        async def async_load(self):
            return self._data

        async def async_save(self, data):
            self._data = data

    storage_mod.Store = Store
    helpers.storage = storage_mod

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
    sys.modules["homeassistant.components.persistent_notification"] = persistent_notification_mod
    sys.modules["homeassistant.components.http"] = http_mod
    sys.modules["homeassistant.components.frontend"] = frontend_mod
    sys.modules["homeassistant.components.water_heater"] = water_heater_mod
    sys.modules["homeassistant.components.climate"] = climate_mod
    sys.modules["homeassistant.const"] = const
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.typing"] = typing_mod
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator
    sys.modules["homeassistant.helpers.entity_platform"] = entity_platform
    sys.modules["homeassistant.helpers.entity"] = entity_mod
    sys.modules["homeassistant.helpers.config_validation"] = config_validation_mod
    sys.modules["homeassistant.helpers.entity_registry"] = entity_registry_mod
    sys.modules["homeassistant.helpers.event"] = event_mod
    sys.modules["homeassistant.helpers.storage"] = storage_mod
    sys.modules["homeassistant.config_entries"] = config_entries

    exceptions = types.ModuleType("homeassistant.exceptions")

    class ServiceValidationError(Exception):
        pass

    exceptions.ServiceValidationError = ServiceValidationError
    sys.modules["homeassistant.exceptions"] = exceptions

    util_mod = types.ModuleType("homeassistant.util")
    dt_mod = types.ModuleType("homeassistant.util.dt")

    def now(time_zone=None):
        from datetime import datetime
        return datetime.now(time_zone)

    dt_mod.now = now
    util_mod.dt = dt_mod
    ha.util = util_mod
    sys.modules["homeassistant.util"] = util_mod
    sys.modules["homeassistant.util.dt"] = dt_mod


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

    # Make debounced writes synchronous for unit tests.
    try:
        from custom_components.keba_heat_pump_modbus import const as integration_const

        integration_const.WRITE_DEBOUNCE_SECONDS = 0
    except Exception:  # noqa: BLE001
        # If the integration cannot be imported yet for some reason, tests will surface it.
        pass
