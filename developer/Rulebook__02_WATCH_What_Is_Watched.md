# Device Sentinel Rulebook: What Is Watched (WATCH)

*Version: rulebook, 21 November 2026, on Device Sentinel 0.30.0. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

This section covers which devices Device Sentinel watches and what it reads them through. It also covers which devices it sets aside and why, what happens to a device that is removed or taken back, and the quiet first minutes after a start. Excluding and muting, the two choices a person makes, are under [MUTE](Rulebook__03_MUTE_Muting_and_Exclusion.md). What is judged once a device is watched is under [FRZ](Rulebook__05_FRZ_Freeze.md), UNAV, BAT and SIG. The stack readers are under [STACK](Rulebook__08_STACK_Stacks.md).

### WATCH-01 Read Through Home Assistant's Entities

**Device Sentinel reads a device through the entities Home Assistant shows for it. It does not talk to Zigbee, Z-Wave or MQTT directly for a device's own readings (the stack readers, under [STACK](Rulebook__08_STACK_Stacks.md), watch the stacks themselves).**
- **Exceptions:** these are named here and contact nothing. One is a field a core integration already holds, such as ZHA's own Last Seen or a Lutron Caséta hub's connection (see [STACK](Rulebook__08_STACK_Stacks.md)). The other is a Lutron Pico's button press, which counts as the Pico reporting.
- **Switched-off entities:** an entity that is switched off is not read. Device Sentinel switches one on only when an administrator presses for one device, on its page or its Recommendations card (see [REC](Rulebook__15_REC_Recommendations.md)).

*Proof:* [`test_switched_off_sensors.py`](../tests/test_switched_off_sensors.py), [`test_device_actions.py`](../tests/test_device_actions.py), [`test_last_seen_switched_off_clock.py`](../tests/test_last_seen_switched_off_clock.py).

### WATCH-02 Only a Device's Own Entities Speak for It

**An entity another integration adds to a device, as Battery Notes or a helper does, never counts as the device reporting. It never decides whether the device is unavailable.**
- **Where readings come from:** a reading (battery, signal, last seen) is taken from an entity of the device's own integration wherever it has one. Another integration's reading is used only where the device has none of its own.
- **Choosing between several:** a battery or signal reading is chosen by comparison, never by the order the registry lists them. Two Last Seen entities of the same ownership are taken in the registry's order.
- **Diagnostics:** they name the entity chosen and whose it is.

*Proof:* [`test_foreign_entities.py`](../tests/test_foreign_entities.py), [`test_own_platform.py`](../tests/test_own_platform.py), [`test_signal_own_first.py`](../tests/test_signal_own_first.py).

### WATCH-03 Set Aside

**A device that is set aside is never judged or reported. It keeps its record unless it was excluded.**
- **The reason shown:** the Devices tab's Set aside chip and classification.md give one reason, the first that fits in this order: excluded (see [MUTE](Rulebook__03_MUTE_Muting_and_Exclusion.md)), service, disabled, duplicate coordinator, clone, nothing switched on that can report, no entities.
- **Service:** a device Home Assistant marks as one, such as an add-on.
- **Disabled:** a device disabled by a person, by its integration or with its config entry.
- **No entities:** the device has no entities of its own that could report (firmware notices and buttons do not count, switched on or off). So it is never judged never reported.
- **All switched off:** a device whose entities exist but are all switched off is not set aside. It stays watched, and its never-reported row is the prompt to switch them on.

*Proof:* [`test_set_aside.py`](../tests/test_set_aside.py), [`test_classification.py`](../tests/test_classification.py), [`test_set_aside_verdict.py`](../tests/test_set_aside_verdict.py), [`test_set_aside_left_out.py`](../tests/test_set_aside_left_out.py).

### WATCH-04 Notices and Buttons Are Never the Device

