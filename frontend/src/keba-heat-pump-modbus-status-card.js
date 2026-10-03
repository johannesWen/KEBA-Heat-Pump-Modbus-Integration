import { LitElement, html, css, nothing } from 'lit';
import { INTEGRATION_DOMAIN } from 'virtual:integration-version';

const CARD_TAG = 'keba-heat-pump-modbus-status-card';
const EDITOR_TAG = `${CARD_TAG}-editor`;
const WINDOWS = [
  ['last_hour', 'Last hour'], ['last_3_hours', 'Last 3 hours'],
  ['last_6_hours', 'Last 6 hours'], ['today', 'Today so far'],
  ['yesterday', 'Yesterday'], ['this_week', 'This week'], ['this_month', 'This month'],
];

function timeRange(preset, timeZone, now = new Date()) {
  const hours = { last_hour: 1, last_3_hours: 3, last_6_hours: 6 }[preset];
  if (hours) return { start: new Date(now.getTime() - hours * 3600000), end: now };
  const formatter = new Intl.DateTimeFormat('en-GB', {
    timeZone, year: 'numeric', month: 'numeric', day: 'numeric',
    hour: 'numeric', minute: 'numeric', second: 'numeric', hourCycle: 'h23',
  });
  const parts = date => Object.fromEntries(formatter.formatToParts(date)
    .filter(part => part.type !== 'literal').map(part => [part.type, Number(part.value)]));
  const local = parts(now);
  const day = Date.UTC(local.year, local.month - 1, local.day);
  // Resolve a local calendar midnight without using the browser's time zone.
  const midnight = wallTime => {
    const wall = instant => {
      const p = parts(new Date(instant));
      return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
    };
    const candidates = [-86400000, 86400000].map(delta => {
      const sample = wallTime + delta;
      return wallTime - (wall(sample) - sample);
    }).sort((a, b) => a - b);
    // An overlapping midnight starts at its first occurrence. A skipped midnight
    // starts after the gap, matching calendar-day boundaries in the HA time zone.
    return new Date(candidates.find(instant => wall(instant) === wallTime) ??
      candidates.find(instant => wall(instant) > wallTime));
  };
  let startDay = day;
  if (preset === 'yesterday') startDay -= 86400000;
  if (preset === 'this_week') startDay -= ((new Date(day).getUTCDay() + 6) % 7) * 86400000;
  if (preset === 'this_month') startDay = Date.UTC(local.year, local.month - 1, 1);
  return { start: midnight(startDay), end: preset === 'yesterday' ? midnight(day) : now };
}

function temperatureDevices(hass, registry) {
  const devices = new Map();
  for (const entity of registry.entities) {
    const state = hass.states[entity.entity_id];
    if (entity.platform !== INTEGRATION_DOMAIN || entity.disabled_by || !entity.device_id ||
        !/^(sensor|number)\./.test(entity.entity_id) ||
        state?.attributes?.device_class !== 'temperature' ||
        /(?:^|_)offset(?:_|$)/.test(state.attributes.keba_key || entity.unique_id || '')) continue;
    if (!devices.has(entity.device_id)) {
      const device = registry.devices.find(item => item.id === entity.device_id);
      devices.set(entity.device_id, {
        id: entity.device_id, label: device?.name_by_user || device?.name || 'KEBA device', entities: [],
        heatPump: device?.identifiers?.some(([domain, id]) => domain === INTEGRATION_DOMAIN && id.endsWith('_heat_pump')),
      });
    }
    devices.get(entity.device_id).entities.push(entity.entity_id);
  }
  const result = [...devices.values()].sort((a, b) => Number(!!b.heatPump) - Number(!!a.heatPump) ||
    a.label.localeCompare(b.label) || a.id.localeCompare(b.id));
  const counts = new Map();
  for (const device of result) {
    const label = device.label;
    if (result.filter(item => item.label === label).length > 1 || counts.has(label)) {
      const index = (counts.get(label) || 0) + 1;
      counts.set(label, index);
      device.label = `${label} (${index})`;
    }
    device.entities.sort((a, b) => (hass.states[a].attributes.keba_key || a)
      .localeCompare(hass.states[b].attributes.keba_key || b));
  }
  return result;
}

