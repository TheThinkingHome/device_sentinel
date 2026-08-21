# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_brief_email.py, Version: 0.11.8 (2026-08-04)

"""Sending the brief, and the page a mail client renders.

One of the files split out of test_email_brief.py, which had
grown larger than any source file in the project (ruling #203).
The seam is the subject, the same rule the source split followed.
Helpers are carried to every file that calls them rather than
pooled, so each file reads on its own.
"""




from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    BRIEF_TRIGGER,
    CONF_BRIEF_TARGETS,
    CONF_REMINDER_MODE,
    DATA_TODO_ITEMS,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    PERSISTENT_TARGET,
    REMINDER_MODE_DAILY,
    REMINDER_MODE_NONE,
    REMINDER_MODE_OVERNIGHT,
    REPORT_SIGNAL_URL,
    TODO_DEVICE_ID,
    TODO_KINDS,
    TODO_KIND_FROZEN,
    TODO_SORT_NAME,
    TODO_STATUS,
)

from tests.helpers import setup_coordinator

DOMAIN = "device_sentinel"

def _register(hass, uid, name, battery=False, source=None):
    """A device with a plain sensor and, optionally, a battery entity.

    Returns (device, entity_id, source). The source is returned so a
    test can register a second device on the same integration, which
    the intervention-attribution tests rely on.
    """
    if source is None:
        source = MockConfigEntry(domain="test", title=f"Source {uid}")
        source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    reg = er.async_get(hass)
    plain = reg.async_get_or_create(
        "sensor", "test", f"{uid}_0",
        device_id=device.id, config_entry=source,
    )
    if battery:
        reg.async_get_or_create(
            "sensor", "test", f"{uid}_pct",
            device_id=device.id, config_entry=source,
            original_device_class="battery",
        )
    return device, plain.entity_id, source


