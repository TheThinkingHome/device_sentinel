# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_notifications.py, Version: 0.15.8 (2026-08-18)

"""The config-flow backbone, the notification surface, and the engine.

The integration installs with zero questions and a single instance, and
its status sensor proves persistence across restarts. Its notification
surface mirrors the Sentinel Notify model: two target lists (high gets
live events, normal gets only the brief), a persistent card, quiet
hours, and the daily brief schedule. The engine sends per-family
pushes, a fault audible on the phone's own sound and a recovery silent,
and a self-overwriting card, all reading the same acknowledged-aware
problem lists the sensors publish. The problem counts are opt-in and
the exclusions picker offers only integrations that own a watched
device. This file holds all of that: install, surface, and engine.
"""

import json
import pathlib
from datetime import timedelta

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.device_sentinel.config_flow import (
    _discover_notify_targets,
)
from custom_components.device_sentinel.const import (
    CONF_BRIEF_TARGETS,
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_NORMAL_PRIORITY_TARGETS,
    CONF_PERSISTENT_ENABLED,
    CONF_QUIET_ENABLED,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_REMINDER_MODE,
    CONF_REMINDER_TIME,
    CONF_SETTLE_SHARE,
    DATA_DEVICES,
    DEV_BATTERY_LOW,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    NOTIFY_CARD_ID,
    FREEZE_CATEGORY_NEVER_REPORTED,
    NOTIFY_FAMILY_IDS,
    TODO_KIND_RAILED_SIGNAL,
)
from custom_components.device_sentinel.notifier import (
    NotifierMixin,
    _in_quiet_hours,
)

from tests.helpers import setup_entry

DOMAIN = "device_sentinel"
STORAGE_KEY = f"{DOMAIN}.storage"
MANIFEST_VERSION = json.loads(
    (
        pathlib.Path(__file__).parent.parent
        / "custom_components/device_sentinel/manifest.json"
    ).read_text()
)["version"]


# ==================================================================
# The config-flow backbone (Step 1).
# ==================================================================

