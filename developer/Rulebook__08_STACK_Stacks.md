# Device Sentinel Rulebook: Stacks (STACK)

*Version: rulebook, 28 October 2026, on Device Sentinel 0.27.13. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

What Device Sentinel knows about each radio stack and hub a house runs, and what it reads from each: Zigbee2MQTT, ZHA, Z-Wave, Matter and Thread, Lutron Caséta hubs and ESPHome. It also covers when an integration's private state may be read, Extended Diagnostics and its probe file, and what Device Sentinel never sends to a stack. A stack going down and coming back is under [UP](Rulebook__07_UP_Upstream_Outages.md). Frozen and unavailable in general are under [FRZ](Rulebook__05_FRZ_Freeze.md) and UNAV; mutes, including a hub's, are under [MUTE](Rulebook__03_MUTE_Muting_and_Exclusion.md).

### STACK-01 Which Stacks a House Runs

**Device Sentinel finds which stacks a house runs from its own device registry, never by asking: ZHA, Z-Wave and Matter by their integration's domain, Zigbee2MQTT by its bridge device and never by the mqtt domain it shares. It is worked out again at each registry rebuild and never saved, so adding or removing a stack needs nothing. Each stack's knowledge lives in a file of its own, so adding a stack touches that file and one line.**

*Proof:* [`test_stacks.py`](../tests/test_stacks.py).

### STACK-02 Hardware the Author Does Not Own

**A stack is supported only once it can be tested: on the author's own hardware, or marked experimental when it is built from a tester's recorded data and simulated in the test container with its Home Assistant integration installed and its hardware faked. Stacks are added one per release, in the order of how complete the data in hand is. Each stack still being built for has a wiki page saying what is known, what is not, the exact commands to run, each run on the reference house first, and the questions whose answers decide the design. Captures that name no device are asked for in a public issue; a full diagnostics download is asked for privately, with the page saying what is inside. A tool built to answer one question from inside Home Assistant is its own throwaway integration, never shipped inside a feature, and changes nothing; it summarises bursts, names only the device it means, watches the config entry and never writes from the event loop.**

*Proof:* none; this rule is a procedure, checked when a stack is added.

### STACK-03 Zigbee2MQTT

**Device Sentinel reads Zigbee2MQTT's bridge from its own retained topics under the base topic zigbee2mqtt. MQTT is a soft dependency, so a house without it still loads, and the reader asks whether MQTT is loaded before it waits for it. Each detected stack that has a reader, Zigbee2MQTT and ZHA, gets a Bridge sensor that reads running, binding, down or unknown and is switched on at install, since it exists only where its stack was found (see [CFG](Rulebook__17_CFG_Settings.md)); Z-Wave and Matter are detected but have no reader and no Bridge sensor. Detection works whether or not the sensor is on. The sensor shows whether Zigbee2MQTT's availability setting is on, and Device Sentinel never changes it; where it is off, a line on the Recommendations tab says what turning it on gives. Zigbee2MQTT's own view of a device confirms or doubts a freeze verdict and never decides one: it is matched through the bridge's device list, never by name; a topic with no device in that list answers nothing; an online reading never lifts a verdict; and the timeout for the device's power class, read from the bridge, goes with the reading wherever it is shown, on the Problem List item and in the Daily Brief, never on the phone.**

*Proof:* [`test_bridge_pairing.py`](../tests/test_bridge_pairing.py), [`test_maintenance.py`](../tests/test_maintenance.py), [`test_reachability.py`](../tests/test_reachability.py), [`test_recommendations.py`](../tests/test_recommendations.py), [`test_manifest_dependencies.py`](../tests/test_manifest_dependencies.py).

### STACK-04 ZHA

