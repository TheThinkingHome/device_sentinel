# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_repairs.py, Version: 0.18.6 (2026-08-27)

"""What reaches the Repairs panel, and what is kept out of it.

Rulings #292 through #297, #300 and #301. Four issues, none of them
about a device, each raised on a condition and deleted the moment it
clears.

Three of these tests would have caught a real fault rather than a
hypothetical one. The grace test is the whole reason the load-time
shape check stores its result instead of raising where it runs. The
translation test exists because Repairs renders from the translation
files alone, so an identifier without an entry shows a person a raw
key and no Python test would notice. And the fixable-versus-text test
pins the sentence saying the repair is not built to the flag that
makes it true, so the day Heal ships, the release that makes the
issue fixable has to correct the words in the same change.
"""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    CONF_BRIEF_TARGETS,
    DATA_DEVICES,
    DEV_FIRST_OBSERVED,
    STORAGE_KEY,
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_NORMAL_PRIORITY_TARGETS,
    DATA_FIRST_INSTALLED,
    DOMAIN,
    NO_DELIVERY_MIN_DAYS,
    REPAIRS_ALL,
    REPAIR_ENTITIES_DISABLED,
    REPAIR_MOMENT_BRIEF,
    REPAIR_MOMENT_GRACE,
    REPAIR_NO_DELIVERY,
    REPAIR_NOTIFY_TARGET_MISSING,
    REPAIR_STORAGE_SHAPE,
)
from custom_components.device_sentinel import repairs as repairs_module
from custom_components.device_sentinel.records import _new_device_record

from .helpers import register_device, setup_coordinator, setup_entry


COMPONENT = Path(repairs_module.__file__).parent


def _issue(hass: HomeAssistant, issue_id: str):
    """Return one of our issues from the registry, or None."""
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


def _disabled_battery_entity(hass: HomeAssistant, uid: str) -> None:
    """Register a device with a battery sensor disabled by its own
    integration, which is the state the enable buttons exist for."""
    device, (entity_id,) = register_device(hass, uid)
    registry = er.async_get(hass)
    registry.async_update_entity(
        entity_id,
        device_class="battery",
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    registry.async_update_entity(entity_id, unit_of_measurement="%")


# ------------------------------------------------------ the two rules


async def test_no_issue_is_about_a_device(hass: HomeAssistant) -> None:
    """No identifier carries a device id (ruling #292).

    The rule is that Repairs is never a second copy of the problem
    list. The mechanical form of it is that every issue this
    integration can raise is one of four fixed strings, so no code
    path can key one on a device.
    """
    coordinator = await setup_coordinator(hass)
    device, _ = register_device(hass, "dev_a")
    coordinator._shape_faults = [(device.id, "daily_max", "expected list")]
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()

    for issue_id, issue in ir.async_get(hass).issues.items():
        if issue_id[0] != DOMAIN:
            continue
        assert issue_id[1] in REPAIRS_ALL
        assert device.id not in issue_id[1]


async def test_nothing_raised_during_the_startup_grace(
    hass: HomeAssistant, hass_storage
) -> None:
    """Setup alone raises nothing, however bad the storage is
    (ruling #291).

    The fault is planted in the stored file rather than assigned to
    the coordinator afterwards, so the load-time check finds it for
    itself. That distinction is the test: an earlier version of this
    set the faults after setup had finished, which meant the load
    check ran against an empty file and the test passed whether or
    not the issue was held. Raising from inside _check_storage_shape
    now fails here, which was the whole claim.
    """
    device, _ = register_device(hass, "dev_grace")
    # first_observed rather than a series or the taint. The load path
    # legitimately rewrites several fields before the check runs: the
    # epoch clears the statistics and #164's coercion repairs an old
    # taint, so a fault planted in either heals itself before the
    # check can see it and the test would prove nothing. This field
    # nothing on that path touches.
    record = _new_device_record("2026-08-17T00:00:00+00:00", 1.0)
    record[DEV_FIRST_OBSERVED] = 12345
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "key": STORAGE_KEY,
        "data": {DATA_DEVICES: {device.id: record}},
    }
    coordinator = await setup_coordinator(hass)
    await hass.async_block_till_done()

    # The load check has run and found the planted fault.
    assert coordinator._shape_faults
    # And nothing has reached Settings, because grace has not closed.
    assert _issue(hass, REPAIR_STORAGE_SHAPE) is None

    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_STORAGE_SHAPE) is not None


