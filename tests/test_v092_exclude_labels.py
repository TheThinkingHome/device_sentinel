# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v092_exclude_labels.py, Version: 0.9.2 (2026-07-25)

"""0.9.2 tests: exclude pickers disambiguate collided names (#148).

One physical thing integrated two ways (a companion app device and an
MQTT device) registers twice under the same friendly name, different
device ids. The exclude pickers labelled each option by bare name, so
two devices named "NSPanel Pro Randy" showed as identical strings and
neither could be chosen with confidence. The picker stored the right
id underneath but gave the human no way to tell the options apart.

The fix appends the integration each row already carries, so the
options read "NSPanel Pro Randy (mqtt)" and "NSPanel Pro Randy
(mobile_app)". Applied to every option, not only collided ones, so a
person excluding several devices from one integration can see that and
exclude the integration instead.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "device_sentinel"


def _named_device(hass, domain, uid, name, device_class=None):
    """Register a watched device on the given integration domain."""
    source = MockConfigEntry(domain=domain)
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={(domain, uid)},
        name=name,
    )
    er.async_get(hass).async_get_or_create(
        "sensor",
        domain,
        f"{uid}_0",
        device_id=device.id,
        config_entry=source,
        original_device_class=device_class,
    )
    return device


async def _coordinator(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def test_watched_rows_carry_integration_for_collided_names(
    hass: HomeAssistant,
):
    """The two same-named panels are both present as watched rows,
    each with its own integration, which is the raw material the
    picker labels need to tell them apart."""
    _named_device(hass, "mqtt", "panel_mqtt", "NSPanel Pro Randy")
    _named_device(hass, "mobile_app", "panel_app", "NSPanel Pro Randy")
    coord = await _coordinator(hass)

    rows = [
        r
        for r in coord.watched_device_rows
        if r["name"] == "NSPanel Pro Randy"
    ]
    assert len(rows) == 2
    integrations = {r["integration"] for r in rows}
    assert integrations == {"mqtt", "mobile_app"}


async def test_the_two_panels_are_distinct_device_ids(hass: HomeAssistant):
    """The collision is only in the name: the device ids differ, so
    an exclude that addresses the right id reaches exactly one panel.
    This is why the fix is a label change, not an id change."""
    d1 = _named_device(hass, "mqtt", "panel_mqtt", "NSPanel Pro Randy")
    d2 = _named_device(hass, "mobile_app", "panel_app", "NSPanel Pro Randy")
    assert d1.id != d2.id
    coord = await _coordinator(hass)
    ids = {
        r["device_id"]
        for r in coord.watched_device_rows
        if r["name"] == "NSPanel Pro Randy"
    }
    assert ids == {d1.id, d2.id}


async def test_exclude_option_labels_disambiguate_by_integration(
    hass: HomeAssistant,
):
    """The end-to-end proof: the global exclude step offers the two
    panels as distinct, integration-tagged options, so a person can
    pick the mqtt one. Drives the real options flow and reads the
    labels off the rendered schema."""
    _named_device(hass, "mqtt", "panel_mqtt", "NSPanel Pro Randy")
    _named_device(hass, "mobile_app", "panel_app", "NSPanel Pro Randy")
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exclusions"}
    )
    assert result["step_id"] == "exclusions"
    schema = result["data_schema"].schema
    labels = []
    for key in schema:
        selector_obj = schema[key]
        config = getattr(selector_obj, "config", {})
        for opt in config.get("options", []):
            if isinstance(opt, dict):
                labels.append(opt["label"])

    panel_labels = [x for x in labels if "NSPanel Pro Randy" in x]
    assert "NSPanel Pro Randy (mqtt)" in panel_labels
    assert "NSPanel Pro Randy (mobile_app)" in panel_labels
    # The bare, ambiguous name is no longer offered on its own.
    assert "NSPanel Pro Randy" not in panel_labels
