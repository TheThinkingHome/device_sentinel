# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: radio_channels.py, Version: 0.30.0 (2026-11-21)

"""Which radio channel each network and device uses (rules SIG-19, SIG-20).

Zigbee, Thread and 2.4 GHz Wi-Fi share one band. A Wi-Fi network whose
channel covers a Zigbee or Thread channel can drown it out. Device
Sentinel reads what the house already reports:

- Zigbee2MQTT's channel from its bridge, and ZHA's from the network
  ZHA holds in memory, read only and never through an import.
- A Matter device's own Thread channel, or its Wi-Fi channel and the
  access point it is joined to, from its diagnostics attributes.
- Every Wi-Fi network the server hears, from the Supervisor's scan:
  name, frequency, signal and access point. The scan Device Sentinel
  already makes each minute where a Wi-Fi network is chosen, and once an
  hour where none is. Only the latest is kept, in memory.

Nothing here is measured noise. It is what the server hears from where
it stands, which can differ from what a Zigbee coordinator in another
room hears.
"""

from __future__ import annotations

import base64
import binascii
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    LOGGER,
    STACK_DISPLAY_NAMES,
    STACK_MATTER,
    STACK_Z2M,
    STACK_ZHA,
    WIFI_KEY,
)
from .network_extras import network_ack_ticked
from .study_stacks import _matter_attributes, _plain, _read, live_entries, node_devices
from .wifi import SUPERVISOR, pick_adapter, read_interfaces, scan_networks

# Where no Wi-Fi network is chosen, the scan made for the channels alone.
AIR_SCAN_SECONDS = 3600.0
AIR_RETRY_SECONDS = 300.0
# A network heard at this signal or more, covering a Zigbee or Thread
# channel, is an overlap judged bad (rule SIG-20).
STRONG_PERCENT = 50
# The Wi-Fi channel card, once shown for a crowd, stays while a
# neighbour is heard at this or more, and until a day has passed under
# it, so a neighbour wavering about 50% neither drops a ticked card nor
# brings it back (rule REC-13).
HOLD_PERCENT = 40
HOLD_SECONDS = 86400.0
# Half a 20 MHz Wi-Fi channel's width plus half a Zigbee channel's: a
# Wi-Fi channel covers a Zigbee channel whose centre lies within it.
COVER_MHZ = 11
# The Wi-Fi channels that do not overlap one another, the only ones
# recommended.
WIFI_CHOICES = (1, 6, 11)
# The Zigbee channels Zigbee2MQTT's configuration names "to avoid
# problems", the only ones recommended.
ZIGBEE_CHOICES = (11, 15, 20, 25)
ZIGBEE_STACKS = (STACK_Z2M, STACK_ZHA)
NETWORK_NAME_MAX = 64


def wifi_channel(mhz: int) -> int | None:
    """A Wi-Fi channel from its centre frequency, or None."""
    if mhz == 2484:
        return 14
    if 2412 <= mhz <= 2472 and (mhz - 2407) % 5 == 0:
        return (mhz - 2407) // 5
    if 5000 < mhz < 5925 and mhz % 5 == 0:
        return (mhz - 5000) // 5
    if 5950 <= mhz <= 7125 and (mhz - 5950) % 5 == 0:
        return (mhz - 5950) // 5
    return None


def wifi_band(mhz: int) -> str:
    if mhz < 2500:
        return "2.4 GHz"
    return "5 GHz" if mhz < 5925 else "6 GHz"


def wifi_mhz(channel: int) -> int:
    """A 2.4 GHz Wi-Fi channel's centre."""
    return 2484 if channel == 14 else 2407 + 5 * channel


def zigbee_mhz(channel: int) -> int:
    """A Zigbee or Thread channel's centre (IEEE 802.15.4, 2.4 GHz)."""
    return 2405 + 5 * (channel - 11)


def covers(mhz: int, channel: int) -> bool:
    """Whether a 2.4 GHz Wi-Fi network at `mhz` covers a Zigbee or
    Thread channel."""
    return mhz < 2500 and abs(mhz - zigbee_mhz(channel)) <= COVER_MHZ