# ---------------------------------------------------- storage_shape


async def test_storage_shape_raised_and_cleared(
    hass: HomeAssistant,
) -> None:
    """Raised on a fault, deleted on the next clean pass (#294)."""
    coordinator = await setup_coordinator(hass)
    device, _ = register_device(hass, "dev_shape", name="Temperature Outdoors")
    coordinator._shape_faults = [(device.id, "tainted", "expected reason")]
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()

    issue = _issue(hass, REPAIR_STORAGE_SHAPE)
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.ERROR
    assert issue.is_fixable is False
    assert issue.is_persistent is False

    coordinator._shape_faults = []
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_STORAGE_SHAPE) is None


async def test_storage_shape_names_the_device_and_field(
    hass: HomeAssistant,
) -> None:
    """The card is composed from the fault list, not from the log line.

    The system event carries "load: 1 fault(s) in 1 record(s):
    tainted", which is written for a log and reads as one. A person
    looking at Settings needs the device they can go and look at.
    """
    coordinator = await setup_coordinator(hass)
    device, _ = register_device(hass, "dev_named", name="Temperature Outdoors")
    coordinator._shape_faults = [(device.id, "tainted", "expected reason")]
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()

    placeholders = _issue(hass, REPAIR_STORAGE_SHAPE).translation_placeholders
    assert placeholders["count"] == "1"
    assert placeholders["records"] == "record"
    assert "Temperature Outdoors" in placeholders["detail"]
    assert "tainted" in placeholders["detail"]
    assert "fault(s)" not in placeholders["detail"]


async def test_storage_shape_counts_the_rest(hass: HomeAssistant) -> None:
    """Beyond three records the card names three and counts the rest."""
    coordinator = await setup_coordinator(hass)
    faults = []
    for index in range(5):
        device, _ = register_device(hass, f"dev_many{index}")
        faults.append((device.id, "daily_max", "expected list"))
    coordinator._shape_faults = faults
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()

    placeholders = _issue(hass, REPAIR_STORAGE_SHAPE).translation_placeholders
    assert placeholders["count"] == "5"
    assert placeholders["records"] == "records"
    assert "and 2 other records" in placeholders["detail"]


async def test_recurrence_updates_rather_than_stacks(
    hass: HomeAssistant,
) -> None:
    """A second fault changes the open issue; it does not add one
    (ruling #293)."""
    coordinator = await setup_coordinator(hass)
    first, _ = register_device(hass, "dev_one")
    second, _ = register_device(hass, "dev_two")

    coordinator._shape_faults = [(first.id, "tainted", "expected reason")]
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()

    coordinator._shape_faults = [
        (first.id, "tainted", "expected reason"),
        (second.id, "daily_max", "expected list"),
    ]
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()

    ours = [
        key
        for key in ir.async_get(hass).issues
        if key[0] == DOMAIN and key[1] == REPAIR_STORAGE_SHAPE
    ]
    assert len(ours) == 1
    assert _issue(hass, REPAIR_STORAGE_SHAPE).translation_placeholders[
        "count"
    ] == "2"


# ------------------------------------------------- entities_disabled


async def test_entities_disabled_raised_and_fixed(
    hass: HomeAssistant,
) -> None:
    """Raised on a disabled entity, and the fix flow enables it.

    Grace close raises it here because a test install has no stored
    version, so every setup reads as an upgrade, which is the
    condition of ruling #303. The two tests below pin that rather
    than leaving it as an accident of the fixture.
    """
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    _disabled_battery_entity(hass, "dev_batt")
    coordinator._rebuild_registry_view()
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()

    issue = _issue(hass, REPAIR_ENTITIES_DISABLED)
    assert issue is not None
    assert issue.is_fixable is True
    assert issue.severity == ir.IssueSeverity.WARNING

    flow = await repairs_module.async_create_fix_flow(
        hass, REPAIR_ENTITIES_DISABLED, {"entry_id": entry.entry_id}
    )
    flow.hass = hass
    flow.handler = DOMAIN
    flow.issue_id = REPAIR_ENTITIES_DISABLED
    menu = await flow.async_step_init()
    assert menu["type"] == "menu"
    assert menu["menu_options"] == ["confirm", "ignore"]
    await flow.async_step_confirm({})
    await hass.async_block_till_done()

    assert _issue(hass, REPAIR_ENTITIES_DISABLED) is None
    assert coordinator.awaiting_enable_counts()["battery"] == 0


