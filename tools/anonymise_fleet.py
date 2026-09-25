# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tools/anonymise_fleet.py, Version: 0.23.3 (2026-09-25)

"""Build the committed fleet set from real houses' files.

The test suite reads real storage from the houses that test Device
Sentinel, because no constructed house has ever had their shape. Those
files name a person's devices, which is a floor plan, so what goes into
the repository is an anonymized copy, and the real files stay with the
owner in a private archive.

    python tools/anonymise_fleet.py RAW_DIR OUT_DIR --key fleet_aliases.json

RAW_DIR holds one folder per house (reference, second, fourth, and any
tester after them), each with the house's storage file, its clocks file
and its diagnostics download (`config_entry-device_sentinel-*.json`).
OUT_DIR receives the same folders: the storage and clocks under their
own names, and in place of the diagnostics a small
`config_entry-device_sentinel-fleet.json` holding only what the suite
reads from it, each device's name and the entry's options.

What is replaced, with the same stand-in everywhere it occurs:

- every registry id, 32 hex characters, and every config entry id, 26
  characters, wherever it stands: a key, a field, or inside a sentence;
- every device name, by name rather than by device, so two devices that
  share a name still share one, which the suite tests;
- the router's client trackers, which name people's phones and carry
  hardware addresses;
- the Wi-Fi network names, and the notification targets, which are
  often named after an email address.

A missing name stays missing, since the suite tests nameless devices.
Timestamps, domains, counts and every learned number stay as they are:
they carry the shape the tests need and say nothing about a person.

The alias key, `--key`, is the owner's and is never committed. It maps
each real value to its stand-in, house by house, so a device keeps its
stand-in from one refresh to the next and a refresh's diff shows what
changed rather than churning every line. A value the key has not seen
is given the next stand-in and added.

The output is proven rather than trusted. After writing, every string
and key in every file written is checked against the real values the
run replaced, and against the names in the raw diagnostics, and the run
fails naming the first leak it finds.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

HEX_ID = re.compile(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])")
ENTRY_ID = re.compile(r"(?<![0-9A-Z])[0-9A-HJKMNP-TV-Z]{26}(?![0-9A-Z])")
TRACKER = re.compile(r"device_tracker\.[a-z0-9_]+")
ANY_ID = re.compile(
    rf"(?P<hex>{HEX_ID.pattern})|(?P<entry>{ENTRY_ID.pattern})|(?P<tracker>{TRACKER.pattern})"
)

# The fields that carry a device's name, and the ones that carry a name
# inside a sentence.
NAME_FIELDS = {"name", "sort_name"}
# A problem-list item for an upstream, keyed "upstream:<domain>", names
# an integration, not a person's device, and its name is the domain
# the rest of the file carries as a scope. Anonymizing it as a device
# name made the leak check find the domain everywhere: the second
# fleet's "switchbot" item of 24 September (0.23.3).
UPSTREAM_PREFIX = "upstream:"


def _is_upstream(value: dict[str, Any]) -> bool:
    device_id = value.get("device_id")
    return isinstance(device_id, str) and device_id.startswith(UPSTREAM_PREFIX)
SENTENCE_FIELDS = {"summary", "detail"}

STORAGE_NAMES = (
    ("device_sentinel.storage", "device_sentinel.clocks"),
    ("device_sentinel_storage.json", "device_sentinel_clocks.json"),
)
DIAGNOSTICS_OUT = "config_entry-device_sentinel-fleet.json"
KEEP_TARGETS = {"persistent_notification"}
KINDS = ("ids", "entries", "names", "trackers", "networks", "targets")


class House:
    """One house's aliases: the key's record, extended as needed."""

    def __init__(self, index: int, key: dict[str, dict[str, str]]) -> None:
        self.index = index
        self.key = key
        for kind in KINDS:
            key.setdefault(kind, {})
        self.used: dict[str, set[str]] = {kind: set() for kind in KINDS}

    def _alias(self, kind: str, real: str, make) -> str:
        table = self.key[kind]
        if real not in table:
            table[real] = make(len(table) + 1)
        self.used[kind].add(real)
        return table[real]

    def device_id(self, real: str) -> str:
        return self._alias(
            "ids", real, lambda n: f"{self.index:02x}fa{n:028x}"
        )

    def entry_id(self, real: str) -> str:
        return self._alias(
            "entries", real, lambda n: f"{self.index:02d}{n:024d}"
        )

    def name(self, real: str | None) -> str | None:
        if not real:
            return real
        return self._alias("names", real, lambda n: f"Device {n:03d}")

    def tracker(self, real: str) -> str:
        return self._alias(
            "trackers", real, lambda n: f"device_tracker.client_{n:03d}"
        )

    def network(self, real: str) -> str:
        return self._alias("networks", real, lambda n: f"network_{n}")

    def target(self, real: str) -> str:
        if real in KEEP_TARGETS:
            return real
        return self._alias("targets", real, lambda n: f"notify.target_{n}")

    def ids_in(self, text: str) -> str:
        """Replace every id and tracker standing inside a string.

        One pass over the original text, so a stand-in just written is
        never read again as though it were a real id.
        """

        def swap(match: re.Match[str]) -> str:
            if match.group("hex"):
                return self.device_id(match.group("hex"))
            if match.group("entry"):
                return self.entry_id(match.group("entry"))
            return self.tracker(match.group("tracker"))

        return ANY_ID.sub(swap, text)

    def names_in(self, text: str, names: list[str]) -> str:
        """Replace known device names inside a sentence, longest first,
        so a name that contains another is taken whole."""
        for real in names:
            if real and real in text:
                text = text.replace(real, self.name(real) or "")
        return text


def _walk(value: Any, house: House, names: list[str], field: str = "") -> Any:
    """Return an anonymized copy, keys kept in their order."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        upstream = _is_upstream(value)
        for key, item in value.items():
            new_key = house.ids_in(key) if isinstance(key, str) else key
            if upstream and key in NAME_FIELDS:
                out[new_key] = item
                continue
            out[new_key] = _walk(item, house, names, str(key))
        return out
    if isinstance(value, list):
        return [_walk(item, house, names, field) for item in value]
    if isinstance(value, str):
        if field in NAME_FIELDS:
            return house.name(value)
        if field in SENTENCE_FIELDS:
            value = house.names_in(value, names)
        return house.ids_in(value)
    return value


