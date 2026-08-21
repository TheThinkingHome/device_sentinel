# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_retention.py, Version: 0.15.8 (2026-08-18)

"""How much is kept, and what reads only a window of it.

One of the files split out of test_storage.py, which had
grown larger than any source file in the project (ruling #203).
The seam is the subject, the same rule the source split followed.
Helpers are carried to every file that calls them rather than
pooled, so each file reads on its own.
"""


import glob
import os


from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
)

from custom_components.device_sentinel.const import (
    BRIEF_KEEP_DAYS,
    CONF_COALESCE_MINUTES,
    CONF_EPISODE_SHARE,
    CONF_LOW_THRESHOLD,
    CONF_RETENTION_DAYS,
    CONF_SETTLE_SHARE,
    DAILY_MAX_KEEP,
    DATA_EPISODES,
    DATA_INCIDENTS,
    DATA_SYSTEM_EVENTS,
    DEFAULT_RETENTION_DAYS,
    DEV_DAILY_MAX,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_TODAY_MIN,
    DEV_TODAY_MAX,
    EPISODE_ENDED_RESUMED,
    EPISODE_KEEP_DAYS,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_NEVER_REPORTED,
    FREEZE_CATEGORY_UNAVAILABLE,
    FREEZE_CATEGORY_UNKNOWN,
    INCIDENT_KEEP_DAYS,
    INCIDENT_OPENED,
    INC_DEVICE_ID,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_WHEN,
    REPORT_BRIEF_PREFIX,
    REPORT_DIAGNOSTIC_DIR,
    RETENTION_DAYS_MAX,
    RETENTION_DAYS_MIN,
    RETENTION_DAYS_STEP,
    SIGNAL_DAYS_KEEP,
    SYS_KIND,
    SYS_OPTIONS_CHANGED,
    SYS_RESTART,
    SYS_WHEN,
    TODO_KINDS_ALL,
    TODO_KIND_LOW_BATTERY,
    TODO_KIND_FROZEN,
    TODO_KIND_NEVER_REPORTED,
    TODO_KIND_UNAVAILABLE,
    TODO_KIND_UNKNOWN,
)


from tests.helpers import setup_entry

DOMAIN = "device_sentinel"

def _register(hass, uid, name):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    ent = er.async_get(hass).async_get_or_create(
        "sensor", "test", f"{uid}_0",
        device_id=device.id, config_entry=source,
    )
    return device, ent.entity_id


def _episode(coord, days_ago, ended=EPISODE_ENDED_RESUMED, lag=None):
    when = dt_util.utcnow().timestamp() - days_ago * 86400.0
    coord.data[DATA_EPISODES].append(
        {
            "device_id": f"d{days_ago}",
            "name": f"Device {days_ago}",
            "since": when,
            "basis": 3600.0,
            "window": 7200.0,
            "ended": ended,
            "at": when + 60 if ended else None,
            "lag": lag,
            "learned": "yes" if ended else None,
        }
    )


async def test_only_the_newest_briefs_are_kept(hass: HomeAssistant):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    directory = hass.config.path("www", "device_sentinel")
    os.makedirs(directory, exist_ok=True)
    # Setup writes today's brief, so start from a known count.
    for path in glob.glob(
        os.path.join(directory, "daily_brief_2*.html")
    ):
        os.remove(path)
    for day in range(1, BRIEF_KEEP_DAYS + 7):
        name = f"{REPORT_BRIEF_PREFIX}2026-06-{day:02d}.html"
        with open(os.path.join(directory, name), "w") as handle:
            handle.write("stale\n")
    assert len(
        glob.glob(os.path.join(directory, "daily_brief_2*.html"))
    ) == (BRIEF_KEEP_DAYS + 6)

    coord._trim_briefs(directory)
    left = sorted(
        os.path.basename(p)
        for p in glob.glob(
            os.path.join(directory, "daily_brief_2*.html")
        )
    )
    assert len(left) == BRIEF_KEEP_DAYS
    # The newest survive: the oldest six dates are gone.
    assert left[0] == f"{REPORT_BRIEF_PREFIX}2026-06-07.html"


async def test_trimming_briefs_is_safe_when_there_are_few(
    hass: HomeAssistant,
):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    directory = hass.config.path("device_sentinel")
    before = glob.glob(os.path.join(directory, "daily_brief_*.md"))
    coord._trim_briefs(directory)
    assert len(glob.glob(os.path.join(directory, "daily_brief_*.md"))) == (
        len(before)
    )


