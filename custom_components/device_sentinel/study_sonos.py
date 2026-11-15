# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/study_sonos.py, Version: 0.29.1 (2026-11-14)

"""What a Sonos house shows, recorded for Extended Diagnostics.

Home Assistant's Sonos integration hears each speaker through event
subscriptions and marks a speaker unavailable when a subscription
fails or the speaker stays silent and does not answer a check. It
restores nothing at a start: a speaker that cannot be reached gets no
entities until it answers. Device Sentinel has not yet run on a Sonos
house, so this records what the integration itself holds
for each speaker, to learn how a speaker reads when it is idle, asleep
on battery, or gone (rule STACK-11). Recorded:

- at each change, one line per speaker: whether the integration calls
  it available, how many subscriptions it holds, whether one failed,
  and whether it has fallen back to polling;
- at each change, one line per Sonos entity that turns unavailable or
  comes back;
- once a day, one line per speaker: how long since the integration
  last heard it.

Everything is read from what the Sonos integration already holds in
Home Assistant; no speaker is asked anything. It detects nothing and
changes no verdict.
"""

from __future__ import annotations

import time
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    PROBE_AGREES,
    PROBE_DETAIL,
    PROBE_DEVICE_ID,
    PROBE_NODE,
    PROBE_NOW,
    PROBE_SENTINEL,
    PROBE_STACK,
    PROBE_WAS,
    PROBE_WHEN,
)

SONOS_DOMAIN = "sonos"
NODE_DAY = "day"
NODE_ENTITY = "entity"


def _speakers(entry: Any) -> dict[str, Any]:
    """The entry's speakers by their Sonos id, or none where the
    integration keeps them some other way."""
    found = getattr(getattr(entry, "runtime_data", None), "discovered", None)
    return {str(uid): speaker for uid, speaker in found.items()} if isinstance(found, dict) else {}


def _heard_ago(speaker: Any) -> int | None:
    """Seconds since the integration last heard the speaker, or None
    where it never has or does not say."""
    last = getattr(speaker, "_last_activity", None)
    if isinstance(last, bool) or not isinstance(last, (int, float)) or last <= 0:
        return None
    return max(0, int(time.monotonic() - last))


def _said(speaker: Any) -> str:
    subscriptions = getattr(speaker, "_subscriptions", None)
    count = len(subscriptions) if isinstance(subscriptions, list) else "unknown"
    return (
        f"available {getattr(speaker, 'available', 'unknown')}, subscriptions {count}, "
        f"a subscription failed {getattr(speaker, 'subscriptions_failed', 'unknown')}, "
        f"polling {getattr(speaker, '_poll_timer', None) is not None}"
    )


class SonosStudyMixin:
    """The Sonos recording, on the study's minute and its file."""

    hass: Any
    _sonos_seen: dict[str, str] | None

    def _sonos_memory(self) -> dict[str, str]:
        memory = getattr(self, "_sonos_seen", None)
        if memory is None:
            memory = {}
            self._sonos_seen = memory
        return memory

    @callback
    def _sonos_clear(self) -> None:
        self._sonos_seen = None

    def _sonos_entries(self) -> list[Any]:
        return [
            entry
            for entry in self.hass.config_entries.async_entries(SONOS_DOMAIN)
            if entry.state is ConfigEntryState.LOADED
        ]

    def _sonos_device_id(self, uid: str) -> str:
        """The Home Assistant device a Sonos id belongs to, read from the
        Sonos entries' own devices (rule STACK-08)."""
        registry = dr.async_get(self.hass)
        for entry in self._sonos_entries():
            for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
                if (SONOS_DOMAIN, uid) in device.identifiers:
                    return device.id
        return ""

    def _sonos_line(self, now: float, node: str, device_id: str, was: str, said: str, detail: str) -> None:
        self._probe_queue({  # type: ignore[attr-defined]
            PROBE_WHEN: now,
            PROBE_STACK: SONOS_DOMAIN,
            PROBE_NODE: node,
            PROBE_DEVICE_ID: device_id,
            PROBE_WAS: was,
            PROBE_NOW: said,
            PROBE_SENTINEL: self._watch_view(device_id, now) if device_id else "",  # type: ignore[attr-defined]
            PROBE_AGREES: "",
            PROBE_DETAIL: detail,
        })

    @callback
    def _sonos_tick(self, now: float) -> None:
        """A line for each change since the last minute."""
        last = self._sonos_memory()
        for entry in self._sonos_entries():
            for uid, speaker in sorted(_speakers(entry).items()):
                said = _said(speaker)
                key = f"speaker|{uid}"
                if last.get(key) != said:
                    heard = _heard_ago(speaker)
                    self._sonos_line(
                        now, uid, self._sonos_device_id(uid), last.get(key, ""), said,
                        f"{getattr(speaker, 'model_name', 'unknown model')}, "
                        f"software {getattr(speaker, 'version', 'unknown')}, "
                        + ("never heard" if heard is None else f"last heard {heard} s ago"),
                    )
                    last[key] = said
        registry = er.async_get(self.hass)
        for row in registry.entities.values():
            if row.platform != SONOS_DOMAIN or row.disabled_by:
                continue
            state = self.hass.states.get(row.entity_id)
            said = (
                "no state" if state is None
                else "unavailable" if state.state == STATE_UNAVAILABLE
                else "available"
            )
            key = f"entity|{row.entity_id}"
            if last.get(key) != said:
                # The first sighting is where it stands, not a change.
                if key in last:
                    self._sonos_line(now, NODE_ENTITY, row.device_id or "", last[key], said, row.entity_id)
                last[key] = said

    @callback
    def _sonos_fold(self, now: float) -> None:
        """One line a day for each speaker: how long since it was heard."""
        for entry in self._sonos_entries():
            for uid, speaker in sorted(_speakers(entry).items()):
                heard = _heard_ago(speaker)
                self._sonos_line(
                    now, NODE_DAY, self._sonos_device_id(uid), "",
                    "never heard" if heard is None else f"last heard {heard} s ago", _said(speaker),
                )

    def sonos_diagnostics(self) -> dict[str, Any]:
        """What the Sonos integration holds now, for the download."""
        registry = er.async_get(self.hass)
        found: list[dict[str, Any]] = []
        for entry in self._sonos_entries():
            speakers = _speakers(entry)
            listed = {}
            for uid, speaker in sorted(speakers.items()):
                device_id = self._sonos_device_id(uid)
                subscriptions = getattr(speaker, "_subscriptions", None)
                listed[uid] = {
                    "device_id": device_id,
                    "model": getattr(speaker, "model_name", None),
                    "software": getattr(speaker, "version", None),
                    "available": getattr(speaker, "available", None),
                    "subscriptions": len(subscriptions) if isinstance(subscriptions, list) else None,
                    "subscription_failed": getattr(speaker, "subscriptions_failed", None),
                    "polling": getattr(speaker, "_poll_timer", None) is not None,
                    "heard_seconds_ago": _heard_ago(speaker),
                    "has_battery": bool(getattr(speaker, "battery_info", None)),
                    "entities": {
                        row.entity_id: (
                            state.state if (state := self.hass.states.get(row.entity_id)) is not None
                            else None
                        )
                        for row in er.async_entries_for_device(registry, device_id)
                        if row.platform == SONOS_DOMAIN
                    } if device_id else {},
                }
            found.append({
                "entry": f"sonos entry {str(entry.entry_id)[-6:]}",
                "speakers_readable": bool(speakers),
                "speakers": listed,
            })
        return {"entries": found}
