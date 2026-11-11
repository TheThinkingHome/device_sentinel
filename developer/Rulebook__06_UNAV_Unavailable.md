# Device Sentinel Rulebook: Unavailable (UNAV)

*Version: rulebook, 11 November 2026, on Device Sentinel 0.28.12. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

When a device is unavailable, when its outage began and ended, how a device that keeps dropping out is told, and how long a recovered device is said to have been down. Frozen and never reported devices, and what an outage does to learning, are under [FRZ](Rulebook__05_FRZ_Freeze.md). The stacks' own readers (ESPHome connections, Z-Wave dead nodes, hubs) are under [STACK](Rulebook__08_STACK_Stacks.md). A bridge, broker or integration going down is under [UP](Rulebook__07_UP_Upstream_Outages.md), and the mutes are under [MUTE](Rulebook__03_MUTE_Muting_and_Exclusion.md).

### UNAV-01 Main Entities Decide

**Unavailable is judged on a device's main entities. A device is unavailable only when its main entities are unavailable and nothing of its own is actively reporting.**
- **Main entities:** those with no entity category, not an update or button entity, and not disabled. A device with no main entity is judged on all its own entities.
- **Actively reporting:** a real report heard in this run, since the main entities went, within the freeze window (or within an hour while the device has none), with another of its own entities still holding a value.
- **Other integrations:** an entity another integration adds never counts.
- **After a restart:** real reports are remembered only for the current run. So a device alive only through such reports reads down once after a restart, and then comes back.

*Proof:* [`test_main_entities_decide_unavailable.py`](../tests/test_main_entities_decide_unavailable.py), [`test_absence_is_the_device.py`](../tests/test_absence_is_the_device.py), [`test_never_the_device.py`](../tests/test_never_the_device.py).

### UNAV-02 Unknown Counts as Nothing

**For judging, unknown, and an event or button entity at rest, count as nothing.** There is no separate unknown problem.
- **Only unknown or at rest:** a device whose deciding entities read only those is judged by its freeze clock, and a verdict already standing holds until the device reports.
- **Muted outages:** an unavailable outage hidden by an unavailable mute is listed unavailable when the mute is lifted, even if its entities have since turned unknown, as a device never muted would read.
- **After a restart:** that memory is not saved. If the muted device's entities come back unknown before a check sees them unavailable, lifting the mute judges it by its freeze clock.
- **Unknown for hours:** a device reading only unknown for hours, judged frozen, can turn unavailable at a one-minute stack blip without the three-minute wait, since its outage start is already hours old.

*Proof:* [`test_freeze_unavailable_split.py`](../tests/test_freeze_unavailable_split.py), [`test_freeze_and_unavailable_mutes.py`](../tests/test_freeze_and_unavailable_mutes.py), [`test_matter_awake.py`](../tests/test_matter_awake.py).

### UNAV-03 The Three-Minute Debounce

**A device turns unavailable only after it has read down for three minutes, so a device passing through a quick change of state is not reported. A frozen device waits the same three minutes before it turns unavailable, so an integration restart holds it frozen. A hub's lost connection is published at once, because two checks have already confirmed it (STACK).**

*Proof:* [`test_freeze.py`](../tests/test_freeze.py), [`test_main_entities_decide_unavailable.py`](../tests/test_main_entities_decide_unavailable.py), [`test_lutron_hub.py`](../tests/test_lutron_hub.py).

### UNAV-04 The Saved Outage Start

