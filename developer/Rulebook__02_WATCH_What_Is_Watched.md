# Device Sentinel Rulebook: What Is Watched (WATCH)

*Version: rulebook, 28 October 2026, on Device Sentinel 0.27.13. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

Which devices Device Sentinel watches, what it reads them through, which it sets aside and why, what happens to a device that is removed or taken back, and the quiet first minutes after a start. Excluding and muting, the two choices a person makes, are under [MUTE](Rulebook__03_MUTE_Muting_and_Exclusion.md). What is judged once a device is watched is under [FRZ](Rulebook__05_FRZ_Freeze.md), UNAV, BAT and SIG; the stack readers are under [STACK](Rulebook__08_STACK_Stacks.md).

### WATCH-01 Read Through Home Assistant's Entities

**A device is read through the entities Home Assistant shows for it; Device Sentinel does not talk to Zigbee, Z-Wave or MQTT directly for a device's own readings (the stack readers, under [STACK](Rulebook__08_STACK_Stacks.md), watch the stacks themselves). The exceptions are named here and contact nothing: one field a core integration already holds, such as ZHA's own Last Seen or a Lutron Caséta hub's connection (see [STACK](Rulebook__08_STACK_Stacks.md)), and a Lutron Pico's button press, which counts as the Pico reporting. An entity that is switched off is not read. Device Sentinel switches one on only when an administrator presses for one device, on its page or its Recommendations card (see [REC](Rulebook__15_REC_Recommendations.md)).**

*Proof:* [`test_switched_off_sensors.py`](../tests/test_switched_off_sensors.py), [`test_device_actions.py`](../tests/test_device_actions.py), [`test_last_seen_switched_off_clock.py`](../tests/test_last_seen_switched_off_clock.py).

### WATCH-02 Only a Device's Own Entities Speak for It

**An entity another integration adds to a device, as Battery Notes or a helper does, never counts as the device reporting and never decides whether it is unavailable. A reading (battery, signal, last seen) is taken from an entity of the device's own integration wherever it has one. Another integration's reading is used only where the device has none of its own, and a battery or signal reading is chosen by comparison, never by the order the registry lists them, while two Last Seen entities of the same ownership are taken in the registry's order; the diagnostics name the entity chosen and whose it is.**

*Proof:* [`test_foreign_entities.py`](../tests/test_foreign_entities.py), [`test_own_platform.py`](../tests/test_own_platform.py), [`test_signal_own_first.py`](../tests/test_signal_own_first.py).

### WATCH-03 Set Aside

**A device that is set aside is never judged or reported, and keeps its record unless it was excluded. The Classification tab gives one reason, the first that fits in this order: excluded (see [MUTE](Rulebook__03_MUTE_Muting_and_Exclusion.md)), service, disabled, duplicate coordinator, clone, nothing switched on that can report, no entities. A service is a device Home Assistant marks as one, such as an add-on. A disabled device is one disabled by a person, by its integration or with its config entry. No entities means no entities of its own that could report (firmware notices and buttons do not count, switched on or off), so it is never judged never reported. A device whose entities exist but are all switched off is not set aside: it stays watched, and its never-reported row is the prompt to switch them on.**

*Proof:* [`test_set_aside.py`](../tests/test_set_aside.py), [`test_classification.py`](../tests/test_classification.py), [`test_set_aside_verdict.py`](../tests/test_set_aside_verdict.py), [`test_set_aside_left_out.py`](../tests/test_set_aside_left_out.py).

### WATCH-04 Notices and Buttons Are Never the Device

**A firmware update notice, a command button, the Hue bridge's Zigbee connectivity sensor and the Z-Wave node status never count as the device reporting, with one exception: a Z-Wave node status that changes from dead to alive or awake, with nothing else heard from the device, counts as contact. A device with nothing but notices, buttons or the Hue connectivity sensor switched on is set aside, "Set aside: nothing switched on that can report", except an ESPHome device, judged by its connection ("Judged by its connection: connected."), and a Lutron Pico, judged by its hub. A Z-Wave device whose only switched-on entity is its node status is not set aside: it stays watched and is judged by its clock. A device with everything switched off and nothing on stays watched (see [WATCH-03](#watch-03-set-aside)). An integration whose set-aside devices all have nothing to read reads "Nothing switched on to read".**

*Proof:* [`test_never_the_device.py`](../tests/test_never_the_device.py), [`test_esphome_connection.py`](../tests/test_esphome_connection.py), [`test_dead_node_recovery.py`](../tests/test_dead_node_recovery.py).

### WATCH-05 A Coordinator Listed Twice

**A coordinator that also appears in the registry as an ordinary device is set aside as a duplicate coordinator, so it is watched once, through its own stack. Today that is the Zigbee2MQTT bridge, which reaches the registry as an MQTT device; each stack answers for its own.**

*Proof:* [`test_stacks.py`](../tests/test_stacks.py), [`test_classification.py`](../tests/test_classification.py).

### WATCH-06 Hardware Listed by Several Integrations

**Two devices are one piece of hardware only when devices of different integrations hold the same network or Bluetooth address, or one's identifier holds the other's address, or a Bluetooth integration's device points at its proxy. Never by name, and never two devices of one integration, so a hub and its child stay apart. One is watched, chosen in this order: switched-on entities of its own, no device tracker of its own, an address recorded on the device itself (a copy joined only through its identifier ranks below it), a battery reading, the most direct connection, the most entities, the lowest id. The others are set aside as clones and keep their records, and come back with their history if the group parts. A device with no entities is never kept or set aside as a clone. The watched device's page names each clone in a Same hardware row, with its integration named as the rest of the page names it ("UniFi Network"). The device page and the Classification tab call such a device a clone.**