async function loadRegistry(hass) {
  const [entities, devices] = await Promise.all([
    hass.callWS({ type: 'config/entity_registry/list' }),
    hass.callWS({ type: 'config/device_registry/list' }),
  ]);
  return { entities, devices };
}

const errorMessage = error => error?.message || error?.code || String(error);
const numeric = state => typeof state === 'string' && state.trim() !== '' && Number.isFinite(Number(state));

class KebaHeatPumpStatusCard extends LitElement {
  static properties = {
    hass: { attribute: false }, config: { attribute: false },
    _devices: { state: true }, _deviceId: { state: true }, _window: { state: true },
    _history: { state: true }, _range: { state: true }, _loading: { state: true },
    _error: { state: true }, _notice: { state: true },
  };

  constructor() {
    super();
    this._devices = [];
    this._window = 'today';
    this._request = 0;
    this._discoveryRequest = 0;
    this._unsubscribers = [];
    this._onReady = () => this._loadDevices();
  }

  setConfig(config) {
    if (config.time_window && !WINDOWS.some(([key]) => key === config.time_window)) {
      throw new Error('Unknown Status time_window');
    }
    this.config = { title: 'KEBA Heat Pump Status', ...config };
    this._deviceId = config.device_id || null;
    this._window = config.time_window || 'today';
  }

  static getStubConfig() { return { type: `custom:${CARD_TAG}`, time_window: 'today' }; }
  static getConfigElement() { return document.createElement(EDITOR_TAG); }
  getCardSize() { return 7; }

  connectedCallback() {
    super.connectedCallback();
    this._timer = setInterval(() => {
      if (this._window !== 'yesterday' && !this._loading) this._fetchHistory();
    }, 60000);
    if (this.hass) this._connect();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    clearInterval(this._timer);
    this._disconnect();
    this._request++;
    this._discoveryRequest++;
    this._discovering = false;
  }

  _disconnect() {
    this._subscriptionRequest = (this._subscriptionRequest || 0) + 1;
    this._connection?.removeEventListener('ready', this._onReady);
    for (const unsubscribe of this._unsubscribers) Promise.resolve(unsubscribe()).catch(() => {});
    this._unsubscribers = [];
    this._connection = null;
  }

  _connect() {
    this._disconnect();
    this._connection = this.hass.connection;
    const connection = this._connection;
    const request = this._subscriptionRequest;
    connection?.addEventListener('ready', this._onReady);
    for (const event of ['entity_registry_updated', 'device_registry_updated']) {
      connection?.subscribeEvents(() => this._loadDevices(), event).then(unsubscribe => {
        if (this.isConnected && request === this._subscriptionRequest) this._unsubscribers.push(unsubscribe);
        else return unsubscribe();
      }).catch(error => {
        if (this.isConnected && request === this._subscriptionRequest) this._error = errorMessage(error);
      });
    }
    this._loadDevices();
  }

  updated(changed) {
    if (!this.hass || !this.config || !this.isConnected) return;
    if (changed.has('hass') && this.hass.connection !== this._connection) {
      this._connect();
      return;
    }
    if (!this._registry) {
      if (!this._discovering && !this._error) this._loadDevices();
      return;
    }
    if (changed.has('hass') || changed.has('config')) {
      const changedDevices = this._updateDevices();
      if (changedDevices || changed.has('config')) this._fetchHistory();
    }
  }

  _updateDevices() {
    const devices = temperatureDevices(this.hass, this._registry);
    const signature = JSON.stringify(devices.map(device => [device.id, device.label,
      device.entities.map(id => [id, this.hass.states[id].attributes.unit_of_measurement])]));
    const changed = signature !== this._deviceSignature;
    this._deviceSignature = signature;
    if (changed) this._devices = devices;
    if (!this._deviceId) this._deviceId = devices[0]?.id;
    return changed;
  }

