from __future__ import annotations

import logging
from typing import Dict, List

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException
from pymodbus.payload import BinaryPayloadDecoder
from pymodbus.constants import Endian

from .models import ModbusRegister

_LOGGER = logging.getLogger(__name__)


class KebaModbusClient:
    """Thin wrapper around ModbusTcpClient."""

    def __init__(self, host: str, port: int, unit_id: int) -> None:
        self._host = host
        self._port = port
        self._unit_id = unit_id
        self._client: ModbusTcpClient | None = None

    def connect(self) -> None:
        if self._client is None:
            self._client = ModbusTcpClient(self._host, port=self._port)
        if not self._client.connect():
            raise ModbusException(f"Unable to connect to {self._host}:{self._port}")

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None

    def _ensure_client(self) -> ModbusTcpClient:
        if self._client is None:
            self.connect()
        assert self._client is not None
        return self._client

    def read_all(self, registers: List[ModbusRegister]) -> Dict[str, float | int | str | bool | None]:
        """Read all configured registers and return a dict of unique_id -> value."""
        client = self._ensure_client()
        result: Dict[str, float | int | str | bool | None] = {}

        for reg in registers:
            try:
                if reg.register_type == "holding":
                    resp = client.read_holding_registers(reg.address, reg.length, unit=self._unit_id)
                else:
                    resp = client.read_input_registers(reg.address, reg.length, unit=self._unit_id)

                if resp.isError():
                    _LOGGER.warning("Error reading register %s (%s): %s", reg.name, reg.address, resp)
                    value = None
                else:
                    registers_list = list(resp.registers)
                    value = self._decode_registers(registers_list, reg)
            except Exception as err:  # noqa: BLE001
                _LOGGER.exception("Exception reading register %s (%s): %s", reg.name, reg.address, err)
                value = None

            result[reg.unique_id] = value

        return result

    @staticmethod
    def _decode_registers(raw: list[int], reg: ModbusRegister) -> float | int | str | bool | None:
        """Decode according to data_type, then apply scale/offset and value_map."""
        if not raw:
            return None

        decoder = BinaryPayloadDecoder.fromRegisters(
            raw,
            byteorder=Endian.BIG,
            wordorder=Endian.BIG,
        )

        if reg.data_type == "int16":
            val = decoder.decode_16bit_int()
        elif reg.data_type == "uint16":
            val = decoder.decode_16bit_uint()
        elif reg.data_type == "int32":
            val = decoder.decode_32bit_int()
        elif reg.data_type == "uint32":
            val = decoder.decode_32bit_uint()
        elif reg.data_type == "float32":
            val = decoder.decode_32bit_float()
        else:
            # fallback: just take first register
            val = raw[0]

        # Apply scale and offset
        try:
            numeric = (float(val) * reg.scale) + reg.offset
        except Exception:  # noqa: BLE001
            numeric = val

        if reg.value_map is not None:
            # Value map keys are strings of the raw or scaled value
            key = str(int(val)) if isinstance(val, (int, float)) else str(val)
            mapped = reg.value_map.get(key)
            if mapped is not None:
                return mapped

        # Apply precision
        if isinstance(numeric, float) and reg.precision is not None:
            numeric = round(numeric, reg.precision)

        return numeric
