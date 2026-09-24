"""Simple Modbus TCP simulator for local KEBA heat pump development.

Serves holding registers with plausible static values so the KEBA Heat Pump
Modbus integration can be configured and its bundled Lovelace card tested
without real hardware.
"""

from __future__ import annotations

import logging
import os

from pymodbus.datastore import (
    ModbusDeviceContext,
    ModbusSequentialDataBlock,
    ModbusServerContext,
)
from pymodbus.server import StartTcpServer

_LOGGER = logging.getLogger(__name__)

# Default values for the holding registers used by the integration.
# Addresses are taken from the JSON register definitions.
DEFAULT_HOLDING_REGISTERS: dict[int, int] = {
    # System
    1500: 4,  # operating mode -> Full Auto
    1502: 150,  # exterior temperature -> 15.0 C (scaled *10)
    # Circuit 1
    1: 210,  # actual room temperature -> 21.0 C
    2: 210,  # current set room temperature -> 21.0 C
    4: 210,  # room set temperature -> 21.0 C
    5: 180,  # room set temperature reduced -> 18.0 C
    6: 0,  # room offset temperature -> 0.0 C
    7: 2,  # operating mode circuit 1 -> Day
    8: 1,  # heat request -> On
    10: 450,  # room humidity -> 45.0 %
    11: 0,  # cool request set external -> Off
    12: 0,  # heat request set external -> Off
    15: 350,  # circuit flow temperature -> 35.0 C
    16: 320,  # circuit reflux temperature -> 32.0 C
    17: 35,  # mixer position -> 35 %
    18: 1,  # circuit pump -> On
    # Circuit 2
    101: 205,
    102: 205,
    104: 205,
    105: 170,
    106: 0,
    107: 2,
    108: 1,
    110: 480,
    111: 0,
    112: 0,
    115: 340,
    116: 310,
    117: 40,
    118: 1,
    # Circuit 3
    201: 200,
    202: 200,
    204: 200,
    205: 160,
    206: 0,
    207: 2,
    208: 1,
    210: 500,
    211: 0,
    212: 0,
    215: 330,
    216: 300,
    217: 45,
    218: 1,
    # Circuit 4
    301: 195,
    302: 195,
    304: 195,
    305: 150,
    306: 0,
    307: 2,
    308: 1,
    310: 520,
    311: 0,
    312: 0,
    315: 320,
    316: 290,
    317: 50,
    318: 1,
    # DHW tank
    401: 480,  # top temperature -> 48.0 C
    402: 500,  # top set temperature -> 50.0 C
    403: 1,  # operating mode -> Auto
    404: 650,  # excess energy target temp -> 65.0 C
    405: 1,  # heat request -> On
    407: 450,  # reduced set temp -> 45.0 C
    # Heat pump
    700: 12345,  # operating hours
    701: 8765,  # total heating energy
    702: 4321,  # total electrical energy
    703: 2,  # heat pump state -> Auto
    705: 420,  # flow temperature -> 42.0 C
    706: 2500,  # heat power consumption -> 2500 W
    707: 800,  # electrical power consumption -> 800 W
    708: 120,  # source in temperature -> 12.0 C
    709: 90,  # source out temperature -> 9.0 C
    710: 380,  # reflux temperature -> 38.0 C
    711: 75,  # source circulation pump -> 75 %
    712: 80,  # heat circulation pump -> 80 %
    713: 1,  # operating mode -> On
    718: 45,  # compressor -> 45 %
    719: 400,  # set temperature -> 40.0 C
    # Buffer tank
    501: 420,
    502: 450,
    503: 400,
}


def _build_data_block() -> ModbusSequentialDataBlock:
    """Build a holding-register data block from the default values.

    The pymodbus server maps protocol address N to data block address N+1
    for holding registers, so the block starts at address 1.
    """
    max_address = max(DEFAULT_HOLDING_REGISTERS.keys())
    values = [0] * (max_address + 2)
    for address, value in DEFAULT_HOLDING_REGISTERS.items():
        values[address] = value
    return ModbusSequentialDataBlock(1, values)


def main() -> None:
    """Run the Modbus TCP simulator."""
    logging.basicConfig(level=logging.INFO)

    host = os.environ.get("MODBUS_HOST", "0.0.0.0")
    port = int(os.environ.get("MODBUS_PORT", "502"))

    data_block = _build_data_block()
    store = ModbusDeviceContext(hr=data_block)
    context = ModbusServerContext(devices=store, single=True)

    _LOGGER.info("Starting KEBA Modbus TCP simulator on %s:%s", host, port)
    StartTcpServer(context=context, address=(host, port))


if __name__ == "__main__":
    main()
