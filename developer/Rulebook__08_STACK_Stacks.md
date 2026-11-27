# Device Sentinel Rulebook: Stacks (STACK)

*Version: rulebook, 27 November 2026, on Device Sentinel 0.30.9. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

What Device Sentinel knows about each radio stack and hub a house runs, and what it reads from each: Zigbee2MQTT, ZHA, Z-Wave, Matter and Thread, Lutron Caséta hubs and ESPHome. This section also covers when an integration's private state may be read, Extended Diagnostics and its probe file, and what Device Sentinel never sends to a stack. A stack going down and coming back is under [UP](Rulebook__07_UP_Upstream_Outages.md). Frozen and unavailable in general are under [FRZ](Rulebook__05_FRZ_Freeze.md) and UNAV. Mutes, including a hub's, are under [MUTE](Rulebook__03_MUTE_Muting_and_Exclusion.md).

### STACK-01 Which Stacks a House Runs

**Device Sentinel finds which stacks a house runs from its own device registry, never by asking.**
- **How each is found:** ZHA, Z-Wave and Matter by their integration's domain. Zigbee2MQTT by its bridge device, never by the mqtt domain it shares.
- **When:** it is worked out again at each registry rebuild and never saved, so adding or removing a stack needs nothing.
- **One file per stack:** each stack's knowledge lives in a file of its own, so adding a stack touches that file and one line.

*Proof:* [`test_stacks.py`](../tests/test_stacks.py).

### STACK-02 Hardware the Author Does Not Own

**A stack is supported only once it can be tested.** That means on the author's own hardware, or marked experimental when it is built from a tester's recorded data and simulated in the test container, with its Home Assistant integration installed and its hardware faked.
- **Order:** stacks are added one per release, in the order of how complete the data in hand is.
- **Wiki page:** each stack still being built for has a wiki page saying what is known, what is not, the exact commands to run (each run on the reference house first), and the questions whose answers decide the design.
- **Asking for data:** captures that name no device are asked for in a public issue. A full diagnostics download is asked for privately, with the page saying what is inside.
- **One-question tools:** a tool built to answer one question from inside Home Assistant is its own throwaway integration, never shipped inside a feature, and it changes nothing. It summarises bursts, names only the device it means, watches the config entry and never writes from the event loop.

*Proof:* none; this rule is a procedure, checked when a stack is added.

### STACK-03 Zigbee2MQTT

**Device Sentinel reads each Zigbee2MQTT bridge from its own retained topics, under the base topic that bridge publishes on, never its display name (since 0.30.9; contributed by Reifircax).**
- **One bridge on the default topic:** the bridge on `zigbee2mqtt` keeps the scope, Bridge sensor and saved outages older releases gave it, so a house with one bridge there sees no change. Until a bridge's topic is known, Device Sentinel reads the default topic, as before.
- **Several bridges:** any other bridge is named by its own registry device, so adding, removing or renaming a bridge changes no other bridge's sensor. Each has its own state, pairing window and outage. A house with one bridge reads it for every Zigbee2MQTT device, as before; with several, a device belongs to the bridge it sits under in the registry, or the one whose device list holds its address, and a device two bridges claim gets no opinion.
- **Pairing deadline:** a retained open flag with an expired deadline does not open a window. A window already heard closes at its deadline even if the closing message is missed.
- **Finding the topic (James, 27 November 2026):** every bridge publishes a retained bridge/info message under its base topic that names its coordinator's address, and Zigbee2MQTT names its bridge device "zigbee2mqtt_bridge_" and that address, which a rename does not change. Device Sentinel listens for bridge/info one to four levels deep, through MQTT's own subscribe, and matches the two. A message that names no coordinator is ignored, and an address two topics claim gives no topic. A bridge whose topic is not found, deeper than four levels for one, gets no reader of its own rather than a guessed one; a bridge already read keeps its reader while its topic is briefly not known.
- **MQTT is optional:** MQTT is a soft dependency, so a house without it still loads. The reader asks whether MQTT is loaded before it waits for it.
- **Bridge sensor:** each Zigbee2MQTT bridge and ZHA gets a Bridge sensor that reads running, binding, down or unknown. A bridge found after startup gets its sensor then. It is switched on at install, since it exists only where its stack was found (see [CFG](Rulebook__17_CFG_Settings.md)). Z-Wave and Matter are detected but have no reader and no Bridge sensor. Detection works whether or not the sensor is on.
- **Availability setting:** the sensor shows whether Zigbee2MQTT's availability setting is on, and Device Sentinel never changes it. Where it is off, a line on the Recommendations tab says what turning it on gives.
- **Zigbee2MQTT's own view:** it confirms or doubts a freeze verdict and never decides one. It is matched through the bridge's device list, never by name. A topic with no device in that list answers nothing. An online reading never lifts a verdict.
- **Timeout shown with it:** the timeout for the device's power class, read from the bridge, goes with the reading wherever it is shown, on the Problem List item and in the Daily Brief, never on the phone.

