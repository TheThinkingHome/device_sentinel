# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v096_notifier.py, Version: 0.9.7 (2026-07-25)

"""0.9.6 tests: the event notification engine.

The engine sends per-family high-priority pushes and a self-overwriting
persistent card. These tests prove the rules that make it correct: a
fault is audible and a recovery is silent, events are dropped inside
quiet hours (the card and brief carry them), a family push overwrites
its own last message through a fixed tag, and normal-priority targets
receive no events at all.
"""

from custom_components.device_sentinel.notifier import (
    NotifierMixin,
    _in_quiet_hours,
)
from custom_components.device_sentinel.const import (
    CONF_QUIET_ENABLED,
    CONF_QUIET_END,
    CONF_QUIET_START,
    NOTIFY_CARD_ID,
    NOTIFY_FAMILY_IDS,
)


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

    def __init__(self, high_targets, battery=None, signal=None, freeze=None, acknowledged=None):
        self._high = high_targets
        self._battery = battery or []
        self._signal = signal or []
        self._freeze = freeze or []
        self._acknowledged = set(acknowledged or [])
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
    def signal_problem_list(self):
        return self._signal

    @property
    def frozen_devices_list(self):
        return self._freeze


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
    rows by kind='rail', and the card must not call a rail a low. This
    is the fleet bug from 2026-07-25 where Window Living Room Left
    (signal_railed True, value 255) showed on the card as low."""
    h = _Harness(
        ["notify.phone"],
        signal=[
            {"name": "Window Living Room Left", "device_id": "dc7a", "kind": "rail", "value": 255},
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
            {"name": "Vibration FJ40 Land Cruiser", "device_id": "5dd1", "category": "not_reported"},
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
            {"name": "Window Living Room Left", "device_id": "dc7a", "kind": "rail", "value": 255},
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