*Proof:* [`test_hardware_copies.py`](../tests/test_hardware_copies.py), `check_same_hardware.js`.

### WATCH-07 A Removed Device Is Held 30 Days

**When a device is removed from Home Assistant, Device Sentinel holds its record, its power and type answers and its mutes for 30 days. If Home Assistant gives the same device id back, as it does when the same integration adds the same hardware again, all of it returns: the gap across the absence is not learned, the battery follows the replacement rule (see [BAT](Rulebook__09_BAT_Battery.md)), and the signal history starts over unless the device returns before the next local midnight. A held device is never judged, listed or shown as a page; its leaving is told once as "removed from Home Assistant". The midnight after 30 days deletes the record and its answers. An excluded device that is removed is not held.**

*Proof:* [`test_removed_hold.py`](../tests/test_removed_hold.py), [`test_answers_store.py`](../tests/test_answers_store.py).

### WATCH-08 A Device Taken Back

**A device taken back from being disabled, excluded or removed is judged only from the moment it is watched again, so the time nobody watched it is not its silence. The return is dated once, as it happens, and kept; a later settings change, a restart or an upgrade never dates it again. Each stretch set aside is read on its own, and a device already past its window when it was set aside reads frozen again at once. While a device is set aside its outage is not followed, and its return reads it afresh. Its "down for" counts from its return, or from the opening for one that came back already past its window.**

*Proof:* [`test_unwatched_time.py`](../tests/test_unwatched_time.py), [`test_unwatched_time_cases.py`](../tests/test_unwatched_time_cases.py), [`test_exclusions.py`](../tests/test_exclusions.py).

### WATCH-09 Lists Show Watched Devices Only

**Each list, report, sensor and count that walks devices reads the watched devices only, so a device set aside or excluded never reaches the Problem List, the brief or a trend. The Classification tab and the Excluded list, which exist to show them, are the exceptions.**

*Proof:* [`test_ignored_integrations.py`](../tests/test_ignored_integrations.py), [`test_removed_hold.py`](../tests/test_removed_hold.py), [`test_set_aside_left_out.py`](../tests/test_set_aside_left_out.py).

### WATCH-10 The Startup Grace

**For the first five minutes after a start, nothing is judged, pushed or announced: no new verdict, no phone push, no Repair card, and no event on the bus except two: a device's withdrawal, so a device removed or set aside while Home Assistant was stopped still closes the fault an automation paired with it, and the restored half owed to a stack outage announced before the restart and still open across it (see [UP](Rulebook__07_UP_Upstream_Outages.md)). A device that really reports inside the grace leaves its verdict and the Problem List at once; its recovery event is held and sent when the grace closes, so an automation paired with the fault still hears it end. When the grace closes, Device Sentinel reads the registry again, sets aside what has nothing to report, and the first sweep applies what is still true, once. A device first seen silent inside the grace is not listed never reported until it closes; one already listed before the restart stays. An outage of a stack still standing when the grace closes is announced then, with the moment it began; one that came and went inside the grace says nothing.**

*Proof:* [`test_set_aside_silent.py`](../tests/test_set_aside_silent.py), [`test_notifications.py`](../tests/test_notifications.py), [`test_upstream_reporting.py`](../tests/test_upstream_reporting.py), [`test_restart_handback.py`](../tests/test_restart_handback.py), [`test_outage_pairs_and_counts.py`](../tests/test_outage_pairs_and_counts.py).

### WATCH-11 Registry Changes

**A change to Home Assistant's devices, entities or labels is read at once when nothing was read in the last 2 seconds, and otherwise within 2 seconds, so a burst of changes is read at once and once more after it ends. A removed device that was muted is named in the log at once, since nothing else keeps its name once it is gone.**

*Proof:* [`test_registry_bursts.py`](../tests/test_registry_bursts.py), [`test_stale_picks.py`](../tests/test_stale_picks.py).

### WATCH-12 A Value Handed Back at a Start

**A device with a standing verdict (frozen, unavailable or never reported) keeps the last good value of each of its own entities from the moment the verdict starts until it recovers, unless it has a Last Seen clock, is on ZHA, or is on an integration that fetches its readings from the device: ESPHome and HomeKit Device, which ask as they connect, and the integrations that poll a printer, a NAS or a UPS on the local network and restore nothing at a start (brother, ipp, nut, apcupsd, synology_dsm, qnap and glances). A poller that restores its last value at a start, as Modbus does, or reads a hub's own record of its devices, is not one of them. After a restart, a reload, or an entity being added again, each of those entities is on watch. Its stored value coming back is the integration handing back what it held, not the device reporting, and the same value written again does not count either. Only a value different from the stored one is the device speaking, and it clears the watch. An unavailable device's handed-back value reads as not known yet, so its verdict holds: its stack calling it available is not enough. Entities that do not come from the device never take part: those another integration or Home Assistant adds, firmware updates, buttons and other commands, the stack's own status, and timestamp and duration sensors, whose values are worked out again at each start.**

*Proof:* [`test_boot_handback.py`](../tests/test_boot_handback.py), [`test_held_values_storage.py`](../tests/test_held_values_storage.py), [`test_polled_device_returns.py`](../tests/test_polled_device_returns.py).
