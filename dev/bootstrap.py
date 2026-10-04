"""Initialize the local HA instance through its APIs, without editing .storage."""

import argparse
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DOMAIN = "keba_heat_pump_modbus"
CLIENT_ID = "http://localhost:8123/"
SIMULATOR_CONFIG = {
    "host": "modbus-simulator",
    "port": 502,
    "unit_id": 1,
    "scan_interval": 30,
    "heat_circuits_used": 4,
}


def bootstrap(url: str, username: str, password: str, timeout: float = 300) -> None:
    """Complete onboarding and ensure a single, connected simulator entry."""
    token = None
    deadline = time.monotonic() + timeout

    def api(path, data=None, *, form=False):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = None
        if data is not None:
            headers["Content-Type"] = (
                "application/x-www-form-urlencoded" if form else "application/json"
            )
            body = (urlencode(data) if form else json.dumps(data)).encode()
        request = Request(url.rstrip("/") + path, data=body, headers=headers)
        with urlopen(request, timeout=30) as response:
            body = response.read()
            return json.loads(body) if body else None

    def wait_for(description, check):
        print(f"Waiting for {description}...", flush=True)
        last_error = None
        while time.monotonic() < deadline:
            try:
                if result := check():
                    return result
            except HTTPError as err:
                if err.code not in (404, 502, 503):
                    raise
                last_error = err
            except (URLError, TimeoutError, ConnectionError) as err:
                last_error = err
            time.sleep(2)
        raise TimeoutError(f"Timed out waiting for {description}: {last_error}")

    def onboarding_status():
        try:
            return api("/api/onboarding")
        except HTTPError as err:
            # HA removes the onboarding endpoints after an onboarded restart.
            if err.code == 404:
                return []
            raise

    # The tuple also succeeds when the completed status is an empty list.
    steps = wait_for("Home Assistant", lambda: (onboarding_status(),))[0]
    pending = {step["step"] for step in steps if not step["done"]}
    if "user" in pending:
        print("Creating development user...", flush=True)
        code = api("/api/onboarding/users", {
            "name": "KEBA Developer",
            "username": username,
            "password": password,
            "client_id": CLIENT_ID,
            "language": "en",
        })["auth_code"]
    else:
        flow = api("/auth/login_flow", {
            "client_id": CLIENT_ID,
            "redirect_uri": CLIENT_ID,
            "handler": ["homeassistant", None],
        })
        result = api(f"/auth/login_flow/{flow['flow_id']}", {
            "client_id": CLIENT_ID, "username": username, "password": password,
        })
        if result["type"] != "create_entry":
            raise RuntimeError(
                "Development login failed. Set HA_DEV_USERNAME and HA_DEV_PASSWORD "
                "to the credentials used when this HA volume was initialized."
            )
        code = result["result"]

    tokens = api("/auth/token", {
        "grant_type": "authorization_code", "code": code, "client_id": CLIENT_ID,
    }, form=True)
    token = tokens["access_token"]
    try:
        for step in ("core_config", "analytics", "integration"):
            if step in pending:
                data = {"client_id": CLIENT_ID, "redirect_uri": CLIENT_ID}
                api(f"/api/onboarding/{step}", data if step == "integration" else {})

        wait_for("HA startup", lambda: api("/api/config")["state"] == "RUNNING")
        entries_path = f"/api/config/config_entries/entry?domain={DOMAIN}"
        entries = api(entries_path)
        title = "KEBA Heat Pump (modbus-simulator)"
        entry = next((entry for entry in entries if entry["title"] == title), None)
        if entry is None:
            print("Adding the simulated heat pump (four heating circuits)...", flush=True)
            flow = api("/api/config/config_entries/flow", {"handler": DOMAIN})
            result = api(f"/api/config/config_entries/flow/{flow['flow_id']}", SIMULATOR_CONFIG)
            if result["type"] != "create_entry":
                raise RuntimeError(f"KEBA config flow did not create an entry: {result}")
            entry = result["result"]
        else:
            # HA may have started before the postStart hook built missing cards.
            api(f"/api/config/config_entries/entry/{entry['entry_id']}/reload", {})

        entry_id = entry["entry_id"]
        wait_for("KEBA integration", lambda: any(
            item["entry_id"] == entry_id and item["state"] == "loaded"
            for item in api(entries_path)
        ))
        wait_for("Modbus sensor values", lambda: any(
            state["attributes"].get("keba_key") == "flow_temperature"
            and state["state"] not in ("unavailable", "unknown")
            for state in api("/api/states")
        ))
        # The module contains both the control card and the status/history card.
        card_path = f"/api/{DOMAIN}/keba-heat-pump-modbus-card.js"
        with urlopen(url.rstrip("/") + card_path, timeout=30) as response:
            if response.status != 200:
                raise RuntimeError("Bundled Lovelace cards are not available")
        print(f"HA ready: {url.rstrip('/')}/lovelace/keba", flush=True)
    finally:
        api("/auth/token", {"action": "revoke", "token": tokens["refresh_token"]}, form=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("HA_URL", "http://localhost:8123"))
    args = parser.parse_args()
    bootstrap(args.url, os.environ.get("HA_DEV_USERNAME", "dev"),
              os.environ.get("HA_DEV_PASSWORD", "dev"))