async def test_entities_disabled_absent_when_nothing_is_off(
    hass: HomeAssistant,
) -> None:
    """A tidy system sees no issue at all."""
    coordinator = await setup_coordinator(hass)
    register_device(hass, "dev_clean")
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_ENTITIES_DISABLED) is None


async def test_disabled_entities_are_not_raised_at_every_restart(
    hass: HomeAssistant, hass_storage
) -> None:
    """An ordinary restart says nothing about disabled entities
    (ruling #303).

    Seven restarts in one day on the reference fleet is what this
    exists for: the condition has not moved, so meeting the badge
    seven times is noise. Storage is seeded with the running version
    so this start is not an upgrade.
    """
    from custom_components.device_sentinel.const import (
        DATA_LAST_VERSION,
        DATA_DEVICES as _DEVICES,
    )

    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "key": STORAGE_KEY,
        "data": {_DEVICES: {}, DATA_LAST_VERSION: "0.16.1"},
    }
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    coordinator.version = "0.16.1"
    coordinator._version_changed = False
    _disabled_battery_entity(hass, "dev_quiet")
    coordinator._rebuild_registry_view()

    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_ENTITIES_DISABLED) is None

    # The brief send is where it does reach a person (ruling #309).
    coordinator._evaluate_repairs(REPAIR_MOMENT_BRIEF)
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_ENTITIES_DISABLED) is not None


async def test_an_upgrade_raises_it_without_waiting_for_the_brief(
    hass: HomeAssistant,
) -> None:
    """The first start on a new version checks straight away
    (ruling #303).

    An integration update is when diagnostics arrive turned off, so a
    person who has just upgraded is the one person for whom this is
    news the same day.
    """
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    assert coordinator._version_changed is True
    _disabled_battery_entity(hass, "dev_upgraded")
    coordinator._rebuild_registry_view()
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_ENTITIES_DISABLED) is not None


async def test_a_set_aside_device_never_raises_it(
    hass: HomeAssistant,
) -> None:
    """A device Home Assistant disabled raises nothing (ruling #302).

    The loop this closes: the sweep enabled the entities of a disabled
    device, Home Assistant re-disabled them at the next registry
    write, and the count never reached zero. As a button that was a
    number nobody watched; as a Repair it is a badge that returns
    after every Fix.
    """
    from homeassistant.helpers import device_registry as dr

    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    device, (entity_id,) = register_device(hass, "dev_off")
    registry = er.async_get(hass)
    registry.async_update_entity(
        entity_id, device_class="battery", unit_of_measurement="%"
    )
    dr.async_get(hass).async_update_device(
        device.id, disabled_by=dr.DeviceEntryDisabler.USER
    )
    await hass.async_block_till_done()
    coordinator._rebuild_registry_view()

    assert device.id in coordinator._set_aside
    assert coordinator.awaiting_enable_counts()["battery"] == 0

    coordinator._evaluate_repairs(REPAIR_MOMENT_BRIEF)
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_ENTITIES_DISABLED) is None


async def test_an_excluded_device_still_raises_it(
    hass: HomeAssistant,
) -> None:
    """Exclusion suppresses judgment, never learning (ruling #302).

    So an excluded device is watched, its readings still feed the
    statistics, and a disabled reading on one is still work the button
    would do.
    """
    from custom_components.device_sentinel.const import (
        CONF_MUTED_DEVICES,
    )

    device, (entity_id,) = register_device(hass, "dev_excluded")
    registry = er.async_get(hass)
    registry.async_update_entity(
        entity_id,
        device_class="battery",
        unit_of_measurement="%",
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    entry = await setup_entry(hass, {CONF_MUTED_DEVICES: [device.id]})
    coordinator = entry.runtime_data
    coordinator._rebuild_registry_view()

    assert device.id in coordinator._watched
    assert coordinator.awaiting_enable_counts()["battery"] == 1

    coordinator._evaluate_repairs(REPAIR_MOMENT_BRIEF)
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_ENTITIES_DISABLED) is not None


# -------------------------------------------- notify_target_missing