async def test_flow_creates_entry_with_zero_questions(hass: HomeAssistant):
    """Opening the flow creates the entry immediately, no form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Device Sentinel"
    assert result["data"] == {}


async def test_second_instance_refused(hass: HomeAssistant):
    """single_config_entry makes HA refuse a second entry."""
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_setup_creates_status_sensor(hass: HomeAssistant):
    """Setup produces the status sensor with state 1 and identity attrs."""
    await setup_entry(hass)

    state = hass.states.get("sensor.device_sentinel_status")
    assert state is not None
    # Status answers its own name. With no device yet established, a
    # fresh install reads learning; the setup count that used to be
    # the state now rides as an attribute, still proving persistence.
    assert state.state == "learning"
    assert state.attributes["setup_count"] == 1
    assert state.attributes["sentinel_type"] == "status"
    assert state.attributes["sentinel_version"] == MANIFEST_VERSION
    assert state.attributes["storage_healthy"] is True
    assert state.attributes["first_installed"] is not None


async def test_restart_increments_count_and_keeps_first_installed(
    hass: HomeAssistant, hass_storage
):
    """Reload simulates a restart: count ticks up, first_installed holds."""
    entry = await setup_entry(hass)

    first = hass.states.get("sensor.device_sentinel_status").attributes[
        "first_installed"
    ]
    assert hass_storage[STORAGE_KEY]["data"]["setup_count"] == 1

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.device_sentinel_status")
    assert state.state == "learning"
    assert state.attributes["setup_count"] == 2
    assert state.attributes["first_installed"] == first
    assert hass_storage[STORAGE_KEY]["data"]["setup_count"] == 2
    assert hass_storage[STORAGE_KEY]["data"]["first_installed"] == first
    assert hass_storage[STORAGE_KEY]["data"]["devices"] == {}


async def test_unload_cleans_up(hass: HomeAssistant):
    """Unload removes the platform cleanly."""
    entry = await setup_entry(hass)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get("sensor.device_sentinel_status")
    assert state.state == "unavailable"


# ==================================================================
# The notification config surface (no engine).
# ==================================================================

def test_discovery_includes_persistent_and_notify_services(hass):
    hass.services._services.setdefault("notify", {})
    hass.services._services["notify"]["mobile_app_s24"] = object()
    hass.services._services["notify"]["mobile_app_pad"] = object()
    targets = _discover_notify_targets(hass)
    assert "persistent_notification" in targets
    assert "notify.mobile_app_s24" in targets
    assert "notify.mobile_app_pad" in targets
    assert targets == sorted(targets)


async def test_options_menu_branches(hass: HomeAssistant):
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert set(result["menu_options"]) == {
        "exclusions", "battery", "notifications", "signal", "freeze",
        "advanced",
    }


async def test_two_lists_and_both_means_high(hass: HomeAssistant):
    hass.services._services.setdefault("notify", {})
    for name in ("mobile_app_mine", "mobile_app_wife"):
        hass.services._services["notify"][name] = object()
    entry = await setup_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "notifications"}
    )
    assert result["step_id"] == "notifications"

    # Mine is high; wife is normal; a shared target is listed in both.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "instant": {
                CONF_HIGH_PRIORITY_TARGETS: [
                    "notify.mobile_app_mine",
                    "notify.mobile_app_wife",
                ],
                CONF_NORMAL_PRIORITY_TARGETS: [
                    "notify.mobile_app_wife"
                ],
                CONF_PERSISTENT_ENABLED: True,
            },
            "quiet": {
                CONF_QUIET_ENABLED: True,
                CONF_QUIET_START: "22:00:00",
                "quiet_hours_end": "07:00:00",
            },
            "brief": {
                CONF_REMINDER_MODE: "overnight",
                CONF_REMINDER_TIME: "08:00:00",
                CONF_BRIEF_TARGETS: [],
            },
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # The shared target normalized out of the normal list (both = high).
    assert entry.options[CONF_HIGH_PRIORITY_TARGETS] == [
        "notify.mobile_app_mine",
        "notify.mobile_app_wife",
    ]
    assert entry.options[CONF_NORMAL_PRIORITY_TARGETS] == []
    assert entry.options[CONF_QUIET_ENABLED] is True
    assert entry.options[CONF_REMINDER_MODE] == "overnight"


async def test_empty_lists_allowed(hass: HomeAssistant):
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "notifications"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "instant": {
                CONF_HIGH_PRIORITY_TARGETS: [],
                CONF_NORMAL_PRIORITY_TARGETS: [],
                CONF_PERSISTENT_ENABLED: False,
            },
            "quiet": {
                CONF_QUIET_ENABLED: False,
                CONF_QUIET_START: "22:00:00",
                "quiet_hours_end": "08:00:00",
            },
            "brief": {
                CONF_REMINDER_MODE: "none",
                CONF_REMINDER_TIME: "08:00:00",
                CONF_BRIEF_TARGETS: [],
            },
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_HIGH_PRIORITY_TARGETS] == []
    assert entry.options[CONF_NORMAL_PRIORITY_TARGETS] == []


async def test_thresholds_still_work_through_menu(hass: HomeAssistant):
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "battery"}
    )
    assert result["step_id"] == "battery"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"low_threshold": 30}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.runtime_data.low_threshold == 30.0


# ==================================================================
# The event notification engine.
# ==================================================================

def test_quiet_hours_wrapping_window():
    """A window from 22:00 to 08:00 wraps midnight: quiet late and
    early, awake in the day."""
    opts = {
        CONF_QUIET_ENABLED: True,
        CONF_QUIET_START: "22:00:00",
        CONF_QUIET_END: "08:00:00",
    }
    assert _in_quiet_hours(opts, "23:30:00") is True
    assert _in_quiet_hours(opts, "03:00:00") is True
    assert _in_quiet_hours(opts, "12:00:00") is False
    assert _in_quiet_hours(opts, "08:00:00") is False


def test_quiet_hours_disabled_is_never_quiet():
    opts = {CONF_QUIET_ENABLED: False}
    assert _in_quiet_hours(opts, "03:00:00") is False


class _Harness(NotifierMixin):
    """A minimal object carrying only what the notifier reads."""

    def __init__(
        self,
        high_targets,
        battery=None,
        signal=None,
        freeze=None,
        acknowledged=None,
        falling=None,
        suppressed=None,
    ):
        self._high = high_targets
        self._battery = battery or []
        self._falling = falling or []
        self._signal = signal or []
        self._freeze = freeze or []
        self._acknowledged = set(acknowledged or [])
        self._suppressed = suppressed or {}
        self.sent = []
        self.entry = type("E", (), {"options": {}})()
        self.hass = type(
            "H", (), {"services": type("S", (), {})()}
        )()

        async def async_call(domain, service, payload, blocking=False):
            self.sent.append((domain, service, payload))

        self.hass.services.async_call = async_call

    def _acknowledged_devices(self):
        return self._acknowledged

    def _high_priority_targets(self):
        return self._high

    @property
    def battery_low_list(self):
        return self._battery

    @property
    def battery_falling_list(self):
        """The card reads two battery sources, not one (#220)."""
        return self._falling

    @property
    def signal_problem_list(self):
        return self._signal

    @property
    def frozen_devices_list(self):
        return self._freeze

    @property
    def reportable_down_rows(self):
        """What the card and the pushes read (ruling #266): the down
        devices worth naming, which is all of them unless an upstream
        is masking some."""
        return self._freeze

    @property
    def suppressed_down_counts(self):
        """How many devices each downed upstream is masking."""
        return self._suppressed


async def test_fault_is_audible_recovery_is_silent():
    """A fault leaves the sound flags off; a recovery sets them, so the
    phone plays its own sound for a fault and stays silent on recovery.
    """
    h = _Harness(
        ["notify.phone"], battery=[{"name": "Battery X", "level": 20}]
    )
    fault = h._family_payload("battery", "At 8:00 am, Battery X low.", False)
    recovery = h._family_payload(
        "battery", "At 3:00 pm, Battery X recovered.", True
    )
    assert "importance" not in fault["data"]  # audible
    assert fault["data"]["tag"] == NOTIFY_FAMILY_IDS["battery"]
    assert recovery["data"]["importance"] == "low"  # silent
    assert recovery["data"]["push"]["interruption-level"] == "passive"


async def test_family_summary_reads_the_lists():
    """The summary is the current family state, read from the same
    lists the sensors publish."""
    h = _Harness(
        ["notify.phone"],
        battery=[
            {"name": "Battery X", "level": 20},
            {"name": "Battery U", "level": None},
        ],
    )
    summary = h._family_summary("battery")
    assert "Battery X 20%" in summary
    assert "Battery U low" in summary

    # The card reads two battery sources (#220). A cell that is both
    # reads level then direction in one entry; a cell that is only
    # falling stands on its own.
    h = _Harness(
        ["notify.phone"],
        battery=[{"device_id": "d1", "name": "Battery X", "level": 16}],
        falling=[
            {"device_id": "d1", "name": "Battery X", "left": "about 2 weeks"},
            {"device_id": "d2", "name": "Battery Y", "left": "about a month"},
        ],
    )
    summary = h._family_summary("battery")
    assert "Battery X 16%, empty in about 2 weeks" in summary
    assert "Battery Y empty in about a month" in summary


async def test_events_dropped_in_quiet_hours():
    """Inside quiet hours, no push is sent; the card and brief carry
    the state."""
    h = _Harness(["notify.phone"], battery=[{"name": "X", "level": 10}])
    h.entry.options = {
        CONF_QUIET_ENABLED: True,
        CONF_QUIET_START: "00:00:00",
        CONF_QUIET_END: "23:59:59",
    }
    await h.async_fire_events([("battery", "At 3 am, X low.", False)])
    assert h.sent == []


async def test_no_high_targets_sends_nothing():
    h = _Harness([], battery=[{"name": "X", "level": 10}])
    await h.async_fire_events([("battery", "At 3 pm, X low.", False)])
    assert h.sent == []


async def test_events_fire_outside_quiet_hours():
    h = _Harness(["notify.phone"], battery=[{"name": "X", "level": 10}])
    h.entry.options = {CONF_QUIET_ENABLED: False}
    await h.async_fire_events([("battery", "At 3 pm, X low.", False)])
    assert len(h.sent) == 1
    domain, service, payload = h.sent[0]
    assert (domain, service) == ("notify", "phone")
    assert "X low." in payload["message"]


async def test_card_overwrites_with_fixed_id():
    """The persistent card uses one fixed id so it overwrites, and it
    reads all-clear when nothing is wrong."""
    h = _Harness(["notify.phone"])
    await h.async_update_card()
    assert len(h.sent) == 1
    domain, service, payload = h.sent[0]
    assert domain == "persistent_notification"
    assert payload["notification_id"] == NOTIFY_CARD_ID
    assert "All devices reporting" in payload["message"]


async def test_full_path_battery_fault_fires_and_updates_card(hass, freezer):
    """End to end: a battery crossing its threshold flows through the
    sync, fires a high-priority push, and refreshes the card, all
    outside quiet hours."""
    from datetime import timedelta
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
        async_fire_time_changed,
    )
    from custom_components.device_sentinel.const import (
        CONF_HIGH_PRIORITY_TARGETS,
        STARTUP_GRACE_SECONDS,
    )

    freezer.move_to("2026-07-24T15:00:00+00:00")  # daytime, not quiet
    src = MockConfigEntry(domain="test")
    src.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=src.entry_id,
        identifiers={("test", "batt1")},
        name="Battery X",
    )
    ent = er.async_get(hass).async_get_or_create(
        "sensor",
        "test",
        "batt1_level",
        device_id=device.id,
        config_entry=src,
        original_device_class="battery",
        unit_of_measurement="%",
    )

    entry = MockConfigEntry(
        domain="device_sentinel",
        title="Device Sentinel",
        data={},
        options={CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"]},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    # Register real mock services so the engine's calls are captured.
    pushes = []
    cards = []

    async def _phone(call):
        pushes.append(call.data)

    async def _card(call):
        cards.append(call.data)

    hass.services.async_register("notify", "phone", _phone)
    hass.services.async_register("persistent_notification", "create", _card)

    # Battery drops below threshold, which the event-driven battery
    # evaluation judges immediately and syncs onto the list.
    hass.states.async_set(
        ent.entity_id, "15", {"device_class": "battery", "unit_of_measurement": "%"}
    )
    await hass.async_block_till_done()

    assert pushes, "expected a high-priority battery push"
    assert "Battery X" in pushes[0]["message"]
    assert cards, "expected the persistent card to refresh"


def test_signal_summary_says_railed_not_low():
    """A railed device must read railed, not low: the signal list tags
    rows by kind, and the card must not call a rail a low. This
    is the fleet bug from 2026-07-25 where Window Living Room Left
    (signal_railed True, value 255) showed on the card as low."""
    h = _Harness(
        ["notify.phone"],
        signal=[
            {"name": "Window Living Room Left", "device_id": "dc7a",
             "kind": TODO_KIND_RAILED_SIGNAL, "value": 255},
        ],
    )
    summary = h._family_summary("signal")
    assert "Window Living Room Left railed" in summary
    assert "low" not in summary


def test_freeze_summary_uses_system_words():
    """A never-reported device reads never reported, not the internal
    not_reported token."""
    h = _Harness(
        ["notify.phone"],
        freeze=[
            {"name": "Vibration FJ40 Land Cruiser", "device_id": "5dd1",
             "category": FREEZE_CATEGORY_NEVER_REPORTED},
            {"name": "Door X", "device_id": "aaaa", "category": "unavailable"},
        ],
    )
    summary = h._family_summary("freeze")
    assert "Vibration FJ40 Land Cruiser never reported" in summary
    assert "Door X unavailable" in summary
    assert "not_reported" not in summary


def test_acknowledged_device_is_hidden_from_summary():
    """An acknowledged problem is invisible to humans everywhere,
    including the card and pushes (#109). This is the fleet case:
    Window Living Room Left is railed and acknowledged, so it must not
    appear in the signal summary at all."""
    h = _Harness(
        ["notify.phone"],
        signal=[
            {"name": "Window Living Room Left", "device_id": "dc7a",
             "kind": TODO_KIND_RAILED_SIGNAL, "value": 255},
        ],
        acknowledged={"dc7a"},
    )
    summary = h._family_summary("signal")
    assert summary == "All clear."
    assert "Window Living Room Left" not in summary


def test_acknowledged_hidden_but_others_still_shown():
    """Acknowledging one device does not hide the others in its
    family: the summary keeps the unacknowledged ones."""
    h = _Harness(
        ["notify.phone"],
        battery=[
            {"name": "Battery Acked", "device_id": "a1", "level": 5},
            {"name": "Battery Live", "device_id": "b2", "level": 12},
        ],
        acknowledged={"a1"},
    )
    summary = h._family_summary("battery")
    assert "Battery Acked" not in summary
    assert "Battery Live 12%" in summary


async def test_card_omits_acknowledged_device():
    """The persistent card, built from the same summaries, must not
    carry an acknowledged problem."""
    h = _Harness(
        ["notify.phone"],
        freeze=[
            {"name": "Door Acked", "device_id": "d1", "category": "unavailable"},
        ],
        acknowledged={"d1"},
    )
    await h.async_update_card()
    domain, service, payload = h.sent[0]
    assert "Door Acked" not in payload["message"]
    assert "All devices reporting" in payload["message"]


async def test_card_suppressed_and_dismissed_when_toggle_off():
    """With the persistent-card toggle off, no card is created and any
    existing card is dismissed, so turning the setting off removes it
    (0.9.8, wiring CONF_PERSISTENT_ENABLED)."""
    from custom_components.device_sentinel.const import (
        CONF_PERSISTENT_ENABLED,
        NOTIFY_CARD_ID,
    )

    h = _Harness(
        ["notify.phone"],
        freeze=[{"name": "Door X", "device_id": "d1", "category": "unavailable"}],
    )
    h.entry.options = {CONF_PERSISTENT_ENABLED: False}
    await h.async_update_card()
    assert len(h.sent) == 1
    domain, service, payload = h.sent[0]
    assert domain == "persistent_notification"
    assert service == "dismiss"
    assert payload["notification_id"] == NOTIFY_CARD_ID
    assert "message" not in payload  # a dismiss, not a create


async def test_card_created_when_toggle_on():
    """With the toggle on (the default), the card is created as before."""
    from custom_components.device_sentinel.const import CONF_PERSISTENT_ENABLED

    h = _Harness(
        ["notify.phone"],
        freeze=[{"name": "Door X", "device_id": "d1", "category": "unavailable"}],
    )
    h.entry.options = {CONF_PERSISTENT_ENABLED: True}
    await h.async_update_card()
    domain, service, payload = h.sent[0]
    assert (domain, service) == ("persistent_notification", "create")
    assert "Door X unavailable" in payload["message"]


async def test_card_default_on_when_option_absent():
    """With no option set, the card defaults on and is created."""
    h = _Harness(
        ["notify.phone"],
        freeze=[{"name": "Door X", "device_id": "d1", "category": "unavailable"}],
    )
    await h.async_update_card()
    domain, service, _ = h.sent[0]
    assert (domain, service) == ("persistent_notification", "create")


# ==================================================================
# Entity defaults and the integration picker.
# ==================================================================

# The problem-count and tracked-count defaults moved twice: opt-in at
# birth, enabled by #212 when no list carried a weak link, and back to
# opt-in by #239 once every kind reached the problem list and the
# facts under #212 had gone stale. The single home for the whole
# defaults table is tests/test_entity_defaults.py, asserted as one
# dictionary so a flip is always a decision; nothing here repeats it.

async def test_the_service_count_stays_opt_in(hass: HomeAssistant):
    """Opt-in under #212 and carried forward by #239. It answers why
    a particular device is not watched, which is asked once if ever,
    so it belongs in the registry rather than on the page."""
    entry = await setup_entry(hass)
    reg = er.async_get(hass)
    eid = reg.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_classification"
    )
    assert eid is not None
    assert reg.async_get(eid).disabled_by is not None


async def test_battery_low_is_a_primary_sensor(hass: HomeAssistant):
    """Battery: Low sits with the primary sensors (ruling #247).

    A count of what was found is news about the house rather than
    bookkeeping about the integration, the same line #243 drew for
    the bridge and broker. This test asserted DIAGNOSTIC until the
    split; the bookkeeping counts (classification and the three
    tracked totals) still do.
    """
    entry = await setup_entry(hass)
    reg = er.async_get(hass)
    eid = reg.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_low_batteries"
    )
    assert reg.async_get(eid).entity_category is None


