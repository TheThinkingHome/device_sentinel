# Device Sentinel Rulebook: Unavailable (UNAV)

*Version: rulebook, 28 October 2026, on Device Sentinel 0.27.11. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

When a device is unavailable, when its outage began and ended, how a device that keeps dropping out is told, and how long a recovered device is said to have been down. Frozen and never reported devices, and what an outage does to learning, are under [FRZ](Rulebook__05_FRZ_Freeze.md). The stacks' own readers (ESPHome connections, Z-Wave dead nodes, hubs) are under [STACK](Rulebook__08_STACK_Stacks.md); a bridge, broker or integration going down is under [UP](Rulebook__07_UP_Upstream_Outages.md); the mutes are under [MUTE](Rulebook__03_MUTE_Muting_and_Exclusion.md).

### UNAV-01 Main Entities Decide

**Unavailable is judged on a device's main entities: those with no entity category, not an update or button entity, and not disabled. A device with no main entity is judged on all its own entities. A device is unavailable only when its main entities are unavailable and nothing of its own is actively reporting. Actively reporting means a real report heard in this run, since the main entities went, within the freeze window or within an hour while the device has none, with another of its own entities still holding a value. An entity another integration adds never counts. Real reports are remembered only for the current run, so after a restart a device alive only through such reports reads down once and then comes back.**

*Proof:* [`test_main_entities_decide_unavailable.py`](../tests/test_main_entities_decide_unavailable.py), [`test_absence_is_the_device.py`](../tests/test_absence_is_the_device.py), [`test_never_the_device.py`](../tests/test_never_the_device.py).

### UNAV-02 Unknown Counts as Nothing

**For judging, unknown, and an event or button entity at rest, count as nothing. A device whose deciding entities read only those is judged by its freeze clock, and a verdict already standing is held until the device reports. There is no separate unknown problem. An unavailable outage hidden by an unavailable mute is listed unavailable when the mute is lifted, even if its entities have since turned unknown, as a device never muted would read. That memory of a hidden outage is not saved: after a restart, if the muted device's entities come back reading unknown before a check sees them unavailable, lifting the mute judges it by its freeze clock. A device reading only unknown for hours, judged frozen, can turn unavailable at a one-minute stack blip without the three-minute wait, since its outage start is already hours old.**

*Proof:* [`test_freeze_unavailable_split.py`](../tests/test_freeze_unavailable_split.py), [`test_freeze_and_unavailable_mutes.py`](../tests/test_freeze_and_unavailable_mutes.py), [`test_matter_awake.py`](../tests/test_matter_awake.py).

### UNAV-03 The Three-Minute Debounce

**A device turns unavailable only once it has read down for three minutes, so a device passing through a quick change of state is not reported. A frozen device waits the same three minutes before it turns unavailable, so an integration restart holds it frozen. A hub's lost connection is published at once, having already been confirmed over two checks (STACK).**

*Proof:* [`test_freeze.py`](../tests/test_freeze.py), [`test_main_entities_decide_unavailable.py`](../tests/test_main_entities_decide_unavailable.py), [`test_lutron_hub.py`](../tests/test_lutron_hub.py).

### UNAV-04 The Saved Outage Start