async def test_missing_target_raised_and_removed(
    hass: HomeAssistant,
) -> None:
    """A target whose service has gone is named, and the fix drops it."""
    entry = await setup_entry(
        hass,
        {
            CONF_HIGH_PRIORITY_TARGETS: ["notify.gone_phone"],
            CONF_BRIEF_TARGETS: ["persistent_notification"],
        },
    )
    coordinator = entry.runtime_data
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()

    issue = _issue(hass, REPAIR_NOTIFY_TARGET_MISSING)
    assert issue is not None
    assert issue.is_fixable is True
    assert "notify.gone_phone" in issue.translation_placeholders["detail"]

    flow = await repairs_module.async_create_fix_flow(
        hass, REPAIR_NOTIFY_TARGET_MISSING, {"entry_id": entry.entry_id}
    )
    flow.hass = hass
    flow.handler = DOMAIN
    flow.issue_id = REPAIR_NOTIFY_TARGET_MISSING
    await flow.async_step_init()
    await flow.async_step_confirm({})
    await hass.async_block_till_done()

    assert _issue(hass, REPAIR_NOTIFY_TARGET_MISSING) is None
    assert entry.options[CONF_HIGH_PRIORITY_TARGETS] == []
    # The living target is left exactly where it was.
    assert entry.options[CONF_BRIEF_TARGETS] == ["persistent_notification"]


async def test_persistent_target_is_never_called_missing(
    hass: HomeAssistant,
) -> None:
    """The persistent notification is always present and never flagged."""
    entry = await setup_entry(
        hass, {CONF_NORMAL_PRIORITY_TARGETS: ["persistent_notification"]}
    )
    entry.runtime_data._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_NOTIFY_TARGET_MISSING) is None


# ------------------------------------------- no_delivery_configured


async def test_no_delivery_waits_for_the_seventh_day(
    hass: HomeAssistant,
) -> None:
    """A fresh install is not interrupted; a settled one is told
    (ruling #301)."""
    coordinator = await setup_coordinator(hass)

    young = dt_util.utcnow() - dt_util.dt.timedelta(days=1)
    coordinator.data[DATA_FIRST_INSTALLED] = young.isoformat()
    coordinator._evaluate_repairs(REPAIR_MOMENT_BRIEF)
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_NO_DELIVERY) is None

    old = dt_util.utcnow() - dt_util.dt.timedelta(
        days=NO_DELIVERY_MIN_DAYS + 1
    )
    coordinator.data[DATA_FIRST_INSTALLED] = old.isoformat()
    coordinator._evaluate_repairs(REPAIR_MOMENT_BRIEF)
    await hass.async_block_till_done()

    issue = _issue(hass, REPAIR_NO_DELIVERY)
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.severity == ir.IssueSeverity.WARNING


async def test_no_delivery_is_a_brief_question_only(
    hass: HomeAssistant,
) -> None:
    """Grace close never raises it, however old the install
    (ruling #300)."""
    coordinator = await setup_coordinator(hass)
    old = dt_util.utcnow() - dt_util.dt.timedelta(days=90)
    coordinator.data[DATA_FIRST_INSTALLED] = old.isoformat()

    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_NO_DELIVERY) is None

    coordinator._evaluate_repairs(REPAIR_MOMENT_BRIEF)
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_NO_DELIVERY) is not None


async def test_one_configured_target_is_enough(
    hass: HomeAssistant,
) -> None:
    """Any target at all clears it, including the brief's own."""
    entry = await setup_entry(
        hass, {CONF_BRIEF_TARGETS: ["persistent_notification"]}
    )
    coordinator = entry.runtime_data
    old = dt_util.utcnow() - dt_util.dt.timedelta(days=90)
    coordinator.data[DATA_FIRST_INSTALLED] = old.isoformat()
    coordinator._evaluate_repairs(REPAIR_MOMENT_BRIEF)
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_NO_DELIVERY) is None


# --------------------------------------------------------- the words


def test_every_identifier_has_translations() -> None:
    """Repairs renders from the translation files alone.

    An identifier with no entry shows a person a raw key, and no
    Python test would see it, because the code path is identical
    either way. Both files are checked, and they are compared to each
    other, which is the build gate's rule written down where a change
    to one of them runs it.
    """
    strings = json.loads((COMPONENT / "strings.json").read_text())
    english = json.loads(
        (COMPONENT / "translations" / "en.json").read_text()
    )
    assert strings == english

    issues = strings["issues"]
    assert set(issues) == set(REPAIRS_ALL)
    for issue_id, block in issues.items():
        assert block["title"], issue_id
        fixable = "fix_flow" in block
        if fixable:
            confirm = block["fix_flow"]["step"]["confirm"]
            assert confirm["title"] and confirm["description"], issue_id
        else:
            assert block["description"], issue_id


