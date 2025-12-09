from __future__ import annotations

import logging
import struct
from typing import Dict, List

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

from .models import ModbusRegister

_LOGGER = logging.getLogger(__name__)


class KebaModbusClient:
    """Thin wrapper around ModbusTcpClient."""

    def __init__(self, host: str, port: int, unit_id: int) -> None:
        self._host = host
        self._port = port
        self._unit_id = unit_id  # note: may not be used by your pymodbus version
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

    # ---------------------------------------------------------------------
    #  Helper that hides all the pymodbus version differences
    # ---------------------------------------------------------------------
    def _read_register_list(self, client: ModbusTcpClient, reg: ModbusRegister) -> list[int] | None:
        """
        Return a list of raw 16-bit register values for one ModbusRegister.

        Tries the "modern" signature (address, count) first.
        If that raises TypeError (like in your environment), falls back to
        calling with only address and, for multi-word values, multiple calls.
        """
        try:
            # First try: assume function(address, count) exists.
            if reg.register_type == "holding":
                resp = client.read_holding_registers(reg.address, reg.length)
            else:
                resp = client.read_input_registers(reg.address, reg.length)

            if hasattr(resp, "isError") and resp.isError():
                _LOGGER.warning(
                    "Error reading register %s (%s): %s",
                    reg.name,
                    reg.address,
                    resp,
                )
                return None

            return list(resp.registers)

        except TypeError:
            # Fallback for your style: read_holding_registers(address) only.
            # We simulate 'count' by doing multiple calls.
            if reg.length <= 1:
                if reg.register_type == "holding":
                    resp = client.read_holding_registers(reg.address)
                else:
                    resp = client.read_input_registers(reg.address)

                if hasattr(resp, "isError") and resp.isError():
                    _LOGGER.warning(
                        "Error reading register %s (%s): %s",
                        reg.name,
                        reg.address,
                        resp,
                    )
                    return None

                return list(resp.registers)

            # Multi-register fallback: call once per 16-bit word.
            all_regs: list[int] = []
            for offset in range(reg.length):
                addr = reg.address + offset
                if reg.register_type == "holding":
                    resp = client.read_holding_registers(addr)
                else:
                    resp = client.read_input_registers(addr)

                if hasattr(resp, "isError") and resp.isError():
                    _LOGGER.warning(
                        "Error reading register %s (%s + %s): %s",
                        reg.name,
                        reg.address,
                        offset,
                        resp,
                    )
                    return None

                all_regs.extend(list(resp.registers))

            return all_regs

    # ---------------------------------------------------------------------
    #  Main public method used by the coordinator
    # ---------------------------------------------------------------------
    def read_all(self, registers: List[ModbusRegister]) -> Dict[str, float | int | str | bool | None]:
        """Read all configured registers and return a dict of unique_id -> value."""
        client = self._ensure_client()
        result: Dict[str, float | int | str | bool | None] = {}

        for reg in registers:
            try:
                raw_list = self._read_register_list(client, reg)
                if raw_list is None:
                    value = None
                else:
                    value = self._decode_registers(raw_list, reg)
            except Exception as err:  # noqa: BLE001
                _LOGGER.exception(
                    "Exception reading register %s (%s): %s",
                    reg.name,
                    reg.address,
                    err,
                )
                value = None

            result[reg.unique_id] = value

        return result

    # ---------------------------------------------------------------------
    #  Decoding
    # ---------------------------------------------------------------------
    @staticmethod
    def _decode_registers(raw: list[int], reg: ModbusRegister) -> float | int | str | bool | None:
        """Decode according to data_type, then apply scale/offset and value_map."""
        if not raw:
            return None

        def to_int16(v: int) -> int:
            return v - 0x10000 if v & 0x8000 else v

        # Basic decoding
        if reg.data_type == "int16":
            val = to_int16(raw[0])
        elif reg.data_type == "uint16":
            val = int(raw[0])
        elif reg.data_type in ("int32", "uint32", "float32"):
            if len(raw) < 2:
                base = raw[0]
                val = to_int16(base) if reg.data_type == "int32" else int(base)
            else:
                hi, lo = raw[0], raw[1]
                combined = (hi << 16) | lo

                if reg.data_type == "int32":
                    val = struct.unpack(">i", combined.to_bytes(4, "big", signed=False))[0]
                elif reg.data_type == "uint32":
                    val = combined
                else:  # float32
                    val = struct.unpack(">f", combined.to_bytes(4, "big", signed=False))[0]
        else:
            # Unknown type: just return the first raw register
            val = raw[0]

        # Scale and offset
        numeric = val
        if isinstance(val, (int, float)):
            try:
                numeric = (float(val) * reg.scale) + reg.offset
            except Exception:  # noqa: BLE001
                numeric = val

        # Map enum values if provided
        if reg.value_map is not None:
            key = str(int(val)) if isinstance(val, (int, float)) else str(val)
            mapped = reg.value_map.get(key)
            if mapped is not None:
                return mapped

        # Precision on floats
        if isinstance(numeric, float) and reg.precision is not None:
            numeric = round(numeric, reg.precision)

        return numeric
