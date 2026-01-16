import asyncio
from typing import Any

from keba_keenergy_api import KebaKeEnergyAPI
from keba_keenergy_api.constants import HeatCircuit


async def main() -> None:
    # ssl=True and skip_ssl_verification=True is only required for devices with basic auth
    client = KebaKeEnergyAPI(host="192.168.10.30",
                             ssl=False, skip_ssl_verification=True)

    # Get current outdoor temperature
    outdoor_temperature: float = await client.system.get_outdoor_temperature()
    print(f"Outdoor temperature: {outdoor_temperature} °C")

    # Get heat circuit temperature from heat circuit 1
    heat_circuit_temperature: float = await client.heat_circuit.get_target_temperature(position=1)
    print(f"Heat circuit 1 target temperature: {heat_circuit_temperature} °C")

    # Read multiple values
    data: dict[str, tuple[float | int | str]] = await client.read_data(
        request=[
            HeatCircuit.TARGET_TEMPERATURE,
            HeatCircuit.TARGET_TEMPERATURE_DAY,
        ],
    )
    for key, value in data.items():
        print(f"{key}: {value}")

    # Enable "day" mode for heat circuit 2
    # await client.heat_circuit.set_operating_mode(mode="day", position=2)

    # Write multiple values
    # await client.write_data(
    #     request={
    #         # Write heat circuit on position 1 and 3
    #         HeatCircuit.TARGET_TEMPERATURE_DAY: (20, None, 5),
    #         # Write night temperature on position 1
    #         HeatCircuit.TARGET_TEMPERATURE_NIGHT: (16,),
    #     },
    # )


asyncio.run(main())
