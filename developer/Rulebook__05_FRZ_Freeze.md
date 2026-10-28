# Device Sentinel Rulebook: Freeze (FRZ)

*Version: rulebook, 28 October 2026, on Device Sentinel 0.27.13. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

This section covers how Device Sentinel learns each device's reporting rhythm, how long it waits before calling a device frozen, which silences it learns from and which it sets aside, and how restarts, stops and clock steps are kept out of both. A device whose entities read unavailable is under [UNAV](Rulebook__06_UNAV_Unavailable.md). Freeze and unavailable mutes are under [MUTE](Rulebook__03_MUTE_Muting_and_Exclusion.md). Which devices are watched at all is under [WATCH](Rulebook__02_WATCH_What_Is_Watched.md). The stacks' own readers (ESPHome connections, Z-Wave dead nodes, Matter, hubs) are under [STACK](Rulebook__08_STACK_Stacks.md). Upstream outages are under [UP](Rulebook__07_UP_Upstream_Outages.md).

### FRZ-01 Learning Is Per Device

**Each device learns its own rhythm, all the time, with no learning mode to switch on or off.**
- **Arming floor:** a device is judged for freeze only once it has reached its arming floor of 7 learned days.
- **Before that:** it is watched for unavailable and never called frozen, because it has no window to miss.
- **After a reinstall:** a reinstall that wipes storage leaves each device unarmed until it has learned again.

*Proof:* [`test_freeze.py`](../tests/test_freeze.py), [`test_learning_rhythm.py`](../tests/test_learning_rhythm.py).

### FRZ-02 One Longest Gap a Day

**Each day keeps one figure for a device: the longest gap between two of its reports that ended that day.**
- **The day:** a device's day runs from local midnight to local midnight, in the system time zone.
- **Measured days only:** the freeze rules read only the days that were measured. Only the charts lay days out by the calendar.
- **The clock's seed:** a device's clock is seeded from its own clock entity alone, never from the recorder.

*Proof:* [`test_dated_histories.py`](../tests/test_dated_histories.py), [`test_daily_dates.py`](../tests/test_daily_dates.py), [`test_learning_rhythm.py`](../tests/test_learning_rhythm.py).

### FRZ-03 The 14-Day Trimmed Maximum

