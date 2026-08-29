# Tests for 0.19.2, attributing a recovery to a person (ruling #362).
#
# The property that matters: a device that came back because somebody
# handled it must not teach its own rhythm, and a device that came
# back on its own must.

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel import attribution
from custom_components.device_sentinel.const import (
    SYS_DEVICE_HANDLED,
    SYS_DETAIL,
    SYS_KIND,
    SYS_SCOPE,
    SYS_WHEN,
    STACK_ZHA,
    ZHA_HANDLED_TAIL_SECONDS,
)

from .helpers import register_device, setup_coordinator


def _event(device_id, when, kind="device_fully_initialized"):
    return {
        SYS_KIND: SYS_DEVICE_HANDLED,
        SYS_SCOPE: STACK_ZHA,
        SYS_WHEN: when,
        SYS_DETAIL: f"{device_id} {kind}",
    }


def test_a_handling_explains_only_its_own_device():
    """Every ZHA message names exactly one device, so a handling
    reaches that device and no other. A fleet-wide reach here would
    silence real faults on every other device."""
    windows = attribution.windows(([_event("dev_a", 1000.0)]))
    assert len(windows) == 1
    window = windows[0]
    # The stack-wide question must say no: two ZHA devices share a
    # domain and a stack, and those cannot tell them apart.
    assert window.covers("zha", STACK_ZHA) is False
    assert (
        attribution.attribute(
            windows, "zha", STACK_ZHA, 1005.0, 1010.0, "dev_a"
        )
        is window
    )
    assert (
        attribution.attribute(
            windows, "zha", STACK_ZHA, 1005.0, 1010.0, "dev_b"
        )
        is None
    )


def test_a_handling_expires_rather_than_explaining_forever():
    """Nothing writes a closing for a handling. A person who touched
    a device and walked away must not explain its recovery an hour
    later."""
    windows = attribution.windows([_event("dev_a", 1000.0)])
    inside = attribution.attribute(
        windows, "zha", STACK_ZHA,
        1000.0 + ZHA_HANDLED_TAIL_SECONDS - 5, None, "dev_a",
    )
    assert inside is not None
    outside = attribution.attribute(
        windows, "zha", STACK_ZHA,
        1000.0 + ZHA_HANDLED_TAIL_SECONDS + 3600, None, "dev_a",
    )
    assert outside is None


def test_the_measured_gap_is_covered():
    """The message precedes the recovery by two to eight seconds
    across eighteen observed recoveries, and a re-pair runs 34
    seconds end to end. Both must land inside the window."""
    windows = attribution.windows([_event("dev_a", 1000.0)])
    for gap in (2.0, 5.0, 8.0, 15.0, 34.0):
        assert attribution.attribute(
            windows, "zha", STACK_ZHA, 1000.0 + gap, None, "dev_a"
        ) is not None


def test_the_wording_says_what_happened():
    """Not 'a pairing window': ZHA has none, and the report should
    say what was observed."""
    windows = attribution.windows([_event("dev_a", 1000.0)])
    assert attribution.phrase(windows[0]) == "somebody handling the device"


def test_an_event_naming_no_device_is_ignored():
    """A malformed event must not produce a window that reaches
    everything or nothing in an undefined way."""
    for detail in (None, "", "   "):
        row = {
            SYS_KIND: SYS_DEVICE_HANDLED,
            SYS_SCOPE: STACK_ZHA,
            SYS_WHEN: 1000.0,
            SYS_DETAIL: detail,
        }
        assert attribution.windows([row]) == []


def test_it_does_not_disturb_the_other_causes():
    """A handling sits beside the existing windows without changing
    which of them explains what."""
    from custom_components.device_sentinel.const import (
        SYS_BRIDGE_DOWN, SYS_BRIDGE_UP,
    )

    rows = [
        {SYS_KIND: SYS_BRIDGE_DOWN, SYS_SCOPE: STACK_ZHA, SYS_WHEN: 500.0},
        _event("dev_a", 1000.0),
        {SYS_KIND: SYS_BRIDGE_UP, SYS_SCOPE: STACK_ZHA, SYS_WHEN: 1500.0},
    ]
    windows = attribution.windows(rows)
    kinds = sorted(w.kind for w in windows)
    assert kinds == sorted([SYS_BRIDGE_DOWN, SYS_DEVICE_HANDLED])
    # A device silent from 600 is explained by the bridge, not by a
    # handling that happened later to another device.
    window = attribution.attribute(
        windows, "zha", STACK_ZHA, 600.0, 1600.0, "dev_b"
    )
    assert window is not None
    assert window.kind == SYS_BRIDGE_DOWN


async def test_the_coordinator_records_one_event_per_handling(
    hass: HomeAssistant,
):
    """A re-pair fires four or five messages over half a minute, and
    each is the same person at the same device. One event, refreshed,
    rather than five in the brief."""
    device, _ = register_device(hass, "h1", "Handled Device")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._watched[device.id] = STACK_ZHA

    for kind in (
        "device_joined",
        "raw_device_initialized",
        "device_fully_initialized",
        "device_fully_initialized",
    ):
        coord._record_device_handled(device.id, kind)

    events = [
        row
        for row in coord.data.get("system_events", [])
        if row.get(SYS_KIND) == SYS_DEVICE_HANDLED
    ]
    assert len(events) == 1
    assert events[0][SYS_DETAIL].startswith(device.id)


async def test_a_device_we_do_not_watch_is_not_recorded(
    hass: HomeAssistant,
):
    """A device set aside has no verdict to explain, so an event
    about it would be noise in the log a person reads."""
    device, _ = register_device(hass, "h2", "Unwatched")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._watched.pop(device.id, None)
    coord._record_device_handled(device.id, "device_fully_initialized")
    events = [
        row
        for row in coord.data.get("system_events", [])
        if row.get(SYS_KIND) == SYS_DEVICE_HANDLED
    ]
    assert events == []


