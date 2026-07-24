# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v090_pairing_and_email.py, Version: 0.9.0 (2026-07-24)

"""0.9.0 tests: episodes in the prose, title case, and the email.

Three changes that arrived together. The brief's history told a stop
and its recovery as two sentences in strict time order, so a live
brief put two unrelated devices between them (#134). Headings were
sentence case where the house style is title case (#133). And the
brief now leaves the machine: the document channel opens while the
event-triggered engine stays shut (#132).
"""

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    BRIEF_TRIGGER,
    CONF_BRIEF_TARGETS,
    CONF_REMINDER_MODE,
    DATA_INCIDENTS,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    INC_CAUSE,
    INC_DEVICE_ID,
    INC_DURATION,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_WHEN,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    PERSISTENT_TARGET,
    RECOVERY_CAUSE_UNOBSERVED,
    REMINDER_MODE_DAILY,
    REMINDER_MODE_NONE,
    REMINDER_MODE_OVERNIGHT,
    TODO_KIND_FROZEN,
    TODO_KIND_NOT_REPORTED,
)

DOMAIN = "device_sentinel"


def _register(hass, uid, name):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    plain = er.async_get(hass).async_get_or_create(
        "sensor", "test", f"{uid}_0",
        device_id=device.id, config_entry=source,
    )
    return device, plain.entity_id


