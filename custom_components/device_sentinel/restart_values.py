# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/restart_values.py, Version: 0.29.3 (2026-11-15)

"""Integrations and models that report cached values after a restart
(rule WATCH-12).

After Home Assistant restarts, or an integration reloads, some
integrations show a device's cached values before the device has
spoken. Device Sentinel keeps a list of those integrations, and of the
makes and models a person set on a device page. A device on the list is
reported back only when one of its values changes. Every other device
is taken at its word: a value arriving, even the same value as before,
is the device speaking.

Only a device with no last seen is in scope. A device with a Last Seen
entity, one whose stack keeps that clock for it (ZHA), and a Z-Wave JS
device, whose Last Seen sensor Device Sentinel asks to have turned on
(rule REC-05), are judged by last seen and never by this list.

Two things can show an assumption is wrong, and each is counted and
offered to the person on the device's page:

- A device on the list, still listed as down after a restart with its
  values back. It may be working. "It's Back" clears it; the second
  button also sets its model to report live.
- A device not on the list, reported back at a restart with the same
  values it had, then listed frozen with none of them changed. It may
  never have been back. Its button sets its model to report cached
  values.

Device Sentinel also ships a short list of makes and models known to
report cached values in integrations that otherwise report live. A
person's own setting on a device page comes first.

The starting lists are in docs/TRUSTED_INTEGRATIONS.md and
docs/UNTRUSTED_DEVICES.md, with the reason for each integration and
model checked; a test keeps the files and the code in step.
"""

from __future__ import annotations

from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    CONF_CACHED_ADDED,
    CONF_CACHED_REMOVED,
    CONF_RETENTION_DAYS,
    DATA_DEVICES,
    DEFAULT_RETENTION_DAYS,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_HELD_VALUES,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_UNAVAILABLE,
    FREEZE_CATEGORY_UNKNOWN,
    LOGGER,
)
from .power_source import is_model_key, model_key
from .stacks import last_heard as stack_last_heard

# The integrations that report cached values after a restart, as a
# whole (rule WATCH-12). Each is here because its code shows it, read
# in Home Assistant's source or the integration's own repository and
# its library; docs/TRUSTED_INTEGRATIONS.md gives the day it was checked,
# the reason for each, and for every integration checked and left off.
# An integration where only some models do it is not here: a person
# sets such a model on its device page.
CACHED_VALUE_INTEGRATIONS = frozenset({
    # Restore their saved values at a start and stay available.
    "oralb", "mobile_app", "knx", "octopus_energy", "modbus",
    # Never mark a single device unavailable.
    "lutron_caseta", "lightwave_smart",
    # A cloud or a controller whose stored copy is shown while it
    # answers, whatever the device is doing.
    "unifi", "tado", "august", "yale", "ring", "blink", "withings",
    "tronity", "trmnl", "alarmdotcom",
    # One-way radio receivers whose entities restore and
    # never go unavailable, and Bluetooth scales that are always shown
    # available because they sleep between weighings.
    "rfxtrx", "enocean", "leaone", "okok_scale", "eufylife_ble", "acaia",
    # A hub or cloud whose devices stay available with its last values:
    # Danfoss Link rooms, Drayton Wiser devices, Easee chargers and
    # Navimow mowers; and a printer whose saved values are shown while it
    # can't be reached.
    "danfoss_link", "wiser", "easee", "navimow", "navimower", "snmp_printer",
    # Values handed back at a start: Node-RED's sensors resend their last
    # state, and FlightRadar24's restore theirs.
    "nodered", "flightradar24",
})
# The makes and models that report cached values in integrations that
# otherwise report live (rule WATCH-12): manufacturer, model and model
# ID exactly as each integration writes them, so they match the model
# key a device page sets. Each is here because the integration's code
# or its library marks it as a device that sleeps and is shown with its
# restored values; docs/UNTRUSTED_DEVICES.md gives the reason for each,
# how sure we are, and every model checked and left off. A person's own
# setting on the device page comes first.
CACHED_VALUE_MODEL_NAMES: tuple[tuple[str, str, str], ...] = (
    # Shelly's first generation that sleeps; the second generation has a
    # Last Seen sensor and is judged by it.
    ("Shelly", "Shelly H&T", "SHHT-1"),
    ("Shelly", "Shelly Door/Window", "SHDW-1"),
    ("Shelly", "Shelly Door/Window 2", "SHDW-2"),
    ("Shelly", "Shelly Flood", "SHWT-1"),
    ("Shelly", "Shelly Smoke", "SHSM-01"),
    ("Shelly", "Shelly Smoke 2", "SHSM-02"),
    # Govee Bluetooth models its library marks as sleepy.
    ("Govee", "H5121", ""),
    ("Govee", "H5122", ""),
    ("Govee", "H5123", ""),
    ("Govee", "H5124", ""),
    ("Govee", "H5125", ""),
    ("Govee", "H5126", ""),
    ("Govee", "H5127", ""),
    ("Govee", "H5130", ""),
    # Xiaomi Bluetooth models its library marks as sleepy.
    ("Xiaomi", "CGH1", ""),
    ("Linptech", "ES3", ""),
    ("Xiaomi", "MC-COMM", ""),
    ("Linptech", "ES5BB", ""),
    ("Linptech", "PS1BB", ""),
    ("Xiaomi", "JTYJGD03MI", ""),
    ("Xiaomi", "MCCGQ02HL", ""),
    ("Xiaomi", "MS1BB(MI)", ""),
    ("Xiaomi", "RTCGQ02LM", ""),
    ("Xiaomi", "MMC-W505", ""),
    ("Xiaomi", "RS1BB(MI)", ""),
    ("Xiaomi", "SJWS02LM", ""),
    ("Xiaomi", "XMOSB01XS", ""),
    ("Xiaomi", "MJTZC01YM", ""),
    ("Xiaomi", "MJTZC02YM", ""),
    ("Xiaomi", "MJTZC03YM", ""),
    ("Xiaomi", "HS1BB(MI)", ""),
    ("Xiaomi", "XMPIRO2SXS", ""),
    ("Xiaomi", "XMPIRO2GSXS", ""),
    ("Xiaomi", "M2456B1", ""),
    ("Xiaomi", "M2457B1", ""),
    ("Xiaomi", "zhiee.flood.sj01", ""),
)
CACHED_VALUE_MODELS = frozenset(
    key for key in (model_key(*names) for names in CACHED_VALUE_MODEL_NAMES) if key
)
# Judged by last seen whatever the lists say. ZHA is found by its
# stack's own clock; Z-Wave JS has a Last Seen sensor on every node,
# switched off as it ships, and Device Sentinel asks for it on the Last
# Seen Sensor Switched Off card (rule REC-05).
LAST_SEEN_BY_RULE = frozenset({"zha", "zwave_js"})
# ZHA restores each entity's last state from Home Assistant's store at a
# start, and its own clock tells that from the device speaking. Should
# the clock not be readable, such a value is still not the device.
RESTORES_BEHIND_ITS_CLOCK = frozenset({"zha"})

