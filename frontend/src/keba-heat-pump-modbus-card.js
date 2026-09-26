import { LitElement, html, css, nothing } from 'lit';
import { live } from 'lit/directives/live.js';
import { CARD_VERSION } from 'virtual:integration-version';

const CARD_TAG = 'keba-heat-pump-modbus-card';
const EDITOR_TAG = 'keba-heat-pump-modbus-card-editor';
const DEFAULT_PREFIX = 'keba_heat_pump_modbus';
const DEFAULT_VIEW = 'settings';

const VIEWS = [
  { key: 'settings', label: 'Settings', icon: 'mdi:cog' },
  { key: 'schedule', label: 'Schedule', icon: 'mdi:calendar-clock' },
];

const SECTIONS = [
  { key: 'system', label: 'System', icon: 'mdi:cog' },
  { key: 'heat_pump', label: 'Heat Pump', icon: 'mdi:heat-pump' },
  { key: 'dhw', label: 'Hot Water', icon: 'mdi:water-boiler' },
];

const HOURS = Array.from({ length: 24 }, (_, i) => i);
const WEEKDAYS = [
  { index: 0, label: 'Mon', full: 'Monday' },
  { index: 1, label: 'Tue', full: 'Tuesday' },
  { index: 2, label: 'Wed', full: 'Wednesday' },
  { index: 3, label: 'Thu', full: 'Thursday' },
  { index: 4, label: 'Fri', full: 'Friday' },
  { index: 5, label: 'Sat', full: 'Saturday' },
  { index: 6, label: 'Sun', full: 'Sunday' },
];