**The 14-Day Trimmed Maximum reads the newest 14 days' longest gaps, sets the longest one aside as a possible fluke, and takes the longest of the rest.**
- **What it gives:** one bad day moves nothing, while a long gap that comes back counts.
- **Always 14 days:** it reads 14 days whatever the How Much History to Keep setting keeps, so two houses with different settings judge alike. The one exception is the cap on a single gap ([FRZ-13](#frz-13-limits-on-a-learned-gap)).

*Proof:* [`test_freeze.py`](../tests/test_freeze.py), [`test_freeze_rules.py`](../tests/test_freeze_rules.py).

### FRZ-04 The 42-Day Log-Normal Percentile

**From a device's 28th measured day, the 42-Day Log-Normal Percentile reads up to its newest 42 days.**
- **How it works:** it works on the logarithm of each day's longest gap. It sets aside any day more than 2.5 spreads above or below the average, again until none is left. Then it takes the average of the rest plus 1.2816 spreads: the gap the device stays under on nine days out of ten.
- **Smallest spread:** the spread never reads below 0.15, so a device whose longest gap is nearly the same each day is not read as perfectly regular.
- **Its name:** each rule is named with the days it read, such as "37-Day Log-Normal Percentile".

*Proof:* [`test_freeze_rules.py`](../tests/test_freeze_rules.py).

### FRZ-05 The Wait in Use

**The wait in use is the shorter of the two rules. With only the Trimmed Maximum ready, or on a tie, it is the Trimmed Maximum.**
- **Starting the count again:** the Log-Normal Percentile starts its count again after a firmware update, a battery replacement Device Sentinel detects from the level, a re-pair, three days in a row set aside as longer than the device's usual, or a press of "Use the 14-Day Trimmed Maximum" on the device page. The device then waits on the Trimmed Maximum until it has 28 new days.
- **What does not restart it:** a replacement date a person enters, a reconfigure and a removal do not start the count again, since none of them changes how a device reports.
- **A re-pair on ZHA:** a join followed by its setup.
- **A re-pair on Zigbee2MQTT:** Zigbee2MQTT does not say which device was paired. There a re-pair is a device removed and added again while pairing is open or within 120 seconds after it closes, or one that was frozen, unavailable or silent past its window and comes back in that time. A device reporting on its rhythm while another is paired keeps its count.
- **On the device page:** the button shows only while the Log-Normal Percentile is in use, and while the count runs again the device page says why.

*Proof:* [`test_freeze_rules.py`](../tests/test_freeze_rules.py), [`test_repair_restarts_count.py`](../tests/test_repair_restarts_count.py), [`test_battery_last_replaced.py`](../tests/test_battery_last_replaced.py), [`tools/panel_checks/check_rhythm_rules.js`](../tools/panel_checks/check_rhythm_rules.js).

### FRZ-06 The Freeze Window and Its Sliders

**A device's freeze window is its wait in use plus a grace margin.**
- **The grace curve:** the grace follows a curve of the rhythm that passes through Delta Low at a 10-second rhythm and Delta High at a 24-hour rhythm. It never falls below Delta Low or rises above Delta High.
- **The sliders:** Delta Low runs 1 to 8 minutes, default 3. Delta High runs 4 to 12 hours, default 8. Both sit on the Freeze and Unavailable Detection screen.
- **Moving them:** moving either reshapes the whole curve, so a device in the middle of the house answers too. The sliders change how long Device Sentinel waits and never what it learns.

*Proof:* [`test_freeze.py`](../tests/test_freeze.py).

### FRZ-07 A Device Is Frozen

**An armed device is frozen when its silence reaches its freeze window while it is not judged unavailable.** Its silence counts only time Device Sentinel was listening ([FRZ-10](#frz-10-only-watched-silence-counts-against-a-device)).
- **Devices their stack speaks for:** these are never newly judged frozen. They are an ESPHome device that does not deep-sleep while Home Assistant's connection to it is up, whatever its entities read; a Matter device not behind a bridge, of a type that reports only on use, while any of its entities reads available; and a Lutron hub and the devices registered through it (see [STACK](Rulebook__08_STACK_Stacks.md)).
- **Unknown:** unknown counts as nothing, so a device whose deciding entities read only unknown is still judged by its freeze clock, unless its stack speaks for it as above (see [UNAV](Rulebook__06_UNAV_Unavailable.md)).
- **The verdict:** it is dated from the moment the counted silence reached the window. Its entity is refreshed only when the verdict changes, never on each reading. A frozen verdict clears the moment the device reports.
- **Devices never judged for freezing:** in place of a window, the device page and the Devices tab show "Judged by its hub, <hub>" with a link to the hub, or "Judged by its connection" for a hub itself and for an ESPHome device whose only entities switched on are notices or buttons.

*Proof:* [`test_freeze.py`](../tests/test_freeze.py), [`test_frozen_sentence_times.py`](../tests/test_frozen_sentence_times.py), [`test_esphome_connection.py`](../tests/test_esphome_connection.py), [`test_judged_by.py`](../tests/test_judged_by.py), [`tools/panel_checks/check_judged_by_line.js`](../tools/panel_checks/check_judged_by_line.js).

### FRZ-08 Silence Episodes

**A silence episode opens once a device's silence passes the rhythm in use ([FRZ-05](#frz-05-the-wait-in-use)) plus half its grace.** That is halfway to its freeze window, so it always opens before the device is called frozen.
- **Closing:** it closes when the device reports, or earlier when a restart or a bridge coming back cuts it short. Then the record names that cause and the time from it to the device's next report.
- **Fixed share:** the share is fixed, not a setting.
- **For reading only:** episodes are a record for reading. Nothing is judged on them.

*Proof:* [`test_reports.py`](../tests/test_reports.py), [`test_silence_episode_rhythm.py`](../tests/test_silence_episode_rhythm.py).

### FRZ-09 Never Reported

**A device is never reported when 48 hours by the wall clock have passed since it was first seen, and it has never reported, has no learned day, and owns at least one registered entity of its own, disabled or not.** A device with none has nothing that could report.
- **Checked first:** this is checked ahead of frozen and unavailable, because such a device has no rhythm for the freeze window to catch.
- **At startup:** a device first found never reported inside the startup window, and not already listed, stays off the list until the window closes.
- **Learned history wins:** a device with learned history is never judged never reported, whatever its clock says.
- **Lutron:** a Lutron hub and the devices registered through it are never judged never reported (see [STACK](Rulebook__08_STACK_Stacks.md)).
- **What the person does:** the person decides what it needs: fixing, deleting a stale entry, or a freeze mute.

*Proof:* [`test_freeze.py`](../tests/test_freeze.py), [`test_clock_loss.py`](../tests/test_clock_loss.py), [`test_freeze_unavailable_split.py`](../tests/test_freeze_unavailable_split.py).

### FRZ-10 Only Watched Silence Counts Against a Device

**A device's silence is what elapsed before Device Sentinel last saved plus what has elapsed since it started. The time it was stopped counts against no device.**
- **The last save:** it is exact after a clean stop and up to one write interval early after a crash, so the error gives credit rather than takes it.
- **After a clean stop:** a device already silent before the stop carries that silence into the total and is caught at the first sweep after the startup grace ([WATCH-10](Rulebook__02_WATCH_What_Is_Watched.md#watch-10-the-startup-grace)).
- **After an unclean stop:** only a device already on the Problem List keeps its silence, and each other device starts over ([FRZ-20](#frz-20-clean-and-unclean-stops)).
- **Upstream outages:** time an upstream was down is taken out the same way (see [UP](Rulebook__07_UP_Upstream_Outages.md)).

*Proof:* [`test_freeze.py`](../tests/test_freeze.py), [`test_shutdown_flush.py`](../tests/test_shutdown_flush.py), [`test_outage_credit.py`](../tests/test_outage_credit.py).

### FRZ-11 A Device's Clock

**Where a device has a last-contact entity (a Last Seen), its value is the device's clock for each report. The clock never moves backwards: the later of the stored and reported times wins.**
- **Not the device speaking:** a value a stack hands back from a cache, a bridge restoring the values of the devices behind it, or Home Assistant's restart is not the device speaking. It neither moves the clock nor ends a frozen verdict, for any device and any stack, muted or not.
- **Two exceptions:** in each, the return is a real return (see [UNAV](Rulebook__06_UNAV_Unavailable.md)). A device Device Sentinel had judged unavailable, muted or not, recovers when its stack says it is available. A device muted for unavailable whose own outage began at least three minutes before the stack's hold began, or before Device Sentinel last listened, recovers the same way.
- **Fetched readings:** a reading the integration fetches from the device itself when it connects is the device answering, for the integrations whose source shows they fetch (HomeKit Device and ESPHome).

*Proof:* [`test_freeze.py`](../tests/test_freeze.py), [`test_recovery_one_way.py`](../tests/test_recovery_one_way.py), [`test_restart_handback.py`](../tests/test_restart_handback.py), [`test_own_platform.py`](../tests/test_own_platform.py).

### FRZ-12 What a Completed Gap Teaches

**A gap the device ended itself is learned, even one that ends while it stands frozen.** A slow reporter learns the quiet spells it really has. But a gap is learned only if Device Sentinel could have heard the device for all of it.
- **Upstream outages:** an upstream outage on the device's path forgets the gap, unless the outage was shorter than the device's rhythm and lay wholly inside it from the last report. An outage still open counts as running to the report. A device with no rhythm yet forgets any gap an outage touched.
- **Clock jumps:** a jump of the system clock forgets the gap.
- **Clean stops:** Device Sentinel's own clean stop is the one exception. The gap is learned less the time stopped, so a nightly restart does not cost a slow reporter its longest gap.

*Proof:* [`test_learning_rhythm.py`](../tests/test_learning_rhythm.py), [`test_untrusted_gaps.py`](../tests/test_untrusted_gaps.py), [`test_outage_inside_rhythm.py`](../tests/test_outage_inside_rhythm.py), [`test_open_outage_learning.py`](../tests/test_open_outage_learning.py), [`test_frozen_recovery_learning.py`](../tests/test_frozen_recovery_learning.py).

### FRZ-13 Limits on a Learned Gap

**A gap is learned at most as long as the How Much History to Keep setting keeps.**
- **Longer silences:** a longer silence is stored as that length, and the reports show it as "more than N days". The device page shows the stored figure.
- **Longer than watched:** a stored gap longer than the time the device has been watched is forgotten at load, and the day reads as skipped in the history's dates. Where neither the device's first-seen time nor the install time can say how long it has been watched, nothing is forgotten.
- **Negative gaps:** a negative gap is damage, and the device's gap history is reset.

*Proof:* [`test_gap_bounds.py`](../tests/test_gap_bounds.py), [`test_learning_rhythm.py`](../tests/test_learning_rhythm.py), [`test_long_durations.py`](../tests/test_long_durations.py).

### FRZ-14 A Gap Across an Outage of the Device

**When a device as a whole goes unavailable or unknown and comes back, the gap around it is not learned if the outage lasted long enough.**
- **The limit:** the gap is not learned if the outage, less Device Sentinel's own downtime, lasted 10 minutes plus 10 percent of the device's whole freeze window (rhythm plus grace) or longer. A shorter one is a mesh blip, and the gap is learned. Both figures are fixed.
- **Unknown:** for this, unknown counts as gone, though for judging it counts as nothing (UNAV).
- **The reason kept:** a gap set aside this way records why: unclean shutdown, bridge down, unavailable or unknown, the widest cause first.
- **Learning only:** it changes learning only. The device is still watched, judged and reported.

*Proof:* [`test_taint_reasons.py`](../tests/test_taint_reasons.py), [`test_saved_outage_start_cases.py`](../tests/test_saved_outage_start_cases.py), [`test_learning_rhythm.py`](../tests/test_learning_rhythm.py).

### FRZ-15 A Person's Hand Is Not Learned

**A device that came back because a person handled it did not recover on its own, and its gap is set aside.**
- **The detectors, in order:** a Zigbee2MQTT pairing window, a device set aside, a ZHA device a person handled, Maintenance Mode, and a commanded recovery.
- **What matters:** whether a person caused the return. A network healing itself, such as a Z-Wave SmartStart rejoin, is learned.
- **Setting a gap aside:** this puts back the day's longest gap from before it.
- **A detector that fails:** a detector that fails or cannot read its stack does nothing, and the outage rule ([FRZ-14](#frz-14-a-gap-across-an-outage-of-the-device)) decides. So a detector can only cost a caught intervention, never spoil a gap.
- **Z-Wave and Matter:** they have no detector. Maintenance Mode is how a person says so there.

*Proof:* [`test_bridge_pairing.py`](../tests/test_bridge_pairing.py), [`test_maintenance.py`](../tests/test_maintenance.py), [`test_device_handled.py`](../tests/test_device_handled.py), [`test_set_aside.py`](../tests/test_set_aside.py), [`test_frozen_recovery_learning.py`](../tests/test_frozen_recovery_learning.py).

### FRZ-16 Pairing on Zigbee2MQTT

**A device behind Zigbee2MQTT that comes back while its bridge is open for pairing, or within 120 seconds after it closes, has its gap set aside as pairing.**
- **Which devices:** any device on the MQTT integration counts, since pairing is open for the whole coordinator. A non-Zigbee2MQTT MQTT device coming back by chance loses one gap.
- **Diagnostics:** the bridge's state is in the diagnostics download.

*Proof:* [`test_bridge_pairing.py`](../tests/test_bridge_pairing.py).

### FRZ-17 A ZHA Device Handled by a Person

**ZHA names the device a person re-pairs, reconfigures or removes, seconds before its entities return, and that device's gap is set aside.** The mark lasts 60 seconds after ZHA's last message about the device.
- **Full initialisation:** it counts only after a raw initialisation for the same address (a Reconfigure, or a new device being paired), or after a join while pairing is open, within 15 minutes and until ZHA calls the device initialized. A full initialisation alone, or a join with pairing closed, sets nothing aside.
- **When pairing is open:** for as long as the zha.permit action asks, or up to 254 seconds after ZHA's Add Device page last relays its log.
- **Pairing alone:** ZHA keeps no pairing window of its own, and pairing being open never sets a gap aside by itself. It only decides whether a join counts.
- **Not seen:** a join opened from a button on a router or by Touchlink. Nor a reset device that re-pairs and gets its old network address back, since ZHA sends nothing about it.

*Proof:* [`test_device_handled.py`](../tests/test_device_handled.py), [`test_zha_join_observer.py`](../tests/test_zha_join_observer.py), [`test_zha_reader.py`](../tests/test_zha_reader.py).

### FRZ-18 Maintenance Mode

**The Maintenance Mode button declares a person at work on the hardware, for the whole house. A device that comes back inside it has its gap set aside.**
- **How long:** 10 minutes by default, 5 to 60 under Advanced (Maintenance Window in Minutes).
- **When it ends:** the window ends when it runs out, at a second press, or at a restart, exactly, with no grace after.
- **Failures during it:** a device that fails during it is detected, listed and pushed as usual. Where a pairing window is open too, pairing is named.
- **The record:** a timestamp sensor holds the window's end and reads unknown when closed. The opening and closing are kept, and a restart mid-window gets its closing row at the next start.

*Proof:* [`test_maintenance.py`](../tests/test_maintenance.py).

### FRZ-19 A Commanded Recovery

**A commanded recovery is a report that clears a frozen verdict within a short window after a command to any of that device's entities, from a person or an automation.**
- **What happens:** the verdict clears, because the device answered. The gap is set aside, because a toggle says nothing about its rhythm.
- **Presses on the device:** a press on the device itself sends no command and is not seen.
- **The window:** 60 seconds, a first figure to be measured on the rig before it is settled.

*Proof:* [`test_frozen_recovery_learning.py`](../tests/test_frozen_recovery_learning.py).

### FRZ-20 Clean and Unclean Stops

**A stop Device Sentinel was not asked for is an unclean shutdown.**
- **After an unclean stop:** each device not on the Problem List starts its clock again at the new start, and nothing of the silence before the stop is learned. A device already on the list, for any kind of problem, keeps its clock, so a known fault is not forgiven.
- **Open episodes:** an open silence episode closes at the last moment Device Sentinel was known alive, and the unclean restart is a system event.
- **After a clean stop:** clocks stand and the stopped time is credited ([FRZ-10](#frz-10-only-watched-silence-counts-against-a-device)).

*Proof:* [`test_unclean_restart.py`](../tests/test_unclean_restart.py), [`test_shutdown_flush.py`](../tests/test_shutdown_flush.py).

### FRZ-21 The System Clock Steps

**A clock step is a change of 5 minutes or more, backward or forward, between the system clock and Device Sentinel's own steady clock, between two minute checks. A pause of the host for that long is one too.**
- **Time across a step is unknown:** each device clock and saved outage start restarts at the moment the step is noticed. An outage running across it is not learned. Each verdict stands until the device reports. Credit for downtime before the step is dropped, and each "down for" afterwards counts from the step.
- **What moves:** moments held in memory, such as the startup grace and Maintenance Mode, move by the step's size. Stored history does not.
- **The record:** the step is kept as a system event, which the Daily Brief tells. There is no Repair card.

*Proof:* [`test_clock_steps.py`](../tests/test_clock_steps.py), [`test_clock_loss.py`](../tests/test_clock_loss.py), [`test_untrusted_gaps.py`](../tests/test_untrusted_gaps.py).

### FRZ-22 The Rhythm Charts

**The device page charts both rules, with a paragraph beneath them on why there are two.**
- **The two charts:** "N-Day Trimmed Maximum" with its set-aside day hatched, and "N-Day Log-Normal Percentile" with its set-aside days grey. Each shows its result as a red line, and the one in use is tagged.
- **The rhythm chart:** it draws both waits as dashed lines. A line above it follows the day under the pointer, with that day's rule in use, its wait, the other rule's wait and the day that set the trimmed wait. The chart rings that day and crosses the day it set aside. Away from the chart, both marks rest on today.
- **Other places:** the History chart keeps its title. The status bar and the Devices tab show the rhythm of the rule in use.
- **Not stored:** the chart's history is worked out on each request and kept nowhere, since everyday running matters more than browsing.
- **In Simple:** the rhythm chart, its figures and the rhythm statistics show only for a device frozen or never reported (see [DASH](Rulebook__14_DASH_Dashboard.md)).

*Proof:* [`tools/panel_checks/check_rhythm_rules.js`](../tools/panel_checks/check_rhythm_rules.js), `check_rhythm_words.js`, `check_dated_histories.js`, [`test_dashboard_history.py`](../tests/test_dashboard_history.py).

### FRZ-23 The Wait Behind the Scenes

**Each device's wait is kept in memory and worked out again only when its inputs change: its day list, the count since a restart of the Log-Normal Percentile, or the Freeze and Unavailable Detection settings.**
- **Device Telemetry:** it names the rule in use for each device and carries a daily count line: how many devices used each rule, and how many frozen listings the Log-Normal Percentile made that the Trimmed Maximum would not have.

*Proof:* [`test_freeze_rules.py`](../tests/test_freeze_rules.py), [`test_reports.py`](../tests/test_reports.py).

### FRZ-24 Testing a Freeze Rule

**A freeze rule is judged on the habit-based week, where each device reports at its own recorded habit. It is never judged on the original chaos week, whose random hourly reporting makes each fast device look silent.**

*Proof:* none found.