async def test_old_episodes_are_dropped(hass: HomeAssistant):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord.data[DATA_EPISODES].clear()
    _episode(coord, days_ago=EPISODE_KEEP_DAYS + 6)
    _episode(coord, days_ago=EPISODE_KEEP_DAYS + 1)
    _episode(coord, days_ago=2)
    coord._trim_episodes(dt_util.utcnow().timestamp())
    assert len(coord.data[DATA_EPISODES]) == 1
    assert coord.data[DATA_EPISODES][0]["name"] == "Device 2"


async def test_an_unfinished_episode_survives_the_boundary(
    hass: HomeAssistant,
):
    """An episode still waiting on its lag is an unfinished story, not
    old news, so age alone does not remove it."""
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord.data[DATA_EPISODES].clear()
    _episode(coord, days_ago=EPISODE_KEEP_DAYS + 9, ended=None)
    _episode(
        coord,
        days_ago=EPISODE_KEEP_DAYS + 9,
        ended="intervention (restart)",
        lag=None,
    )
    _episode(coord, days_ago=EPISODE_KEEP_DAYS + 9)
    coord._trim_episodes(dt_util.utcnow().timestamp())
    survivors = [row["ended"] for row in coord.data[DATA_EPISODES]]
    assert len(survivors) == 2
    assert EPISODE_ENDED_RESUMED not in survivors


async def test_old_incidents_are_dropped_as_new_ones_arrive(
    hass: HomeAssistant,
):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord.data[DATA_INCIDENTS].clear()
    stale = dt_util.utcnow().timestamp() - (INCIDENT_KEEP_DAYS + 3) * 86400
    coord.data[DATA_INCIDENTS].append(
        {
            "device_id": "old",
            "name": "Ancient History",
            "kind": TODO_KIND_FROZEN,
            "event": INCIDENT_OPENED,
            INC_WHEN: stale,
            "cause": None,
            "duration": None,
        }
    )
    coord._record_incident("new", "Fresh", TODO_KIND_FROZEN, INCIDENT_OPENED)
    names = [row["name"] for row in coord.data[DATA_INCIDENTS]]
    assert names == ["Fresh"]


async def test_freeze_kinds_alias_their_verdicts(hass: HomeAssistant):
    """The sync passes a freeze verdict straight through as a kind, so
    the two names must be the same string, defined once."""
    assert TODO_KIND_FROZEN == FREEZE_CATEGORY_FROZEN
    assert TODO_KIND_UNAVAILABLE == FREEZE_CATEGORY_UNAVAILABLE
    assert TODO_KIND_UNKNOWN == FREEZE_CATEGORY_UNKNOWN
    assert TODO_KIND_NEVER_REPORTED == FREEZE_CATEGORY_NEVER_REPORTED


async def test_every_kind_has_words_everywhere(
    hass: HomeAssistant,
):
    """The guard that failed to guard (ruling #215).

    Five tables map a kind to words. This test existed for exactly
    the case where one is missed, and it listed the kinds by hand, so
    when the falling kind arrived the list did not grow and the test
    kept passing while checking six of seven. A person's brief read
    "battery_falling" and "Door 2nd Bedroom 0s" for a day.

    It now reads TODO_KINDS_ALL, so a kind added without wording
    fails here rather than in a brief.
    """
    entry = await setup_entry(hass)
    coord = entry.runtime_data

    for kind in TODO_KINDS_ALL:
        assert kind in coord._KIND_SEVERITY, kind
        # The freeze categories are already their own words, so
        # falling through to the key is correct for them. What is
        # never correct is a raw key reaching a person: an underscore
        # in the output is the tell, and it is precisely what
        # "battery_falling" showed in a live brief.
        assert "_" not in coord._kind_word(
            kind, 20.0, "about a month"
        ), kind
        # The events table, which takes an incident row.
        assert "_" not in coord._brief_phrase(
            {
                INC_KIND: kind,
                INC_EVENT: INCIDENT_OPENED,
                INC_DEVICE_ID: "nonexistent",
                INC_NAME: "Probe",
            }
        ), kind

    # The two narrative tables cover the kinds that describe a moment
    # or a standing state. A battery level is phrased from its own
    # reading rather than a template, so it is absent by design.
    for kind in TODO_KINDS_ALL:
        if kind in (TODO_KIND_LOW_BATTERY, TODO_KIND_NEVER_REPORTED):
            continue
        assert kind in coord._EVENT_WORDING, kind
        assert kind in coord._STATE_TEMPLATE, kind