*Proof:* [`test_multiple_z2m_bridges.py`](../tests/test_multiple_z2m_bridges.py), [`test_z2m_topic_search.py`](../tests/test_z2m_topic_search.py), [`test_bridge_pairing.py`](../tests/test_bridge_pairing.py), [`test_maintenance.py`](../tests/test_maintenance.py), [`test_reachability.py`](../tests/test_reachability.py), [`test_recommendations.py`](../tests/test_recommendations.py), [`test_manifest_dependencies.py`](../tests/test_manifest_dependencies.py).

### STACK-04 ZHA

**For a ZHA device, Device Sentinel reads the time ZHA last heard it, which ZHA sets from each radio message (under [STACK-08](#stack-08-reading-an-integrations-private-state)).**
- **What it decides:** one thing. A value handed back after a ZHA restart or reload is the device speaking only if ZHA has heard the device since its last report. It does not date contact or start a new device's clock.
- **On the device page:** in Advanced, the Last seen sensor row names it: "ZHA's own", "when ZHA last heard it, used to tell it's alive". Simple shows that row only when the sensor is switched off.
- **Other stacks:** Zigbee2MQTT and Z-Wave JS devices have their own Last Seen entities. Once switched on, those also date contact and start a new device's clock.
- **Coordinator:** ZHA's coordinator is watched as an upstream through its config entry (see [UP](Rulebook__07_UP_Upstream_Outages.md)).
- **ZHA's own view, since 0.28.5:** beside a verdict, as Zigbee2MQTT's is (under [STACK-03](#stack-03-zigbee2mqtt)), Device Sentinel tells what ZHA itself holds for the device: whether it is available, when its radio last heard it, and how long ZHA waits before marking it unavailable. The wait is ZHA's setting for the device's power, 6 hours for a battery device and 2 hours for a mains one unless ZHA's settings change them. "ZHA reads it as available and last heard from it 3 minutes ago. ZHA waits 6 hours of silence from a battery device before it marks it unavailable." It confirms or doubts a verdict and never decides one. Read from ZHA's own objects (under [STACK-08](#stack-08-reading-an-integrations-private-state)); anything not where it is expected is no opinion, and the sentence is left out.

*Proof:* [`test_zha_last_seen.py`](../tests/test_zha_last_seen.py), [`test_zha_reader.py`](../tests/test_zha_reader.py), [`test_zha_availability_view.py`](../tests/test_zha_availability_view.py).

### STACK-05 Z-Wave

**For each watched Z-Wave device, Device Sentinel reads its Z-Wave status sensor.**
- **Dead:** "dead" makes the device unavailable, dated from the change and kept through a restart or a reload. Values written while it reads dead are not the device speaking.
- **Back from dead:** "alive" or "awake" after dead is the device heard and counts as contact, a restart included, since Z-Wave JS marks a node alive only when it answers.
- **Otherwise:** the status is never a report. It stamps no clock and teaches no rhythm. A device whose status sensor is its only enabled entity is judged by the clock while the node reads up.
- **The backstop:** Z-Wave marks a node dead only when a command to it fails, so for a device nobody tries to reach, the freeze window stays the backstop.
- **On the device page:** a Z-Wave status row sits under Last seen sensor. It reads alive, asleep, awake, dead or "not known yet", or "switched off" with a Turn it on button. Simple shows it only when the node is dead or its sensor is switched off.
- **Sensor switched off:** a device whose status sensor is switched off is listed on the Z-Wave Status Switched Off card (REC). Switching the status sensor off while the node reads dead can be read as the device recovering.

*Proof:* [`test_zwave_dead_node.py`](../tests/test_zwave_dead_node.py), [`test_dead_node_recovery.py`](../tests/test_dead_node_recovery.py), [`test_dead_node_outage_dates.py`](../tests/test_dead_node_outage_dates.py), [`tools/panel_checks/check_node_status.js`](../tools/panel_checks/check_node_status.js).

### STACK-06 Matter and Thread

**There is no Matter device reader.**
- **Spared types:** a Matter device not behind a bridge whose type reports only on use (Appliance, Button, Cover, Fan, Light, Lock, Matter Bridge, Plug, Siren, Switch, Vacuum or Valve) is never newly judged frozen while any of its entities reads available, whatever powers it.
- **Not spared:** a sensor, and any other type, keeps the freeze rule. So does a device that measures something, unless its owner set the type.
- **Standing verdicts:** a frozen verdict already standing stays until the device reports, and unavailable is judged as before.
- **What the person sees:** while a device is spared, its page reads "Not called frozen while Home Assistant shows it available." and the Slow Reporting Devices card leaves it off.
- **Next:** the upstream to build next is the Thread network: one problem when each border router carrying it is gone, from measured timings.
- **The Thread role and contact (since 0.30.7):** each Matter device's Thread role is shown, never judged ([STACK-18](#stack-18-the-thread-role)), and Extended Diagnostics records Device Sentinel's own contact clock for each Matter device ([STACK-19](#stack-19-matter-in-extended-diagnostics)). A Matter goal of the 0.30 line (James, 26 November 2026): what the two show on real houses decides whether a router that others route through, or a sleepy sensor that checks in, is spared later.

*Proof:* [`test_matter_awake.py`](../tests/test_matter_awake.py), [`tools/panel_checks/check_device_page_text.js`](../tools/panel_checks/check_device_page_text.js).

### STACK-07 ESPHome

**An ESPHome device that does not deep-sleep is never newly judged frozen while Home Assistant's connection to it is up, whatever its entities read ([FRZ-07](Rulebook__05_FRZ_Freeze.md#frz-07-a-device-is-frozen)).**
- **What it reads:** ESPHome's own deep-sleep and connection flags (under [STACK-08](#stack-08-reading-an-integrations-private-state)).
- **Connection down:** a device that does not deep-sleep and whose connection is down is unavailable within a few minutes, whatever its Status sensor shows. A frozen verdict standing moves to unavailable on the same item.
- **While disconnected:** a value written then, such as the Status sensor turning off, is not the device speaking, and the time it spent off the network is not learned.
- **Freeze rule kept:** a device that deep-sleeps keeps the freeze rule, and so does one whose flags cannot be read.

*Proof:* [`test_esphome_connection.py`](../tests/test_esphome_connection.py), [`test_freeze.py`](../tests/test_freeze.py), [`test_recommendations.py`](../tests/test_recommendations.py).

### STACK-08 Reading an Integration's Private State

**Detection reads an integration's private state only where a rule names the integration and the one field.**
- **Failure is safe:** each read is wrapped, so a missing field, a changed shape or any failure leaves the device on the ordinary rules and logs one line. A Home Assistant update that moves the field costs the exception, never a start, a verdict or a save.
- **Manifest and imports:** such an integration is named in the manifest's after_dependencies, never its dependencies. Nothing is imported from an integration read this way. Home Assistant's recorder is named there too, since 0.28.7, and its public statistics functions are imported for a Z-Wave controller's typical radio noise ([DASH-18](Rulebook__14_DASH_Dashboard.md#dash-18-a-networks-outage-patterns-and-radio-noise)).
- **Listed:** the wiki lists each exception and its field.
- **Who is read:** three integrations: ESPHome (deep sleep and connection), ZHA (when it last heard a device) and Lutron Caséta (the hub's session). Matter, Thread and Z-Wave JS are weighed against their probe data as it arrives.
- **Shown, not judged (since 0.30.7):** Matter's network map, read through the Matter client Home Assistant holds, for the Thread role on the device page and the Networks tab ([STACK-18](#stack-18-the-thread-role)). It decides no verdict. ZHA's and Zigbee2MQTT's power source fill in Powered By ([DEV-06](Rulebook__04_DEV_Device_Identity.md#dev-06-what-powers-a-device)).
- **Extended Diagnostics:** it may also read private state, since it records and never judges.

*Proof:* [`test_manifest_dependencies.py`](../tests/test_manifest_dependencies.py), [`test_freeze.py`](../tests/test_freeze.py), [`test_zha_last_seen.py`](../tests/test_zha_last_seen.py), [`test_lutron_hub.py`](../tests/test_lutron_hub.py).

### STACK-09 Lutron Hubs

**Lutron Caséta is supported, marked experimental. Device Sentinel reads whether each hub is connected from the session its library holds, once a minute, and sends nothing to the hub.**
- **Hub down:** a hub read as not connected on two checks 55 seconds or more apart is down, dated from when it was first seen gone. A hub whose integration failed to set up is not connected. One whose integration is not loaded, or whose session cannot be read, gives no opinion.
- **How each is judged:** a hub is judged by its connection, and each device registered through it by the hub. Those devices are never frozen and never "never reported", since Lutron reports a device only when someone uses it.
- **On the Problem List:** a watched hub that is down is one row. The devices it controls keep their verdicts and are listed on its page until it is back.
- **Device readings:** a Pico press counts as the Pico reporting. Unknown counts as nothing. A device whose entities read unavailable, leaving aside any that read unknown, is unavailable. A device whose entities all read unknown gets no new verdict and keeps one already standing.
- **Integration entry:** a watched hub owns its integration entry. A hub that is not watched is judged by nothing, and its entry is left to the integration outage rule (UP).
- **Mutes:** a hub's mute covers the devices it controls, mute by mute, and a device's own mute stands. A hub muted for freeze is still reported when it goes down (see [MUTE](Rulebook__03_MUTE_Muting_and_Exclusion.md)).

*Proof:* [`test_lutron_hub.py`](../tests/test_lutron_hub.py), [`test_lutron_campaign.py`](../tests/test_lutron_campaign.py).

### STACK-10 What a Hub's Rows and Pages Say

**A hub's rows and pages say the following.**
- **Problem List:** "Hub down, 2 devices that it controls", with "Down since 1:28 PM. The 2 devices it controls are listed on its page, not on the Problem List, until it is back."
- **Notification card:** "Garage Lutron Caseta hub down, 2 devices that it controls".
- **Daily Brief:** it says a hub "went down" and "has been down", and lists a hub that is down as "hub down, 2 devices that it controls".
- **Hub's page:** Up or Down with when, how it is judged, Devices This Hub Controls (DEVICE, TYPE, STANDING, LAST SEEN, PROBLEM) and its outages over 14 days (WENT DOWN, BACK, DOWN FOR, DEVICES IT CONTROLS), with no Reporting group. The TYPE column shows Device Sentinel's type.
- **Controlled device's page:** it reads "Judged by its hub", links the hub and says why its silence cannot be judged. While the hub's connection cannot be read it says "Device Sentinel cannot read {Hub}'s connection right now."
- **Muted with its hub:** the device reads "Muted with its hub" on the hub's page and "Freeze is muted with its hub. Change it on {Hub}'s page." on its own.

*Proof:* [`tools/panel_checks/check_hub_pages.js`](../tools/panel_checks/check_hub_pages.js), [`test_lutron_campaign.py`](../tests/test_lutron_campaign.py), [`test_lutron_hub.py`](../tests/test_lutron_hub.py).

### STACK-11 Extended Diagnostics

**Extended Diagnostics offers one switch for each integration or stack in the house that support is still being built for. Extended Diagnostics records and never judges.**
- **Turning one on:** it gathers for that integration only, into the diagnostics download the person attaches to an issue. Nothing is sent anywhere.
- **Turning it off:** gathering stops. The shapes it gathered are dropped at the next midnight fold. Lines already written to the probe file stay until they roll out ([STACK-12](#stack-12-the-stack-probe-file)).
- **Built stacks:** a stack whose support is built may stay on the list, so its data can be gathered if trouble comes.
- **What is offered:** the routers (UniFi, FRITZ!Box, AsusWRT, NETGEAR and MikroTik), Z-Wave, Matter, Hue, SmartThings, Tuya, Lutron Caséta, since 0.28.10 Tado, since 0.29.1 Sonos, read from what Home Assistant's Sonos integration holds for each speaker, and since 0.30.3 "Hub: Aqara", each only where the house has it, and Problem Sensors and Polling on every house ([STACK-14](#stack-14-problem-sensors-and-polling)). HomeKit Device and deCONZ are not, and Shelly needs nothing.
- **Hue and SmartThings:** read by sampling only, once a minute from memory, beside Device Sentinel's own record of each device's state changes, with no callback added to either library. A change shorter than a minute can be missed. Nothing judges from them until a house with them has sent its data.
- **SmartThings and Tuya:** they are there for a cloud outage. Once each has recorded a real one, one rule for cloud integrations is built from them and those probes retire.
- **Tado (since 0.28.10):** read from the data Home Assistant's own coordinator holds, never from tado, whose free accounts have 100 requests a day. A line at each change of a device's Connection State, battery or firmware; one at each refresh with the interval set, whether it worked and the requests left; each room's link sensor when it changes; and one a day per device with how often its connection timestamp moved, which tells whether that timestamp is a clock each device could be judged by. The current values are in the download.
- **Hub: Aqara (since 0.30.3):** offered where an Aqara device (maker Aqara or Lumi) reaches Home Assistant through Matter or HomeKit Device, as an Aqara hub shares its own devices. Read from Home Assistant's registries and states alone: a line when an Aqara device's entity turns unavailable or comes back, the hub's own included; a line when three or more Aqara devices report inside the same two seconds, with how many and through which integration; and a line a day per Aqara device with how long since it last reported and the hub it sits behind. The download lists each Aqara device, its integration, model, software, the hub it sits behind, how many devices sit behind it, how long since it reported and its entities' states. It answers whether Home Assistant ever marks a device behind the hub unavailable, which decides whether Device Sentinel can see a dead leak sensor there (James, 23 November 2026).
- **Matter (more since 0.30.7):** see [STACK-19](#stack-19-matter-in-extended-diagnostics).
- **Judging goes on:** whatever a studied library does, Device Sentinel goes on judging, listing, saving and folding.
- **The page (since 0.29.8):** it opens with Share Names in Diagnostics ([STOR-21](Rulebook__18_STOR_Storage.md#stor-21-the-diagnostics-download)), then the list, with how to ask for support for listed hardware in the list's own help text.

*Proof:* [`test_study.py`](../tests/test_study.py), [`test_diagnostics_share_names.py`](../tests/test_diagnostics_share_names.py), [`test_stack_probes_hubs.py`](../tests/test_stack_probes_hubs.py), [`test_hue_smartthings_probe.py`](../tests/test_hue_smartthings_probe.py), [`test_probe_guard.py`](../tests/test_probe_guard.py), [`test_lutron_study_gating.py`](../tests/test_lutron_study_gating.py), [`test_tado_recording.py`](../tests/test_tado_recording.py), [`test_sonos_recording.py`](../tests/test_sonos_recording.py), [`test_aqara_recording.py`](../tests/test_aqara_recording.py).

### STACK-12 The Stack Probe File

**Each studied stack writes its lines to one file, stack_probe.md, rolled at 1 MB to .1, .2 and .3.**
- **Each line:** each Z-Wave and Matter line names the node's device beside its node id, with Device Sentinel's own view of the device beside the stack's.
- **Z-Wave:** the probe records node events as they arrive, each device's route and its changes, and one controller health line a day. Its Device Sentinel column says muted, set aside or learning where that is true.
- **Matter:** the probe records each Thread border router appearing and disappearing, with its network name and ID, each Thread device's network ID, and which Matter Wi-Fi devices were away when a Wi-Fi outage opens or closes.
- **Which entries:** only entries set up to run are read. An ignored discovery or a disabled entry is not a controller, bridge, hub or cloud.
- **Several entries:** where a stack has several, each one's lines carry the last eight characters of its entry id, never its title. A lone entry keeps the plain name.
- **A line only when something changes (since 0.28.3):** each device row is remembered by its stack, its node's full id and its device. The NODE column shows a Hue, SmartThings or Tuya id cut to eight characters, and two devices can share those eight; an entry left by an older setup can list the same node as an empty copy of the device. Remembered by the short id alone, the two views took turns and each turn was written: on a tester's house, 2,310 Tuya lines in three and a half hours.

*Proof:* [`test_stack_readers.py`](../tests/test_stack_readers.py), [`test_stack_probes_hubs.py`](../tests/test_stack_probes_hubs.py), [`test_probe_additions.py`](../tests/test_probe_additions.py), [`test_hue_smartthings_probe.py`](../tests/test_hue_smartthings_probe.py), [`test_study_live_entries.py`](../tests/test_study_live_entries.py), [`test_stack_probe_duplicates.py`](../tests/test_stack_probe_duplicates.py).

### STACK-13 What Device Sentinel Never Sends to a Stack

**Device Sentinel reads a stack and never writes to it.** No ping, no re-interview, no configure, no setting changed, no connection opened to a hub, and no message to a hub, a bridge or a cloud.
- **One exception:** with the Matter study on, the Thread border router read may ask the local network for border routers over multicast DNS, and they answer. It is read-only, it is the only way to see them, and it changes nothing.
- **Recovery by writing:** recovering a device by writing to its stack is set aside whole until a real incident shows one it would have fixed, and nothing a person reads promises it.

*Proof:* [`test_maintenance.py`](../tests/test_maintenance.py), [`test_hue_smartthings_probe.py`](../tests/test_hue_smartthings_probe.py), [`test_lutron_hub.py`](../tests/test_lutron_hub.py), [`test_lutron_study_gating.py`](../tests/test_lutron_study_gating.py).

### STACK-14 Problem Sensors and Polling

**Since 0.28.3, the Extended Diagnostics choice Problem Sensors and Polling records every problem sensor's state and which integrations update all their devices at once. It records and never judges.**
- **Why:** on a tester's house, Alarm.com polls a cloud and updates its 16 devices together, so what is heard from each device is the poll. When the poll stopped for hours with the integration loaded, every device was reported frozen one by one and the gap was learned as their rhythm. Each device publishes its own health as a Malfunction sensor, a binary sensor of class problem, which nothing read. Problem sensors mean other things elsewhere: a printer's can mean it is out of paper. Both are recorded before either is judged.
- **Offered on every house,** since neither is hardware a house may lack.
- **Problem sensors:** every enabled binary sensor of class problem on a device. A line in stack_probe.md when its state or its own attributes change, NODE problem, with Device Sentinel's view of the device beside it and the entity and its attributes in DETAIL, so Alarm.com's Trouble says which condition turned it on (since 0.28.10); a count a day per integration by state; and each one's state, attributes and since when in the diagnostics download.
- **Lockstep:** an integration with at least 3 watched devices that each have 5 days of daily longest gaps is measured: a device is in step when each of those gaps is within 1% of the integration's median that day, and never closer than 2 seconds or a tenth of the median, whichever is less, and the integration is lockstep when at least 80% are. Days are matched by date, not by place in the list, a date fewer than 3 devices hold is not compared, and a device with fewer than 3 dates compared is left out of the count, not taken as in step on no evidence (since 0.28.11). A day removed by hand is not counted ([FRZ-25](Rulebook__05_FRZ_Freeze.md#frz-25-a-day-removed-by-hand)). At a 30-second poll 1% is a third of a second, finer than the few seconds a cloud takes to write all its devices: a tester's Alarm.com read 8 of 15 at 1% and 13 of 15 at 2 seconds, while a tester's TP-Link plugs, each reporting about every 10 seconds, stay apart on the house as a whole. On a small house a few such plugs can still read as moving together, which is Rare and costs only the announcement of their update bursts. Measured at the start and at each fold, with a line a day, NODE polling, lockstep or independent. On three houses, Alarm.com is lockstep and nothing else watched is.
- **A stop:** a lockstep integration none of whose watched devices has been heard for twice its usual longest gap, never less than 10 minutes, outside the startup grace. A line when it stops and when any of its devices is heard again, with how long, how many devices and the most of them Device Sentinel listed meanwhile. Ended stops are kept for the download, the last 20.
- **Memory only:** nothing is stored. A restart measures again, and taking the choice off forgets it at once.
- **Each poller's refresh (since 0.28.10):** the download says, for each lockstep integration and each poller, whether Home Assistant's own update coordinator can be read from its entry, and if so its interval and last result. Tado's can; the Alarm.com fork's keeps a hub and cannot.
- **Since 0.28.10:** the lockstep measure also decides the lasting poller verdict and its stop ([UP-17](Rulebook__07_UP_Upstream_Outages.md#up-17-storms-and-pollers)), on every house.
- **Next:** judging a device by its integration's own health sensor, Alarm.com's Malfunction and Trouble and Tado's Connection State, waits on these recordings and a test on a tester's house.

*Proof:* [`test_problem_sensors_and_polling.py`](../tests/test_problem_sensors_and_polling.py), [`test_tado_recording.py`](../tests/test_tado_recording.py).

### STACK-15 A Z-Wave Controller's Own Status

**Since 0.28.5, Device Sentinel records each change of a Z-Wave controller's Status (ready, unresponsive or jammed) with when it began, and shows it. It never judges from it.**
- **Found:** by the sensor's unique id, ending `.controller_status`, whatever the entity is named.
- **Recorded:** each change, on the controller's record; the newest 20 are kept. Unknown and unavailable are the sensor not answering and are not recorded. A start reads the sensor as it stands, and a reading that repeats the last adds nothing.
- **Shown:** on the controller's device page, in the Reporting group, as "Controller status: Ready, since Nov 8, 9:00 AM". The first reading, taken at an install or an upgrade, reads "first read Nov 8, 4:35 PM", since when it began is not known; the Networks tab gives it no "since" either. Simple shows it only when it is not Ready. Device Telemetry lists every change, newest first.
- **Next:** naming the controller as the cause of an outage waits for a real Unresponsive or Jammed in a house's readings.

*Proof:* [`test_zwave_controller_status.py`](../tests/test_zwave_controller_status.py), `check_status_readings.js`.

### STACK-16 Lightwave Devices and Their Connectivity Sensor

**Since 0.30.0, a Lightwave Smart Series device is judged by its Connectivity sensor, which Lightwave Smart 5.5.0 adds to each device's radio device ("Office Light Device").**
- **Off:** the hub cannot reach the device, about 30 minutes after it loses power. The device is unavailable, dated from the change, as a dead Z-Wave node is ([STACK-05](#stack-05-z-wave)). Off is never the device speaking. Since 0.30.2 it is listed at the next minute check, without the three-minute wait, as a hub's lost connection is ([UNAV-03](Rulebook__06_UNAV_Unavailable.md#unav-03-the-three-minute-debounce)): Lightwave has already waited about 30 minutes.
- **Back on:** the hub has heard the device again, which counts as contact and ends the outage.
- **On:** the device is never newly called frozen, as a connected ESPHome device is not ([STACK-07](#stack-07-esphome)). A dimmer used once a week says nothing between uses, and its hub reaches it all the same. A frozen verdict already standing stays until the device reports.
- **Never reported:** a device whose sensor reads on is never called never reported. The radio device carries only this sensor and a firmware notice, and a socket nobody has switched since it was added has sent nothing either; the hub reaching them is enough. One that has never sent anything and whose sensor reads off is unavailable.
- **Lights and sockets:** each is a device of its own registered via the radio device, and follows its sensor. Their own entities stay their reports.
- **Says nothing:** unavailable (Home Assistant's Lightwave session down, the hub's own link lost, or a status other than connected or disconnected), not yet known, or switched off. The last word stands for an outage, and the freeze rule stands for a device not known to be down.
- **The hub's Cloud Link sensor:** read since 0.30.2, under [STACK-17](#stack-17-lightwave-hubs-and-their-cloud-link). Connect Series devices, and Lightwave Smart before 5.5.0, have no Connectivity sensor and keep the ordinary rules.
- **On the page:** no Z-Wave status row, and the Recommendations tab does not ask for the sensor switched on.

*Proof:* [`test_lightwave_connectivity.py`](../tests/test_lightwave_connectivity.py).

### STACK-17 Lightwave Hubs and Their Cloud Link

**Since 0.30.2, a Lightwave hub is judged by its Cloud Link sensor, as a Lutron hub is judged by its connection ([STACK-09](#stack-09-lutron-hubs)). One row tells a hub that has lost its link, not a row for each device behind it.**
- **The hub:** the device carrying Cloud Link (unique id `<hub id>_cloudLink`). Lightwave registers it as a service; it is watched as a hub all the same ([WATCH-03](Rulebook__02_WATCH_What_Is_Watched.md#watch-03-set-aside)), and shows on the Networks tab as a Lutron hub does.
- **Down:** Cloud Link read Disconnected on two checks 55 seconds or more apart, dated from the first, published at once. On a tester's house the sensor turned to Disconnected 2 minutes 23 seconds after the hub's network cable was pulled, and to Connected 38 seconds after it was plugged back in. Its integration failing to start is down too.
- **No opinion:** Cloud Link unavailable, or its integration still starting or unloaded. What was known stands and nothing is confirmed.
- **Behind it:** every Lightwave device of the same entry registered under it, directly or through its radio device. While the hub is down, or going, each waits for it with its verdict as it stood, and is listed on the hub's page, not on the Problem List. While the hub is up, each keeps its own judgment ([STACK-16](#stack-16-lightwave-devices-and-their-connectivity-sensor)), unlike a Lutron hub's devices, which report only when used.
- **The hub itself:** judged by Cloud Link alone, never frozen and never "never reported".
- **Its mute:** covers the hub's own outage, and so its devices while they wait for it, and nothing of their own. Muted for unavailable, the hub going down is silent, and a socket it cannot reach while it is up is still listed. Unlike a Lutron hub's mute, which covers its devices in every family ([STACK-09](#stack-09-lutron-hubs)), because a Lutron device has no voice but its hub's (James, 22 November 2026).
- **The return:** Lightwave updates every device at once when the hub comes back, 70 devices 13 seconds after Cloud Link read Connected on the tester's house. That burst is recorded as a storm, as any other ([UP-17](Rulebook__07_UP_Upstream_Outages.md#up-17-storms-and-pollers)).
- **Rows and words:** as for any hub ([STACK-10](#stack-10-what-a-hubs-rows-and-pages-say)): "Hub down", with the number of devices that it controls.
- **Cloud Link switched off:** the hub is watched with no word to give, its devices are judged on their own, and the Cloud Link Switched Off card asks for it on ([REC-05](Rulebook__15_REC_Recommendations.md#rec-05-switched-off-sensors)), in Simple too (James, 22 November 2026).
- **No Cloud Link sensor:** the hub stays set aside as a service, and its devices are judged as before.

*Proof:* [`test_lightwave_hub.py`](../tests/test_lightwave_hub.py).

### STACK-18 The Thread Role

**Since 0.30.7 (James, 26 November 2026, 10:32), Device Sentinel shows each Matter device's Thread role from the map the Matter server keeps, and draws no map of its own: Home Assistant has drawn one on its Matter panel since 2026.9.**
- **The device page, Advanced:** Thread Role, such as "Router, 3 devices route through it" or "Sleepy end device", with "Read from the Matter server's network map, which can lag a few minutes." and a link, Open Home Assistant's Matter map. Thread Link names its strongest link to a router: "Strong to SMHUB Nano". A Wi-Fi or Ethernet Matter device has neither row.
- **The Networks tab:** a Thread card, "Your Thread network (home-thread): 2 border routers, 1 router, 1 end device, 4 sleepy end devices.", with the same note and link. Advanced adds each router, border routers first, with ROUTER (a link to its page where it has one), ROLE, CARRIES (the end devices linked to it) and LINK (its strongest link to another router).
- **How it is read:** through the Matter client Home Assistant already holds, never by importing Matter ([STACK-08](#stack-08-reading-an-integrations-private-state)), on a server with the map (its schema 13 or later). Asked for at most every ten minutes, in the background, waiting at most 30 seconds, and never refreshed: a refresh reads every device over the radio. The server counts leader, router and router-eligible as routers, as Home Assistant's map does. A link reading "none" is no link.
- **A hint, never proof:** the map can lag, and a router taken away can stay on it, so the role changes no verdict ([STACK-06](#stack-06-matter-and-thread)).
- **Failure is safe:** an older server, no client, or a map that cannot be read leaves the rows and the card out, and never stops the minute; the rest of each page draws.

*Proof:* [`test_matter_thread_role.py`](../tests/test_matter_thread_role.py), [`tools/panel_checks/check_thread_role.js`](../tools/panel_checks/check_thread_role.js).

### STACK-19 Matter in Extended Diagnostics

**Since 0.30.7 (James, 26 November 2026, 10:21 and 10:32), with Matter studied, the download carries more for each Matter device, recorded to learn whether Device Sentinel can judge Matter better. Nothing here judges, and nothing is stored.**
- **Its own contact clock:** Device Sentinel listens to each Matter device through Home Assistant's Matter client and counts any value it sends as contact, even one no entity shows, and any event it sends, such as a press. A whole-node update comes from the server, also when it marks a device unavailable, so it is counted apart and is never contact. Per device: how many times heard, how long since, how long it has listened and the longest silence, a silence still running included. Set beside how long since its entities last reported. The clock starts again at each restart, at a Matter reload and when Matter is no longer studied. In October a tester's sleepy Thread devices sent a value no entity showed about every 2.2 hours.
- **Check-in state:** from the server's own record (its schema 12 or later): supported, registered, operating mode, awake, available and the next expected check-in. Each is asked for at most five seconds, and once one answer is too slow the rest of that download is not asked.
- **Power Source:** from the device's own Power Source cluster: wired or battery, rechargeable, replaceable, and the battery's description, designations and count where it gives them.
- **The Thread map:** the routers and what each carries, and each device's role and best link, from the map of [STACK-18](#stack-18-the-thread-role), never refreshed.

*Proof:* [`test_matter_contact_clock.py`](../tests/test_matter_contact_clock.py).