async def test_a_second_handling_later_is_its_own_event(
    hass: HomeAssistant,
):
    """Two visits to the same device an hour apart are two events,
    not one refreshed forever."""
    from unittest.mock import patch
    from datetime import datetime, timezone

    device, _ = register_device(hass, "h3", "Twice Handled")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._watched[device.id] = STACK_ZHA

    def _at(t):
        return patch(
            "custom_components.device_sentinel.interventions.dt_util.utcnow",
            return_value=datetime.fromtimestamp(t, tz=timezone.utc),
        )

    with _at(1000.0):
        coord._record_device_handled(device.id, "device_joined")
    with _at(1000.0 + ZHA_HANDLED_TAIL_SECONDS + 1):
        coord._record_device_handled(device.id, "device_joined")

    events = [
        row
        for row in coord.data.get("system_events", [])
        if row.get(SYS_KIND) == SYS_DEVICE_HANDLED
    ]
    assert len(events) == 2


def test_the_window_means_exactly_what_it_says():
    """Found by the adversarial round. Every other window carries a
    90 second allowance for the sampler noticing late, which made a
    60 second handling reach 150 seconds forward and 90 backward: it
    explained recoveries that happened before the person touched the
    device. A handling is pushed, not sampled, so it gets none."""
    windows = attribution.windows([_event("dev_a", 1000.0)])
    window = windows[0]
    assert window.in_effect_at(999.0) is False
    assert window.in_effect_at(1000.0) is True
    assert window.in_effect_at(1000.0 + ZHA_HANDLED_TAIL_SECONDS) is True
    assert window.in_effect_at(1000.0 + ZHA_HANDLED_TAIL_SECONDS + 1) is False
    # And the other kinds keep their allowance.
    from custom_components.device_sentinel.const import SYS_BRIDGE_DOWN

    bridge = attribution.Window(SYS_BRIDGE_DOWN, STACK_ZHA, 1000.0, 1060.0)
    assert bridge.in_effect_at(999.0) is True
    assert bridge.in_effect_at(1100.0) is True


# --------------------------------------------- the learning half

# Added after the comparison of 29 August found both candidate
# implementations incomplete in the same way: each explained the
# recovery and neither stopped the gap being learned. The report
# saying "a person handled this" while the daily maximum quietly
# widened as though the device had chosen its own silence is worse
# than saying nothing, because the two disagree and only one of them
# is visible.


async def test_a_handled_gap_is_discarded_and_retracted(
    hass: HomeAssistant,
):
    """The half that was missing. Same treatment as pairing, being
    set aside and maintenance: the verdict says why, and the daily
    maximum the gap just wrote is taken back."""
    from custom_components.device_sentinel.const import (
        DATA_DEVICES,
        DEV_DAILY_MAX,
        DEV_LAST_ACTIVITY,
        DEV_TODAY_MAX,
        LEARNED_HANDLED,
    )

    device, _ = register_device(hass, "lh1", "Handled Device")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [60.0] * 14
    record[DEV_TODAY_MAX] = 60.0
    now = dt_util.utcnow().timestamp()
    record[DEV_LAST_ACTIVITY] = now - 3600.0

    coord._handled_at[device.id] = now - 5.0
    coord._record_activity(device.id, coord.entry.entry_id)

    # The gap was an hour, which would have taught an hour-long
    # rhythm. The retraction pulls it back out, and pulling out the
    # day's largest leaves None, which is the shipped behaviour for
    # pairing and the rest: the day has no learned maximum rather
    # than a false one.
    assert record[DEV_TODAY_MAX] in (None, 60.0)
    episodes = [
        row
        for row in coord.data.get("silence_episodes") or []
        if row.get("device_id") == device.id
    ]
    if episodes:
        assert episodes[-1].get("learned") == LEARNED_HANDLED


async def test_an_untouched_device_still_teaches_its_rhythm(
    hass: HomeAssistant,
):
    """The discard must be narrow. A device nobody touched learns
    exactly as it did before, which is almost every recovery."""
    from custom_components.device_sentinel.const import (
        DATA_DEVICES,
        DEV_DAILY_MAX,
        DEV_LAST_ACTIVITY,
        DEV_TODAY_MAX,
    )

    device, _ = register_device(hass, "lh2", "Untouched Device")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [60.0] * 14
    record[DEV_TODAY_MAX] = 60.0
    now = dt_util.utcnow().timestamp()
    record[DEV_LAST_ACTIVITY] = now - 3600.0

    coord._record_activity(device.id, coord.entry.entry_id)

    assert record[DEV_TODAY_MAX] > 60.0


async def test_a_stale_handling_does_not_discard(hass: HomeAssistant):
    """A person who touched a device and walked away must not
    explain its recovery an hour later."""
    from custom_components.device_sentinel.const import (
        DATA_DEVICES,
        DEV_DAILY_MAX,
        DEV_LAST_ACTIVITY,
        DEV_TODAY_MAX,
        ZHA_HANDLED_TAIL_SECONDS,
    )

    device, _ = register_device(hass, "lh3", "Stale Handling")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [60.0] * 14
    record[DEV_TODAY_MAX] = 60.0
    now = dt_util.utcnow().timestamp()
    record[DEV_LAST_ACTIVITY] = now - 3600.0

    coord._handled_at[device.id] = now - ZHA_HANDLED_TAIL_SECONDS - 1
    coord._record_activity(device.id, coord.entry.entry_id)

    assert record[DEV_TODAY_MAX] > 60.0