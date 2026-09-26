from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any, Dict, List

import voluptuous as vol

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util.dt import now as dt_now

from .const import (
    DATA_SCHEDULE_MANAGER,
    DEVICE_NAME_MAP,
    DOMAIN,
    SCHEDULE_MAX_PLANS,
    SCHEDULE_STORAGE_VERSION,
    SERVICE_ADD_SCHEDULE,
    SERVICE_REMOVE_SCHEDULE,
    SERVICE_SET_SCHEDULE_ENABLED,
    SERVICE_SET_SCHEDULE_HOUR,
    SERVICE_SET_SCHEDULE_NAME,
    SERVICE_SET_SCHEDULE_OFF_MODE,
    SERVICE_SET_SCHEDULE_ON_MODE,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "{domain}_{entry_id}_schedules"

ATTR_PLAN_ID = "plan_id"
ATTR_NAME = "name"
ATTR_ENABLED = "enabled"
ATTR_OFF_MODE = "off_mode"
ATTR_ON_MODE = "on_mode"
ATTR_HOUR = "hour"
ATTR_ON = "on"

DEFAULT_OFF_MODE = "Hot Water"
DEFAULT_ON_MODE = "Auto Heat"

OPERATING_MODE_ENTITY_KEY = "operating_mode"


@dataclass
class SchedulePlan:
    """A single schedule plan."""

    plan_id: int
    name: str = ""
    enabled: bool = True
    off_mode: str = DEFAULT_OFF_MODE
    on_mode: str = DEFAULT_ON_MODE
    on_hours: List[int] = field(default_factory=list)

    def asdict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScheduleStorage:
    """Root storage model."""

    plans: List[Dict[str, Any]] = field(default_factory=list)


# Global registry of schedule managers keyed by their schedules sensor entity id.
# Used by domain-wide services to find the manager that owns the target entity.
_managers_by_entity_id: Dict[str, "KebaScheduleManager"] = {}


class KebaScheduleManager:
    """Manages schedule plans and applies the system operating mode.

    Plans are persisted via Home Assistant storage. The manager evaluates the
    active schedules every minute and immediately after any plan change.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        entity_prefix: str,
    ) -> None:
        """Initialize the schedule manager."""
        self.hass = hass
        self._entry_id = entry.entry_id
        self._entity_prefix = entity_prefix
        self._store: Store = Store(
            hass,
            SCHEDULE_STORAGE_VERSION,
            STORAGE_KEY.format(domain=DOMAIN, entry_id=entry.entry_id),
        )
        self._plans: Dict[int, SchedulePlan] = {}
        self._unload_callbacks: List[Any] = []
        self._entities: List[Any] = []
        self._scheduled_mode: str | None = None
        self._last_applied_mode: str | None = None
        self._evaluation_lock = asyncio.Lock()

    @property
    def entity_prefix(self) -> str:
        return self._entity_prefix

    @property
    def plans(self) -> Dict[int, SchedulePlan]:
        return self._plans.copy()

    @property
    def scheduled_mode(self) -> str | None:
        return self._scheduled_mode

    @property
    def active(self) -> bool:
        return any(plan.enabled for plan in self._plans.values())

    @property
    def schedules_sensor_entity_id(self) -> str:
        return f"sensor.{self._entity_prefix}_schedules"

    async def async_setup(self) -> None:
        """Load persisted plans and start scheduler."""
        await self._async_load()
        self._start_scheduler()
        # Evaluate once after startup to catch up after HA restart.
        await self._async_evaluate()

    async def async_shutdown(self) -> None:
        """Cancel trackers after the platforms have removed their entities."""
        self.unregister_schedules_sensor_entity_id()
        self._entities.clear()
        for unsub in self._unload_callbacks:
            unsub()
        self._unload_callbacks.clear()

    def register_schedules_sensor_entity_id(self, entity_id: str) -> None:
        """Register the actual entity id once the sensor is added to HA."""
        _managers_by_entity_id[entity_id] = self

    def unregister_schedules_sensor_entity_id(self) -> None:
        """Remove the manager from the global registry."""
        for key, manager in list(_managers_by_entity_id.items()):
            if manager is self:
                _managers_by_entity_id.pop(key, None)

    async def async_setup_sensor_entities(self, async_add_entities: Any) -> None:
        """Create schedule sensor entities; called from sensor platform."""
        entities: List[SensorEntity] = [
            KebaSchedulesSensor(self),
            KebaScheduledModeSensor(self),
        ]
        self._entities.extend(entities)
        async_add_entities(entities)

    async def async_setup_binary_sensor_entities(
        self, async_add_entities: Any
    ) -> None:
        """Create schedule binary sensor entity; called from binary_sensor platform."""
        entity = KebaScheduleActiveBinarySensor(self)
        self._entities.append(entity)
        async_add_entities([entity])

    async def _async_load(self) -> None:
        """Load plans from storage."""
        data = await self._store.async_load()
        self._plans = {}
        if data is None:
            return
        storage = ScheduleStorage(**data)
        for raw in storage.plans:
            try:
                plan = SchedulePlan(**raw)
                self._plans[plan.plan_id] = plan
            except (TypeError, ValueError) as err:
                _LOGGER.warning("Ignoring malformed schedule plan: %s (%s)", raw, err)

    async def _async_save(self) -> None:
        """Persist plans to storage."""
        storage = ScheduleStorage(
            plans=[plan.asdict() for plan in self._plans.values()],
        )
        await self._store.async_save(storage.__dict__)

    def _start_scheduler(self) -> None:
        """Start the periodic evaluation."""
        self._unload_callbacks.append(
            async_track_time_interval(
                self.hass,
                self._async_evaluate_callback,
                timedelta(minutes=1),
            )
        )

    @callback
    def _async_evaluate_callback(self, _now: Any) -> None:
        """Wrap async evaluate for the event tracker."""
        self.hass.async_create_task(self._async_evaluate())

    def _resolve_operating_mode_entity_id(self) -> str | None:
        """Find the system operating_mode select entity for this config entry.

        The select entity unique_id is deterministic: ``{entry_id}_operating_mode``.
        """
        ent_reg = er.async_get(self.hass)
        target_unique_id = f"{self._entry_id}_{OPERATING_MODE_ENTITY_KEY}"
        return ent_reg.async_get_entity_id("select", DOMAIN, target_unique_id)

    async def _async_evaluate(self) -> None:
        """Apply a mode only when the schedule selects a different mode.

        Track successful applications separately from the sensor's target mode.
        That lets us retry after an unavailable entity or failed service call,
        without resending a command while the same mode spans several hours.
        """
        async with self._evaluation_lock:
            target_mode = self._compute_target_mode()
            if self._scheduled_mode != target_mode:
                self._scheduled_mode = target_mode
                self._async_update_entities()

            if target_mode is None:
                self._last_applied_mode = None
                return

            if target_mode == self._last_applied_mode:
                return

            operating_mode_entity = self._resolve_operating_mode_entity_id()
            if operating_mode_entity is None:
                return

            current_state = self.hass.states.get(operating_mode_entity)
            if current_state is None or current_state.state in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                return

            if current_state.state != target_mode:
                try:
                    await self.hass.services.async_call(
                        "select",
                        "select_option",
                        {
                            ATTR_ENTITY_ID: operating_mode_entity,
                            "option": target_mode,
                        },
                        blocking=True,
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.error(
                        "Failed to apply scheduled operating mode '%s': %s",
                        target_mode,
                        err,
                    )
                    return

            self._last_applied_mode = target_mode

    def _compute_target_mode(self) -> str | None:
        """Return the operating mode that should currently be active.

        Enabled plans are evaluated by plan_id (1 = highest priority). If any
        enabled plan has the current hour in on_hours, its on_mode wins.
        Otherwise the off_mode of the lowest enabled plan_id is used.
        Returns None when no plan is enabled.
        """
        enabled_plans = sorted(
            (plan for plan in self._plans.values() if plan.enabled),
            key=lambda p: p.plan_id,
        )
        if not enabled_plans:
            return None

        current_hour = dt_now().hour

        for plan in enabled_plans:
            if current_hour in plan.on_hours:
                return plan.on_mode

        return enabled_plans[0].off_mode

    def _get_plan(self, plan_id: int) -> SchedulePlan:
        if plan_id not in self._plans:
            raise ValueError(f"Plan {plan_id} does not exist")
        return self._plans[plan_id]

    async def _async_update_plan(self, plan: SchedulePlan) -> None:
        """Persist a plan change and re-evaluate immediately."""
        self._plans[plan.plan_id] = plan
        await self._async_save()
        self._async_update_entities()
        await self._async_evaluate()

    @callback
    def _async_update_entities(self) -> None:
        """Request state update for schedule entities."""
        for entity in self._entities:
            entity.async_write_ha_state()

    def _plan_data_for_sensor(self) -> Dict[str, Any]:
        return {
            str(plan.plan_id): {
                "name": plan.name,
                "enabled": plan.enabled,
                "off_mode": plan.off_mode,
                "on_mode": plan.on_mode,
                "on_hours": sorted(plan.on_hours),
            }
            for plan in self._plans.values()
        }

    # ── Service handlers ────────────────────────────────────

    async def _service_add_schedule(self, _call: ServiceCall) -> None:
        """Add a new schedule plan."""
        if len(self._plans) >= SCHEDULE_MAX_PLANS:
            raise ValueError(f"Maximum number of plans ({SCHEDULE_MAX_PLANS}) reached")

        # Find the lowest free plan_id.
        used = set(self._plans.keys())
        plan_id = next(i for i in range(1, SCHEDULE_MAX_PLANS + 1) if i not in used)

        plan = SchedulePlan(plan_id=plan_id)
        self._plans[plan_id] = plan
        await self._async_save()
        self._async_update_entities()
        await self._async_evaluate()

    async def _service_remove_schedule(self, call: ServiceCall) -> None:
        plan_id = call.data[ATTR_PLAN_ID]
        if plan_id not in self._plans:
            raise ValueError(f"Plan {plan_id} does not exist")
        del self._plans[plan_id]
        await self._async_save()
        self._async_update_entities()
        await self._async_evaluate()

    async def _service_set_schedule_name(self, call: ServiceCall) -> None:
        plan = self._get_plan(call.data[ATTR_PLAN_ID])
        plan.name = call.data[ATTR_NAME]
        await self._async_update_plan(plan)

    async def _service_set_schedule_enabled(self, call: ServiceCall) -> None:
        plan = self._get_plan(call.data[ATTR_PLAN_ID])
        plan.enabled = call.data[ATTR_ENABLED]
        await self._async_update_plan(plan)

    async def _service_set_schedule_off_mode(self, call: ServiceCall) -> None:
        plan = self._get_plan(call.data[ATTR_PLAN_ID])
        plan.off_mode = call.data[ATTR_OFF_MODE]
        await self._async_update_plan(plan)

    async def _service_set_schedule_on_mode(self, call: ServiceCall) -> None:
        plan = self._get_plan(call.data[ATTR_PLAN_ID])
        plan.on_mode = call.data[ATTR_ON_MODE]
        await self._async_update_plan(plan)

    async def _service_set_schedule_hour(self, call: ServiceCall) -> None:
        plan = self._get_plan(call.data[ATTR_PLAN_ID])
        hour = call.data[ATTR_HOUR]
        on = call.data[ATTR_ON]
        if on:
            if hour not in plan.on_hours:
                plan.on_hours.append(hour)
                plan.on_hours.sort()
        else:
            plan.on_hours = [h for h in plan.on_hours if h != hour]
        await self._async_update_plan(plan)


# ── Domain-wide services ───────────────────────────────────

SERVICE_SCHEMAS = {
    SERVICE_ADD_SCHEDULE: vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_id}),
    SERVICE_REMOVE_SCHEDULE: vol.Schema(
        {
            vol.Required(ATTR_ENTITY_ID): cv.entity_id,
            vol.Required(ATTR_PLAN_ID): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=SCHEDULE_MAX_PLANS)
            ),
        }
    ),
    SERVICE_SET_SCHEDULE_NAME: vol.Schema(
        {
            vol.Required(ATTR_ENTITY_ID): cv.entity_id,
            vol.Required(ATTR_PLAN_ID): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=SCHEDULE_MAX_PLANS)
            ),
            vol.Required(ATTR_NAME): vol.All(vol.Coerce(str), vol.Length(max=32)),
        }
    ),
    SERVICE_SET_SCHEDULE_ENABLED: vol.Schema(
        {
            vol.Required(ATTR_ENTITY_ID): cv.entity_id,
            vol.Required(ATTR_PLAN_ID): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=SCHEDULE_MAX_PLANS)
            ),
            vol.Required(ATTR_ENABLED): cv.boolean,
        }
    ),
    SERVICE_SET_SCHEDULE_OFF_MODE: vol.Schema(
        {
            vol.Required(ATTR_ENTITY_ID): cv.entity_id,
            vol.Required(ATTR_PLAN_ID): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=SCHEDULE_MAX_PLANS)
            ),
            vol.Required(ATTR_OFF_MODE): cv.string,
        }
    ),
    SERVICE_SET_SCHEDULE_ON_MODE: vol.Schema(
        {
            vol.Required(ATTR_ENTITY_ID): cv.entity_id,
            vol.Required(ATTR_PLAN_ID): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=SCHEDULE_MAX_PLANS)
            ),
            vol.Required(ATTR_ON_MODE): cv.string,
        }
    ),
    SERVICE_SET_SCHEDULE_HOUR: vol.Schema(
        {
            vol.Required(ATTR_ENTITY_ID): cv.entity_id,
            vol.Required(ATTR_PLAN_ID): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=SCHEDULE_MAX_PLANS)
            ),
            vol.Required(ATTR_HOUR): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=23)
            ),
            vol.Required(ATTR_ON): cv.boolean,
        }
    ),
}


async def _handle_service(call: ServiceCall) -> None:
    entity_id = call.data[ATTR_ENTITY_ID]
    manager = _managers_by_entity_id.get(entity_id)
    if manager is None:
        raise ServiceValidationError(
            f"No schedule manager found for {entity_id}. "
            "Reload the KEBA integration and check the schedules entity."
        )
    handler = getattr(manager, f"_service_{call.service}")
    await handler(call)


def async_register_services(hass: HomeAssistant) -> None:
    """Register domain-wide schedule services once per Home Assistant instance."""
    if hass.services.has_service(DOMAIN, SERVICE_ADD_SCHEDULE):
        return

    for service, schema in SERVICE_SCHEMAS.items():
        hass.services.async_register(
            DOMAIN,
            service,
            _handle_service,
            schema,
        )


# ── Entities ───────────────────────────────────────────────

class KebaSchedulesSensor(SensorEntity):
    """Sensor exposing all schedule plans."""

    _attr_has_entity_name = True
    _attr_name = "Schedules"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, manager: KebaScheduleManager) -> None:
        self._manager = manager
        self._attr_unique_id = f"{manager._entry_id}_schedules"
        self._attr_extra_state_attributes = {"keba_key": "schedules"}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._manager.register_schedules_sensor_entity_id(self.entity_id)

    async def async_will_remove_from_hass(self) -> None:
        self._manager.unregister_schedules_sensor_entity_id()
        await super().async_will_remove_from_hass()

    @property
    def native_value(self) -> str:
        return str(len(self._manager.plans))

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        attrs = dict(self._attr_extra_state_attributes or {})
        attrs["plans"] = self._manager._plan_data_for_sensor()
        return attrs

    @property
    def device_info(self) -> Dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, f"{self._manager._entry_id}_system")},
            "name": DEVICE_NAME_MAP.get("system", "System"),
            "manufacturer": "KEBA",
            "model": "Heat Pump (Modbus)",
        }


class KebaScheduledModeSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Scheduled Mode"
    _attr_icon = "mdi:calendar-check"

    def __init__(self, manager: KebaScheduleManager) -> None:
        self._manager = manager
        self._attr_unique_id = f"{manager._entry_id}_scheduled_mode"
        self._attr_extra_state_attributes = {"keba_key": "scheduled_mode"}

    @property
    def native_value(self) -> str | None:
        return self._manager.scheduled_mode

    @property
    def device_info(self) -> Dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, f"{self._manager._entry_id}_system")},
            "name": DEVICE_NAME_MAP.get("system", "System"),
            "manufacturer": "KEBA",
            "model": "Heat Pump (Modbus)",
        }


class KebaScheduleActiveBinarySensor(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Schedule Active"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, manager: KebaScheduleManager) -> None:
        self._manager = manager
        self._attr_unique_id = f"{manager._entry_id}_schedule_active"
        self._attr_extra_state_attributes = {"keba_key": "schedule_active"}

    @property
    def is_on(self) -> bool:
        return self._manager.active

    @property
    def device_info(self) -> Dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, f"{self._manager._entry_id}_system")},
            "name": DEVICE_NAME_MAP.get("system", "System"),
            "manufacturer": "KEBA",
            "model": "Heat Pump (Modbus)",
        }
