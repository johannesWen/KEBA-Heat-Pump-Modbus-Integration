import pytest

from pymodbus.exceptions import ModbusException

from custom_components.keba_heat_pump_modbus.modbus_client import KebaModbusClient
from custom_components.keba_heat_pump_modbus.models import ModbusRegister


class DummyResponse:
    def __init__(self, registers, error=False):
        self.registers = registers
        self._error = error

    def isError(self):
        return self._error


class LegacyClient:
    """Client without count parameter support to exercise fallback path."""

    def __init__(self):
        self.read_calls = []

    def read_holding_registers(self, address, count=None):
        if count is not None:
            raise TypeError("count not supported")
        self.read_calls.append(address)
        return DummyResponse([address])

    def read_input_registers(self, address, count=None):
        if count is not None:
            raise TypeError("count not supported")
        self.read_calls.append(address)
        return DummyResponse([address])


class RecordingClient:
    def __init__(self, responses):
        self.responses = responses
        self.writes = []

    def _take_response(self, key, address, count=None):
        resp = self.responses.get((key, address, count))
        if resp is None:
            return DummyResponse([address])
        return resp

    def read_holding_registers(self, address, count=None):
        return self._take_response("holding", address, count)

    def read_input_registers(self, address, count=None):
        return self._take_response("input", address, count)

    def write_register(self, address, value):
        self.writes.append((address, value))
        return DummyResponse([value])


@pytest.fixture
def sample_registers():
    return [
        ModbusRegister(
            unique_id="uint16_reg",
            name="Unsigned",
            register_type="holding",
            address=0,
            data_type="uint16",
            scale=0.5,
            offset=1,
            precision=1,
        ),
        ModbusRegister(
            unique_id="mapped_reg",
            name="Mapped",
            register_type="input",
            address=2,
            data_type="uint16",
            value_map={"1": "On", "0": "Off"},
        ),
        ModbusRegister(
            unique_id="float_reg",
            name="Float",
            register_type="input",
            address=4,
            length=2,
            data_type="float32",
            precision=2,
        ),
    ]


def test_read_all_decodes_values(monkeypatch, sample_registers):
    responses = {
        ("holding", 0, 1): DummyResponse([10]),
        ("input", 2, 1): DummyResponse([1]),
        ("input", 4, 2): DummyResponse([0x4120, 0x0000]),  # 10.0 float32
    }
    client = KebaModbusClient("localhost", 502, 1)
    recording_client = RecordingClient(responses)
    monkeypatch.setattr(client, "_ensure_client", lambda: recording_client)

    result = client.read_all(sample_registers)

    assert result["uint16_reg"] == 6.0  # (10 * 0.5) + 1
    assert result["mapped_reg"] == "On"
    assert result["float_reg"] == pytest.approx(10.0, rel=1e-3)


def test_read_all_handles_error_response(monkeypatch, sample_registers):
    error_reg = sample_registers[0]
    responses = {
        ("holding", error_reg.address, error_reg.length): DummyResponse([], error=True)
    }
    client = KebaModbusClient("localhost", 502, 1)
    recording_client = RecordingClient(responses)
    monkeypatch.setattr(client, "_ensure_client", lambda: recording_client)

    result = client.read_all([error_reg])

    assert result == {error_reg.unique_id: None}


def test_read_all_recovers_from_exceptions(monkeypatch, sample_registers):
    client = KebaModbusClient("localhost", 502, 1)

    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(client, "_ensure_client", lambda: object())
    monkeypatch.setattr(client, "_read_register_list", boom)

    result = client.read_all([sample_registers[0]])

    assert result[sample_registers[0].unique_id] is None


def test_read_register_list_falls_back_without_count():
    reg = ModbusRegister(
        unique_id="legacy",
        name="Legacy",
        register_type="holding",
        address=10,
        length=2,
        data_type="uint16",
    )
    client = KebaModbusClient("localhost", 502, 1)
    legacy_client = LegacyClient()

    result = client._read_register_list(legacy_client, reg)

    assert result == [10, 11]
    assert legacy_client.read_calls == [10, 11]


def test_read_register_list_handles_error_response():
    reg = ModbusRegister(
        unique_id="err",
        name="Error",
        register_type="holding",
        address=5,
        data_type="uint16",
    )
    client = KebaModbusClient("localhost", 502, 1)
    responses = {("holding", 5, 1): DummyResponse([], error=True)}
    reader = RecordingClient(responses)

    result = client._read_register_list(reader, reg)

    assert result is None


def test_write_register_scales_and_validates(monkeypatch):
    reg = ModbusRegister(
        unique_id="target",
        name="Writable",
        register_type="holding",
        address=7,
        data_type="int16",
        scale=2,
        offset=0,
    )
    client = KebaModbusClient("localhost", 502, 1)
    recorder = RecordingClient({})
    monkeypatch.setattr(client, "_ensure_client", lambda: recorder)

    client.write_register(reg, 4)

    assert recorder.writes == [(7, 2)]


