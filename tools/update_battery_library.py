# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tools/update_battery_library.py, Version: 0.24.7 (2026-10-05)

"""Refresh the Battery Notes library Device Sentinel ships (0.24.7).

Run before each Latest release, from the repository's top folder:

    python tools/update_battery_library.py           # report, then write
    python tools/update_battery_library.py --check   # report only

It downloads Battery Notes' current library.json, checks that every
entry has the fields Device Sentinel reads, says how many devices were
added, removed and changed since the copy in the repository, and
writes the new copy unchanged. Update the date and count line in
data/BATTERY_LIBRARY_LICENSE.md by hand; the tool prints the line.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

SOURCE = "https://raw.githubusercontent.com/andrew-codechimp/HA-Battery-Notes/main/library/library.json"
TARGET = Path("custom_components/device_sentinel/data/battery_library.json")
KEY = ("manufacturer", "model", "model_id", "hw_version")


def _check(data: object) -> list[dict]:
    if not isinstance(data, dict) or not isinstance(data.get("devices"), list):
        raise SystemExit("The download has no list of devices; nothing written.")
    devices = data["devices"]
    bad = [
        i for i, d in enumerate(devices)
        if not isinstance(d, dict)
        or not all(isinstance(d.get(f), str) and d.get(f) for f in ("manufacturer", "model", "battery_type"))
    ]
    if bad:
        raise SystemExit(f"{len(bad)} entries lack a manufacturer, model or battery type; nothing written.")
    return devices


def _index(devices: list[dict]) -> dict[tuple, dict]:
    return {tuple(str(d.get(k) or "").casefold() for k in KEY): d for d in devices}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="report only, write nothing")
    args = parser.parse_args()
    if not TARGET.exists():
        print(f"Run this from the repository's top folder; {TARGET} was not found.")
        return 2
    with urllib.request.urlopen(SOURCE, timeout=30) as response:  # noqa: S310  # nosec B310 - a fixed https address
        raw = response.read()
    new = _check(json.loads(raw))
    old = _check(json.loads(TARGET.read_bytes()))
    before, after = _index(old), _index(new)
    added = len(after.keys() - before.keys())
    removed = len(before.keys() - after.keys())
    changed = sum(1 for k in after.keys() & before.keys() if after[k] != before[k])
    print(f"Battery Notes library: {len(old)} devices before, {len(new)} now; "
          f"{added} added, {removed} removed, {changed} changed.")
    if args.check:
        return 0
    TARGET.write_bytes(raw)
    print(f"Written to {TARGET}. Licence file line to use:")
    print(f"Copied for Device Sentinel <version> on {date.today():%-d %B %Y}: {len(new):,} devices.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
