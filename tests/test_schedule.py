import asyncio

import pytest

from custom_components.keba_heat_pump_modbus.const import DOMAIN, SCHEDULE_MAX_PLANS
from custom_components.keba_heat_pump_modbus.schedule import (
    KebaScheduleManager,
    SchedulePlan,
    async_register_services,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import ServiceCall


def _make_hass():
    """Create a minimal stub HomeAssistant."""
    import types

    class DummyHass:
        def __init__(self):
            self.data = {DOMAIN: {}}
            self.states = {}
            self._services = {}
            self._call_log = []

        def services_has(self, domain, service):
            return (domain, service) in self._services

        def services_register(self, domain, service, handler, schema):
            # HA determines whether to await the handler from its declaration.
            assert asyncio.iscoroutinefunction(handler)
            self._services[(domain, service)] = handler

        async def async_call(self, domain, service, data, blocking=False):
            self._call_log.append((domain, service, data, blocking))

        async def async_create_task(self, coro):
            await coro

    hass = DummyHass()

    async def services_async_call(domain, service, data, blocking=False):
        await hass.async_call(domain, service, data, blocking)

    hass.services = types.SimpleNamespace(
        has_service=hass.services_has,
        async_register=hass.services_register,
        async_call=services_async_call,
    )
    return hass


def _make_manager(hass, entry_id="entry1"):
    entry = ConfigEntry(data={}, entry_id=entry_id)
    return KebaScheduleManager(hass, entry, "keba_heat_pump_modbus")


def test_plan_defaults():
    plan = SchedulePlan(plan_id=1)
    assert plan.plan_id == 1
    assert plan.name == ""
    assert plan.enabled is True
    assert plan.off_mode == "Hot Water"
    assert plan.on_mode == "Auto Heat"
    assert plan.on_hours == []
    assert plan.weekdays == []


def test_manager_setup_loads_empty_plans():
    async def _run():
        hass = _make_hass()
        manager = _make_manager(hass)
        await manager.async_setup()
        assert manager.plans == {}
        assert manager.active is False
        assert manager.scheduled_mode is None
        await manager.async_shutdown()

    asyncio.run(_run())


def test_manager_add_and_remove_plan():
    async def _run():
        hass = _make_hass()
        manager = _make_manager(hass)
        await manager.async_setup()

        await manager._service_add_schedule(ServiceCall(data={}))
        assert 1 in manager.plans
        assert manager.plans[1].plan_id == 1

        await manager._service_add_schedule(ServiceCall(data={}))
        assert 2 in manager.plans

        await manager._service_remove_schedule(ServiceCall(data={"plan_id": 1}))
        assert 1 not in manager.plans
        assert 2 in manager.plans

        await manager.async_shutdown()

    asyncio.run(_run())


def test_manager_enforces_max_plans():
    async def _run():
        hass = _make_hass()
        manager = _make_manager(hass)
        await manager.async_setup()

        for _ in range(SCHEDULE_MAX_PLANS):
            await manager._service_add_schedule(ServiceCall(data={}))

        assert len(manager.plans) == SCHEDULE_MAX_PLANS

        with pytest.raises(ValueError):
            await manager._service_add_schedule(ServiceCall(data={}))

        await manager.async_shutdown()

    asyncio.run(_run())


def test_manager_set_plan_name_and_modes():
    async def _run():
        hass = _make_hass()
        manager = _make_manager(hass)
        await manager.async_setup()

        await manager._service_add_schedule(ServiceCall(data={}))

        await manager._service_set_schedule_name(
            ServiceCall(data={"plan_id": 1, "name": "Night"})
        )
        assert manager.plans[1].name == "Night"

        await manager._service_set_schedule_off_mode(
            ServiceCall(data={"plan_id": 1, "off_mode": "Standby"})
        )
        assert manager.plans[1].off_mode == "Standby"

        await manager._service_set_schedule_on_mode(
            ServiceCall(data={"plan_id": 1, "on_mode": "Full Auto"})
        )
        assert manager.plans[1].on_mode == "Full Auto"

        await manager.async_shutdown()

    asyncio.run(_run())


def test_manager_set_plan_hours():
    async def _run():
        hass = _make_hass()
        manager = _make_manager(hass)
        await manager.async_setup()

        await manager._service_add_schedule(ServiceCall(data={}))

        await manager._service_set_schedule_hour(
            ServiceCall(data={"plan_id": 1, "hour": 5, "on": True})
        )
        assert manager.plans[1].on_hours == [5]

        await manager._service_set_schedule_hour(
            ServiceCall(data={"plan_id": 1, "hour": 3, "on": True})
        )
        assert manager.plans[1].on_hours == [3, 5]

        await manager._service_set_schedule_hour(
            ServiceCall(data={"plan_id": 1, "hour": 5, "on": False})
        )
        assert manager.plans[1].on_hours == [3]

        await manager.async_shutdown()

    asyncio.run(_run())



def test_compute_target_mode_with_mocked_hour(monkeypatch):
    async def _run():
        hass = _make_hass()
        manager = _make_manager(hass)
        await manager.async_setup()

        await manager._service_add_schedule(ServiceCall(data={}))
        await manager._service_add_schedule(ServiceCall(data={}))

        await manager._service_set_schedule_on_mode(
            ServiceCall(data={"plan_id": 1, "on_mode": "Auto Heat"})
        )
        await manager._service_set_schedule_off_mode(
            ServiceCall(data={"plan_id": 1, "off_mode": "Hot Water"})
        )
        await manager._service_set_schedule_on_mode(
            ServiceCall(data={"plan_id": 2, "on_mode": "Full Auto"})
        )
        await manager._service_set_schedule_off_mode(
            ServiceCall(data={"plan_id": 2, "off_mode": "Standby"})
        )

        await manager._service_set_schedule_hour(
            ServiceCall(data={"plan_id": 2, "hour": 12, "on": True})
        )

        class FakeNow:
            def __init__(self, hour):
                self.hour = hour

            def weekday(self):
                return 0

        monkeypatch.setattr(
            "custom_components.keba_heat_pump_modbus.schedule.dt_now",
            lambda: FakeNow(12),
        )

        # Plan 1 has no on-hours, plan 2 has 12 -> on_mode of plan 2
        assert manager._compute_target_mode() == "Full Auto"

        await manager._service_set_schedule_hour(
            ServiceCall(data={"plan_id": 1, "hour": 12, "on": True})
        )
        # Plan 1 has lower id -> higher priority -> its on_mode wins
        assert manager._compute_target_mode() == "Auto Heat"

        monkeypatch.setattr(
            "custom_components.keba_heat_pump_modbus.schedule.dt_now",
            lambda: FakeNow(5),
        )
        # No plan has 5 -> off_mode of lowest enabled plan (plan 1)
        assert manager._compute_target_mode() == "Hot Water"

        await manager.async_shutdown()

    asyncio.run(_run())


def test_evaluate_applies_mode_when_changed(monkeypatch):
    async def _run():
        hass = _make_hass()
        manager = _make_manager(hass)
        await manager.async_setup()

        await manager._service_add_schedule(ServiceCall(data={}))
        await manager._service_set_schedule_on_mode(
            ServiceCall(data={"plan_id": 1, "on_mode": "Auto Heat"})
        )
        await manager._service_set_schedule_off_mode(
            ServiceCall(data={"plan_id": 1, "off_mode": "Hot Water"})
        )
        await manager._service_set_schedule_hour(
            ServiceCall(data={"plan_id": 1, "hour": 8, "on": True})
        )

        class FakeNow:
            def __init__(self, hour):
                self.hour = hour

            def weekday(self):
                return 0

        monkeypatch.setattr(
            "custom_components.keba_heat_pump_modbus.schedule.dt_now",
            lambda: FakeNow(8),
        )

        # Resolve operating mode entity by faking the entity registry lookup.
        import types

        class FakeRegistry:
            def async_get_entity_id(self, platform, domain, unique_id):
                if unique_id == "entry1_operating_mode":
                    return "select.keba_heat_pump_modbus_operating_mode"
                return None

        fake_er = types.SimpleNamespace(async_get=lambda hass: FakeRegistry())
        monkeypatch.setattr(
            "custom_components.keba_heat_pump_modbus.schedule.er", fake_er
        )

        # Current mode differs from target
        hass.states = {
            "select.keba_heat_pump_modbus_operating_mode": types.SimpleNamespace(
                state="Hot Water"
            )
        }

        await manager._async_evaluate()

        assert len(hass._call_log) == 1
        assert hass._call_log[0][0] == "select"
        assert hass._call_log[0][1] == "select_option"
        assert hass._call_log[0][2]["option"] == "Auto Heat"

        await manager.async_shutdown()

    asyncio.run(_run())


def test_service_registration():
    async def _run():
        hass = _make_hass()
        async_register_services(hass)

        services = [
            "add_schedule",
            "remove_schedule",
            "set_schedule_name",
            "set_schedule_enabled",
            "set_schedule_off_mode",
            "set_schedule_on_mode",
            "set_schedule_hour",
            "set_schedule_weekday",
        ]
        for service in services:
            assert hass.services_has(DOMAIN, service)

        # Second call is a no-op
        async_register_services(hass)
        assert len(hass._services) == len(services)

    asyncio.run(_run())


def test_entities_expose_plan_data():
    async def _run():
        hass = _make_hass()
        manager = _make_manager(hass)
        await manager.async_setup()

        added = []
        await manager.async_setup_sensor_entities(lambda e: added.extend(e))
        await manager.async_setup_binary_sensor_entities(lambda e: added.extend(e))

        schedules_sensor = next(
            e for e in added if e._attr_name == "Schedules"
        )
        active_sensor = next(
            e for e in added if e._attr_name == "Schedule Active"
        )

        assert schedules_sensor.native_value == "0"
        assert schedules_sensor.extra_state_attributes["plans"] == {}
        assert active_sensor.is_on is False

        await manager._service_add_schedule(ServiceCall(data={}))
        assert schedules_sensor.native_value == "1"
        assert "1" in schedules_sensor.extra_state_attributes["plans"]

        await manager.async_shutdown()

    asyncio.run(_run())


def test_remove_nonexistent_plan_raises():
    async def _run():
        hass = _make_hass()
        manager = _make_manager(hass)
        await manager.async_setup()

        with pytest.raises(ValueError):
            await manager._service_remove_schedule(ServiceCall(data={"plan_id": 1}))

        await manager.async_shutdown()

    asyncio.run(_run())


def test_registered_services_update_the_schedules_sensor():
    """Exercise the same registered service route used by the Lovelace card."""
    async def _run():
        hass = _make_hass()
        manager = _make_manager(hass)
        await manager.async_setup()
        added = []
        await manager.async_setup_sensor_entities(added.extend)
        sensor = added[0]
        sensor.entity_id = "sensor.renamed_schedules"
        await sensor.async_added_to_hass()
        async_register_services(hass)

        async def call(service, **data):
            await hass._services[(DOMAIN, service)](
                ServiceCall(domain=DOMAIN, service=service,
                            data={"entity_id": sensor.entity_id, **data})
            )

        try:
            await call("add_schedule")
            assert sensor.native_value == "1"
            await call("set_schedule_name", plan_id=1, name="Morning")
            await call("set_schedule_off_mode", plan_id=1, off_mode="Standby")
            await call("set_schedule_on_mode", plan_id=1, on_mode="Full Auto")
            await call("set_schedule_hour", plan_id=1, hour=7, on=True)
            await call("set_schedule_weekday", plan_id=1, weekday=0, selected=True)
            await call("set_schedule_enabled", plan_id=1, enabled=False)
            assert sensor.extra_state_attributes["plans"]["1"] == {
                "name": "Morning", "enabled": False, "off_mode": "Standby",
                "on_mode": "Full Auto", "on_hours": [7], "weekdays": [0],
            }
            await call("remove_schedule", plan_id=1)
            assert sensor.native_value == "0"
        finally:
            await sensor.async_will_remove_from_hass()
            await manager.async_shutdown()

    asyncio.run(_run())


def test_registered_service_reports_missing_manager():
    from homeassistant.exceptions import ServiceValidationError

    async def _run():
        hass = _make_hass()
        async_register_services(hass)
        with pytest.raises(ServiceValidationError, match="No schedule manager"):
            await hass._services[(DOMAIN, "add_schedule")](
                ServiceCall(domain=DOMAIN, service="add_schedule",
                            data={"entity_id": "sensor.missing_schedules"})
            )

    asyncio.run(_run())


def test_shutdown_does_not_remove_platform_entities_twice():
    from unittest.mock import AsyncMock
    from homeassistant.exceptions import ServiceValidationError

    async def _run():
        hass = _make_hass()
        manager = _make_manager(hass)
        added = []
        await manager.async_setup_sensor_entities(added.extend)
        sensor = added[0]
        sensor.entity_id = "sensor.shutdown_schedules"
        sensor.async_remove = AsyncMock()
        await sensor.async_added_to_hass()
        await manager.async_shutdown()
        sensor.async_remove.assert_not_awaited()
        async_register_services(hass)
        with pytest.raises(ServiceValidationError):
            await hass._services[(DOMAIN, "add_schedule")](
                ServiceCall(domain=DOMAIN, service="add_schedule",
                            data={"entity_id": sensor.entity_id})
            )

    asyncio.run(_run())


def test_integration_registers_services_without_a_loaded_entry(monkeypatch):
    from unittest.mock import AsyncMock
    from importlib import import_module

    integration = import_module("custom_components.keba_heat_pump_modbus")
    hass = _make_hass()
    monkeypatch.setattr(integration, "_async_register_card", AsyncMock())
    assert asyncio.run(integration.async_setup(hass, {})) is True
    assert hass.services_has(DOMAIN, "add_schedule")


def test_schedule_sends_one_command_per_mode_transition(monkeypatch):
    """Several adjacent on-hours and a stale select state must not resend."""
    import types

    async def _run():
        hass = _make_hass()
        manager = _make_manager(hass)
        hour = {"value": 5}
        monkeypatch.setattr(
            "custom_components.keba_heat_pump_modbus.schedule.dt_now",
            lambda: types.SimpleNamespace(hour=hour["value"], weekday=lambda: 0),
        )
        entity_id = "select.system_mode"
        monkeypatch.setattr(
            "custom_components.keba_heat_pump_modbus.schedule.er.async_get",
            lambda _hass: types.SimpleNamespace(
                async_get_entity_id=lambda *_args: entity_id
            ),
        )
        hass.states[entity_id] = types.SimpleNamespace(state="Hot Water")
        await manager.async_setup()
        await manager._service_add_schedule(ServiceCall(data={}))
        for selected_hour in (6, 7, 8):
            await manager._service_set_schedule_hour(
                ServiceCall(data={"plan_id": 1, "hour": selected_hour, "on": True})
            )
        assert hass._call_log == []  # The current Off mode is already correct.

        hour["value"] = 6
        await manager._async_evaluate()
        assert [call[2]["option"] for call in hass._call_log] == ["Auto Heat"]
        assert hass._call_log[0][3] is True  # Wait for the service to finish.

        # Keep the reported mode stale across two more hours and a plan edit.
        for selected_hour in (7, 8):
            hour["value"] = selected_hour
            await manager._async_evaluate()
        await manager._service_set_schedule_name(
            ServiceCall(data={"plan_id": 1, "name": "Morning"})
        )
        assert len(hass._call_log) == 1

        hass.states[entity_id].state = "Auto Heat"
        hour["value"] = 9
        await manager._async_evaluate()
        assert [call[2]["option"] for call in hass._call_log] == [
            "Auto Heat", "Hot Water"
        ]
        hour["value"] = 10
        await manager._async_evaluate()
        assert len(hass._call_log) == 2
        await manager.async_shutdown()

    asyncio.run(_run())


def test_schedule_retries_unavailable_or_failed_change(monkeypatch):
    import types

    async def _run():
        hass = _make_hass()
        manager = _make_manager(hass)
        entity_id = "select.system_mode"
        monkeypatch.setattr(
            "custom_components.keba_heat_pump_modbus.schedule.er.async_get",
            lambda _hass: types.SimpleNamespace(
                async_get_entity_id=lambda *_args: entity_id
            ),
        )
        monkeypatch.setattr(
            "custom_components.keba_heat_pump_modbus.schedule.dt_now",
            lambda: types.SimpleNamespace(hour=6, weekday=lambda: 0),
        )
        manager._plans[1] = SchedulePlan(plan_id=1, on_hours=[6])
        hass.states[entity_id] = types.SimpleNamespace(state="unavailable")
        await manager._async_evaluate()
        assert hass._call_log == []
        assert manager.scheduled_mode == "Auto Heat"

        attempts = []

        async def flaky_call(domain, service, data, blocking=False):
            attempts.append((domain, service, data, blocking))
            if len(attempts) == 1:
                raise RuntimeError("Modbus write failed")

        hass.services.async_call = flaky_call
        hass.states[entity_id].state = "Hot Water"
        await manager._async_evaluate()
        await manager._async_evaluate()
        await manager._async_evaluate()
        assert len(attempts) == 2
        assert all(call[3] is True for call in attempts)
        await manager.async_shutdown()

    asyncio.run(_run())


def test_overlapping_evaluations_do_not_duplicate_commands(monkeypatch):
    import types

    async def _run():
        hass = _make_hass()
        manager = _make_manager(hass)
        entity_id = "select.system_mode"
        monkeypatch.setattr(
            "custom_components.keba_heat_pump_modbus.schedule.er.async_get",
            lambda _hass: types.SimpleNamespace(
                async_get_entity_id=lambda *_args: entity_id
            ),
        )
        monkeypatch.setattr(
            "custom_components.keba_heat_pump_modbus.schedule.dt_now",
            lambda: types.SimpleNamespace(hour=6, weekday=lambda: 0),
        )
        manager._plans[1] = SchedulePlan(plan_id=1, on_hours=[6])
        hass.states[entity_id] = types.SimpleNamespace(state="Hot Water")
        started = asyncio.Event()
        release = asyncio.Event()
        attempts = []

        async def slow_call(domain, service, data, blocking=False):
            attempts.append(data["option"])
            started.set()
            await release.wait()

        hass.services.async_call = slow_call
        first = asyncio.create_task(manager._async_evaluate())
        await started.wait()
        second = asyncio.create_task(manager._async_evaluate())
        release.set()
        await asyncio.gather(first, second)
        assert attempts == ["Auto Heat"]
        await manager.async_shutdown()

    asyncio.run(_run())


def test_legacy_plan_loads_as_every_day_and_persists_weekdays():
    async def _run():
        hass = _make_hass()
        manager = _make_manager(hass)
        manager._store._data = {
            "plans": [{
                "plan_id": 1, "name": "Existing", "enabled": True,
                "off_mode": "Hot Water", "on_mode": "Auto Heat", "on_hours": [8],
            }]
        }
        await manager.async_setup()
        assert manager.plans[1].weekdays == []
        assert manager._plan_data_for_sensor()["1"]["weekdays"] == []
        await manager._service_set_schedule_weekday(
            ServiceCall(data={"plan_id": 1, "weekday": 2, "selected": True})
        )
        await manager._service_set_schedule_weekday(
            ServiceCall(data={"plan_id": 1, "weekday": 0, "selected": True})
        )
        await manager._service_set_schedule_weekday(
            ServiceCall(data={"plan_id": 1, "weekday": 2, "selected": True})
        )
        assert manager.plans[1].weekdays == [0, 2]
        assert manager._store._data["plans"][0]["weekdays"] == [0, 2]
        await manager._service_set_schedule_weekday(
            ServiceCall(data={"plan_id": 1, "weekday": 0, "selected": False})
        )
        await manager._service_set_schedule_weekday(
            ServiceCall(data={"plan_id": 1, "weekday": 2, "selected": False})
        )
        assert manager.plans[1].weekdays == []  # Daily again.
        assert manager._store._data["plans"][0]["weekdays"] == []
        await manager.async_shutdown()

    asyncio.run(_run())


def test_weekdays_filter_on_and_off_modes_before_priority(monkeypatch):
    from datetime import datetime

    async def _run():
        hass = _make_hass()
        manager = _make_manager(hass)
        local = {"now": datetime(2026, 9, 28, 8)}  # Monday
        monkeypatch.setattr(
            "custom_components.keba_heat_pump_modbus.schedule.dt_now",
            lambda: local["now"],
        )
        manager._plans = {
            1: SchedulePlan(
                plan_id=1, weekdays=[0], on_hours=[8],
                on_mode="Auto Heat", off_mode="Standby",
            ),
            2: SchedulePlan(
                plan_id=2, weekdays=[1], on_hours=[8],
                on_mode="Full Auto", off_mode="Hot Water",
            ),
        }
        assert manager.active is True
        assert manager._compute_target_mode() == "Auto Heat"
        local["now"] = datetime(2026, 9, 28, 9)
        assert manager._compute_target_mode() == "Standby"

        local["now"] = datetime(2026, 9, 29, 8)  # Tuesday
        assert manager.active is True
        assert manager._compute_target_mode() == "Full Auto"
        local["now"] = datetime(2026, 9, 29, 9)
        assert manager._compute_target_mode() == "Hot Water"

        local["now"] = datetime(2026, 9, 30, 8)  # Wednesday
        assert manager.active is False
        assert manager._compute_target_mode() is None

        manager._plans[3] = SchedulePlan(
            plan_id=3, on_hours=[8], on_mode="Auto Heat", off_mode="Standby",
        )  # No weekdays selected means every day.
        assert manager.active is True
        assert manager._compute_target_mode() == "Auto Heat"
        local["now"] = datetime(2026, 9, 29, 8)
        assert manager._compute_target_mode() == "Full Auto"  # Plan 2 wins.
        await manager.async_shutdown()

    asyncio.run(_run())


def test_monday_plan_stops_at_midnight_without_off_command(monkeypatch):
    from datetime import datetime
    import types

    async def _run():
        hass = _make_hass()
        manager = _make_manager(hass)
        entity_id = "select.system_mode"
        monkeypatch.setattr(
            "custom_components.keba_heat_pump_modbus.schedule.er.async_get",
            lambda _hass: types.SimpleNamespace(
                async_get_entity_id=lambda *_args: entity_id
            ),
        )
        local = {"now": datetime(2026, 9, 28, 23)}  # Monday
        monkeypatch.setattr(
            "custom_components.keba_heat_pump_modbus.schedule.dt_now",
            lambda: local["now"],
        )
        manager._plans[1] = SchedulePlan(
            plan_id=1, weekdays=[0], on_hours=[0, 23],
        )
        hass.states[entity_id] = types.SimpleNamespace(state="Hot Water")
        await manager._async_evaluate()
        assert [call[2]["option"] for call in hass._call_log] == ["Auto Heat"]
        assert manager.active is True

        local["now"] = datetime(2026, 9, 29, 0)  # Tuesday
        await manager._async_evaluate()
        assert manager.scheduled_mode is None
        assert manager.active is False
        assert len(hass._call_log) == 1  # No Monday Off mode on Tuesday.

        local["now"] = datetime(2026, 10, 5, 0)  # Next Monday
        await manager._async_evaluate()
        assert manager.scheduled_mode == "Auto Heat"
        assert len(hass._call_log) == 2
        await manager.async_shutdown()

    asyncio.run(_run())