**For a ZHA device, Device Sentinel reads the time ZHA last heard it, which ZHA sets from each radio message (under [STACK-08](#stack-08-reading-an-integrations-private-state)). It decides one thing: a value handed back after a ZHA restart or reload is the device speaking only if ZHA has heard the device since its last report. It does not date contact or start a new device's clock. In Advanced, the device page names it on the Last seen sensor row: "ZHA's own", "heartbeat: when ZHA last heard it"; Simple shows that row only when the sensor is switched off. Zigbee2MQTT and Z-Wave JS devices have their own Last Seen entities, which, once switched on, also date contact and start a new device's clock. ZHA's coordinator is watched as an upstream through its config entry (see [UP](Rulebook__07_UP_Upstream_Outages.md)).**

*Proof:* [`test_zha_last_seen.py`](../tests/test_zha_last_seen.py), [`test_zha_reader.py`](../tests/test_zha_reader.py).

### STACK-05 Z-Wave

**For each watched Z-Wave device, Device Sentinel reads its Z-Wave status sensor. "dead" makes the device unavailable, dated from the change and kept through a restart or a reload, and values written while it reads dead are not the device speaking. "alive" or "awake" after dead is the device heard and counts as contact, a restart included, since Z-Wave JS marks a node alive only when it answers. Otherwise the status is never a report: it stamps no clock and teaches no rhythm. A device whose status sensor is its only enabled entity is judged by the clock while the node reads up. Z-Wave marks a node dead only when a command to it fails, so for a device nobody tries to reach, the freeze window stays the backstop. The device page carries a Z-Wave status row under Last seen sensor: alive, asleep, awake, dead or "not known yet", or "switched off" with a Turn it on button; Simple shows it only when the node is dead or its sensor is switched off. A device whose status sensor is switched off is listed on the Z-Wave Status Switched Off card (REC). Switching the status sensor off while the node reads dead can be read as the device recovering.**

*Proof:* [`test_zwave_dead_node.py`](../tests/test_zwave_dead_node.py), [`test_dead_node_recovery.py`](../tests/test_dead_node_recovery.py), [`test_dead_node_outage_dates.py`](../tests/test_dead_node_outage_dates.py), [`tools/panel_checks/check_node_status.js`](../tools/panel_checks/check_node_status.js).

### STACK-06 Matter and Thread

**There is no Matter device reader. A Matter device not behind a bridge whose type reports only on use (Appliance, Button, Cover, Fan, Light, Lock, Matter Bridge, Plug, Siren, Switch, Vacuum or Valve) is never newly judged frozen while any of its entities reads available, whatever powers it. A sensor, and any other type, keeps the freeze rule, and so does a device that measures something, unless its owner set the type. A frozen verdict already standing stays until the device reports, and unavailable is judged as before. While it is spared, its page reads "Not called frozen while Home Assistant shows it available." and the Slow Reporting Devices card leaves it off. The upstream to build next is the Thread network: one problem when each border router carrying it is gone, from measured timings.**

*Proof:* [`test_matter_awake.py`](../tests/test_matter_awake.py), [`tools/panel_checks/check_device_page_text.js`](../tools/panel_checks/check_device_page_text.js).

### STACK-07 ESPHome

**An ESPHome device that does not deep-sleep is never newly judged frozen while Home Assistant's connection to it is up, whatever its entities read ([FRZ-07](Rulebook__05_FRZ_Freeze.md#frz-07-a-device-is-frozen)). Device Sentinel reads ESPHome's own deep-sleep and connection flags (under [STACK-08](#stack-08-reading-an-integrations-private-state)): a device that does not deep-sleep and whose connection is down is unavailable within a few minutes, whatever its Status sensor shows, and a frozen verdict standing moves to unavailable on the same item. A value written while it is disconnected, such as the Status sensor turning off, is not the device speaking, and the time it spent off the network is not learned. A device that deep-sleeps keeps the freeze rule, and so does one whose flags cannot be read.**

*Proof:* [`test_esphome_connection.py`](../tests/test_esphome_connection.py), [`test_freeze.py`](../tests/test_freeze.py), [`test_recommendations.py`](../tests/test_recommendations.py).

### STACK-08 Reading an Integration's Private State

**Detection reads an integration's private state only where a rule names the integration and the one field. Each read is wrapped, so a missing field, a changed shape or any failure leaves the device on the ordinary rules and logs one line: a Home Assistant update that moves the field costs the exception, never a start, a verdict or a save. Such an integration is named in the manifest's after_dependencies, never its dependencies, and nothing is imported from an integration read this way. The wiki lists each exception and its field. Three integrations are read this way: ESPHome (deep sleep and connection), ZHA (when it last heard a device) and Lutron Caséta (the hub's session). Matter, Thread and Z-Wave JS are weighed against their probe data as it arrives. Extended Diagnostics may also read private state, since it records and never judges.**

*Proof:* [`test_manifest_dependencies.py`](../tests/test_manifest_dependencies.py), [`test_freeze.py`](../tests/test_freeze.py), [`test_zha_last_seen.py`](../tests/test_zha_last_seen.py), [`test_lutron_hub.py`](../tests/test_lutron_hub.py).

### STACK-09 Lutron Hubs

**Lutron Caséta is supported, marked experimental. Device Sentinel reads whether each hub is connected from the session its library holds, once a minute, and sends nothing to the hub. A hub read as not connected on two checks 55 seconds or more apart is down, dated from when it was first seen gone; a hub whose integration failed to set up is not connected; one whose integration is not loaded, or whose session cannot be read, gives no opinion. A hub is judged by its connection, and each device registered through it by the hub: never frozen and never "never reported", since Lutron reports a device only when someone uses it. A watched hub that is down is one row on the Problem List, and the devices it controls keep their verdicts and are listed on its page until it is back. A Pico press counts as the Pico reporting. Unknown counts as nothing. A device whose entities read unavailable, leaving aside any that read unknown, is unavailable. A device whose entities all read unknown gets no new verdict and keeps one already standing. A watched hub owns its integration entry; a hub that is not watched is judged by nothing, and its entry is left to the integration outage rule (UP). A hub's mute covers the devices it controls, mute by mute, and a device's own mute stands; a hub muted for freeze is still reported when it goes down (see [MUTE](Rulebook__03_MUTE_Muting_and_Exclusion.md)).**

*Proof:* [`test_lutron_hub.py`](../tests/test_lutron_hub.py), [`test_lutron_campaign.py`](../tests/test_lutron_campaign.py).

### STACK-10 What a Hub's Rows and Pages Say

**The Problem List reads "Hub down, 2 devices that it controls", with "Down since 1:28 PM. The 2 devices it controls are listed on its page, not on the Problem List, until it is back." The notification card reads "Garage Lutron Caseta hub down, 2 devices that it controls"; the Daily Brief says a hub "went down" and "has been down", and lists a hub that is down as "hub down, 2 devices that it controls". A hub's page shows Up or Down with when, how it is judged, Devices This Hub Controls (DEVICE, TYPE, STANDING, LAST SEEN, PROBLEM) and its outages over 14 days (WENT DOWN, BACK, DOWN FOR, DEVICES IT CONTROLS), with no Last seen group. A controlled device's page reads "Judged by its hub", links the hub and says why its silence cannot be judged; while the hub's connection cannot be read it says "Device Sentinel cannot read {Hub}'s connection right now." A device muted with its hub reads "Muted with its hub" on the hub's page and "Freeze is muted with its hub. Change it on {Hub}'s page." on its own. The TYPE column shows Device Sentinel's type.**

*Proof:* [`tools/panel_checks/check_hub_pages.js`](../tools/panel_checks/check_hub_pages.js), [`test_lutron_campaign.py`](../tests/test_lutron_campaign.py), [`test_lutron_hub.py`](../tests/test_lutron_hub.py).

### STACK-11 Extended Diagnostics

**Extended Diagnostics offers one switch for each integration or stack in the house that support is still being built for. Turning one on gathers for that integration only, into the diagnostics download the person attaches to an issue; nothing is sent anywhere. Turning it off stops the gathering. The shapes it gathered are dropped at the next midnight fold. Lines already written to the probe file stay until they roll out ([STACK-12](#stack-12-the-stack-probe-file)). A stack whose support is built may stay on the list, so its data can be gathered if trouble comes. The routers (UniFi, FRITZ!Box, AsusWRT, NETGEAR and MikroTik), Z-Wave, Matter, Hue, SmartThings, Tuya and Lutron Caséta are offered; HomeKit Device and deCONZ are not, and Shelly needs nothing. Hue and SmartThings are read by sampling only, once a minute from memory, beside Device Sentinel's own record of each device's state changes, with no callback added to either library, so a change shorter than a minute can be missed; nothing judges from them until a house with them has sent its data. SmartThings and Tuya are there for a cloud outage: once each has recorded a real one, one rule for cloud integrations is built from them and those probes retire. Extended Diagnostics records and never judges, and whatever a studied library does, Device Sentinel goes on judging, listing, saving and folding.**

*Proof:* [`test_study.py`](../tests/test_study.py), [`test_stack_probes_hubs.py`](../tests/test_stack_probes_hubs.py), [`test_hue_smartthings_probe.py`](../tests/test_hue_smartthings_probe.py), [`test_probe_guard.py`](../tests/test_probe_guard.py), [`test_lutron_study_gating.py`](../tests/test_lutron_study_gating.py).

### STACK-12 The Stack Probe File

**Each studied stack writes its lines to one file, stack_probe.md, rolled at 1 MB to .1, .2 and .3. Each Z-Wave and Matter line names the node's device beside its node id, with Device Sentinel's own view of the device beside the stack's. The Z-Wave probe records node events as they arrive, each device's route and its changes, and one controller health line a day; its Device Sentinel column says muted, set aside or learning where that is true. The Matter probe records each Thread border router appearing and disappearing, with its network name and ID, each Thread device's network ID, and which Matter Wi-Fi devices were away when a Wi-Fi outage opens or closes. Only entries set up to run are read: an ignored discovery or a disabled entry is not a controller, bridge, hub or cloud. Where a stack has several entries, each one's lines carry the last eight characters of its entry id, never its title; a lone entry keeps the plain name.**

*Proof:* [`test_stack_readers.py`](../tests/test_stack_readers.py), [`test_stack_probes_hubs.py`](../tests/test_stack_probes_hubs.py), [`test_probe_additions.py`](../tests/test_probe_additions.py), [`test_hue_smartthings_probe.py`](../tests/test_hue_smartthings_probe.py), [`test_study_live_entries.py`](../tests/test_study_live_entries.py).

### STACK-13 What Device Sentinel Never Sends to a Stack

**Device Sentinel reads a stack and never writes to it: no ping, no re-interview, no configure, no setting changed, no connection opened to a hub, and no message to a hub, a bridge or a cloud. One exception is noted. With the Matter study on, the Thread border router read may ask the local network for border routers over multicast DNS, and they answer. It is read-only, it is the only way to see them, and it changes nothing. Recovering a device by writing to its stack is set aside whole until a real incident shows one it would have fixed, and nothing a person reads promises it.**

*Proof:* [`test_maintenance.py`](../tests/test_maintenance.py), [`test_hue_smartthings_probe.py`](../tests/test_hue_smartthings_probe.py), [`test_lutron_hub.py`](../tests/test_lutron_hub.py), [`test_lutron_study_gating.py`](../tests/test_lutron_study_gating.py).
