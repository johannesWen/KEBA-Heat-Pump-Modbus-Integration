"""Status card browser regressions. Run after npm run build, like check_card.py."""
import unittest

from playwright.sync_api import sync_playwright, expect

from check_card import BUNDLE


FIXTURE = """<!doctype html><html><head><meta charset="utf-8"><style>
body { font-family: sans-serif; --primary-color: #007b83; --primary-text-color: #202c32;
--secondary-text-color: #596b75; --card-background-color: white; --divider-color: #d8e0e3; }
ha-card { display: block; background: var(--card-background-color); }
keba-heat-pump-modbus-status-card { display: block; width: 420px; }
</style></head><body><script type="module">
import '/card.js';
window.calls = []; window.listeners = {}; window.readyListeners = new Set();
window.unsubscribed = []; window.fail = ''; window.hold = false;
window.helpersLoaded = 0;
window.loadCardHelpers = async () => ({createCardElement(config) {
  window.helpersLoaded++;
  window.chartConfig = config;
  customElements.define('state-history-charts', class extends HTMLElement {});
  return document.createElement('div');
}});
const entity = (id, device, key, platform='keba_heat_pump_modbus', disabled_by=null) =>
  ({entity_id:id, device_id:device, unique_id:key, platform, disabled_by});
window.entities = [
  entity('sensor.renamed_flow', 'hp1', 'flow_temperature'),
  entity('sensor.return', 'hp1', 'reflux_temperature'),
  entity('number.target', 'hp1', 'set_temperature'),
  entity('number.offset', 'hp1', 'room_offset_temperature_circuit_1'),
  entity('sensor.disabled', 'hp1', 'disabled_temperature', 'keba_heat_pump_modbus', 'integration'),
  entity('sensor.other', 'hp1', 'other', 'other_integration'),
  entity('sensor.hot_water', 'dhw', 'temperature_top_dhw_tank1'),
  entity('number.hot_water_target', 'dhw', 'temperature_top_set_dhw_tank1'),
  entity('sensor.second', 'hp2', 'flow_temperature'),
  entity('sensor.room', 'circuit', 'actual_room_temperature_circuit_1'),
  entity('sensor.buffer', 'buffer', 'temperature_top_buffer_tank1'),
  entity('sensor.exterior', 'system', 'exterior_temperature'),
];
window.devices = ['hp1', 'hp2', 'dhw', 'circuit', 'buffer', 'system'].map(id => ({
  id, name: id.startsWith('hp') ? 'Heat Pump' : id,
  name_by_user: id === 'dhw' ? 'My hot water' : null,
  identifiers: [['keba_heat_pump_modbus', id.startsWith('hp') ? `${id}_heat_pump` : id]],
}));
window.states = Object.fromEntries(window.entities.map(e => [e.entity_id, {
  entity_id: e.entity_id, state: '30', attributes: { keba_key:e.unique_id,
    device_class:'temperature', state_class:'measurement', unit_of_measurement:'°C', friendly_name:e.unique_id }
}]));
window.states['sensor.return'].state = 'unavailable';
window.hass = {
  config: {time_zone:'Europe/Vienna', components:['history','recorder']},
  locale: {language:'en'}, states:window.states,
  connection: {
    addEventListener(type, cb) { window.readyListeners.add(cb); },
    removeEventListener(type, cb) { window.readyListeners.delete(cb); },
    async subscribeEvents(cb, type) { window.listeners[type] = cb;
      return () => { window.unsubscribed.push(type); delete window.listeners[type]; }; }
  },
  async callWS(params) {
    window.calls.push(params);
    if (window.fail === params.type) throw new Error('Connection lost');
    if (params.type === 'config/entity_registry/list') return structuredClone(window.entities);
    if (params.type === 'config/device_registry/list') return structuredClone(window.devices);
    if (params.type === 'recorder/statistics_during_period') {
      const start = Date.parse(params.start_time);
      return Object.fromEntries(params.statistic_ids.map(id => [id, [
        {mean:null, end:start + 3600000},
        {mean:22, end:start + 7200000},
        {mean:23, end:Date.parse(params.end_time) - 1000},
      ]]));
    }
    if (window.hold) {
      window.hold = false;
      return await new Promise(resolve => { window.release = resolve; });
    }
    const start = window.recentOnly ? Date.parse(params.end_time) - 86400000 : Date.parse(params.start_time);
    return Object.fromEntries(params.entity_ids.map(id => [id, window.empty ? [] : [
      {s:'30', lu:start/1000}, {s:'unavailable', lc:(start+1000)/1000},
      {s:'31', lu:(start+2000)/1000},
    ]]));
  }
};
window.card = document.createElement('keba-heat-pump-modbus-status-card');
card.setConfig({}); card.hass = window.hass; document.body.append(card);
</script></body></html>"""


class StatusCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page(timezone_id="America/Los_Angeles")
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.clock.install(time="2026-10-20T10:00:00Z")
        self.page.clock.set_fixed_time("2026-10-20T10:00:00Z")
        self.page.route("http://keba.test/card.js", lambda route: route.fulfill(path=str(BUNDLE), content_type="text/javascript"))
        self.page.route("http://keba.test/", lambda route: route.fulfill(body=FIXTURE, content_type="text/html"))
        self.page.goto("http://keba.test/")
        expect(self.page.locator("state-history-charts")).to_be_attached()

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def history_calls(self):
        return self.page.evaluate("window.calls.filter(c => c.type === 'history/history_during_period')")

    def select_window(self, label):
        self.page.get_by_role("button", name=label, exact=True).click()
        expect(self.page.locator("state-history-charts")).to_be_attached()

    def test_discovery_and_chart_contract(self):
        expect(self.page.get_by_label("Device", exact=True)).to_have_value("hp1")
        self.assertEqual(self.history_calls()[-1]["entity_ids"], ["sensor.renamed_flow", "sensor.return", "number.target"])
        options = self.page.get_by_label("Device", exact=True).locator("option").all_text_contents()
        self.assertEqual(len(options), 6)
        self.assertIn("Heat Pump (1)", options)
        self.assertIn("Heat Pump (2)", options)
        self.assertIn("My hot water", options)
        data = self.page.locator("state-history-charts").evaluate("node => node.historyData")
        self.assertEqual(len(data["line"][0]["data"]), 3)
        self.assertEqual(data["line"][0]["data"][0]["states"][1]["state"], "unavailable")
        self.assertEqual(self.page.evaluate("window.helpersLoaded"), 1)
        self.assertEqual(self.page.evaluate("window.chartConfig.entities"), ["sensor.renamed_flow"])
        self.assertTrue(self.history_calls()[-1]["include_start_time_state"])
        self.page.get_by_label("Device", exact=True).select_option("dhw")
        expect(self.page.locator("state-history-charts")).to_be_attached()
        self.assertEqual(self.history_calls()[-1]["entity_ids"], ["sensor.hot_water", "number.hot_water_target"])

    def test_presets_use_server_timezone_and_exact_bounds(self):
        for label, start, end in [
            ("Last hour", "2026-10-20T09:00:00.000Z", "2026-10-20T10:00:00.000Z"),
            ("Last 3 hours", "2026-10-20T07:00:00.000Z", "2026-10-20T10:00:00.000Z"),
            ("Last 6 hours", "2026-10-20T04:00:00.000Z", "2026-10-20T10:00:00.000Z"),
            ("Today so far", "2026-10-19T22:00:00.000Z", "2026-10-20T10:00:00.000Z"),
            ("Yesterday", "2026-10-18T22:00:00.000Z", "2026-10-19T22:00:00.000Z"),
            ("This week", "2026-10-18T22:00:00.000Z", "2026-10-20T10:00:00.000Z"),
            ("This month", "2026-09-30T22:00:00.000Z", "2026-10-20T10:00:00.000Z"),
        ]:
            self.select_window(label)
            call = self.history_calls()[-1]
            self.assertEqual((call["start_time"], call["end_time"]), (start, end), label)
            expect(self.page.get_by_role("button", name=label, exact=True)).to_have_attribute("aria-pressed", "true")

    def test_dst_days_and_calendar_boundaries(self):
        for now, label, start, end in [
            ("2026-03-30T10:00:00Z", "Yesterday", "2026-03-28T23:00:00.000Z", "2026-03-29T22:00:00.000Z"),
            ("2026-10-26T10:00:00Z", "Yesterday", "2026-10-24T22:00:00.000Z", "2026-10-25T23:00:00.000Z"),
            ("2027-01-01T10:00:00Z", "This month", "2026-12-31T23:00:00.000Z", "2027-01-01T10:00:00.000Z"),
            ("2027-01-01T10:00:00Z", "This week", "2026-12-27T23:00:00.000Z", "2027-01-01T10:00:00.000Z"),
        ]:
            self.page.clock.set_fixed_time(now)
            self.select_window(label)
            call = self.history_calls()[-1]
            self.assertEqual((call["start_time"], call["end_time"]), (start, end))
        self.page.evaluate("window.hass.config.time_zone = 'America/New_York'")
        self.select_window("Today so far")
        self.assertEqual(self.history_calls()[-1]["start_time"], "2027-01-01T05:00:00.000Z")
        # Some zones change clocks at midnight itself rather than at 02:00.
        for zone, now, start in [
            ("America/Santiago", "2026-09-06T12:00:00Z", "2026-09-06T04:00:00.000Z"),
            ("America/Havana", "2026-11-01T12:00:00Z", "2026-11-01T04:00:00.000Z"),
        ]:
            self.page.clock.set_fixed_time(now)
            self.page.evaluate("zone => window.hass.config.time_zone = zone", zone)
            self.select_window("Today so far")
            self.assertEqual(self.history_calls()[-1]["start_time"], start)

    def test_statistics_merge_older_only_and_keep_setpoints(self):
        self.page.evaluate("window.recentOnly = true")
        self.select_window("This month")
        data = self.page.locator("state-history-charts").evaluate("node => node.historyData.line[0].data")
        by_id = {entity["entity_id"]: entity for entity in data}
        self.assertEqual(len(by_id["sensor.renamed_flow"]["statistics"]), 1)
        self.assertEqual(by_id["sensor.renamed_flow"]["statistics"][0]["state"], "22")
        self.assertEqual(by_id["number.target"]["statistics"], [])
        expect(self.page.get_by_text("Older sensor values are hourly averages.", exact=False)).to_be_visible()
        stats = self.page.evaluate("window.calls.filter(c => c.type === 'recorder/statistics_during_period').at(-1)")
        self.assertEqual(stats["statistic_ids"], ["sensor.renamed_flow", "sensor.return"])
        self.assertEqual(stats["units"], {"temperature": "°C"})
        self.assertEqual(stats["types"], ["mean"])
        # Statistics can render even when detailed history has been completely purged.
        self.page.evaluate("window.empty = true")
        self.select_window("This week")
        data = self.page.locator("state-history-charts").evaluate("node => node.historyData.line[0].data")
        self.assertTrue(all(not entity["states"] and entity["statistics"] for entity in data))

    def test_statistics_failure_and_history_retry(self):
        self.page.evaluate("window.fail = 'recorder/statistics_during_period'")
        self.select_window("This month")
        expect(self.page.get_by_text("Older statistics unavailable:", exact=False)).to_be_visible()
        self.page.evaluate("window.fail = 'history/history_during_period'")
        self.page.get_by_role("button", name="Last hour", exact=True).click()
        expect(self.page.get_by_role("alert")).to_contain_text("Connection lost")
        self.page.evaluate("window.fail = ''")
        self.page.get_by_role("button", name="Refresh history").click()
        expect(self.page.locator("state-history-charts")).to_be_attached()
        expect(self.page.get_by_role("alert")).to_have_count(0)

    def test_empty_disabled_and_missing_device_states(self):
        self.page.evaluate("window.empty = true")
        self.page.get_by_role("button", name="Last hour", exact=True).click()
        expect(self.page.get_by_text("No temperature history found for this period.")).to_be_visible()
        self.page.evaluate("card.setConfig({device_id:'removed'})")
        expect(self.page.get_by_text("Selected device unavailable.", exact=True)).to_be_visible()
        self.page.evaluate("card.setConfig({}); window.hass.config.components = []; card.hass = {...window.hass}")
        expect(self.page.get_by_role("alert")).to_contain_text("History is not enabled")
        self.page.evaluate("window.entities = []; window.listeners.entity_registry_updated()")
        expect(self.page.get_by_text("Selected device unavailable.", exact=True)).to_be_visible()

    def test_stale_results_refresh_and_disconnect_cleanup(self):
        self.page.evaluate("window.hold = true")
        self.page.get_by_role("button", name="Last hour", exact=True).click()
        expect(self.page.get_by_text("Loading temperature history…")).to_be_visible()
        self.page.get_by_label("Device", exact=True).select_option("hp2")
        expect(self.page.locator("state-history-charts")).to_be_attached()
        self.page.evaluate("window.release({'sensor.renamed_flow':[{s:'99',lu:1}]})")
        expect(self.page.locator("state-history-charts")).to_be_attached()
        self.assertEqual(self.page.locator("state-history-charts").evaluate("node => node.historyData.line[0].data[0].entity_id"), "sensor.second")
        before = len(self.history_calls())
        self.page.clock.run_for(60000)
        expect(self.page.locator("state-history-charts")).to_be_attached()
        self.assertEqual(len(self.history_calls()), before + 1)
        self.select_window("Yesterday")
        before = len(self.history_calls())
        self.page.clock.run_for(60000)
        self.assertEqual(len(self.history_calls()), before)
        self.page.evaluate("card.remove()")
        self.assertEqual(self.page.evaluate("window.readyListeners.size"), 0)
        self.assertEqual(sorted(self.page.evaluate("window.unsubscribed")), ["device_registry_updated", "entity_registry_updated"])
        before = len(self.history_calls())
        self.page.clock.run_for(60000)
        self.assertEqual(len(self.history_calls()), before)
        self.page.evaluate("document.body.append(card)")
        expect(self.page.locator("state-history-charts")).to_be_attached()

    def test_registry_changes_reconnect_and_no_fetch_on_state_refresh(self):
        before = len(self.history_calls())
        self.page.evaluate("card.hass = {...window.hass}")
        self.page.wait_for_timeout(50)
        self.assertEqual(len(self.history_calls()), before)
        self.page.evaluate("""() => {
          window.devices[0].name_by_user = 'Basement pump';
          window.listeners.device_registry_updated();
        }""")
        expect(self.page.get_by_label("Device", exact=True).locator("option", has_text="Basement pump")).to_have_count(1)
        self.page.evaluate("window.readyListeners.forEach(cb => cb())")
        expect(self.page.locator("state-history-charts")).to_be_attached()

    def test_saved_defaults_before_discovery_and_editor_load(self):
        self.page.evaluate("""() => {
          card.remove();
          window.card = document.createElement('keba-heat-pump-modbus-status-card');
          const config = {device_id:'dhw', time_window:'last_6_hours'};
          card.setConfig(config); card.hass = window.hass; document.body.append(card);
          const editor = card.constructor.getConfigElement();
          editor.setConfig(config); editor.hass = window.hass; document.body.append(editor);
        }""")
        expect(self.page.locator("state-history-charts")).to_be_attached()
        expect(self.page.get_by_label("Device", exact=True)).to_have_value("dhw")
        expect(self.page.get_by_role("button", name="Last 6 hours", exact=True)).to_have_attribute("aria-pressed", "true")
        editor = self.page.locator("keba-heat-pump-modbus-status-card-editor")
        expect(editor.get_by_label("Initial device").locator("option")).to_have_count(7)
        expect(editor.get_by_label("Initial device")).to_have_value("dhw")
        expect(editor.get_by_label("Initial time window")).to_have_value("last_6_hours")

    def test_empty_discovery_and_registry_failure_retry(self):
        self.page.evaluate("window.fail = 'config/entity_registry/list'")
        self.page.get_by_role("button", name="Refresh history").click()
        expect(self.page.get_by_role("alert")).to_contain_text("Connection lost")
        self.page.evaluate("window.fail = ''; window.entities = []; card.setConfig({})")
        self.page.get_by_role("button", name="Refresh history").click()
        expect(self.page.get_by_text("Selected device unavailable.", exact=True)).to_be_visible()
        expect(self.page.get_by_role("alert")).to_have_count(0)
        self.page.evaluate("""() => {
          card.remove(); window.card = document.createElement('keba-heat-pump-modbus-status-card');
          card.setConfig({}); card.hass = window.hass; document.body.append(card);
        }""")
        expect(self.page.get_by_text("No KEBA temperature devices available.")).to_be_visible()
        self.assertEqual(self.page.get_by_label("Device", exact=True).locator("option").count(), 1)

    def test_late_chart_helpers_and_pending_subscriptions(self):
        # Use a fresh document so the native chart stub has not been registered yet.
        delayed = FIXTURE.replace(
            "card.setConfig({}); card.hass = window.hass; document.body.append(card);",
            """window.installHelpers = window.loadCardHelpers; delete window.loadCardHelpers;
            window.hass.connection.subscribeEvents = (cb, type) => new Promise(resolve => {
              window.pendingSubscriptions ||= []; window.pendingSubscriptions.push({resolve, type});
            });
            card.setConfig({}); card.hass = window.hass; document.body.append(card);""",
        )
        self.page.route("http://keba.test/", lambda route: route.fulfill(body=delayed, content_type="text/html"))
        self.page.reload()
        expect(self.page.get_by_text("Loading temperature history…")).to_be_visible()
        self.page.evaluate("""() => {
          card.remove(); document.body.append(card);
          window.loadCardHelpers = window.installHelpers;
          customElements.define('ha-panel-lovelace', class extends HTMLElement {});
          window.pendingSubscriptions.forEach(({resolve,type}) => resolve(() => {
            window.unsubscribed.push(type); return Promise.reject(new Error('Disconnected'));
          }));
        }""")
        expect(self.page.locator("state-history-charts")).to_be_attached()
        self.assertEqual(len(self.page.evaluate("window.unsubscribed")), 2)
        self.page.evaluate("card.remove()")
        self.page.wait_for_timeout(50)
        self.assertEqual(len(self.page.evaluate("window.unsubscribed")), 4)

    def test_unit_groups_editor_registration_and_narrow_layout(self):
        self.assertEqual(self.page.evaluate("window.customCards.filter(c => c.type === 'keba-heat-pump-modbus-status-card').length"), 1)
        self.page.evaluate("window.states['sensor.return'].attributes.unit_of_measurement = '°F'; card.hass = {...window.hass}")
        expect(self.page.locator("state-history-charts")).to_be_attached()
        self.assertEqual(self.page.locator("state-history-charts").evaluate("node => node.historyData.line.map(line => line.unit)"), ["°C", "°F"])
        self.page.evaluate("""() => {
          const editor = card.constructor.getConfigElement(); editor.setConfig({type:'custom:keba-heat-pump-modbus-status-card'});
          editor.hass = window.hass;
          editor.addEventListener('config-changed', event => { window.editedConfig = event.detail.config; editor.setConfig(event.detail.config); });
          document.body.append(editor);
        }""")
        editor = self.page.locator("keba-heat-pump-modbus-status-card-editor")
        expect(editor.get_by_label("Initial device").locator("option")).to_have_count(7)
        editor.get_by_label("Title").fill("Temperatures")
        editor.get_by_label("Initial device").select_option("dhw")
        editor.get_by_label("Initial time window").select_option("last_3_hours")
        config = self.page.evaluate("window.editedConfig")
        self.assertEqual(config["title"], "Temperatures")
        self.assertEqual(config["device_id"], "dhw")
        self.assertEqual(config["time_window"], "last_3_hours")
        self.page.evaluate("config => card.setConfig(config)", config)
        expect(self.page.get_by_label("Device", exact=True)).to_have_value("dhw")
        for width in [280, 320, 420, 700]:
            self.page.evaluate("width => card.style.width = `${width}px`", width)
            self.assertFalse(self.page.locator(".content").evaluate("node => node.scrollWidth > node.clientWidth + 1"))
        self.page.evaluate("document.body.style.setProperty('--card-background-color', '#18242b')")
        expect(self.page.get_by_label("Device", exact=True)).to_be_visible()


if __name__ == "__main__":
    unittest.main()
