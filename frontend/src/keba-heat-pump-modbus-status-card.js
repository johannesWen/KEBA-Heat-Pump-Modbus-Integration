import { LitElement, html, css, nothing } from 'lit';
import { INTEGRATION_DOMAIN } from 'virtual:integration-version';

const VIEW_TAG = 'keba-heat-pump-modbus-status-view';
const OPTIONS_TAG = 'keba-heat-pump-modbus-status-options';
const WINDOWS = [
  ['last_hour', 'Last hour'], ['last_3_hours', 'Last 3 hours'],
  ['last_6_hours', 'Last 6 hours'], ['today', 'Today so far'],
  ['yesterday', 'Yesterday'], ['this_week', 'This week'], ['this_month', 'This month'],
];

export function validateStatusConfig(config) {
  if (config.time_window && !WINDOWS.some(([key]) => key === config.time_window)) {
    throw new Error('Unknown Status time_window');
  }
}

function localDateTime(date, timeZone) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
    timeZone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).formatToParts(date).map(part => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}`;
}

function parseLocalDateTime(value, timeZone, current) {
  const normalized = value.length === 16 ? `${value}:00` : value;
  if (current && value === localDateTime(current, timeZone).slice(0, 16)) return current;
  const wallTime = Date.parse(`${normalized}Z`);
  if (!Number.isFinite(wallTime)) throw new Error('Enter valid start and end times.');
  // Try both offsets around a DST transition; repeated times use the first occurrence.
  const candidates = [-86400000, 86400000].map(delta => {
    const sample = wallTime + delta;
    return new Date(wallTime - (Date.parse(`${localDateTime(new Date(sample), timeZone)}Z`) - sample));
  }).sort((a, b) => a - b);
  const result = candidates.find(date => localDateTime(date, timeZone) === normalized);
  if (!result) throw new Error('This local time does not exist. Check the date and daylight-saving change.');
  return result;
}

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
        id: entity.device_id, label: device?.name_by_user || device?.name || 'KEBA device', entities: [], keys: {},
        heatPump: device?.identifiers?.some(([domain, id]) => domain === INTEGRATION_DOMAIN && id.endsWith('_heat_pump')),
      });
    }
    devices.get(entity.device_id).entities.push(entity.entity_id);
    devices.get(entity.device_id).keys[entity.entity_id] = state.attributes.keba_key || entity.unique_id || '';
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

function temperaturePlots(device) {
  const matching = pattern => device.entities.filter(id => pattern.test(device.keys[id]));
  const flow = matching(/(?:^|_)(?:flow_temperature|reflux_temperature|set_temperature)$/);
  const source = matching(/(?:^|_)source_(?:in|out)_temperature$/);
  if (device.heatPump || flow.length || source.length) {
    return [
      { title: 'Flow, reflux and setpoint', entities: flow },
      { title: 'Source in and out', entities: source },
      { title: 'Other temperatures', entities: device.entities.filter(id => !flow.includes(id) && !source.includes(id)) },
    ].filter(plot => plot.entities.length);
  }
  if (matching(/_buffer_tank\d+$/).length) {
    const primary = matching(/(?:^|_)temperature_(?:middle|top)_buffer_tank\d+$/);
    return [{ title: 'Middle and top', entities: device.entities,
      optional: device.entities.filter(id => !primary.includes(id)) }];
  }
  if (matching(/_circuit_\d+$/).length) {
    const circuitFlow = matching(/(?:^|_)circuit_(?:flow|reflux)_temperature_circuit_\d+$/);
    return [
      { title: 'Flow and reflux', entities: circuitFlow },
      { title: 'Other temperatures', entities: device.entities.filter(id => !circuitFlow.includes(id)) },
    ].filter(plot => plot.entities.length);
  }
  return [{ title: 'Temperatures', entities: device.entities }];
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

function resampleStates(states, range) {
  if (states.length <= 1000) return states;
  const start = range.start.getTime();
  const interval = (range.end.getTime() - start) / 250;
  const buckets = new Array(250);
  const keep = new Set([0, states.length - 1]);
  let previousNumeric;
  states.forEach((point, index) => {
    const isNumeric = numeric(point.state);
    if (index && isNumeric !== previousNumeric) {
      keep.add(index - 1);
      keep.add(index);
    }
    previousNumeric = isNumeric;
    if (!isNumeric) return;
    const key = Math.max(0, Math.min(249, Math.floor((point.last_changed - start) / interval)));
    const bucket = buckets[key];
    if (!bucket) {
      buckets[key] = { first: index, min: index, max: index, last: index };
      return;
    }
    if (Number(point.state) < Number(states[bucket.min].state)) bucket.min = index;
    if (Number(point.state) > Number(states[bucket.max].state)) bucket.max = index;
    bucket.last = index;
  });
  for (const bucket of buckets) {
    if (bucket) for (const index of Object.values(bucket)) keep.add(index);
  }
  // ponytail: gap boundaries can exceed 1,000 points; chunk processing if gap-heavy histories still block rendering.
  return states.filter((point, index) => keep.has(index));
}

class KebaHeatPumpStatusView extends LitElement {
  static properties = {
    hass: { attribute: false }, config: { attribute: false },
    _devices: { state: true }, _deviceId: { state: true }, _window: { state: true },
    _history: { state: true }, _range: { state: true }, _loading: { state: true },
    _error: { state: true }, _notice: { state: true }, _enabledBufferEntities: { state: true },
    _rangeError: { state: true }, _touchZoom: { state: true }, _zoomed: { state: true },
  };

  constructor() {
    super();
    this._devices = [];
    this._window = 'today';
    this._request = 0;
    this._discoveryRequest = 0;
    this._unsubscribers = [];
    this._enabledBufferEntities = new Set();
    this._plotHistory = new Map();
    this._yRanges = new Map();
    this._draft = {};
    this._touchZoom = false;
    this._zoomed = false;
    this._onReady = () => this._loadDevices();
  }

  setConfig(config) {
    validateStatusConfig(config);
    if (!this.config || this.config.device_id !== config.device_id) {
      this._deviceId = config.device_id || null;
      this._yRanges.clear();
    }
    if (!this.config || this.config.time_window !== config.time_window) {
      this._window = config.time_window || 'today';
      this._customRange = null;
      this._resetRange = null;
      this._yRanges.clear();
      this._zoomed = false;
      this._draft = {};
      this._rangeError = '';
    }
    this.config = { ...config };
  }

  getCardSize() {
    const device = this._devices.find(item => item.id === this._deviceId);
    return 7 + Math.max(0, (device ? temperaturePlots(device).length : 1) - 1) * 4;
  }

  connectedCallback() {
    super.connectedCallback();
    this._timer = setInterval(() => {
      if (!['yesterday', 'custom'].includes(this._window) && !this._loading && !this._drag) this._fetchHistory();
    }, 60000);
    if (this.hass) this._connect();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    clearInterval(this._timer);
    this._cancelDrag();
    this._disconnect();
    this._request++;
    this._discoveryRequest++;
    this._discovering = false;
  }

  firstUpdated() {
    this.renderRoot.addEventListener('dblclick', event => {
      const path = event.composedPath();
      const base = path.find(node => node.localName === 'ha-chart-base');
      if (base?.chart && path.includes(base.chart.getDom())) event.stopPropagation();
    }, true);
    for (const type of ['pointerdown', 'pointermove', 'pointerup', 'pointercancel', 'lostpointercapture']) {
      this.renderRoot.addEventListener(type, event => this._handlePointer(event), true);
    }
    // Suppress compatibility mouse/touch events only while our selection owns the gesture.
    for (const type of ['mousedown', 'mousemove', 'mouseup', 'touchstart', 'touchmove', 'touchend']) {
      this.renderRoot.addEventListener(type, event => {
        if (this._drag) event.stopPropagation();
      }, { capture: true, passive: true });
    }
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
    if (this._history?.line.length) this._configureChartLegends();
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
      device.entities.map(id => [id, device.keys[id], this.hass.states[id].attributes.unit_of_measurement])]));
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

  async _configureChartLegends() {
    this._legendCharts ||= new WeakSet();
    for (const charts of this.renderRoot.querySelectorAll('state-history-charts')) {
      await charts.updateComplete;
      for (const line of charts.shadowRoot?.querySelectorAll('state-history-chart-line') || []) {
        await line.updateComplete;
        if (!this.renderRoot.contains(charts) || this._legendCharts.has(line)) continue;
        const chart = line.shadowRoot?.querySelector('ha-chart-base');
        if (!chart) continue;
        await chart.updateComplete;
        if (!this.renderRoot.contains(charts)) continue;
        this._legendCharts.add(line);
        line.hideResetButton = true;
        const plot = charts.closest('.plot').getAttribute('aria-label');
        const yRange = this._yRanges.get(`${plot}:${line.unit}`);
        if (yRange) {
          line.fitYData = false;
          [line.minYAxis, line.maxYAxis] = yRange;
        }
        const timestamp = document.createElement('div');
        timestamp.className = 'selected-time';
        const style = document.createElement('style');
        style.textContent = `
          .chart-legend { container-type: inline-size; margin-top: 12px; padding: 12px; border: 1px solid var(--divider-color); border-radius: 8px; max-height: 240px; overflow: auto; }
          .selected-time { margin-bottom: 8px; font-size: 12px; color: var(--secondary-text-color); }
          .chart-legend ul { display: grid; grid-template-columns: minmax(0, 1fr); gap: 0px 16px; }
          .chart-legend li { display: flex; align-items: center; min-width: 0; max-width: none !important; height: auto; min-height: 24px; }
          .chart-legend .label { flex: 1; min-width: 0; white-space: normal; overflow-wrap: anywhere; text-align: start; }
          .chart-legend .value { max-width: 50%; white-space: normal; overflow-wrap: anywhere; line-height: 1.5; text-align: end; }
          @container (min-width: 340px) { .chart-legend ul { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
        `;
        chart.shadowRoot.append(style);
        chart.addController({ hostUpdated: () => {
          const legend = chart.shadowRoot.querySelector('.chart-legend');
          if (legend && timestamp.parentElement !== legend) {
            legend.setAttribute('role', 'group');
            legend.setAttribute('aria-label', 'Legend and selected values');
            legend.prepend(timestamp);
          }
        } });
        let selectedTime = null;
        const updateLegend = (params = []) => {
          const time = selectedTime ?? Math.max(this._range.end.getTime(),
            ...(chart.data || []).map(dataset => dataset.data?.at(-1)?.[0] || 0));
          timestamp.textContent = new Intl.DateTimeFormat(this.hass.locale?.language || this.hass.language || 'en', {
            timeZone: this.hass.config.time_zone, dateStyle: 'medium', timeStyle: 'medium',
          }).format(new Date(time));
          for (const item of chart.options.legend?.data || []) {
            const dataset = chart.data?.find(dataset => dataset.id === item.id);
            const point = params.find(point => point.seriesId === item.id);
            const value = point?.value?.[1] ?? dataset?.data?.findLast(point =>
              point[0] <= time && typeof point[1] === 'number')?.[1];
            const state = this.hass.states[item.id];
            item.value = typeof value !== 'number' ? '—' :
              state && this.hass.formatEntityState ? this.hass.formatEntityState(state, String(value)) :
              `${new Intl.NumberFormat(this.hass.locale?.language || 'en').format(value)} ${line.unit || ''}`.trim();
          }
          chart.requestUpdate();
        };
        let configuredOptions;
        let tooltipChart;
        // Keep the selected time when native updates rebuild the chart options.
        const controller = { hostUpdated: () => {
          if (!chart?.options?.tooltip || chart.options === configuredOptions) return;
          const tooltip = chart.options.tooltip;
          chart.options = configuredOptions = { ...chart.options,
            dataZoom: [{ type: 'inside', xAxisIndex: 0, zoomOnMouseWheel: false,
              moveOnMouseWheel: false, moveOnMouseMove: false, preventDefaultMouseMove: false }],
            tooltip: {
              ...tooltip, extraCssText: 'display:none!important;',
              formatter: params => {
                if (chart.chart && chart.chart !== tooltipChart) {
                  tooltipChart = chart.chart;
                  tooltipChart.on('hideTip', event => {
                    // A touch drag ending keeps the native slider active.
                    if (!event.from) return;
                    selectedTime = null;
                    updateLegend();
                  });
                }
                selectedTime = params[0].axisValue;
                updateLegend(params);
                return nothing;
              },
            },
          };
          updateLegend();
        } };
        line.addController(controller);
        controller.hostUpdated();
      }
    }
  }

  _entityName(id) {
    const name = this.hass.states[id].attributes.friendly_name || id;
    const entity = this._registry.entities.find(entity => entity.entity_id === id);
    const device = this._registry.devices.find(device => device.id === entity?.device_id);
    for (const prefix of [device?.name_by_user, device?.name]) {
      if (prefix && name.startsWith(`${prefix} `)) return name.slice(prefix.length + 1);
    }
    return name;
  }

  async _fetchHistory() {
    if (!this.hass || !this.isConnected) return;
    this._cancelDrag();
    const request = ++this._request;
    const device = this._devices.find(item => item.id === this._deviceId);
    this._history = null;
    this._plotHistory.clear();
    this._notice = '';
    this._error = '';
    this._loading = false;
    if (!device) return;
    if (!this.hass.config.components.includes('history')) {
      this._error = 'Home Assistant History is not enabled.';
      return;
    }
    const range = this._customRange || timeRange(this._window, this.hass.config.time_zone);
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
      const wantStatistics = ['this_week', 'this_month', 'custom'].includes(this._window);
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
            name: this._entityName(id),
            states: id.startsWith('sensor.') ? resampleStates(states, range) : states,
            statistics: older };
        }).filter(entity => entity.states.some(point => numeric(point.state)) ||
          entity.statistics.some(point => numeric(point.state))),
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

  _selectDevice(event) {
    this._deviceId = event.target.value;
    this._yRanges.clear();
    this._fetchHistory();
  }

  _selectWindow(key) {
    if (key === 'custom') {
      this._customRange = this._range;
    } else this._customRange = null;
    this._window = key;
    this._resetRange = null;
    this._zoomed = false;
    this._yRanges.clear();
    this._draft = {};
    this._rangeError = '';
    this._fetchHistory();
  }

  _applyRange(event) {
    if (!Object.hasOwn(this._draft, event.target.name)) return;
    try {
      const fields = this.renderRoot.querySelectorAll('input[type="datetime-local"]');
      if ([...fields].some(field => !field.validity.valid)) throw new Error('Enter valid start and end times.');
      const [start, end] = [...fields].map(field =>
        parseLocalDateTime(field.value, this.hass.config.time_zone, this._range?.[field.name]));
      if (start >= end) throw new Error('Start time must be before end time.');
      this._rangeError = '';
      this._draft = {};
      if (+start === +this._range?.start && +end === +this._range?.end) return;
      this._customRange = { start, end };
      this._window = 'custom';
      this._resetRange = null;
      this._zoomed = false;
      this._yRanges.clear();
      this._fetchHistory();
    } catch (error) { this._rangeError = errorMessage(error); }
  }

  _resetZoom() {
    this._cancelDrag();
    if (this._resetRange) {
      this._window = this._resetRange.window;
      this._customRange = this._resetRange.custom;
    }
    this._resetRange = null;
    this._zoomed = false;
    this._yRanges.clear();
    this._draft = {};
    this._rangeError = '';
    this._fetchHistory();
  }

  _cancelDrag() {
    const drag = this._drag;
    if (!drag) return;
    this._drag = null;
    drag.overlay.remove();
    window.removeEventListener('keydown', drag.keydown, true);
    if (drag.base.hasPointerCapture(drag.pointerId)) drag.base.releasePointerCapture(drag.pointerId);
  }

  _handlePointer(event) {
    if (event.type === 'pointerdown') {
      if (this._drag) { this._cancelDrag(); return; }
      if (event.button !== 0 || !event.isPrimary || (event.pointerType === 'touch' && !this._touchZoom)) return;
      const base = event.composedPath().find(node => node.localName === 'ha-chart-base');
      const chart = base?.chart;
      // ponytail: native HA chart internals; revisit this hook if HA changes its renderer.
      if (!chart?.containPixel || !chart.convertFromPixel) return;
      const rect = chart.getDom().getBoundingClientRect();
      const point = [event.clientX - rect.left, event.clientY - rect.top];
      if (!chart.containPixel({ gridIndex: 0 }, point)) return;
      const options = chart.getOption();
      const grid = options.grid[0];
      const size = (value, total) => typeof value === 'string' && value.endsWith('%') ? parseFloat(value) * total / 100 : Number(value || 0);
      const bounds = [size(grid.left, rect.width), size(grid.top, rect.height),
        rect.width - size(grid.right, rect.width), rect.height - size(grid.bottom, rect.height)];
      const overlay = document.createElement('div');
      overlay.className = 'zoom-selection';
      base.style.position = 'relative';
      overlay.style.cssText = 'position:absolute;pointer-events:none;border:1px solid var(--primary-color);background:var(--primary-color);opacity:0.2;z-index:1;';
      base.shadowRoot.append(overlay);
      const line = base.getRootNode().host;
      const plot = event.composedPath().find(node => node.classList?.contains('plot'));
      this._drag = { base, chart, rect, bounds, point, overlay, line,
        key: `${plot.getAttribute('aria-label')}:${line.unit}`, pointerId: event.pointerId,
        keydown: keyEvent => { if (keyEvent.key === 'Escape') { keyEvent.stopPropagation(); this._cancelDrag(); } } };
      window.addEventListener('keydown', this._drag.keydown, true);
      base.setPointerCapture(event.pointerId);
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    const drag = this._drag;
    if (!drag || event.pointerId !== drag.pointerId) return;
    event.stopPropagation();
    if (event.type === 'pointercancel' || event.type === 'lostpointercapture') { this._cancelDrag(); return; }
    const [left, top, right, bottom] = drag.bounds;
    const point = [Math.max(left, Math.min(right, event.clientX - drag.rect.left)),
      Math.max(top, Math.min(bottom, event.clientY - drag.rect.top))];
    const dx = Math.abs(point[0] - drag.point[0]), dy = Math.abs(point[1] - drag.point[1]);
    const horizontal = dx >= 8 && dx * 3 >= dy;
    const vertical = dy >= 8 && dy * 3 >= dx;
    const from = [horizontal ? Math.min(point[0], drag.point[0]) : left, vertical ? Math.min(point[1], drag.point[1]) : top];
    const to = [horizontal ? Math.max(point[0], drag.point[0]) : right, vertical ? Math.max(point[1], drag.point[1]) : bottom];
    Object.assign(drag.overlay.style, { left: `${from[0]}px`, top: `${from[1]}px`,
      width: `${to[0] - from[0]}px`, height: `${to[1] - from[1]}px`, display: horizontal || vertical ? 'block' : 'none' });
    if (event.type !== 'pointerup') return;
    this._cancelDrag();
    if (!horizontal && !vertical) return;
    const a = drag.chart.convertFromPixel({ gridIndex: 0 }, from);
    const b = drag.chart.convertFromPixel({ gridIndex: 0 }, to);
    if (![...a, ...b].every(Number.isFinite)) return;
    const start = Math.max(this._range.start.getTime(), Math.round(a[0]));
    const end = Math.min(this._range.end.getTime(), Math.round(b[0]));
    if (horizontal && start >= end) return;
    this._resetRange ||= { window: this._window, custom: this._customRange };
    this._zoomed = true;
    if (vertical) {
      const range = [Math.min(a[1], b[1]), Math.max(a[1], b[1])];
      this._yRanges.set(drag.key, range);
      drag.line.fitYData = false;
      [drag.line.minYAxis, drag.line.maxYAxis] = range;
    }
    if (horizontal) {
      this._customRange = { start: new Date(start), end: new Date(end) };
      this._window = 'custom';
      this._draft = {};
      this._rangeError = '';
      this._fetchHistory();
    }
  }

  _toggleBufferEntity(id, enabled) {
    const entities = new Set(this._enabledBufferEntities);
    if (enabled) entities.add(id);
    else entities.delete(id);
    this._plotHistory.clear();
    this._enabledBufferEntities = entities;
  }

  _renderPlot(plot) {
    let history = this._plotHistory.get(plot.title);
    if (!history) {
      const line = this._history.line.map(group => ({ ...group,
        identifier: group.data.filter(entity => plot.entities.includes(entity.entity_id))
          .map(entity => entity.entity_id).join(','),
        data: group.data.filter(entity => plot.entities.includes(entity.entity_id) &&
          (!plot.optional?.includes(entity.entity_id) || this._enabledBufferEntities.has(entity.entity_id))),
      })).filter(group => group.data.length);
      history = { line, timeline: [] };
      this._plotHistory.set(plot.title, history);
    }
    return html`<section class="plot" aria-label=${plot.title}>
      <div class="plot-heading">
        <h3>${plot.title}</h3>
        ${history.line.length ? html`<button class="reset-zoom" aria-label="Reset zoom" title="Reset zoom for all plots"
          ?disabled=${!this._zoomed} @click=${this._resetZoom}>
          <ha-icon icon="mdi:restore" aria-hidden="true"></ha-icon>
        </button>` : nothing}
      </div>
      ${plot.optional?.length ? html`<fieldset class="extra-temperatures">
        <legend>Additional temperatures</legend>
        ${plot.optional.map(id => html`<label><input type="checkbox"
          .checked=${this._enabledBufferEntities.has(id)}
          @change=${event => this._toggleBufferEntity(id, event.target.checked)}
        >${this.hass.states[id].attributes.friendly_name || id}</label>`)}
      </fieldset>` : nothing}
      ${history.line.length ? html`
        <state-history-charts .hass=${this.hass} .historyData=${history}
          style=${this._touchZoom ? 'touch-action: none;' : ''}
          .startTime=${this._range.start} .endTime=${this._range.end}
          .showNames=${true} .expandLegend=${true} .fitYData=${true}
        ></state-history-charts>
      ` : html`<p class="message" role="status">No temperature history found for this plot.</p>`}
    </section>`;
  }

  render() {
    if (!this.hass || !this.config) return nothing;
    const device = this._devices.find(item => item.id === this._deviceId);
    return html`
        <header><h2>Temperature history</h2>
          <button class="refresh" aria-label="Refresh history" @click=${() => this._loadDevices()}>
            <ha-icon icon="mdi:refresh"></ha-icon><span>Refresh</span>
          </button>
        </header>
        <div class="content">
          <div class="selectors">
            <label class="outlined-field"><span id="device-label">Device</span>
              <select id="device" aria-labelledby="device-label" .value=${this._deviceId || ''} @change=${this._selectDevice}>
                ${!device ? html`<option value=${this._deviceId || ''} .selected=${true}>${this._deviceId ? 'Selected device unavailable' : 'Select a device'}</option>` : nothing}
                ${this._devices.map(item => html`<option value=${item.id} .selected=${item.id === this._deviceId}>${item.label}</option>`)}
              </select>
            </label>
            <label class="outlined-field"><span id="time-window-label">Time window</span>
              <select id="time-window" aria-labelledby="time-window-label" .value=${this._window} @change=${event => this._selectWindow(event.target.value)}>
                ${[...WINDOWS, ['custom', 'Custom']].map(([key, label]) => html`
                  <option value=${key} .selected=${this._window === key}>${label}</option>`)}
              </select>
            </label>
          </div>
          <div class="range-controls">
            ${['start', 'end'].map(name => html`<label class="outlined-field"><span>${name === 'start' ? 'Start time' : 'End time'}</span>
              <input type="datetime-local" name=${name} required step="60"
                aria-describedby="range-error"
                aria-invalid=${!!this._rangeError}
                .value=${this._draft[name] ?? (this._range ? localDateTime(this._range[name], this.hass.config.time_zone).slice(0, 16) : '')}
                @input=${event => { this._draft[name] = event.target.value; }}
                @blur=${this._applyRange}>
            </label>`)}
          </div>
          <p id="range-error" class="error" role="alert" ?hidden=${!this._rangeError}>${this._rangeError || ''}</p>
          <button class="touch-zoom" aria-pressed=${this._touchZoom}
            @click=${() => { this._cancelDrag(); this._touchZoom = !this._touchZoom; }}>
            <ha-icon icon="mdi:gesture-pinch" aria-hidden="true"></ha-icon>Touch zoom
          </button>
          ${this._error ? html`<p class="message error" role="alert">${this._error} Use Refresh to retry.</p>` :
            this._loading ? html`<p class="message" role="status">Loading temperature history…</p>` :
            !device ? html`<p class="message" role="status">${this._deviceId ? 'Selected device unavailable.' : 'No KEBA temperature devices available.'}</p>` :
            !this._history?.line.length ? html`<p class="message" role="status">No temperature history found for this period.</p>` :
            temperaturePlots(device).map(plot => this._renderPlot(plot))}
          ${this._notice ? html`<p class="notice" role="status">${this._notice}</p>` : nothing}
        </div>
      `;
  }

  static styles = css`
    :host { display: block; color: var(--primary-text-color); font-family: var(--ha-font-family-body, Roboto, sans-serif); }
    header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 24px; }
    h2 { margin: 0; font-size: 20px; font-weight: 500; line-height: 1.4; letter-spacing: 0.15px; }
    .content { padding: 0 0 16px; }
    label { display: block; margin-bottom: 6px; font-size: 12px; color: var(--secondary-text-color); }
    button, select, input[type="datetime-local"] { color: var(--primary-text-color); background: var(--card-background-color); font: inherit; }
    button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 40px; padding: 8px 16px;
      border: 0; border-radius: 20px; cursor: pointer; font-size: 14px; font-weight: 500; letter-spacing: 0.1px; color: var(--primary-color);
      transition: background-color 120ms, box-shadow 120ms; }
    button:hover:not(:disabled) { background: color-mix(in srgb, var(--primary-color) 8%, var(--card-background-color)); }
    button:active:not(:disabled) { background: color-mix(in srgb, var(--primary-color) 16%, var(--card-background-color)); }
    button:focus-visible, select:focus-visible, input:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
    button:disabled { cursor: default; opacity: 0.38; }
    button[aria-pressed="true"] { background: color-mix(in srgb, var(--primary-color) 16%, var(--card-background-color)); }
    .refresh { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
    ha-icon { --mdc-icon-size: 20px; }
    .selectors, .range-controls { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr)); gap: 20px 16px; }
    .range-controls { margin-top: 20px; }
    .outlined-field { position: relative; min-width: 0; margin: 0; }
    .outlined-field > span { position: absolute; z-index: 1; top: -7px; left: 12px; padding: 0 4px;
      background: var(--card-background-color); font-size: 12px; line-height: 14px; letter-spacing: 0.4px; }
    .outlined-field > select, .outlined-field > input { box-sizing: border-box; width: 100%; min-width: 0; min-height: 56px;
      padding: 14px 12px; border: 1px solid var(--input-outlined-idle-border-color, var(--divider-color)); border-radius: 4px; font-size: 14px; }
    .outlined-field:hover > select, .outlined-field:hover > input { border-color: var(--primary-text-color); }
    .outlined-field:focus-within > span { color: var(--primary-color); }
    .outlined-field > select:focus, .outlined-field > input:focus { outline: none; border-color: var(--primary-color); box-shadow: inset 0 0 0 1px var(--primary-color); }
    .outlined-field > input[aria-invalid="true"] { border-color: var(--error-color, #db4437); }
    .touch-zoom { margin-top: 12px; }
    @media (hover: hover) and (pointer: fine) { .touch-zoom { display: none; } }
    @media (any-pointer: coarse) { .touch-zoom { display: inline-flex; } }
    .notice { font-size: 12px; line-height: 1.5; color: var(--secondary-text-color); }
    .message { padding: 24px 8px; text-align: center; font-size: 14px; color: var(--secondary-text-color); }
    .error { color: var(--error-color, #db4437); }
    .plot { padding: 16px 0; }
    .plot + .plot { border-top: 1px solid var(--divider-color); }
    .plot-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
    h3 { margin: 0; font-size: 16px; font-weight: 500; letter-spacing: 0.15px; }
    .reset-zoom { flex-shrink: 0; width: 40px; height: 40px; padding: 0; }
    .extra-temperatures { border: 0; padding: 0; margin: 0 0 12px; }
    .extra-temperatures legend { margin-bottom: 6px; font-size: 12px; color: var(--secondary-text-color); }
    .extra-temperatures label { display: flex; align-items: center; gap: 6px; overflow-wrap: anywhere; }
    input[type="checkbox"] { accent-color: var(--primary-color); flex-shrink: 0; }
    state-history-charts { display: block; min-width: 0; --chart-max-height: 300px; }
    @media (prefers-reduced-motion: reduce) { button { transition: none; } }
    @media (max-width: 400px) { .refresh span { display: none; } }
  `;
}

class KebaHeatPumpStatusOptions extends LitElement {
  static properties = { hass: { attribute: false }, config: { attribute: false }, _devices: { state: true }, _error: { state: true } };
  constructor() { super(); this._devices = []; this._request = 0; }
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
    return html`<label>Initial device<select name="device_id" .value=${this.config.device_id || ''} @change=${this._change}>
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

export function defineStatusViewElements() {
  if (!window.customElements.get(VIEW_TAG)) window.customElements.define(VIEW_TAG, KebaHeatPumpStatusView);
  if (!window.customElements.get(OPTIONS_TAG)) window.customElements.define(OPTIONS_TAG, KebaHeatPumpStatusOptions);
}
