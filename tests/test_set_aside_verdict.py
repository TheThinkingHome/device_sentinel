"""The stale verdict of a set-aside device, and what it cost.

Reproduce the 27 minute recovery on a five minute absence.

James's ZHA coordinator, 30 August 2026. It has no entities and
never will, so the startup grace watches it, it is judged never
reported, and five minutes later grace closes and it is set aside.
The incident timeline recorded both cycles honestly, 300 seconds
each. The recovery event announced 27 minutes, which is the span
from the first cycle's opening to the second cycle's close, and that
is what a voice assistant read out.

These tests report as well as assert, so the mechanism is visible
whatever the outcome.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    EVENT_RECOVERED,
)

from tests.helpers import register_device, setup_coordinator

OBSERVED = "2026-07-08T00:00:00+00:00"


def _catch_recoveries(hass):
    seen = []
    hass.bus.async_listen(EVENT_RECOVERED, lambda event: seen.append(event.data))
    return seen


async def _never_reporting_device(hass, name: str):
    device, _eids = register_device(hass, name)
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    record = coord.data[DATA_DEVICES].setdefault(device.id, {})
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    record[DEV_FIRST_OBSERVED] = OBSERVED
    record[DEV_FROZEN_CATEGORY] = None
    record[DEV_FROZEN_SINCE] = None
    return coord, device, record


def _set_aside(coord, device_id: str) -> None:
    """Take a device out of the watched set, as grace closing does
    to a device with no entities."""
    coord._watched.pop(device_id, None)


def _watch_again(coord, device_id: str, integration: str = "zha") -> None:
    coord._watched[device_id] = integration


async def test_the_sweep_alone_leaves_a_set_aside_verdict_standing(
    hass: HomeAssistant,
):
    """The root of it, shown at the sweep: it walks only watched
    devices, so nothing there can clear a departed one. The clearing
    belongs to the rebuild, and its own test follows."""
    coord, device, record = await _never_reporting_device(hass, "co1")
    coord._judge_all_devices()
    coord._sync_problem_list()
    assert record[DEV_FROZEN_CATEGORY] is not None
    stamped = record[DEV_FROZEN_SINCE]
    assert stamped is not None

    _set_aside(coord, device.id)
    coord._judge_all_devices()
    coord._sync_problem_list()

    print(
        "AFTER SET ASIDE: category=%r since=%r"
        % (record[DEV_FROZEN_CATEGORY], record[DEV_FROZEN_SINCE])
    )
    assert record[DEV_FROZEN_SINCE] == stamped, (
        "the sweep cleared it, so the rebuild is not the only place "
        "this can happen and the fix is in the wrong module"
    )


async def test_a_recovery_is_timed_from_the_absence_that_ended(
    hass: HomeAssistant,
):
    """The duration fix, through the path that still announces.

    A device with a problem standing, watched throughout, whose
    problem then clears. The item's own stamp is deliberately set
    far in the past, as it would be for a device that has been on
    the list a long time; the announcement must measure the incident
    that just closed, not that stamp.
    """
    recoveries = _catch_recoveries(hass)
    coord, device, record = await _never_reporting_device(hass, "co2")

    coord._judge_all_devices()
    coord._sync_problem_list()
    items = [
        i for i in coord.data["todo_items"] if i["device_id"] == device.id
    ]
    assert items, "no item was raised"

    # Age the item's own stamp by 23 minutes without touching the
    # incident, which is the state a carried-forward stamp leaves.
    kinds = items[0]["kinds"]
    for kind in list(kinds):
        kinds[kind] = kinds[kind] - 1368.0

    # The device speaks. It never left the watched set.
    record[DEV_EVENT_COUNT] = 1
    record[DEV_LAST_ACTIVITY] = 1_788_000_000.0
    record[DEV_FROZEN_CATEGORY] = None
    record[DEV_FROZEN_SINCE] = None
    coord._judge_all_devices()
    coord._sync_problem_list()
    await hass.async_block_till_done()

    mine = [r for r in recoveries if r.get("device_id") == device.id]
    assert mine, "a watched device's recovery was not announced"
    reported = mine[-1].get("down_for")
    print("REPORTED:", reported, "seconds")
    assert reported is not None
    assert reported < 60, (
        f"the recovery reported {reported}s, measured from the item's "
        "stamp rather than from the incident that closed"
    )


# ------------------- the three fixes, driven through the real paths


async def test_a_device_set_aside_loses_its_verdict(hass: HomeAssistant):
    """Fix one, through the registry rebuild rather than by poking
    the watched set: a device that leaves it drops its verdict."""
    coord, device, record = await _never_reporting_device(hass, "co3")
    coord._judge_all_devices()
    assert record[DEV_FROZEN_CATEGORY] is not None
    assert record[DEV_FROZEN_SINCE] is not None

    coord._clear_verdicts_for_set_aside({device.id: ("Name", "zha", "x")})

    assert record[DEV_FROZEN_CATEGORY] is None
    assert record[DEV_FROZEN_SINCE] is None


async def test_the_record_itself_survives_the_clearing(
    hass: HomeAssistant,
):
    """It clears the judgment, never the history."""
    coord, device, record = await _never_reporting_device(hass, "co4")
    record[DEV_EVENT_COUNT] = 42
    record[DEV_FIRST_OBSERVED] = OBSERVED
    coord._clear_verdicts_for_set_aside({device.id: ("Name", "zha", "x")})
    assert record[DEV_EVENT_COUNT] == 42
    assert record[DEV_FIRST_OBSERVED] == OBSERVED


async def test_a_loaded_integration_ends_the_grace_exemption(
    hass: HomeAssistant,
):
    """Fix three: the clock alone was too blunt."""
    coord, _device, _record = await _never_reporting_device(hass, "co5")
    # The integration Device Sentinel itself runs under is loaded.
    assert coord._integration_finished_loading(
        coord.entry.domain
    ) is True
    # An integration with no entries at all has not finished.
    assert coord._integration_finished_loading("nothing_here") is False
    assert coord._integration_finished_loading(None) is False
    assert coord._integration_finished_loading("") is False


async def test_the_cause_is_bounded_to_the_incident_that_closed(
    hass: HomeAssistant,
):
    """Fix four: the bound of #228 was defeated at this call site.

    The resolution is written before the cause is asked, so asking
    the log again returned nothing and the bound fell to zero, which
    let any episode on the device answer. An episode far older than
    this incident must not explain it.
    """
    coord, device, record = await _never_reporting_device(hass, "co6")
    coord._judge_all_devices()
    coord._sync_problem_list()
    opened = record[DEV_FROZEN_SINCE]

    # An episode that ended long before this incident opened.
    coord.data.setdefault("silence_episodes", []).append(
        {
            "device_id": device.id,
            "name": "Ancient",
            "since": opened - 900_000.0,
            "basis": 600.0,
            "window": 1800.0,
            "ended": "intervention (reboot)",
            "at": opened - 800_000.0,
            "lag": None,
            "learned": "yes",
            "taint_seconds": None,
            "signal": None,
        }
    )

    causes = []
    hass.bus.async_listen(
        EVENT_RECOVERED, lambda event: causes.append(event.data)
    )
    # The device speaks again, watched throughout, so the recovery
    # is a real one and does announce (ruling #368).
    record[DEV_EVENT_COUNT] = 1
    record[DEV_LAST_ACTIVITY] = 1_788_000_000.0
    record[DEV_FROZEN_CATEGORY] = None
    record[DEV_FROZEN_SINCE] = None
    coord._judge_all_devices()
    coord._sync_problem_list()
    await hass.async_block_till_done()

    mine = [c for c in causes if c.get("device_id") == device.id]
    assert mine, "no recovery fired"
    print("RESOLVED BY:", mine[-1].get("resolved_by"))
    # A null cause reads unknown rather than being guessed into a
    # self-recovery (ruling #291), so unknown is the right answer
    # here: nobody knows, and the ancient reboot is not an answer.
    assert mine[-1].get("resolved_by") == "unknown", (
        f"an episode nine days older than the incident explained it: "
        f"{mine[-1].get('resolved_by')}"
    )