def _options(options: dict[str, Any], house: House, names: list[str]) -> Any:
    """The entry's options, with networks and targets replaced too."""
    out = _walk(options, house, names)
    if isinstance(out.get("wifi_networks"), list):
        out["wifi_networks"] = [house.network(v) for v in out["wifi_networks"]]
    targets = out.get("brief_document_targets")
    if isinstance(targets, list):
        out["brief_document_targets"] = [house.target(v) for v in targets]
    return out


def _collect_names(value: Any, found: set[str], field: str = "") -> None:
    """Gather every value standing in a name field."""
    if isinstance(value, dict):
        upstream = _is_upstream(value)
        for key, item in value.items():
            if upstream and key in NAME_FIELDS:
                continue
            _collect_names(item, found, str(key))
    elif isinstance(value, list):
        for item in value:
            _collect_names(item, found, field)
    elif isinstance(value, str) and field in NAME_FIELDS and value:
        found.add(value)


def _strings(value: Any):
    """Every string in a structure, keys included."""
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, str):
        yield value


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _leaks(written: list[Path], house: House, raw_names: set[str]) -> list[str]:
    """Every real value the run replaced, and every raw name, that
    still stands anywhere in what was written."""
    forbidden: dict[str, str] = {}
    for kind in ("ids", "entries", "trackers", "networks", "targets"):
        for real in house.used[kind]:
            forbidden[real] = kind
    for real in house.used["names"] | raw_names:
        # A name too short or too common to search for as text is
        # still checked exactly, field by field, below.
        if len(real) >= 5:
            forbidden[real] = "name"
            slug = _slug(real)
            if len(slug) >= 8:
                forbidden[slug] = "name slug"
    exact = house.used["names"] | raw_names
    found: list[str] = []
    for path in written:
        data = json.loads(path.read_text(encoding="utf-8"))
        for text in _strings(data):
            if text in exact:
                found.append(f"{path.name}: the name {text!r}")
                continue
            for real, kind in forbidden.items():
                if real in text:
                    found.append(f"{path.name}: {kind} {real!r} in {text[:80]!r}")
                    break
            if len(found) > 20:
                return found
    return found


