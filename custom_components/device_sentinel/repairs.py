# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: repairs.py, Version: 0.18.6 (2026-08-27)

"""What Device Sentinel asks a person to fix, and the flows that fix it.

Every `async_create_issue` and `async_delete_issue` call in the
integration lives here, the same way every bus event lives in
`events.py`, so the rules below are enforced in one place rather than
in each module that happens to notice something.

A device is never the subject of a Repair (ruling #292). The problem
list is what is wrong with a person's devices; Repairs is what is
wrong with Device Sentinel's own ability to do its job, or with the
plumbing beneath it. Every open Repair lights the Settings badge for
as long as it exists, so a frozen motion sensor there would make
Repairs a second and noisier copy of the to-do list and teach a person
to ignore the gear. The line is never crossed.

The rest of the rules, in the order they bite:

One issue per class, keyed by a stable identifier (ruling #293). Ten
bridge flaps in a day are one issue that comes and goes, not ten rows.
The identifier is stable across releases, which is what lets
`storage_shape` gain a fix flow later without becoming a different
issue and orphaning the one a person already has open.

An issue is deleted the moment its condition clears (ruling #294).
Nothing outlives its cause, because a badge lit with nothing behind it
hides the next real issue inside it.

Severity is `warning` by default; `error` is reserved for setup and
storage; `critical` is never used (ruling #295).

An issue is fixable only where a fix flow exists (ruling #296).
`storage_shape` has none in this release because Heal is not built
yet, so it carries a link and says plainly that the repair is coming.

Issues are not persistent (ruling #297). They live in memory and are
re-raised on load if the condition still holds, which makes the
condition the single source of truth: an issue can never survive the
thing it describes, and a restart is a free reconciliation.

Nothing is raised during the startup grace (ruling #291). Everything
reports at once on a restart and none of it is news. The two
evaluation moments are grace close and the midnight fold, which is the
cadence the fold's other periodic work already uses; there is no tick,
deliberately, because a Repair a person has read is worse than useless
if it comes back before they have finished reading it.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.util import dt as dt_util
from homeassistant.core import DOMAIN as HOMEASSISTANT_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .backup import (
    _last_good_holds_devices,
    describe_restore_loss,
)
from .const import (
    CONF_BRIEF_TARGETS,
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_NORMAL_PRIORITY_TARGETS,
    DATA_DEVICES,
    DOMAIN,
    LOGGER,
    NO_DELIVERY_MIN_DAYS,
    PERSISTENT_TARGET,
    REPAIRS_ALL,
    REPAIR_DETAIL_MAX,
    REPAIR_ENTITIES_DISABLED,
    REPAIR_MOMENT_BRIEF,
    REPAIR_MOMENT_GRACE,
    REPAIR_NO_DELIVERY,
    REPAIR_NOTIFY_TARGET_MISSING,
    REPAIR_STORAGE_SHAPE,
    WIKI_LINK_NOTIFICATIONS,
    WIKI_LINK_REPAIRS,
    REPAIR_STORAGE_RESTORED,
    STORAGE_KEY,
)


# ------------------------------------------------------------ helpers


def _english_list(items: list[str], limit: int = REPAIR_DETAIL_MAX) -> str:
    """Return a readable list, naming a few and counting the rest.

    A Repair card is read in a dialog rather than scrolled, so naming
    every one of two hundred faults would bury the sentence that says
    what to do. The first few are named because a person recognises
    their own device by name, and the remainder is a count because the
    exact list is in the log and the diagnostics already.
    """
    if not items:
        return ""
    if len(items) <= limit:
        if len(items) == 1:
            return items[0]
        return ", ".join(items[:-1]) + " and " + items[-1]
    rest = len(items) - limit
    return (
        ", ".join(items[:limit])
        + f", and {rest} other"
        + ("s" if rest > 1 else "")
    )


def _configured_targets(entry: Any) -> list[str]:
    """Return every notification target this entry holds, deduplicated.

    The three lists are read together because the question a Repair
    answers is whether a person can be reached at all, and a target
    that has stopped existing has stopped existing on every list it
    appears on.
    """
    seen: list[str] = []
    for key in (
        CONF_HIGH_PRIORITY_TARGETS,
        CONF_NORMAL_PRIORITY_TARGETS,
        CONF_BRIEF_TARGETS,
    ):
        for target in entry.options.get(key) or []:
            if target and target not in seen:
                seen.append(target)
    return seen


@callback
def missing_targets(hass: HomeAssistant, entry: Any) -> list[str]:
    """Return configured targets whose service no longer exists.

    A target is stored as a service name, so this is a registry read
    and never a send: nothing is delivered to find out whether it
    could be. The persistent notification is always present and is
    skipped, and a stored value that is not a service at all is
    reported alongside the missing ones, because both fail in the
    same way at send time and neither can be fixed by waiting.
    """
    missing: list[str] = []
    for target in _configured_targets(entry):
        if target == PERSISTENT_TARGET:
            continue
        domain, _, service = target.partition(".")
        if not service or not hass.services.has_service(domain, service):
            missing.append(target)
    return missing


@callback
def delivery_is_configured(entry: Any) -> bool:
    """Is there any target at all for a push or the daily brief?

    The persistent card is deliberately not counted here (ruling
    #301). It defaults on, so counting it would mean this never fired
    on a system that had been left exactly as installed, which is the
    system it exists for. What the card does is said in the issue's
    own words instead, so nothing tells the person their card is off
    when it is on.
    """
    for key in (
        CONF_HIGH_PRIORITY_TARGETS,
        CONF_NORMAL_PRIORITY_TARGETS,
        CONF_BRIEF_TARGETS,
    ):
        if [target for target in (entry.options.get(key) or []) if target]:
            return True
    return False


# ------------------------------------------------------- raise, clear


@callback
def _raise(
    hass: HomeAssistant,
    issue_id: str,
    *,
    severity: ir.IssueSeverity,
    is_fixable: bool,
    learn_more_url: str,
    placeholders: dict[str, str] | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    """Create or update one issue.

    Home Assistant treats a second create on a live identifier as an
    update, which is what ruling #293 asks for: a recurrence changes
    the placeholders of the issue already open rather than stacking a
    second row beside it.
    """
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        data=data,
        is_fixable=is_fixable,
        is_persistent=False,
        learn_more_url=learn_more_url,
        severity=severity,
        translation_key=issue_id,
        translation_placeholders=placeholders,
    )


@callback
def _clear(hass: HomeAssistant, issue_id: str) -> None:
    """Delete one issue if it is open, and say nothing if it is not."""
    ir.async_delete_issue(hass, DOMAIN, issue_id)


@callback
def async_clear_all(hass: HomeAssistant) -> None:
    """Delete every issue this integration can raise.

    Called on unload, so an integration that is being removed or
    reconfigured does not leave a badge lit behind it (ruling #240).
    The issues are not persistent, so a restart would clear them
    anyway; this covers the reload and the uninstall, where there is
    no restart to do it.
    """
    for issue_id in REPAIRS_ALL:
        _clear(hass, issue_id)


# ------------------------------------------------------ the four issues


@callback
def _evaluate_storage_shape(
    hass: HomeAssistant,
    faults: list[tuple[str, str, str]],
    namer: Any,
    entry_id: str,
) -> None:
    """Raise or clear the storage shape issue from the last check.

    The description is composed from the fault list rather than from
    the string the system event carries. That string is written for a
    log and reads as one: a card saying "load: 1 fault(s) in 1
    record(s): tainted" tells a person nothing they can act on, and
    the same rawness has already leaked into the daily brief's prose
    once. The device name and the field are what a person can look
    at, so they are what the card names.

    No Fix button in this release, on ruling #296: Heal is not built,
    and a button opening a screen with nothing to press is worse than
    no button. The text says the repair is being built, because the
    alternative is a person reading that their storage is wrong and
    being offered nothing at all. The identifier is fixed now so the
    Phase 4 fix flow attaches to the issue a person already has open
    rather than orphaning it (ruling #293).
    """
    if not faults:
        _clear(hass, REPAIR_STORAGE_SHAPE)
        return
    # A fixable issue carries a flow, not a description (ruling
    # #351), so the card in the list is the title alone and every
    # word a person reads comes from the flow, which composes them
    # from the plan built at the moment they click (ruling #353).
    # The namer stays in the signature because the flow's own words
    # are checked against it in tests.
    _ = namer
    _raise(
        hass,
        REPAIR_STORAGE_SHAPE,
        severity=ir.IssueSeverity.ERROR,
        is_fixable=True,
        learn_more_url=WIKI_LINK_REPAIRS,
        placeholders=None,
        data={"entry_id": entry_id},
    )


@callback
def _evaluate_entities_disabled(
    hass: HomeAssistant, counts: dict[str, int], entry_id: str
) -> None:
    """Raise or clear the disabled-entities issue.

    One issue rather than three, so a fresh install lights the badge
    once and clears it once. The counts are the enable buttons' own,
    so a non-zero count is exactly a press that would do something
    (ruling #237), and both now read watched devices alone, so a
    device Home Assistant disabled can no longer raise an issue whose
    fix Home Assistant immediately undoes (ruling #302).

    The fix is a confirmation rather than a form with a checkbox per
    kind. The form was the plan and was dropped on James's ruling: a
    person who opens this dialog wants the entities Device Sentinel
    needs turned on, and asking them to choose which of three kinds
    they meant is a question with one answer. A person who wants only
    one kind has three buttons on the device page that do exactly
    that.
    """
    total = sum(counts.values())
    if not total:
        _clear(hass, REPAIR_ENTITIES_DISABLED)
        return
    named = [
        f"{count} {kind}"
        for kind, count in (
            ("signal", counts.get("signal", 0)),
            ("last seen", counts.get("last_seen", 0)),
            ("battery", counts.get("battery", 0)),
        )
        if count
    ]
    _raise(
        hass,
        REPAIR_ENTITIES_DISABLED,
        severity=ir.IssueSeverity.WARNING,
        is_fixable=True,
        learn_more_url=WIKI_LINK_REPAIRS,
        placeholders={
            "count": str(total),
            "entities": "entity" if total == 1 else "entities",
            "detail": _english_list(named, limit=3),
        },
        data={"entry_id": entry_id},
    )


@callback
def _evaluate_notify_targets(
    hass: HomeAssistant, missing: list[str], entry_id: str
) -> None:
    """Raise or clear the missing-target issue.

    This is the one condition here that is already breaking something
    quietly. A target whose service has gone is caught at send time
    and written to the log as a warning, so the integration goes on
    watching, goes on judging, and tells nobody, which is this
    project's own failure mode happening inside the project. The
    Repair says it once, in the place a person looks when something
    is wrong.

    Fixable, because removing a target that cannot exist is safe:
    there is nothing behind it to lose. If removing it empties every
    list, the no-delivery issue takes over at the next fold and says
    so, which is the correct chain rather than a silence.
    """
    if not missing:
        _clear(hass, REPAIR_NOTIFY_TARGET_MISSING)
        return
    _raise(
        hass,
        REPAIR_NOTIFY_TARGET_MISSING,
        severity=ir.IssueSeverity.WARNING,
        is_fixable=True,
        learn_more_url=WIKI_LINK_NOTIFICATIONS,
        placeholders={
            "count": str(len(missing)),
            "targets": "target" if len(missing) == 1 else "targets",
            "detail": _english_list(missing),
        },
        data={"entry_id": entry_id},
    )


@callback
def _evaluate_no_delivery(
    hass: HomeAssistant, configured: bool, days_installed: float | None
) -> None:
    """Raise or clear the nothing-configured issue.

    Evaluated at the fold alone and only once the install is old
    enough (ruling #301). A person setting the integration up should
    not be interrupted on their first evening by a badge telling them
    they have not finished, and the seven days are the same week
    freeze detection already asks for: by then they have had seven
    daily briefs they never received, which is the evidence that this
    is a state they have settled into rather than passed through.

    Never fixable. Choosing where a notification goes is a decision
    only the person can make, and a Fix button that opened the
    options screen would be a link wearing a button's clothes.
    """
    if configured or days_installed is None:
        _clear(hass, REPAIR_NO_DELIVERY)
        return
    if days_installed < NO_DELIVERY_MIN_DAYS:
        _clear(hass, REPAIR_NO_DELIVERY)
        return
    _raise(
        hass,
        REPAIR_NO_DELIVERY,
        severity=ir.IssueSeverity.WARNING,
        is_fixable=False,
        learn_more_url=WIKI_LINK_NOTIFICATIONS,
        placeholders={"days": str(int(days_installed))},
    )


@callback
def async_evaluate(
    hass: HomeAssistant,
    entry: Any,
    moment: str,
    *,
    shape_faults: list[tuple[str, str, str]],
    awaiting: dict[str, int],
    days_installed: float | None,
    version_changed: bool,
    namer: Any,
) -> None:
    """Reconcile every issue against the conditions as they stand now.

    One pass, raising what holds and clearing what does not, so an
    issue can never be left open by a path that forgot to clear it.
    The caller supplies the readings rather than this module reaching
    back into the coordinator for them, which keeps the rules here and
    the measurements where they are taken.

    Two of the four are narrower than the two moments (ruling #303).
    Disabled entities are judged when the brief is sent, and
    additionally on the first start after Device Sentinel's own
    version changed, because that is when an integration update
    re-ships its diagnostics turned off and it is the only way the
    state arrives. Judging it at every grace close meant a person who
    restarted seven times in a day met the same badge seven times
    over a condition that had not moved. Nothing configured is the
    brief moment alone (ruling #301).

    Both were the fold's until ruling #309 moved them. A card raised
    at midnight is read by nobody, and an install that reboots
    nightly after midnight closes its grace and clears the card
    before morning, so the condition was judged at the hour least
    likely to reach a person. The brief hour is the hour a person
    looks, and the two arrive together.
    """
    _evaluate_storage_shape(hass, shape_faults, namer, entry.entry_id)
    _evaluate_notify_targets(
        hass, missing_targets(hass, entry), entry.entry_id
    )
    if moment == REPAIR_MOMENT_BRIEF or version_changed:
        _evaluate_entities_disabled(hass, awaiting, entry.entry_id)
    if moment == REPAIR_MOMENT_BRIEF:
        _evaluate_no_delivery(
            hass, delivery_is_configured(entry), days_installed
        )
    LOGGER.debug(
        "Repairs evaluated at %s: %d shape fault(s), %d entity/entities "
        "awaiting enable",
        moment,
        len(shape_faults),
        sum(awaiting.values()),
    )


# ---------------------------------------------------------- fix flows


class _SentinelRepairFlow(RepairsFlow):
    """What the two fix flows share: an entry, and the issue's words.

    The confirmation screen is written from the placeholders the issue
    was raised with rather than from a second measurement taken when
    the dialog opens. One reading behind one set of words, so the card
    a person clicked and the screen it opened can never disagree about
    how many things are wrong. This is what Home Assistant's own
    ConfirmRepairFlow does, for the same reason.
    """

    def __init__(self, entry_id: str) -> None:
        """Remember which entry to act on."""
        self._entry_id = entry_id

    @callback
    def _placeholders(self) -> dict[str, str] | None:
        """Return the placeholders of the issue that opened this flow."""
        registry = ir.async_get(self.hass)
        issue = registry.async_get_issue(self.handler, self.issue_id)
        return issue.translation_placeholders if issue else None

    async def async_step_ignore(
        self, user_input: dict[str, str] | None = None
    ) -> Any:
        """Hide the issue without changing anything (ruling #325).

        Home Assistant offers its own Ignore on an issue that is not
        fixable, and takes it away as soon as one is: a fixable issue
        opens its flow instead of the dialog that carries the button.
        A person who does not want the fix then has no way out of the
        card, which is the fault reported against 0.16.3. The way
        back is to offer the ignore inside the flow, on the same
        registry call Home Assistant would have made, so the issue
        hides and stays hidden until the person shows ignored issues
        again.
        """
        ir.async_ignore_issue(self.hass, DOMAIN, self.issue_id, True)
        return self.async_create_entry(data={})


class EnableEntitiesFlow(_SentinelRepairFlow):
    """Turn on the entities the three enable buttons would turn on."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> Any:
        """Offer the fix and the ignore side by side (ruling #325)."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["confirm", "ignore"],
            description_placeholders=self._placeholders(),
        )

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> Any:
        """Enable the entities, then let the next pass clear the issue.

        The issue is deleted here as well as at the next evaluation.
        Waiting for the fold would leave a badge lit over a condition
        the person has just cleared, and re-checking rather than
        assuming would still find the registry mid-update.
        """
        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                description_placeholders=self._placeholders(),
            )
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is not None and entry.state.recoverable:
            coordinator = entry.runtime_data
            for action in (
                coordinator.async_enable_signal_entities,
                coordinator.async_enable_last_seen_entities,
                coordinator.async_enable_battery_entities,
            ):
                await action()
        _clear(self.hass, REPAIR_ENTITIES_DISABLED)
        return self.async_create_entry(data={})


class StorageRepairFlow(_SentinelRepairFlow):
    """The storage_shape card's Fix: three options, one screen each.

    Restore Backup replaces the file from the last-good copy, the
    same restore the unreadable-file path runs automatically, with
    the copy's age stated in the 0.18.7 wording (ruling #353). Trim
    Record erases only the named damaged records (ruling #354).
    Ignore hides the card and states its cost: the damaged records
    stay unwatched until repaired (rulings #325, #355). Options are
    offered only where they would work: no restore without a usable
    copy, no trim without a damaged device record.
    """

    def __init__(self, entry_id: str) -> None:
        super().__init__(entry_id)
        self._faults: list[tuple[str, str, str]] = []
        self._trim_ids: list[str] = []
        self._copy_taken: float | None = None

    def _coordinator(self) -> Any:
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None or not entry.state.recoverable:
            return None
        return entry.runtime_data

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> Any:
        """Measure at click time, then offer what would work."""
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="entry_not_loaded")
        self._faults = coordinator._gather_current_faults()
        if not self._faults:
            # Everything the card named has cleared since it was
            # raised: a live value overwrote itself, or a restart
            # loaded clean. Nothing to repair is nothing to do.
            _clear(self.hass, REPAIR_STORAGE_SHAPE)
            return self.async_create_entry(data={})
        devices = coordinator.data.get(DATA_DEVICES)
        devices = devices if isinstance(devices, dict) else {}
        quarantined = getattr(coordinator, "_quarantined", {})
        self._trim_ids = sorted(
            {
                holder
                for holder, _field, _why in self._faults
                if holder in devices or holder in quarantined
            }
        )
        usable = await self.hass.async_add_executor_job(
            _last_good_holds_devices, self.hass
        )
        self._copy_taken = coordinator.last_good_taken
        options = []
        if usable:
            options.append("restore")
        if self._trim_ids:
            options.append("trim")
        options.append("ignore")
        return self.async_show_menu(
            step_id="init",
            menu_options=options,
            description_placeholders=self._card_placeholders(),
        )

    @callback
    def _card_placeholders(self) -> dict[str, str]:
        coordinator = self._coordinator()
        namer = getattr(coordinator, "_device_name", str)
        devices = (
            coordinator.data.get(DATA_DEVICES)
            if coordinator is not None
            else {}
        )
        devices = devices if isinstance(devices, dict) else {}
        quarantined = getattr(coordinator, "_quarantined", {})
        lines: list[str] = []
        seen: set[str] = set()
        for holder, field, why in self._faults:
            if holder in seen:
                continue
            seen.add(holder)
            if holder in devices or holder in quarantined:
                fields = sorted(
                    {f for h, f, _w in self._faults if h == holder}
                )
                lines.append(
                    f"{namer(holder)}: {_english_list(fields)}"
                )
            else:
                lines.append(f"{holder}: {why}")
            if len(lines) >= REPAIR_DETAIL_MAX:
                rest = len(
                    {h for h, _f, _w in self._faults}
                ) - REPAIR_DETAIL_MAX
                if rest > 0:
                    lines.append(f"and {rest} more")
                break
        if self._copy_taken is not None:
            age = describe_restore_loss(
                self._copy_taken, dt_util.utcnow().timestamp()
            )
        else:
            age = (
                "The last-good backup could not be dated; its age "
                "is shown before anything runs."
            )
        return {
            "count": str(len(self._faults)),
            "faults": "fault" if len(self._faults) == 1 else "faults",
            "detail": "\n".join(f"- {line}" for line in lines),
            "age": age,
        }

    async def async_step_restore(
        self, user_input: dict[str, str] | None = None
    ) -> Any:
        """Confirm, then run the proven restore and reload."""
        if user_input is None:
            return self.async_show_form(
                step_id="restore",
                data_schema=vol.Schema({}),
                description_placeholders=self._card_placeholders(),
            )
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="entry_not_loaded")
        if not await coordinator.async_restore_from_card():
            return self.async_abort(reason="restore_failed")
        _clear(self.hass, REPAIR_STORAGE_SHAPE)
        return self.async_create_entry(data={})

    async def async_step_trim(
        self, user_input: dict[str, str] | None = None
    ) -> Any:
        """Confirm the one destructive option, naming every device."""
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="entry_not_loaded")
        namer = getattr(coordinator, "_device_name", str)
        if user_input is None:
            names = [namer(d) for d in self._trim_ids]
            return self.async_show_form(
                step_id="trim",
                data_schema=vol.Schema({}),
                description_placeholders={
                    "count": str(len(names)),
                    "devices": (
                        "device" if len(names) == 1 else "devices"
                    ),
                    "names": "\n".join(f"- {n}" for n in names),
                },
            )
        await coordinator.async_trim_from_card(set(self._trim_ids))
        if not coordinator._gather_current_faults():
            _clear(self.hass, REPAIR_STORAGE_SHAPE)
        return self.async_create_entry(data={})


class RemoveDeadTargetsFlow(_SentinelRepairFlow):
    """Remove notification targets whose services no longer exist."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> Any:
        """Offer the fix and the ignore side by side (ruling #325)."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["confirm", "ignore"],
            description_placeholders=self._placeholders(),
        )

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> Any:
        """Drop the dead targets from all three lists.

        Re-read from the live options rather than from the list the
        issue was raised with, because a person may have edited the
        screen since. A target that has come back between the raising
        and the pressing is left alone.
        """
        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                description_placeholders=self._placeholders(),
            )
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is not None:
            dead = set(missing_targets(self.hass, entry))
            options = dict(entry.options)
            for key in (
                CONF_HIGH_PRIORITY_TARGETS,
                CONF_NORMAL_PRIORITY_TARGETS,
                CONF_BRIEF_TARGETS,
            ):
                options[key] = [
                    target
                    for target in (options.get(key) or [])
                    if target not in dead
                ]
            self.hass.config_entries.async_update_entry(
                entry, options=options
            )
            LOGGER.info(
                "Repairs removed %d notification target(s) whose service "
                "no longer exists: %s",
                len(dead),
                ", ".join(sorted(dead)),
            )
        _clear(self.hass, REPAIR_NOTIFY_TARGET_MISSING)
        return self.async_create_entry(data={})


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    """Return the flow behind an issue's Fix button.

    Home Assistant calls this for any issue raised with
    `is_fixable=True`, so every identifier that can arrive here is one
    of the two below. Anything else is a mismatch between what was
    raised and what was built, and a confirmation that changes
    nothing is the safe answer to it rather than an exception in a
    person's dialog.
    """
    payload = data or {}
    entry_id = str(payload.get("entry_id") or "")
    if issue_id == REPAIR_ENTITIES_DISABLED:
        return EnableEntitiesFlow(entry_id)
    if issue_id == REPAIR_NOTIFY_TARGET_MISSING:
        return RemoveDeadTargetsFlow(entry_id)
    if issue_id == REPAIR_STORAGE_SHAPE:
        return StorageRepairFlow(entry_id)
    if issue_id == REPAIR_STORAGE_RESTORED:
        # Nothing left to repair, so the flow is acknowledgement
        # (ruling #350). Home Assistant's own ConfirmRepairFlow shows
        # the issue's words and clears it on Submit, which is exactly
        # what is wanted and is not worth reimplementing.
        return ConfirmRepairFlow()
    LOGGER.warning(
        "Repairs was asked for a fix flow for %s, which has none", issue_id
    )
    return ConfirmRepairFlow()


__all__ = [
    "REPAIR_MOMENT_BRIEF",
    "REPAIR_MOMENT_GRACE",
    "async_clear_all",
    "async_clear_home_assistant_corruption",
    "async_create_fix_flow",
    "async_evaluate",
    "async_raise_restored",
]


@callback
def async_raise_restored(
    hass: HomeAssistant,
    entry_id: str,
    reason: str,
    loss: str,
    where: str,
) -> None:
    """Report a completed restore as a repair card (ruling #350).

    This replaces the persistent notification the restore used to
    post. A persistent notification sits among transient things and
    is dismissed by reflex; a repair card sits in the place a person
    looks for things that need attention, survives a restart, and
    carries a severity of its own.

    A warning rather than an error, because the problem is over by
    the time this is raised: the file has already been replaced and
    the integration is already running. What survives it is the loss,
    and the card says how much.

    Fixable, and the fix is acknowledgement. There is nothing left to
    repair, so a card that could not be cleared without restarting
    would be a critical alert about a solved problem. Pressing Submit
    means the person has read it.
    """
    _raise(
        hass,
        REPAIR_STORAGE_RESTORED,
        severity=ir.IssueSeverity.WARNING,
        is_fixable=True,
        learn_more_url=WIKI_LINK_REPAIRS,
        placeholders={
            "reason": reason,
            "loss": loss,
            "where": where,
        },
        data={"entry_id": entry_id},
    )


@callback
def async_clear_home_assistant_corruption(
    hass: HomeAssistant, corrupt_names: list[str]
) -> int:
    """Remove Home Assistant's own storage-corruption issue.

    When a storage file will not parse, Home Assistant raises a
    critical issue of its own telling the person to repair the file by
    hand and put it back, or to restore the whole system from a
    backup. After a successful restore both instructions are wrong,
    and the second is expensive: a system restore to recover a file
    that has already been recovered (ruling #350).

    The identifier is derived rather than searched for. Home Assistant
    builds the corrupt filename and the issue identifier from the same
    timestamp in the same function, so the text after `.corrupt.` in
    the filename is exactly the text at the end of the identifier.
    Only identifiers built from this integration's own storage key and
    from files sitting beside its own file are ever touched.

    Called only after a restore succeeded. A failed restore leaves the
    issue standing, because then its advice is the right advice.

    Deleting an issue that is not there is not an error, which is what
    makes this safe against an upstream change: if the identifier ever
    stops matching, nothing happens and the issue stays, which is the
    behaviour before this existed.
    """
    cleared = 0
    for name in corrupt_names:
        _, marker, isotime = name.partition(".corrupt.")
        if not marker or not isotime:
            continue
        ir.async_delete_issue(
            hass,
            HOMEASSISTANT_DOMAIN,
            f"storage_corruption_{STORAGE_KEY}_{isotime}",
        )
        cleared += 1
    return cleared