def test_write_register_supports_boolean(monkeypatch):
    reg = ModbusRegister(
        unique_id="bool",
        name="Boolean",
        register_type="holding",
        address=8,
        data_type="uint16",
    )
    client = KebaModbusClient("localhost", 502, 1)
    recorder = RecordingClient({})
    monkeypatch.setattr(client, "_ensure_client", lambda: recorder)

    client.write_register(reg, True)

    assert recorder.writes == [(8, 1)]


def test_write_register_raises_on_error_response(monkeypatch):
    reg = ModbusRegister(
        unique_id="err_write",
        name="Err",
        register_type="holding",
        address=9,
        data_type="uint16",
    )
    client = KebaModbusClient("localhost", 502, 1)
    error_response = DummyResponse([], error=True)
    recorder = RecordingClient({})
    recorder.write_register = lambda address, value: error_response
    monkeypatch.setattr(client, "_ensure_client", lambda: recorder)

    with pytest.raises(ModbusException):
        client.write_register(reg, 1)


@pytest.mark.parametrize(
    "data_type,raw,expected",
    [
        ("int16", [0xFF9C], -100),
        ("uint32", [0x0001, 0x0002], 0x00010002),
        ("float32", [0x447A, 0x0000], pytest.approx(1000.0, rel=1e-3)),
    ],
)
def test_decode_registers_various_types(data_type, raw, expected):
    reg = ModbusRegister(
        unique_id="decoder",
        name="Decoder",
        register_type="input",
        address=0,
        length=len(raw),
        data_type=data_type,
    )

    value = KebaModbusClient._decode_registers(raw, reg)

    assert value == expected


def test_decode_registers_handles_empty_and_bool():
    reg_bool = ModbusRegister(
        unique_id="bool_decoder",
        name="Bool",
        register_type="input",
        address=0,
        data_type="boolean",
    )
    reg_unknown = ModbusRegister(
        unique_id="unknown",
        name="Unknown",
        register_type="input",
        address=0,
        data_type="mystery",
    )

    assert KebaModbusClient._decode_registers([], reg_bool) is None
    assert KebaModbusClient._decode_registers([1], reg_bool) == 1.0
    assert KebaModbusClient._decode_registers([123], reg_unknown) == 123


def test_decode_registers_scale_failure_returns_raw_value():
    reg = ModbusRegister(
        unique_id="bad_scale",
        name="Bad Scale",
        register_type="input",
        address=0,
        data_type="uint16",
        scale="not-a-number",  # type: ignore[arg-type]
    )

    assert KebaModbusClient._decode_registers([5], reg) == 5


def test_write_register_rejects_invalid_requests(monkeypatch):
    holding_reg = ModbusRegister(
        unique_id="bad",
        name="Bad",
        register_type="holding",
        address=0,
        length=2,
        data_type="uint16",
    )
    client = KebaModbusClient("localhost", 502, 1)
    monkeypatch.setattr(client, "_ensure_client", lambda: RecordingClient({}))

    with pytest.raises(ModbusException):
        client.write_register(holding_reg, 1)

    input_reg = ModbusRegister(
        unique_id="input",
        name="Input",
        register_type="input",
        address=0,
        data_type="uint16",
    )
    with pytest.raises(ModbusException):
        client.write_register(input_reg, 1)


def test_connect_raises_when_modbus_connect_fails(monkeypatch):
    class FailingClient:
        def __init__(self, host, port):
            self.host = host
            self.port = port

        def connect(self):
            return False

    monkeypatch.setattr(
        "custom_components.keba_heat_pump_modbus.modbus_client.ModbusTcpClient",
        FailingClient,
    )
    client = KebaModbusClient("localhost", 502, 1)

    with pytest.raises(ModbusException):
        client.connect()


def test_write_register_out_of_range(monkeypatch):
    reg_int16 = ModbusRegister(
        unique_id="int16",
        name="Int16",
        register_type="holding",
        address=1,
        data_type="int16",
    )
    reg_uint16 = ModbusRegister(
        unique_id="uint16",
        name="UInt16",
        register_type="holding",
        address=2,
        data_type="uint16",
    )
    client = KebaModbusClient("localhost", 502, 1)
    monkeypatch.setattr(client, "_ensure_client", lambda: RecordingClient({}))

    with pytest.raises(ModbusException):
        client.write_register(reg_int16, 40000)

    with pytest.raises(ModbusException):
        client.write_register(reg_uint16, -1)


def test_write_register_scale_error(monkeypatch):
    reg = ModbusRegister(
        unique_id="scale",
        name="Scale",
        register_type="holding",
        address=3,
        data_type="uint16",
        scale=0,
    )
    client = KebaModbusClient("localhost", 502, 1)
    monkeypatch.setattr(client, "_ensure_client", lambda: RecordingClient({}))

    with pytest.raises(ZeroDivisionError):
        client.write_register(reg, 10)
