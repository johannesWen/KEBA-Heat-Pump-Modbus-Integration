"""
Helper script to convert Modbusdatapoints.xls to modbus_registers.json.

Usage:
    python convert_xls_to_json.py Modbusdatapoints.xls modbus_registers.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import xlrd  # pip install xlrd


def main(xls_path: str, json_path: str) -> None:
    book = xlrd.open_workbook(xls_path)
    sheet = book.sheet_by_index(0)

    # ---- ADAPT THIS SECTION TO YOUR COLUMN LAYOUT ----
    # This assumes the first row is a header row with column names like:
    # "Address", "Name", "Unit", "DataType", "Scale", "Device", ...
    header = [str(sheet.cell_value(0, col)).strip() for col in range(sheet.ncols)]

    def col_index(name: str) -> int:
        try:
            return header.index(name)
        except ValueError:
            raise SystemExit(f"Column '{name}' not found in header: {header}")

    col_addr = col_index("Address")
    col_name = col_index("Name")
    col_unit = col_index("Unit")
    col_dtype = col_index("DataType")      # e.g. INT16, UINT16, FLOAT32
    col_scale = col_index("Scale")        # factor / scaling
    col_device = col_index("Device")      # e.g. HeatPump, DHWTank, BufferTank, Circuit1, ...

    registers = []

    for row in range(1, sheet.nrows):
        addr = int(sheet.cell_value(row, col_addr))
        name = str(sheet.cell_value(row, col_name)).strip()
        unit = str(sheet.cell_value(row, col_unit)).strip() or None
        dtype_raw = str(sheet.cell_value(row, col_dtype)).strip().lower()
        scale_raw = sheet.cell_value(row, col_scale)
        device_raw = str(sheet.cell_value(row, col_device)).strip().lower()

        if not name:
            continue

        # Map Excel data type to our schema
        if "int16" in dtype_raw and "u" in dtype_raw:
            data_type = "uint16"
            length = 1
        elif "int16" in dtype_raw:
            data_type = "int16"
            length = 1
        elif "int32" in dtype_raw and "u" in dtype_raw:
            data_type = "uint32"
            length = 2
        elif "int32" in dtype_raw:
            data_type = "int32"
            length = 2
        elif "float32" in dtype_raw or "real32" in dtype_raw:
            data_type = "float32"
            length = 2
        else:
            # Fallback
            data_type = "uint16"
            length = 1

        # scale
        try:
            scale = float(scale_raw) if scale_raw not in ("", None) else 1.0
        except Exception:  # noqa: BLE001
            scale = 1.0

        # Device normalization
        device_map = {
            "heatpump": "heat_pump",
            "heat_pump": "heat_pump",
            "dhw": "dhw_tank",
            "dhw_tank": "dhw_tank",
            "buffertank": "buffer_tank",
            "buffer": "buffer_tank",
            "circuit1": "circuit_1",
            "circuit2": "circuit_2",
        }
        device_key = device_raw.replace(" ", "_")
        device = device_map.get(device_key, device_key)

        # Unique id can be based on name, sanitized
        unique_id = name.lower().replace(" ", "_").replace("/", "_").replace("-", "_")

        registers.append(
            {
                "unique_id": unique_id,
                "name": name,
                "register_type": "input",  # or "holding" if your sheet says so
                "address": addr,
                "length": length,
                "data_type": data_type,
                "unit_of_measurement": unit,
                "scale": scale,
                "offset": 0.0,
                "precision": 1,
                "device": device,
                "icon": None,
                "device_class": None,
                "state_class": "measurement",
                "entity_category": None,
                "enabled_default": True,
                "entity_platform": "sensor",
                "value_map": None,
            }
        )

    out = {"registers": registers}
    Path(json_path).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {len(registers)} registers to {json_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: convert_xls_to_json.py Modbusdatapoints.xls modbus_registers.json")
        raise SystemExit(1)
    main(sys.argv[1], sys.argv[2])