async def test_the_kind_list_is_the_whole_list(hass: HomeAssistant):
    """TODO_KINDS_ALL has to actually hold every kind, or the guard
    above is checking a subset again (ruling #215). Read from the
    source: every TODO_KIND_ constant must appear in it.
    """
    from custom_components.device_sentinel import const

    declared = {
        value
        for name, value in vars(const).items()
        if name.startswith("TODO_KIND_") and isinstance(value, str)
    }
    assert declared == set(TODO_KINDS_ALL), declared ^ set(TODO_KINDS_ALL)


async def test_the_floor_ignores_history_beyond_its_window(
    hass: HomeAssistant,
):
    """The guard that matters. The floor is a trimmed minimum, so the
    fourth lowest of ninety days is lower than the fourth lowest of
    thirty, and reading the whole series would quietly slacken every
    floor on the fleet.

    The window is thirty days rather than the fourteen the rhythm
    uses (ruling #196): a fortnight forgets a device's genuinely bad
    days and sits too high, and a floor that jumps as one ages out is
    what made dwell spike and collapse rather than trend.
    """
    device, _ = _register(hass, "fl1", "Floor Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]

    month = [100.0 - n for n in range(SIGNAL_DAYS_KEEP)]
    record[DEV_SIGNAL_DAILY_MIN] = list(month)
    with_a_month = coord._danger_line(record)

    # The same month, preceded by far worse older days.
    record[DEV_SIGNAL_DAILY_MIN] = [10.0] * 40 + list(month)
    with_a_season = coord._danger_line(record)

    assert with_a_season == with_a_month
    assert 10.0 not in coord._signal_history(record)
    assert len(coord._signal_history(record)) == SIGNAL_DAYS_KEEP


async def test_a_bad_day_three_weeks_back_still_counts(
    hass: HomeAssistant,
):
    """The reason the window moved (ruling #196). On the reference
    fleet fifty-one of seventy-eight devices had a worse day just
    outside the fortnight, so a fourteen day floor sat above what
    those devices actually do, and it jumped when the day aged out.
    """
    device, _ = _register(hass, "fl2", "Long Memory")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]

    # Twenty steady days, with three bad ones twenty-one days back.
    record[DEV_SIGNAL_DAILY_MIN] = (
        [40.0, 40.0, 40.0] + [100.0] * 20
    )
    assert 40.0 in coord._signal_history(record)


