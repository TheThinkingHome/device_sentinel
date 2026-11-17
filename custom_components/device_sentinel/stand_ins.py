# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: stand_ins.py, Version: 0.29.5 (2026-11-17)

"""The numbers that stand in for names in the diagnostics download.

A download is often attached to a public issue, so it names no device,
area, label, Wi-Fi network or router tracker. Each is given a number
the first time a download needs one, and keeps it: "Device 37" is the
same device in every download this house makes, so two downloads can
be compared. A number is never given to anything else, even after its
device is removed (rule STOR-21).

The numbers are kept in their own file, device_sentinel.stand_ins, a
table that only grows. An older release never reads it. Each download
also writes the key, which tells the numbers back into names, to
diagnostics_key.md in the reports folder: it stays on the person's
system, and is sent only by private email.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

STAND_INS_KEY = "device_sentinel.stand_ins"
STAND_INS_VERSION = 1
KEY_FILE = "diagnostics_key.md"

KINDS = ("device", "area", "label", "entity", "network", "tracker")
# A number is given to at most this many things of one kind; past it, a
# number is still given but not kept, so a house that churns through
# thousands of short-lived trackers cannot grow the file without end.
KEPT_PER_KIND = 5000
NAME_LENGTH_KEPT = 120

_LOCK = "device_sentinel_stand_ins_lock"


def device_word(n: int) -> str:
    return f"Device {n}"


def area_word(n: int) -> str:
    return f"Area {n}"


def label_word(n: int) -> str:
    return f"Label {n}"


def network_word(n: int) -> str:
    return f"SSID-{n:02d}"


def tracker_word(n: int) -> str:
    return f"device_tracker.tracker_{n:02d}"


WORDS = {
    "device": device_word,
    "area": area_word,
    "label": label_word,
    "network": network_word,
    "tracker": tracker_word,
}


class StandInBook:
    """The kept numbers, by kind and by what each stands for."""

    def __init__(self, data: Any = None) -> None:
        self.numbers: dict[str, dict[str, int]] = {kind: {} for kind in KINDS}
        self.names: dict[str, dict[str, str]] = {kind: {} for kind in KINDS}
        self.next: dict[str, int] = dict.fromkeys(KINDS, 1)
        self.changed = False
        # Given this download beyond the kept limit: numbered, not kept.
        self._spare: dict[str, dict[str, int]] = {kind: {} for kind in KINDS}
        if not isinstance(data, dict):
            return
        for kind in KINDS:
            table = data.get(kind)
            if not isinstance(table, dict):
                continue
            for key, row in table.items():
                n = row.get("n") if isinstance(row, dict) else None
                if not isinstance(key, str) or type(n) is not int or n < 1:
                    continue
                self.numbers[kind][key] = n
                name = row.get("name")
                if isinstance(name, str) and name:
                    self.names[kind][key] = name[:NAME_LENGTH_KEPT]
        raw_next = data.get("next")
        stored_next: dict[str, Any] = raw_next if isinstance(raw_next, dict) else {}
        for kind in KINDS:
            highest = max(self.numbers[kind].values(), default=0)
            given = stored_next.get(kind)
            given = given if type(given) is int and given > 0 else 1
            # Never below a number already given, so none is given twice.
            self.next[kind] = max(given, highest + 1)

    def number(self, kind: str, key: str, name: str | None = None) -> int:
        """The number standing for `key`, given now if it has none."""
        table = self.numbers[kind]
        n = table.get(key) or self._spare[kind].get(key)
        if n is None:
            n = self.next[kind]
            self.next[kind] = n + 1
            self.changed = True
            if len(table) < KEPT_PER_KIND:
                table[key] = n
            else:
                self._spare[kind][key] = n
        if name and key in table and self.names[kind].get(key) != name[:NAME_LENGTH_KEPT]:
            self.names[kind][key] = name[:NAME_LENGTH_KEPT]
            self.changed = True
        return n

    def word(self, kind: str, key: str, name: str | None = None) -> str:
        return WORDS[kind](self.number(kind, key, name))

    def payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {"next": dict(self.next)}
        for kind in KINDS:
            out[kind] = {
                key: ({"n": n, "name": self.names[kind][key]} if key in self.names[kind] else {"n": n})
                for key, n in self.numbers[kind].items()
            }
        return out


def _store(hass: HomeAssistant) -> Store[dict[str, Any]]:
    return Store(hass, STAND_INS_VERSION, STAND_INS_KEY, atomic_writes=True)


def book_lock(hass: HomeAssistant) -> asyncio.Lock:
    """One download at a time reads and writes the numbers."""
    lock = hass.data.get(_LOCK)
    if lock is None:
        lock = hass.data[_LOCK] = asyncio.Lock()
    return lock


async def async_load_book(hass: HomeAssistant) -> StandInBook:
    """The kept numbers. A file that cannot be read starts an empty book:
    Home Assistant sets an unreadable file aside on its own."""
    try:
        data = await _store(hass).async_load()
    except Exception:  # noqa: BLE001 - a download must still arrive
        data = None
    return StandInBook(data)


async def async_save_book(hass: HomeAssistant, book: StandInBook) -> None:
    if book.changed:
        await _store(hass).async_save(book.payload())
        book.changed = False


def _cell(text: Any) -> str:
    """A table cell: one line, its bars escaped."""
    return " ".join(str(text if text is not None else "").split()).replace("|", "\\|") or " "


def key_text(book: StandInBook, entities: dict[str, str], version: str, now: datetime) -> str:
    """The key, as Markdown: every number given and the name it stands for."""
    lines = [
        "# Diagnostics Key",
        "",
        f"Device Sentinel {version}, written {now.strftime('%Y-%m-%d %H:%M')}.",
        "",
        "Your diagnostics download names no device, area, label, Wi-Fi network or",
        "router tracker. Each is shown by the stand-in on the left of this key,",
        "and keeps its stand-in in each download. Keep this file on your",
        "system. Send it only by private email, never with a public issue.",
    ]
    titles = {
        "device": "Devices",
        "area": "Areas",
        "label": "Labels",
        "network": "Wi-Fi Networks",
        "tracker": "Router Trackers",
    }
    for kind, title in titles.items():
        rows = sorted(book.numbers[kind].items(), key=lambda item: item[1])
        if not rows:
            continue
        lines += ["", f"## {title}", "", "| Stand-in | Name |", "|---|---|"]
        for key, n in rows:
            if kind in ("network", "tracker"):
                name = key
            else:
                name = book.names[kind].get(key) or ("(no name kept)" if not key.startswith("name:") else key[5:])
            lines.append(f"| {WORDS[kind](n)} | {_cell(name)} |")
    if entities:
        lines += [
            "",
            "## Entities in the Latest Download",
            "",
            "| Stand-in | Entity |",
            "|---|---|",
        ]
        for real, shown in sorted(entities.items(), key=lambda item: item[1]):
            lines.append(f"| {_cell(shown)} | {_cell(real)} |")
    return "\n".join(lines) + "\n"
