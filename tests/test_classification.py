# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_classification.py, Version: 0.13.4 (2026-08-13)

"""How devices are counted and attributed to integrations.

Every registry device is sorted into watched or set aside, and a
device that belongs to more than one config entry is attributed to its
primary one, so a camera also seen by a router tracker counts once,
under the camera. The classification report renders one combined table,
one row per device, watched and set-aside together and alphabetical,
where a globally excluded device keeps its watched check and names the
tier it was excluded at, and the coverage sensors publish the same
watched and set-aside counts a person reads on the device page. This
file holds that classification behaviour, the combined table, and the
coverage sensors.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    SET_ASIDE_SERVICE,
    CONF_MUTED_DEVICES,
    DATA_DEVICES,
)

from tests.helpers import setup_coordinator, setup_entry

DOMAIN = "device_sentinel"


async def test_attribution_uses_primary_config_entry(hass: HomeAssistant):
    """A multi-homed device attributes to its primary entry's domain."""
    owner = MockConfigEntry(domain="camera_brand")
    owner.add_to_hass(hass)
    tracker = MockConfigEntry(domain="router_tracker")
    tracker.add_to_hass(hass)

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=owner.entry_id,
        identifiers={("camera_brand", "cam1")},
        name="Multi-homed Camera",
    )
    dev_reg.async_update_device(
        device.id, add_config_entry_id=tracker.entry_id
    )
    er.async_get(hass).async_get_or_create(
        "camera", "camera_brand", "cam1_uid",
        device_id=device.id, config_entry=owner,
    )

    coord = await setup_coordinator(hass)
    breakdown = coord.classification_breakdown
    assert breakdown.get("camera_brand", {}).get("watched", 0) == 1
    assert breakdown.get("router_tracker", {}).get("watched", 0) == 0


# ==================================================================
# The classification report is one combined table.
# ==================================================================

def _class_device(hass, uid, name, entities=1):
    """Build a registry device with N enabled entities.

    An entity is not decoration here: ruling #257 sets aside a device
    with nothing enabled, because it has no way to speak, so a
    fixture without one is no longer a watched device.
    """
    src = MockConfigEntry(domain="test", title="Source")
    src.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=src.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    for index in range(entities):
        er.async_get(hass).async_get_or_create(
            "sensor", "test", f"{uid}_{index}",
            device_id=device.id, config_entry=src,
        )
    return device


def _class_rows(hass):
    text = open(
        hass.config.path("device_sentinel/classification.md")
    ).read()
    return [
        line
        for line in text.splitlines()
        if line.startswith("| ") and "---" not in line and "DEVICE |" not in line
    ]


async def test_one_table_three_states(hass: HomeAssistant):
    """A watched device, a globally excluded device, and a service
    device each read correctly in one table."""
    _class_device(hass, "w", "Bravo Watched")
    excluded = _class_device(hass, "e", "Alpha Excluded")
    coord = await setup_coordinator(
        hass, {CONF_MUTED_DEVICES: [excluded.id]}
    )
    coord._muted_devices[excluded.id] = "integration"
    await hass.async_add_executor_job(coord._write_reports, "manual")
    rows = _class_rows(hass)
    text = "\n".join(rows)

    # Excluded device: watched check kept, reason named.
    excl_row = next(r for r in rows if "Alpha Excluded" in r)
    assert "\u2713" in excl_row
    assert "Global (integration)" in excl_row

    # Watched device: watched check, no exclusion.
    w_row = next(r for r in rows if "Bravo Watched" in r)
    assert "\u2713" in w_row
    assert "Global" not in w_row

    # A service device is set aside, no watched check.
    service_row = next(r for r in rows if "Device Sentinel" in r)
    # The reason, not a tick: a disabled device and a service
    # device read identically in a column that can only say yes.
    assert SET_ASIDE_SERVICE in service_row

    # Alphabetical: Alpha before Bravo.
    assert text.index("Alpha Excluded") < text.index("Bravo Watched")


async def test_global_reason_wording(hass: HomeAssistant):
    """The EXCLUDED cell names the tier: Global (label), (device)."""
    d = _class_device(hass, "x", "Label Excluded")
    coord = await setup_coordinator(hass)
    coord._muted_devices[d.id] = "label"
    await hass.async_add_executor_job(coord._write_reports, "manual")
    row = next(r for r in _class_rows(hass) if "Label Excluded" in r)
    assert "Global (label)" in row