def test_the_not_built_sentence_matches_the_fixable_flag() -> None:
    """The storage issue says the repair is not built, and is not
    fixable. Those two must move together.

    Heal ships in a later release and makes this issue fixable. On the
    day it does, this test fails until the sentence is corrected,
    which is the point: a promise about a future release is prose, and
    prose that nothing watches goes stale (ruling #205).
    """
    strings = json.loads((COMPONENT / "strings.json").read_text())
    description = strings["issues"][REPAIR_STORAGE_SHAPE]["description"]
    says_not_built = "not built yet" in description
    has_fix_flow = "fix_flow" in strings["issues"][REPAIR_STORAGE_SHAPE]
    assert says_not_built is not has_fix_flow


def test_no_issue_uses_critical_severity() -> None:
    """Critical is never used (ruling #295).

    A source scan rather than a behavioural test, because the wrong
    severity is a value nobody would think to assert on and the file
    that could introduce it is one file.
    """
    source = (COMPONENT / "repairs.py").read_text()
    assert "CRITICAL" not in source


# ------------------------------------------------------------ unload


async def test_unload_clears_every_issue(hass: HomeAssistant) -> None:
    """Nothing this integration raised outlives it (rulings #240,
    #294)."""
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    device, _ = register_device(hass, "dev_unload")
    coordinator._shape_faults = [(device.id, "tainted", "expected reason")]
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_STORAGE_SHAPE) is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    for issue_id in REPAIRS_ALL:
        assert _issue(hass, issue_id) is None


async def test_unknown_issue_gets_a_harmless_flow(
    hass: HomeAssistant,
) -> None:
    """An identifier with no flow behind it confirms and changes
    nothing, rather than raising inside a person's dialog."""
    flow = await repairs_module.async_create_fix_flow(
        hass, "not_a_real_issue", {}
    )
    assert flow is not None


async def test_the_brief_send_is_what_evaluates_repairs(
    hass: HomeAssistant, hass_storage
) -> None:
    """The scheduled send judges; the fold no longer does.

    Ruling #309. A card raised at midnight is read by nobody, and an
    install rebooting nightly after midnight closes its grace and
    clears the card before morning. Driving the two real scheduled
    callbacks rather than calling the evaluator by hand is the
    point: it proves the wiring, which is exactly where 0.16.9's
    stitch went wrong.
    """
    from custom_components.device_sentinel.const import (
        DATA_LAST_VERSION,
        DATA_DEVICES as _DEVICES,
    )

    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "key": STORAGE_KEY,
        "data": {_DEVICES: {}, DATA_LAST_VERSION: "0.16.1"},
    }
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    coordinator.version = "0.16.1"
    coordinator._version_changed = False
    _disabled_battery_entity(hass, "dev_brief")
    coordinator._rebuild_registry_view()

    await coordinator._on_midnight(dt_util.utcnow())
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_ENTITIES_DISABLED) is None

    await coordinator._on_brief_time(dt_util.utcnow())
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_ENTITIES_DISABLED) is not None


def test_every_fixable_issue_carries_a_flow_and_no_description():
    """hassfest rejects an issue holding both (ruling #351).

    Found when a validate run failed on 0.18.6: `storage_restored`
    was written with a description beside its fix_flow, which no
    integration in Home Assistant core does. A fixable issue shows its
    flow's first step, so the description is never read and its
    presence is a schema error rather than a redundancy.
    """
    import json
    from pathlib import Path

    root = Path("custom_components/device_sentinel")
    for name in ("strings.json", "translations/en.json"):
        data = json.loads((root / name).read_text())
        for issue, block in (data.get("issues") or {}).items():
            if "fix_flow" in block:
                assert "description" not in block, f"{name}: {issue}"
            else:
                assert "description" in block, f"{name}: {issue}"
            assert "title" in block, f"{name}: {issue}"


def test_the_two_string_files_agree():
    """en.json is the shipped copy of strings.json."""
    import json
    from pathlib import Path

    root = Path("custom_components/device_sentinel")
    assert json.loads((root / "strings.json").read_text()) == json.loads(
        (root / "translations/en.json").read_text()
    )