**Each device keeps one saved moment for when it went down as a whole.**
- **Down as a whole:** the entities that decide ([UNAV-01](#unav-01-main-entities-decide)) all read unavailable or unknown (an event or button entity at rest holds) with nothing of its own actively reporting, or an ESPHome device's connection drops.
- **Counts as up:** a device whose deciding entities read only unknown or at rest while another of its own entities holds a value.
- **Kept and cleared:** the moment names no entity, so it is kept through restarts, reloads and an entity's rename or removal. A device set aside or removed from Home Assistant has it cleared.
- **The date:** a device that went straight to unavailable is dated from it. A freeze that turns unavailable keeps the freeze's start ([UNAV-07](#unav-07-how-long-a-device-was-down)).
- **The end:** the outage ends when a deciding entity holds a value again, or when the device actively reports through another of its own entities.
- **One entity alone:** an entity that goes bad alone while another deciding entity holds a value starts nothing.
- **Nothing saved:** a standing unavailable verdict gives the start.

*Proof:* [`test_saved_outage_start.py`](../tests/test_saved_outage_start.py), [`test_saved_outage_start_cases.py`](../tests/test_saved_outage_start_cases.py), [`test_saved_outage_start_edges.py`](../tests/test_saved_outage_start_edges.py), [`test_outage_verdict_start.py`](../tests/test_outage_verdict_start.py), [`test_renamed_entities.py`](../tests/test_renamed_entities.py).

### UNAV-05 A Return Through a Restart

**A value handed back through a stack restart or Home Assistant's start is not the device speaking, whether or not the device is muted. A device muted for unavailable is a real return when its own outage began at least three minutes before the stack's hold began, or before Device Sentinel last listened. The stack's hold is under [UP](Rulebook__07_UP_Upstream_Outages.md).**
- **A broker that comes back (since 0.28.12):** a value an MQTT or Tasmota entity writes back on its way from an unavailable that began as MQTT lost the broker is handed back, not heard, until a minute after MQTT has found it again. Each MQTT entity hears MQTT's word on its own and may write before Device Sentinel hears it, so the loss, which each entity's unavailable follows, is what is matched. A Mosquitto restart can come and go between two minute checks, and its hand-back would otherwise revive each frozen device with no Last Seen.
- **A Zigbee2MQTT bridge that restarts (since 0.28.12):** the same holds when Zigbee2MQTT says its bridge is offline and online again: each of its entities follows the bridge's word, and a restart of half a minute can come and go between two minute checks. A value written back on the way from an unavailable that began as the bridge went offline is handed back, not heard, until a minute after the bridge is online again, so a silent device keeps its clock.
- **A first value at the start (since 0.28.12):** an integration that finishes loading after Device Sentinel adds its entities with the values it kept. Inside the startup grace that first value is handed back, not heard, for an entity that had no value yet when Device Sentinel began to listen, unless the device has a Last Seen clock or its integration asks the device itself, so a device that fell silent before the restart keeps its clock. A device Device Sentinel had judged unavailable is a real return either way. Outside the grace, or for an entity removed and added again, a first value is a device paired or an entity switched on, and it is heard.

*Proof:* [`test_restart_handback.py`](../tests/test_restart_handback.py), [`test_integration_handback.py`](../tests/test_integration_handback.py), [`test_freeze_and_unavailable_mutes.py`](../tests/test_freeze_and_unavailable_mutes.py), [`test_broker_reconnect_handback.py`](../tests/test_broker_reconnect_handback.py), [`test_bridge_restart_handback.py`](../tests/test_bridge_restart_handback.py), [`test_start_handback.py`](../tests/test_start_handback.py), [`test_first_state_judged_unavailable.py`](../tests/test_first_state_judged_unavailable.py).

### UNAV-06 Dropping Out

**Retired in 0.28.1.** Three drops to unavailable within two hours no longer make a device "dropping out". A device that keeps going unavailable and coming back on its own has short drop-outs, a signal problem ([SIG-17](Rulebook__10_SIG_Signal.md)).

### UNAV-07 How Long a Device Was Down

**A recovery's "down for", on the `device_sentinel_recovered` event and in the Daily Brief, counts from a start saved with the record when the trouble opens, and read back when the recovery is told.**
- **The start:** a freeze saves the device's last report. Straight to unavailable or unknown saves when the device went. A freeze that turns unavailable keeps the freeze's start. Never reported and dropping out count from the opening.
- **Saved once:** no report, no minute waiting on the Problem List ([LIST-06](Rulebook__11_LIST_Problem_List.md#list-06-a-problem-is-announced-once)) and no restart moves it, so a device that reports several times as it comes back is timed from its silence. The next trouble writes over it.
- **Taken back from set aside:** a freeze on a device taken back saves when it was watched again. One that came back already past its window counts from the opening.
- **Not trusted:** a damaged saved start, or one later than the recovery, counts from the opening. A record from before the start was saved has none, so a trouble standing at the upgrade counts from its opening.
- **After a clock step:** each "down for" counts from the step (FRZ). The start a standing trouble saved moves to the step, so a restart that forgets the step still counts from it.
- **A long drop beside short drop-outs (since 0.28.1):** a device with short drop-outs whose drop outlasts its freeze window is listed as unavailable from when it went, and its recovery counts from then ([SIG-17](Rulebook__10_SIG_Signal.md)).

*Proof:* [`test_short_drops.py`](../tests/test_short_drops.py), [`test_frozen_sentence_times.py`](../tests/test_frozen_sentence_times.py), [`test_unavailable_opening_time.py`](../tests/test_unavailable_opening_time.py), [`test_unwatched_time_cases.py`](../tests/test_unwatched_time_cases.py), [`test_recovery_one_way.py`](../tests/test_recovery_one_way.py), [`test_recovery_down_time.py`](../tests/test_recovery_down_time.py).

### UNAV-08 "Became Unavailable"

**The Daily Brief's words are the standard: a device "became unavailable" and a hub "went down", in the brief, its event sentences and the push alike ("At 3:04 pm, Kitchen Motion became unavailable."). Each surface keeps its own sentence shape, so the Problem List, which lists a state, reads "unavailable".**

*Proof:* [`test_unavailable_opening_time.py`](../tests/test_unavailable_opening_time.py), [`test_brief_wording.py`](../tests/test_brief_wording.py), [`test_problem_words.py`](../tests/test_problem_words.py), [`test_lutron_hub.py`](../tests/test_lutron_hub.py).
