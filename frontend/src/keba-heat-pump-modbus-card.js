import { LitElement, html, css, nothing } from 'lit';
import { CARD_VERSION } from 'virtual:integration-version';

const CARD_TAG = 'keba-heat-pump-modbus-card';
const EDITOR_TAG = 'keba-heat-pump-modbus-card-editor';
const DEFAULT_PREFIX = 'keba_heat_pump_modbus';

const SECTIONS = [
  { key: 'system', label: 'System', icon: 'mdi:cog' },
  { key: 'heat_pump', label: 'Heat Pump', icon: 'mdi:heat-pump' },
  { key: 'dhw', label: 'Hot Water', icon: 'mdi:water-boiler' },
];

class KebaHeatPumpModbusCard extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      config: { type: Object },
    };
  }

  constructor() {
    super();
    this.config = {};
    this._entityAliases = {};
  }

  setConfig(config) {
    this.config = {
      entity_prefix: DEFAULT_PREFIX,
      title: 'KEBA Heat Pump',
      ...config,
    };
  }

  getCardSize() {
    return 10;
  }

  static getConfigElement() {
    return document.createElement(EDITOR_TAG);
  }

  static getStubConfig() {
    return { entity_prefix: DEFAULT_PREFIX, title: 'KEBA Heat Pump' };
  }

  static _escapeRegExp(text) {
    return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  _eid(domain, key) {
    const states = this.hass?.states;
    const exact = `${domain}.${this.config.entity_prefix}_${key}`;
    if (!states) return exact;

    // Primary: the integration exposes the register unique_id as the
    // "keba_key" state attribute. This is the only reliable identifier when
    // Home Assistant generates entity ids from device/entity names.
    const byKey = this._findEntityByKebaKey(states, domain, key);
    if (byKey) return byKey;

    if (states[exact]) return exact;

    const cached = this._entityAliases[exact];
    if (cached !== undefined) {
      if (states[cached]) return cached;
      delete this._entityAliases[exact];
    }

    // The integration creates entities with a host-derived config-entry id
    // (e.g. "keba_heat_pump_modbus_192_168_1_100_operating_mode") while the
    // card defaults to the plain domain prefix. Auto-detect the real prefix by
    // looking for entities that end with the expected key.
    const auto = this._autoResolveEntityId(states, domain, key);
    if (auto) {
      this._entityAliases[exact] = auto;
      return auto;
    }

    const wanted = KebaHeatPumpModbusCard._escapeRegExp(
      `${this.config.entity_prefix}_${key}`,
    );
    const reStrict = new RegExp(`^${domain}\\.${wanted}(?:_\\d+)?$`);
    const reLoose = new RegExp(`^${domain}\\..*${wanted}(?:_\\d+)?$`);

    let best = null;
    for (const entityId of Object.keys(states)) {
      const layer = reStrict.test(entityId) ? 0 : reLoose.test(entityId) ? 1 : null;
      if (layer === null) continue;
      if (
        best === null ||
        layer < best.layer ||
        (layer === best.layer &&
          (entityId.length < best.entityId.length ||
            (entityId.length === best.entityId.length && entityId < best.entityId)))
      ) {
        best = { entityId, layer };
      }
    }
    if (best) {
      this._entityAliases[exact] = best.entityId;
      return best.entityId;
    }
    return exact;
  }

  _findEntityByKebaKey(states, domain, key) {
    const prefix = `${domain}.`;
    const candidates = Object.entries(states).filter(
      ([entityId, state]) =>
        entityId.startsWith(prefix) && state?.attributes?.keba_key === key,
    );
    if (candidates.length === 0) return null;
    if (candidates.length === 1) return candidates[0][0];

    candidates.sort((a, b) => {
      const aHas = a[0].includes(this.config.entity_prefix) ? 0 : 1;
      const bHas = b[0].includes(this.config.entity_prefix) ? 0 : 1;
      if (aHas !== bHas) return aHas - bHas;
      return a[0].length - b[0].length || a[0].localeCompare(b[0]);
    });
    return candidates[0][0];
  }

  _autoResolveEntityId(states, domain, key) {
    const suffix = `_${key}`;
    const domainPrefix = `${domain}.`;
    const candidates = Object.keys(states).filter(
      (entityId) =>
        entityId.startsWith(domainPrefix) &&
        entityId.endsWith(suffix) &&
        entityId.length > domainPrefix.length + suffix.length,
    );
    if (candidates.length === 0) return null;

    // Prefer entities whose id contains the integration domain so we do not
    // accidentally pick an unrelated entity that happens to share the key.
    const branded = candidates.filter((entityId) =>
      entityId.includes(DEFAULT_PREFIX),
    );
    const pool = branded.length > 0 ? branded : candidates;

    // If multiple instances exist, pick the shortest id as the most canonical
    // one. The user can override via the entity_prefix card option.
    pool.sort((a, b) => a.length - b.length || a.localeCompare(b));
    return pool[0];
  }

  _state(domain, key) {
    return this.hass?.states?.[this._eid(domain, key)];
  }

  _val(domain, key) {
    return this._state(domain, key)?.state;
  }

  _callService(domain, service, data) {
    let result;
    try {
      result = this.hass.callService(domain, service, data);
    } catch (err) {
      result = Promise.reject(err);
    }
    return Promise.resolve(result).catch((err) => {
      console.error(
        `[keba-heat-pump-modbus-card] service ${domain}.${service} failed:`,
        err,
      );
    });
  }

  _setNumber(key, value) {
    this._callService('number', 'set_value', {
      entity_id: this._eid('number', key),
      value: Number(value),
    });
  }

  _selectOption(key, option) {
    this._callService('select', 'select_option', {
      entity_id: this._eid('select', key),
      option,
    });
  }

  _renderSection({ label, icon }, content) {
    return html`
      <div class="section">
        <div class="section-header">
          <ha-icon .icon=${icon}></ha-icon>
          <span>${label}</span>
        </div>
        <div class="section-content">${content}</div>
      </div>
    `;
  }

  _renderStatusChip(icon, label, value) {
    if (value === undefined || value === null || value === 'unavailable' || value === 'unknown') {
      return nothing;
    }
    return html`
      <div class="status-chip">
        <ha-icon .icon=${icon}></ha-icon>
        <span>${label}: ${value}</span>
      </div>
    `;
  }

  _renderSelect(label, key) {
    const state = this._state('select', key);
    if (!state) return nothing;
    const options = state.attributes?.options || [];
    return html`
      <div class="control-row">
        <span class="control-label">${label}</span>
        <select
          class="ha-select"
          .value=${state.state || ''}
          @change=${(e) => this._selectOption(key, e.target.value)}
        >
          ${options.map(
            (opt) => html`<option value=${opt} ?selected=${opt === state.state}>${opt}</option>`,
          )}
        </select>
      </div>
    `;
  }

  _renderSlider(label, key, unit = '') {
    const state = this._state('number', key);
    if (!state) return nothing;
    const value = parseFloat(state.state);
    const { min = 0, max = 100, step = 0.5 } = state.attributes;
    return html`
      <div class="control-row slider-row">
        <span class="control-label">${label}</span>
        <div class="slider-wrap">
          <input
            type="range"
            min=${min}
            max=${max}
            step=${step}
            .value=${String(value)}
            @change=${(e) => this._setNumber(key, e.target.value)}
          />
          <span class="slider-value">${state.state}${unit}</span>
        </div>
      </div>
    `;
  }

  _renderSystemSection() {
    return this._renderSection(
      SECTIONS.find((s) => s.key === 'system'),
      html`
        ${this._renderSelect('Operating Mode', 'operating_mode')}
        ${this._renderStatusChip(
          'mdi:sun-thermometer',
          'Exterior',
          this._val('sensor', 'exterior_temperature'),
        )}
      `,
    );
  }

  _renderHeatPumpSection() {
    return this._renderSection(
      SECTIONS.find((s) => s.key === 'heat_pump'),
      html`
        ${this._renderSelect('Operating Mode', 'operating_mode_heat_pump')}
        <div class="status-row">
          ${this._renderStatusChip(
            'mdi:heat-pump',
            'State',
            this._val('sensor', 'heat_pump_state'),
          )}
          ${this._renderStatusChip(
            'mdi:thermometer-chevron-up',
            'Flow',
            this._val('sensor', 'flow_temperature'),
          )}
          ${this._renderStatusChip(
            'mdi:lightning-bolt',
            'Power',
            this._val('sensor', 'electrical_power_consumption'),
          )}
        </div>
      `,
    );
  }

  _renderDhwSection() {
    const modeState = this._state('select', 'operating_mode_dhw_tank1');
    const topTempState = this._state('number', 'temperature_top_set_dhw_tank1');
    const whState =
      !modeState || !topTempState ? this._findDhwWaterHeater() : null;

    return this._renderSection(
      SECTIONS.find((s) => s.key === 'dhw'),
      html`
        ${modeState
          ? this._renderSelect('Operating Mode', 'operating_mode_dhw_tank1')
          : whState
            ? this._renderDhwModeFromWaterHeater(whState)
            : nothing}
        ${topTempState
          ? this._renderSlider('Top Set Temperature', 'temperature_top_set_dhw_tank1', '°C')
          : whState
            ? this._renderDhwTopTempFromWaterHeater(whState)
            : nothing}
        ${this._renderSlider('Reduced Set Temperature', 'reduced_set_temp_dhw_tank1', '°C')}
        ${this._renderSlider(
          'Excess Energy Target',
          'excess_energy_target_temp_dhw_tank1',
          '°C',
        )}
        ${this._renderStatusChip(
          'mdi:thermometer-water',
          'Top',
          this._val('sensor', 'temperature_top_dhw_tank1'),
        )}
      `,
    );
  }

  _findDhwWaterHeater() {
    const states = this.hass?.states;
    if (!states) return null;
    const targetKey = 'operating_mode_dhw_tank1_water_heater';
    const candidates = Object.entries(states).filter(
      ([entityId, state]) =>
        entityId.startsWith('water_heater.') &&
        state?.attributes?.keba_key === targetKey,
    );
    if (candidates.length === 0) return null;
    candidates.sort((a, b) => a[0].length - b[0].length || a[0].localeCompare(b[0]));
    return states[candidates[0][0]];
  }

  _renderDhwModeFromWaterHeater(state) {
    const current = state.attributes?.operation_mode || state.state || '';
    const options = state.attributes?.operation_list || [];
    return html`
      <div class="control-row">
        <span class="control-label">Operating Mode</span>
        <select
          class="ha-select"
          .value=${current}
          @change=${(e) =>
            this._callService('water_heater', 'set_operation_mode', {
              entity_id: state.entity_id,
              operation_mode: e.target.value,
            })}
        >
          ${options.map(
            (opt) =>
              html`<option value=${opt} ?selected=${opt === current}>${opt}</option>`,
          )}
        </select>
      </div>
    `;
  }

  _renderDhwTopTempFromWaterHeater(state) {
    const temp = state.attributes?.temperature;
    if (temp === undefined || temp === null) return nothing;
    const min = state.attributes?.min_temp ?? 0;
    const max = state.attributes?.max_temp ?? 100;
    const step = 0.5;
    return html`
      <div class="control-row slider-row">
        <span class="control-label">Top Set Temperature</span>
        <div class="slider-wrap">
          <input
            type="range"
            min=${min}
            max=${max}
            step=${step}
            .value=${String(temp)}
            @change=${(e) =>
              this._callService('water_heater', 'set_temperature', {
                entity_id: state.entity_id,
                temperature: Number(e.target.value),
              })}
          />
          <span class="slider-value">${temp}°C</span>
        </div>
      </div>
    `;
  }

  _renderCircuitSection(circuit) {
    const modeKey = `operating_mode_circuit_${circuit}`;
    const setTempKey = `room_set_temperature_circuit_${circuit}`;
    const reducedTempKey = `room_set_temperature_reduced_circuit_${circuit}`;
    const currentTempKey = `actual_room_temperature_circuit_${circuit}`;

    const hasAny =
      this._state('select', modeKey) ||
      this._state('number', setTempKey) ||
      this._state('number', reducedTempKey);
    if (!hasAny) return nothing;

    return this._renderSection(
      { label: `Heating Circuit ${circuit}`, icon: 'mdi:radiator' },
      html`
        ${this._renderSelect('Operating Mode', modeKey)}
        ${this._renderSlider('Room Set Temperature', setTempKey, '°C')}
        ${this._renderSlider('Reduced Set Temperature', reducedTempKey, '°C')}
        ${this._renderStatusChip(
          'mdi:home-thermometer',
          'Room',
          this._val('sensor', currentTempKey),
        )}
      `,
    );
  }

  render() {
    if (!this.hass) {
      return html`<div class="card">Loading...</div>`;
    }

    return html`
      <ha-card class="card">
        <div class="card-header">
          <span class="title">${this.config.title}</span>
          <span class="version">v${CARD_VERSION}</span>
        </div>
        <div class="card-content">
          ${this._renderSystemSection()}
          ${this._renderHeatPumpSection()}
          ${this._renderDhwSection()}
          ${[1, 2, 3, 4].map((c) => this._renderCircuitSection(c))}
        </div>
      </ha-card>
    `;
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }
      .card {
        padding: 16px;
      }
      .card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0 0 12px 0;
        font-size: 18px;
        font-weight: 500;
      }
      .version {
        font-size: 12px;
        color: var(--secondary-text-color);
        font-weight: 400;
      }
      .section {
        margin-bottom: 16px;
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 8px;
        padding: 12px;
      }
      .section-header {
        display: flex;
        align-items: center;
        gap: 8px;
        font-weight: 500;
        margin-bottom: 12px;
        color: var(--primary-text-color);
      }
      .section-content {
        display: flex;
        flex-direction: column;
        gap: 12px;
      }
      .control-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
      }
      .control-label {
        flex: 1 1 0;
        min-width: 0;
        color: var(--primary-text-color);
      }
      .slider-row {
        flex-wrap: wrap;
      }
      .slider-wrap {
        display: flex;
        align-items: center;
        gap: 8px;
        flex: 1;
        min-width: 120px;
      }
      input[type='range'] {
        flex: 1;
        min-width: 0;
        min-height: 24px;
        cursor: ew-resize;
        pointer-events: auto;
        touch-action: none;
      }
      .slider-value {
        min-width: 44px;
        text-align: right;
        color: var(--secondary-text-color);
        font-size: 12px;
        white-space: nowrap;
      }
      .ha-select {
        min-width: 140px;
        min-height: 36px;
        padding: 6px 8px;
        border-radius: 4px;
        border: 1px solid var(--divider-color, #e0e0e0);
        background: var(--card-background-color, #fff);
        color: var(--primary-text-color);
        cursor: pointer;
        pointer-events: auto;
        -webkit-appearance: menulist;
        appearance: menulist-button;
      }
      .ha-select:hover,
      .ha-select:focus {
        border-color: var(--primary-color);
      }
      .ha-select:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }
      .status-row {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }
      .status-chip {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 4px 8px;
        border-radius: 12px;
        background: var(--secondary-background-color, #f5f5f5);
        color: var(--secondary-text-color);
        font-size: 12px;
      }
    `;
  }
}

class KebaHeatPumpModbusCardEditor extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      config: { type: Object },
    };
  }

  setConfig(config) {
    this.config = config;
  }

  _valueChanged(ev) {
    if (!this.config) return;
    const target = ev.target;
    const newConfig = {
      ...this.config,
      [target.dataset.configValue]: target.value,
    };
    const event = new CustomEvent('config-changed', {
      detail: { config: newConfig },
      bubbles: true,
      composed: true,
    });
    this.dispatchEvent(event);
  }

  render() {
    if (!this.hass || !this.config) {
      return html``;
    }

    return html`
      <div class="card-config">
        <div class="field">
          <label for="title">Title</label>
          <input
            id="title"
            type="text"
            .value=${this.config.title || ''}
            data-config-value="title"
            @input=${this._valueChanged}
          />
        </div>
        <div class="field">
          <label for="entity_prefix">Entity prefix</label>
          <input
            id="entity_prefix"
            type="text"
            .value=${this.config.entity_prefix || DEFAULT_PREFIX}
            data-config-value="entity_prefix"
            @input=${this._valueChanged}
          />
        </div>
      </div>
    `;
  }

  static get styles() {
    return css`
      .card-config {
        display: flex;
        flex-direction: column;
        gap: 16px;
      }
      .field {
        display: flex;
        flex-direction: column;
        gap: 4px;
      }
      label {
        font-size: 12px;
        color: var(--secondary-text-color);
      }
      input {
        padding: 8px;
        border-radius: 4px;
        border: 1px solid var(--divider-color, #e0e0e0);
        background: var(--card-background-color, #fff);
        color: var(--primary-text-color);
      }
    `;
  }
}

// ────────────────────────────────────────────────────────────
// Registration
// ────────────────────────────────────────────────────────────

function defineCardElements() {
  if (!window.customElements.get(CARD_TAG)) {
    window.customElements.define(CARD_TAG, KebaHeatPumpModbusCard);
  }
  if (!window.customElements.get(EDITOR_TAG)) {
    window.customElements.define(EDITOR_TAG, KebaHeatPumpModbusCardEditor);
  }

  window.customCards = window.customCards || [];
  if (!window.customCards.some((card) => card.type === CARD_TAG)) {
    window.customCards.push({
      type: CARD_TAG,
      name: 'KEBA Heat Pump Modbus',
      description: 'Settings card for the KEBA Heat Pump Modbus integration',
      preview: true,
    });
  }

  console.info(
    `%c KEBA-HEAT-PUMP-MODBUS-CARD %c v${CARD_VERSION} `,
    'color: white; background: #2c7be5; font-weight: 700; border-radius: 4px 0 0 4px; padding: 2px 6px;',
    'color: #2c7be5; background: transparent; font-weight: 700; border: 1px solid #2c7be5; border-radius: 0 4px 4px 0; padding: 2px 6px;',
  );
}

async function registerCard() {
  // This module is auto-loaded by the integration via add_extra_js_url, which
  // makes Home Assistant's index page import it in a race with HA's own core
  // bundle. Recent HA frontends replace window.customElements with a scoped
  // custom-element-registry polyfill during boot; elements defined before that
  // swap are stranded in the discarded native registry and Lovelace reports
  // "Custom element doesn't exist". The HA index page sets
  // window.customPanelJS synchronously before extra modules are imported, so
  // its presence tells us we are inside HA and must wait until HA's root
  // element resolves through the *current* registry (i.e. the final registry
  // is installed) before defining ours. window.customElements is re-read on
  // every poll on purpose — a stored reference would keep pointing at the
  // replaced registry.
  if (window.customPanelJS !== undefined || window.hassConnection !== undefined) {
    const deadline = Date.now() + 60000;
    while (!window.customElements.get('home-assistant') && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
  }
  defineCardElements();
}

registerCard();