  async _loadDevices() {
    if (!this.hass || !this.isConnected) return;
    const request = ++this._discoveryRequest;
    this._discovering = true;
    this._loading = true;
    this._error = '';
    this._request++; // Invalidate results based on the previous registry.
    try {
      const registry = await loadRegistry(this.hass);
      if (request !== this._discoveryRequest || !this.isConnected) return;
      this._registry = registry;
      this._updateDevices();
      await this._fetchHistory();
    } catch (error) {
      if (request === this._discoveryRequest) this._error = errorMessage(error);
    } finally {
      if (request === this._discoveryRequest) {
        this._discovering = false;
        this._loading = false;
      }
    }
  }

  async _loadChart(entityId) {
    if (window.customElements.get('state-history-charts')) return;
    this._chartReady ||= (async () => {
      const waitFor = tag => new Promise((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error('Home Assistant chart could not be loaded')), 15000);
        window.customElements.whenDefined(tag).then(() => { clearTimeout(timeout); resolve(); });
      });
      // The integration bundle can load before the Lovelace panel installs helpers.
      if (!window.loadCardHelpers) await waitFor('ha-panel-lovelace');
      if (!window.loadCardHelpers) throw new Error('Home Assistant chart helpers are unavailable');
      const helpers = await window.loadCardHelpers();
      helpers.createCardElement({ type: 'history-graph', entities: [entityId] });
      await waitFor('state-history-charts');
    })().catch(error => { this._chartReady = null; throw error; });
    await this._chartReady;
  }

  async _fetchHistory() {
    if (!this.hass || !this.isConnected) return;
    const request = ++this._request;
    const device = this._devices.find(item => item.id === this._deviceId);
    this._history = null;
    this._notice = '';
    this._error = '';
    this._loading = false;
    if (!device) return;
    if (!this.hass.config.components.includes('history')) {
      this._error = 'Home Assistant History is not enabled.';
      return;
    }
    const range = timeRange(this._window, this.hass.config.time_zone);
    this._range = range;
    this._loading = true;
    try {
      const groups = new Map();
      for (const id of device.entities) {
        const unit = this.hass.states[id].attributes.unit_of_measurement || '°C';
        if (!groups.has(unit)) groups.set(unit, []);
        groups.get(unit).push(id);
      }
      const params = { start_time: range.start.toISOString(), end_time: range.end.toISOString() };
      const wantStatistics = ['this_week', 'this_month'].includes(this._window);
      const statistics = async () => {
        if (!wantStatistics) return {};
        const result = {};
        for (const [unit, ids] of groups) {
          const sensors = ids.filter(id => id.startsWith('sensor.') &&
            this.hass.states[id].attributes.state_class === 'measurement');
          if (!sensors.length) continue;
          Object.assign(result, await this.hass.callWS({
            type: 'recorder/statistics_during_period', ...params, statistic_ids: sensors,
            period: 'hour', types: ['mean'], units: { temperature: unit },
          }));
        }
        return result;
      };
      const [raw, statsResult] = await Promise.all([
        this.hass.callWS({ type: 'history/history_during_period', ...params,
          entity_ids: device.entities, minimal_response: true, no_attributes: true,
          include_start_time_state: true }),
        statistics().then(data => ({ data }), error => ({ error })),
        this._loadChart(device.entities[0]),
      ]);
      if (request !== this._request || !this.isConnected) return;
      let usedStatistics = false;
      const line = [...groups].map(([unit, ids]) => ({
        unit, device_class: 'temperature', identifier: ids.join(','),
        data: ids.map(id => {
          const states = (raw[id] || []).map(point => ({
            state: point.s, last_changed: (point.lc ?? point.lu) * 1000,
          }));
          const oldest = states[0]?.last_changed ?? Infinity;
          const older = (statsResult.data?.[id] || [])
            .filter(point => point.mean != null && point.end < oldest &&
              point.end >= range.start.getTime() && point.end <= range.end.getTime())
            .map(point => ({ state: String(point.mean), last_changed: point.end }));
          usedStatistics ||= older.length > 0;
          return { entity_id: id, domain: id.split('.')[0],
            name: this.hass.states[id].attributes.friendly_name || id, states, statistics: older };
        }).filter(entity => [...entity.states, ...entity.statistics].some(point => numeric(point.state))),
      })).filter(group => group.data.length);
      this._history = { line, timeline: [] };
      if (statsResult.error) this._notice = `Older statistics unavailable: ${errorMessage(statsResult.error)}. Showing recorded history.`;
      else if (usedStatistics) this._notice = 'Older sensor values are hourly averages. Setpoints show available recorded history.';
    } catch (error) {
      if (request === this._request && this.isConnected) this._error = errorMessage(error);
    } finally {
      if (request === this._request) this._loading = false;
    }
  }

  _selectDevice(event) { this._deviceId = event.target.value; this._fetchHistory(); }
  _selectWindow(key) { this._window = key; this._fetchHistory(); }

  render() {
    if (!this.hass || !this.config) return nothing;
    const device = this._devices.find(item => item.id === this._deviceId);
    const format = date => new Intl.DateTimeFormat(this.hass.locale?.language || this.hass.language || 'en', {
      timeZone: this.hass.config.time_zone, month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    }).format(date);
    return html`
      <ha-card>
        <header><div><p class="eyebrow">Temperature history</p><h2>${this.config.title}</h2></div>
          <button class="refresh" aria-label="Refresh history" @click=${() => this._loadDevices()}>
            <ha-icon icon="mdi:refresh"></ha-icon><span>Refresh</span>
          </button>
        </header>
        <div class="content">
          <label for="device">Device</label>
          <select id="device" .value=${this._deviceId || ''} @change=${this._selectDevice}>
            ${!device ? html`<option value=${this._deviceId || ''} .selected=${true}>${this._deviceId ? 'Selected device unavailable' : 'Select a device'}</option>` : nothing}
            ${this._devices.map(item => html`<option value=${item.id} .selected=${item.id === this._deviceId}>${item.label}</option>`)}
          </select>
          <div class="presets" role="group" aria-label="Time window">
            ${WINDOWS.map(([key, label]) => html`<button aria-pressed=${this._window === key}
              @click=${() => this._selectWindow(key)}>${label}</button>`)}
          </div>
          ${device && this._range ? html`<p class="range">${format(this._range.start)} – ${format(this._range.end)} · ${this.hass.config.time_zone}</p>` : nothing}
          ${this._error ? html`<p class="message error" role="alert">${this._error} Use Refresh to retry.</p>` :
            this._loading ? html`<p class="message" role="status">Loading temperature history…</p>` :
            !device ? html`<p class="message" role="status">${this._deviceId ? 'Selected device unavailable.' : 'No KEBA temperature devices available.'}</p>` :
            !this._history?.line.length ? html`<p class="message" role="status">No temperature history found for this period.</p>` : html`
              <state-history-charts .hass=${this.hass} .historyData=${this._history}
                .startTime=${this._range.start} .endTime=${this._range.end}
                .showNames=${true} .expandLegend=${true} .fitYData=${true}
              ></state-history-charts>`}
          ${this._notice ? html`<p class="notice" role="status">${this._notice}</p>` : nothing}
        </div>
      </ha-card>`;
  }

  static styles = css`
    :host { display: block; color: var(--primary-text-color); }
    header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 20px 20px 12px; }
    h2 { margin: 4px 0 0; font-size: 20px; font-weight: 500; line-height: 1.3; }
    .eyebrow { margin: 0; color: var(--secondary-text-color); font-size: 11px; letter-spacing: .08em; text-transform: uppercase; }
    .content { padding: 0 20px 16px; }
    label { display: block; margin-bottom: 6px; font-size: 12px; color: var(--secondary-text-color); }
    select { box-sizing: border-box; width: 100%; padding: 10px; font: inherit; }
    button, select { border: 1px solid var(--divider-color); border-radius: 8px; color: var(--primary-text-color); background: var(--card-background-color); }
    button { min-height: 36px; padding: 6px 10px; cursor: pointer; font: inherit; font-size: 12px; }
    button:focus-visible, select:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
    button[aria-pressed="true"] { color: var(--text-primary-color, white); background: var(--primary-color); border-color: var(--primary-color); }
    .refresh { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
    .refresh ha-icon { --mdc-icon-size: 18px; }
    .presets { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
    .range, .notice { font-size: 12px; line-height: 1.5; color: var(--secondary-text-color); }
    .message { padding: 24px 8px; text-align: center; font-size: 14px; color: var(--secondary-text-color); }
    .error { color: var(--error-color, #db4437); }
    state-history-charts { display: block; min-width: 0; --chart-max-height: 300px; }
    @media (max-width: 400px) { header { padding: 16px 12px 12px; } .content { padding: 0 12px 12px; } .refresh span { display: none; } }
  `;
}