def _mac(value: Any) -> str | None:
    """A MAC address as six upper-case pairs, or None."""
    if not isinstance(value, str):
        return None
    digits = "".join(ch for ch in value if ch.isalnum()).upper()
    if len(digits) != 12 or any(ch not in "0123456789ABCDEF" for ch in digits):
        return None
    return ":".join(digits[i:i + 2] for i in range(0, 12, 2))


def _matter_mac(value: Any) -> str | None:
    """A Matter device's access point address: six bytes, which the
    Matter server writes as base64, or as hex."""
    if isinstance(value, (bytes, bytearray)) and len(value) == 6:
        return ":".join(f"{b:02X}" for b in value)
    if isinstance(value, str) and len(value) == 8:
        try:
            raw = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            raw = b""
        if len(raw) == 6:
            return ":".join(f"{b:02X}" for b in raw)
    return _mac(value)


def _siblings(a: str, b: str) -> bool:
    """Two access points of one radio: their addresses differ in one
    pair at most, as a router's main, guest and IoT networks do."""
    return sum(x != y for x, y in zip(a.split(":"), b.split(":"), strict=False)) <= 1


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class RadioChannelsMixin:
    """The coordinator's side of the radio channels."""

    _air: list[dict[str, Any]] | None = None
    _air_at: float | None = None
    _air_next: float = 0.0
    _air_interface: str | None = None
    _air_joined: str | None = None
    # Whether the adapter in use is connected to a network: the empty
    # Networks tab says how to connect one that is not (rule DASH-17).
    _air_connected: bool | None = None
    _air_why: str = "not_yet"
    # Each Wi-Fi card held for a crowd, by its advice: when its neighbours
    # were last heard at HOLD_PERCENT or more, and the loudest then
    # (rule REC-13).
    _wifi_held: dict[str, tuple[float, dict[str, Any]]] | None = None

    # ------------------------------------------------------------- scan

    def _note_air(self, points: list[dict[str, Any]], now: float) -> None:
        """Keep the latest scan: each access point with a frequency."""
        rows: list[dict[str, Any]] = []
        for point in points or []:
            if not isinstance(point, dict):
                continue
            mhz = _int(point.get("frequency"))
            channel = wifi_channel(mhz) if mhz is not None else None
            if mhz is None or channel is None:
                continue
            signal = _int(point.get("signal"))
            raw = point.get("ssid")
            ssid = raw if isinstance(raw, str) else ""
            rows.append({
                "ssid": ssid[:NETWORK_NAME_MAX],
                "mhz": mhz,
                "channel": channel,
                "band": wifi_band(mhz),
                "signal": max(0, min(100, signal)) if signal is not None else None,
                "bssid": _mac(point.get("mac")),
            })
        rows.sort(key=lambda row: (row["mhz"], -(row["signal"] or 0)))
        self._air = rows
        self._air_at = now
        self._air_why = "ok"

    async def async_sweep_air(self, now: float | None = None) -> None:
        """Once an hour, where no Wi-Fi network is chosen: the scan made
        for the channels alone (rule SIG-19). Where one is chosen, the
        minute's Wi-Fi sweep keeps the scan, and only the network the
        server is joined to is read here."""
        now = dt_util.utcnow().timestamp() if now is None else now
        if now < self._air_next:
            return
        self._air_next = now + AIR_SCAN_SECONDS
        try:
            interfaces = await read_interfaces(self.hass)  # type: ignore[attr-defined]
        except Exception as err:  # noqa: BLE001 - a scan never breaks the minute
            LOGGER.debug("device_sentinel: radio scan not read: %s", err)
            # A Supervisor still starting is asked again in five minutes.
            self._air_next = now + AIR_RETRY_SECONDS
            return
        if interfaces is None:
            if self.hass.data.get(SUPERVISOR) is None:  # type: ignore[attr-defined]
                self._air_why = "no_supervisor"
            else:
                # The Supervisor did not answer: asked again in five minutes.
                self._air_next = now + AIR_RETRY_SECONDS
            return
        wireless = [row for row in interfaces if isinstance(row, dict) and row.get("type") == "wireless"]
        if not wireless:
            self._air_why = "no_adapter"
            return
        # The adapter connected to a network, then one switched on, as the
        # Wi-Fi sweep picks it (rule UP-12).
        first = pick_adapter(wireless) or wireless[0]
        if first.get("enabled") is False:
            # Turned off in Settings: nothing to hear until it is on.
            self._air_why = "adapter_off"
            self._air_connected = False
            return
        self._air_interface = first.get("interface") if isinstance(first.get("interface"), str) else None
        self._air_connected = first.get("connected") is True
        wifi = first.get("wifi")
        joined = wifi.get("ssid") if isinstance(wifi, dict) and first.get("connected") else None
        self._air_joined = joined if isinstance(joined, str) and joined else None
        if self.wifi_networks or self._air_interface is None:  # type: ignore[attr-defined]
            return
        points = await scan_networks(self.hass, self._air_interface)  # type: ignore[attr-defined]
        if points is not None:
            self._note_air(points, now)
        else:
            self._air_next = now + AIR_RETRY_SECONDS

    # ------------------------------------------------------ what is used

    def _matter_nodes(self) -> list[tuple[str, dict[str, Any]]]:
        """Each Matter device with its attribute table, read from what
        Home Assistant holds in memory."""
        found: list[tuple[str, dict[str, Any]]] = []
        for entry in live_entries(self.hass, STACK_MATTER):  # type: ignore[attr-defined]
            client = _read(_read(_read(entry, "runtime_data"), "adapter"), "matter_client")
            getter = _read(client, "get_nodes")
            if not callable(getter):
                continue
            try:
                nodes = list(getter())
            except Exception as err:  # noqa: BLE001 - a library call
                LOGGER.debug("device_sentinel: Matter nodes unreadable: %s", err)
                continue
            devices = node_devices(self.hass, entry, STACK_MATTER)  # type: ignore[attr-defined]
            for node in nodes:
                device_id = devices.get(str(_plain(_read(node, "node_id"))))
                if device_id is not None:
                    found.append((device_id, _matter_attributes(node)))
        return found

    def _zha_channel(self) -> int | None:
        """ZHA's channel, from the network ZHA holds in memory."""
        data = self.hass.data.get("zha")  # type: ignore[attr-defined]
        proxy = _read(data, "gateway_proxy")
        app = _read(_read(proxy, "gateway"), "application_controller")
        channel = _int(_read(_read(_read(app, "state"), "network_info"), "channel"))
        return channel if channel is not None and 11 <= channel <= 26 else None

    def zigbee_networks(self) -> list[dict[str, Any]]:
        """Each Zigbee network with its channel."""
        found: list[dict[str, Any]] = []
        reader = self.bridge_reader(STACK_Z2M)  # type: ignore[attr-defined]
        try:
            channel = _int((getattr(reader, "hardware", None) or {}).get("channel")) if reader else None
        except Exception:  # noqa: BLE001 - a reader never breaks a page
            channel = None
        if channel is not None:
            found.append({"key": STACK_Z2M, "name": STACK_DISPLAY_NAMES[STACK_Z2M], "channel": channel})
        try:
            channel = self._zha_channel()
        except Exception:  # noqa: BLE001 - ZHA's own objects may move
            channel = None
        if channel is not None:
            found.append({"key": STACK_ZHA, "name": STACK_DISPLAY_NAMES[STACK_ZHA], "channel": channel})
        return found

    def _matter_radios(self) -> dict[str, dict[str, Any]]:
        """Each Matter device's Thread channel, or Wi-Fi channel and
        access point, as the device reports them."""
        radios: dict[str, dict[str, Any]] = {}
        for device_id, table in self._matter_nodes():
            thread = _int(table.get("0/53/0"))
            wifi = _int(table.get("0/54/3"))
            if thread is not None and 11 <= thread <= 26:
                radios[device_id] = {"kind": "thread", "channel": thread}
            elif wifi is not None and 1 <= wifi <= 233:
                radios[device_id] = {"kind": "wifi", "channel": wifi, "bssid": _matter_mac(table.get("0/54/0"))}
        return radios

    # ------------------------------------------------------- whose it is

    def _own_names(self) -> set[str]:
        """The house's own network names: the ones chosen, the one the
        server is joined to, and those its devices and trackers report."""
        names = {name for name in self.wifi_networks if name}  # type: ignore[attr-defined]
        if self._air_joined:
            names.add(self._air_joined)
        for state in self.hass.states.async_all("sensor"):  # type: ignore[attr-defined]
            if state.entity_id.endswith("_ssid") and not state.entity_id.endswith("_bssid"):
                if isinstance(state.state, str) and state.state not in ("", "unknown", "unavailable"):
                    names.add(state.state)
        for tracker in set((getattr(self, "_wifi_ties", None) or {}).values()):
            state = self.hass.states.get(tracker) if isinstance(tracker, str) else None  # type: ignore[attr-defined]
            for key in ("essid", "ssid"):
                value = state.attributes.get(key) if state is not None else None
                if isinstance(value, str) and value:
                    names.add(value)
        return names

    def _air_rows(self) -> list[dict[str, Any]]:
        """The latest scan, each access point marked as the house's own
        or a neighbour's."""
        rows = [dict(row) for row in (self._air or [])]
        own = self._own_names()
        for row in rows:
            row["own"] = bool(row["ssid"]) and row["ssid"] in own
        # A router's main, guest, IoT and hidden networks on one radio,
        # each found through the next, and then each of those names on
        # every band.
        grew = True
        while grew:
            grew = False
            for row in rows:
                if row["own"] or not row["bssid"]:
                    continue
                if any(other["own"] and other["bssid"] and other["mhz"] == row["mhz"]
                       and _siblings(row["bssid"], other["bssid"]) for other in rows):
                    row["own"] = grew = True
            names = {row["ssid"] for row in rows if row["own"] and row["ssid"]}
            for row in rows:
                if not row["own"] and row["ssid"] in names:
                    row["own"] = grew = True
        return rows

    # ------------------------------------------------------- the device

    def _device_bssid(self, device_id: str) -> str | None:
        """The access point a device reports it is joined to, from a
        `bssid` sensor of its own (ESPHome, a phone)."""
        from homeassistant.helpers import entity_registry as er

        for entry in er.async_entries_for_device(er.async_get(self.hass), device_id):  # type: ignore[attr-defined]
            if entry.domain == "sensor" and entry.entity_id.endswith("_bssid"):
                state = self.hass.states.get(entry.entity_id)  # type: ignore[attr-defined]
                found = _mac(state.state) if state is not None else None
                if found:
                    return found
        return None

    def _device_ssid(self, device_id: str) -> str | None:
        from homeassistant.helpers import entity_registry as er

        for entry in er.async_entries_for_device(er.async_get(self.hass), device_id):  # type: ignore[attr-defined]
            if entry.domain == "sensor" and entry.entity_id.endswith("_ssid") and not entry.entity_id.endswith("_bssid"):
                state = self.hass.states.get(entry.entity_id)  # type: ignore[attr-defined]
                if state is not None and state.state not in ("", "unknown", "unavailable"):
                    return str(state.state)
        return None

    def _tracker_band(self, device_id: str) -> tuple[str | None, str | None]:
        """The network and band a router reports a device on: UniFi's
        `essid` and `radio`, or a TP-Link Deco's `band`."""
        tracker = (getattr(self, "_wifi_ties", None) or {}).get(device_id)
        state = self.hass.states.get(tracker) if isinstance(tracker, str) else None  # type: ignore[attr-defined]
        if state is None:
            return None, None
        attrs = state.attributes
        ssid = attrs.get("essid") if isinstance(attrs.get("essid"), str) else None
        radio = attrs.get("radio")
        band = attrs.get("band")
        if radio == "ng" or band in ("2G", "2.4G", "2.4GHz"):
            return ssid, "2.4 GHz"
        if radio == "na" or band in ("5G", "5G1", "5G2", "5GHz"):
            return ssid, "5 GHz"
        if radio == "6e" or band in ("6G", "6GHz"):
            return ssid, "6 GHz"
        return ssid, None

    def device_radio(self, device_id: str) -> dict[str, Any] | None:
        """The channel a device's radio uses and where that was learned,
        or None where nothing says (rule SIG-19)."""
        stack = getattr(self, "_radio_stack", {}).get(device_id)
        if stack in ZIGBEE_STACKS:
            net = next((n for n in self.zigbee_networks() if n["key"] == stack), None)
            if net is None:
                return None
            return self._judged({"kind": "zigbee", "channel": net["channel"],
                                 "words": f"Zigbee channel {net['channel']}, from {net['name']}"}, stack)
        try:
            matter = self._matter_radios().get(device_id) if stack == STACK_MATTER else None
        except Exception:  # noqa: BLE001 - a library's objects may move
            matter = None
        if matter is not None and matter["kind"] == "thread":
            return self._judged({"kind": "thread", "channel": matter["channel"],
                                 "words": f"Thread channel {matter['channel']}, from the device"})
        rows = self._air_rows()
        if matter is not None:
            matter_band = "2.4 GHz" if matter["channel"] <= 14 else "5 GHz"
            return self._judged({"kind": "wifi", "channel": matter["channel"], "band": matter_band,
                                 "words": f"Wi-Fi channel {matter['channel']}, {matter_band}, from the device"})
        bssid = self._device_bssid(device_id)
        if bssid:
            row = next((r for r in rows if r["bssid"] == bssid), None)
            if row is not None:
                return self._judged({"kind": "wifi", "channel": row["channel"], "band": row["band"], "mhz": row["mhz"],
                                     "words": f"Wi-Fi channel {row['channel']}, {row['band']}, from its access point"})
        named, band = self._tracker_band(device_id)
        ssid = named or self._device_ssid(device_id)
        if ssid:
            heard = [r for r in rows if r["ssid"] == ssid and (band is None or r["band"] == band)]
            # A device that names its network but not its band: the
            # 2.4 GHz radio, which every one of these devices has.
            if band is None and any(r["band"] == "2.4 GHz" for r in heard):
                heard = [r for r in heard if r["band"] == "2.4 GHz"]
            where = f"from its network {ssid}"
        elif band is not None and getattr(self, "_wifi_ties", {}).get(device_id):
            heard = [r for r in rows if r.get("own") and r["band"] == band]
            where = "from its band on your network"
        else:
            return None
        channels = sorted({r["channel"] for r in heard})
        if not channels:
            return None
        shown = channels[0] if len(channels) == 1 else None
        said = str(shown) if shown is not None else " or ".join(str(c) for c in channels)
        band_said = heard[0]["band"]
        return self._judged({"kind": "wifi", "channel": shown, "channels": channels, "band": band_said,
                             "mhz": heard[0]["mhz"] if shown is not None else None,
                             "words": f"Wi-Fi channel {said}, {band_said}, {where}"})

    def _open_card(self, key: str, test: Any) -> dict[str, Any] | None:
        """A channel card of a network that is shown and not ticked."""
        kept: dict[str, bool] = self._acks().get("lines") or {}  # type: ignore[attr-defined]
        for card in self._channel_cards(key):
            if test(card) and not network_ack_ticked(kept, key, card):
                return card
        return None

    def _judged(self, radio: dict[str, Any], network: str | None = None) -> dict[str, Any]:
        """The radio with a warning where a strong network overlaps it,
        only while the card that could clear it is shown and not ticked
        (rule SIG-20): the house's Wi-Fi card for its own Wi-Fi, the
        Zigbee network's card for a neighbour's."""
        radio["warn"] = None
        if radio["kind"] not in ("zigbee", "thread"):
            return radio
        rows = self._air_rows()
        over = [r for r in rows if not r["own"] and (r["signal"] or 0) >= STRONG_PERCENT and covers(r["mhz"], radio["channel"])]
        mine = [r for r in rows if r["own"] and covers(r["mhz"], radio["channel"])]
        if mine:
            channels = {r["channel"] for r in mine}
            if self._open_card(WIFI_KEY, lambda c: c.get("reason") in {f"wifi:{ch}:covered" for ch in channels}):
                radio["warn"] = f"Your own Wi-Fi on channel {mine[0]['channel']} covers this channel."
        elif over and network in ZIGBEE_STACKS and self._open_card(network, lambda c: True):
            strongest = max(over, key=lambda r: r["signal"] or 0)
            radio["warn"] = (
                f"A neighbour's Wi-Fi on channel {strongest['channel']}, heard at "
                f"{strongest['signal']}%, covers this channel."
            )
        return radio

    def device_radio_safe(self, device_id: str) -> dict[str, Any] | None:
        """The device page's Radio channel row; never breaks the page."""
        try:
            return self.device_radio(device_id)
        except Exception as err:  # noqa: BLE001 - a row never breaks a page
            LOGGER.debug("device_sentinel: radio channel of %s not read: %s", device_id, err)
            return None

    def zha_channel_safe(self) -> int | None:
        try:
            return self._zha_channel()
        except Exception:  # noqa: BLE001 - ZHA's own objects may move
            return None

    def network_radio(self, key: str) -> dict[str, Any] | None:
        """A network page's radio section: for Wi-Fi, every network the
        server hears; for Matter, its Thread channels (rule DASH-19)."""
        try:
            if key == WIFI_KEY:
                view = self.air_view()
                return {"scanned_at": view["scanned_at"], "scan": view["scan"], "heard": view["wifi"]}
            if key == STACK_MATTER:
                thread = self._thread_channels()
                return {"thread": thread} if thread else None
        except Exception as err:  # noqa: BLE001 - a section never breaks a page
            LOGGER.debug("device_sentinel: radio section of %s not read: %s", key, err)
        return None

    def air_view_safe(self) -> dict[str, Any] | None:
        try:
            return self.air_view()
        except Exception as err:  # noqa: BLE001 - the tab still shows without it
            LOGGER.debug("device_sentinel: radio chart not read: %s", err)
            return None

    # ------------------------------------------------------------- views

    def _thread_channels(self) -> list[dict[str, Any]]:
        counts: dict[int, int] = {}
        try:
            radios = self._matter_radios()
        except Exception:  # noqa: BLE001 - a library's objects may move
            radios = {}
        for radio in radios.values():
            if radio["kind"] == "thread":
                counts[radio["channel"]] = counts.get(radio["channel"], 0) + 1
        return [{"channel": c, "devices": n} for c, n in sorted(counts.items())]

    def air_view(self) -> dict[str, Any]:
        """The Networks tab's chart: the 2.4 GHz band as the server hears
        it, and the Zigbee and Thread networks in it (rule DASH-19)."""
        rows = self._air_rows()
        zigbee = []
        members = self._network_members() if hasattr(self, "_network_members") else {}  # type: ignore[attr-defined]
        for net in self.zigbee_networks():
            zigbee.append({**net, "mhz": zigbee_mhz(net["channel"]), "devices": len(members.get(net["key"], []))})
        thread = [{**row, "mhz": zigbee_mhz(row["channel"])} for row in self._thread_channels()]
        overlaps = []
        for net in [*({"name": n["name"], "channel": n["channel"]} for n in zigbee),
                    *({"name": "Thread", "channel": t["channel"]} for t in thread)]:
            for row in rows:
                if covers(row["mhz"], net["channel"]):
                    overlaps.append({
                        "network": net["name"], "channel": net["channel"],
                        "ssid": row["ssid"], "wifi_channel": row["channel"], "signal": row["signal"],
                        "own": row["own"], "bad": bool(row["own"] or (row["signal"] or 0) >= STRONG_PERCENT),
                    })
        ours = [n["channel"] for n in zigbee] + [t["channel"] for t in thread]
        heard = [
            {**{key: row[key] for key in ("ssid", "mhz", "channel", "band", "signal", "own")},
             # Drawn red: the house's own Wi-Fi, or a neighbour's heard
             # at 50% or more, over a Zigbee or Thread channel.
             "bad": any(covers(row["mhz"], c) for c in ours)
             and bool(row["own"] or (row["signal"] or 0) >= STRONG_PERCENT)}
            for row in rows
        ]
        return {
            "scanned_at": dt_util.utc_from_timestamp(self._air_at).isoformat() if self._air_at else None,
            "scan": self._air_why if self._air is None else "ok",
            "connected": self._air_connected,
            "wifi": heard,
            "zigbee": zigbee,
            "thread": thread,
            "overlaps": overlaps,
        }

    # ------------------------------------------------------ the cards

    def _cost_of(self, key: str) -> int:
        """How many of a Zigbee network's devices show a weak link now:
        a bad signal day, or short drop-outs."""
        members = set(self._network_members().get(key, []))  # type: ignore[attr-defined]
        weak = {row.get("device_id") for row in (self.signal_weak_list or []) if isinstance(row, dict)}  # type: ignore[attr-defined]
        return len([d for d in members if d in weak or self.is_flapping(d)])  # type: ignore[attr-defined]

    def channel_cards(self, key: str) -> list[dict[str, Any]]:
        """The Recommendations for a network's channel (rule REC-13): the
        house's Wi-Fi on a better channel, or a Zigbee network moved
        from under a neighbour's strong Wi-Fi."""
        return self._channel_cards(key)

    def _channel_cards(self, key: str) -> list[dict[str, Any]]:
        """Every channel card for a network."""
        try:
            if key == WIFI_KEY:
                return self._wifi_channel_cards()
            if key in ZIGBEE_STACKS:
                return self._zigbee_channel_cards(key)
        except Exception as err:  # noqa: BLE001 - a card never breaks a page
            LOGGER.debug("device_sentinel: channel card for %s not made: %s", key, err)
        return []

    def _busy(self, rows: list[dict[str, Any]], mhz: int) -> list[dict[str, Any]]:
        """The neighbours' networks a 2.4 GHz Wi-Fi channel at `mhz`
        would share the air with: any whose 22 MHz overlaps it."""
        return [r for r in rows if not r["own"] and r["band"] == "2.4 GHz" and abs(r["mhz"] - mhz) < 22]

    def _crowd(
        self,
        rows: list[dict[str, Any]],
        mhz: int,
        best: int | None,
        now: float,
        kept: dict[str, bool],
    ) -> list[dict[str, Any]]:
        """The neighbours that make the Wi-Fi card's crowd (rules SIG-20, REC-13).

        At 50% or more a card is made. A card made, or one ticked, keeps
        its crowd down to 40%, and below that for a day: the advice is
        the card's, so a router moving itself from channel 4 to 3 keeps
        the same card while the neighbours stay. Held in memory; after a
        restart a ticked card is held from its tick, and an unticked one
        waits for 50% again.
        """
        held = self._wifi_held if self._wifi_held is not None else {}
        self._wifi_held = held
        busy = self._busy(rows, mhz)
        strong = [r for r in busy if (r["signal"] or 0) >= STRONG_PERCENT]
        if best is None:
            return strong
        advice = f"to:{best}:crowded"
        near = [r for r in busy if (r["signal"] or 0) >= HOLD_PERCENT]
        if strong:
            held[advice] = (now, max(strong, key=lambda r: r["signal"] or 0))
            return strong
        if advice not in held:
            ticked = network_ack_ticked(
                kept, WIFI_KEY, {"kind": "channel", "channel": best, "reason": "wifi:0:crowded"}
            )
            if not (ticked and near):
                return []
        if near:
            held[advice] = (now, max(near, key=lambda r: r["signal"] or 0))
            return near
        since, loudest = held[advice]
        if now - since < HOLD_SECONDS:
            # A day under the line before the card goes, told with the
            # neighbour as last heard over it.
            return [loudest]
        held.pop(advice, None)
        return []

    def _wifi_channel_cards(self) -> list[dict[str, Any]]:
        rows = self._air_rows()
        mine = [r for r in rows if r["own"] and r["band"] == "2.4 GHz"]
        if not mine:
            return []
        now = dt_util.utcnow().timestamp()
        kept: dict[str, bool] = self._acks().get("lines") or {}  # type: ignore[attr-defined]
        ours = [n["channel"] for n in self.zigbee_networks()] + [t["channel"] for t in self._thread_channels()]

        def score(mhz: int) -> int:
            return max((r["signal"] or 0 for r in self._busy(rows, mhz)), default=0)

        cards: list[dict[str, Any]] = []
        # A mesh on several channels: the one covering a Zigbee or Thread
        # channel first, then the most crowded, and one card only.
        order = sorted({r["channel"] for r in mine}, key=lambda c: (
            not any(covers(wifi_mhz(c), z) for z in ours), -score(wifi_mhz(c)), c))
        for channel in order:
            if cards:
                break
            mhz = wifi_mhz(channel)
            covered = [c for c in ours if covers(mhz, c)]
            choices = [c for c in WIFI_CHOICES if not any(covers(wifi_mhz(c), z) for z in ours)]
            best = min(choices, key=lambda c: (score(wifi_mhz(c)), c), default=None)
            strong = self._crowd(rows, mhz, best, now, kept)
            if not covered and not strong:
                continue
            # Moving off a Zigbee or Thread channel is the gain on its
            # own; otherwise the new channel must be quieter.
            # A held card is weighed by its crowd as last heard over the line.
            crowd = max([score(mhz), *(r["signal"] or 0 for r in strong)])
            if best is None or best == channel or (not covered and score(wifi_mhz(best)) >= crowd):
                continue
            why = []
            if covered:
                why.append(f"covers your Zigbee or Thread channel {', '.join(str(c) for c in covered)}")
            if strong:
                top = max(strong, key=lambda r: r["signal"] or 0)
                why.append(f"overlaps a neighbour's network on channel {top['channel']}, heard at {top['signal']}%")
            clear = score(wifi_mhz(best))
            sentence = (
                f"Your Wi-Fi on channel {channel} {' and '.join(why)}. If your router lets you choose, "
                f"channel {best} is clearer: it covers none of your Zigbee or Thread channels, and "
                + (f"the strongest network heard near it is at {clear}%." if clear else "no other network is heard near it.")
            )
            cards.append({
                "kind": "channel", "channel": best,
                # What the card is about: a new channel, or a new reason,
                # is a new card, which an earlier tick does not cover
                # (rule REC-07).
                "reason": f"wifi:{channel}:{'covered' if covered else 'crowded'}",
                "sentence": sentence,
                "question": "A mesh router that picks its own channel may change it back. Device Sentinel "
                            "only hears Wi-Fi where your server is.",
            })
        return cards

    def _zigbee_channel_cards(self, key: str) -> list[dict[str, Any]]:
        net = next((n for n in self.zigbee_networks() if n["key"] == key), None)
        if net is None:
            return []
        rows = self._air_rows()
        # The house's own Wi-Fi is the Wi-Fi card's to move, the cheaper fix.
        if any(r["own"] and covers(r["mhz"], net["channel"]) for r in rows):
            return []
        strong = [r for r in rows if not r["own"] and (r["signal"] or 0) >= STRONG_PERCENT and covers(r["mhz"], net["channel"])]
        cost = self._cost_of(key)
        if not strong or not cost:
            return []
        # Never a channel another Zigbee network or Thread already uses.
        others = {n["channel"] for n in self.zigbee_networks() if n["key"] != key}
        others |= {t["channel"] for t in self._thread_channels()}

        def score(channel: int) -> int:
            return max((r["signal"] or 0 for r in rows if covers(r["mhz"], channel)), default=0)

        choices = [c for c in ZIGBEE_CHOICES if c != net["channel"] and c not in others]
        best = min(choices, key=lambda c: (score(c), c), default=None)
        if best is None or score(best) >= STRONG_PERCENT:
            return []
        top = max(strong, key=lambda r: r["signal"] or 0)
        return [{
            "kind": "channel", "channel": best,
            "reason": f"{key}:{net['channel']}",
            "sentence": (
                f"{net['name']} is on channel {net['channel']}, inside a neighbour's Wi-Fi on channel "
                f"{top['channel']}, heard at {top['signal']}%, and {cost} of its devices "
                f"{'has' if cost == 1 else 'have'} a weak link. Channel {best} is clearer."
            ),
            "question": (
                "Changing a Zigbee channel can mean pairing some devices again, and some "
                "coordinators cannot do it. Wake battery devices afterwards so they follow."
            ),
        }]

    def radio_diagnostics(self) -> dict[str, Any]:
        """The radio channels for the download: networks under their
        stand-ins, access points under the address stand-ins."""
        return {
            "scan": self._air_why if self._air is None else "ok",
            "scanned_at": self._air_at,
            "joined": {"ssid": self._air_joined} if self._air_joined else None,
            "heard": [
                {"ssid": r["ssid"], "bssid": r["bssid"], "channel": r["channel"], "band": r["band"],
                 "signal": r["signal"], "own": r["own"]}
                for r in self._air_rows()
            ],
            # Keys and channels only: a network's display name can read
            # as a device's and be taken for one.
            "zigbee": [{"key": n["key"], "channel": n["channel"]} for n in self.zigbee_networks()],
            "thread": self._thread_channels(),
            "cards": {
                key: [{k: c[k] for k in ("kind", "channel", "reason", "sentence")} for c in self._channel_cards(key)]
                for key in (WIFI_KEY, *ZIGBEE_STACKS)
            },
            "acknowledged": sorted(k for k, on in (self._acks().get("lines") or {}).items()  # type: ignore[attr-defined]
                                   if on and k.startswith("net:")),
        }
