# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/device_recommendations.py, Version: 0.27.10 (2026-10-27)

"""Recommendations about single devices, for the Recommendations tab.

Each card lists the devices it covers, worst first (rule REC-04): a
device with no power set, the switched-off sensor cards, one with no
area, devices sharing a name, a device slow to judge for freeze,
offered a freeze mute (rule REC-06), and two about types: a device
with no type, and a model whose devices have more than one. Watched
devices only. A device leaves its card when its condition is gone,
as the other recommendations do.

The switched-off cards are read from a device's own entities only
(rule REC-05). Each row, and each written recommendation, is
acknowledged on its own with a checkbox that can be unticked again.
An acknowledgement is kept in the answers file and forgotten when its
device leaves the card, or its line goes, so a problem that comes back
is active again. A sensor a person switched off themselves starts
acknowledged (rule REC-07). Each card and line says whether Simple
shows it (rule REC-09); the dashboard counts what is unticked in the
cards its mode shows (rule REC-08).

The tab lists every device, and each can be put right from the list.
The emailed brief, and its file, carries one line for each kind, with
its count of devices not acknowledged, pointing to the tab. The slow
card and the two type cards stay out of the brief, because a slow
device or a missing or mixed type is not a fault (rule REC-10).
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr

from .const import (
    DATA_DEVICES,
    DEV_FROZEN_CATEGORY,
    FREEZE_CATEGORY_FROZEN,
    SLOW_REPORTER_SECONDS,
)

KIND_POWER = "power"
KIND_AREA = "area"
KIND_LAST_SEEN = "last_seen"
KIND_NAMES = "names"
KIND_TYPE = "type"
KIND_MIXED_TYPES = "mixed_types"
KIND_SLOW = "slow"
KIND_BATTERY_OFF = "battery_off"
KIND_SIGNAL_OFF = "signal_off"
KIND_NODE_STATUS_OFF = "node_status_off"
# A battery device's own voltage sensor, all switched off, listed only
# for a device with a battery reading.
KIND_VOLTAGE_OFF = "voltage_off"

# The switched-off cards and the kind of sensor each one turns on
# (rule REC-05).
SWITCHED_OFF_CARDS = {
    KIND_LAST_SEEN: "last_seen",
    KIND_BATTERY_OFF: "battery",
    KIND_SIGNAL_OFF: "signal",
    KIND_NODE_STATUS_OFF: "node_status",
    KIND_VOLTAGE_OFF: "voltage",
}
# The cards Simple shows: the ones that stop a missed or false alarm,
# with Confirm Battery Replacement. Signal Sensor Switched Off and
# Battery Voltage Switched Off join them too, because Simple's device
# page offers no turn-on button, so each sensor a Simple user may need
# on has its card here (rule REC-09).
KIND_BATTERY_CONFIRM = "battery_confirm"
SIMPLE_CARDS = frozenset({
    KIND_LAST_SEEN, KIND_BATTERY_OFF, KIND_NODE_STATUS_OFF, KIND_NAMES, KIND_SLOW,
    KIND_BATTERY_CONFIRM, KIND_SIGNAL_OFF, KIND_VOLTAGE_OFF,
})


def _count(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _short_day(iso: str) -> str:
    """A day as the brief writes one: Oct 18."""
    from datetime import date

    day = date.fromisoformat(iso)
    return f"{day.strftime('%b')} {day.day}"


class DeviceRecommendationsMixin:
    """The coordinator's device recommendations."""

    def switched_off_voltage(self) -> dict[str, str]:
        """The devices Battery Voltage Switched Off lists, with who
        switched each off.

        Only a device with a battery reading whose voltage nothing else
        reports, such as ZHA's battery_voltage on its battery sensor.
        One place, so the card and the diagnostics download count the
        same devices (rule REC-09).
        """
        return {
            d: who for d, who in self.switched_off_devices("voltage").items()  # type: ignore[attr-defined]
            if d in self._battery_entity  # type: ignore[attr-defined]
            and self.battery_voltage_now(d) is None  # type: ignore[attr-defined]
            # A device whose power is mains, USB or PoE: its voltage
            # sensor reads the supply, not a battery.
            and (self.power_of(d) or {}).get("kind", "battery") == "battery"  # type: ignore[attr-defined]
        }

    def device_recommendations(self) -> list[dict[str, Any]]:
        """Each kind that applies, with its devices in name order."""
        hass = self.hass  # type: ignore[attr-defined]
        devices = dr.async_get(hass)
        areas = ar.async_get(hass)
        watched = [d for d in self._watched if devices.async_get(d) is not None]  # type: ignore[attr-defined]

        def area_of(device_id: str) -> str | None:
            entry = devices.async_get(device_id)
            area = areas.async_get_area(entry.area_id) if entry and entry.area_id else None
            return area.name if area else None

        def rows(ids: list[str]) -> list[dict[str, Any]]:
            listed = [
                {"device_id": d, "name": self._device_name(d), "area": area_of(d)}  # type: ignore[attr-defined]
                for d in ids
            ]
            return sorted(listed, key=lambda row: (str(row["name"]).casefold(), row["device_id"]))

        cards: list[dict[str, Any]] = []
        # A detected battery replacement waits for a person, so it comes
        # first, because it is a question, and in Simple as well
        # (rule REC-04).
        confirm = [row for row in self.battery_confirm_rows() if row["device_id"] in watched]  # type: ignore[attr-defined]
        if confirm:
            by_id = {row["device_id"]: row for row in confirm}
            listed = rows(list(by_id))
            for row in listed:
                row["day"] = by_id[row["device_id"]]["day"]
                row["words"] = by_id[row["device_id"]]["words"]
            charged = all(row["words"]["done"] == "charged" for row in listed)
            cards.append({
                "kind": KIND_BATTERY_CONFIRM,
                "title": "Confirm Battery Charge" if charged else "Confirm Battery Replacement",
                "body": (
                    f"Device Sentinel detected a new or charged battery in "
                    f"{_count(len(listed), 'device', 'devices')}. Confirm each one, change the day "
                    "if it is wrong, or cancel it if the battery was not changed. The days left "
                    "and the battery charts follow your answer."
                ),
                "devices": listed,
                "brief_words": lambda n, listed=listed: (
                    "Battery " + ", ".join(
                        f"{row['words']['done']} on {row['name']}, detected {_short_day(row['day'])}"
                        for row in listed
                    ) + ". Confirm "
                    + ("it" if len(listed) == 1 else "them")
                    + " on the Recommendations tab."
                ),
            })
        power = [d for d in watched if self.power_of(d) is None]  # type: ignore[attr-defined]
        if power:
            cards.append({
                "kind": KIND_POWER,
                "title": "Power Not Set",
                "body": (
                    f"{_count(len(power), 'device has', 'devices have')} no battery or power "
                    "source set. Set each one here, and a low battery warning names "
                    "the battery to buy."
                ),
                "devices": rows(power),
                "brief_words": lambda n: (
                    f"{_count(n, 'device has', 'devices have')} no battery or power "
                    "source set. Set them from the Recommendations tab, and a low battery "
                    "warning names the battery to buy."
                ),
            })
        # The switched-off cards: a device is listed when none of its
        # own entities of the kind is on (rule REC-05).
        off = {
            kind: self.switched_off_devices(sensor)  # type: ignore[attr-defined]
            for kind, sensor in SWITCHED_OFF_CARDS.items()
            if kind != KIND_VOLTAGE_OFF
        }
        off[KIND_VOLTAGE_OFF] = self.switched_off_voltage()
        switched_off_words = (
            (KIND_LAST_SEEN, "Last Seen Sensor Switched Off", "a Last Seen sensor",
             "With it on, Device Sentinel notices the device going quiet sooner."),
            (KIND_BATTERY_OFF, "Battery Sensor Switched Off", "a battery sensor",
             "With it on, Device Sentinel warns you when the battery runs low."),
            (KIND_NODE_STATUS_OFF, "Z-Wave Status Switched Off", "a Z-Wave status sensor",
             "It is the only place Home Assistant shows that Z-Wave can no longer reach "
             "a device, so with it on, Device Sentinel reports the device unavailable."),
            (KIND_SIGNAL_OFF, "Signal Sensor Switched Off", "a signal sensor",
             "With it on, Device Sentinel charts the device's signal and tells you when "
             "a signal reading is stuck."),
            # The card's own words (rule REC-05).
            (KIND_VOLTAGE_OFF, "Battery Voltage Switched Off", "a battery voltage sensor",
             lambda n: (
                "This device has a battery voltage entity" if n == 1
                else "These devices have battery voltage entities"
             ) + " which can be used for more accurate battery reporting and forecasting."),
        )
        for kind, title, sensor_words, gain_words in switched_off_words:
            ids = [d for d in watched if d in off[kind]]
            if not ids:
                continue
            # A sentence, or one that follows the count.
            gain = gain_words(len(ids)) if callable(gain_words) else gain_words
            listed = rows(ids)
            for row in listed:
                row["by_user"] = off[kind][row["device_id"]] == "user"
            cards.append({
                "kind": kind,
                "title": title,
                "body": (
                    f"{_count(len(ids), 'device has', 'devices have')} {sensor_words} "
                    f"that is switched off. {gain} Turn each one on here."
                ),
                "devices": listed,
                "brief_words": (
                    lambda n, sensor_words=sensor_words, gain_words=gain_words: (
                        f"{_count(n, 'device has', 'devices have')} {sensor_words} that "
                        f"is switched off. {gain_words(n) if callable(gain_words) else gain_words} "
                        "Turn them on from the Recommendations tab."
                    )
                ),
            })
        no_area = [d for d in watched if area_of(d) is None]
        if no_area:
            cards.append({
                "kind": KIND_AREA,
                "title": "No Area Assigned",
                "body": (
                    f"{_count(len(no_area), 'device has', 'devices have')} no area. The "
                    "Daily Brief and the Problem List name each device with its room, "
                    "so these appear without one. Open a device to assign its area."
                ),
                "devices": rows(no_area),
                "brief_words": lambda n: (
                    f"{_count(n, 'device has', 'devices have')} no area, so the "
                    "Daily Brief and the Problem List show them without a room. Assign "
                    "them from the Recommendations tab."
                ),
            })
        by_name: dict[str, list[str]] = {}
        for device_id in watched:
            name = str(self._device_name(device_id) or "").strip().casefold()  # type: ignore[attr-defined]
            if name:
                by_name.setdefault(name, []).append(device_id)
        shared = [d for ids in by_name.values() if len(ids) > 1 for d in ids]
        if shared:
            cards.append({
                "kind": KIND_NAMES,
                "title": "Devices Sharing A Name",
                "body": (
                    f"{_count(len(shared), 'device shares', 'devices share')} a name with "
                    "another. In the Daily Brief and in notifications they cannot be told "
                    "apart. Open a device to rename it."
                ),
                "devices": rows(shared),
                "brief_words": lambda n: (
                    f"{_count(n, 'device shares', 'devices share')} a name with "
                    "another, so they cannot be told apart in this brief or in "
                    "notifications. Rename them from the Recommendations tab."
                ),
            })
        # A device slow to judge for freeze: its wait in use is over
        # SLOW_REPORTER_SECONDS, it reports on a person's habits rather
        # than a rhythm, and a freeze verdict for it comes late and is
        # often noise. The card offers a freeze mute and changes nothing
        # itself. A device already muted for freeze or for everything,
        # and one the freeze rules never judge frozen, such as an awake
        # ESPHome device or an available Matter button, light, plug or
        # switch, are left off (rule REC-06). Not in the emailed brief,
        # because a slow device is not a fault (rule REC-10).
        slow = [d for d in watched if self._slow_reporter(d)]  # type: ignore[attr-defined]
        if slow:
            cards.append({
                "kind": KIND_SLOW,
                "title": "Slow Reporting Devices",
                "body": (
                    "These devices go quiet for long periods. They are often devices that "
                    "sleep until a person triggers or interacts with them. Because these "
                    "devices do not report on a rhythm, Device Sentinel has trouble "
                    "accurately reporting a frozen verdict. Often a freeze verdict for "
                    "this device is noise and the best practice is to mute it. Device "
                    "Sentinel will still report when it becomes unavailable or its "
                    "battery runs low."
                ),
                "devices": rows(slow),
            })
        # Last: a missing or mixed type. The type decides a Matter
        # device's freeze rule (rule STACK-06); for any other it changes
        # no judgment.
        kinds = {d: self.type_words(d) for d in watched}  # type: ignore[attr-defined]
        untyped = [d for d in watched if not kinds[d]]
        if untyped:
            cards.append({
                "kind": KIND_TYPE,
                "title": "Type Not Set",
                "body": (
                    f"{_count(len(untyped), 'device has', 'devices have')} no type. Set each "
                    "one here, and it joins the others of its kind on the Devices, Battery "
                    "Trends and Classification tabs."
                ),
                "devices": rows(untyped),
            })
        # Models whose devices disagree: a device given its own type
        # apart from the rest of its model, by an owner or by its
        # entities. Devices with no type are the card above's.
        by_model: dict[str, list[str]] = {}
        for device_id in watched:
            key = self._power_key(device_id)  # type: ignore[attr-defined]
            if key is not None and kinds[device_id]:
                by_model.setdefault(key, []).append(device_id)
        mixed = [ids for ids in by_model.values() if len({kinds[d] for d in ids}) > 1]
        if mixed:
            listed_mixed = []
            for ids in mixed:
                for row in rows(ids):
                    maker, model, _model_id, _hw = self._power_device_fields(row["device_id"])  # type: ignore[attr-defined]
                    row["model"] = " ".join(part for part in (maker, model) if part)
                    row["type"] = kinds[row["device_id"]]
                    listed_mixed.append(row)
            cards.append({
                "kind": KIND_MIXED_TYPES,
                "title": "Model With More Than One Type",
                "body": (
                    f"{_count(len(mixed), 'model has', 'models have')} devices of more than one "
                    "type. Open the device that is different and set it to match, or give the "
                    "model the type you want."
                ),
                "devices": listed_mixed,
            })
        return self._acknowledged_cards(cards)

    # ------------------------------------------------- acknowledgement

    def _acks(self) -> dict[str, Any]:
        """The acknowledgements, read from the answers file (rule REC-07)."""
        found = getattr(self, "_recommendation_acks", None)
        if not isinstance(found, dict):
            found = {"devices": {}, "lines": {}}
            self._recommendation_acks = found
        return found

    def _acknowledged_cards(self, cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Mark each row acknowledged or not, and word each card's brief
        line for the rows still active (rule REC-07).

        A row's tick is the person's own. A switched-off sensor the
        person switched off themselves starts ticked: it is shown, so
        the person sees Device Sentinel would like it on, and left out
        of the count and the Brief. This only reads: ticks are
        forgotten at the midnight run alone
        (`prune_recommendation_acks`), so the report writer, off Home
        Assistant's own thread, never changes them.
        """
        kept: dict[str, dict[str, bool]] = self._acks().get("devices") or {}
        for card in cards:
            kind = card["kind"]
            own = kept.get(kind) or {}
            active = 0
            for row in card["devices"]:
                default = bool(row.get("by_user"))
                # A battery replacement is answered, not ticked (rule REC-04).
                row["acknowledged"] = (
                    False if kind == KIND_BATTERY_CONFIRM
                    else bool(own.get(row["device_id"], default))
                )
                if not row["acknowledged"]:
                    active += 1
            card["active"] = active
            card["simple"] = kind in SIMPLE_CARDS
            words = card.pop("brief_words", None)
            if words is not None:
                card["brief"] = words(active) if active else None
        return cards

    def recommendation_lines(self) -> list[dict[str, Any]]:
        """The written recommendations, each marked acknowledged or not
        (rule REC-07). Reads only, as `_acknowledged_cards` does."""
        entries = self._recommendation_entries()  # type: ignore[attr-defined]
        kept: dict[str, bool] = self._acks().get("lines") or {}
        for entry in entries:
            entry["acknowledged"] = bool(kept.get(entry["key"], False))
        return entries

    def prune_recommendation_acks(self) -> None:
        """Forget each tick whose device has left its card or whose
        line is gone, at the midnight run only (rule REC-07).

        One place, on Home Assistant's own thread, at a time every
        reader has long since been heard: a start is not a midnight, so
        a line missing for a moment while a reader starts never loses
        its tick. The new dictionaries are put in place whole.
        """
        acks = self._acks()
        cards = {card["kind"]: {row["device_id"] for row in card["devices"]}
                 for card in self.device_recommendations()}
        old_devices: dict[str, dict[str, bool]] = acks.get("devices") or {}
        devices = {
            kind: {d: on for d, on in ticks.items() if d in cards.get(kind, set())}
            for kind, ticks in old_devices.items()
        }
        devices = {kind: ticks for kind, ticks in devices.items() if ticks}
        present = {entry["key"] for entry in self._recommendation_entries()}  # type: ignore[attr-defined]
        old_lines: dict[str, bool] = acks.get("lines") or {}
        lines = {key: on for key, on in old_lines.items() if key in present}
        if devices != old_devices or lines != old_lines:
            acks["devices"] = devices
            acks["lines"] = lines
            self._answers_save()  # type: ignore[attr-defined]

    def set_recommendation_ack(
        self, on: bool, *, kind: str | None = None, device_id: str | None = None,
        line: str | None = None,
    ) -> None:
        """Tick or untick one device on one card, or one written line.

        Kept as the person left it, true or false, so a sensor they
        switched off can be unticked to count again.
        """
        acks = self._acks()
        if line is not None:
            present = {entry["key"] for entry in self._recommendation_entries()}  # type: ignore[attr-defined]
            if line not in present:
                raise ValueError("That recommendation is no longer shown")
            acks.setdefault("lines", {})[line] = bool(on)
        else:
            cards = {card["kind"]: card for card in self.device_recommendations()}
            card = cards.get(kind or "")
            if card is None or device_id not in {row["device_id"] for row in card["devices"]}:
                raise ValueError("That device is no longer on that card")
            acks.setdefault("devices", {}).setdefault(str(kind), {})[str(device_id)] = bool(on)
        self._answers_save()  # type: ignore[attr-defined]
        self._mark_changed()  # type: ignore[attr-defined]

    def _acks_read(self, payload: Any) -> int:
        """Take the acknowledgements from the answers file; anything not
        in their shape is dropped and counted (rule STOR-09)."""
        dropped = 0
        devices: dict[str, dict[str, bool]] = {}
        lines: dict[str, bool] = {}
        if not isinstance(payload, dict):
            dropped += payload is not None
            payload = {}
        raw_devices = payload.get("devices", {})
        if isinstance(raw_devices, dict):
            for kind, ticks in raw_devices.items():
                if not isinstance(ticks, dict):
                    dropped += 1
                    continue
                for device_id, value in ticks.items():
                    if isinstance(value, bool):
                        devices.setdefault(str(kind), {})[str(device_id)] = value
                    else:
                        dropped += 1
        else:
            dropped += 1
        raw_lines = payload.get("lines", {})
        if isinstance(raw_lines, dict):
            for key, value in raw_lines.items():
                if isinstance(value, bool):
                    lines[str(key)] = value
                else:
                    dropped += 1
        else:
            dropped += 1
        self._recommendation_acks = {"devices": devices, "lines": lines}
        return dropped

    def _acks_payload(self) -> dict[str, Any]:
        acks = self._acks()
        return {
            "devices": {kind: dict(ticks) for kind, ticks in acks.get("devices", {}).items() if ticks},
            "lines": dict(acks.get("lines", {})),
        }

    def _slow_reporter(self, device_id: str) -> bool:
        """Whether a watched device's wait in use is over the slow line (rule REC-06).

        A device muted for everything is never judged frozen either, so
        it is left off as a freeze-muted one is.
        """
        if device_id in self._muted_devices:  # type: ignore[attr-defined]
            return False
        if self._freeze_muted(device_id):  # type: ignore[attr-defined]
            return False
        record = self.data.get(DATA_DEVICES, {}).get(device_id)  # type: ignore[attr-defined]
        if not isinstance(record, dict):
            return False
        # Left off only where judgment leaves it (rule STACK-07): an
        # awake ESPHome device, connected or dropped (a drop is judged
        # unavailable, never frozen), with no frozen verdict standing.
        # Otherwise the freeze rule can still judge it, so the card
        # still offers the mute.
        if (
            (
                self._awake_esphome(device_id)  # type: ignore[attr-defined]
                or self._dropped_esphome(device_id)  # type: ignore[attr-defined]
                # a Matter device of a type that reports only on use, available (rule STACK-06).
                or self._matter_available_now(device_id)  # type: ignore[attr-defined]
            )
            and record.get(DEV_FROZEN_CATEGORY) != FREEZE_CATEGORY_FROZEN
        ):
            return False
        # Judged by its hub: never judged frozen, so a freeze mute
        # offers nothing (rule STACK-09).
        if self.judged_by_hub(device_id):  # type: ignore[attr-defined]
            return False
        window = self._freeze_window(record)  # type: ignore[attr-defined]
        return window is not None and window > SLOW_REPORTER_SECONDS
