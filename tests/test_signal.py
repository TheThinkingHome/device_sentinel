# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_signal.py, Version: 0.20.5 (2026-09-05)

"""Signal detection: the floor line and the rail.

A device's danger line is the plain minimum of its daily P5 window
plus the sensitivity margin (rulings #322, #323). A rail (LQI 255,
RSSI -128) is not a reading: it feeds neither the floor nor the
estimators, and the confirmed rail is three consecutive days on which
the device spoke and said nothing but the fill value, read as a zero
reading count beside a rail count above zero (ruling #322). This file
holds the floor line and how it renders, the rail detector, signal
muting as recorded-not-reported, and the tracked count surface.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_SIGNAL_ALT,
    DEV_SIGNAL_READS,
    DEV_SIGNAL_SCALE,
    SIGNAL_SCALE_LQI,
    SIGNAL_SCALE_RSSI,
    CONF_SIGNAL_MUTED_DEVICES,
    CONF_SIGNAL_MUTED_INTEGRATIONS,
    CONF_SIGNAL_MUTED_LABELS,
    DEV_SIGNAL_DAILY_COUNT,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_RAIL,
    DEV_SIGNAL_LAST_CHANGE,
    DEV_SIGNAL_TODAY_MIN,
    DEV_SIGNAL_VALUE,
    SIGNAL_RAIL_LQI,
    SIGNAL_RAIL_RSSI,
    UNIT_SIGNALS,
)
from custom_components.device_sentinel.detect_signal import (
    SignalMixin,
    scale_of,
    signal_bucket,
)
from custom_components.device_sentinel.coordinator import (
    _new_device_record,
)

from tests.helpers import setup_coordinator, setup_coordinator_flat_line, setup_entry

DOMAIN = "device_sentinel"


def _register_device(hass, uid: str):
    """A real registry device carrying one link-quality sensor, so
    setup watches it rather than pruning its storage record as an
    orphan. Returns the device."""
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=f"Signal {uid}",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", uid, device_id=device.id, config_entry=source
    )
    return device


def _record(daily_p5):
    """A device record seeded with a daily P5 history."""
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_SIGNAL_DAILY_P5] = list(daily_p5)
    return record


def _railed_record(counts, rails):
    """A record seeded with the rail evidence pair (ruling #322)."""
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_SIGNAL_DAILY_COUNT] = list(counts)
    record[DEV_SIGNAL_DAILY_RAIL] = list(rails)
    return record


def _armed_lqi_record(floor_days=None):
    """A record with an established LQI floor of 80."""
    return _record(floor_days or [80, 96, 88, 80, 104, 92, 80])


def _armed_rssi_record():
    """A record with an established RSSI floor of -70 dBm."""
    return _record([-60, -66, -70, -62, -58, -64, -70])