class KebaHeatPumpStatusEditor extends LitElement {
  static properties = { hass: { attribute: false }, config: { attribute: false }, _devices: { state: true }, _error: { state: true } };
  constructor() { super(); this._devices = []; this._request = 0; }
  setConfig(config) { this.config = { ...config }; }
  connectedCallback() { super.connectedCallback(); if (this.hass) this._load(); }
  disconnectedCallback() { super.disconnectedCallback(); this._request++; this._registry = null; }
  updated(changed) {
    if (changed.has('hass') && this.isConnected) {
      if (!this._registry && !this._loading) this._load();
      else if (this._registry) this._devices = temperatureDevices(this.hass, this._registry);
    }
  }
  async _load() {
    const request = ++this._request;
    this._loading = true;
    try {
      const registry = await loadRegistry(this.hass);
      if (request !== this._request) return;
      this._registry = registry;
      this._devices = temperatureDevices(this.hass, registry);
      this._error = '';
    } catch (error) { if (request === this._request) this._error = errorMessage(error); }
    finally { if (request === this._request) this._loading = false; }
  }
  _change(event) {
    const config = { ...this.config };
    if (event.target.value) config[event.target.name] = event.target.value;
    else delete config[event.target.name];
    this.dispatchEvent(new CustomEvent('config-changed', { detail: { config }, bubbles: true, composed: true }));
  }
  render() {
    if (!this.config) return nothing;
    return html`<label>Title<input name="title" .value=${this.config.title ?? ''} @input=${this._change}></label>
      <label>Initial device<select name="device_id" .value=${this.config.device_id || ''} @change=${this._change}>
        <option value="" .selected=${!this.config.device_id}>Automatic</option>
        ${this.config.device_id && !this._devices.some(device => device.id === this.config.device_id)
          ? html`<option value=${this.config.device_id} .selected=${true}>Selected device unavailable</option>` : nothing}
        ${this._devices.map(device => html`<option value=${device.id} .selected=${device.id === this.config.device_id}>${device.label}</option>`)}
      </select></label>
      <label>Initial time window<select name="time_window" .value=${this.config.time_window || 'today'} @change=${this._change}>
        ${WINDOWS.map(([key, label]) => html`<option value=${key} .selected=${key === (this.config.time_window || 'today')}>${label}</option>`)}
      </select></label>
      ${this._error ? html`<p role="alert">${this._error}</p>` : nothing}`;
  }
  static styles = css`
    :host { display: grid; gap: 16px; }
    label { display: grid; gap: 6px; color: var(--secondary-text-color); font-size: 12px; }
    input, select { padding: 10px; border: 1px solid var(--divider-color); border-radius: 6px; font: inherit;
      color: var(--primary-text-color); background: var(--card-background-color); }
  `;
}

export function defineStatusCardElements() {
  if (!window.customElements.get(CARD_TAG)) window.customElements.define(CARD_TAG, KebaHeatPumpStatusCard);
  if (!window.customElements.get(EDITOR_TAG)) window.customElements.define(EDITOR_TAG, KebaHeatPumpStatusEditor);
  if (!window.customCards.some(card => card.type === CARD_TAG)) window.customCards.push({
    type: CARD_TAG, name: 'KEBA Heat Pump Status',
    description: 'Temperature history by device with time presets and older hourly averages', preview: true,
  });
}