**Each device keeps one saved moment for when it went down as a whole: the entities that decide ([UNAV-01](#unav-01-main-entities-decide)) all reading unavailable or unknown (an event or button entity at rest holds) with nothing of its own actively reporting, or an ESPHome device's connection dropping. A device whose deciding entities read only unknown or at rest while another of its own entities holds a value counts as up. The moment names no entity, so it is kept through restarts, reloads and an entity's rename or removal; a device set aside or removed from Home Assistant has it cleared. A device that went straight to unavailable is dated from it; a freeze that turns unavailable keeps the freeze's start ([UNAV-07](#unav-07-how-long-a-device-was-down)). The outage ends when a deciding entity holds a value again, or when the device actively reports through another of its own entities. An entity that goes bad alone while another deciding entity holds a value starts nothing. With nothing saved, a standing unavailable verdict gives the start.**

*Proof:* [`test_saved_outage_start.py`](../tests/test_saved_outage_start.py), [`test_saved_outage_start_cases.py`](../tests/test_saved_outage_start_cases.py), [`test_saved_outage_start_edges.py`](../tests/test_saved_outage_start_edges.py), [`test_outage_verdict_start.py`](../tests/test_outage_verdict_start.py), [`test_renamed_entities.py`](../tests/test_renamed_entities.py).

### UNAV-05 A Return Through a Restart

**A value handed back through a stack restart or Home Assistant's start is not the device speaking, whether or not the device is muted. A device muted for unavailable is a real return when its own outage began at least three minutes before the stack's hold began, or before Device Sentinel last listened. The stack's hold is under [UP](Rulebook__07_UP_Upstream_Outages.md).**

*Proof:* [`test_restart_handback.py`](../tests/test_restart_handback.py), [`test_integration_handback.py`](../tests/test_integration_handback.py), [`test_freeze_and_unavailable_mutes.py`](../tests/test_freeze_and_unavailable_mutes.py).

### UNAV-06 Dropping Out

**Three drops to unavailable within two hours make a device flapping. While it flaps, the longest time it stayed back between drops in the current run is learned, and it stays flapping until it has been back longer than that plus the freeze grace for a gap that size; the next run is learned afresh. It is one Problem List item in the Daily Brief's words, "dropped out 53 times since October 24, 2026 at 7:00 AM", the push and the brief saying the same, with one push and one bus event when it starts and one each when it clears; a drop inside a flap is recorded as an incident but neither pushed nor put on the bus. The device page reads Flapping, Signal Trends lists it under Devices That Keep Dropping Out, and the reason reads "Check its signal and the router it connects through." Dropping out counts as unavailable for the mutes: the unavailable mute takes it and the freeze mute does not. Its pushes stay in the three groups, Device, Battery and Signal, with no group of its own.**

*Proof:* [`test_flapping.py`](../tests/test_flapping.py), [`test_freeze_and_unavailable_mutes.py`](../tests/test_freeze_and_unavailable_mutes.py), [`test_problem_words.py`](../tests/test_problem_words.py), [`tools/panel_checks/check_dropping_out.js`](../tools/panel_checks/check_dropping_out.js).

### UNAV-07 How Long a Device Was Down

**A recovery's "down for", on the `device_sentinel_recovered` event and in the Daily Brief, counts from the device's last report when the trouble began as a freeze, and from when the device went down when it went straight to unavailable. How the trouble began is saved with the record, so a restart cannot change it; a damaged saved value is not trusted, and a standing freeze always began as a freeze. A device taken back from being set aside, then judged frozen a window later and reporting, or cleared with no report, counts from when it was taken back; one that came back already past its window counts from the opening. After a clock step, each "down for" counts from the step (FRZ).**

*Proof:* [`test_frozen_sentence_times.py`](../tests/test_frozen_sentence_times.py), [`test_unavailable_opening_time.py`](../tests/test_unavailable_opening_time.py), [`test_unwatched_time_cases.py`](../tests/test_unwatched_time_cases.py), [`test_recovery_one_way.py`](../tests/test_recovery_one_way.py).

### UNAV-08 "Became Unavailable"

**The Daily Brief's words are the standard: a device "became unavailable" and a hub "went down", in the brief, its event sentences and the push alike ("At 3:04 pm, Kitchen Motion became unavailable."). Each surface keeps its own sentence shape, so the Problem List, which lists a state, reads "unavailable".**

*Proof:* [`test_unavailable_opening_time.py`](../tests/test_unavailable_opening_time.py), [`test_brief_wording.py`](../tests/test_brief_wording.py), [`test_problem_words.py`](../tests/test_problem_words.py), [`test_lutron_hub.py`](../tests/test_lutron_hub.py).
