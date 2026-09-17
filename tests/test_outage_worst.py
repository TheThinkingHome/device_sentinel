# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_outage_worst.py, Version: 0.21.12 (2026-09-17)

"""The daily brief tells an outage by its worst moment (ruling #442).

The second fleet's brief of 16 September said the Wi-Fi network went
down "74 devices behind it", and said the same 74 when it came back.
74 is every device tied to the network. 56 went down. The brief now
records the most devices an outage had down at once, the figure its
problem list row reached at its peak, and says it beside the total
when the outage ends. A row from an older release, which carries no
such figure, reads as it always did.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    DATA_SYSTEM_EVENTS,
    SYS_BRIDGE_UP,
    SYS_BROKER_UP,
    SYS_DEVICES,
    SYS_DURATION,
    SYS_INTEGRATION_UP,
    SYS_KIND,
    SYS_SCOPE,
    SYS_WHEN,
    SYS_WIFI_UP,
    SYS_WORST,
)
from tests.helpers import setup_coordinator
from tests.test_outage_wording import _bridge_back_with
from tests.test_wifi_outage import _declared, _fall, _house, _rise
from tests.test_wifi_recovery import _tick


def _last(coord, kind):
    return [
        row for row in coord.data[DATA_SYSTEM_EVENTS]
        if row[SYS_KIND] == kind
    ][-1]


# ------------------------------------------------------ the recording


async def test_a_wifi_outage_records_its_worst_moment(
    hass: HomeAssistant, freezer
):
    coord, trackers, _devices, _untied = await _house(hass, 14)
    first = await _declared(hass, coord, trackers[:8], freezer, count=8)
    coord._note_upstream_peaks()
    # A second wave, as the second fleet had five minutes in.
    for tracker in trackers[8:12]:
        await _fall(hass, tracker)
    coord._note_upstream_peaks()
    for tracker in trackers[:12]:
        await _rise(hass, tracker)
    await _tick(coord, first + 120.0)
    await _tick(coord, first + 180.0)
    await _tick(coord, first + 240.0)
    assert coord.wifi_down_at is None

    row = _last(coord, SYS_WIFI_UP)
    assert row[SYS_DEVICES] == 14
    assert row[SYS_WORST] == 12


async def test_a_bridge_outage_records_its_worst_moment(
    hass: HomeAssistant, freezer
):
    coord, _began = await _bridge_back_with(hass, freezer, down=3, back=0)
    row = _last(coord, SYS_BRIDGE_UP)
    assert row[SYS_WORST] == 3
    assert row[SYS_DEVICES] == 3


async def test_a_new_outage_starts_its_count_again(
    hass: HomeAssistant, freezer
):
    """The worst moment belongs to one outage, not to the upstream."""
    coord = await setup_coordinator(hass)
    coord._upstream_peak["z2m"] = 40
    coord._begin_upstream_peak("z2m")
    assert coord._upstream_worst("z2m") == 0


# ------------------------------------------------------ the brief


async def test_the_brief_says_the_worst_beside_the_total(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    base = {SYS_WHEN: 1789595686.0, SYS_DURATION: 610.0}
    wifi = {**base, SYS_KIND: SYS_WIFI_UP, SYS_SCOPE: "wifi",
            SYS_DEVICES: 74, SYS_WORST: 56}
    # The network came back when its recovery began, which has its own
    # line (ruling #444); this one is the outage ending.
    assert coord._system_event_sentence(wifi).startswith(
        "The WiFi outage ended at"
    )
    assert coord._system_event_sentence(wifi).endswith(
        "after 10m. 56 of its 74 devices went down."
    )
    assert coord._system_event_phrase(wifi) == (
        "WiFi outage ended after 10m, 56 of 74 devices went down"
    )
    bridge = {**base, SYS_KIND: SYS_BRIDGE_UP, SYS_SCOPE: "zha",
              SYS_DEVICES: 55, SYS_WORST: 14}
    assert coord._system_event_sentence(bridge).endswith(
        "after 10m. 14 of its 55 devices went down."
    )
    assert coord._system_event_phrase(bridge) == (
        "zha bridge came back after 10m, 14 of 55 devices went down"
    )
    integration = {**base, SYS_KIND: SYS_INTEGRATION_UP,
                   SYS_SCOPE: "zwave_js", SYS_DEVICES: 17, SYS_WORST: 1}
    assert coord._system_event_sentence(integration).endswith(
        "after 10m. 1 of its 17 devices went down."
    )
    broker = {**base, SYS_KIND: SYS_BROKER_UP, SYS_SCOPE: "mqtt",
              SYS_DEVICES: 77, SYS_WORST: 77}
    assert coord._system_event_phrase(broker) == (
        "MQTT broker came back after 10m, 77 of 77 devices went down"
    )


async def test_an_outage_that_took_nothing_says_so(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    row = {SYS_WHEN: 1789595686.0, SYS_DURATION: 60.0,
           SYS_KIND: SYS_BRIDGE_UP, SYS_SCOPE: "z2m",
           SYS_DEVICES: 77, SYS_WORST: 0}
    assert coord._system_event_sentence(row).endswith(
        "after 1m. None of its 77 devices went down."
    )


async def test_an_older_row_reads_as_it_always_did(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    row = {SYS_WHEN: 1789595686.0, SYS_DURATION: 610.0,
           SYS_KIND: SYS_WIFI_UP, SYS_SCOPE: "wifi", SYS_DEVICES: 74}
    assert coord._system_event_sentence(row).endswith(
        "after 10m, 74 devices behind it."
    )
    assert coord._system_event_phrase(row) == "WiFi network came back after 10m"


# ------------------------------------------------------ hostile rows


def test_the_storage_check_knows_the_worst_field():
    from custom_components.device_sentinel.normalise import (
        damaged_rows,
        fill_missing_row_fields,
    )

    good = {SYS_WHEN: 1.0, SYS_KIND: SYS_WIFI_UP, SYS_SCOPE: "wifi",
            SYS_DURATION: 5.0, "detail": None, SYS_DEVICES: 74,
            SYS_WORST: 56}
    old = {SYS_WHEN: 1.0, SYS_KIND: SYS_WIFI_UP, SYS_SCOPE: "wifi",
           SYS_DURATION: 5.0, "detail": None, SYS_DEVICES: 74}
    bad = dict(good, **{SYS_WORST: "fifty-six"})
    data = {DATA_SYSTEM_EVENTS: [good, old, bad]}
    assert damaged_rows(data) == {DATA_SYSTEM_EVENTS: [2]}
    fill_missing_row_fields(data)
    # An old row is not given a worst figure it never had.
    assert SYS_WORST not in old