RESTART_MODE_LIVE = "live"
RESTART_MODE_CACHED = "cached"
RESTART_MODES = (RESTART_MODE_LIVE, RESTART_MODE_CACHED)

DATA_RESTART_VALUES = "restart_values"
CASES = "cases"
RETURNS = "returns"
# A case row: [when, kind, device id, model key or None, restart moment].
CASE_LISTED = "listed"
CASE_FROZEN = "frozen"
CASE_CONFIRMED = "confirmed"
CASE_KINDS = (CASE_LISTED, CASE_FROZEN, CASE_CONFIRMED)
# Card 1 shows once a person has pressed It's Back twice on devices of
# a model. Card 2 has no person behind it, so it waits for three cases
# on at least two restarts: a working device left unused can show the
# pattern once, and one restart can hit several devices of a model.
# First values, to be tuned from real houses' diagnostics.
CARD_LIVE_PRESSES = 2
CARD_CACHED_CASES = 3
CARD_CACHED_RESTARTS = 2
# Watches armed within this many seconds belong to one restart.
SAME_RESTART_SECONDS = 600
CASES_KEPT = 2000
# How long a person's confirmation waits for the device's row to leave
# the Problem List, where its recovery is told.
CONFIRMED_TOLD_SECONDS = 900
CONFIRMED_NAME_LENGTH = 60

RECOVERY_CAUSE_CONFIRMED = "confirmed working"
CONFIRMED_ON_DASHBOARD = "on the Device Sentinel dashboard"


def confirmed_cause(who: str | None) -> str:
    """The cause stored with a recovery a person confirmed."""
    return f"{RECOVERY_CAUSE_CONFIRMED} by {who}" if who else (
        f"{RECOVERY_CAUSE_CONFIRMED} {CONFIRMED_ON_DASHBOARD}"
    )


def is_confirmed_cause(cause: Any) -> bool:
    return isinstance(cause, str) and cause.startswith(RECOVERY_CAUSE_CONFIRMED)


def confirmed_by(cause: str) -> str | None:
    """The person named in a confirmed cause, or None for the dashboard."""
    prefix = f"{RECOVERY_CAUSE_CONFIRMED} by "
    return cause[len(prefix):] if cause.startswith(prefix) else None