async def _coordinator(hass, options: dict[str, Any] | None = None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Device Sentinel",
        data={},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _seed(coord, rows):
    """Place incidents inside the current brief window, in order.

    Offsets are measured forward from the window's own start rather
    than back from now, because the window runs brief-to-brief and a
    row placed an hour ago falls outside it whenever the test runs
    within an hour of the brief time.
    """
    now = dt_util.utcnow().timestamp()
    start = coord._brief_window_start(now)
    seeded = []
    for step, (device_id, name, event, extra) in enumerate(rows, start=1):
        row = {
            INC_DEVICE_ID: device_id,
            INC_NAME: name,
            INC_KIND: TODO_KIND_FROZEN,
            INC_EVENT: event,
            INC_WHEN: min(start + step, now),
            INC_CAUSE: None,
            INC_DURATION: None,
        }
        row.update(extra)
        seeded.append(row)
    coord.data[DATA_INCIDENTS] = seeded


# ------------------------------------------------------------ pairing


async def test_a_stop_and_its_recovery_are_one_sentence(
    hass: HomeAssistant, read_brief
):
    """#134: the brief told them four sentences apart in a live file."""
    coord = await _coordinator(hass)
    _seed(coord, [
        ("d1", "Presence Guest", INCIDENT_OPENED, {}),
        ("d1", "Presence Guest", INCIDENT_RESOLVED,
         {INC_DURATION: 4.1 * 3600, INC_CAUSE: "reboot"}),
    ])
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = read_brief(hass)
    prose = text[text.index("## In Short"): text.index("## Now")]
    assert (
        "Presence Guest stopped reporting at" in prose
        and "and recovered 4.1h later, revived by a reboot." in prose
    )
    # One sentence, so the name is said once rather than twice.
    assert prose.count("Presence Guest") == 1


async def test_the_recovery_clock_time_is_dropped_from_a_pair(
    hass: HomeAssistant, read_brief
):
    """The opening time plus the span gives it, and the table below
    carries exact times for anyone looking one up."""
    coord = await _coordinator(hass)
    _seed(coord, [
        ("d1", "Paired Sensor", INCIDENT_OPENED, {}),
        ("d1", "Paired Sensor", INCIDENT_RESOLVED, {INC_DURATION: 3600.0}),
    ])
    await hass.async_add_executor_job(coord._write_reports, "test")
    prose = read_brief(hass)
    prose = prose[prose.index("## In Short"): prose.index("## Now")]
    assert "and recovered 1.0h later." in prose
    assert "recovered at" not in prose


async def test_a_pair_holds_together_across_other_devices(
    hass: HomeAssistant, read_brief
):
    """The failure this fixes: strict time order split every pair as
    soon as a second device broke in between."""
    coord = await _coordinator(hass)
    _seed(coord, [
        ("d1", "First Device", INCIDENT_OPENED, {}),
        ("d2", "Second Device", INCIDENT_OPENED, {}),
        ("d1", "First Device", INCIDENT_RESOLVED, {INC_DURATION: 4 * 3600.0}),
        ("d2", "Second Device", INCIDENT_RESOLVED,
         {INC_DURATION: 4 * 3600.0}),
    ])
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = read_brief(hass)
    prose = text[text.index("## In Short"): text.index("## Now")]
    sentences = [
        part.strip()
        for part in prose.split(". ")
        if "Device" in part
    ]
    assert len(sentences) == 2, prose
    # Ordered by when each episode began, so the narrative still
    # runs forward without splitting a pair.
    assert prose.index("First Device") < prose.index("Second Device")
    assert prose.count("First Device") == 1
    assert prose.count("Second Device") == 1


async def test_two_breaks_in_one_window_give_two_episodes(
    hass: HomeAssistant, read_brief
):
    """Each resolution matches the most recent unmatched opening, so
    a device that breaks twice is not crossed into one long silence."""
    coord = await _coordinator(hass)
    _seed(coord, [
        ("d1", "Twice Sensor", INCIDENT_OPENED, {}),
        ("d1", "Twice Sensor", INCIDENT_RESOLVED, {INC_DURATION: 3600.0}),
        ("d1", "Twice Sensor", INCIDENT_OPENED, {}),
        ("d1", "Twice Sensor", INCIDENT_RESOLVED,
         {INC_DURATION: 2 * 3600.0}),
    ])
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = read_brief(hass)
    prose = text[text.index("## In Short"): text.index("## Now")]
    assert prose.count("Twice Sensor") == 2
    assert "and recovered 1.0h later." in prose
    assert "and recovered 2.0h later." in prose


async def test_a_recovery_older_than_the_window_stands_alone(
    hass: HomeAssistant, read_brief
):
    """Door Master's case: the silence began before the window opened,
    so there is no opening to pair with and the lone wording stays."""
    coord = await _coordinator(hass)
    _seed(coord, [
        ("d1", "Door Master", INCIDENT_RESOLVED,
         {INC_DURATION: 4.3 * 3600, INC_CAUSE: RECOVERY_CAUSE_UNOBSERVED}),
    ])
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = read_brief(hass)
    prose = text[text.index("## In Short"): text.index("## Now")]
    assert "Door Master recovered at" in prose
    assert "after 4.3h, no intervention recorded." in prose


async def test_a_never_reported_device_is_never_paired(
    hass: HomeAssistant, read_brief
):
    """It has no moment of failure, so joining its opening to a
    recovery would read "had never reported and recovered 3.6d
    later". Two sentences instead."""
    coord = await _coordinator(hass)
    _seed(coord, [
        ("d1", "Ghost Device", INCIDENT_OPENED,
         {INC_KIND: TODO_KIND_NOT_REPORTED}),
        ("d1", "Ghost Device", INCIDENT_RESOLVED,
         {INC_KIND: TODO_KIND_NOT_REPORTED, INC_DURATION: 3600.0}),
    ])
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = read_brief(hass)
    prose = text[text.index("## In Short"): text.index("## Now")]
    assert "has never reported since it was discovered." in prose
    assert "Ghost Device recovered at" in prose


# --------------------------------------------------------- title case


async def test_every_generated_heading_is_title_case(
    hass: HomeAssistant, read_brief
):
    """#133: one file fixed and three left would be worse than none."""
    _register(hass, "t1", "Title Sensor")
    coord = await _coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "test")
    brief = read_brief(hass)
    assert "# Device Sentinel Daily Brief" in brief
    assert "## In Short" in brief
    assert "## Last 24 Hours" in brief

    directory = hass.config.path("device_sentinel", "diagnostics")
    for name, heading in (
        ("device_telemetry.md", "Learned Statistics"),
        ("classification.md", "Classification"),
        ("silence_episodes.md", "Silence Episodes"),
    ):
        with open(f"{directory}/{name}", encoding="utf-8") as handle:
            text = handle.read()
        assert heading in text, name
        assert heading.lower() not in text.replace(
            heading.lower().replace(" ", "_"), ""
        ), f"{name} still carries a sentence-case heading"


# --------------------------------------------------------- the email


def _capture(hass, service="brief_mail"):
    """Register a notify service that records what it was sent."""
    calls: list[dict[str, Any]] = []

    async def handler(call):
        calls.append(dict(call.data))

    hass.services.async_register("notify", service, handler)
    return calls


async def test_the_brief_is_emailed_whole(hass: HomeAssistant):
    """The document, not a summary of it: the same text the file
    carries, with the In Short prose leading it."""
    calls = _capture(hass)
    coord = await _coordinator(
        hass,
        {
            CONF_REMINDER_MODE: REMINDER_MODE_DAILY,
            CONF_BRIEF_TARGETS: ["notify.brief_mail"],
        },
    )
    await coord._on_brief_time(None)
    await hass.async_block_till_done()
    assert len(calls) == 1
    sent = calls[0]
    assert sent["title"] == "Device Sentinel Daily Brief"
    assert sent["message"].startswith("# Device Sentinel Daily Brief")
    assert "## In Short" in sent["message"]
    assert "## Last 24 Hours" in sent["message"]
    assert "<h2>In Short</h2>" in sent["data"]["html"]