def _text(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _capture(hass, service="brief_mail"):
    """Register a notify service that records what it was sent."""
    calls = []

    async def handler(call):
        calls.append(dict(call.data))

    hass.services.async_register("notify", service, handler)
    return calls


async def test_the_brief_is_emailed_whole(hass: HomeAssistant):
    """The document, not a summary of it: the same text the file
    carries, with the In Short prose leading it."""
    calls = _capture(hass)
    coord = await setup_coordinator(
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
    document, and mailing those would deliver one day several times.

    The guard has to return before the send loop, not merely produce a
    zero count. If a None text reached the loop, building its payload
    would raise and the bare except would swallow it, leaving sent at
    zero and a broken guard looking healthy. So this pins the loop is
    never entered: _brief_payload is never called for an unfinished
    brief.
    """
    calls = _capture(hass)
    coord = await setup_coordinator(
        hass,
        {
            CONF_REMINDER_MODE: REMINDER_MODE_DAILY,
            CONF_BRIEF_TARGETS: ["notify.brief_mail"],
        },
    )
    text = await hass.async_add_executor_job(coord._write_reports, "test")
    assert text is None

    payloads = []
    original = coord._brief_payload
    coord._brief_payload = lambda target, body: payloads.append(body) or original(
        target, body
    )
    try:
        assert await coord.async_send_brief(text) == 0
    finally:
        coord._brief_payload = original
    # The loop was never entered, so no payload was ever built. Under
    # the whole guard this holds; drop the not-text half and the loop
    # runs, _brief_payload is called with None, and this fails.
    assert payloads == []
    assert not calls


async def test_never_means_never(hass: HomeAssistant):
    calls = _capture(hass)
    coord = await setup_coordinator(
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
    coord = await setup_coordinator(
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
    device, entity_id, _ = _register(hass, "p1", "Problem Sensor")
    coord = await setup_coordinator(
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
    coord = await setup_coordinator(
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
    coord = await setup_coordinator(
        hass,
        {
            CONF_REMINDER_MODE: REMINDER_MODE_DAILY,
            CONF_BRIEF_TARGETS: [PERSISTENT_TARGET],
        },
    )
    payload = coord._brief_payload(PERSISTENT_TARGET, "# Title")
    assert "data" not in payload
    assert coord._brief_payload("notify.mail", "# Title")["data"]


async def test_the_renderer_makes_tables_and_escapes_content(
    hass: HomeAssistant,
):
    """A mail client shows a pipe table as a wall of text, so the
    tables are rendered; anything a device name could carry is
    escaped rather than injected.

    Moved onto the surviving renderer in 0.10.22 (ruling #188). It
    tested the messenger's renderer, which stopped being what the
    file and the mail carried in 0.10.18, so it went on passing over
    a renderer nothing read while the one that mattered escaped
    nothing.
    """
    coord = await setup_coordinator(hass)
    html = coord._render_brief_html(
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


async def test_a_device_name_cannot_inject_markup_into_the_brief(
    hass: HomeAssistant,
):
    """The fault as found, end to end through the real brief path.

    Reproduced on 0.10.21 before the fix: a device named with an
    angle bracket in it reached daily_brief.html raw, and therefore
    reached the mail raw, because the renderer that writes the file
    escaped nothing while the one carrying the escaping test was no
    longer read (ruling #188).
    """
    coord = await setup_coordinator(hass)
    coord.data[DATA_TODO_ITEMS] = [
        {
            TODO_DEVICE_ID: "inject1",
            TODO_SORT_NAME: "Sensor <script>alert(1)</script>",
            TODO_STATUS: "needs_action",
            TODO_KINDS: {
                TODO_KIND_FROZEN: dt_util.utcnow().timestamp() - 60
            },
        }
    ]
    await hass.async_add_executor_job(coord._write_reports, "manual")

    page = _text(
        hass.config.path("www", "device_sentinel", "daily_brief.html")
    )
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page
    # And the sender's fallback is now the same document, so a
    # mismatched stash cannot reintroduce a second rendering.
    assert coord._render_brief_html(coord._last_brief_text) == page


async def test_the_separator_is_told_by_its_characters(
    hass: HomeAssistant,
):
    """The merged renderer reads the rule row rather than counting to
    it, so a pipe line arriving anywhere else is still data."""
    coord = await setup_coordinator(hass)
    html = coord._render_brief_html(
        "| A | B |\n"
        "|:--|--:|\n"
        "| one | two |\n"
    )
    assert "<th>A</th>" in html
    assert "<td>one</td>" in html
    assert ":--" not in html


async def test_the_email_carries_the_closed_day_not_the_new_window(
    hass: HomeAssistant,
):
    """The fault of 0.10.18, found on the first morning it ran (#184).

    The scheduled write closes yesterday and then immediately opens
    today's in-progress brief, and the page was stashed on both
    writes. So the mail went out with yesterday's text in the
    message field and today's twenty-second window in the HTML body:
    the scope line read "in progress" and the events table read
    nothing happened.

    This walks that exact two-write sequence and pins the emailed
    body to the closed dated file on disk. The second assertion is
    the one that catches a regression, because after the roll the
    undated current file is the in-progress page by design, and a
    stash updated by that write matches it.
    """
    calls = _capture(hass)
    coord = await setup_coordinator(
        hass,
        {
            CONF_REMINDER_MODE: REMINDER_MODE_DAILY,
            CONF_BRIEF_TARGETS: ["notify.brief_mail"],
        },
    )
    await coord._on_brief_time(None)
    await hass.async_block_till_done()

    start, _end = coord._brief_close_bounds()
    closed_name = dt_util.as_local(
        dt_util.utc_from_timestamp(start)
    ).strftime("daily_brief_%Y-%m-%d.html")
    closed = _text(hass.config.path("www", "device_sentinel", closed_name))
    current = _text(
        hass.config.path("www", "device_sentinel", "daily_brief.html")
    )

    assert len(calls) == 1
    body = calls[0]["data"]["html"]
    assert body == closed
    assert body != current
    assert "(in progress)" not in body
    assert "(in progress)" in current


async def test_a_page_from_another_document_is_never_sent(
    hass: HomeAssistant,
):
    """The check, not the guard: the stash is used only where it was
    rendered from the very text being sent.

    Guarding the stash on completion alone fixes the roll and leaves
    a field written in one module and read in another with nothing
    tying the two together. Here the stash is deliberately set to a
    page belonging to some other document; the sender must decline
    it and render the text it was handed instead.
    """
    calls = _capture(hass)
    coord = await setup_coordinator(
        hass,
        {
            CONF_REMINDER_MODE: REMINDER_MODE_DAILY,
            CONF_BRIEF_TARGETS: ["notify.brief_mail"],
        },
    )
    text = await hass.async_add_executor_job(
        coord._write_reports, BRIEF_TRIGGER
    )
    coord._last_brief_pair = ("some other brief", "<p>WRONG DAY</p>")
    await coord.async_send_brief(text)
    await hass.async_block_till_done()

    assert len(calls) == 1
    body = calls[0]["data"]["html"]
    assert "WRONG DAY" not in body
    assert "<h1>Device Sentinel Daily Brief</h1>" in body


async def test_the_chart_link_prefers_the_external_url(
    hass: HomeAssistant,
):
    """#183, amending #181: external first, because an emailed brief
    is most useful when the reader is away from home."""
    coord = await setup_coordinator(hass)
    hass.config.internal_url = "http://192.168.1.10:8123"
    hass.config.external_url = "https://panorama.example.com"
    assert (
        coord._absolute_url(REPORT_SIGNAL_URL)
        == "https://panorama.example.com" + REPORT_SIGNAL_URL
    )


async def test_the_chart_link_falls_back_to_the_internal_url(
    hass: HomeAssistant,
):
    """#183, the clause that amends #181: where no external URL is
    configured the link is the internal one, never relative.

    A relative /local address has no host to resolve against inside
    a mail client, so it is dead everywhere. The internal address at
    least works on home wifi, which is strictly more than nothing.
    Restore the relative fallback and this fails.
    """
    coord = await setup_coordinator(hass)
    hass.config.external_url = None
    hass.config.internal_url = "http://192.168.1.10:8123"
    link = coord._absolute_url(REPORT_SIGNAL_URL)
    assert link == "http://192.168.1.10:8123" + REPORT_SIGNAL_URL
    assert not link.startswith("/")


async def test_the_emailed_chart_link_is_absolute_in_the_page(
    hass: HomeAssistant,
):
    """End to end through the renderer: the href a mail client sees
    carries a host, not a bare path."""
    coord = await setup_coordinator(hass)
    hass.config.external_url = None
    hass.config.internal_url = "http://192.168.1.10:8123"
    page = coord._render_brief_html(
        "# Device Sentinel Daily Brief\n"
        "\n"
        f"Details and the full report: {REPORT_SIGNAL_URL}\n"
    )
    assert (
        f"<a href='http://192.168.1.10:8123{REPORT_SIGNAL_URL}'>"
        in page
    )
    assert f"href='{REPORT_SIGNAL_URL}'" not in page
