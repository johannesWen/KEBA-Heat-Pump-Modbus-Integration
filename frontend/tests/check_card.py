"""Browser regressions against the built card with a simulated Home Assistant.

Run after npm run build:
    uv run --with playwright==1.58.0 python frontend/tests/check_card.py
"""
from pathlib import Path
import unittest

from playwright.sync_api import sync_playwright, expect

BUNDLE = Path(__file__).resolve().parents[2] / "custom_components/keba_heat_pump_modbus/static/keba-heat-pump-modbus-card.js"
FIXTURE = """<!doctype html>
<html><head><style>
body { margin: 20px; background: #f2f4f5; font-family: sans-serif;
--primary-color: #007b83; --primary-text-color: #202c32;
--secondary-text-color: #596b75; --text-primary-color: #fff;
--card-background-color: #fff; --secondary-background-color: #edf2f3;
--divider-color: #d8e0e3; }
ha-card { display: block; background: var(--card-background-color); border-radius: 16px; }
keba-heat-pump-modbus-card { display: block; width: 420px; color: var(--primary-text-color); }
ha-icon { display: inline-block; width: 20px; height: 20px; }
</style></head><body><script type="module">
import '/card.js';
// Minimal HA shell: the real frontend supplies these custom elements.
customElements.define('ha-card', class extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: 'open'}).innerHTML = `<style>:host {
      display: block; background: var(--card-background-color); border-radius: 16px;
    }</style><slot></slot>`;
  }
});
const entityId = 'sensor.renamed_schedules';
const plans = {};
window.calls = [];
window.failNext = false;
window.holdNext = false;
const card = document.createElement('keba-heat-pump-modbus-card');
window.card = card;
card.setConfig({ view: 'schedule' });
const hass = {
  config: { time_zone: 'Europe/Vienna' },
  states: {},
  async callService(domain, service, data) {
    window.calls.push({domain, service, data});
    if (window.holdNext) {
      window.holdNext = false;
      await new Promise(resolve => { window.releaseSave = resolve; });
    }
    if (window.failNext) { window.failNext = false; throw new Error('Connection lost'); }
    const plan = plans[data.plan_id];
    if (service === 'add_schedule') {
      const id = [1,2,3,4,5].find(id => !plans[id]);
      plans[id] = { name: '', enabled: true, off_mode: 'Hot Water', on_mode: 'Auto Heat', on_hours: [] };
    } else if (service === 'remove_schedule') { delete plans[data.plan_id]; }
    else if (service === 'set_schedule_hour') {
      plan.on_hours = data.on ? [...plan.on_hours, data.hour] : plan.on_hours.filter(h => h !== data.hour);
    } else {
      const field = service.replace('set_schedule_', '');
      plan[field] = data[field];
    }
    window.publish();
  }
};
window.publish = () => {
  hass.states = {
    [entityId]: { entity_id: entityId, state: String(Object.keys(plans).length), attributes: { keba_key: 'schedules', plans: structuredClone(plans) } },
    'select.system': { entity_id: 'select.system', state: 'Hot Water', attributes: { keba_key: 'operating_mode', options: ['Standby', 'Hot Water', 'Auto Heat', 'Full Auto'] } },
    'binary_sensor.active': { entity_id: 'binary_sensor.active', state: Object.values(plans).some(p => p.enabled) ? 'on' : 'off', attributes: { keba_key: 'schedule_active' } }
  };
  card.hass = {...hass};
};
window.publish();
document.body.append(card);
</script></body></html>"""


class CardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 1000, "height": 1100})
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.route("http://keba.test/card.js", lambda route: route.fulfill(path=str(BUNDLE), content_type="text/javascript"))
        self.page.route("http://keba.test/", lambda route: route.fulfill(body=FIXTURE, content_type="text/html"))
        self.page.goto("http://keba.test/")
        self.add = self.page.get_by_role("button", name="Add plan", exact=True)
        expect(self.add).to_be_visible()

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def test_add_plan_saving_state_and_renamed_entity(self):
        self.page.evaluate("window.holdNext = true")
        self.add.click()
        expect(self.add).to_be_disabled()
        expect(self.page.get_by_text("Saving…", exact=True)).to_be_visible()
        self.page.evaluate("window.releaseSave()")
        expect(self.page.get_by_role("textbox", name="Name for plan 1")).to_be_visible()
        expect(self.add).to_be_enabled()
        self.assertEqual(self.page.evaluate("window.calls"), [{
            "domain": "keba_heat_pump_modbus", "service": "add_schedule",
            "data": {"entity_id": "sensor.renamed_schedules"},
        }])

    def test_failed_add_shows_error_and_can_retry(self):
        self.page.evaluate("window.failNext = true")
        self.add.click()
        expect(self.page.get_by_role("alert")).to_contain_text("Connection lost")
        expect(self.add).to_be_enabled()
        self.add.click()
        expect(self.page.get_by_role("alert")).to_have_count(0)
        expect(self.page.get_by_role("textbox", name="Name for plan 1")).to_be_visible()

    def test_plan_edits_hours_and_failed_toggle(self):
        self.add.click()
        name = self.page.get_by_role("textbox", name="Name for plan 1")
        name.fill("Morning")
        name.press("Tab")
        expect(self.page.get_by_role("switch", name="Enable Morning")).to_be_visible()
        self.page.get_by_label("On mode During selected hours").select_option("Full Auto")
        hour = self.page.get_by_role("button", name="07:00–08:00", exact=True)
        hour.click()
        expect(hour).to_have_attribute("aria-pressed", "true")
        expect(self.page.locator(".hour-summary")).to_have_text("07:00–08:00")
        switch = self.page.get_by_role("switch", name="Enable Morning")
        self.page.evaluate("window.failNext = true")
        switch.click()
        expect(self.page.get_by_role("alert")).to_be_visible()
        expect(switch).to_be_checked()
        switch.click()
        expect(switch).not_to_be_checked()
        self.page.get_by_role("button", name="Remove Morning").click()
        expect(self.page.get_by_text("Set your daily rhythm")).to_be_visible()

    def test_limit_and_keyed_plan_removal(self):
        for _ in range(5):
            self.add.click()
        expect(self.add).to_be_disabled()
        self.page.get_by_role("button", name="Remove Plan 1", exact=True).click()
        expect(self.add).to_be_enabled()
        expect(self.page.get_by_role("textbox", name="Name for plan 2")).to_have_value("Plan 2")
        self.add.click()
        expect(self.page.get_by_role("textbox", name="Name for plan 1")).to_be_visible()

    def test_narrow_card_on_desktop_and_dark_theme(self):
        self.add.click()
        for width in [280, 320, 420, 700]:
            self.page.locator("keba-heat-pump-modbus-card").evaluate("(card, width) => card.style.width = `${width}px`", width)
            overflow = self.page.locator("keba-heat-pump-modbus-card").evaluate("""card => {
              const nodes = [...card.shadowRoot.querySelectorAll('.plan-card, .plan-modes, .hour-grid')];
              return nodes.some(node => node.scrollWidth > node.clientWidth + 1);
            }""")
            self.assertFalse(overflow, f"Overflow at {width}px")
            self.assertGreaterEqual(self.page.locator(".hour-chip").first.bounding_box()["height"], 40)
        self.page.evaluate("""() => {
          card.style.width = '320px';
          document.body.style.setProperty('--card-background-color', '#18242b');
          document.body.style.setProperty('--primary-text-color', '#e5eff3');
          document.body.style.setProperty('--secondary-text-color', '#acbdc5');
          document.body.style.setProperty('--secondary-background-color', '#26343c');
        }""")
        expect(self.page.get_by_role("textbox", name="Name for plan 1")).to_be_visible()

    def test_unavailable_sensor_and_view_switch(self):
        self.page.get_by_role("button", name="Settings", exact=True).click()
        expect(self.add).to_have_count(0)
        self.page.get_by_role("button", name="Schedule", exact=True).click()
        expect(self.add).to_be_visible()
        self.page.evaluate("card.hass = {...card.hass, states: {}}")
        expect(self.page.get_by_text("Schedules unavailable", exact=True)).to_be_visible()
        expect(self.add).to_have_count(0)


if __name__ == "__main__":
    unittest.main()
