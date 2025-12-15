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

    const = types.ModuleType("homeassistant.const")

    class Platform:
        SENSOR = "sensor"
        BINARY_SENSOR = "binary_sensor"
        NUMBER = "number"
        SELECT = "select"

    const.Platform = Platform

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

    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")

    class UpdateFailed(Exception):
        pass

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

    helpers.update_coordinator = update_coordinator

    ha.const = const
    ha.core = core
    ha.helpers = helpers
    ha.config_entries = config_entries

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.const"] = const
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.typing"] = typing_mod
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator
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