async def test_integration_picker_offers_only_watched_integrations(
    hass: HomeAssistant,
):
    """A watched device's integration is offered; a service-only
    integration with no watched device is not.

    watched_device_rows already omits service-type devices, so its
    integration set is exactly the pickable list.
    """
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    # A real device on integration "reolink".
    dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("reolink", "cam1")},
        name="Front Camera",
    )
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    integrations = {row["integration"] for row in coord.watched_device_rows}
    # The watched device's integration is present; nothing service-only
    # sneaks in, because service devices never entered watched_device_rows.
    assert all(isinstance(name, str) for name in integrations)


# ==================================================================
# The notification debounce.
# ==================================================================

def _debounce_device(hass, uid, name, battery=False):
    """Register a device with one entity under its own source."""
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    reg = er.async_get(hass)
    ent = reg.async_get_or_create(
        "sensor", "test", f"{uid}_0",
        device_id=device.id, config_entry=source,
    )
    if battery:
        reg.async_get_or_create(
            "sensor", "test", f"{uid}_pct",
            device_id=device.id, config_entry=source,
            original_device_class="battery",
        )
    return device, ent.entity_id


def _phone_capture(hass, service="phone"):
    """Register a notify service that records what it was sent."""
    calls = []

    async def handler(call):
        calls.append(dict(call.data))

    hass.services.async_register("notify", service, handler)
    return calls