async def test_the_signal_series_keeps_ninety_days(
    hass: HomeAssistant,
):
    device, _ = _register(hass, "se1", "Series Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]
    record[DEV_SIGNAL_DAILY_MIN] = [float(n) for n in range(200)]
    # The trim happens when a day is appended, so roll one.
    record[DEV_SIGNAL_TODAY_MIN] = 42.0
    await coord._on_midnight(None)
    assert len(record[DEV_SIGNAL_DAILY_MIN]) == DEFAULT_RETENTION_DAYS
    assert record[DEV_SIGNAL_DAILY_MIN][-1] == 42.0


async def test_the_columns_show_the_window_and_not_the_season(
    hass: HomeAssistant,
):
    """A season of history must not widen the report's columns.

    The signal column shows exactly the window the floor is computed
    over, thirty days since ruling #196. Showing fewer would leave
    the marked value outside the cell on any device whose worst days
    sit further back, and a reader would see every reading struck
    with none marked.
    """
    device, _ = _register(hass, "co1", "Column Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]
    record[DEV_SIGNAL_DAILY_MIN] = [50.0 + n for n in range(DEFAULT_RETENTION_DAYS)]
    cell = coord._format_signal_lows_cell(record)
    assert len(cell.split()) == SIGNAL_DAYS_KEEP
    # The rhythm column is unchanged; the two windows differ on
    # purpose, because a trimmed maximum and a trimmed minimum need
    # different lengths of memory.
    record[DEV_DAILY_MAX] = [60.0 + n for n in range(DEFAULT_RETENTION_DAYS)]
    assert len(coord._format_maxima_cell(record[DEV_DAILY_MAX]).split()) == (
        DAILY_MAX_KEEP
    )


async def test_the_maintainer_files_live_at_the_top(
    hass: HomeAssistant,
):
    """Since 0.10.18 the folder is the developer's (#178): the
    briefs a person reads live under www, so the maintainer files
    come back up and the old diagnostics subfolder is emptied of
    them."""
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    await hass.async_add_executor_job(coord._write_reports, "test")
    top = hass.config.path("device_sentinel")
    below = os.path.join(top, REPORT_DIAGNOSTIC_DIR)
    for name in (
        "device_telemetry.md",
        "classification.md",
        "silence_episodes.md",
    ):
        assert os.path.isfile(os.path.join(top, name)), name
        assert not os.path.isfile(os.path.join(below, name)), name
    # The briefs live under www now, not here.
    www = hass.config.path("www", "device_sentinel")
    assert any(
        name.startswith("daily_brief_") for name in os.listdir(www)
    )


async def test_the_rhythm_reads_only_the_judgment_window(
    hass: HomeAssistant,
):
    """The hazard this release had to avoid. The trimmed maximum of
    ninety days is higher than of fourteen, because more days mean
    more chances at a long gap, so reading the whole series would
    quietly widen every freeze window on the fleet."""
    device, _ = _register(hass, "jd1", "Judged Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]

    fortnight = [600.0 + n for n in range(DAILY_MAX_KEEP)]
    record[DEV_DAILY_MAX] = list(fortnight)
    with_a_fortnight = coord._freeze_window(record)

    # The same fortnight, preceded by far longer gaps months ago.
    record[DEV_DAILY_MAX] = [50000.0] * 60 + list(fortnight)
    with_a_season = coord._freeze_window(record)

    assert with_a_season == with_a_fortnight


async def test_the_rhythm_is_the_same_at_every_setting(
    hass: HomeAssistant,
):
    """A Pi keeping thirty days detects what a fast machine keeping a
    year detects."""
    device, _ = _register(hass, "jd2", "Same Sensor")
    series = [50000.0] * 60 + [600.0 + n for n in range(DAILY_MAX_KEEP)]
    seen = set()
    for days in (RETENTION_DAYS_MIN, DEFAULT_RETENTION_DAYS,
                 RETENTION_DAYS_MAX):
        entry = await setup_entry(hass, {CONF_RETENTION_DAYS: days})
        coord = entry.runtime_data
        record = coord.data["devices"][device.id]
        record[DEV_DAILY_MAX] = list(series)
        seen.add(coord._freeze_window(record))
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
    assert len(seen) == 1


async def test_the_report_cell_still_shows_a_fortnight(
    hass: HomeAssistant,
):
    device, _ = _register(hass, "jd3", "Cell Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [600.0 + n for n in range(120)]
    assert len(coord._format_maxima_cell(record[DEV_DAILY_MAX]).split(", ")) == (
        DAILY_MAX_KEEP
    )


async def test_gaps_are_kept_for_the_chosen_length(
    hass: HomeAssistant,
):
    """Reporting gaps join the long series, so three months of them
    can eventually be used to question the fourteen-day window."""
    device, _ = _register(hass, "ke1", "Kept Sensor")
    entry = await setup_entry(hass, {CONF_RETENTION_DAYS: 30})
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [float(n) for n in range(200)]
    record[DEV_TODAY_MAX] = 999.0
    await coord._on_midnight(None)
    assert len(record[DEV_DAILY_MAX]) == 30
    assert record[DEV_DAILY_MAX][-1] == 999.0


async def test_the_setting_is_clamped_to_its_band(
    hass: HomeAssistant,
):
    """The floor of thirty is what makes the slider safe: no choice
    can starve a fourteen-day judgment window."""
    for asked, expected in (
        (5, RETENTION_DAYS_MIN),
        (900, RETENTION_DAYS_MAX),
        (60, 60),
    ):
        entry = await setup_entry(hass, {CONF_RETENTION_DAYS: asked})
        assert entry.runtime_data.retention_days == expected
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_reducing_the_setting_waits_for_midnight(
    hass: HomeAssistant,
):
    """A settings dialog should not destroy three months of history
    the instant a slider moves; the trim happens where every other
    trim happens."""
    device, _ = _register(hass, "ke2", "Patient Sensor")
    entry = await setup_entry(hass, {CONF_RETENTION_DAYS: 90})
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [float(n) for n in range(90)]

    hass.config_entries.async_update_entry(
        entry, options={CONF_RETENTION_DAYS: 30}
    )
    await coord.async_options_updated()
    assert len(record[DEV_DAILY_MAX]) == 90     # untouched for now

    record[DEV_TODAY_MAX] = 1.0
    await coord._on_midnight(None)
    assert len(record[DEV_DAILY_MAX]) == 30     # trimmed at the roll


async def test_the_slider_reaches_the_advanced_screen(
    hass: HomeAssistant,
):
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "advanced"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SETTLE_SHARE: 30,
            CONF_EPISODE_SHARE: 50,
            CONF_COALESCE_MINUTES: 15,
            CONF_RETENTION_DAYS: 180,
        },
    )
    assert result["type"] is FlowResultType.MENU
    assert entry.options[CONF_RETENTION_DAYS] == 180
    assert entry.runtime_data.retention_days == 180
    assert RETENTION_DAYS_STEP == 30


async def test_the_report_states_the_retention_in_force(
    hass: HomeAssistant,
):
    """The tunables line said "keep 14 days" after retention became a
    setting, telling a reader it kept a fortnight while keeping three
    months (0.8.10)."""
    _register(hass, "tu1", "Tunable Sensor")
    entry = await setup_entry(hass, {CONF_RETENTION_DAYS: 180})
    coord = entry.runtime_data
    await hass.async_add_executor_job(coord._write_reports, "test")
    with open(
        hass.config.path("device_sentinel/device_telemetry.md"),
        encoding="utf-8",
    ) as handle:
        text = handle.read()
    assert f"judge on {DAILY_MAX_KEEP} days, keep 180 days." in text


async def test_a_start_records_itself_as_a_system_event(
    hass: HomeAssistant, freezer
):
    """The house's own record, so a device revived by a reboot has a
    reason above it rather than being a mystery in the brief."""
    _register(hass, "sys1", "Any Device")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    starts = [
        row
        for row in coord.data[DATA_SYSTEM_EVENTS]
        if row[SYS_KIND] == SYS_RESTART
    ]
    assert len(starts) == 1
    # Consistency only: the harness clock is frozen, so start-time
    # and write-time are the same value here and this cannot tell
    # them apart. The test below is the one that can.
    assert coord._started_at is not None
    assert starts[0][SYS_WHEN] == coord._started_at


async def test_an_event_can_be_stamped_when_it_happened(
    hass: HomeAssistant, freezer
):
    """Not every event is written the moment it occurs.

    A restart is recorded once setup has succeeded, so that a start
    which failed halfway leaves no claim the system came back. But it
    happened earlier, before the first sweep judged anything, and
    stamped at the write it would sort below the very devices it
    explains. The brief would print the morning underneath the
    morning.
    """
    _register(hass, "sys5", "Any Device")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord.data[DATA_SYSTEM_EVENTS] = []
    earlier = dt_util.utcnow().timestamp() - 600.0

    coord._record_system_event(SYS_RESTART, when=earlier)
    coord._record_system_event(SYS_RESTART)

    stamped, written = coord.data[DATA_SYSTEM_EVENTS]
    assert stamped[SYS_WHEN] == earlier, "the given moment was ignored"
    assert written[SYS_WHEN] > stamped[SYS_WHEN]


async def test_system_events_keep_the_retention_the_person_chose(
    hass: HomeAssistant, freezer
):
    """Not the fourteen days an incident keeps.

    An incident older than a fortnight has been fixed or is still
    standing. How often this house loses power is a question about
    the house, answerable only over seasons, so these rows live as
    long as the statistics they explain.
    """
    _register(hass, "sys2", "Any Device")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    keep = coord.retention_days
    now = dt_util.utcnow().timestamp()

    coord.data[DATA_SYSTEM_EVENTS] = [
        {SYS_WHEN: now - (keep - 1) * 86400.0, SYS_KIND: "old_but_kept",
         "scope": "system", "detail": None, "duration": None},
        {SYS_WHEN: now - (keep + 1) * 86400.0, SYS_KIND: "expired",
         "scope": "system", "detail": None, "duration": None},
    ]
    coord._record_system_event(SYS_RESTART)

    kinds = {row[SYS_KIND] for row in coord.data[DATA_SYSTEM_EVENTS]}
    assert "old_but_kept" in kinds, "trimmed at the incident window"
    assert "expired" not in kinds
    assert keep > 14, "the point of the test is that it outlives an incident"


async def test_changing_a_setting_records_which_one(
    hass: HomeAssistant, freezer
):
    """Which setting moved, not merely that one did.

    A row saying something changed cannot answer, months later, why a
    device started being reported when nothing in the house altered.
    """
    _register(hass, "sys3", "Any Device")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.config_entries.async_update_entry(
        entry, options={**dict(entry.options), CONF_LOW_THRESHOLD: 42}
    )
    await coord.async_options_updated()

    changed = [
        row
        for row in coord.data[DATA_SYSTEM_EVENTS]
        if row[SYS_KIND] == SYS_OPTIONS_CHANGED
    ]
    assert len(changed) == 1
    assert CONF_LOW_THRESHOLD in changed[0]["detail"]


async def test_applying_the_same_settings_records_nothing(
    hass: HomeAssistant, freezer
):
    """The options flow can be opened and closed without changing
    anything, and a row for that is noise in a record kept for
    months."""
    _register(hass, "sys4", "Any Device")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    await coord.async_options_updated()

    assert [
        row
        for row in coord.data[DATA_SYSTEM_EVENTS]
        if row[SYS_KIND] == SYS_OPTIONS_CHANGED
    ] == []