async def test_an_in_progress_brief_is_never_sent(hass: HomeAssistant):
    """#135: a regenerate or a midnight rewrite produces an unfinished
    document, and mailing those would deliver one day several times."""
    calls = _capture(hass)
    coord = await _coordinator(
        hass,
        {
            CONF_REMINDER_MODE: REMINDER_MODE_DAILY,
            CONF_BRIEF_TARGETS: ["notify.brief_mail"],
        },
    )
    text = await hass.async_add_executor_job(coord._write_reports, "test")
    assert text is None
    assert await coord.async_send_brief(text) == 0
    assert not calls


async def test_never_means_never(hass: HomeAssistant):
    calls = _capture(hass)
    coord = await _coordinator(
        hass,
        {
            CONF_REMINDER_MODE: REMINDER_MODE_NONE,
            CONF_BRIEF_TARGETS: ["notify.brief_mail"],
        },
    )
    await coord._on_brief_time(None)
    await hass.async_block_till_done()
    assert not calls


async def test_problems_only_stays_quiet_on_a_clear_day(
    hass: HomeAssistant,
):
    """The mode says only when something needs attention, and the
    brief is still written to disk either way."""
    calls = _capture(hass)
    coord = await _coordinator(
        hass,
        {
            CONF_REMINDER_MODE: REMINDER_MODE_OVERNIGHT,
            CONF_BRIEF_TARGETS: ["notify.brief_mail"],
        },
    )
    await coord._on_brief_time(None)
    await hass.async_block_till_done()
    assert not calls


async def test_problems_only_sends_when_something_is_wrong(
    hass: HomeAssistant,
):
    calls = _capture(hass)
    device, entity_id = _register(hass, "p1", "Problem Sensor")
    coord = await _coordinator(
        hass,
        {
            CONF_REMINDER_MODE: REMINDER_MODE_OVERNIGHT,
            CONF_BRIEF_TARGETS: ["notify.brief_mail"],
        },
    )
    hass.states.async_set(entity_id, "on")
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = dt_util.utcnow().timestamp() - 3600
    coord._sync_problem_list()
    await coord._on_brief_time(None)
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert "Problem Sensor" in calls[0]["message"]


async def test_one_dead_target_does_not_silence_the_others(
    hass: HomeAssistant,
):
    """A brief that cannot reach one mail server must still reach the
    rest, and must still be on disk either way."""
    good = _capture(hass, "good_mail")

    async def broken(call):
        raise OSError("no route to host")

    hass.services.async_register("notify", "dead_mail", broken)
    coord = await _coordinator(
        hass,
        {
            CONF_REMINDER_MODE: REMINDER_MODE_DAILY,
            CONF_BRIEF_TARGETS: ["notify.dead_mail", "notify.good_mail"],
        },
    )
    text = await hass.async_add_executor_job(
        coord._write_reports, BRIEF_TRIGGER
    )
    assert await coord.async_send_brief(text) == 1
    assert len(good) == 1


async def test_the_persistent_notification_gets_no_html(
    hass: HomeAssistant,
):
    """It takes a title and a message and nothing else, so offering
    it a data key it does not know would fail the whole send."""
    coord = await _coordinator(
        hass,
        {
            CONF_REMINDER_MODE: REMINDER_MODE_DAILY,
            CONF_BRIEF_TARGETS: [PERSISTENT_TARGET],
        },
    )
    payload = coord._brief_payload(PERSISTENT_TARGET, "# Title")
    assert "data" not in payload
    assert coord._brief_payload("notify.mail", "# Title")["data"]


# ------------------------------------------------------ the rendering


async def test_the_renderer_makes_tables_and_escapes_content(
    hass: HomeAssistant,
):
    """A mail client shows a pipe table as a wall of text, so the
    tables are rendered; anything a device name could carry is
    escaped rather than injected."""
    coord = await _coordinator(hass)
    html = coord._brief_html(
        "# Device Sentinel Daily Brief\n"
        "\n"
        "Jul 24, 7:00 AM.\n"
        "\n"
        "## Now\n"
        "\n"
        "| DEVICE | PROBLEM |\n"
        "|---|---|\n"
        "| Sensor <script> | stopped reporting |\n"
    )
    assert "<h1>Device Sentinel Daily Brief</h1>" in html
    assert "<h2>Now</h2>" in html
    assert "<p>Jul 24, 7:00 AM.</p>" in html
    assert "<th" in html and "DEVICE</th>" in html
    assert "<td" in html and "stopped reporting</td>" in html
    # The separator row is grammar, not data.
    assert "---" not in html
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
