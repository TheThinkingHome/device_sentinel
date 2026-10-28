# Device Sentinel Rulebook: Notifications (NOTE)

*Version: rulebook, 28 October 2026, on Device Sentinel 0.27.11. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

How Device Sentinel tells people and automations about the Problem List: phone pushes, the two priority tiers, quiet hours, the persistent card and the bus events, and the words they share with the Daily Brief. What reaches the Problem List, and when a change counts as new or as a recovery, is under [LIST](Rulebook__11_LIST_Problem_List.md). The Daily Brief itself, its targets and its email are under [BRIEF](Rulebook__13_BRIEF_Daily_Brief.md). The push for an upstream outage is under [UP](Rulebook__07_UP_Upstream_Outages.md). Repairs cards are under [REP](Rulebook__16_REP_Repairs.md).

### NOTE-01 One Record, Many Readers

**The incident record is the one source. Each channel (push, card, Daily Brief, email) is a reader over it and none works out its own truth. Each problem has one word, the Daily Brief's, and each surface uses it in its own sentence shape, so an event is never described two ways. An event sentence carries its time; a line about a device carries its state and no time.**

*Proof:* [`test_notifications.py`](../tests/test_notifications.py), [`test_problem_words.py`](../tests/test_problem_words.py).

### NOTE-02 Two Priority Tiers

**High-priority targets receive each live push as problems appear and clear, at any hour, Quiet Hours included. Normal-priority targets receive each live push except during Quiet Hours. The tiers differ in Quiet Hours, not in urgency or content. The Daily Brief goes to neither tier; it goes only to Send the Full Brief To (see [BRIEF](Rulebook__13_BRIEF_Daily_Brief.md)).**

*Proof:* [`test_priority_targets.py`](../tests/test_priority_targets.py), [`test_settings_screen_text.py`](../tests/test_settings_screen_text.py), [`test_notifications.py`](../tests/test_notifications.py), [`test_settings.py`](../tests/test_settings.py).

### NOTE-03 One Push Per Family

**A live push belongs to one of three families, titled Device, Battery and Signal, and each family's push replaces its own last message on the phone rather than stacking. Each push reads the line that just happened, then "Summary:" and the family's current, unacknowledged state, so the newest push always says what is true. A recovery sends its family's push again, so a summary never claims a problem that has cleared. Several changes in one family at once make one push. Nothing is pushed inside the startup grace.**

*Proof:* [`test_notifications.py`](../tests/test_notifications.py), [`test_todo.py`](../tests/test_todo.py).

### NOTE-04 A Fault Sounds, a Recovery Is Silent

**A fault plays the phone's own notification sound, never a forced one. A recovery, and a later message about an outage already announced, is sent silently on Android and Apple alike.**

*Proof:* [`test_notifications.py`](../tests/test_notifications.py), [`test_upstream_reporting.py`](../tests/test_upstream_reporting.py).

### NOTE-05 A Push Names Three Devices

**A push's summary names the three worst devices, worst first and then most recent, and counts the rest ("and 4 more devices"). An outage's count of devices gone quiet is never cut. The persistent card names three devices on each line in the same way and ends with its link to the Problem List. The Problem List, the Daily Brief and the dashboard name each device, and In Short is never cut (see [BRIEF](Rulebook__13_BRIEF_Daily_Brief.md)).**

*Proof:* [`test_escalation_and_limits.py`](../tests/test_escalation_and_limits.py), [`test_upstream_reporting.py`](../tests/test_upstream_reporting.py).

### NOTE-06 A Fault Waits Its Device's Share

**A fault waits a share of its device's own learned reporting gap, 30 percent, before it is pushed, so a device that reports within seconds waits briefly and one that reports a few times a day waits far longer. A problem that heals inside the wait is never pushed, and its recovery sends nothing either. There is no minimum under the share. A device with nothing learned yet pushes at once. The wait delays only the push; the Problem List, the card and the brief show the problem straight away.**

*Proof:* [`test_notifications.py`](../tests/test_notifications.py), [`test_settings.py`](../tests/test_settings.py).

### NOTE-07 Quiet Hours

**Quiet Hours are off until a person turns them on, and run from 22:00 to 08:00 by default. The screen reads: "During these hours, Normal-Priority Targets are sent nothing and High-Priority Targets are still sent all alerts. The Daily Brief reports what happened." The one-time notice that a storage file could not be read and was replaced from the last-good copy follows the same rules as a push (see [STOR](Rulebook__18_STOR_Storage.md)). A push to a normal-priority target that falls inside them is dropped, never kept for later. Quiet Hours stop pushes to normal-priority targets and nothing else: the persistent card, the Daily Brief and the bus events go on as usual. Nothing runs when Quiet Hours end; the Problem List, the card and the Daily Brief carry the night.**

*Proof:* [`test_notifications.py`](../tests/test_notifications.py), [`test_priority_targets.py`](../tests/test_priority_targets.py).

