# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: device_notes.py, Version: 0.29.5 (2026-11-17)

"""A person's own note on a device (rule DEV-19).

One line of the person's own words on each device page, empty until
they write one: "Previously the terrace door sensor in the guest room",
"Put in service on 10/10/2025". Device Sentinel reads nothing in it and
says nothing about how to use it; it is a place for what a person would
otherwise keep elsewhere.

It is an answer, so it lives in the answers file beside the power and
type answers (rule STOR-20), stays through a Data Trim (rule CFG-10),
and goes with the device's record, as a battery replacement's day does.
The download says only that a note exists, never its words, since a
note can hold anything (rule STOR-21).

The answers file's part: {"notes": {device_id: {"text": "...", "set": time}}}.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import DATA_DEVICES

# Long enough for a sentence or two, short enough to sit on the page.
NOTE_MAX_CHARACTERS = 500


def _entry_ok(raw: Any) -> dict[str, str] | None:
    """A stored note, or None for one that is not one."""
    if not isinstance(raw, dict):
        return None
    text, when = raw.get("text"), raw.get("set")
    if not isinstance(text, str) or not text.strip() or not isinstance(when, str):
        return None
    # Held to what the pencil accepts, so a file edited by hand cannot put
    # a page's worth of text, or a hidden character, on the device page.
    if len(text) > NOTE_MAX_CHARACTERS or any(
        unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn") for ch in text
    ):
        return None
    return {"text": text, "set": when[:64]}


class DeviceNotesMixin:
    """The coordinator's side of the Notes row."""

    _device_notes: dict[str, dict[str, str]]

    def _notes(self) -> dict[str, dict[str, str]]:
        """This coordinator's notes, never a dictionary shared between two."""
        if "_device_notes" not in self.__dict__:
            self._device_notes = {}
        return self._device_notes

    def _notes_read(self, payload: Any) -> int:
        """Take the notes from the answers file; a malformed one is
        dropped and counted (rule STOR-09)."""
        kept: dict[str, dict[str, str]] = {}
        dropped = 0
        if isinstance(payload, dict):
            for device_id, raw in payload.items():
                entry = _entry_ok(raw)
                if entry is None:
                    dropped += 1
                else:
                    kept[str(device_id)] = entry
        elif payload is not None:
            dropped += 1
        self._device_notes = kept
        return dropped

    def _notes_payload(self) -> dict[str, dict[str, str]]:
        return {device_id: dict(entry) for device_id, entry in self._notes().items()}

    def device_note(self, device_id: str) -> str | None:
        """The device's note as the person wrote it, or None."""
        entry = self._notes().get(device_id)
        return entry["text"] if entry else None

    def page_set_note(self, device_id: str, text: str | None) -> None:
        """Write, change or clear a device's note (rule DEV-19).

        One line: the same refusal of hidden and control characters as
        a rename (rule DEV-05), a line break among them, and no more than
        NOTE_MAX_CHARACTERS. The log records that the note changed and
        where, never its words (rule BRIEF-07).
        """
        self._device(device_id)  # type: ignore[attr-defined]
        wanted = (text or "").strip()
        if any(unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn") for ch in wanted):
            raise ValueError("A note is one line, and that text holds characters that cannot be shown.")
        if len(wanted) > NOTE_MAX_CHARACTERS:
            raise ValueError(f"A note holds up to {NOTE_MAX_CHARACTERS} characters.")
        notes = self._notes()
        had = device_id in notes
        if not wanted:
            if not had:
                return
            del notes[device_id]
            what = "note cleared"
        else:
            if had and notes[device_id]["text"] == wanted:
                return
            notes[device_id] = {"text": wanted, "set": dt_util.utcnow().isoformat()}
            what = "note changed" if had else "note added"
        self._answers_save()  # type: ignore[attr-defined]
        self._page_done(device_id, what)  # type: ignore[attr-defined]

    def _settle_notes(self) -> None:
        """A note goes when its device has left Home Assistant and its
        held record is gone, as a power answer does. Excluding a device,
        which keeps no record, keeps its note (rules DEV-19, STOR-20)."""
        devices = self.data.get(DATA_DEVICES) or {}  # type: ignore[attr-defined]
        registry = dr.async_get(self.hass)  # type: ignore[attr-defined]
        notes = self._notes()
        gone = [
            device_id for device_id in notes
            if device_id not in devices and registry.async_get(device_id) is None
        ]
        for device_id in gone:
            del notes[device_id]
        if gone:
            self._answers_save()  # type: ignore[attr-defined]