**A firmware update notice, a command button, the Hue bridge's Zigbee connectivity sensor, the Z-Wave node status and a Lightwave device's Connectivity sensor never count as the device reporting.**
- **The exceptions:** a Z-Wave node status that changes from dead to alive or awake, with nothing else heard from the device, counts as contact, and so does a Lightwave Connectivity sensor that turns on after off ([STACK-16](Rulebook__08_STACK_Stacks.md#stack-16-lightwave-devices-and-their-connectivity-sensor)).
- **Nothing else switched on:** a device with nothing but notices, buttons or the Hue connectivity sensor switched on is set aside, "Set aside: nothing switched on that can report". An ESPHome device is the exception, judged by its connection ("Judged by its connection: connected."), and so is a Lutron Pico, judged by its hub.
- **Z-Wave node status alone:** a Z-Wave device whose only switched-on entity is its node status is not set aside. It stays watched and is judged by its clock.
- **Everything switched off:** a device with everything switched off and nothing on stays watched (see [WATCH-03](#watch-03-set-aside)).
- **On the integration:** an integration whose set-aside devices all have nothing to read reads "Nothing switched on to read".

*Proof:* [`test_never_the_device.py`](../tests/test_never_the_device.py), [`test_esphome_connection.py`](../tests/test_esphome_connection.py), [`test_dead_node_recovery.py`](../tests/test_dead_node_recovery.py).

### WATCH-05 A Coordinator Listed Twice

**A coordinator that also appears in the registry as an ordinary device is set aside as a duplicate coordinator, so it is watched once, through its own stack. Today that is the Zigbee2MQTT bridge, which reaches the registry as an MQTT device. Each stack answers for its own.**

*Proof:* [`test_stacks.py`](../tests/test_stacks.py), [`test_classification.py`](../tests/test_classification.py).

### WATCH-06 Hardware Listed by Several Integrations

**Device Sentinel treats two devices as one piece of hardware only when they match as set out below, never by name. Two devices of one integration are never matched, so a hub and its child stay apart.**
- **What makes a match:** devices of different integrations hold the same network or Bluetooth address, or one's identifier holds the other's address, or a Bluetooth integration's device points at its proxy.
- **Which one is watched:** one is chosen in this order: switched-on entities of its own, no device tracker of its own, an address recorded on the device itself (a copy joined only through its identifier ranks below it), a battery reading, the most direct connection, the most entities, the lowest id.
- **The others:** they are set aside as clones and keep their records. They come back with their history if the group parts.
- **No entities:** a device with no entities is never kept or set aside as a clone.
- **On screen:** the watched device's page names each clone in a Same hardware row, with its integration named as the rest of the page names it ("UniFi Network"). The device page, the Devices tab and classification.md call such a device a clone.

*Proof:* [`test_hardware_copies.py`](../tests/test_hardware_copies.py), `check_same_hardware.js`.

### WATCH-07 A Removed Device Is Held 30 Days

**When a device is removed from Home Assistant, Device Sentinel holds its record, its power and type answers and its mutes for 30 days. An excluded device that is removed is not held.**
- **If it comes back:** if Home Assistant gives the same device id back, as it does when the same integration adds the same hardware again, all of it returns. The gap across the absence is not learned, and the battery follows the replacement rule (see [BAT](Rulebook__09_BAT_Battery.md)). The signal history starts over unless the device returns before the next local midnight.
- **While held:** the device is never judged, listed or shown as a page. Its leaving is told once as "removed from Home Assistant".
- **After 30 days:** the midnight after 30 days deletes the record and its answers.

*Proof:* [`test_removed_hold.py`](../tests/test_removed_hold.py), [`test_answers_store.py`](../tests/test_answers_store.py).

### WATCH-08 A Device Taken Back

**A device taken back from being disabled, excluded or removed is judged only from the moment it is watched again. The time nobody watched it is not its silence.**
- **The return date:** it is dated once, as it happens, and kept. A later settings change, a restart or an upgrade never dates it again.
- **Each stretch:** each stretch set aside is read on its own. A device already past its window when it was set aside reads frozen again at once.
- **Outages:** while a device is set aside its outage is not followed, and its return reads it afresh.
- **Down for:** its "down for" counts from its return, or from the opening for one that came back already past its window.

*Proof:* [`test_unwatched_time.py`](../tests/test_unwatched_time.py), [`test_unwatched_time_cases.py`](../tests/test_unwatched_time_cases.py), [`test_exclusions.py`](../tests/test_exclusions.py).

### WATCH-09 Lists Show Watched Devices Only

**Each list, report, sensor and count that walks devices reads only the watched devices. So a device set aside or excluded never reaches the Problem List, the brief or a trend. The exceptions are the Devices tab's Excluded and Set aside chips and classification.md, which exist to show them.**

*Proof:* [`test_ignored_integrations.py`](../tests/test_ignored_integrations.py), [`test_removed_hold.py`](../tests/test_removed_hold.py), [`test_set_aside_left_out.py`](../tests/test_set_aside_left_out.py).

### WATCH-10 The Startup Grace

**For the first five minutes after a start, nothing is judged, pushed or announced: no new verdict, no phone push, no Repair card.**
- **Events on the bus:** none, except two. One is a device's withdrawal, so a device removed or set aside while Home Assistant was stopped still closes the fault an automation paired with it. The other is the restored half owed to a stack outage announced before the restart and still open across it (see [UP](Rulebook__07_UP_Upstream_Outages.md)).
- **A device that reports:** a device that really reports inside the grace leaves its verdict and the Problem List at once. Its recovery event is held and sent when the grace closes, so an automation paired with the fault still hears it end.
- **When the grace closes:** Device Sentinel reads the registry again and sets aside what has nothing to report. The first sweep applies what is still true, once.
- **Never reported:** a device first seen silent inside the grace is not listed never reported until the grace closes. One already listed before the restart stays.
- **Stack outages:** an outage of a stack still standing when the grace closes is announced then, with the moment it began. One that came and went inside the grace says nothing.

*Proof:* [`test_set_aside_silent.py`](../tests/test_set_aside_silent.py), [`test_notifications.py`](../tests/test_notifications.py), [`test_upstream_reporting.py`](../tests/test_upstream_reporting.py), [`test_restart_handback.py`](../tests/test_restart_handback.py), [`test_outage_pairs_and_counts.py`](../tests/test_outage_pairs_and_counts.py).

### WATCH-11 Registry Changes

**A change to Home Assistant's devices, entities or labels is read at once when nothing was read in the last 2 seconds, and otherwise within 2 seconds. So a burst of changes is read at once and once more after it ends. A removed device that was muted is named in the log at once, since nothing else keeps its name once it is gone.**

*Proof:* [`test_registry_bursts.py`](../tests/test_registry_bursts.py), [`test_stale_picks.py`](../tests/test_stale_picks.py).

### WATCH-12 A Value Handed Back at a Start

**After a restart or a reload, a value from a device on the list of integrations and models that report cached values is not the device speaking; a value from any other device is (since 0.29.1, issue #36).** Before 0.29.1 the rule ran the other way: every device was distrusted except those on a short list of integrations known to behave, and a working device that came back with the values it had stayed listed for good.
- **Scope:** only a device with no last seen. A device with a Last Seen entity, a ZHA device, whose stack keeps that clock, and a Z-Wave JS device are judged by last seen and never by the list. Z-Wave JS has a Last Seen sensor on every node, switched off as it ships, and Device Sentinel asks for it ([REC-05](Rulebook__15_REC_Recommendations.md#rec-05-switched-off-sensors)).
- **The list:** the integrations that report cached values as a whole, each because its code shows it, with the reason for each in [`docs/TRUSTED_INTEGRATIONS.md`](../docs/TRUSTED_INTEGRATIONS.md); a test keeps the file and the code in step. An integration where only some models do it is not on the list. MQTT is not on it. Since 0.29.2 it holds 23: RFXtrx, EnOcean and four Bluetooth scale integrations (LeaOne, OKOK Scale, EufyLife, Acaia) joined the first 17. Since 0.29.3 it holds 31: Danfoss Link, Drayton Wiser, Easee, Navimow, NaviMower, SNMP Printer, Node-RED and FlightRadar24 joined (James, 15 November 2026, 19:18).
- **Device Sentinel's models (since 0.29.2):** a list of makes and models that report cached values in integrations that otherwise report live, each by manufacturer, model and model ID exactly as its integration writes them: Shelly's first-generation devices that sleep, and the Govee and Xiaomi Bluetooth models their libraries mark as sleepy. Each is there because the integration's code or library marks it, with the reason, how sure we are and whether it has been seen on a real house in [`docs/UNTRUSTED_DEVICES.md`](../docs/UNTRUSTED_DEVICES.md), with every model checked and left off; a test keeps the file and the code in step. A model on it is read as reporting cached values unless a person sets it otherwise. Ruled by James, 15 November 2026, 10:40 and 10:52: a model goes on with a preponderance of evidence, and live data is watched from there.
- **The person's changes:** the Advanced settings screen lists the integrations in the house that the list can apply to, ours ticked: one with at least one watched device in scope (since 0.29.2; James, 15 November 2026, 10:40), and any the person added. An integration whose watched devices all have a Last Seen is not offered, since ticking it would change nothing. A stored change that is not a list of names, as a settings entry edited by hand can hold, reads as no change, and the list is still read. What a person ticks or unticks is saved apart from our list, so an integration added to ours in a later release still reaches them. A change takes effect at once: a device waiting on an unticked integration is judged on what it shows.
- **A model's own setting:** set from a device's page, for every device of its make and model, to report live or to report cached values. It overrides Device Sentinel's models and the integration's setting. The first choice goes back to Device Sentinel's setting: it reads "Same as" the integration, or "Device Sentinel's Setting" for a model on Device Sentinel's list. A device that names no make and model follows its integration. Kept in the answers file ([STOR-20](Rulebook__18_STOR_Storage.md)).
- **Values kept:** a device in scope with a standing verdict (frozen, unavailable or never reported) keeps the last good value of each of its own entities from the moment the verdict starts until it ends.
- **On the list, on watch:** after a restart, a reload, or an entity being added again, each of those entities is on watch. Its stored value coming back is the integration's cached value, and the same value written again does not count. Only a different value is the device speaking, and it ends the watch. An unavailable device's cached value reads as not known yet, so its verdict holds, and its stack calling it available is not enough.
- **Not on the list:** the device is taken at its word. A value arriving, even the same value as before, is the device speaking: a listed device is back, and a working device's clock moves. With no value arriving, nothing changes. Two things are kept apart from the list. A value an MQTT device writes back while its broker or its Zigbee2MQTT bridge is down or just back is the broker's copy ([UNAV-05](Rulebook__06_UNAV_Unavailable.md#unav-05-a-return-through-a-restart)). And a ZHA device whose stack clock cannot be read is not taken at its word, since ZHA restores each entity's last state ([STACK-04](Rulebook__08_STACK_Stacks.md)).
- **Still listed with its values back:** a device on the list in that state shows the note "Back after a restart?" on its page, with how often it has happened to it and to others of its model. "It's Back" clears it as a recovery a person confirmed: its clock starts again, the alert and the Daily Brief say who confirmed it, and the stored cause is "confirmed working". "It's Back, This Model Reports Live" also sets the model.
- **Back, then frozen unchanged:** a device not on the list that came back across a restart showing exactly the values it had is remembered. If it is then listed frozen with none of those values changed, its page shows "Frozen since a restart?", with the count and a button that sets its model to report cached values. A changed value, or any other verdict, ends the memory.
- **Counted:** each case and each press is recorded by device and by model, kept as long as How Much History to Keep, and given in the diagnostics download. Two presses of It's Back on a model offer "Models That May Report Live" on the Recommendations tab; three cases of back-then-frozen on at least two restarts offer "Models That May Report Cached Values" ([REC-04](Rulebook__15_REC_Recommendations.md#rec-04-the-device-cards)). Both numbers are first values, to be tuned from real houses.
- **Entities that never take part:** entities that do not come from the device. These are those another integration or Home Assistant adds, firmware updates, buttons and other commands, the stack's own status, and timestamp and duration sensors, whose values are worked out again at each start.

*Proof:* [`test_cached_values_after_restart.py`](../tests/test_cached_values_after_restart.py), [`test_cached_value_models.py`](../tests/test_cached_value_models.py), [`test_cached_values_dashboard.py`](../tests/test_cached_values_dashboard.py), [`test_trusted_integrations_file.py`](../tests/test_trusted_integrations_file.py), [`test_boot_handback.py`](../tests/test_boot_handback.py), [`test_held_values_storage.py`](../tests/test_held_values_storage.py), [`test_polled_device_returns.py`](../tests/test_polled_device_returns.py), [`tools/panel_checks/check_after_a_restart.js`](../tools/panel_checks/check_after_a_restart.js).
