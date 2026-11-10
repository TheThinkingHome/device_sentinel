# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: network_extras.py, Version: 0.28.8 (2026-11-09)

"""More on each network's page (rules DASH-17, DASH-18).

A network's devices and what they are made of, how long it has run,
the devices that keep failing on it, Wi-Fi address changes, firmware,
and a Z-Wave controller's radio noise.

A network that goes down at the same time of day again and again is a
pattern, told in one sentence that the page's Recommendations section
and its outage list share (rule DASH-18). A person can mark a pattern
as expected, such as a nightly backup: its outages are still listed,
marked expected, and no longer counted or recommended on. An outage at
another time, one that runs well past its usual length, or one that
does not end, is not expected. A pattern that stops happening for 14
days is forgotten, so a schedule removed since never hides a future
outage at the same time.

Everything else is read from what Device Sentinel already keeps or
from Home Assistant's registries and states. Nothing here changes
another integration's settings (rule STACK-13).
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    ADDR_AP,
    ADDR_DEVICE_ID,
    ADDR_IP,
    ADDR_WHEN,
    BROKER_SCOPE,
    DATA_ADDRESS_CHANGES,
    DATA_DEVICES,
    DATA_EXPECTED_OUTAGES,
    DATA_SHORT_DROP_DAYS,
    DATA_SHORT_DROPS,
    DEV_FIRMWARE_HISTORY,
    DROP_DAY,
    DROP_DAY_SHORT,
    DROP_DEVICE_ID,
    DROP_WENT,
    EXP_LENGTH,
    EXP_MINUTE,
    EXP_NETWORK,
    EXP_SET_AT,
    EXPECTED_FORGET_DAYS,
    EXPECTED_LENGTH_TIMES,
    EXPECTED_MINUTES,
    LOGGER,
    NOISE_ABOVE_DB,
    NOISE_MIN_DAYS,
    NOISE_RECENT_DAYS,
    OFFENDER_ROWS,
    PATTERN_LONGER_DAYS,
    PATTERN_MAX_OUTAGES,
    PATTERN_MIN_TIMES,
    PATTERN_SHARE,
    STACK_MATTER,
    STACK_Z2M,
    STACK_ZHA,
    STACK_ZWAVE,
    SYS_BRIDGE_UP,
    SYS_BROKER_UP,
    SYS_DETAIL,
    SYS_DURATION,
    SYS_INTEGRATION_UP,
    SYS_KIND,
    SYS_SCOPE,
    SYS_WHEN,
    SYS_WIFI_UP,
    WIFI_KEY,
)
from .device_fields import device_field
from .outage_detail import REMOVED, UNWATCHED, parse_detail
from .short_drops import drop_day, is_short

# The day a network page's lists look back, as on the rest of the page.
EXTRAS_WINDOW_DAYS = 30
# Short drop-outs and repeat offenders, as on the Daily Brief.
EXTRAS_WEEK_DAYS = 7
# The makers listed under a network's makeup.
MAKERS_SHOWN = 5
# A Z-Wave controller's channel noise sensors, current and average.
_NOISE_CHANNEL = re.compile(r"statistics_background_rssi[._-]channel_(\d+)[._-](current|average)$")
# What a pattern's question names as the likely cause, by network.
_CAUSE = {
    WIFI_KEY: "A scheduled restart of the router or its access points often does this.",
    BROKER_SCOPE: "A nightly backup or scheduled restart on the device that runs the broker often does this.",
}


def _number(value: Any) -> float | None:
    """A real number, or None for anything else, a boolean included."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _apart(a: int, b: int) -> int:
    """Minutes between two times of day, around midnight."""
    gap = abs(a - b) % 1440
    return min(gap, 1440 - gap)


def _clock(minute: int) -> str:
    """A time of day as a person reads it: 3:40 AM."""
    hour, mins = divmod(int(minute) % 1440, 60)
    return f"{(hour % 12) or 12}:{mins:02d} {'AM' if hour < 12 else 'PM'}"


def _date(moment: Any) -> str:
    return f"{moment.strftime('%b')} {moment.day}"


def _span(seconds: float | None) -> str | None:
    """A length as a person reads it: 4 minutes, 3.4 hours."""
    if seconds is None:
        return None
    if seconds < 90:
        whole = max(1, round(seconds))
        return f"{whole} second{'' if whole == 1 else 's'}"
    if seconds < 5400:
        return f"{round(seconds / 60)} minutes"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} hours".replace(".0 ", " ")
    return f"{seconds / 86400:.1f} days".replace(".0 ", " ")


def _iso(moment: float | None) -> str | None:
    return dt_util.utc_from_timestamp(moment).isoformat() if moment is not None else None


def _stamp(iso: Any) -> float | None:
    if not isinstance(iso, str):
        return None
    moment = dt_util.parse_datetime(iso)
    return moment.timestamp() if moment is not None else None