def anonymise_house(raw: Path, out: Path, house: House) -> list[Path]:
    """Write one house's anonymized files, and return their paths."""
    storage_name = clocks_name = None
    for storage, clocks in STORAGE_NAMES:
        if (raw / storage).exists():
            storage_name, clocks_name = storage, clocks
    if storage_name is None:
        raise SystemExit(f"{raw}: no storage file")
    diagnostics = sorted(raw.glob("config_entry-device_sentinel-*.json"))
    if not diagnostics:
        raise SystemExit(f"{raw}: no diagnostics download")
    dump = json.loads(diagnostics[0].read_text(encoding="utf-8"))["data"]
    raw_names = {
        record.get("name")
        for record in (dump.get("devices") or {}).values()
        if isinstance(record, dict) and record.get("name")
    }
    # Names the registry no longer holds live on in the records, for a
    # device since removed, and a sentence can carry one of those too.
    stored = set(raw_names)
    for storage in (storage_name, clocks_name):
        if (raw / storage).exists():
            _collect_names(json.loads((raw / storage).read_text(encoding="utf-8")), stored)
    names = sorted(stored, key=len, reverse=True)

    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in (storage_name, clocks_name):
        source = raw / name
        if not source.exists():
            continue
        data = json.loads(source.read_text(encoding="utf-8"))
        target = out / name
        target.write_text(
            json.dumps(_walk(data, house, names), indent=1, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        written.append(target)

    devices = {
        house.device_id(device_id): {"name": house.name((record or {}).get("name"))}
        for device_id, record in (dump.get("devices") or {}).items()
    }
    small = {
        "data": {
            "devices": devices,
            "entry_options": _options(dump.get("entry_options") or {}, house, names),
        }
    }
    target = out / DIAGNOSTICS_OUT
    target.write_text(
        json.dumps(small, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    written.append(target)

    leaks = _leaks(written, house, stored)
    if leaks:
        raise SystemExit(f"{raw.name}: real values survived:\n  " + "\n  ".join(leaks))
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("raw", type=Path, help="one folder per house, real files")
    parser.add_argument("out", type=Path, help="where the committed set is written")
    parser.add_argument("--key", type=Path, required=True, help="the alias key, kept private")
    args = parser.parse_args(argv)

    key = (
        json.loads(args.key.read_text(encoding="utf-8"))
        if args.key.exists()
        else {}
    )
    houses = sorted(p for p in args.raw.iterdir() if p.is_dir())
    if not houses:
        raise SystemExit(f"{args.raw}: no house folders")
    order = key.setdefault("_order", [])
    for folder in houses:
        if folder.name not in order:
            order.append(folder.name)
    for folder in houses:
        house = House(order.index(folder.name) + 1, key.setdefault(folder.name, {}))
        written = anonymise_house(folder, args.out / folder.name, house)
        sizes = ", ".join(f"{p.name} {p.stat().st_size // 1024} KB" for p in written)
        print(f"{folder.name}: {sizes}; no real value survives")
    args.key.write_text(json.dumps(key, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"alias key written to {args.key}; keep it, never commit it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