class KebaHeatPumpModbusCard extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      config: { type: Object },
      _currentView: { state: true },
      _lastError: { state: true },
      _pending: { state: true },
      _selectedPlanId: { state: true },
    };
  }

  constructor() {
    super();
    this.config = {};
    this._entityAliases = {};
    this._currentView = DEFAULT_VIEW;
    this._lastError = null;
    this._pending = false;
    this._selectedPlanId = null;
    this._selectAfterAdd = null;
  }

  setConfig(config) {
    this.config = {
      entity_prefix: DEFAULT_PREFIX,
      title: 'KEBA Heat Pump',
      view: DEFAULT_VIEW,
      ...config,
    };
    this._currentView = this.config.view || DEFAULT_VIEW;
  }

  getCardSize() {
    return 10;
  }

  static getConfigElement() {
    return document.createElement(EDITOR_TAG);
  }

  static getStubConfig() {
    return { entity_prefix: DEFAULT_PREFIX, title: 'KEBA Heat Pump', view: DEFAULT_VIEW };
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
    const reStrict = new RegExp(`^${domain}\.${wanted}(?:_\d+)?$`);
    const reLoose = new RegExp(`^${domain}\..*${wanted}(?:_\d+)?$`);

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

  _callService(domain, service, data, onFail) {
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
      if (onFail) onFail(err);
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

  _renderViewTabs() {
    const current = this._currentView;
    return html`
      <div class="view-tabs">
        ${VIEWS.map(
          (view) => html`
            <button
              type="button"
              aria-pressed=${current === view.key}
              class="view-tab ${current === view.key ? 'active' : ''}"
              @click=${() => this._setView(view.key)}
            >
              <ha-icon .icon=${view.icon}></ha-icon>
              <span>${view.label}</span>
            </button>
          `,
        )}
      </div>
    `;
  }

  _setView(view) {
    if (this._currentView === view) return;
    this._currentView = view;
    this._lastError = null;
    this.requestUpdate();
  }

  // ── Settings view ─────────────────────────────────────────

  _renderSettingsView() {
    return html`
      ${this._renderSystemSection()}
      ${this._renderHeatPumpSection()}
      ${this._renderDhwSection()}
      ${[1, 2, 3, 4].map((c) => this._renderCircuitSection(c))}
    `;
  }

  // ── Schedule view ─────────────────────────────────────────

  _getSchedulesState() {
    return this._state('sensor', 'schedules');
  }

  _getOperatingModeOptions() {
    const state = this._state('select', 'operating_mode');
    return state?.attributes?.options || [];
  }

  _getPlans() {
    const state = this._getSchedulesState();
    const plansAttr = state?.attributes?.plans || {};
    return Object.entries(plansAttr)
      .map(([planId, data]) => ({
        planId: Number(planId),
        ...data,
      }))
      .sort((a, b) => a.planId - b.planId);
  }

  _schedulesEntityId() {
    const state = this._getSchedulesState();
    return state?.entity_id || this._eid('sensor', 'schedules');
  }

  async _callScheduleService(service, data) {
    if (this._pending) return;
    this._lastError = null;
    this._pending = true;
    try {
      await this._callService(
        'keba_heat_pump_modbus',
        service,
        { entity_id: this._schedulesEntityId(), ...data },
        (err) => {
          this._lastError = `Could not save schedule: ${err?.message || err}`;
        },
      );
    } finally {
      this._pending = false;
    }
  }

  async _addPlan() {
    // Select the newly created plan when its sensor update arrives, even if
    // the service response arrives before the state change.
    this._selectAfterAdd = new Set(this._getPlans().map((plan) => plan.planId));
    await this._callScheduleService('add_schedule', {});
    if (this._lastError) this._selectAfterAdd = null;
  }

  _removePlan(planId) {
    this._callScheduleService('remove_schedule', { plan_id: planId });
  }

  _setPlanName(planId, name) {
    this._callScheduleService('set_schedule_name', { plan_id: planId, name });
  }

  _setPlanEnabled(planId, enabled) {
    this._callScheduleService('set_schedule_enabled', { plan_id: planId, enabled });
  }

  _setPlanOffMode(planId, offMode) {
    this._callScheduleService('set_schedule_off_mode', { plan_id: planId, off_mode: offMode });
  }

  _setPlanOnMode(planId, onMode) {
    this._callScheduleService('set_schedule_on_mode', { plan_id: planId, on_mode: onMode });
  }

  _setPlanHour(planId, hour, on) {
    this._callScheduleService('set_schedule_hour', { plan_id: planId, hour, on });
  }

  _setPlanWeekday(planId, weekday, selected) {
    this._callScheduleService('set_schedule_weekday', { plan_id: planId, weekday, selected });
  }

  _renderScheduleStatus() {
    const active = this._val('binary_sensor', 'schedule_active');
    const scheduledMode = this._val('sensor', 'scheduled_mode');
    const operatingMode = this._val('select', 'operating_mode');
    return html`
      <div class="schedule-status">
        <div class="status-item">
          <ha-icon icon="mdi:calendar-clock"></ha-icon>
          <span>Schedule ${active === 'on' ? 'active' : active === 'off' ? 'inactive' : 'unavailable'}</span>
        </div>
        ${scheduledMode && scheduledMode !== 'unknown' && scheduledMode !== 'unavailable'
          ? html`
              <div class="status-item">
                <ha-icon icon="mdi:calendar-check"></ha-icon>
                <span>Scheduled: ${scheduledMode}</span>
              </div>
            `
          : nothing}
        ${operatingMode && operatingMode !== 'unknown' && operatingMode !== 'unavailable'
          ? html`
              <div class="status-item">
                <ha-icon icon="mdi:cog"></ha-icon>
                <span>Current: ${operatingMode}</span>
              </div>
            `
          : nothing}
      </div>
    `;
  }

  _renderWeekdayGrid(plan) {
    const selectedDays = new Set(plan.weekdays || []);
    const summary = selectedDays.size
      ? WEEKDAYS.filter((day) => selectedDays.has(day.index)).map((day) => day.label).join(', ')
      : 'Every day';
    return html`
      <div class="weekday-section">
        <div class="hours-heading">
          <span>Active days</span>
          <span class="muted">${summary}</span>
        </div>
        <div class="weekday-grid" role="group" aria-label="Active weekdays">
          ${WEEKDAYS.map((day) => html`
            <button
              type="button"
              class="day-chip ${selectedDays.has(day.index) ? 'on' : ''}"
              aria-label=${day.full}
              aria-pressed=${selectedDays.has(day.index)}
              @click=${() => this._setPlanWeekday(plan.planId, day.index, !selectedDays.has(day.index))}
            >${day.label}</button>
          `)}
        </div>
        <p class="weekday-hint">${selectedDays.size
          ? 'Only selected days run this plan.'
          : 'No days selected means every day.'}</p>
      </div>
    `;
  }

  _renderHourGrid(plan) {
    const onHours = new Set(plan.on_hours || []);
    return html`
      <div class="hour-grid" role="group" aria-label="On hours">
        ${HOURS.map(
          (h) => html`
            <button
              type="button"
              aria-pressed=${onHours.has(h)}
              aria-label="${String(h).padStart(2, '0')}:00–${String(h + 1).padStart(2, '0')}:00"
              class="hour-chip ${onHours.has(h) ? 'on' : ''}"
              @click=${() => this._setPlanHour(plan.planId, h, !onHours.has(h))}
              title="${String(h).padStart(2, '0')}:00"
            >
              ${String(h).padStart(2, '0')}
            </button>
          `,
        )}
      </div>
    `;
  }

  _hourSummary(hours = []) {
    const selected = HOURS.filter((hour) => hours.includes(hour));
    if (!selected.length) return 'No on hours selected';
    if (selected.length === 24) return 'All day';
    const ranges = [];
    let start = selected[0];
    let end = start;
    const time = (hour) => `${String(hour).padStart(2, '0')}:00`;
    for (const hour of selected.slice(1)) {
      if (hour === end + 1) {
        end = hour;
      } else {
        ranges.push(`${time(start)}–${time(end + 1)}`);
        start = end = hour;
      }
    }
    ranges.push(`${time(start)}–${time(end + 1)}`);
    return ranges.join(', ');
  }

  _selectedPlan(plans) {
    if (this._selectAfterAdd) {
      const added = plans.find((plan) => !this._selectAfterAdd.has(plan.planId));
      if (added) {
        this._selectedPlanId = added.planId;
        this._selectAfterAdd = null;
      }
    }
    const selected = plans.find((plan) => plan.planId === this._selectedPlanId) || plans[0];
    if (selected && this._selectedPlanId !== selected.planId) this._selectedPlanId = selected.planId;
    return selected;
  }

  _handlePlanTabKeydown(event, plans, index) {
    const last = plans.length - 1;
    let next;
    switch (event.key) {
      case 'ArrowRight': next = index === last ? 0 : index + 1; break;
      case 'ArrowLeft': next = index === 0 ? last : index - 1; break;
      case 'Home': next = 0; break;
      case 'End': next = last; break;
      default: return;
    }
    event.preventDefault();
    this._selectedPlanId = plans[next].planId;
    this.updateComplete.then(() =>
      this.renderRoot.querySelector(`#plan-tab-${plans[next].planId}`)?.focus(),
    );
  }

  _renderPlanTabs(plans, selectedPlan) {
    return html`
      <div class="plan-tabs" role="tablist" aria-label="Schedule plans">
        ${plans.map((plan, index) => html`
          <button
            type="button"
            role="tab"
            id="plan-tab-${plan.planId}"
            aria-controls="plan-panel-${plan.planId}"
            aria-selected=${plan.planId === selectedPlan.planId}
            aria-label="Plan ${plan.planId}: ${plan.name || `Plan ${plan.planId}`}"
            title=${plan.name || `Plan ${plan.planId}`}
            tabindex=${plan.planId === selectedPlan.planId ? 0 : -1}
            class="plan-tab ${plan.planId === selectedPlan.planId ? 'active' : ''}"
            @click=${() => { this._selectedPlanId = plan.planId; }}
            @keydown=${(event) => this._handlePlanTabKeydown(event, plans, index)}
          >
            <span class="plan-tab-number">${plan.planId}</span>
            <span class="plan-tab-name">${plan.name || `Plan ${plan.planId}`}</span>
          </button>
        `)}
      </div>
    `;
  }

  _renderPlanCard(plan, modeOptions) {
    const displayName = plan.name || `Plan ${plan.planId}`;
    // Keep saved modes visible even while the operating-mode entity is unavailable.
    const options = [...new Set([...modeOptions, plan.off_mode, plan.on_mode])].filter(Boolean);
    return html`
      <fieldset class="plan-card ${plan.enabled ? 'enabled' : ''}" ?disabled=${this._pending}>
        <legend class="sr-only">${displayName}</legend>
        <div class="plan-header">
          <div class="plan-identity">
            <span class="plan-number">Plan ${plan.planId}</span>
            <input
              class="plan-name-input"
              type="text"
              aria-label="Name for plan ${plan.planId}"
              .value=${displayName}
              placeholder="Plan name"
              maxlength="32"
              @change=${(e) => this._setPlanName(plan.planId, e.target.value)}
            />
          </div>
          <div class="plan-actions">
            <label class="plan-toggle">
              <input
                type="checkbox"
                role="switch"
                aria-label="Enable ${displayName}"
                .checked=${live(Boolean(plan.enabled))}
                @change=${(e) => this._setPlanEnabled(plan.planId, e.target.checked)}
              />
              <span>${plan.enabled ? 'Enabled' : 'Paused'}</span>
            </label>
            <button
              type="button"
              class="icon-btn danger"
              title="Remove ${displayName}"
              aria-label="Remove ${displayName}"
              @click=${() => this._removePlan(plan.planId)}
            >
              <ha-icon icon="mdi:delete-outline"></ha-icon>
            </button>
          </div>
        </div>
        ${this._renderWeekdayGrid(plan)}
        <div class="plan-modes">
          <label class="mode-field">
            <span class="control-label">Off mode <small>Outside selected hours</small></span>
            <select
              class="ha-select"
              .value=${live(plan.off_mode)}
              @change=${(e) => this._setPlanOffMode(plan.planId, e.target.value)}
            >
              ${options.map((opt) => html`<option value=${opt} ?selected=${opt === plan.off_mode}>${opt}</option>`)}
            </select>
          </label>
          <label class="mode-field">
            <span class="control-label">On mode <small>During selected hours</small></span>
            <select
              class="ha-select"
              .value=${live(plan.on_mode)}
              @change=${(e) => this._setPlanOnMode(plan.planId, e.target.value)}
            >
              ${options.map((opt) => html`<option value=${opt} ?selected=${opt === plan.on_mode}>${opt}</option>`)}
            </select>
          </label>
        </div>
        <div class="plan-hours">
          <div class="hours-heading">
            <span>Daily on hours</span>
            <span class="muted">${(plan.on_hours || []).length} / 24 h</span>
          </div>
          ${this._renderHourGrid(plan)}
          <p class="hour-summary">${this._hourSummary(plan.on_hours)}</p>
          <div class="hour-legend">
            <span><i class="legend-dot selected"></i>On mode</span>
            <span><i class="legend-dot"></i>Off mode</span>
          </div>
        </div>
      </fieldset>
    `;
  }

  _renderScheduleView() {
    const state = this._getSchedulesState();
    if (!state || ['unavailable', 'unknown'].includes(state.state)) {
      return html`
        <div class="empty-state" role="status">
          <ha-icon icon="mdi:calendar-alert"></ha-icon>
          <strong>Schedules unavailable</strong>
          <p>Check that the KEBA integration is loaded and its Schedules sensor is enabled.</p>
        </div>
      `;
    }

    const plans = this._getPlans();
    const modeOptions = this._getOperatingModeOptions();
    const maxPlans = state.attributes?.max_plans || 5;
    const canAdd = plans.length < maxPlans;
    const selectedPlan = this._selectedPlan(plans);

    return html`
      ${this._lastError
        ? html`<div class="error-banner" role="alert">
            <ha-icon icon="mdi:alert-circle"></ha-icon>
            <span>${this._lastError}</span>
          </div>`
        : nothing}
      ${this._renderScheduleStatus()}
      <div class="schedule-actions">
        <div>
          <h2>Daily plans</h2>
          <span class="muted">${plans.length} of ${maxPlans} plans</span>
        </div>
        <button
          type="button"
          class="action-btn primary"
          ?disabled=${!canAdd || this._pending}
          @click=${() => this._addPlan()}
        >
          <ha-icon icon="mdi:plus"></ha-icon>
          Add plan
        </button>
      </div>
      <p class="schedule-hint">
        Select weekdays and hours for each plan${this.hass.config?.time_zone ? ` · ${this.hass.config.time_zone}` : ''}.
      </p>
      <div class="save-status muted" role="status" aria-live="polite">
        ${this._pending ? 'Saving…' : !canAdd ? 'Plan limit reached. Remove a plan to add another.' : 'Changes apply immediately.'}
      </div>
      ${selectedPlan ? html`
        ${this._renderPlanTabs(plans, selectedPlan)}
        <div
          id="plan-panel-${selectedPlan.planId}"
          role="tabpanel"
          aria-labelledby="plan-tab-${selectedPlan.planId}"
          tabindex="0"
          aria-busy=${this._pending}
        >
          ${this._renderPlanCard(selectedPlan, modeOptions)}
        </div>
      ` : nothing}
      ${plans.length === 0
        ? html`<div class="empty-state">
            <ha-icon icon="mdi:calendar-clock-outline"></ha-icon>
            <strong>Set your daily rhythm</strong>
            <p>Add your first plan, choose two operating modes, then select the hours to switch between them.</p>
          </div>`
        : html`<p class="schedule-hint priority-note">
            Lower plan numbers have priority when selected hours overlap. Outside all selected hours,
            the lowest-numbered enabled plan supplies the Off mode.
          </p>`}
    `;
  }

  render() {
    if (!this.hass) {
      return html`<div class="card">Loading...</div>`;
    }

    const view = this._currentView;

    return html`
      <ha-card class="card">
        <div class="card-header">
          <span class="title">${this.config.title}</span>
          <span class="version">v${CARD_VERSION}</span>
        </div>
        ${this._renderViewTabs()}
        <div class="card-content">
          ${view === 'schedule' ? this._renderScheduleView() : this._renderSettingsView()}
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
      .view-tabs {
        display: flex;
        gap: 8px;
        padding: 0 0 12px 0;
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
        margin-bottom: 12px;
      }
      .view-tab {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px 12px;
        border-radius: 16px;
        border: 1px solid var(--divider-color, #e0e0e0);
        background: var(--card-background-color, #fff);
        color: var(--primary-text-color);
        cursor: pointer;
        font-size: 14px;
      }
      .view-tab.active {
        background: var(--primary-color);
        color: var(--text-primary-color, #fff);
        border-color: var(--primary-color);
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

      /* Schedule controls follow the dashboard theme and the card's own width. */
      :host {
        container-type: inline-size;
      }
      button, input, select {
        font: inherit;
        box-sizing: border-box;
      }
      button:focus-visible, input:focus-visible, select:focus-visible {
        outline: 2px solid var(--primary-color);
        outline-offset: 3px;
      }
      button:disabled, fieldset:disabled input, fieldset:disabled select {
        cursor: wait;
        opacity: 0.6;
      }
      .view-tab {
        flex: 1;
        justify-content: center;
        min-height: 44px;
        border-radius: 8px;
      }
      .muted, .schedule-hint, .hour-summary {
        color: var(--secondary-text-color);
        font-size: 12px;
        line-height: 1.5;
      }
      .error-banner {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 12px;
        border-radius: 8px;
        border: 1px solid var(--error-color, #db4437);
        color: var(--error-color, #db4437);
        margin-bottom: 16px;
        overflow-wrap: anywhere;
      }
      .error-banner ha-icon { flex-shrink: 0; }
      .schedule-status {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin-bottom: 20px;
      }
      .status-item {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px 10px;
        border-radius: 6px;
        background: var(--secondary-background-color, #f5f5f5);
        color: var(--secondary-text-color);
        font-size: 12px;
      }
      .status-item ha-icon { --mdc-icon-size: 18px; }
      .schedule-actions {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
      }
      h2 { margin: 0; font-size: 18px; font-weight: 600; }
      .schedule-hint { margin: 12px 0 4px; }
      .save-status { min-height: 18px; margin-bottom: 16px; }
      .action-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        min-height: 44px;
        padding: 8px 14px;
        border-radius: 8px;
        border: 1px solid var(--primary-color);
        cursor: pointer;
        font-size: 14px;
        font-weight: 500;
      }
      .action-btn.primary {
        background: var(--primary-color);
        color: var(--text-primary-color, #fff);
      }
      .plan-tabs {
        display: flex;
        gap: 4px;
        min-width: 0;
        overflow-x: auto;
        margin: 0 0 12px;
        padding: 0 0 3px;
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
      }
      .plan-tab {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        flex: 0 1 auto;
        min-width: 64px;
        max-width: 150px;
        min-height: 40px;
        padding: 6px 10px;
        border: 0;
        border-bottom: 2px solid transparent;
        border-radius: 6px 6px 0 0;
        background: transparent;
        color: var(--secondary-text-color);
        cursor: pointer;
        text-align: left;
      }
      .plan-tab:hover { background: var(--secondary-background-color, #f5f5f5); }
      .plan-tab.active { border-bottom-color: var(--primary-color); color: var(--primary-text-color); font-weight: 600; }
      .plan-tab-number {
        flex: 0 0 auto;
        display: grid;
        place-items: center;
        width: 20px;
        height: 20px;
        border-radius: 5px;
        background: var(--secondary-background-color, #f5f5f5);
        color: var(--secondary-text-color);
        font-size: 11px;
      }
      .plan-tab.active .plan-tab-number { background: var(--primary-color); color: var(--text-primary-color, #fff); }
      .plan-tab-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .plan-card {
        min-inline-size: 0;
        margin: 0 0 16px;
        padding: 16px;
        border: 1px solid var(--divider-color, #e0e0e0);
        border-inline-start: 3px solid var(--divider-color, #e0e0e0);
        border-radius: 10px;
      }
      .plan-card.enabled { border-inline-start-color: var(--primary-color); }
      .plan-header {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 18px;
      }
      .plan-identity { flex: 1 1 140px; min-width: 0; }
      .plan-number {
        display: block;
        color: var(--secondary-text-color);
        font-size: 11px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        margin-bottom: 4px;
      }
      .plan-name-input {
        width: 100%;
        min-width: 0;
        padding: 6px 0;
        border: 0;
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 0;
        background: transparent;
        color: var(--primary-text-color);
        font-size: 16px;
        font-weight: 600;
      }
      .plan-actions, .plan-toggle { display: flex; align-items: center; gap: 10px; }
      .plan-toggle { font-size: 12px; cursor: pointer; }
      .plan-toggle input { width: 20px; height: 20px; accent-color: var(--primary-color); }
      .icon-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 44px;
        height: 44px;
        padding: 0;
        border: 0;
        border-radius: 8px;
        background: transparent;
        color: var(--secondary-text-color);
        cursor: pointer;
      }
      .icon-btn.danger:hover { color: var(--error-color, #db4437); background: var(--secondary-background-color); }
      .weekday-section { margin-bottom: 18px; }
      .weekday-grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 4px; }
      .weekday-hint { margin: 7px 0 0; color: var(--secondary-text-color); font-size: 11px; }
      .plan-modes { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-bottom: 20px; }
      .mode-field { display: flex; flex-direction: column; gap: 8px; min-width: 0; font-size: 13px; }
      .mode-field small { display: block; color: var(--secondary-text-color); font-size: 11px; margin-top: 2px; }
      .mode-field select { width: 100%; min-width: 0; min-height: 44px; border-radius: 6px; }
      .hours-heading { display: flex; justify-content: space-between; gap: 8px; font-size: 13px; margin-bottom: 10px; }
      .hour-grid { display: grid; grid-template-columns: repeat(8, minmax(0, 1fr)); gap: 4px; }
      .hour-chip, .day-chip {
        min-width: 0;
        min-height: 32px;
        padding: 0;
        border-radius: 5px;
        border: 1px solid var(--divider-color, #e0e0e0);
        background: var(--secondary-background-color, #f5f5f5);
        color: var(--primary-text-color);
        font-size: 11px;
        font-variant-numeric: tabular-nums;
        cursor: pointer;
      }
      .hour-chip:hover:not(:disabled), .day-chip:hover:not(:disabled) { border-color: var(--primary-color); }
      .hour-chip.on, .day-chip.on {
        background: var(--primary-color);
        color: var(--text-primary-color, #fff);
        border-color: var(--primary-color);
        font-weight: 700;
      }
      .hour-summary { margin: 10px 0 6px; font-variant-numeric: tabular-nums; }
      .hour-legend, .hour-legend span { display: flex; align-items: center; gap: 6px; }
      .hour-legend { gap: 16px; font-size: 11px; color: var(--secondary-text-color); }
      .legend-dot { width: 8px; height: 8px; border-radius: 2px; background: var(--secondary-background-color, #f5f5f5); border: 1px solid var(--divider-color, #e0e0e0); }
      .legend-dot.selected { background: var(--primary-color); border-color: var(--primary-color); }
      .priority-note { padding: 0 2px; }
      .empty-state { display: flex; flex-direction: column; align-items: center; text-align: center; padding: 28px 16px; border: 1px dashed var(--divider-color, #e0e0e0); border-radius: 10px; }
      .empty-state ha-icon { --mdc-icon-size: 32px; color: var(--primary-color); margin-bottom: 12px; }
      .empty-state p { max-width: 36ch; margin: 8px 0 0; color: var(--secondary-text-color); line-height: 1.6; font-size: 13px; }
      .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
      @container (min-width: 520px) {
        .hour-grid { grid-template-columns: repeat(12, minmax(0, 1fr)); }
      }
      @container (max-width: 350px) {
        .hour-grid { grid-template-columns: repeat(6, minmax(0, 1fr)); }
        .plan-card { padding: 12px; }
        .plan-modes { grid-template-columns: 1fr; }
        .plan-actions { justify-content: space-between; width: 100%; }
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

  _toggleView(view) {
    if (!this.config) return;
    const event = new CustomEvent('config-changed', {
      detail: { config: { ...this.config, view } },
      bubbles: true,
      composed: true,
    });
    this.dispatchEvent(event);
  }

  render() {
    if (!this.hass || !this.config) {
      return html``;
    }

    const currentView = this.config.view || DEFAULT_VIEW;

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
        <div class="field">
          <label>View</label>
          <div class="view-options">
            ${VIEWS.map(
              (view) => html`
                <button
                  class="view-option ${currentView === view.key ? 'active' : ''}"
                  @click=${() => this._toggleView(view.key)}
                >
                  ${view.label}
                </button>
              `,
            )}
          </div>
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
      .view-options {
        display: flex;
        gap: 8px;
      }
      .view-option {
        padding: 6px 12px;
        border-radius: 4px;
        border: 1px solid var(--divider-color, #e0e0e0);
        background: var(--card-background-color, #fff);
        color: var(--primary-text-color);
        cursor: pointer;
      }
      .view-option.active {
        background: var(--primary-color);
        color: var(--text-primary-color, #fff);
        border-color: var(--primary-color);
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
      description: 'Settings and schedule card for the KEBA Heat Pump Modbus integration',
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
