"""Combined card Status view browser regressions. Run after npm run build, like check_card.py."""
import json
import unittest

from playwright.sync_api import sync_playwright, expect

from check_card import BUNDLE


FIXTURE = """<!doctype html><html><head><meta charset="utf-8"><style>
body { font-family: sans-serif; --primary-color: #007b83; --primary-text-color: #202c32;
--secondary-text-color: #596b75; --card-background-color: white; --divider-color: #d8e0e3; }
ha-card { display: block; background: var(--card-background-color); }
keba-heat-pump-modbus-card { display: block; width: 420px; }
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
    if (window.recordedHistory) return window.recordedHistory;
    const start = window.recentOnly ? Date.parse(params.end_time) - 86400000 : Date.parse(params.start_time);
    return Object.fromEntries(params.entity_ids.map(id => [id, window.empty ? [] : [
      {s:'30', lu:start/1000}, {s:'unavailable', lc:(start+1000)/1000},
      {s:'31', lu:(start+2000)/1000},
    ]]));
  }
};
window.mountCard = async config => {
  window.dashboardCard?.remove();
  window.dashboardCard = document.createElement('keba-heat-pump-modbus-card');
  dashboardCard.setConfig({view:'status', ...config}); dashboardCard.hass = window.hass;
  document.body.append(dashboardCard);
  await dashboardCard.updateComplete;
  window.card = dashboardCard._statusView;
};
await window.mountCard({});
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

    def test_status_is_lazy_and_tab_switches_preserve_session_selections(self) -> None:
        self.page.evaluate("window.mountCard({view:'settings'})")
        before = len(self.history_calls())
        self.page.clock.run_for(60000)
        self.assertEqual(len(self.history_calls()), before)
        self.assertEqual(self.page.evaluate("window.readyListeners.size"), 0)
        self.page.get_by_role("button", name="Status", exact=True).click()
        expect(self.page.locator("state-history-charts")).to_be_attached()
        self.page.evaluate("window.card = dashboardCard._statusView")
        self.page.get_by_label("Device", exact=True).select_option("hp2")
        self.select_window("Last 6 hours")
        self.page.get_by_role("button", name="Settings", exact=True).click()
        expect(self.page.locator("state-history-charts")).to_have_count(0)
        self.assertEqual(self.page.evaluate("window.readyListeners.size"), 0)
        before = len(self.history_calls())
        self.page.clock.run_for(60000)
        self.assertEqual(len(self.history_calls()), before)
        self.page.evaluate("dashboardCard.setConfig({...dashboardCard.config, title:'Renamed'})")
        status = self.page.get_by_role("button", name="Status", exact=True)
        status.focus()
        status.press("Enter")
        expect(self.page.locator("state-history-charts")).to_be_attached()
        expect(self.page.get_by_label("Device", exact=True)).to_have_value("hp2")
        expect(self.page.get_by_role("button", name="Last 6 hours", exact=True)).to_have_attribute("aria-pressed", "true")
        self.assertTrue(self.page.evaluate("card === dashboardCard._statusView"))
        self.assertEqual(self.page.locator("ha-card").count(), 1)

        self.page.evaluate("window.hold = true")
        self.page.get_by_role("button", name="Today so far", exact=True).click()
        expect(self.page.get_by_text("Loading temperature history…")).to_be_visible()
        self.page.get_by_role("button", name="Settings", exact=True).click()
        status.click()
        expect(self.page.locator("state-history-charts")).to_be_attached()
        self.page.evaluate("window.release({'sensor.second':[{s:'99',lu:1}]})")
        self.assertEqual(self.page.locator("state-history-charts").evaluate(
            "node => node.historyData.line[0].data[0].states.at(-1).state"), "31")

    def test_status_tab_survives_reload_without_persisting_selections(self) -> None:
        config = self.page.evaluate("dashboardCard.constructor.getStubConfig()")
        self.page.evaluate("config => dashboardCard.setConfig(config)", config)
        self.page.get_by_role("button", name="Status", exact=True).click()
        expect(self.page.locator("state-history-charts")).to_be_attached()
        self.page.get_by_label("Device", exact=True).select_option("dhw")
        self.select_window("Last 6 hours")
        self.page.route("http://keba.test/", lambda route: route.fulfill(
            body=FIXTURE.replace("await window.mountCard({});",
                                 f"await window.mountCard({json.dumps(config)});"),
            content_type="text/html"))
        self.page.reload()
        expect(self.page.locator("state-history-charts")).to_be_attached()
        expect(self.page.get_by_role("button", name="Status", exact=True)).to_have_attribute("aria-pressed", "true")
        expect(self.page.get_by_label("Device", exact=True)).to_have_value("hp1")
        expect(self.page.get_by_role("button", name="Today so far", exact=True)).to_have_attribute("aria-pressed", "true")

    def test_dense_history_preserves_peaks_and_setpoints_in_every_preset(self) -> None:
        self.page.evaluate("""() => {
          const callWS = window.hass.callWS;
          window.hass.callWS = async params => {
            if (params.type !== 'history/history_during_period') return callWS(params);
            const start = Date.parse(params.start_time), end = Date.parse(params.end_time);
            window.denseHistory = Array.from({length:10001}, (_, index) => ({
              s: String(index % 40 === 7 ? 80 : index % 40 === 23 ? -40 : 20),
              lu: (start + Math.round((end - start) * index / 10000)) / 1000,
            }));
            return Object.fromEntries(params.entity_ids.map(id => [id, denseHistory]));
          };
        }""")
        for label in ["Last hour", "Last 3 hours", "Last 6 hours", "Today so far",
                      "Yesterday", "This week", "This month"]:
            with self.subTest(preset=label):
                self.select_window(label)
                result = self.page.locator("state-history-charts").evaluate("""node => {
                  const data = node.historyData.line[0].data;
                  const states = data.find(entity => entity.entity_id === 'sensor.renamed_flow').states;
                  const original = denseHistory.map(point => ({state:point.s, last_changed:point.lu*1000}));
                  const retained = new Set(states.map(point => point.last_changed));
                  const byTime = new Map(original.map(point => [point.last_changed, point.state]));
                  return {
                    count: states.length,
                    endpoints: JSON.stringify([states[0], states.at(-1)]) ===
                      JSON.stringify([original[0], original.at(-1)]),
                    peaks: original.filter((point, index) => index % 40 === 7 || index % 40 === 23)
                      .every(point => retained.has(point.last_changed)),
                    bucketEdges: original.filter((point, index) => index % 40 === 0 ||
                      (index % 40 === 39 && index < 9960)).every(point => retained.has(point.last_changed)),
                    recorded: states.every(point => byTime.get(point.last_changed) === point.state),
                    ordered: states.every((point, index) => !index ||
                      point.last_changed > states[index-1].last_changed),
                    setpoints: JSON.stringify(data.find(entity => entity.entity_id === 'number.target').states)
                      === JSON.stringify(original),
                  };
                }""")
                self.assertLessEqual(result.pop("count"), 1000)
                self.assertTrue(all(result.values()), result)

    def test_resampling_sparse_constant_and_gap_boundaries(self) -> None:
        for mode in ["sparse", "constant", "gaps", "one_valid"]:
            with self.subTest(mode=mode):
                result = self.page.evaluate("""async mode => {
                  const start = card._range.start.getTime();
                  const raw = Array.from({length:mode === 'sparse' ? 1000 : 10001}, (_, index) => ({
                    s:'-5', lu:(start + index * 1000)/1000,
                  }));
                  if (mode === 'sparse' || mode === 'gaps') {
                    raw[0].lu -= 60;
                    for (let index = 123; index <= 150; index++) raw[index].s = 'unavailable';
                    for (let index = 321; index <= 345; index++) raw[index].s = '';
                    raw[raw.length-1].s = 'unknown';
                  }
                  if (mode === 'one_valid') raw.forEach((point, index) => {
                    point.s = index === 5000 ? '-5' : 'unavailable';
                  });
                  window.recordedHistory = {'sensor.renamed_flow':raw};
                  await card._fetchHistory(); await card.updateComplete;
                  const states = card._history.line[0].data[0].states;
                  const original = raw.map(point => ({state:point.s, last_changed:point.lu*1000}));
                  const retained = new Set(states.map(point => point.last_changed));
                  const required = mode === 'one_valid' ? [0,4999,5000,5001,10000] :
                    [0,122,123,150,151,320,321,345,346,raw.length-2,raw.length-1];
                  return {count:states.length, unchanged:JSON.stringify(states) === JSON.stringify(original),
                    boundaries:required.every(index => retained.has(original[index].last_changed)),
                    endpoints:states[0].last_changed === original[0].last_changed &&
                      states.at(-1).last_changed === original.at(-1).last_changed,
                    values:states.every(point => mode !== 'constant' || point.state === '-5'),
                  };
                }""", mode)
                self.assertTrue(result["endpoints"])
                if mode == "sparse":
                    self.assertTrue(result["unchanged"])
                elif mode == "constant":
                    self.assertLessEqual(result["count"], 500)
                    self.assertTrue(result["values"])
                else:
                    self.assertTrue(result["boundaries"])
                    self.assertLessEqual(result["count"], 1012)

    def test_chart_data_reused_until_history_or_buffer_selection_changes(self) -> None:
        self.page.evaluate("""async () => {
          window.previousChart = card.shadowRoot.querySelector('state-history-charts');
          window.previousData = previousChart.historyData;
          card.hass = {...window.hass}; await card.updateComplete;
        }""")
        self.assertTrue(self.page.evaluate("""() => {
          const chart = card.shadowRoot.querySelector('state-history-charts');
          return chart === previousChart && chart.historyData === previousData && chart.hass === card.hass;
        }"""))
        self.page.get_by_role("button", name="Refresh history").click()
        expect(self.page.locator("state-history-charts")).to_be_attached()
        self.assertTrue(self.page.evaluate(
            "card.shadowRoot.querySelector('state-history-charts').historyData !== previousData"))
        self.page.evaluate("""() => {
          window.entities.push({entity_id:'sensor.backup', device_id:'buffer',
            unique_id:'temperature_backup_buffer_tank1', platform:'keba_heat_pump_modbus'});
          window.states['sensor.backup'] = {entity_id:'sensor.backup', state:'30', attributes:{
            keba_key:'temperature_backup_buffer_tank1', device_class:'temperature',
            unit_of_measurement:'°C', friendly_name:'Backup temperature'}};
          window.listeners.entity_registry_updated();
        }""")
        self.page.get_by_label("Device", exact=True).select_option("buffer")
        expect(self.page.locator("state-history-charts")).to_be_attached()
        self.page.evaluate("window.previousData = card.shadowRoot.querySelector('state-history-charts').historyData")
        before = len(self.history_calls())
        self.page.get_by_role("checkbox", name="Backup temperature", exact=True).check()
        result = self.page.locator("state-history-charts").evaluate("""node => ({
          changed:node.historyData !== previousData,
          ids:node.historyData.line.flatMap(group => group.data.map(entity => entity.entity_id)),
        })""")
        self.assertTrue(result["changed"])
        self.assertIn("sensor.backup", result["ids"])
        self.assertEqual(len(self.history_calls()), before)

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

    def test_legend_entity_names_without_device_prefix(self):
        self.page.evaluate("""() => {
          window.states['sensor.renamed_flow'].attributes.friendly_name = 'Heat Pump Flow temperature';
          window.states['sensor.return'].attributes.friendly_name = 'Heat Pump Reflux temperature';
          window.states['number.target'].attributes.friendly_name = 'Custom setpoint';
          window.listeners.entity_registry_updated();
        }""")
        charts = self.page.locator("state-history-charts")
        expect(charts).to_be_attached()
        self.assertEqual(charts.evaluate("node => node.historyData.line[0].data.map(entity => entity.name)"),
                         ["Flow temperature", "Reflux temperature", "Custom setpoint"])
        self.page.evaluate("""() => {
          window.devices.find(device => device.id === 'hp1').name_by_user = 'Basement [HP]';
          window.states['sensor.renamed_flow'].attributes.friendly_name = 'Basement [HP] Flow temperature';
          window.states['number.target'].attributes.friendly_name = 'Heat Pumping target';
          window.listeners.device_registry_updated();
        }""")
        expect(self.page.get_by_label("Device", exact=True).locator("option:checked")).to_have_text("Basement [HP]")
        expect(charts).to_be_attached()
        self.assertEqual(charts.evaluate("node => node.historyData.line[0].data.map(entity => entity.name)"),
                         ["Flow temperature", "Reflux temperature", "Heat Pumping target"])

    def test_combined_legend_and_selected_values(self):
        self.page.evaluate("""async () => {
          customElements.define('ha-chart-base', class extends HTMLElement {
            controllers = [];
            hidden = new Set();
            onCalls = 0;
            chart = {on: (type, callback) => { this.onCalls++; this.hideTip = callback; }};
            updateComplete = Promise.resolve();
            constructor() { super(); this.attachShadow({mode: 'open'}); }
            addController(controller) { this.controllers.push(controller); }
            requestUpdate() {
              let legend = this.shadowRoot.querySelector('.chart-legend');
              if (!legend) {
                legend = document.createElement('div'); legend.className = 'chart-legend';
                this.shadowRoot.append(legend);
              }
              const list = document.createElement('ul');
              for (const item of this.options.legend.data) {
                const row = document.createElement('li');
                const toggle = document.createElement('button');
                toggle.className = 'legend-toggle'; toggle.textContent = '●';
                toggle.setAttribute('aria-label', `Toggle ${item.id}`);
                toggle.setAttribute('aria-pressed', String(!this.hidden.has(item.id)));
                toggle.onclick = () => {
                  if (this.hidden.has(item.id)) this.hidden.delete(item.id);
                  else this.hidden.add(item.id);
                  this.requestUpdate();
                };
                const label = document.createElement('button');
                label.className = 'label'; label.textContent = item.name;
                const value = document.createElement('div');
                value.className = 'value'; value.textContent = item.value;
                row.append(toggle, label, value); list.append(row);
              }
              legend.replaceChildren(list);
              this.controllers.forEach(controller => controller.hostUpdated());
            }
          });
          customElements.define('state-history-chart-line', class extends HTMLElement {
            controllers = [];
            updateComplete = Promise.resolve();
            addController(controller) { this.controllers.push(controller); }
          });
          const charts = card.shadowRoot.querySelector('state-history-charts');
          charts.style.height = '300px'; charts.attachShadow({mode: 'open'});
          window.selectedTime = Date.parse('2026-10-20T08:00:00Z');
          window.nativeLines = ['°C', '°F'].map(unit => {
            const line = document.createElement('state-history-chart-line'); line.unit = unit;
            const base = document.createElement('ha-chart-base');
            line.attachShadow({mode: 'open'}).append(base);
            base.data = Array.from({length:30}, (_,index) => ({
              id: `sensor.temperature_${index}`, name: 'Long entity name '.repeat(8),
              data: index === 29 ? [] : [[selectedTime-1000, 20+index], [selectedTime, 42+index]],
            }));
            line.resetOptions = () => {
              base.options = {grid:{top:15}, legend:{type:'custom', show:true,
                data:base.data.map(dataset => ({id:dataset.id, name:dataset.name}))},
                tooltip:{trigger:'axis', formatter:() => 'Native tooltip'}};
              line.controllers.forEach(controller => controller.hostUpdated());
            };
            line.resetOptions(); charts.shadowRoot.append(line); return line;
          });
          await card._configureChartLegends();
          window.inspectTime = (index, time) => nativeLines[index].shadowRoot
            .querySelector('ha-chart-base').options.tooltip.formatter([
              {axisValue:time, seriesId:'sensor.temperature_0', value:[time,45]},
            ]);
        }""")
        legends = self.page.get_by_role("group", name="Legend and selected values")
        expect(legends).to_have_count(2)
        expect(self.page.locator(".chart-tooltip")).to_have_count(0)
        expect(legends.nth(0).locator(".value").first).to_have_text("42 °C")
        expect(legends.nth(0).locator(".value").last).to_have_text("—")
        self.page.evaluate("inspectTime(0, selectedTime)")
        expect(legends.nth(0).locator(".value").first).to_have_text("45 °C")
        expect(legends.nth(0).locator(".value").nth(1)).to_have_text("43 °C")
        expect(legends.nth(0).locator(".selected-time")).to_contain_text("10:00:00")
        expect(legends.nth(1).locator(".value").first).to_have_text("42 °F")
        toggle = legends.nth(0).get_by_role("button", name="Toggle sensor.temperature_0", exact=True)
        toggle.click()
        expect(toggle).to_have_attribute("aria-pressed", "false")
        self.page.evaluate("nativeLines[0].resetOptions()")
        expect(legends.nth(0).locator(".selected-time")).to_contain_text("10:00:00")
        expect(legends.nth(0).locator(".value").first).to_have_text("42 °C")
        expect(toggle).to_have_attribute("aria-pressed", "false")
        expect(legends.nth(0).locator(".selected-time")).to_have_count(1)
        self.page.evaluate("inspectTime(0, selectedTime - 1000)")
        expect(legends.nth(0).locator(".value").first).to_have_text("45 °C")
        expect(legends.nth(0).locator(".value").nth(1)).to_have_text("21 °C")
        self.page.evaluate("nativeLines[0].shadowRoot.querySelector('ha-chart-base').hideTip({})")
        expect(legends.nth(0).locator(".value").first).to_have_text("45 °C")
        self.page.evaluate("nativeLines[0].shadowRoot.querySelector('ha-chart-base').hideTip({from:'outside'})")
        expect(legends.nth(0).locator(".value").first).to_have_text("42 °C")
        expect(legends.nth(0).locator(".value").nth(1)).to_have_text("43 °C")
        expect(legends.nth(0).locator(".selected-time")).to_contain_text("12:00:00")
        expect(toggle).to_have_attribute("aria-pressed", "false")
        self.assertEqual(self.page.evaluate("nativeLines[0].shadowRoot.querySelector('ha-chart-base').onCalls"), 1)
        self.page.evaluate("""() => {
          const base = nativeLines[0].shadowRoot.querySelector('ha-chart-base');
          base.data.forEach((dataset, index) => {
            if (dataset.data.length) dataset.data.push([Date.parse('2026-10-20T10:00:01Z'), 60+index]);
          });
          nativeLines[0].resetOptions();
        }""")
        expect(legends.nth(0).locator(".value").first).to_have_text("60 °C")
        expect(legends.nth(0).locator(".selected-time")).to_contain_text("12:00:01")
        expect(legends.nth(1).locator(".value").first).to_have_text("42 °F")
        self.assertTrue(legends.nth(0).evaluate("node => node.scrollHeight > node.clientHeight"))
        for width, columns in [(280, 1), (420, 2), (700, 2)]:
            self.page.evaluate("width => dashboardCard.style.width = `${width}px`", width)
            self.assertFalse(legends.nth(0).evaluate("node => node.scrollWidth > node.clientWidth + 1"))
            self.assertEqual(legends.nth(0).locator("ul").evaluate(
                "node => getComputedStyle(node).gridTemplateColumns.split(/\\s+/).length"), columns)
        self.assertEqual(self.page.evaluate("nativeLines[0].shadowRoot.querySelector('ha-chart-base').options.grid.top"), 15)
        self.page.get_by_label("Device", exact=True).select_option("dhw")
        expect(legends).to_have_count(0)

    def test_grouped_plots_and_optional_buffer_temperatures(self):
        self.page.evaluate("""() => {
          const additions = [
            ['sensor.renamed_source_in', 'hp1', 'source_in_temperature'],
            ['sensor.renamed_source_out', 'hp1', 'source_out_temperature'],
            ['sensor.middle', 'buffer', 'temperature_middle_buffer_tank1'],
            ['sensor.backup', 'buffer', 'temperature_backup_buffer_tank1'],
            ['number.minimum', 'buffer', 'temperature_min_set_buffer_tank1'],
            ['number.cool', 'buffer', 'temperature_cool_set_buffer_tank1'],
            ['number.excess', 'buffer', 'temperature_target_excess_heat_buffer_tank1'],
            ['sensor.circuit_flow', 'circuit', 'circuit_flow_temperature_circuit_1'],
            ['sensor.circuit_reflux', 'circuit', 'circuit_reflux_temperature_circuit_1'],
            ['number.room_target', 'circuit', 'room_set_temperature_circuit_1'],
            ['number.room_current_target', 'circuit', 'current_set_room_temperature_circuit_1'],
            ['number.room_reduced', 'circuit', 'room_set_temperature_reduced_circuit_1'],
          ];
          additions.forEach(([id, device, key]) => {
            window.entities.push({entity_id:id, device_id:device,
              unique_id:`installation_${key}`, platform:'keba_heat_pump_modbus'});
            window.states[id] = {entity_id:id, state:'30', attributes:{keba_key:key,
              device_class:'temperature', state_class:'measurement',
              unit_of_measurement:'°C', friendly_name:key}};
          });
          // Grouping also works with registry keys when state metadata is absent.
          delete window.states['sensor.renamed_source_out'].attributes.keba_key;
          window.listeners.entity_registry_updated();
        }""")
        charts = self.page.locator("state-history-charts")
        expect(charts).to_have_count(2)

        def plotted_entities():
            return charts.evaluate_all("nodes => nodes.map(node => node.historyData.line.flatMap(line => line.data.map(entity => entity.entity_id)))")

        self.assertEqual(plotted_entities(), [
            ['sensor.renamed_flow', 'sensor.return', 'number.target'],
            ['sensor.renamed_source_out', 'sensor.renamed_source_in'],
        ])
        self.assertEqual(set(self.history_calls()[-1]['entity_ids']), {
            'sensor.renamed_flow', 'sensor.return', 'number.target',
            'sensor.renamed_source_in', 'sensor.renamed_source_out',
        })
        self.assertEqual(charts.evaluate_all("nodes => new Set(nodes.map(node => `${node.startTime.toISOString()}/${node.endTime.toISOString()}`)).size"), 1)
        expect(self.page.get_by_role('heading', name='Source in and out')).to_be_visible()
        self.page.evaluate("window.recentOnly = true")
        self.page.get_by_role('button', name='This month', exact=True).click()
        expect(charts).to_have_count(2)
        self.assertTrue(charts.nth(1).evaluate("node => node.historyData.line[0].data.every(entity => entity.statistics.length === 1)"))

        self.page.get_by_label('Device', exact=True).select_option('buffer')
        expect(charts).to_have_count(1)
        self.assertEqual(plotted_entities(), [['sensor.middle', 'sensor.buffer']])
        extras = self.page.get_by_role('group', name='Additional temperatures')
        expect(extras.get_by_role('checkbox')).to_have_count(4)
        self.assertEqual(extras.locator('input:checked').count(), 0)
        before = len(self.history_calls())
        backup = extras.get_by_role('checkbox', name='temperature_backup_buffer_tank1', exact=True)
        backup.check()
        expect(backup).to_be_checked()
        self.assertIn('sensor.backup', plotted_entities()[0])
        self.assertEqual(len(self.history_calls()), before)
        self.page.get_by_role('button', name='Last hour', exact=True).click()
        expect(charts).to_have_count(1)
        expect(backup).to_be_checked()
        self.assertIn('sensor.backup', plotted_entities()[0])

        self.page.get_by_label('Device', exact=True).select_option('circuit')
        expect(charts).to_have_count(2)
        self.assertEqual(plotted_entities(), [
            ['sensor.circuit_flow', 'sensor.circuit_reflux'],
            ['sensor.room', 'number.room_current_target', 'number.room_target', 'number.room_reduced'],
        ])
        self.page.get_by_label('Device', exact=True).select_option('buffer')
        expect(charts).to_have_count(1)
        expect(backup).to_be_checked()
        backup.uncheck()
        self.assertEqual(plotted_entities(), [['sensor.middle', 'sensor.buffer']])
        for width in [280, 320, 420]:
            self.page.evaluate('width => dashboardCard.style.width = `${width}px`', width)
            self.assertFalse(self.page.locator('.content').evaluate('node => node.scrollWidth > node.clientWidth + 1'))

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
        self.page.evaluate("""async () => {
          const config = {view:'status', device_id:'dhw', time_window:'last_6_hours'};
          await window.mountCard(config);
          const editor = dashboardCard.constructor.getConfigElement();
          editor.setConfig(config); editor.hass = window.hass; document.body.append(editor);
        }""")
        expect(self.page.locator("state-history-charts")).to_be_attached()
        expect(self.page.get_by_label("Device", exact=True)).to_have_value("dhw")
        expect(self.page.get_by_role("button", name="Last 6 hours", exact=True)).to_have_attribute("aria-pressed", "true")
        editor = self.page.locator("keba-heat-pump-modbus-card-editor")
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
        self.page.evaluate("window.mountCard({})")
        expect(self.page.get_by_text("No KEBA temperature devices available.")).to_be_visible()
        self.assertEqual(self.page.get_by_label("Device", exact=True).locator("option").count(), 1)

    def test_late_chart_helpers_and_pending_subscriptions(self):
        # Use a fresh document so the native chart stub has not been registered yet.
        delayed = FIXTURE.replace(
            "await window.mountCard({});",
            """window.installHelpers = window.loadCardHelpers; delete window.loadCardHelpers;
            window.hass.connection.subscribeEvents = (cb, type) => new Promise(resolve => {
              window.pendingSubscriptions ||= []; window.pendingSubscriptions.push({resolve, type});
            });
            await window.mountCard({});""",
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
        self.assertEqual(self.page.evaluate("window.customCards.filter(c => c.type === 'keba-heat-pump-modbus-status-card').length"), 0)
        self.assertTrue(self.page.evaluate("""() =>
          !customElements.get('keba-heat-pump-modbus-status-card') &&
          !customElements.get('keba-heat-pump-modbus-status-card-editor')"""))
        self.assertEqual(self.page.evaluate("window.customCards.filter(c => c.type === 'keba-heat-pump-modbus-card').length"), 1)
        self.page.evaluate("window.states['sensor.return'].attributes.unit_of_measurement = '°F'; card.hass = {...window.hass}")
        expect(self.page.locator("state-history-charts")).to_be_attached()
        self.assertEqual(self.page.locator("state-history-charts").evaluate("node => node.historyData.line.map(line => line.unit)"), ["°C", "°F"])
        self.page.evaluate("""() => {
          const editor = dashboardCard.constructor.getConfigElement(); editor.setConfig({type:'custom:keba-heat-pump-modbus-card', view:'status'});
          editor.hass = window.hass;
          editor.addEventListener('config-changed', event => { window.editedConfig = event.detail.config; editor.setConfig(event.detail.config); });
          document.body.append(editor);
        }""")
        editor = self.page.locator("keba-heat-pump-modbus-card-editor")
        expect(editor.get_by_label("Initial device").locator("option")).to_have_count(7)
        storage_id = self.page.evaluate("window.editedConfig.view_storage_id")
        editor.get_by_label("Title").fill("Temperatures")
        editor.get_by_label("Initial device").select_option("dhw")
        editor.get_by_label("Initial time window").select_option("last_3_hours")
        config = self.page.evaluate("window.editedConfig")
        self.assertEqual(config["title"], "Temperatures")
        self.assertEqual(config["device_id"], "dhw")
        self.assertEqual(config["time_window"], "last_3_hours")
        self.assertEqual(config["view_storage_id"], storage_id)
        self.assertEqual(config["type"], "custom:keba-heat-pump-modbus-card")
        self.page.evaluate("config => dashboardCard.setConfig(config)", config)
        expect(self.page.get_by_label("Device", exact=True)).to_have_value("dhw")
        for width in [280, 320, 420, 700]:
            self.page.evaluate("width => dashboardCard.style.width = `${width}px`", width)
            self.assertFalse(self.page.locator(".content").evaluate("node => node.scrollWidth > node.clientWidth + 1"))
            self.assertFalse(self.page.locator(".view-tabs").evaluate("node => node.scrollWidth > node.clientWidth + 1"))
        self.page.evaluate("document.body.style.setProperty('--card-background-color', '#18242b')")
        expect(self.page.get_by_label("Device", exact=True)).to_be_visible()


if __name__ == "__main__":
    unittest.main()