async def _rail_coordinator(hass):
    """A coordinator with one registered link-quality device, returning
    the coordinator and that device's id. The rail tests read and write
    the device's series directly, so they need its id in hand."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "rail48")},
        name="Rail48 Device",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "rail48",
        suggested_object_id="rail48_linkquality",
        device_id=device.id, config_entry=source,
    )
    coord = await setup_coordinator_flat_line(hass)
    return coord, device.id


# ------------------------------------------- the line is the floor (#66)


async def test_lqi_line_is_the_floor(hass: HomeAssistant):
    """The floor is the plain minimum of the P5 window (ruling
    #323): P5 already discards the worst five percent of every day
    by time, so no cross-day trim sits on top of it."""
    coord = await setup_coordinator_flat_line(hass)
    record = _armed_lqi_record()
    line = coord._danger_line(record)
    assert line == 80


async def test_rssi_line_is_the_floor(hass: HomeAssistant):
    """Same rule as LQI, no offset: below the floor is below the
    floor whichever sign the scale carries."""
    coord = await setup_coordinator_flat_line(hass)
    record = _armed_rssi_record()
    line = coord._danger_line(record)
    assert line == -70


async def test_line_lives_from_the_first_day(hass: HomeAssistant):
    """The line is the plain lowest P5 from the first recorded day;
    there is no arming wait to sit out."""
    coord = await setup_coordinator_flat_line(hass)
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_SIGNAL_DAILY_P5] = [80, 96, 88]
    assert coord._danger_line(record) == 80


async def test_a_null_day_is_skipped_by_the_floor(hass: HomeAssistant):
    """A rail-only day records null statistics (ruling #305), and
    the floor skips the null rather than crashing or reading it as
    zero."""
    coord = await setup_coordinator_flat_line(hass)
    record = _record([90.0, None, 84.0, None])
    assert coord._danger_line(record) == 84.0


async def test_line_in_report(hass: HomeAssistant):
    """The report shows the daily P5 window with the floor bold.

    The floor is the plain minimum (ruling #323), so nothing is
    struck: no value can sit below it. A rail-only day's null
    renders as a dash.
    """
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "sig31")},
        name="Signal Preview Device",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "sig31",
        suggested_object_id="sig31_linkquality",
        device_id=device.id, config_entry=source,
    )
    coord = await setup_coordinator_flat_line(hass)

    coord.data["devices"][device.id][DEV_SIGNAL_DAILY_P5] = [
        120.0, 118.0, None, 119.0, 121.0, 117.0,
    ]
    await hass.async_add_executor_job(coord._write_reports)
    text = open(
        hass.config.path("device_sentinel/device_telemetry.md")
    ).read()
    row = next(
        line
        for line in text.splitlines()
        if "Signal Preview Device" in line
    )
    # Newest first: the floor 117 is bold, the null day a dash,
    # nothing struck.
    assert "**117** 121 119 - 118 120" in row


# -------------------------------------- the rail-filtered floor (0.4.3)

async def test_rail_history_does_not_poison_the_floor(hass: HomeAssistant):
    """Door Laundry sat at rail for a week, then read a real 172.
    Rail-only days record null P5 (ruling #305), the floor skips
    them, and the one real day is the floor."""
    coord = await setup_coordinator_flat_line(hass)
    record = _record([None] * 7 + [172.0])
    assert coord._danger_line(record) == 172.0


async def test_all_rail_history_has_no_floor(hass: HomeAssistant):
    """A device whose entire history is rail has no floor at all,
    rather than a false one at the rail value."""
    coord = await setup_coordinator_flat_line(hass)
    record = _record([None] * 5)
    assert coord._danger_line(record) is None


# ------------------------------------- the rails and stuck detector (#60)

async def test_rail_feeds_neither_floor_nor_estimators(hass: HomeAssistant):
    """A rail value is not a measurement: it never touches today's
    minimum or the estimators. But it is still a reading, so it
    stamps the signal value and starts the frozen clock like any
    other."""
    coord = await setup_coordinator_flat_line(hass)
    record = _armed_lqi_record()
    coord._feed_signal(record, SIGNAL_RAIL_LQI, 1000.0)
    assert record[DEV_SIGNAL_TODAY_MIN] is None
    assert record[DEV_SIGNAL_VALUE] == SIGNAL_RAIL_LQI
    assert record[DEV_SIGNAL_LAST_CHANGE] == 1000.0


async def test_rssi_rail_does_not_poison_the_floor(hass: HomeAssistant):
    """James S24+ hit -128 once inside real readings; that spike must
    not feed the floor. It is still a reading for the frozen clock."""
    coord = await setup_coordinator_flat_line(hass)
    record = _armed_rssi_record()
    coord._feed_signal(record, SIGNAL_RAIL_RSSI, 1000.0)
    assert record[DEV_SIGNAL_TODAY_MIN] is None
    assert record[DEV_SIGNAL_VALUE] == SIGNAL_RAIL_RSSI


async def test_a_changed_reading_moves_the_frozen_clock(
    hass: HomeAssistant,
):
    """The recovered-by-hand case: the moment a revived sensor sends a
    different value, last_change advances and it is no longer flat."""
    coord = await setup_coordinator_flat_line(hass)
    record = _armed_lqi_record()
    coord._feed_signal(record, SIGNAL_RAIL_LQI, 1000.0)
    coord._feed_signal(record, 116.0, 2000.0)
    assert record[DEV_SIGNAL_LAST_CHANGE] == 2000.0
    assert record[DEV_SIGNAL_VALUE] == 116.0
    assert record[DEV_SIGNAL_TODAY_MIN] == 116.0


# --------------------------- the rail confirmed over three days (0.4.8)

async def test_three_rail_days_confirm_a_rail(hass: HomeAssistant):
    """Three consecutive days on which the device spoke and said
    nothing but the fill value: a zero reading count beside a rail
    count above zero (ruling #322)."""
    coord, device_id = await _rail_coordinator(hass)
    rec = coord.data["devices"][device_id]
    rec[DEV_SIGNAL_DAILY_COUNT] = [400, 380, 0, 0, 0]
    rec[DEV_SIGNAL_DAILY_RAIL] = [0, 2, 9, 7, 8]
    assert coord.signal_railed(rec) is True


async def test_two_rail_days_do_not_confirm(hass: HomeAssistant):
    """Fewer than three consecutive railed days is not yet a rail: a
    rail that comes and goes never confirms."""
    coord, device_id = await _rail_coordinator(hass)
    rec = coord.data["devices"][device_id]
    rec[DEV_SIGNAL_DAILY_COUNT] = [400, 0, 380, 0, 0]
    rec[DEV_SIGNAL_DAILY_RAIL] = [0, 9, 2, 7, 8]
    assert coord.signal_railed(rec) is False


async def test_a_recovered_rail_clears(hass: HomeAssistant):
    """Three railed days then real speech is not a rail: the most
    recent three days are not all railed."""
    coord, device_id = await _rail_coordinator(hass)
    rec = coord.data["devices"][device_id]
    rec[DEV_SIGNAL_DAILY_COUNT] = [0, 0, 0, 380, 400]
    rec[DEV_SIGNAL_DAILY_RAIL] = [9, 7, 8, 1, 0]
    assert coord.signal_railed(rec) is False


async def test_a_silent_day_is_not_a_railed_day(hass: HomeAssistant):
    """A silent day and a railed day both carry a zero reading
    count and differ only in the rail entry, which is why the rail
    column is the evidence (ruling #322). Three silent days confirm
    nothing."""
    coord, device_id = await _rail_coordinator(hass)
    rec = coord.data["devices"][device_id]
    rec[DEV_SIGNAL_DAILY_COUNT] = [400, 380, 0, 0, 0]
    rec[DEV_SIGNAL_DAILY_RAIL] = [0, 0, 0, 0, 0]
    assert coord.signal_railed(rec) is False


async def test_a_steady_plausible_value_is_not_a_rail(hass: HomeAssistant):
    """The motion-blind case: a device speaking real readings,
    however steady, is never a rail. Only all-fill days are."""
    coord, device_id = await _rail_coordinator(hass)
    rec = coord.data["devices"][device_id]
    rec[DEV_SIGNAL_DAILY_COUNT] = [212, 212, 212, 212, 212]
    rec[DEV_SIGNAL_DAILY_RAIL] = [0, 0, 0, 0, 0]
    assert coord.signal_railed(rec) is False


async def test_short_history_is_not_a_rail(hass: HomeAssistant):
    """Fewer than three days of history cannot confirm a rail."""
    coord, device_id = await _rail_coordinator(hass)
    rec = coord.data["devices"][device_id]
    rec[DEV_SIGNAL_DAILY_COUNT] = [0, 0]
    rec[DEV_SIGNAL_DAILY_RAIL] = [9, 8]
    assert coord.signal_railed(rec) is False


# ------------------------------------ exclusion: recorded, not reported

async def test_excluded_device_by_device_id(hass: HomeAssistant):
    coord = await setup_coordinator_flat_line(hass, {CONF_SIGNAL_MUTED_DEVICES: ["dev-plug"]})
    assert coord._signal_muted("dev-plug") is True
    assert coord._signal_muted("dev-other") is False


async def test_excluded_device_by_integration_and_label(
    hass: HomeAssistant,
):
    coord = await setup_coordinator(
        hass,
        {
            CONF_SIGNAL_MUTED_INTEGRATIONS: ["mqtt"],
            CONF_SIGNAL_MUTED_LABELS: ["noisy"],
        },
    )
    coord._watched["dev-mqtt"] = "mqtt"
    coord._device_labels["dev-labelled"] = frozenset({"noisy"})
    assert coord._signal_muted("dev-mqtt") is True
    assert coord._signal_muted("dev-labelled") is True


async def test_excluded_device_still_records_but_is_not_reported(
    hass: HomeAssistant,
):
    """The living room router plug case: excluded from reporting, but
    its floor keeps accumulating in storage so re-including
    it is instant. The report shows excl; the problem list skips it."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "plug")},
        name="LR Router Plug",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "plug",
        suggested_object_id="plug_linkquality",
        device_id=device.id, config_entry=source,
    )
    coord = await setup_coordinator_flat_line(hass, {CONF_SIGNAL_MUTED_DEVICES: [device.id]})
    record = coord.data["devices"][device.id]
    record[DEV_SIGNAL_DAILY_P5] = [80.0, 96.0, 88.0]
    record[DEV_SIGNAL_VALUE] = 80.0

    # Still observed: the floor is computed, history is intact.
    assert coord._danger_line(record) == 80.0
    # Not judged: absent from the frozen list regardless of state.
    assert all(
        row["name"] != "LR Router Plug"
        for row in coord.signal_problem_list
    )
    # The report marks it excl in the signal cell.
    await hass.async_add_executor_job(coord._write_reports)
    text = open(
        hass.config.path("device_sentinel/device_telemetry.md")
    ).read()
    row = next(
        line for line in text.splitlines() if "LR Router Plug" in line
    )
    # excl ahead of the readings; the readings are still shown,
    # floor bold: recorded, not hidden.
    assert "excl" in row
    assert "88 96 **80**" in row


# ------------------------------------------- the erasure at load (#322)

async def test_the_erased_fields_are_swept_at_load(
    hass: HomeAssistant, hass_storage
):
    """A file written before the erasure carries the dwell record;
    one load later it does not, in the record and inside the
    second-scale block alike (ruling #322)."""
    device = _register_device(hass, "sweep322")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]
    record["signal_daily_min"] = [80.0, 96.0]
    record["signal_daily_line"] = [76.0, 76.0]
    record["signal_dwell_daily_pct"] = [3.0]
    record["signal_below_since"] = 1000.0
    record["signal_below_today_seconds"] = 12.0
    record[DEV_SIGNAL_ALT] = {
        "signal_daily_min": [(-70.0), (-68.0)],
        "signal_scale": SIGNAL_SCALE_RSSI,
    }
    record[DEV_SIGNAL_DAILY_P5] = [84.0, 97.0]
    await coord._store.async_save(coord.data)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    reloaded = entry.runtime_data.data["devices"][device.id]
    for key in (
        "signal_daily_min",
        "signal_daily_line",
        "signal_dwell_daily_pct",
        "signal_below_since",
        "signal_below_today_seconds",
    ):
        assert key not in reloaded
        alt = reloaded.get(DEV_SIGNAL_ALT)
        if isinstance(alt, dict):
            assert key not in alt
    # The surviving series is untouched.
    assert reloaded[DEV_SIGNAL_DAILY_P5] == [84.0, 97.0]


# ------------------------------------------------ the tracked surface

async def _enable_tracked_signals(hass, entry):
    """Turn on the tracked-signals sensor, disabled by default under
    #239, so the two tests below have a state to read."""
    reg = er.async_get(hass)
    eid = reg.async_get_entity_id(
        "sensor", "device_sentinel", f"{entry.entry_id}_tracked_signals"
    )
    reg.async_update_entity(eid, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


async def test_tracked_signals_sensor_exists(hass: HomeAssistant):
    entry = await setup_entry(hass)
    await _enable_tracked_signals(hass, entry)
    state = hass.states.get("sensor.device_sentinel_signal_tracked")
    assert state is not None
    assert state.attributes["unit_of_measurement"] == UNIT_SIGNALS


async def test_tracked_counts_armed_devices_and_splits_by_scale(
    hass: HomeAssistant,
):
    device = _register_device(hass, "tracked")
    entry = await setup_entry(hass)
    await _enable_tracked_signals(hass, entry)
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]
    record[DEV_SIGNAL_DAILY_P5] = [80, 96, 88, 80, 104, 92, 80]
    coord._notify()
    await hass.async_block_till_done()
    state = hass.states.get("sensor.device_sentinel_signal_tracked")
    assert int(state.state) == 1
    assert state.attributes["lqi"] == 1
    assert state.attributes["rssi"] == 0


def _sig_entry(entity_id, device_class=None, unit=None, name=None):
    """A registry-entry double carrying a unit (ruling #283)."""

    class _E:
        pass

    e = _E()
    e.entity_id = entity_id
    e.unique_id = entity_id.split(".", 1)[1]
    e.original_name = name
    e.original_device_class = device_class
    e.device_class = None
    e.unit_of_measurement = unit
    e.original_unit_of_measurement = unit
    return e


def test_a_percentage_called_rssi_is_refused():
    """Tasmota's inversion, refused by unit rather than by vendor.

    Tasmota reports RSSI as a 0 to 100 quality figure and Signal as
    the dBm, so on a Tasmota device an entity called RSSI carries a
    percentage. All seven such devices on the first ZHA fleet to send
    data were consistent with 2 x (dBm + 100) clamped, one sitting
    exactly on the clamp at -50 dBm against 100 percent, so it
    restates a number already recorded.
    """
    for unit in ("%", "percent", "PERCENTAGE", " % "):
        assert not SignalMixin._is_signal(
            _sig_entry("sensor.tasmota_e13_rssi", unit=unit)
        ), unit


def test_the_dbm_entity_beside_it_is_kept():
    """The same device's real measurement is untouched."""
    assert SignalMixin._is_signal(
        _sig_entry(
            "sensor.tasmota_e13_signal",
            device_class="signal_strength",
            unit="dBm",
        )
    )


def test_the_signal_strength_class_is_never_refused():
    """Home Assistant permits only dB and dBm for that class, so an
    entity carrying it cannot be a percentage and never reaches the
    unit test. Asserted anyway, because the class is the one path
    that must not depend on a unit being present."""
    for unit in ("dBm", "dB", None, "%"):
        assert SignalMixin._is_signal(
            _sig_entry(
                "sensor.master_city_blinds_signal_strength",
                device_class="signal_strength",
                unit=unit,
            )
        ), unit


def test_a_unitless_name_match_is_kept():
    """The narrowness of #283, which is the whole point of it.

    Nothing in any diagnostics says what unit a Zigbee2MQTT
    linkquality entity carries. A rule refusing every unrecognized
    unit would have taken signal from 74 devices on the reference
    fleet if the guess were wrong, so only a percentage is refused
    and everything else is kept.
    """
    for unit in (None, "", "lqi", "LQI", "dBm", "arbitrary"):
        assert SignalMixin._is_signal(
            _sig_entry("sensor.door_master_linkquality", unit=unit)
        ), unit


def test_the_registry_unit_wins_over_the_original():
    """A person can change a unit, and the changed one is what the
    state carries, so it is the one that decides."""
    ent = _sig_entry("sensor.plug_rssi", unit=None)
    ent.original_unit_of_measurement = "dBm"
    ent.unit_of_measurement = "%"
    assert not SignalMixin._is_signal(ent)
    ent.unit_of_measurement = "dBm"
    ent.original_unit_of_measurement = "%"
    assert SignalMixin._is_signal(ent)


def test_an_entity_with_no_unit_attribute_at_all_is_kept():
    """Older registry doubles and any entry without the field.

    The recognizer must not depend on an attribute existing, because
    a missing unit is not a percentage.
    """

    class _Bare:
        entity_id = "sensor.door_master_lqi"
        unique_id = "door_master_lqi"
        original_name = None
        original_device_class = None
        device_class = None

    assert SignalMixin._is_signal(_Bare())


def test_the_two_real_fleets_classify_as_expected():
    """Every signal entity naming pattern seen on either fleet.

    The reference fleet loses nothing, and the ZHA fleet loses only
    the percentage.
    """
    kept = [
        _sig_entry("sensor.door_master_linkquality"),
        _sig_entry("sensor.temperature_outdoors_linkquality"),
        _sig_entry(
            "sensor.stove_vent_relays_signal",
            device_class="signal_strength",
            unit="dBm",
        ),
        _sig_entry(
            "sensor.master_city_blinds_signal_strength",
            device_class="signal_strength",
            unit="dBm",
        ),
        _sig_entry("sensor.s25_main_bath_toilet_leak_lqi"),
        _sig_entry(
            "sensor.s25_main_bath_toilet_leak_rssi",
            device_class="signal_strength",
            unit="dBm",
        ),
    ]
    for ent in kept:
        assert SignalMixin._is_signal(ent), ent.entity_id
    assert not SignalMixin._is_signal(
        _sig_entry("sensor.e13_grumpy_desk_dragon_light_rssi", unit="%")
    )


def test_the_sign_decides_the_scale():
    """RSSI is negative at any Zigbee receiver; LQI runs 0 to 255
    (ruling #284). Zero is a valid link quality and not a plausible
    received power, so it belongs with LQI."""
    for value in (-1.0, -66.0, -106.0, -128.0):
        assert scale_of(value) == SIGNAL_SCALE_RSSI, value
    for value in (0.0, 1.0, 94.0, 247.0, 255.0):
        assert scale_of(value) == SIGNAL_SCALE_LQI, value


def test_one_scale_stays_at_the_top_of_the_record():
    """A Zigbee2MQTT device publishes linkquality alone, so nothing
    about it changes: no block is allocated and it costs 20 bytes."""
    rec = _new_device_record("2026-08-17T00:00:00+00:00", 1.0)
    bucket = signal_bucket(rec, SIGNAL_SCALE_LQI)
    assert bucket is rec
    assert rec[DEV_SIGNAL_SCALE] == SIGNAL_SCALE_LQI
    assert rec[DEV_SIGNAL_ALT] is None


def test_a_second_scale_gets_its_own_block():
    rec = _new_device_record("2026-08-17T00:00:00+00:00", 1.0)
    signal_bucket(rec, SIGNAL_SCALE_RSSI)
    alt = signal_bucket(rec, SIGNAL_SCALE_LQI)
    assert alt is not rec
    assert alt is rec[DEV_SIGNAL_ALT]
    assert alt[DEV_SIGNAL_SCALE] == SIGNAL_SCALE_LQI
    assert rec[DEV_SIGNAL_SCALE] == SIGNAL_SCALE_RSSI
    # and the block holds no judgment fields
    assert "signal_dwell_daily_pct" not in alt
    assert "signal_daily_line" not in alt


def test_rssi_takes_the_primary_even_when_lqi_arrived_first():
    """Precedence is RSSI (ruling #285), and a ZHA device's LQI
    entity may well report first. The two trade places rather than
    either being discarded, so nothing already learned is lost."""
    rec = _new_device_record("2026-08-17T00:00:00+00:00", 1.0)
    lqi = signal_bucket(rec, SIGNAL_SCALE_LQI)
    assert lqi is rec
    rec[DEV_SIGNAL_VALUE] = 215.0
    rec[DEV_SIGNAL_DAILY_P5] = [200.0, 205.0]
    rec[DEV_SIGNAL_READS] = 41

    rssi = signal_bucket(rec, SIGNAL_SCALE_RSSI)
    assert rssi is rec
    assert rec[DEV_SIGNAL_SCALE] == SIGNAL_SCALE_RSSI
    # the LQI it had learned moved down, intact
    alt = rec[DEV_SIGNAL_ALT]
    assert alt[DEV_SIGNAL_SCALE] == SIGNAL_SCALE_LQI
    assert alt[DEV_SIGNAL_VALUE] == 215.0
    assert alt[DEV_SIGNAL_DAILY_P5] == [200.0, 205.0]
    assert alt[DEV_SIGNAL_READS] == 41
    # and the top is clear for RSSI rather than holding LQI's numbers
    assert rec[DEV_SIGNAL_VALUE] is None
    assert rec[DEV_SIGNAL_DAILY_P5] == []
    assert rec[DEV_SIGNAL_READS] == 0


def test_lqi_never_displaces_rssi():
    rec = _new_device_record("2026-08-17T00:00:00+00:00", 1.0)
    signal_bucket(rec, SIGNAL_SCALE_RSSI)
    rec[DEV_SIGNAL_VALUE] = -70.0
    signal_bucket(rec, SIGNAL_SCALE_LQI)
    assert rec[DEV_SIGNAL_SCALE] == SIGNAL_SCALE_RSSI
    assert rec[DEV_SIGNAL_VALUE] == -70.0


def test_routing_is_stable_however_the_readings_interleave():
    """Whatever order the two entities report in, the device ends up
    with RSSI on top and LQI in the block."""
    import itertools

    for order in itertools.permutations(
        [-70.0, 215.0, -66.0, 247.0, -71.0]
    ):
        rec = _new_device_record("2026-08-17T00:00:00+00:00", 1.0)
        for value in order:
            bucket = signal_bucket(rec, scale_of(value))
            bucket[DEV_SIGNAL_VALUE] = value
        assert rec[DEV_SIGNAL_SCALE] == SIGNAL_SCALE_RSSI, order
        assert rec[DEV_SIGNAL_VALUE] < 0, order
        assert rec[DEV_SIGNAL_ALT][DEV_SIGNAL_VALUE] > 0, order


# ------------------------------------------- a series past its window


async def test_the_floor_reads_only_the_window_it_is_given(
    hass: HomeAssistant,
):
    """A long series does not drag an old regime forward.

    The floor reads the most recent thirty days (SIGNAL_DAYS_KEEP,
    widened by #196), and a device that has been running for months
    holds more than that. A link that was poor in its first month and
    steady since must be judged on the month it is in, or every
    device that ever had a bad patch carries it as a permanent
    excuse.
    """
    coord = await setup_coordinator_flat_line(hass)
    record = _new_device_record("2026-06-01T00:00:00+00:00", None)
    # Sixty days at a poor floor, then thirty steady and high.
    record[DEV_SIGNAL_DAILY_P5] = [40.0] * 60 + [88.0] * 30
    assert coord._danger_line(record) == 88.0

    # And the reverse: a link that has just gone bad is judged bad,
    # however good its history was.
    record[DEV_SIGNAL_DAILY_P5] = [95.0] * 60 + [52.0] * 30
    assert coord._danger_line(record) == 52.0


async def test_the_floor_at_the_window_boundary(hass: HomeAssistant):
    """Exactly thirty days in, and one day past it.

    The day the oldest reading leaves the window is the day the line
    can move without anything about the device changing, which is the
    one moment a person would call the reading wrong.
    """
    coord = await setup_coordinator_flat_line(hass)
    record = _new_device_record("2026-06-01T00:00:00+00:00", None)
    record[DEV_SIGNAL_DAILY_P5] = [30.0] + [90.0] * 29
    assert coord._danger_line(record) == 30.0
    record[DEV_SIGNAL_DAILY_P5] = [30.0] + [90.0] * 30
    assert coord._danger_line(record) == 90.0


async def test_a_long_series_with_gaps_and_rails(hass: HomeAssistant):
    """Ninety days of real shape: null days, rail days, and a floor.

    A rail value means no reading at all (#305) and must not become
    the floor, and a null day must be skipped rather than read as
    zero. Over three months a device collects both, and the floor has
    to survive the mixture.
    """
    coord = await setup_coordinator_flat_line(hass)
    record = _new_device_record("2026-06-01T00:00:00+00:00", None)
    series = []
    for day in range(90):
        if day % 17 == 0:
            series.append(None)
        elif day % 23 == 0:
            series.append(255.0)
        else:
            series.append(70.0 + (day % 11))
    record[DEV_SIGNAL_DAILY_P5] = series
    line = coord._danger_line(record)
    assert line is not None
    assert 70.0 <= line <= 81.0, line