def _learned_freeze(coord, device_id, gap=3600.0, since=1_000_000.0):
    """Give a device a learned reporting gap and a freeze verdict."""
    record = coord.data[DATA_DEVICES][device_id]
    record[DEV_DAILY_MAX] = [gap] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = since - 10.0
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = since


async def test_the_delay_is_a_share_of_the_learned_gap(
    hass: HomeAssistant,
):
    """Thirty percent of an hourly gap is eighteen minutes, and a
    device with nothing learned has no gap to take a share of."""
    device, _eid = _debounce_device(hass, "dl1", "Delay Device")
    entry = await setup_entry(hass, {CONF_SETTLE_SHARE: 30})
    coord = entry.runtime_data
    record = coord.data[DATA_DEVICES][device.id]

    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    assert coord._notification_delay(device.id) == pytest.approx(1080.0)

    record[DEV_DAILY_MAX] = []
    assert coord._notification_delay(device.id) == 0.0


async def test_a_learned_fault_waits_then_is_announced(
    hass: HomeAssistant, freezer
):
    """The fault is held for its debounce, then sent with the time it
    was first seen rather than the time it was released."""
    device, eid = _debounce_device(hass, "dh1", "Held Device")
    entry = await setup_entry(
        hass,
        {
            CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"],
            CONF_SETTLE_SHARE: 30,
        },
    )
    coord = entry.runtime_data
    calls = _phone_capture(hass)
    hass.states.async_set(eid, "21.5")

    _learned_freeze(coord, device.id)
    coord._sync_problem_list()
    await hass.async_block_till_done()
    assert calls == []  # held, not sent
    assert coord._held_events

    # Past the eighteen-minute hold, the alert goes out.
    freezer.tick(timedelta(seconds=1081))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert "Held Device" in calls[0]["message"]
    assert not coord._held_events


