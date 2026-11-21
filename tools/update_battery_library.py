# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tools/update_battery_library.py, Version: 0.30.0 (2026-11-21)

"""Refresh the Battery Notes library Device Sentinel ships (rule REL-15).

Run before each Latest release, from the repository's top folder:

    python tools/update_battery_library.py           # report, then write
    python tools/update_battery_library.py --check   # report only

It downloads Battery Notes' library.json at one pinned commit, refuses
it unless its SHA-256 is the pinned one, checks that every entry has
the fields Device Sentinel reads, says how many devices were added,
removed and changed since the copy in the repository, and writes the
new copy unchanged. Update the date and count line in
data/BATTERY_LIBRARY_LICENSE.md by hand; the tool prints the line.

To move the pin, look at a newer commit first:

    python tools/update_battery_library.py --check --commit <sha>

It prints that commit's SHA-256. Put both in COMMIT and SHA256 below,
in a change of their own, then run the tool to write.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

# The commit of Battery Notes' repository the library is taken from, and
# the SHA-256 of its library.json, so a refresh brings exactly what was
# reviewed, never whatever its main branch holds that day.
COMMIT = "f8f0cbed81c32f7777472fc5a4a491695df758d8"
SHA256 = "1bfb6c5ab6692a7c82619916ff0796e9e901ccda1abb3c385cba4d05ecb227eb"
SOURCE = "https://raw.githubusercontent.com/andrew-codechimp/HA-Battery-Notes/{commit}/library/library.json"
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
    parser.add_argument("--commit", help="look at another commit (with --check only)")
    args = parser.parse_args()
    if args.commit and not args.check:
        print("--commit looks only: move the pin by editing COMMIT and SHA256.")
        return 2
    commit = args.commit or COMMIT
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        print("A commit is its full 40-character hash.")
        return 2
    if not TARGET.exists():
        print(f"Run this from the repository's top folder; {TARGET} was not found.")
        return 2
    try:
        with urllib.request.urlopen(SOURCE.format(commit=commit), timeout=30) as response:  # noqa: S310  # nosec B310 - a fixed https address
            raw = response.read()
    except (urllib.error.URLError, TimeoutError) as err:
        print(f"Commit {commit} could not be read: {err}. Nothing written.")
        return 1
    digest = hashlib.sha256(raw).hexdigest()
    if args.commit:
        print(f"Commit {commit}: SHA-256 {digest}.")
    elif digest != SHA256:
        print(f"The download's SHA-256 is {digest}, not the pinned {SHA256}; nothing written.")
        return 1
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
