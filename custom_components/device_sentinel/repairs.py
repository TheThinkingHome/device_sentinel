# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: repairs.py, Version: 0.26.7 (2026-10-19)

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
The identifier is stable across releases, which is what lets an issue
gain a fix flow in a later release without becoming a different issue
and orphaning the one a person already has open.

An issue is deleted the moment its condition clears (ruling #294).
Nothing outlives its cause, because a badge lit with nothing behind it
hides the next real issue inside it.

Severity is `warning` by default; `error` is reserved for setup and
storage; `critical` is never used (ruling #295).

An issue is fixable only where a fix flow exists (ruling #296): the
three storage notices (repaired containers, a repaired record, a
restored file) and a missing notify target have one.
`storage_shape` is no longer raised: storage is repaired where the
fault is found since #370, and the identifier is only cleared, for
installs that raised it before.

A card is for what stops Device Sentinel working now, or a repair it
made (ruling #697). Four cards were retired by it and are cleared at
every evaluation: disabled entities (switched-off sensors are on the
Recommendations tab, one device at a time, #698), nothing to send to
(a recommendation says so), and the two clock notices (told in the
brief).

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
from homeassistant.core import DOMAIN as HOMEASSISTANT_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from .const import (
    SMTP_DOMAIN,
    SMTP_SEND_MESSAGE,
    SMTP_TARGET_PREFIX,
    CONF_BRIEF_TARGETS,
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_NORMAL_PRIORITY_TARGETS,
    DOMAIN,
    LOGGER,
    PERSISTENT_TARGET,
    REPAIRS_ALL,
    REPAIRS_RETIRED,
    REPAIR_DETAIL_MAX,
    REPAIR_MOMENT_BRIEF,
    REPAIR_MOMENT_GRACE,
    REPAIR_NOTIFY_TARGET_MISSING,
    REPAIR_STORAGE_SHAPE,
    REPAIR_STORAGE_REPAIRED,
    REPAIR_CONTAINERS_REPAIRED,
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
    entities = er.async_get(hass)
    for target in _configured_targets(entry):
        if target == PERSISTENT_TARGET:
            continue
        if target.startswith(SMTP_TARGET_PREFIX):
            # An SMTP recipient is present while its entity is and the
            # action that sends to it exists (0.23.0).
            entity_id = target[len(SMTP_TARGET_PREFIX):]
            if entities.async_get(entity_id) is None or not (
                hass.services.has_service(SMTP_DOMAIN, SMTP_SEND_MESSAGE)
            ):
                missing.append(target)
            continue
        domain, _, service = target.partition(".")
        if not service or not hass.services.has_service(domain, service):
            missing.append(target)
    return missing


@callback
def delivery_is_configured(entry: Any) -> bool:
    """Is there any target at all for a push or the daily brief?

    The persistent card is deliberately not counted here (ruling
    #301, a rule #309 kept when it moved #301's timing). A card is
    read only by someone already looking, so it reaches nobody who is
    away; and when it defaulted on, counting it would have meant this
    never fired on a system left exactly as installed, the system it
    exists for. It has defaulted off since 0.22.5 (ruling #462) and
    the rule stands. What the card does is said in the issue's own
    words, so nothing tells the person their card is off when it is
    on.
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
    for issue_id in (*REPAIRS_ALL, *REPAIRS_RETIRED):
        _clear(hass, issue_id)
    # The retired three-option card's identifier (ruling #370),
    # cleared so an install upgraded mid-issue leaves nothing lit.
    _clear(hass, REPAIR_STORAGE_SHAPE)


# ------------------------------------------------------ the four issues


@callback
def _evaluate_containers_repaired(
    hass: HomeAssistant,
    notice: dict[str, str] | None,
    entry_id: str,
) -> None:
    """Raise or clear gate 1's notice (ruling #371).

    Its own card rather than a line inside gate 2's, because the two
    gates answer different questions: this one says the file held a
    container of the wrong kind, which would have stopped the load
    before anything could judge it. Same shape as gate 2's notice: a
    warning, dismissible, nothing to decide.
    """
    if not notice:
        _clear(hass, REPAIR_CONTAINERS_REPAIRED)
        return
    _raise(
        hass,
        REPAIR_CONTAINERS_REPAIRED,
        severity=ir.IssueSeverity.WARNING,
        is_fixable=True,
        learn_more_url=WIKI_LINK_REPAIRS,
        placeholders={
            "what": notice.get("what", ""),
            "where": notice.get("where", ""),
        },
        data={"entry_id": entry_id},
    )


def _evaluate_storage_repaired(
    hass: HomeAssistant,
    notice: dict[str, str] | None,
    entry_id: str,
) -> None:
    """Raise or clear the storage-repaired notice (ruling #370).

    A notice, not a decision: the repair already ran at the point of
    detection, so the card names what was repaired and where the
    originals are and offers nothing to press but acknowledgement.
    No notice this session means nothing was repaired, and the card
    clears, which is the self-clearing the ruling asks for: a
    restart that loads clean starts a session with no notice.
    """
    if not notice:
        _clear(hass, REPAIR_STORAGE_REPAIRED)
        return
    _raise(
        hass,
        REPAIR_STORAGE_REPAIRED,
        severity=ir.IssueSeverity.WARNING,
        is_fixable=True,
        learn_more_url=WIKI_LINK_REPAIRS,
        placeholders={
            "what": notice.get("what", ""),
            "where": notice.get("where", ""),
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
    list, the no-delivery issue takes over at the next brief time and
    says so, which is the correct chain rather than a silence.
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


def async_evaluate(
    hass: HomeAssistant,
    entry: Any,
    moment: str,
    *,
    repair_notice: dict[str, str] | None,
    container_notice: dict[str, str] | None,
) -> None:
    """Reconcile every issue against the conditions as they stand now.

    One pass, raising what holds and clearing what does not, so an
    issue can never be left open by a path that forgot to clear it.
    The caller supplies the readings rather than this module reaching
    back into the coordinator for them, which keeps the rules here and
    the measurements where they are taken. The moment is kept for the
    log, which says when each pass ran.
    """
    _evaluate_storage_repaired(hass, repair_notice, entry.entry_id)
    _evaluate_containers_repaired(hass, container_notice, entry.entry_id)
    # The identifier the retired three-option card used. Cleared
    # unconditionally so an install upgraded mid-issue does not
    # carry a card whose flow no longer exists (ruling #370).
    _clear(hass, REPAIR_STORAGE_SHAPE)
    # The four cards ruling #697 retired, cleared for an install that
    # holds one from before 0.26.7.
    for issue_id in REPAIRS_RETIRED:
        _clear(hass, issue_id)
    _evaluate_notify_targets(
        hass, missing_targets(hass, entry), entry.entry_id
    )
    LOGGER.debug(
        "Repairs evaluated at %s: repair notice %s",
        moment,
        "standing" if (repair_notice or container_notice) else "none",
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
    if issue_id in REPAIRS_RETIRED:
        # A card retired by #697 that an install still showed when
        # Fix was pressed: nothing is left to fix, so it closes.
        return ConfirmRepairFlow()
    if issue_id == REPAIR_NOTIFY_TARGET_MISSING:
        return RemoveDeadTargetsFlow(entry_id)
    if issue_id == REPAIR_CONTAINERS_REPAIRED:
        # The repair already ran (ruling #371); acknowledgement only.
        return ConfirmRepairFlow()
    if issue_id == REPAIR_STORAGE_REPAIRED:
        # The repair already ran (ruling #370); the flow is
        # acknowledgement alone, the same as the restored card.
        return ConfirmRepairFlow()
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