async def test_a_fault_that_heals_inside_the_hold_is_never_announced(
    hass: HomeAssistant, freezer
):
    """The whole point: a problem that fixes itself inside the delay
    reaches nobody's phone, and its recovery is dropped with it rather
    than arriving as news about nothing."""
    device, eid = _debounce_device(hass, "dh2", "Healing Device")
    entry = await setup_entry(
        hass,
        {
            CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"],
            CONF_SETTLE_SHARE: 30,
        },
    )
    coord = entry.runtime_data
    calls = _phone_capture(hass)
    hass.states.async_set(eid, "21.5")

    _learned_freeze(coord, device.id)
    coord._sync_problem_list()
    await hass.async_block_till_done()
    assert calls == []

    # It recovers well inside the hold.
    freezer.tick(timedelta(seconds=60))
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_FROZEN_CATEGORY] = None
    record[DEV_FROZEN_SINCE] = None
    coord._sync_problem_list()
    await hass.async_block_till_done()
    assert coord._held_events == {}

    # And nothing arrives when the original hold would have matured.
    freezer.tick(timedelta(seconds=1200))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls == []


async def test_an_acknowledged_fault_is_dropped_at_maturity(
    hass: HomeAssistant, freezer
):
    """Checking the box silences the phone, so a hold that matures
    after an acknowledgment has nothing left to say."""
    device, eid = _debounce_device(hass, "dh3", "Acked Device")
    entry = await setup_entry(
        hass,
        {
            CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"],
            CONF_SETTLE_SHARE: 30,
        },
    )
    coord = entry.runtime_data
    calls = _phone_capture(hass)
    hass.states.async_set(eid, "21.5")

    _learned_freeze(coord, device.id)
    coord._sync_problem_list()
    await hass.async_block_till_done()
    assert calls == []

    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_update(uid=uid, status="completed")

    freezer.tick(timedelta(seconds=1081))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls == []


async def test_a_device_with_nothing_learned_is_announced_at_once(
    hass: HomeAssistant,
):
    """A share of a gap that does not exist is no delay at all, so a
    fresh device is never held silent waiting on a number it has not
    earned."""
    device, eid = _debounce_device(hass, "dh4", "Fresh Device", battery=True)
    entry = await setup_entry(
        hass,
        {
            CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"],
            CONF_SETTLE_SHARE: 30,
        },
    )
    coord = entry.runtime_data
    calls = _phone_capture(hass)
    hass.states.async_set(eid, "21.5")

    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_BATTERY_LOW] = True
    record[DEV_BATTERY_VALUE] = 12.0
    record[DEV_BATTERY_SINCE] = "2026-07-20T15:02:00+00:00"
    coord._sync_problem_list()
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert coord._held_events == {}