# ==================================================================
# Service devices set aside, and the coverage sensors.
# ==================================================================

def _coverage_device(hass, source_entry, index, *, service=False):
    """Create a device with one entity; return the device."""
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=source_entry.entry_id,
        identifiers={("test", f"dev{index}")},
        name=f"Test Device {index}",
        entry_type=dr.DeviceEntryType.SERVICE if service else None,
    )
    ent_reg.async_get_or_create(
        "sensor", "test", f"uid_{index}",
        device_id=device.id, config_entry=source_entry,
    )
    return device


async def test_classification_sets_service_devices_aside(
    hass: HomeAssistant,
):
    """Service devices get no telemetry records; hardware devices do."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    hw = _coverage_device(hass, source, 1)
    svc = _coverage_device(hass, source, 2, service=True)

    entry = await setup_entry(hass)
    coord = entry.runtime_data

    assert hw.id in coord.data[DATA_DEVICES]
    assert svc.id not in coord.data[DATA_DEVICES]
    assert coord.set_aside_count >= 1
    # The integration's own device is service-type: it sets itself aside.
    own = dr.async_get(hass).async_get_device({(DOMAIN, entry.entry_id)})
    assert own is not None
    assert own.id not in coord.data[DATA_DEVICES]


async def test_coverage_sensors(hass: HomeAssistant):
    """The coverage and diagnostics sensors render the registry view."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    _coverage_device(hass, source, 1)
    _coverage_device(hass, source, 2)
    _coverage_device(hass, source, 3, service=True)

    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._notify()
    await hass.async_block_till_done()

    coverage = hass.states.get("sensor.device_sentinel_devices_watched")
    assert coverage is not None
    assert int(coverage.state) == coord.watched_count
    assert coverage.attributes["set_aside"] == coord.set_aside_count
    assert coverage.attributes["learning"]["observing"] >= 2

    # Service Devices Ignored is opt-in since 0.11.11 (ruling #212),
    # so it has no state until enabled. Its numbers are read from the
    # coordinator, which is where the sensor reads them.
    assert hass.states.get(
        "sensor.device_sentinel_service_devices_ignored"
    ) is None
    breakdown = coord.classification_breakdown
    assert breakdown["test"]["watched"] == 2
    assert breakdown["test"]["set_aside"] == 1

    # Clock source was retired at 0.3.12: it counted devices lacking
    # protocol truth, so a higher number read better while meaning
    # worse, and its soak question closed. The split it published is
    # still computed and still reaches diagnostics.
    assert hass.states.get("sensor.device_sentinel_clock_source") is None
    assert coord.clock_source_split["without_last_seen"] >= 0

    learning = hass.states.get("sensor.device_sentinel_devices_learned")
    assert learning is not None
    assert learning.state == "0"


# --------------------------- the row's columns stay in order (#331)

async def test_the_classification_row_keeps_its_columns(
    hass: HomeAssistant,
) -> None:
    """The set-aside reason and the copies count are two columns.

    Both were bound to names that collided with something else in
    the same method. If a rename crossed them, the reason would
    print in the copies column and a person would read a device
    count as a word.
    """
    from homeassistant.helpers import device_registry as dr
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
    )

    coord = await setup_coordinator(hass)
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    # A set-aside device, so the reason column carries a word. Two
    # empty cells cannot tell a swap from a correct row, which is how
    # the first draft of this test passed against the swap.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "r4svc")},
        name="Service Device",
        entry_type=dr.DeviceEntryType.SERVICE,
    )
    coord._rebuild_registry_view()
    await hass.async_add_executor_job(coord._write_reports)
    text = open(
        hass.config.path("device_sentinel/classification.md")
    ).read()
    row = next(
        line
        for line in text.splitlines()
        if "Service Device" in line
    )
    cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
    # DEVICE, INTEGRATION, WATCHED, MUTED, SET ASIDE, COPIES.
    assert len(cells) == 6
    assert cells[4] == "service"
    assert cells[5] == ""
