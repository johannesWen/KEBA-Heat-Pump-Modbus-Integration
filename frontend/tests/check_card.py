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
window.plans = plans;
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
      plans[id] = { name: '', enabled: true, off_mode: 'Hot Water', on_mode: 'Auto Heat', on_hours: [], weekdays: [], hot_water_enabled: true, hot_water_off_mode: 'Off', hot_water_on_mode: 'On', hot_water_on_hours: [] };
    } else if (service === 'remove_schedule') { delete plans[data.plan_id]; }
    else if (service === 'set_schedule_hour') {
      plan.on_hours = data.on ? [...new Set([...plan.on_hours, data.hour])] : plan.on_hours.filter(h => h !== data.hour);
      if ('hot_water_on' in data) {
        const hours = plan.hot_water_on_hours || [];
        plan.hot_water_on_hours = data.hot_water_on ? [...new Set([...hours, data.hour])] : hours.filter(h => h !== data.hour);
      }
    } else if (service === 'set_schedule_weekday') {
      plan.weekdays = data.selected
        ? [...new Set([...plan.weekdays, data.weekday])].sort((a, b) => a - b)
        : plan.weekdays.filter(day => day !== data.weekday);
    } else if (service === 'set_schedule_hot_water_enabled') {
      plan.hot_water_enabled = data.enabled;
    } else if (service === 'set_schedule_hot_water_off_mode') {
      plan.hot_water_off_mode = data.off_mode;
    } else if (service === 'set_schedule_hot_water_on_mode') {
      plan.hot_water_on_mode = data.on_mode;
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
    'select.hot_water': { entity_id: 'select.hot_water', state: 'Auto', attributes: { keba_key: 'operating_mode_dhw_tank1', options: ['Off', 'Auto', 'On', 'Heat Up'] } },
    'sensor.scheduled': { entity_id: 'sensor.scheduled', state: 'Auto Heat', attributes: { keba_key: 'scheduled_mode', hot_water_mode: 'On' } },
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

    def test_prefix_is_internal_and_editor_removes_legacy_setting(self):
        config = {"view": "schedule", "title": "My heat pump", "entity_prefix": "old_custom_prefix"}
        self.page.evaluate("config => card.setConfig(config)", config)
        self.assertNotIn("entity_prefix", self.page.evaluate("card.config"))
        self.assertNotIn("entity_prefix", self.page.evaluate("card.constructor.getStubConfig()"))
        self.add.click()
        self.assertEqual(self.page.evaluate("window.calls.at(-1).data.entity_id"), "sensor.renamed_schedules")
        self.assertEqual(self.page.evaluate("""() => {
          const isolated = document.createElement('keba-heat-pump-modbus-card');
          isolated.setConfig({entity_prefix: 'old_custom_prefix'});
          return isolated._eid('select', 'operating_mode');
        }"""), "select.keba_heat_pump_modbus_operating_mode")
        self.page.evaluate("""config => {
          const editor = card.constructor.getConfigElement();
          editor.setConfig(config);
          editor.hass = card.hass;
          editor.addEventListener('config-changed', event => {
            window.editedConfig = event.detail.config;
            editor.setConfig(event.detail.config);
          });
          document.body.append(editor);
        }""", config)
        editor = self.page.locator("keba-heat-pump-modbus-card-editor")
        expect(editor.get_by_label("Entity prefix")).to_have_count(0)
        expect(editor.get_by_label("Title")).to_have_value("My heat pump")
        editor.get_by_label("Title").fill("Updated title")
        self.assertEqual(self.page.evaluate("window.editedConfig"), {"view": "schedule", "title": "Updated title"})
        editor.get_by_role("button", name="Settings", exact=True).click()
        self.assertEqual(self.page.evaluate("window.editedConfig"), {"view": "settings", "title": "Updated title"})

    def test_failed_add_shows_error_and_can_retry(self):
        self.page.evaluate("window.failNext = true")
        self.add.click()
        expect(self.page.get_by_role("alert")).to_contain_text("Connection lost")
        expect(self.add).to_be_enabled()
        self.add.click()
        expect(self.page.get_by_role("alert")).to_have_count(0)
        expect(self.page.get_by_role("textbox", name="Name for plan 1")).to_be_visible()

    def test_weekday_selection_and_daily_default(self):
        self.add.click()
        days = self.page.get_by_role("group", name="Active weekdays")
        expect(days.get_by_role("button")).to_have_count(7)
        expect(self.page.get_by_text("No days selected means every day.")).to_be_visible()
        expect(days.get_by_role("button", name="Monday")).to_have_attribute("aria-pressed", "false")

        days.get_by_role("button", name="Monday").click()
        expect(days.get_by_role("button", name="Monday")).to_have_attribute("aria-pressed", "true")
        expect(self.page.get_by_text("Only selected days run this plan.")).to_be_visible()
        days.get_by_role("button", name="Wednesday").click()
        expect(days.get_by_role("button", name="Wednesday")).to_have_attribute("aria-pressed", "true")
        self.assertEqual(self.page.evaluate("window.calls.filter(call => call.service === 'set_schedule_weekday')"), [
            {"domain": "keba_heat_pump_modbus", "service": "set_schedule_weekday",
             "data": {"entity_id": "sensor.renamed_schedules", "plan_id": 1, "weekday": 0, "selected": True}},
            {"domain": "keba_heat_pump_modbus", "service": "set_schedule_weekday",
             "data": {"entity_id": "sensor.renamed_schedules", "plan_id": 1, "weekday": 2, "selected": True}},
        ])
        self.page.evaluate("window.publish()")
        expect(days.get_by_role("button", name="Wednesday")).to_have_attribute("aria-pressed", "true")
        days.get_by_role("button", name="Monday").click()
        days.get_by_role("button", name="Wednesday").click()
        expect(self.page.get_by_text("No days selected means every day.")).to_be_visible()
        expect(self.page.locator(".weekday-section .muted")).to_have_text("Every day")

        self.add.click()
        expect(self.page.get_by_role("tabpanel").get_by_role("button", name="Monday")).to_have_attribute("aria-pressed", "false")
        self.page.get_by_role("tab", name="Plan 1: Plan 1").click()
        expect(self.page.locator(".weekday-section .muted")).to_have_text("Every day")

    def test_rename_survives_state_refresh_before_save(self):
        self.add.click()
        name = self.page.get_by_role("textbox", name="Name for plan 1")
        name.fill("Evening comfort")
        # Home Assistant refreshes the card while the user is still typing.
        self.page.evaluate("window.publish()")
        expect(name).to_have_value("Evening comfort")
        name.press("Tab")
        expect(self.page.get_by_role("textbox", name="Name for plan 1")).to_have_value("Evening comfort")
        name_calls = self.page.evaluate("window.calls.filter(call => call.service === 'set_schedule_name')")
        self.assertEqual(name_calls, [{
            "domain": "keba_heat_pump_modbus", "service": "set_schedule_name",
            "data": {
                "entity_id": "sensor.renamed_schedules",
                "plan_id": 1,
                "name": "Evening comfort",
            },
        }])
        self.page.evaluate("window.publish()")
        expect(self.page.get_by_role("textbox", name="Name for plan 1")).to_have_value("Evening comfort")

    def test_plan_edits_hours_and_failed_toggle(self):
        self.add.click()
        name = self.page.get_by_role("textbox", name="Name for plan 1")
        name.fill("Morning")
        name.press("Tab")
        expect(self.page.get_by_role("switch", name="Enable Morning")).to_be_visible()
        self.page.get_by_label("Heating On mode", exact=True).select_option("Full Auto")
        hour = self.page.locator(".hour-chip").nth(7)
        hour.click()
        expect(hour).to_have_attribute("aria-pressed", "true")
        expect(self.page.locator(".hour-summary").first).to_have_text("Heating: 07:00–08:00")
        switch = self.page.get_by_role("switch", name="Enable Morning")
        self.page.evaluate("window.failNext = true")
        switch.click()
        expect(self.page.get_by_role("alert")).to_be_visible()
        expect(switch).to_be_checked()
        switch.click()
        expect(switch).not_to_be_checked()
        self.page.get_by_role("button", name="Remove Morning").click()
        expect(self.page.get_by_text("Set your daily rhythm", exact=True)).to_be_visible()

    def test_hour_cycle_colors_atomic_payloads_and_keyboard(self):
        self.add.click()
        hour = self.page.locator(".hour-chip").nth(7)
        for mode, heating, hot_water, color in [
            ("heat", True, False, "rgb(21, 101, 192)"),
            ("hot-water", False, True, "rgb(198, 40, 40)"),
            ("both", True, True, None),
            ("off", False, False, None),
        ]:
            hour.click()
            expect(hour).to_have_class(f"hour-chip {mode}")
            expect(hour).to_have_attribute("aria-label", f"07:00–08:00: heating {'on' if heating else 'off'}, hot water {'on' if hot_water else 'off'}")
            self.assertEqual(self.page.evaluate("window.calls.at(-1)"), {
                "domain": "keba_heat_pump_modbus", "service": "set_schedule_hour",
                "data": {"entity_id": "sensor.renamed_schedules", "plan_id": 1,
                         "hour": 7, "on": heating, "hot_water_on": hot_water},
            })
            self.assertEqual(self.page.evaluate("window.plans[1].on_hours"), [7] if heating else [])
            self.assertEqual(self.page.evaluate("window.plans[1].hot_water_on_hours"), [7] if hot_water else [])
            if color:
                self.assertEqual(hour.evaluate("node => getComputedStyle(node).backgroundColor"), color)
            if mode == "both":
                self.assertEqual(hour.evaluate("node => getComputedStyle(node).backgroundImage"),
                                 "linear-gradient(to right, rgb(21, 101, 192) 50%, rgb(198, 40, 40) 50%)")
        self.assertEqual(self.page.evaluate("window.calls.filter(c => c.service === 'set_schedule_hour').length"), 4)
        hour.focus()
        hour.press("Enter")
        expect(hour).to_have_class("hour-chip heat")
        hour.press("Space")
        expect(hour).to_have_class("hour-chip hot-water")
        expect(self.page.locator(".hour-summary").nth(1)).to_have_text("Hot water: 07:00–08:00")
        self.page.evaluate("window.publish()")
        expect(hour).to_have_class("hour-chip hot-water")

    def test_hot_water_modes_and_disable_retains_selections(self):
        self.add.click()
        switch = self.page.get_by_role("switch", name="Schedule hot water")
        expect(switch).to_be_checked()
        off = self.page.get_by_label("Hot water Off mode", exact=True)
        on = self.page.get_by_label("Hot water On mode", exact=True)
        expect(off).to_have_value("Off")
        expect(on).to_have_value("On")
        self.assertEqual(on.locator("option").all_text_contents(), ["Off", "Auto", "On", "Heat Up"])
        off.select_option("Auto")
        on.select_option("Heat Up")
        self.assertEqual(self.page.evaluate("window.calls.slice(-2).map(c => [c.service, c.data])"), [
            ["set_schedule_hot_water_off_mode", {"entity_id": "sensor.renamed_schedules", "plan_id": 1, "off_mode": "Auto"}],
            ["set_schedule_hot_water_on_mode", {"entity_id": "sensor.renamed_schedules", "plan_id": 1, "on_mode": "Heat Up"}],
        ])
        hour = self.page.locator(".hour-chip").nth(8)
        hour.click()
        hour.click()
        expect(hour).to_have_class("hour-chip hot-water")
        self.page.evaluate("window.failNext = true")
        switch.click()
        expect(switch).to_be_checked()
        expect(self.page.get_by_role("alert")).to_contain_text("Connection lost")
        switch.click()
        expect(switch).not_to_be_checked()
        expect(hour).to_have_class("hour-chip off")
        expect(on).to_have_count(0)
        hour.click()
        expect(hour).to_have_class("hour-chip heat")
        self.assertNotIn("hot_water_on", self.page.evaluate("window.calls.at(-1).data"))
        self.assertEqual(self.page.evaluate("window.plans[1].hot_water_on_hours"), [8])
        switch.click()
        expect(hour).to_have_class("hour-chip both")
        expect(off).to_have_value("Auto")
        expect(on).to_have_value("Heat Up")

    def test_failed_hour_cycle_retains_state_and_blocks_pending_clicks(self):
        self.add.click()
        hour = self.page.locator(".hour-chip").nth(9)
        hour.click()
        self.page.evaluate("window.failNext = true")
        hour.click()
        expect(self.page.get_by_role("alert")).to_contain_text("Connection lost")
        expect(hour).to_have_class("hour-chip heat")
        self.page.evaluate("window.holdNext = true")
        hour.click()
        expect(hour).to_be_disabled()
        expect(self.page.get_by_text("Saving…", exact=True)).to_be_visible()
        self.page.evaluate("window.releaseSave()")
        expect(hour).to_be_enabled()
        expect(hour).to_have_class("hour-chip hot-water")

    def test_legacy_plan_opt_in_and_unavailable_hot_water_options(self):
        self.page.evaluate("""() => {
          window.plans[1] = { name: 'Legacy', enabled: true, off_mode: 'Hot Water',
            on_mode: 'Auto Heat', on_hours: [7], weekdays: [] };
          window.publish();
        }""")
        switch = self.page.get_by_role("switch", name="Schedule hot water")
        expect(switch).not_to_be_checked()
        hour = self.page.locator(".hour-chip").nth(7)
        expect(hour).to_have_attribute("aria-label", "07:00–08:00: heating on, hot water unmanaged")
        hour.click()
        expect(hour).to_have_class("hour-chip off")
        self.assertNotIn("hot_water_on", self.page.evaluate("window.calls.at(-1).data"))
        switch.click()
        expect(self.page.get_by_label("Hot water Off mode", exact=True)).to_have_value("Off")
        expect(self.page.get_by_label("Hot water On mode", exact=True)).to_have_value("On")
        self.page.get_by_label("Hot water On mode", exact=True).select_option("Heat Up")
        self.page.evaluate("""() => {
          const states = {...card.hass.states};
          delete states['select.hot_water'];
          card.hass = {...card.hass, states};
        }""")
        expect(self.page.get_by_label("Hot water On mode", exact=True)).to_have_value("Heat Up")
        expect(self.page.get_by_label("Hot water Off mode", exact=True)).to_have_value("Off")

    def test_schedule_status_shows_both_functions(self):
        expect(self.page.get_by_text("Heating scheduled: Auto Heat", exact=True)).to_be_visible()
        expect(self.page.get_by_text("Heating current: Hot Water", exact=True)).to_be_visible()
        expect(self.page.get_by_text("Hot water scheduled: On", exact=True)).to_be_visible()
        expect(self.page.get_by_text("Hot water current: Auto", exact=True)).to_be_visible()

    def test_limit_and_keyed_plan_removal(self):
        for _ in range(5):
            self.add.click()
        expect(self.add).to_be_disabled()
        self.page.get_by_role("tab", name="Plan 1: Plan 1").click()
        self.page.get_by_role("button", name="Remove Plan 1", exact=True).click()
        expect(self.add).to_be_enabled()
        expect(self.page.get_by_role("tab", name="Plan 1: Plan 1")).to_have_count(0)
        expect(self.page.get_by_role("textbox", name="Name for plan 2")).to_have_value("Plan 2")
        self.add.click()
        expect(self.page.get_by_role("textbox", name="Name for plan 1")).to_be_visible()

    def test_plan_tabs_switch_and_preserve_selection(self):
        self.add.click()
        self.add.click()
        expect(self.page.get_by_role("tab")).to_have_count(2)
        expect(self.page.get_by_role("tab", name="Plan 2: Plan 2")).to_have_attribute("aria-selected", "true")
        expect(self.page.get_by_role("tabpanel")).to_have_count(1)
        expect(self.page.get_by_role("textbox", name="Name for plan 1")).to_have_count(0)

        second_name = self.page.get_by_role("textbox", name="Name for plan 2")
        second_name.fill("Night")
        second_name.press("Tab")
        expect(self.page.get_by_role("tab", name="Plan 2: Night")).to_be_visible()
        self.page.get_by_role("tab", name="Plan 1: Plan 1").click()
        expect(self.page.get_by_role("textbox", name="Name for plan 1")).to_be_visible()
        self.page.evaluate("window.publish()")
        expect(self.page.get_by_role("tab", name="Plan 1: Plan 1")).to_have_attribute("aria-selected", "true")
        expect(self.page.get_by_role("textbox", name="Name for plan 2")).to_have_count(0)

        first_tab = self.page.get_by_role("tab", name="Plan 1: Plan 1")
        first_tab.focus()
        first_tab.press("ArrowRight")
        expect(self.page.get_by_role("tab", name="Plan 2: Night")).to_have_attribute("aria-selected", "true")
        expect(self.page.get_by_role("textbox", name="Name for plan 2")).to_have_value("Night")
        self.page.get_by_role("button", name="Remove Night").click()
        expect(self.page.get_by_role("tab")).to_have_count(1)
        expect(self.page.get_by_role("textbox", name="Name for plan 1")).to_be_visible()

    def test_narrow_card_on_desktop_and_dark_theme(self):
        self.add.click()
        for width in [280, 320, 420, 700]:
            self.page.locator("keba-heat-pump-modbus-card").evaluate("(card, width) => card.style.width = `${width}px`", width)
            overflow = self.page.locator("keba-heat-pump-modbus-card").evaluate("""card => {
              const nodes = [...card.shadowRoot.querySelectorAll('.plan-card, .plan-modes, .hour-grid, .weekday-grid')];
              return nodes.some(node => node.scrollWidth > node.clientWidth + 1);
            }""")
            self.assertFalse(overflow, f"Overflow at {width}px")
            self.assertGreaterEqual(self.page.locator(".hour-chip").first.bounding_box()["height"], 32)
            columns = self.page.locator(".hour-grid").evaluate(
                "node => getComputedStyle(node).gridTemplateColumns.split(' ').length"
            )
            self.assertEqual(columns, 6 if width <= 350 else 12 if width >= 520 else 8)
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