def _moment(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _case_ok(row: Any) -> bool:
    return (
        isinstance(row, list)
        and len(row) == 5
        and _moment(row[0])
        and row[1] in CASE_KINDS
        and isinstance(row[2], str)
        and (row[3] is None or isinstance(row[3], str))
        and _moment(row[4])
    )


def stored_domains(options: Any, key: str) -> set[str]:
    """The integrations a person added to or removed from the list, as
    stored in the settings. Anything but a list of names, as a settings
    entry edited by hand can hold, reads as none, so the list is still
    read."""
    value = options.get(key) if hasattr(options, "get") else None
    if not isinstance(value, (list, tuple)):
        return set()
    return {d for d in value if isinstance(d, str)}


def restarts_in(moments: list[float]) -> int:
    """How many restarts a set of watch moments spans."""
    count = 0
    last: float | None = None
    for at in sorted(moments):
        if last is None or at - last > SAME_RESTART_SECONDS:
            count += 1
        last = at
    return count


class RestartValuesMixin:
    """The coordinator's side of the cached-values list."""

    # ------------------------------------------------------------ the list

    def cached_integrations(self) -> set[str]:
        """The integrations taken as reporting cached values: ours, with
        the person's own ticks added and their unticks removed. Their
        changes are saved apart from ours, so an integration added to
        ours in a later release still reaches them."""
        options = self.entry.options  # type: ignore[attr-defined]
        added = stored_domains(options, CONF_CACHED_ADDED)
        removed = stored_domains(options, CONF_CACHED_REMOVED)
        return (set(CACHED_VALUE_INTEGRATIONS) | added) - removed - LAST_SEEN_BY_RULE

    def _restart_scope(self, device_id: str) -> bool:
        """Whether the list can apply to this device: watched, with no
        Last Seen entity, no stack clock, and not Z-Wave JS. A stack
        clock that cannot be read leaves the device as one without
        (rule STACK-04)."""
        domain = self._watched.get(device_id)  # type: ignore[attr-defined]
        return (
            domain is not None
            and domain not in LAST_SEEN_BY_RULE
            and device_id not in self._last_seen_entity  # type: ignore[attr-defined]
            and stack_last_heard(self.hass, domain, device_id) is None  # type: ignore[attr-defined]
        )

    def _restart_model(self, device_id: str) -> tuple[str | None, str | None]:
        """The device's model key and the mode a person set for it."""
        key = self._power_key(device_id)  # type: ignore[attr-defined]
        entry = self._restart_models.get(key) if key else None
        mode = entry.get("mode") if isinstance(entry, dict) else None
        return key, mode if mode in RESTART_MODES else None

    def _reports_cached(self, device_id: str) -> bool:
        """Whether this device's values after a restart are taken as
        cached: the setting a person gave its model first, then Device
        Sentinel's list of models, then its integration's."""
        if not self._restart_scope(device_id):
            return False
        key, mode = self._restart_model(device_id)
        if mode is not None:
            return bool(mode == RESTART_MODE_CACHED)
        if key in CACHED_VALUE_MODELS:
            return True
        return self._watched.get(device_id) in self.cached_integrations()  # type: ignore[attr-defined]

    # --------------------------------------------------------- the answers

    def _restart_reset(self) -> None:
        self._restart_models: dict[str, dict[str, Any]] = {}

    def _restart_read(self, payload: Any) -> int:
        """Read the models a person set. Returns how many were left out."""
        self._restart_reset()
        if payload is None:
            return 0
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, dict):
            return 1
        dropped = 0
        for key, entry in models.items():
            if (
                is_model_key(key)
                and isinstance(entry, dict)
                and entry.get("mode") in RESTART_MODES
                and isinstance(entry.get("set"), str)
            ):
                self._restart_models[key] = {"mode": entry["mode"], "set": entry["set"]}
            else:
                dropped += 1
        return dropped

    def _restart_payload(self) -> dict[str, Any]:
        return {"models": {key: dict(entry) for key, entry in self._restart_models.items()}}

    # ------------------------------------------------------- the records

    def _restart_data(self) -> dict[str, Any]:
        data = self.data.get(DATA_RESTART_VALUES)  # type: ignore[attr-defined]
        if not isinstance(data, dict):
            data = {}
            self.data[DATA_RESTART_VALUES] = data  # type: ignore[attr-defined]
        if not isinstance(data.get(CASES), list):
            data[CASES] = []
        if not isinstance(data.get(RETURNS), dict):
            data[RETURNS] = {}
        return data

    def _restart_returns(self) -> dict[str, dict[str, Any]]:
        """The devices remembered as back across a restart with the
        values they had; an empty table, not stored, where none is."""
        data = self.data.get(DATA_RESTART_VALUES)  # type: ignore[attr-defined]
        found = data.get(RETURNS) if isinstance(data, dict) else None
        return found if isinstance(found, dict) else {}

    def _restart_load(self) -> None:
        """Keep the sound rows of what was stored, and only those within
        How Much History to Keep."""
        self._return_watch: dict[str, float] = {}
        self._confirming: dict[str, str | None] = {}
        self._confirmed: dict[str, tuple[str | None, float]] = {}
        stored = self.data.get(DATA_RESTART_VALUES)  # type: ignore[attr-defined]
        if stored is None:
            return
        data = self._restart_data()
        data[CASES] = [row for row in data[CASES] if _case_ok(row)]
        data[RETURNS] = {
            device_id: entry
            for device_id, entry in data[RETURNS].items()
            if isinstance(device_id, str)
            and isinstance(entry, dict)
            and _moment(entry.get("at"))
            and _moment(entry.get("arm"))
            and isinstance(entry.get("values"), dict)
            and all(isinstance(k, str) and isinstance(v, str) for k, v in entry["values"].items())
            # A device no longer held in the records has nothing to tell.
            and device_id in (self.data.get(DATA_DEVICES) or {})  # type: ignore[attr-defined]
        }
        self._restart_trim()

    def _restart_trim(self) -> None:
        data = self.data.get(DATA_RESTART_VALUES)  # type: ignore[attr-defined]
        if not isinstance(data, dict) or not isinstance(data.get(CASES), list):
            return
        days = int(self.entry.options.get(CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS))  # type: ignore[attr-defined]
        floor = dt_util.utcnow().timestamp() - days * 86400
        kept = [row for row in data[CASES] if row[0] >= floor][-CASES_KEPT:]
        if len(kept) != len(data[CASES]):
            data[CASES] = kept
            self._dirty = True  # type: ignore[attr-defined]

    def _restart_case(self, kind: str, device_id: str, arm: float) -> None:
        """Record one case, by device and by model."""
        data = self._restart_data()
        now = dt_util.utcnow().timestamp()
        data[CASES].append([now, kind, device_id, self._power_key(device_id), float(arm)])  # type: ignore[attr-defined]
        self._restart_trim()
        self._dirty = True  # type: ignore[attr-defined]
        self._critical = True  # type: ignore[attr-defined]
        LOGGER.debug(
            "Device %s: %s after a restart", self._device_name(device_id), kind  # type: ignore[attr-defined]
        )

    def _restart_cases(self, kind: str) -> list[list[Any]]:
        data = self.data.get(DATA_RESTART_VALUES)  # type: ignore[attr-defined]
        rows = data.get(CASES) if isinstance(data, dict) else None
        return [row for row in rows or [] if _case_ok(row) and row[1] == kind]

    # ------------------------------ on the list: still listed, values back

    def restart_pending(self, device_id: str) -> bool:
        """Whether a device on the list is still listed as down after a
        restart or a reload while its values are back: the moment the
        first note is for.

        Judged unavailable or unknown, it would read as up were its
        values taken at their word. Judged frozen, one of the values it
        is watched for shows again.
        """
        watch = self._on_watch.get(device_id)  # type: ignore[attr-defined]
        if not watch:
            return False
        record = (self.data.get(DATA_DEVICES) or {}).get(device_id)  # type: ignore[attr-defined]
        if not isinstance(record, dict):
            return False
        category = record.get(DEV_FROZEN_CATEGORY)
        held = record.get(DEV_HELD_VALUES)
        if category is None or not isinstance(held, dict):
            return False
        if category in (FREEZE_CATEGORY_UNAVAILABLE, FREEZE_CATEGORY_UNKNOWN):
            # Read with the watch lifted, as it would be were the device
            # not on the list.
            self._on_watch.pop(device_id)  # type: ignore[attr-defined]
            try:
                return bool(self._down_now(device_id) == "")  # type: ignore[attr-defined]
            finally:
                self._on_watch[device_id] = watch  # type: ignore[attr-defined]
        if category != FREEZE_CATEGORY_FROZEN:
            return False
        for entity_id, key in self._held_entities(device_id).items():  # type: ignore[attr-defined]
            state = self.hass.states.get(entity_id)  # type: ignore[attr-defined]
            if key in watch and state is not None and self._good_value(state.state):  # type: ignore[attr-defined]
                return True
        return False

    def _restart_note_pending(self, device_id: str) -> None:
        """Count a device on the list found still listed with its values
        back, once for each time it went down."""
        if not self.restart_pending(device_id):
            return
        record = (self.data.get(DATA_DEVICES) or {}).get(device_id) or {}  # type: ignore[attr-defined]
        since = record.get(DEV_FROZEN_SINCE)
        mark = (device_id, since if _moment(since) else None)
        if mark in self._restart_noted:
            return
        self._restart_noted.add(mark)
        if _moment(since) and any(
            row[2] == device_id and row[0] >= since for row in self._restart_cases(CASE_LISTED)
        ):
            # Counted before a restart, for this same time down.
            return
        self._restart_case(CASE_LISTED, device_id, self._restart_arms.get(device_id, self._setup_moment))

    def restart_sweep(self) -> None:
        """Count what the minute's check finds, since a value restored
        before Device Sentinel listened arrives as no event."""
        for device_id in list(self._on_watch):  # type: ignore[attr-defined]
            self._restart_note_pending(device_id)

    # -------------------------- not on the list: back, then frozen unchanged

    def _restart_watch_return(self, device_id: str, record: dict[str, Any]) -> None:
        """A device not on the list, down across a restart or a reload:
        remember the restart, so that its return with the same values
        can be told from one with new values."""
        if record.get(DEV_FROZEN_CATEGORY) is None or not isinstance(record.get(DEV_HELD_VALUES), dict):
            return
        self._return_watch.setdefault(device_id, dt_util.utcnow().timestamp())

    def _restart_note_return(self, device_id: str, record: dict[str, Any]) -> None:
        """As a verdict ends: a device not on the list that came back
        across a restart showing exactly the values it had is
        remembered, with those values. Called before the held values
        are forgotten."""
        arm = self._return_watch.pop(device_id, None)
        had = self._restart_returns().pop(device_id, None)
        if had is not None:
            # Its frozen listing ended, or it went down again: over.
            self._dirty = True  # type: ignore[attr-defined]
        held = record.get(DEV_HELD_VALUES)
        if arm is None or not isinstance(held, dict) or device_id in self._confirming:
            return
        shown: dict[str, str] = {}
        for entity_id, key in self._held_entities(device_id).items():  # type: ignore[attr-defined]
            state = self.hass.states.get(entity_id)  # type: ignore[attr-defined]
            if key not in held or state is None or not self._good_value(state.state):  # type: ignore[attr-defined]
                continue
            if not self._same_value(held[key], state.state):  # type: ignore[attr-defined]
                # A new value: the device spoke.
                return
            shown[key] = held[key]
        if not shown:
            return
        self._restart_data()[RETURNS][device_id] = {
            "at": dt_util.utcnow().timestamp(), "arm": float(arm), "values": shown, "listed": None,
        }
        self._dirty = True  # type: ignore[attr-defined]

    def _restart_return_spoke(self, device_id: str, entity_id: str, state: str) -> None:
        """A changed value from a remembered device: it spoke, so its
        return was real."""
        returns = self._restart_returns()
        entry = returns.get(device_id)
        if entry is None:
            return
        key = self._held_keys.get(entity_id)  # type: ignore[attr-defined]
        stored = entry["values"].get(key) if key is not None else None
        if stored is None or not self._good_value(state) or self._same_value(stored, state):  # type: ignore[attr-defined]
            return
        del returns[device_id]
        self._dirty = True  # type: ignore[attr-defined]

    def _restart_note_listed(self, device_id: str, category: str | None) -> None:
        """As a verdict starts on a remembered device: listed frozen with
        nothing changed is the case the second note is for; any other
        verdict ends the memory."""
        returns = self._restart_returns()
        entry = returns.get(device_id)
        # A new problem: an earlier confirmation is not its cause.
        self.confirmed_told(device_id)
        if entry is None:
            return
        if category != FREEZE_CATEGORY_FROZEN or self._reports_cached(device_id) or not self._restart_scope(device_id):
            del returns[device_id]
            self._dirty = True  # type: ignore[attr-defined]
            return
        if entry.get("listed") is None:
            entry["listed"] = dt_util.utcnow().timestamp()
            self._restart_case(CASE_FROZEN, device_id, entry["arm"])

    def restart_frozen_since(self, device_id: str) -> bool:
        """Whether the second note applies: reported back at a restart
        with the values it had, and now listed frozen with none changed."""
        returns = self._restart_returns()
        entry = returns.get(device_id)
        record = (self.data.get(DATA_DEVICES) or {}).get(device_id)  # type: ignore[attr-defined]
        return bool(
            entry is not None
            and entry.get("listed") is not None
            and isinstance(record, dict)
            and record.get(DEV_FROZEN_CATEGORY) == FREEZE_CATEGORY_FROZEN
        )

    # ------------------------------------------------------- what is shown

    def _model_words(self, device_id: str) -> str:
        maker, model, _model_id, _hw = self._power_device_fields(device_id)  # type: ignore[attr-defined]
        return " ".join(part for part in (maker, model) if part)

    def _restart_count_words(self, device_id: str, kind: str) -> str:
        """How often this has happened to the device, and to others of
        its model."""
        rows = self._restart_cases(kind)
        own = [row for row in rows if row[2] == device_id]
        if len(own) <= 1:
            return "This is the first time this has happened to this device."
        since = dt_util.as_local(dt_util.utc_from_timestamp(min(row[0] for row in own)))
        said = f"This has happened to this device {len(own)} times since {since.strftime('%b')} {since.day}"
        key = self._power_key(device_id)  # type: ignore[attr-defined]
        others = sum(1 for row in rows if key and row[3] == key and row[2] != device_id)
        if others:
            times = "once" if others == 1 else f"{others} times"
            return f"{said}, and to other {self._model_words(device_id)} devices {times}."
        return f"{said}."

    def page_restart(self, device_id: str) -> dict[str, Any] | None:
        """The After a restart row and its notes, or None for a device
        the list never applies to."""
        if not self._restart_scope(device_id):
            return None
        domain = self._watched[device_id]  # type: ignore[attr-defined]
        key, mode = self._restart_model(device_id)
        model = self._model_words(device_id) if key else ""
        title = self._integration_title(domain)  # type: ignore[attr-defined]
        listed = domain in self.cached_integrations()
        model_listed = key in CACHED_VALUE_MODELS
        if mode == RESTART_MODE_LIVE:
            words = f"All {model} devices will be reported back as their values return after a restart."
        elif mode == RESTART_MODE_CACHED:
            words = (
                f"All {model} devices will be reported back only when one of their "
                "values changes after a restart."
            )
        elif model_listed:
            words = (
                f"Device Sentinel lists {model} devices as reporting cached values after "
                "a restart, so this device is reported back only when one of its values "
                "changes."
            )
        elif listed:
            words = (
                f"{title} devices can report cached values after a restart, so this "
                "device is reported back only when one of its values changes."
            )
        else:
            words = (
                f"{title} devices report live, so this device is reported back as its "
                "values return after a restart."
            )
        note: dict[str, Any] | None = None
        if self.restart_pending(device_id):
            note = {
                "kind": "back",
                "name": "Back after a restart?",
                "text": (
                    "Home Assistant restarted while this device was down. Its values are "
                    "back, but Device Sentinel can't tell whether the device sent them or "
                    "its integration restored its cached values. Use the device to check: "
                    "turn it on or off, play something, or open and close it. Device "
                    "Sentinel should clear it as soon as a value changes. If you can't do "
                    "that, and you know it's working, mark it as back."
                ),
                "count": self._restart_count_words(device_id, CASE_LISTED),
                "buttons": [
                    {
                        "action": "back",
                        "label": "It's Back",
                        "under": (
                            "Removes this device from the Problem List. If it happens again "
                            "after a restart, you'll see this note again."
                        ),
                    },
                ],
            }
            if key:
                note["buttons"].append({
                    "action": "back_live",
                    "label": "It's Back, This Model Reports Live",
                    "under": (
                        f"All {model} devices will be reported back as their values return "
                        "after a restart. If one is actually dead, it will show as back until "
                        "its normal reporting time passes, and then be listed frozen."
                    ),
                })
        elif self.restart_frozen_since(device_id):
            note = {
                "kind": "frozen",
                "name": "Frozen since a restart?",
                "text": (
                    "This device was down when Home Assistant restarted. It was reported "
                    "back when its values returned, but none of its values has changed "
                    "since, and it is now listed frozen. Its integration may have restored "
                    "its cached values at the restart. Use the device to check: turn it on "
                    "or off, play something, or open and close it. If it doesn't respond, "
                    "it was never back."
                ),
                "count": self._restart_count_words(device_id, CASE_FROZEN),
                "buttons": [],
            }
            if key:
                note["buttons"].append({
                    "action": "cached",
                    "label": "This Model Reports Cached Values After a Restart",
                    "under": (
                        f"All {model} devices will be reported back only when one of their "
                        "values changes after a restart."
                    ),
                })
        return {
            "name": "After a restart",
            "integration": title,
            "listed": listed,
            # The first choice goes back to Device Sentinel's own setting,
            # which for a model on its list is not its integration's.
            "same_label": "Device Sentinel's Setting" if model_listed else f"Same as {title}",
            # A device that names no make and model follows its integration.
            "can_set": key is not None,
            "mode": mode,
            "words": words,
            "note": note,
        }

    # ------------------------------------------------------------ the acts

    def page_set_restart(self, device_id: str, mode: str | None) -> None:
        """Set how every device of this device's model is read after a
        restart; None goes back to its integration's setting."""
        self._device(device_id)  # type: ignore[attr-defined]
        if mode is not None and mode not in RESTART_MODES:
            raise ValueError("Choose from the three choices.")
        key = self._power_key(device_id)  # type: ignore[attr-defined]
        if key is None or not self._restart_scope(device_id):
            raise ValueError("This device names no make and model, so it follows its integration.")
        before = self._restart_model(device_id)[1]
        if before == mode:
            return
        if mode is None:
            self._restart_models.pop(key, None)
        else:
            self._restart_models[key] = {"mode": mode, "set": dt_util.utcnow().isoformat()}
        self._answers_save()  # type: ignore[attr-defined]
        self.restart_settle()
        model = self._model_words(device_id)
        said = {
            RESTART_MODE_LIVE: f"{model} set to report live after a restart",
            RESTART_MODE_CACHED: f"{model} set to report cached values after a restart",
            None: (
                f"{model} set back to Device Sentinel's setting after a restart"
                if key in CACHED_VALUE_MODELS
                else f"{model} set back to its integration's setting after a restart"
            ),
        }[mode]
        self._page_done(device_id, said)  # type: ignore[attr-defined]

    def restart_settle(self) -> None:
        """After the list or a model's setting changes: a device no
        longer taken as reporting cached values leaves its watch and is
        judged on what it shows, and what was remembered of a device now
        on the list is forgotten."""
        records = self.data.get(DATA_DEVICES) or {}  # type: ignore[attr-defined]
        changed = False
        for device_id in list(self._on_watch):  # type: ignore[attr-defined]
            if self._reports_cached(device_id):
                continue
            self._on_watch.pop(device_id, None)  # type: ignore[attr-defined]
            record = records.get(device_id)
            if isinstance(record, dict):
                self._restart_watch_return(device_id, record)
            changed = True
        returns = self._restart_returns()
        for device_id in list(returns):
            if self._reports_cached(device_id) or not self._restart_scope(device_id):
                del returns[device_id]
                self._dirty = True  # type: ignore[attr-defined]
        for device_id in list(self._return_watch):
            if self._reports_cached(device_id):
                del self._return_watch[device_id]
        if changed:
            self._judge_now()  # type: ignore[attr-defined]

    def page_confirm_back(self, device_id: str, who: str | None, live: bool = False) -> None:
        """A person says the device is working: it leaves the Problem
        List as a recovery, told as confirmed, and the press is counted.
        With live, its model is set to report live as well."""
        self._device(device_id)  # type: ignore[attr-defined]
        if not self.restart_pending(device_id):
            raise ValueError("This device is no longer waiting to be confirmed.")
        record = self.data[DATA_DEVICES][device_id]  # type: ignore[attr-defined]
        self._restart_case(CASE_CONFIRMED, device_id, self._restart_arms.get(device_id, self._setup_moment))
        entry_id = None
        for entity_id in self._own_entities.get(device_id, ()):  # type: ignore[attr-defined]
            mapped = self._entity_map.get(entity_id)  # type: ignore[attr-defined]
            if mapped is not None:
                entry_id = mapped[1]
                break
        # The name as Home Assistant holds it, kept to what can be shown
        # on one line of an alert.
        name = "".join(ch for ch in (who or "") if ch.isprintable()).strip()[:CONFIRMED_NAME_LENGTH]
        self._confirming[device_id] = name or None
        # Kept until the device's row leaves the Problem List, which is
        # where its recovery is told, a moment later.
        self._confirmed[device_id] = (self._confirming[device_id], dt_util.utcnow().timestamp())
        try:
            # The person's word stands for the device's: the watch ends,
            # its clock starts again, and its verdict clears.
            self._release_values(device_id, record)  # type: ignore[attr-defined]
            self._confirm_activity(device_id, entry_id)  # type: ignore[attr-defined]
        finally:
            self._confirming.pop(device_id, None)
        if live:
            self.page_set_restart(device_id, RESTART_MODE_LIVE)
        else:
            self._page_done(device_id, "confirmed working after a restart")  # type: ignore[attr-defined]

    def _confirm_activity(self, device_id: str, entry_id: str | None) -> None:
        self._record_activity(device_id, entry_id)  # type: ignore[attr-defined]
        self._judge_now()

    def _judge_now(self) -> None:
        """Judge the house again at once, as the minute's check does."""
        self._judge_all_devices()  # type: ignore[attr-defined]
        self._sync_problem_list()  # type: ignore[attr-defined]
        self._notify()  # type: ignore[attr-defined]

    def confirming(self, device_id: str) -> str | None:
        """The cause to store while a person's confirmation clears a
        device, or None."""
        told = self._confirmed.get(device_id)
        if told is None:
            return None
        if dt_util.utcnow().timestamp() - told[1] > CONFIRMED_TOLD_SECONDS:
            del self._confirmed[device_id]
            return None
        return confirmed_cause(told[0])

    def confirmed_told(self, device_id: str) -> None:
        """The confirmed recovery has been told, or a new problem began."""
        self._confirmed.pop(device_id, None)

    # ------------------------------------------------------------ the cards

    def _restart_model_rows(self, key: str) -> list[str]:
        return sorted(
            d for d in self._power_same_model(key)  # type: ignore[attr-defined]
            if d in self._watched and self._restart_scope(d)  # type: ignore[attr-defined]
        )

    def restart_recommendations(self) -> list[dict[str, Any]]:
        """The models whose cases have reached a card's count, one row
        a model, each with the device to set it through."""
        found: list[dict[str, Any]] = []
        by_model: dict[tuple[str, str], list[list[Any]]] = {}
        for kind in (CASE_CONFIRMED, CASE_FROZEN):
            for row in self._restart_cases(kind):
                if row[3]:
                    by_model.setdefault((kind, row[3]), []).append(row)
        for (kind, key), rows in sorted(by_model.items()):
            devices = self._restart_model_rows(key)
            if not devices:
                continue
            mode = self._restart_model(devices[0])[1]
            since = dt_util.as_local(dt_util.utc_from_timestamp(min(row[0] for row in rows)))
            when = f"{since.strftime('%b')} {since.day}"
            model = self._model_words(devices[0])
            count = "1 device" if len(devices) == 1 else f"{len(devices)} devices"
            if kind == CASE_CONFIRMED:
                if len(rows) < CARD_LIVE_PRESSES or mode == RESTART_MODE_LIVE:
                    continue
                if not any(self._reports_cached(d) for d in devices):
                    continue
                found.append({
                    "card": RESTART_MODE_LIVE,
                    "model_key": key,
                    "model": model,
                    "device_id": devices[0],
                    "devices": devices,
                    "text": (
                        f"{model}, {count}. {len(rows)} times since {when}, a {model} was "
                        "listed as down after a restart with its values back, and was "
                        "marked back each time. If these devices are working when that "
                        "happens, set the model to report live."
                    ),
                    "button": "Set to Reports Live",
                    "under": (
                        f"All {model} devices will be reported back as their values return "
                        "after a restart. If one is actually dead, it will show as back until "
                        "its normal reporting time passes, and then be listed frozen."
                    ),
                })
            else:
                if (
                    len(rows) < CARD_CACHED_CASES
                    or restarts_in([row[4] for row in rows]) < CARD_CACHED_RESTARTS
                    or mode == RESTART_MODE_CACHED
                ):
                    continue
                if all(self._reports_cached(d) for d in devices):
                    continue
                found.append({
                    "card": RESTART_MODE_CACHED,
                    "model_key": key,
                    "model": model,
                    "device_id": devices[0],
                    "devices": devices,
                    "text": (
                        f"{model}, {count}. {len(rows)} times since {when}, a {model} was "
                        "reported back after a restart, then later listed frozen with none "
                        "of its values changed. If these devices were not working when that "
                        "happened, set the model to report cached values."
                    ),
                    "button": "Set to Reports Cached Values",
                    "under": (
                        f"All {model} devices will be reported back only when one of their "
                        "values changes after a restart."
                    ),
                })
        return found

    # --------------------------------------------------------- the settings

    def restart_settings_rows(self) -> list[dict[str, Any]]:
        """Each integration the settings list offers: those with a
        watched device the list can apply to, and any other already on
        the list here. Each says which of its models a person set on
        their device pages."""
        registry_models: dict[str, dict[str, list[str]]] = {}
        domains: set[str] = set()
        for device_id, domain in self._watched.items():  # type: ignore[attr-defined]
            # Only an integration with a device the list can apply to is
            # offered: ticking one whose devices all have a Last Seen
            # would change nothing.
            if not self._restart_scope(device_id):
                continue
            domains.add(domain)
            key, mode = self._restart_model(device_id)
            if key and mode:
                names = registry_models.setdefault(domain, {}).setdefault(mode, [])
                model = self._model_words(device_id)
                if model not in names:
                    names.append(model)
        options = self.entry.options  # type: ignore[attr-defined]
        domains |= stored_domains(options, CONF_CACHED_ADDED) - LAST_SEEN_BY_RULE
        rows = []
        for domain in domains:
            title = self._integration_title(domain)  # type: ignore[attr-defined]
            label = title
            for mode, verb in ((RESTART_MODE_LIVE, "live"), (RESTART_MODE_CACHED, "cached values")):
                names = sorted(registry_models.get(domain, {}).get(mode, []), key=str.casefold)
                if not names:
                    continue
                if len(names) == 1:
                    label += f". {names[0]} reports {verb}, set on its device page."
                elif len(names) == 2:
                    label += f". {names[0]} and {names[1]} report {verb}, set on their device pages."
                else:
                    label += (
                        f". {len(names)} models report {verb}, set on their device pages: "
                        f"{', '.join(names)}."
                    )
            rows.append({"domain": domain, "label": label})
        rows.sort(key=lambda row: row["label"].casefold())
        return rows

    # ------------------------------------------------------- diagnostics

    def restart_diagnostics(self) -> dict[str, Any]:
        """The list in use, what the person changed, the models set, and
        every case counted, for the download (rule STOR-21)."""
        options = self.entry.options  # type: ignore[attr-defined]
        returns = self._restart_returns()
        data = self.data.get(DATA_RESTART_VALUES)  # type: ignore[attr-defined]
        cases = [row for row in (data.get(CASES) if isinstance(data, dict) else None) or [] if _case_ok(row)]
        return {
            "integrations": sorted(self.cached_integrations()),
            "added": sorted(stored_domains(options, CONF_CACHED_ADDED)),
            "removed": sorted(stored_domains(options, CONF_CACHED_REMOVED)),
            "models": {key: dict(entry) for key, entry in self._restart_models.items()},
            "listed_models_present": sorted({
                key for d in self._watched  # type: ignore[attr-defined]
                if (key := self._power_key(d)) in CACHED_VALUE_MODELS  # type: ignore[attr-defined]
            }),
            "devices_in_scope": len([d for d in self._watched if self._restart_scope(d)]),  # type: ignore[attr-defined]
            "devices_reporting_cached": len([d for d in self._watched if self._reports_cached(d)]),  # type: ignore[attr-defined]
            "cases": [
                {"at": row[0], "kind": row[1], "device_id": row[2], "model": row[3], "restart": row[4]}
                for row in cases
            ],
            "returned_unchanged": {
                device_id: {"at": entry.get("at"), "restart": entry.get("arm"), "listed": entry.get("listed")}
                for device_id, entry in returns.items()
            },
            "counts": {
                "card_live_presses": CARD_LIVE_PRESSES,
                "card_cached_cases": CARD_CACHED_CASES,
                "card_cached_restarts": CARD_CACHED_RESTARTS,
            },
        }
