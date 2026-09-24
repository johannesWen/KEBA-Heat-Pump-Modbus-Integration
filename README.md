<p align="center">
    <img src="https://github.com/johannesWen/KEBA-Heat-Pump-Modbus-Integration/blob/main/assets/logo.png" height="150" alt="KEBA-Heat-Pump-Modbus-Integration logo">
</p>

# KEBA Heat Pump Modbus Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](http://www.apache.org/licenses/LICENSE-2.0)
[![codecov](https://codecov.io/gh/johannesWen/KEBA-Heat-Pump-Modbus-Integration/graph/badge.svg?token=MU30OBSTG3)](https://codecov.io/gh/johannesWen/KEBA-Heat-Pump-Modbus-Integration)
[![CI](https://github.com/johannesWen/KEBA-Heat-Pump-Modbus-Integration/actions/workflows/ci.yml/badge.svg)](https://github.com/johannesWen/KEBA-Heat-Pump-Modbus-Integration/actions/workflows/ci.yml)

A custom Home Assistant integration that polls a KEBA heat pump controller over Modbus TCP and exposes operational data as Home Assistant entities. Use it to keep an eye on temperatures, operating states, and circuit health directly from your dashboard.

## What the integration does

- Connects to a KEBA heat pump via Modbus TCP using the host, port, and unit ID you configure.
  - Tested heat pump: [M-Tec](https://www.mtec-systems.com/) WPS412
- Polls defined Modbus registers on a configurable interval to keep data fresh.
- Supports some control entities to change operating modes, temperature, and settings directly from Home Assistant.
- Provides sensors, binary sensors, number and select entities for heat pump components (system, hot water tank, buffer tank, and up to four heating circuits) with manufacturer, model, and device grouping.
- Ships with an options flow so you can adjust the scan interval from the Home Assistant UI after setup.

## Requirements

- Home Assistant with [HACS](https://hacs.xyz/) installed.
- Network access from Home Assistant to the KEBA heat pump Modbus interface (default TCP port 502).
- Modbus unit ID for the controller (defaults to `1`).

## HACS Installation

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=johannesWen&repository=KEBA-Heat-Pump-Modbus-Integration&category=integration)

1. Search for **KEBA Heat Pump Modbus** in HACS and install it.
2. Restart Home Assistant after installation completes.
3. Go to **Settings → Devices & Services → Add Integration** and search for **KEBA Heat Pump Modbus**.
4. Enter the heat pump **Host IP**, optional **Port** (defaults to `502`), **Unit ID** (defaults to `1`), choose your **Scan interval** and select the number of heating circuits (1-4) your system has.
5. Finish setup. You can revisit the integration options later to change the scan interval without re-adding the device.

## Manual Installation (alternative)

1. Copy the `custom_components/keba_heat_pump_modbus` directory into your Home Assistant `custom_components` folder.
2. Restart Home Assistant.
3. Add the integration via **Settings → Devices & Services → Add Integration** and provide the connection details when prompted.

## Configuration options 

- **Host**: IP address or hostname of the KEBA heat pump controller.
- **Port**: Modbus TCP port (defaults to `502`).
- **Unit ID**: Modbus unit/slave ID (defaults to `1`).
- **Scan interval**: How often (in seconds) the integration polls registers; configurable during setup and via options.
- **heat_circuits_used**: Number of heating circuits your system has (1-4).

## Dashboard Card

This integration ships a bundled Lovelace card for quick access to the most common heat pump settings. The card source lives under [`frontend/`](frontend) and is built into `custom_components/keba_heat_pump_modbus/static/` at release time.

Once the integration is set up, the card is **auto-registered** with Home Assistant — no manual Lovelace `resources:` entry is required.

Add the card from the Lovelace UI (**Add Card** → search for **KEBA Heat Pump Modbus**) or configure it directly:

```yaml
type: custom:keba-heat-pump-modbus-card
title: KEBA Heat Pump
entity_prefix: keba_heat_pump_modbus
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `title` | string | `KEBA Heat Pump` | Card title shown in the dashboard. |
| `entity_prefix` | string | `keba_heat_pump_modbus` | Entity id prefix used to resolve integration entities. |

The card exposes:

- System operating mode
- Heat pump operating mode and status
- Hot water tank mode, top/reduced set temperatures, and excess-energy target temperature
- Heating circuit room/reduced set temperatures and operating modes (for each configured circuit)

> **After updating the integration** (via HACS or manually), **restart Home Assistant** before using new card features. The card is served fresh, but the loaded Python code only changes on restart.

## Development

### Build the bundled card

```bash
cd frontend
npm install
npm run build
```

The build writes `custom_components/keba_heat_pump_modbus/static/keba-heat-pump-modbus-card.js`.

For iterative development with rebuild-on-save:

```bash
npm run watch
```

### Local Home Assistant

A Docker Compose stack is provided for testing the integration together with the bundled card against a simulated Modbus TCP server.

```bash
cd frontend && npm install && npm run build && cd ..
docker compose up -d
```

Then open [http://localhost:8123](http://localhost:8123). Add the KEBA integration using the simulator host `modbus-simulator` and port `502` (the simulator is reachable at `localhost:5020` from the Docker host for debugging).

The simulator serves plausible default values for all registers so the integration and card can be exercised without real hardware.

## Troubleshooting

- Ensure the KEBA controller allows Modbus TCP connections from your Home Assistant host.
- Verify that the configured unit ID and port match the controller settings.
- Increase the scan interval if you experience timeouts or if the controller limits request frequency.

## Homeassistant Devices

| Heat Pump | Hot Water Tank | Heat Circuit |
|:---:|:---:|:---:|
| ![](assets/screenshots/heat_pump.png) | ![](assets/screenshots/hot_water_tank.png) | ![](assets/screenshots/heat_circuit.png) |
| | ![](assets/screenshots/water_heater_card.png) | ![](assets/screenshots/heat_circuit_card.png) |

| Buffer Tank | System |
|:---:|:---:|
| ![](assets/screenshots/buffer_tank.png) | ![](assets/screenshots/system.png) |