### NOTE-08 Acknowledgment Silences People

**An acknowledged device is left out of each push summary, the persistent card and the Daily Brief, standing state and history alike, with no mark; the brief's Repeat Offenders keeps it, since that is a seven-day pattern (see [BRIEF](Rulebook__13_BRIEF_Daily_Brief.md)). A ticked item is silent on the phone until the device's last problem clears: a kind joining it, a kind leaving it or its getting worse sends no push. Its last problem clearing is news: the item is deleted and the recovery is pushed, and a later fault is a new one. The bus still hears each change (see [NOTE-12](#note-12-the-bus-events)), so automations keep working. It still appears in Device Telemetry, the classification file, the episode record and the diagnostics download, which are for checking rather than telling.**

*Proof:* [`test_notifications.py`](../tests/test_notifications.py), [`test_falling_surfaces.py`](../tests/test_falling_surfaces.py), [`test_todo.py`](../tests/test_todo.py).

### NOTE-09 Acknowledge From the Phone

**Retired.** A push carries no Acknowledge action: one push covers a whole family of problems, so there is no single device for it to act on. An item is acknowledged by ticking it on the Problem List ([LIST-03](Rulebook__11_LIST_Problem_List.md#list-03-acknowledgment)).

### NOTE-10 The Same Words Everywhere

**A device reads the same on the card, the push, the Daily Brief and the Problem List, in the Daily Brief's word for each problem: a frozen device "stopped reporting", an unavailable one "became unavailable" (a hub "went down"), a device that never spoke "never reported", a railed signal "signal railed", never "low" and never the internal kind word. A low battery reads as the brief words it, "battery crossed the threshold on <date>. Its current level is <N>%." (see [BAT-03](Rulebook__09_BAT_Battery.md#bat-03-low-battery)). A fault line is written as a sentence, "At 5:29 pm, Door 2nd Bedroom battery is running down, empty in about 2 weeks". A recovery names what lifted, "battery is no longer low" or "battery is no longer running down". A new kind is not sent until each table that words a push and each line of the card knows it. No push and no Problem List item adds a line that the device is a battery device.**

*Proof:* [`test_notifications.py`](../tests/test_notifications.py), [`test_problem_words.py`](../tests/test_problem_words.py), [`test_recovery_wording.py`](../tests/test_recovery_wording.py), [`test_falling_surfaces.py`](../tests/test_falling_surfaces.py).

### NOTE-11 The Persistent Card

**The persistent card shows the house's current trouble, one line each for Device, Battery and Signal, and reads "All devices reporting." when nothing is wrong. A card that lists anything ends with a link, Open the Problem List; the all-clear and the pushes carry none. It is rewritten only when its words change, and is never held back by Quiet Hours. A new install starts with it off; an install from before 0.22.5 that never saved the setting keeps it on, and a saved setting is never touched. Turning it off removes the card.**

*Proof:* [`test_notifications.py`](../tests/test_notifications.py), [`test_persistent_default.py`](../tests/test_persistent_default.py).

### NOTE-12 The Bus Events

**Device Sentinel puts six events on the Home Assistant bus, at the edge of the Problem List and nowhere else:**
- **`device_sentinel_fault`** when a device's line is added, gains a family it did not have, or carries a battery running down that crosses into low: once per device, its kinds worst first, with "renewed" when an unticked item comes back, and the battery level and battery type or the signal value when a kind needs them.
- **`device_sentinel_recovered`** when the worst kind on a line clears, with how long it lasted and what ended it; the next kind fires in turn when it clears. A device that has stopped reporting recovers only when it reports again: frozen giving way to unavailable, or unavailable to frozen, while it stays silent fires no recovery. It means the worst thing is no longer wrong, not that the device is well.
- **`device_sentinel_acknowledged`** when a person ticks the item. Unticking has no event of its own; the fault fires again, renewed.
- **`device_sentinel_withdrawn`** when a line leaves without a recovery, with its kinds and the reason: set_aside, muted or removed.
- **`device_sentinel_upstream_down` and `device_sentinel_upstream_restored`** for an outage (see [UP](Rulebook__07_UP_Upstream_Outages.md)).

**Quiet Hours never hold an event. Nothing fires inside the startup grace, except a withdrawal and a restore owed to an outage announced before the restart. A device that really reports inside the grace leaves the Problem List at once, and its recovery event is held and fired when the grace closes (see [WATCH-10](Rulebook__02_WATCH_What_Is_Watched.md#watch-10-the-startup-grace)).**

*Proof:* [`test_todo.py`](../tests/test_todo.py), [`test_set_aside_silent.py`](../tests/test_set_aside_silent.py), [`test_upstream_reporting.py`](../tests/test_upstream_reporting.py), [`test_events_hostile.py`](../tests/test_events_hostile.py).