class NetworkExtrasMixin:
    """The parts of a network's page beyond its counts and outages."""

    # ------------------------------------------------------ expected

    def _expected_rows(self) -> list[dict[str, Any]]:
        """The stored expected outages that can be read, as kept."""
        table = self.data.get(DATA_EXPECTED_OUTAGES)  # type: ignore[attr-defined]
        if not isinstance(table, list):
            return []
        rows = []
        for row in table:
            if not isinstance(row, dict) or not isinstance(row.get(EXP_NETWORK), str):
                continue
            minute = row.get(EXP_MINUTE)
            if isinstance(minute, bool) or not isinstance(minute, int) or not 0 <= minute < 1440:
                continue
            if _number(row.get(EXP_SET_AT)) is None:
                continue
            rows.append(row)
        return rows

    def _outage_fits(self, row: dict[str, Any], outage: dict[str, Any], now: float) -> bool:
        """Whether one outage is the expected one: around its time, no
        longer than twice its usual length, and ended or not yet past
        that length (rule DASH-18)."""
        went = _stamp(outage.get("went_down"))
        if went is None:
            return False
        minute = self._local_minute(went)
        if _apart(minute, row[EXP_MINUTE]) > EXPECTED_MINUTES:
            return False
        # Every outage is held to the usual length, those before it was
        # marked too, and an expected time with no usual length expects
        # nothing: an outage that should be told is never hidden.
        usual = _number(row.get(EXP_LENGTH))
        if usual is None or usual <= 0:
            return False
        allowed = max(usual * EXPECTED_LENGTH_TIMES, usual + 60.0)
        if outage.get("open"):
            return now - went <= allowed
        length = _number(outage.get("duration"))
        return length is not None and length <= allowed

    def _time_fits(self, row: dict[str, Any], outage: dict[str, Any]) -> bool:
        """Whether an outage began within 15 minutes of an expected time."""
        went = _stamp(outage.get("went_down"))
        usual = _number(row.get(EXP_LENGTH))
        return (
            usual is not None and usual > 0 and went is not None
            and _apart(self._local_minute(went), row[EXP_MINUTE]) <= EXPECTED_MINUTES
        )

    @staticmethod
    def _local_minute(moment: float) -> int:
        local = dt_util.as_local(dt_util.utc_from_timestamp(moment))
        return local.hour * 60 + local.minute

    def expected_for(self, key: str) -> list[dict[str, Any]]:
        """This network's expected outages, those not yet forgotten."""
        return [row for row in self._expected_rows() if row[EXP_NETWORK] == key]

    def outage_is_expected(self, key: str, outage: dict[str, Any], now: float | None = None) -> bool:
        """Whether an outage of this network fits one it expects."""
        now = dt_util.utcnow().timestamp() if now is None else now
        # The broker's outages on Zigbee2MQTT's page are judged by the
        # broker's own expected times, as the Daily Brief judges them.
        key = BROKER_SCOPE if outage.get("source") == BROKER_SCOPE else key
        for row in self.expected_for(key):
            if self._outage_fits(row, outage, now):
                return True
        return False

    def forget_expected(self, now: float | None = None) -> int:
        """Forget an expected outage that has not happened for 14 days
        (rule DASH-18). Returns how many were forgotten."""
        now = dt_util.utcnow().timestamp() if now is None else now
        table = self.data.get(DATA_EXPECTED_OUTAGES)  # type: ignore[attr-defined]
        if not isinstance(table, list) or not table:
            return 0
        kept = []
        for row in self._expected_rows():
            last = float(row[EXP_SET_AT])
            for outage in self.network_outages(row[EXP_NETWORK], EXTRAS_WINDOW_DAYS):  # type: ignore[attr-defined]
                if outage.get("source") == BROKER_SCOPE:
                    continue
                went = _stamp(outage.get("went_down"))
                if went is not None and went > last and _apart(self._local_minute(went), row[EXP_MINUTE]) <= EXPECTED_MINUTES:
                    last = went
            if now - last <= EXPECTED_FORGET_DAYS * 86400.0:
                kept.append(row)
        gone = len(table) - len(kept)
        if gone:
            self.data[DATA_EXPECTED_OUTAGES] = kept  # type: ignore[attr-defined]
            self._mark_cold_dirty()  # type: ignore[attr-defined]
        return gone

    def set_outage_expected(self, key: str, minute: int, on: bool) -> None:
        """Mark a network's outages around this time as expected, or stop
        expecting them (rule DASH-18). The usual length is the pattern's
        own, read again here so the panel cannot set it."""
        # Taking one back works even for a network the house no longer
        # has, so its row never sticks on the Integrations tab.
        if on and key not in self.network_keys():  # type: ignore[attr-defined]
            raise ValueError("This house has no such network")
        if isinstance(minute, bool) or not isinstance(minute, int) or not 0 <= minute < 1440:
            raise ValueError("That is not a time of day")
        held = [row for row in self._expected_rows()
                if row[EXP_NETWORK] == key and _apart(row[EXP_MINUTE], minute) <= EXPECTED_MINUTES]
        table = [row for row in self._expected_rows() if row not in held]
        if on:
            pattern = next(
                (p for p in self.outage_patterns(key) if _apart(p["minute"], minute) <= EXPECTED_MINUTES),
                None,
            )
            if pattern is None:
                raise ValueError("No outage pattern at that time")
            if not pattern["usual"] or pattern["usual"] <= 0:
                raise ValueError("This pattern's outages have no recorded length")
            table.append({
                EXP_NETWORK: key,
                EXP_MINUTE: pattern["minute"],
                EXP_LENGTH: pattern["usual"],
                # Marked again, it keeps when it was first marked, so a
                # long outage since is never counted as expected.
                EXP_SET_AT: min([float(r[EXP_SET_AT]) for r in held] + [dt_util.utcnow().timestamp()]),
            })
        self.data[DATA_EXPECTED_OUTAGES] = table  # type: ignore[attr-defined]
        self._mark_cold_dirty()  # type: ignore[attr-defined]
        self._mark_changed()  # type: ignore[attr-defined]

    def expected_list(self) -> list[dict[str, Any]]:
        """Every expected outage, for the Integrations tab's list of what
        is muted, each with its network and time (rule DASH-18)."""
        rows = []
        for row in self._expected_rows():
            rows.append({
                "network": row[EXP_NETWORK],
                "name": self.network_name(row[EXP_NETWORK]),  # type: ignore[attr-defined]
                "minute": row[EXP_MINUTE],
                "time": _clock(row[EXP_MINUTE]),
                "usual": _span(_number(row.get(EXP_LENGTH))),
                "since": _iso(float(row[EXP_SET_AT])),
            })
        rows.sort(key=lambda r: (str(r["name"]).lower(), r["minute"]))
        return rows

    def system_row_expected(self, row: Any) -> bool:
        """Whether a return in the system log ended an outage the person
        expects, for the Daily Brief's words (rule DASH-18)."""
        if not isinstance(row, dict) or not self._expected_rows():
            return False
        kind, scope = row.get(SYS_KIND), row.get(SYS_SCOPE)
        if kind == SYS_INTEGRATION_UP and parse_detail(row.get(SYS_DETAIL))[2] in (REMOVED, UNWATCHED):
            # Removed or no longer watched while down: not an outage
            # that ended.
            return False
        when, length = _number(row.get(SYS_WHEN)), _number(row.get(SYS_DURATION))
        if when is None or length is None:
            return False
        keys: list[str] = []
        if kind == SYS_BRIDGE_UP and isinstance(scope, str):
            keys = [scope]
        elif kind == SYS_INTEGRATION_UP and scope in (STACK_ZHA, STACK_ZWAVE, STACK_MATTER, BROKER_SCOPE):
            keys = [str(scope)]
        elif kind == SYS_BROKER_UP:
            # The broker's own expected times only: Zigbee2MQTT's never
            # make a broker outage expected.
            keys = [BROKER_SCOPE]
        elif kind == SYS_WIFI_UP:
            keys = [WIFI_KEY]
        outage = {"went_down": _iso(when - length), "duration": length, "open": False}
        return any(self.outage_is_expected(key, outage) for key in keys)

    # ------------------------------------------------------ patterns

    def outage_patterns(self, key: str, outages: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """Outages that keep coming at the same time of day, newest first.

        A pattern is outages on three or more occasions, each within 15
        minutes of one time of day, that make up at least a third of the
        network's outages in the window: a network that drops at random
        has no time of its own. An occasion is a day around that time,
        so 11:58 PM and 12:03 AM on one night are one. Its sentence is
        the one the page's recommendation and its outage list both show
        (rule DASH-18).
        """
        outages = self.network_outages(key, EXTRAS_WINDOW_DAYS) if outages is None else outages  # type: ignore[attr-defined]
        items = []
        for index, outage in enumerate(outages):
            went = _stamp(outage.get("went_down"))
            # A pattern is the network's own: the broker's outages make
            # the broker's patterns, on its own page.
            if went is None or outage.get("source") == BROKER_SCOPE:
                continue
            local = dt_util.as_local(dt_util.utc_from_timestamp(went))
            items.append({"i": index, "went": went, "minute": local.hour * 60 + local.minute,
                          "local": local, "outage": outage})
        # A network down hundreds of times a month is failing, not
        # keeping a schedule, and the search would cost too much.
        if len(items) > PATTERN_MAX_OUTAGES:
            return []
        needed = max(PATTERN_MIN_TIMES, -(-len(items) // PATTERN_SHARE))
        left = list(items)
        found = []
        while left:
            best: tuple[tuple[int, float], int, list[dict[str, Any]], list[Any]] | None = None
            for centre in left:
                near = [x for x in left if _apart(x["minute"], centre["minute"]) <= EXPECTED_MINUTES]
                minute = self._middle_minute(near)
                near = [x for x in near if _apart(x["minute"], minute) <= EXPECTED_MINUTES]
                if not near:
                    continue
                occasions = sorted({self._occasion(x["local"], minute) for x in near})
                score = (len(occasions), max(x["went"] for x in near))
                if best is None or score > best[0]:
                    best = (score, minute, near, occasions)
            if best is None or len(best[3]) < PATTERN_MIN_TIMES:
                break
            if len(best[2]) >= needed:
                found.append(self._pattern(key, best[2], best[1], best[3]))
            # Too small a share is no pattern, but another time may be.
            taken = {x["i"] for x in best[2]}
            left = [x for x in left if x["i"] not in taken]
        found.sort(key=lambda p: p["last_went"], reverse=True)
        return found

    @staticmethod
    def _middle_minute(members: list[dict[str, Any]]) -> int:
        """The middle time of day of some outages, read around midnight."""
        anchor = members[0]["minute"]
        offsets = sorted(((x["minute"] - anchor + 720) % 1440) - 720 for x in members)
        return int(anchor + median(offsets)) % 1440

    @staticmethod
    def _occasion(local: datetime, minute: int) -> Any:
        """The day an outage belongs to around a time of day: 12:03 AM
        belongs with the night before when the time is 11:58 PM."""
        offset = ((local.hour * 60 + local.minute - minute + 720) % 1440) - 720
        return (local - timedelta(minutes=offset)).date()

    def _pattern(self, key: str, members: list[dict[str, Any]], minute: int, days: list[Any]) -> dict[str, Any]:
        """One pattern's sentence, its time and usual length, and the
        outages it covers."""
        members = sorted(members, key=lambda x: x["went"])
        lengths = [d for d in (_number(x["outage"].get("duration")) for x in members) if d is not None]
        usual = float(median(lengths)) if lengths else None
        night = minute >= 20 * 60 or minute < 6 * 60
        when = "nights" if night else "days"
        in_row = all((b - a).days == 1 for a, b in zip(days, days[1:]))
        first, last = days[0], days[-1]
        if in_row:
            sentence = (f"Down {len(days)} {when} in a row at {_clock(minute)}, "
                        f"{_date(first)} to {_date(last)}.")
        else:
            sentence = (f"Down {len(days)} times at about {_clock(minute)} in the last "
                        f"{EXTRAS_WINDOW_DAYS} days, most recently {_date(last)}.")
        name = self.network_name(key)  # type: ignore[attr-defined]
        cause = _CAUSE.get(key, f"A nightly backup or scheduled restart on the device that runs {name} often does this.")
        latest = members[-1]
        start = latest["went"] - 600.0
        length = _number(latest["outage"].get("duration"))
        end = latest["went"] + (length if length is not None else 0.0) + 600.0
        return {
            "minute": minute,
            "time": _clock(minute),
            "times": len(days),
            "usual": usual,
            "usual_words": _span(usual),
            "sentence": sentence,
            "question": f"Is this expected? {cause}",
            "outages": [x["i"] for x in members],
            "last_went": latest["outage"].get("went_down"),
            "logbook": self._logbook(start, end),
        }

    @staticmethod
    def _logbook(start: float, end: float) -> dict[str, Any]:
        """The logbook's time range, and its words in the house's own
        time, as the pattern's sentence is worded."""
        first = dt_util.as_local(dt_util.utc_from_timestamp(start))
        last = dt_util.as_local(dt_util.utc_from_timestamp(end))
        until = _clock(last.hour * 60 + last.minute)
        if last.date() != first.date():
            until = f"{_date(last)}, {until}"
        return {"start": _iso(start), "end": _iso(end), "day": _date(first),
                "words": f"{_date(first)}, {_clock(first.hour * 60 + first.minute)} to {until}"}

    def network_outage_view(self, key: str, forget: bool = True) -> dict[str, Any]:
        """A network's outages with each marked expected or not, its
        patterns, and the recommendations they make (rule DASH-18)."""
        now = dt_util.utcnow().timestamp()
        if forget:
            self.forget_expected(now)
        outages = [dict(o) for o in self.network_outages(key, EXTRAS_WINDOW_DAYS)]  # type: ignore[attr-defined]
        for outage in outages:
            outage["expected"] = self.outage_is_expected(key, outage, now)
        patterns = self.outage_patterns(key, outages)
        cards = []
        for pattern in patterns:
            # Marked expected when each of its outages falls at an
            # expected time: one that ran long is told by its own card
            # below, never by asking again (rule DASH-18).
            covered = [outages[i] for i in pattern["outages"]]
            rows = self.expected_for(key)
            pattern["expected"] = bool(covered) and all(
                any(self._time_fits(row, o) for row in rows) for o in covered
            )
            if not pattern["expected"]:
                cards.append({"kind": "pattern", **{k: pattern[k] for k in (
                    "minute", "time", "sentence", "question", "logbook", "usual_words")}})
        # An expected outage that ran well past its usual length, or has
        # not ended, is told on its own, for a week (rule DASH-18).
        told: set[int] = set()
        for row in self.expected_for(key):
            if not (_number(row.get(EXP_LENGTH)) or 0) > 0:
                continue
            for index, outage in enumerate(outages):
                went = _stamp(outage.get("went_down"))
                if (
                    index in told or went is None or outage.get("source") == BROKER_SCOPE or outage["expected"] or went < row[EXP_SET_AT]
                    or now - went > PATTERN_LONGER_DAYS * 86400.0
                    or _apart(self._local_minute(went), row[EXP_MINUTE]) > EXPECTED_MINUTES
                ):
                    continue
                told.add(index)
                length = _number(outage.get("duration"))
                local = dt_util.as_local(dt_util.utc_from_timestamp(went))
                usual = _span(_number(row.get(EXP_LENGTH)))
                if outage.get("open"):
                    ran = f"has not ended since {_clock(local.hour * 60 + local.minute)}"
                elif length is None:
                    ran = "ran for a length that was not recorded"
                else:
                    ran = f"ran {_span(length)}"
                cards.append({
                    "kind": "longer",
                    "minute": row[EXP_MINUTE],
                    "time": _clock(row[EXP_MINUTE]),
                    "sentence": (f"The outage you expect at {_clock(row[EXP_MINUTE])} {ran} on {_date(local)}"
                                 + (f", against its usual {usual}." if usual else ".")),
                    "question": None,
                    "logbook": self._logbook(went - 600.0, went + (length or 0.0) + 600.0),
                    "usual_words": usual,
                })
        return {"outages": outages, "patterns": patterns, "cards": cards}

    # ------------------------------------------------------ devices

    def _mesh_role(self, key: str, device: Any) -> str | None:
        """A Zigbee device's part in its mesh: Router or End device, as
        its stack says. None where the stack does not say."""
        try:
            if key == STACK_Z2M:
                from .stack_z2m import device_key

                reader = self.bridge_reader(STACK_Z2M)  # type: ignore[attr-defined]
                ieee = device_key(device)
                role = reader.zigbee_role(ieee) if reader is not None and ieee else None
            elif key == STACK_ZHA:
                from .stack_zha import _proxy

                role = getattr(_proxy(self.hass, device).device, "device_type", None)  # type: ignore[attr-defined]
            else:
                return None
        except Exception as err:  # noqa: BLE001 - another integration's internals
            LOGGER.debug("Mesh role of %s not read: %s", getattr(device, "id", None), err)
            return None
        if not isinstance(role, str):
            return None
        return {"router": "Router", "enddevice": "End device", "coordinator": "Coordinator"}.get(
            role.replace("_", "").replace(" ", "").lower()
        )

    def _network_power(self, device_id: str) -> str:
        """Battery, Mains or Not known, as Device Sentinel knows it."""
        known = self.power_of(device_id)  # type: ignore[attr-defined]
        if known:
            return "Battery" if known.get("kind") == "battery" else "Mains"
        if device_id in (getattr(self, "_battery_entity", None) or {}):
            return "Battery"
        return "Not known"

    def _network_devices(self, key: str, members: list[str]) -> list[dict[str, Any]]:
        """Each of the network's devices, with its maker, model, firmware,
        part in the mesh, power and problem, by name (rule DASH-17)."""
        registry = dr.async_get(self.hass)  # type: ignore[attr-defined]
        problems = self._problem_groups_by_device()  # type: ignore[attr-defined]
        rows = []
        for device_id in members:
            device = registry.async_get(device_id)
            try:
                role = self._mesh_role(key, device) if device is not None else None
                power = self._network_power(device_id)
            except Exception as err:  # noqa: BLE001 - one device never breaks a page
                LOGGER.debug("Network row for %s not read: %s", device_id, err)
                role, power = None, "Not known"
            groups = (problems.get(device_id) or {}).get("groups") or []
            rows.append({
                "device_id": device_id,
                "name": self._device_name(device_id),  # type: ignore[attr-defined]
                "maker": device_field(device, "manufacturer") if device is not None else None,
                "model": device_field(device, "model") if device is not None else None,
                "firmware": device_field(device, "sw_version") if device is not None else None,
                "role": role,
                "power": power,
                "problem": groups[0] if groups else None,
            })
        rows.sort(key=lambda r: str(r["name"]).lower())
        return rows

    @staticmethod
    def _network_makeup(devices: list[dict[str, Any]]) -> dict[str, Any]:
        """What the network is made of: its parts in the mesh, how its
        devices are powered and its most common makers."""
        roles = Counter(d["role"] for d in devices if d.get("role"))
        power = Counter(d["power"] for d in devices)
        makers = Counter(str(d["maker"]) for d in devices if isinstance(d.get("maker"), str) and d["maker"].strip())
        return {
            "roles": [{"name": name, "devices": n} for name, n in sorted(roles.items(), key=lambda p: (-p[1], p[0]))],
            "power": [{"name": name, "devices": n} for name, n in sorted(power.items(), key=lambda p: (-p[1], p[0]))],
            "makers": [{"name": name, "devices": n} for name, n in makers.most_common(MAKERS_SHOWN)],
            "other_makers": max(0, len(makers) - MAKERS_SHOWN),
        }

    def _network_up(self, key: str, status: dict[str, Any], outages: list[dict[str, Any]]) -> dict[str, Any]:
        """How long the network has run since its last outage ended, and
        how many times it went down in the window."""
        all_outages = outages
        ended = None
        down = isinstance(status, dict) and status.get("state") == "down"
        if down or any(outage.get("open") for outage in outages):
            # Down now: it has not run since anything.
            outages = []
        for outage in outages:
            went = _stamp(outage.get("went_down"))
            length = _number(outage.get("duration"))
            if outage.get("open") or went is None or length is None:
                continue
            back = went + length
            if ended is None or back > ended:
                ended = back
        since = status.get("since") if isinstance(status, dict) else None
        return {
            "back_since": _iso(ended),
            "since": since,
            "outages": len(all_outages),
            "expected": sum(1 for o in all_outages if o.get("expected")),
        }

    # ------------------------------------------------- repeat offenders

    def short_drops_by_device(self, members: list[str], days: int = EXTRAS_WEEK_DAYS) -> dict[str, int]:
        """Each device's short drop-outs in the last `days` days, counted
        as the page's Signal Health counts them."""
        wanted = set(members)
        now = dt_util.utcnow().timestamp()
        line = now - days * 86400.0
        first_day = (dt_util.now().date() - timedelta(days=days - 1)).isoformat()
        cap = self._short_drop_cap()  # type: ignore[attr-defined]
        counts: dict[str, int] = {}
        for row in self.data.get(DATA_SHORT_DROPS) or []:  # type: ignore[attr-defined]
            if not isinstance(row, dict) or row.get(DROP_DEVICE_ID) not in wanted:
                continue
            went = _number(row.get(DROP_WENT))
            if went is None or went < line:
                continue
            if is_short(row, cap):
                counts[row[DROP_DEVICE_ID]] = counts.get(row[DROP_DEVICE_ID], 0) + 1
        for row in self.data.get(DATA_SHORT_DROP_DAYS) or []:  # type: ignore[attr-defined]
            if not isinstance(row, dict) or row.get(DROP_DEVICE_ID) not in wanted:
                continue
            day = row.get(DROP_DAY)
            count = row.get(DROP_DAY_SHORT)
            if not isinstance(day, str) or day < first_day or day > drop_day(now):
                continue
            if isinstance(count, int) and not isinstance(count, bool) and count > 0:
                counts[row[DROP_DEVICE_ID]] = counts.get(row[DROP_DEVICE_ID], 0) + count
        return counts

    def _network_offenders(self, members: list[str]) -> dict[str, Any]:
        """The network's devices that keep failing: the Daily Brief's
        repeat offenders on it, and those with the most short drop-outs,
        over the last seven days."""
        wanted = set(members)
        repeat = []
        try:
            for row in self._repeat_offender_rows(dt_util.utcnow().timestamp()):  # type: ignore[attr-defined]
                if row.get("device_id") in wanted:
                    repeat.append({"device_id": row.get("device_id"), "name": row.get("name"),
                                   "what": row.get("what"), "times": row.get("n"), "typical": row.get("typical")})
        except Exception as err:  # noqa: BLE001 - the brief's rows never break a page
            LOGGER.debug("Repeat offenders for a network page not read: %s", err)
        muted: set[str] = getattr(self, "_muted_devices", set())
        drops = [
            {"device_id": device_id, "name": self._device_name(device_id), "drops": n}  # type: ignore[attr-defined]
            for device_id, n in self.short_drops_by_device(
                [d for d in members if d not in muted and not self._signal_muted(d)]  # type: ignore[attr-defined]
            ).items()
        ]
        drops.sort(key=lambda r: (-r["drops"], str(r["name"]).lower()))
        return {"repeat": repeat[:OFFENDER_ROWS], "drops": drops[:OFFENDER_ROWS]}

    # ---------------------------------------------------------- Wi-Fi

    def _network_wifi_changes(self, members: list[str]) -> list[dict[str, Any]]:
        """Devices whose address or access point changed in the window,
        most changes first. A device's first reading is not a change."""
        wanted = set(members)
        since = dt_util.utcnow().timestamp() - EXTRAS_WINDOW_DAYS * 86400.0
        by_device: dict[str, list[dict[str, Any]]] = {}
        for row in self.data.get(DATA_ADDRESS_CHANGES) or []:  # type: ignore[attr-defined]
            if not isinstance(row, dict) or row.get(ADDR_DEVICE_ID) not in wanted or _number(row.get(ADDR_WHEN)) is None:
                continue
            by_device.setdefault(row[ADDR_DEVICE_ID], []).append(row)
        rows = []
        for device_id, changes in by_device.items():
            changes.sort(key=lambda r: r[ADDR_WHEN])
            addresses = moves = 0
            last = None
            # Each against the last address and access point it had: a
            # tracker that dropped one while away is no change.
            held_ip = held_ap = None
            for index, row in enumerate(changes):
                ip, ap = row.get(ADDR_IP), row.get(ADDR_AP)
                counted = index > 0 and row[ADDR_WHEN] >= since
                if ip is not None:
                    if counted and held_ip is not None and ip != held_ip:
                        addresses += 1
                        last = row[ADDR_WHEN]
                    held_ip = ip
                if ap is not None:
                    if counted and held_ap is not None and ap != held_ap:
                        moves += 1
                        last = row[ADDR_WHEN]
                    held_ap = ap
            if addresses or moves:
                rows.append({"device_id": device_id, "name": self._device_name(device_id),  # type: ignore[attr-defined]
                             "addresses": addresses, "moves": moves, "last": _iso(last)})
        rows.sort(key=lambda r: (-(r["addresses"] + r["moves"]), str(r["name"]).lower()))
        return rows[:OFFENDER_ROWS]

    # -------------------------------------------------------- firmware

    def _update_entities(self, device_id: str) -> list[Any]:
        """The device's own firmware update entities (rule REC-05)."""
        return self._own_entities_of(device_id, "firmware")  # type: ignore[attr-defined]

    def _network_firmware(self, members: list[str]) -> dict[str, Any]:
        """Firmware on the network: updates Home Assistant offers, the
        versions that changed in the window, and models whose devices run
        different versions (rule DEV-15)."""
        registry = dr.async_get(self.hass)  # type: ignore[attr-defined]
        records = self.data.get(DATA_DEVICES) or {}  # type: ignore[attr-defined]
        since = dt_util.utcnow().timestamp() - EXTRAS_WINDOW_DAYS * 86400.0
        updates = []
        changed = []
        models: dict[tuple[str, str], dict[str, int]] = {}
        for device_id in members:
            name = self._device_name(device_id)  # type: ignore[attr-defined]
            for ent in self._update_entities(device_id):
                if ent.disabled_by is not None:
                    continue
                state = self.hass.states.get(ent.entity_id)  # type: ignore[attr-defined]
                if state is None or state.state != "on":
                    continue
                attributes = state.attributes or {}
                updates.append({
                    "device_id": device_id, "name": name, "entity_id": ent.entity_id,
                    "installed": attributes.get("installed_version") if isinstance(attributes.get("installed_version"), str) else None,
                    "latest": attributes.get("latest_version") if isinstance(attributes.get("latest_version"), str) else None,
                })
                break
            record = records.get(device_id)
            history = record.get(DEV_FIRMWARE_HISTORY) if isinstance(record, dict) else None
            if isinstance(history, list):
                pairs = [p for p in history if isinstance(p, (list, tuple)) and len(p) == 2 and _number(p[1]) is not None]
                for before, after in zip(pairs, pairs[1:]):
                    if after[1] >= since:
                        changed.append({"device_id": device_id, "name": name, "from": str(before[0]),
                                        "to": str(after[0]), "when": _iso(float(after[1]))})
            device = registry.async_get(device_id)
            if device is None:
                continue
            maker, model = device_field(device, "manufacturer"), device_field(device, "model")
            version = device_field(device, "sw_version")
            if isinstance(maker, str) and isinstance(model, str) and isinstance(version, str) and version.strip():
                versions = models.setdefault((maker, model), {})
                versions[version] = versions.get(version, 0) + 1
        mixed = [
            {"maker": maker, "model": model,
             "versions": [{"version": v, "devices": n} for v, n in sorted(versions.items(), key=lambda p: (-p[1], p[0]))]}
            for (maker, model), versions in sorted(models.items())
            if len(versions) > 1
        ]
        updates.sort(key=lambda r: str(r["name"]).lower())
        changed.sort(key=lambda r: r["when"] or "", reverse=True)
        return {"updates": updates, "changed": changed[:OFFENDER_ROWS], "mixed": mixed}

    # ----------------------------------------------------- radio noise

    def _noise_entities(self) -> dict[str, dict[str, str]]:
        """The Z-Wave controller's noise sensors, by channel: its current
        and average reading entities."""
        registry = er.async_get(self.hass)  # type: ignore[attr-defined]
        found: dict[str, dict[str, str]] = {}
        for ent in registry.entities.values():
            if ent.platform != STACK_ZWAVE or ent.domain != "sensor" or ent.disabled_by is not None:
                continue
            match = _NOISE_CHANNEL.search(str(ent.unique_id))
            if match:
                found.setdefault(match.group(1), {})[match.group(2)] = ent.entity_id
        return found

    def _reading(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)  # type: ignore[attr-defined]
        if state is None:
            return None
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None
        return value if -200.0 <= value <= 50.0 else None

    async def async_network_noise(self) -> dict[str, Any] | None:
        """A Z-Wave controller's radio noise per channel: now, Z-Wave JS's
        own average, and Device Sentinel's 30-day typical from Home
        Assistant's long-term statistics. A channel that has stayed well
        above its typical for three days makes a recommendation (rule DASH-18). None when the controller
        has no noise sensor with a current reading."""
        channels = self._noise_entities()
        if not channels:
            return None
        daily: dict[str, list[float]] = {}
        try:
            daily = await self._noise_daily([c["current"] for c in channels.values() if "current" in c])
        except Exception as err:  # noqa: BLE001 - the recorder is optional
            LOGGER.debug("Radio noise statistics not read: %s", err)
        rows = []
        cards = []
        for channel in sorted(channels, key=int):
            ids = channels[channel]
            # A channel with no current reading is one the stick does not
            # use, such as an 800 series stick's Long Range channel.
            if "current" not in ids:
                continue
            now_value = self._reading(ids.get("current"))
            average = self._reading(ids.get("average"))
            days = daily.get(ids.get("current", ""), [])
            typical = float(median(days[:-NOISE_RECENT_DAYS])) if len(days) >= NOISE_MIN_DAYS else None
            recent = days[-NOISE_RECENT_DAYS:] if len(days) >= NOISE_MIN_DAYS else []
            raised = typical is not None and len(recent) == NOISE_RECENT_DAYS and all(
                d >= typical + NOISE_ABOVE_DB for d in recent
            )
            rows.append({"channel": int(channel), "now": now_value, "average": average,
                         "typical": round(typical, 1) if typical is not None else None,
                         "days": len(days), "raised": raised})
            if raised and typical is not None:
                cards.append({"kind": "noise", "channel": int(channel), "sentence": (
                    f"Radio noise on channel {channel} has stayed at least {NOISE_ABOVE_DB:g} dB above its usual "
                    f"{typical:.0f} dBm for {NOISE_RECENT_DAYS} days. Something near the controller may be "
                    "interfering: a USB 3 port or cable, a Wi-Fi router, or a power supply. Try a USB "
                    "extension cable that moves the stick away from them.")})
        # Only channels with no current reading: nothing to show.
        if not rows:
            return None
        return {"channels": rows, "cards": cards}

    async def _noise_daily(self, entity_ids: list[str]) -> dict[str, list[float]]:
        """Each sensor's daily mean over the window, oldest first, from
        Home Assistant's long-term statistics. Empty where the recorder
        is not running."""
        if not entity_ids or "recorder" not in self.hass.config.components:  # type: ignore[attr-defined]
            return {}
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.statistics import statistics_during_period

        # Whole days only: today's day so far is not a day.
        end = dt_util.start_of_local_day()
        start = end - timedelta(days=EXTRAS_WINDOW_DAYS)

        def read() -> Any:
            return statistics_during_period(
                self.hass, start, end, set(entity_ids), "day", None, {"mean"}  # type: ignore[attr-defined]
            )

        found = await get_instance(self.hass).async_add_executor_job(read)  # type: ignore[attr-defined]
        out: dict[str, list[float]] = {}
        for entity_id, rows in (found or {}).items():
            means = []
            for row in rows or []:
                value = _number(row.get("mean")) if isinstance(row, dict) else None
                if value is not None and -200.0 <= value <= 50.0:
                    means.append(value)
            out[entity_id] = means
        return out

    def network_recommendations(self) -> list[dict[str, Any]]:
        """Each network with a recommendation of its own: its outage
        patterns and expected outages that ran long (rule DASH-18)."""
        rows = []
        self.forget_expected()
        for key in self.network_keys():  # type: ignore[attr-defined]
            try:
                cards = self.network_outage_view(key, forget=False)["cards"]
            except Exception as err:  # noqa: BLE001 - one network never breaks the tab
                LOGGER.debug("Outage patterns for %s not read: %s", key, err)
                continue
            if cards:
                rows.append({"key": key, "name": self.network_name(key), "cards": cards})  # type: ignore[attr-defined]
        return rows

    # ------------------------------------------------------------ page

    def network_extras(self, key: str, members: list[str], status: dict[str, Any]) -> dict[str, Any]:
        """Everything this mixin adds to a network's page."""
        devices = self._network_devices(key, members)
        view = self.network_outage_view(key)
        return {
            "devices": devices,
            "makeup": self._network_makeup(devices),
            "up": self._network_up(key, status, view["outages"]),
            "outages": view["outages"],
            "patterns": view["patterns"],
            "cards": view["cards"],
            "offenders": self._network_offenders(members),
            "wifi_changes": self._network_wifi_changes(members) if key == WIFI_KEY else None,
            "firmware": self._network_firmware(members),
            "noise": None,
            "own_page": key in (STACK_ZHA, STACK_ZWAVE, STACK_MATTER),
        }
