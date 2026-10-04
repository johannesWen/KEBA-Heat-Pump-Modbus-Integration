"""Run with: python3 -m unittest discover -s dev -p 'test_*.py'."""

from io import BytesIO
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

from bootstrap import DOMAIN, SIMULATOR_CONFIG, bootstrap


class BootstrapTest(unittest.TestCase):
    def test_fresh_start_partial_onboarding_and_restart(self):
        entries = []
        user_creations = []
        completed_steps = set()
        revoked = []
        restarted = False
        connecting = True
        starting = True

        def respond(request, timeout):
            nonlocal connecting, starting
            path = urlparse(request if isinstance(request, str) else request.full_url).path
            body = None if isinstance(request, str) else request.data
            if body:
                data = (parse_qs(body.decode()) if path == "/auth/token"
                        else json.loads(body))
            else:
                data = None

            if path == "/api/onboarding":
                if restarted:
                    raise HTTPError(request.full_url, 404, "Not Found", {}, None)
                if starting:
                    starting = False
                    raise URLError("Server is starting")
                result = [{"step": s, "done": s in completed_steps}
                          for s in ("user", "core_config", "analytics", "integration")]
            elif path == "/api/onboarding/users":
                user_creations.append(data)
                completed_steps.add("user")
                result = {"auth_code": "code"}
            elif path == "/auth/login_flow":
                result = {"flow_id": "login"}
            elif path == "/auth/login_flow/login":
                self.assertEqual(data["username"], "dev")
                result = {"type": "create_entry", "result": "code"}
            elif path == "/auth/token":
                if data.get("action") == ["revoke"]:
                    revoked.append(data["token"])
                    result = None
                else:
                    self.assertEqual(data["code"], ["code"])
                    result = {"access_token": "access", "refresh_token": "refresh"}
            else:
                if not isinstance(request, str):
                    self.assertEqual(request.get_header("Authorization"), "Bearer access")
                if path.startswith("/api/onboarding/"):
                    completed_steps.add(path.rsplit("/", 1)[1])
                    result = {}
                elif path == "/api/config":
                    result = {"state": "RUNNING"}
                elif path == "/api/config/config_entries/entry":
                    result = entries
                elif path == "/api/config/config_entries/entry/simulator/reload":
                    result = {}
                elif path == "/api/config/config_entries/flow":
                    self.assertEqual(data, {"handler": DOMAIN})
                    result = {"flow_id": "keba"}
                elif path == "/api/config/config_entries/flow/keba":
                    self.assertEqual(data, SIMULATOR_CONFIG)
                    entries.append({"entry_id": "simulator", "state": "loaded",
                                    "title": "KEBA Heat Pump (modbus-simulator)"})
                    result = {"type": "create_entry", "result": entries[0]}
                elif path == "/api/states":
                    result = [{"state": "unavailable" if connecting else "42.0",
                               "attributes": {"keba_key": "flow_temperature"}}]
                    connecting = False
                else:
                    self.assertEqual(path, f"/api/{DOMAIN}/keba-heat-pump-modbus-card.js")
                    result = None
            response = BytesIO(json.dumps(result).encode() if result is not None else b"")
            response.status = 200
            return response

        with patch("bootstrap.urlopen", side_effect=respond), patch("bootstrap.time.sleep"):
            bootstrap("http://homeassistant:8123", "dev", "dev")
            # Re-enter after only the user step was saved, then after an HA restart.
            completed_steps.intersection_update({"user"})
            bootstrap("http://homeassistant:8123", "dev", "dev")
            restarted = True
            bootstrap("http://homeassistant:8123", "dev", "dev")

        self.assertEqual(len(user_creations), 1)
        self.assertEqual(len(entries), 1)
        self.assertEqual(len(revoked), 3)
        self.assertEqual(completed_steps, {"user", "core_config", "analytics", "integration"})


if __name__ == "__main__":
    unittest.main()
