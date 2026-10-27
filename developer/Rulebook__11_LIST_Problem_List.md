# Device Sentinel Rulebook: Problem List (LIST)

*Version: rulebook, 27 October 2026, on Device Sentinel 0.27.10. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

The Problem List is Home Assistant's to-do list of what is wrong with the house's devices. This section covers what an item is, the kinds of problem and their words, acknowledgment, the order, when a problem is announced, what counts as a recovery and how an item leaves. What a push, the persistent card and the bus events do with an item is under [NOTE](Rulebook__12_NOTE_Notifications.md). How each problem is judged is under [FRZ](Rulebook__05_FRZ_Freeze.md), UNAV, BAT and SIG; an upstream outage is under [UP](Rulebook__07_UP_Upstream_Outages.md); muting is under [MUTE](Rulebook__03_MUTE_Muting_and_Exclusion.md); the Problem List tab on the dashboard is under [DASH](Rulebook__14_DASH_Dashboard.md).

### LIST-01 One Item Per Device

**The Problem List holds one item per device, keyed by its Home Assistant device and named by the person's name for it. A device with several problems carries them as kinds on that one item, never as two items. Device Sentinel owns the list: there is no add box, an item typed by hand is removed at setup, and each item's text is rewritten from the detections at each change, so an edit does not stick.**

*Proof:* [`test_todo.py`](../tests/test_todo.py).

### LIST-02 The Kinds and Their Words

**There are eight kinds: flapping, unavailable, frozen, unknown, never reported, low battery, falling battery and railed signal. Each surface that puts a kind into words, the push, the notification card and the Problem List among them, uses the Daily Brief's word for it in its own sentence shape, so a raw key never reaches a person: flapping "dropped out N times", unavailable "became unavailable" (a hub "went down"), frozen "stopped reporting", unknown "went unknown", "never reported", a low battery "battery crossed the threshold on Oct 24. Its current level is 14%" (see [BAT](Rulebook__09_BAT_Battery.md)), a falling battery "battery running down" and "signal railed". Their stored names are fixed, because automations trigger on them: flapping, unavailable, frozen, unknown, never_reported, low_battery, falling_battery, railed_signal. They form three families: the first five are a device not reporting, the two battery kinds are battery, and railed signal is signal. Worst first, the order is the one above. An upstream outage stands in for the devices behind it with a row of its own, which is not a kind (see [UP](Rulebook__07_UP_Upstream_Outages.md)).**

*Proof:* `test_citations.py`, [`test_falling_surfaces.py`](../tests/test_falling_surfaces.py), [`test_notifications.py`](../tests/test_notifications.py), [`test_brief_wording.py`](../tests/test_brief_wording.py), [`test_problem_words.py`](../tests/test_problem_words.py).

### LIST-03 Acknowledgment

**Ticking an item acknowledges it. The item stays on the list, keeps its check time and keeps updating as kinds join or leave. A ticked item is silent on the phone until the device's last problem clears, and then its recovery is pushed; the bus still hears each change, so automations keep working. The acknowledgment covers the device, not one kind, so a new problem joining the item does not undo it. It lasts until the device's last problem clears and the item is deleted, so the next failure is a new problem. Unticking reopens the item and its fault fires on the bus again, marked as a renewal. Deleting an item whose problem still stands is the firmer undo: the item comes back and its fault fires on the bus again. Neither is announced on the phone, since the person just acted on the item.**

*Proof:* [`test_todo.py`](../tests/test_todo.py), [`test_falling_surfaces.py`](../tests/test_falling_surfaces.py).

### LIST-04 The Order

**Open items come first, by device name; acknowledged items follow, oldest acknowledgment first, so the checked block reads as a steady history. A person's own reordering does not stick.**

*Proof:* [`test_todo.py`](../tests/test_todo.py).

### LIST-05 The Additions Journal

**Each new item, and each kind joining an item, adds the device, its name, the kind and the time to a journal of the newest 100 entries. The pushes are worked out by the same pass that updates the list, not from the raw detections. The diagnostics download carries the journal (see [STOR](Rulebook__18_STOR_Storage.md)).**

*Proof:* [`test_todo.py`](../tests/test_todo.py).

### LIST-06 A Problem Is Announced Once

**These guards hold on the phone and the bus alike. A kind arriving on an item that already carries a kind of the same family is the same problem said differently and is not announced again, so a worsening inside the family, such as frozen becoming unavailable, sends no push and no new fault; a kind of another family is announced. The one exception is a battery: one running down that crosses into low is announced, on the phone and the bus alike. A kind that ends and returns within 60 seconds carries on the problem that just closed: the item stays, the record keeps one opening, and nothing is announced. So an item whose last problem clears stays on the list for 60 seconds before it is deleted, and its recovery is announced then, dated when it cleared; inside the startup window the item goes at once and its recovery waits for the window to shut (see [WATCH-10](Rulebook__02_WATCH_What_Is_Watched.md#watch-10-the-startup-grace)). A device whose entities are in the registry but have not yet loaded keeps the verdict it had. An entity that reads unknown because nothing has arrived from it since the start counts for nothing: it starts no unknown problem, and it ends none. It counts once it has given a value in this run. The kind a move inside the family leaves is no recovery (see [LIST-08](#list-08-a-recovery-goes-one-way)).**

*Proof:* [`test_incident_settling.py`](../tests/test_incident_settling.py), [`test_escalation_read.py`](../tests/test_escalation_read.py), [`test_todo.py`](../tests/test_todo.py).

### LIST-07 A Worse Problem Replacing a Lesser One

**A kind that ends because a worse one took its place in the same pass is a change, not a recovery: its record is marked, it names no cause, it is not counted as a problem that ended, and it reads as one change, "was marked unavailable from frozen", or "battery was marked low from running down" for a forecast coming true. A record from before 0.22.26 carries no mark and reads as it did. The bus treats it the same way (see [LIST-08](#list-08-a-recovery-goes-one-way)).**

*Proof:* [`test_escalation_read.py`](../tests/test_escalation_read.py), [`test_todo.py`](../tests/test_todo.py).

### LIST-08 A Recovery Goes One Way

**A recovery is announced only when a device that was not reporting, for any reason, starts reporting again. Frozen to unavailable is the device getting worse, never a recovery. Unavailable to frozen happens only in a restart of Home Assistant or a coordinator, is false, and is not reported. This holds on the bus, in the record, in the Daily Brief and on the phone.**

*Proof:* [`test_recovery_one_way.py`](../tests/test_recovery_one_way.py), [`test_freeze_unavailable_split.py`](../tests/test_freeze_unavailable_split.py).

### LIST-09 An Item That Leaves Without Recovering

**When an item leaves because its device stopped being watched (set aside, excluded or removed from Home Assistant), it leaves silently: the record says the device was set aside, or "removed from Home Assistant" for a removal, not that the problem ended, and the bus hears a withdrawal (see [NOTE](Rulebook__12_NOTE_Notifications.md)). An item that leaves because a person muted the device leaves silently too (see [MUTE](Rulebook__03_MUTE_Muting_and_Exclusion.md)). A device that stops being watched loses its verdict at once. A device set aside keeps its record, its counts and its history; an excluded device's record is discarded at the next local midnight (see [MUTE](Rulebook__03_MUTE_Muting_and_Exclusion.md)), and a removed device's is held 30 days (see [WATCH](Rulebook__02_WATCH_What_Is_Watched.md)). How long a recovered device was down is measured from when its trouble began, not from the item's own older stamp. For a device not reporting, trouble that began as a freeze counts from the device's last report; trouble that began as unavailable or unknown counts from when it went; a device taken back from being set aside counts from when it was watched again. Other kinds, and any case without those times, count from the opening of the problem the recovery closes. That figure is the length on the bus and in the record.**

*Proof:* [`test_set_aside_silent.py`](../tests/test_set_aside_silent.py), [`test_exclusions.py`](../tests/test_exclusions.py), [`test_journal.py`](../tests/test_journal.py), [`test_removed_hold.py`](../tests/test_removed_hold.py).

### LIST-10 Never Reported Is Dated Discovered

**A never-reported device's time reads "discovered", since it is when watching began, not when anything failed. A device that has ever spoken leaves the kind for good, and one with learned history is never never reported, whatever its clock says.**

*Proof:* [`test_brief_wording.py`](../tests/test_brief_wording.py), [`test_clock_loss.py`](../tests/test_clock_loss.py), [`test_problem_words.py`](../tests/test_problem_words.py), [`tools/panel_checks/check_problem_list.js`](../tools/panel_checks/check_problem_list.js).

### LIST-11 An Opening Is Kept While Its Item Stands

**The record of when a problem opened is kept for as long as the problem is on the list, whatever its age. Once the problem leaves the list, by recovering, by deletion, by a mute, or by the device being set aside, it ages out on the usual 14 days; unmuting opens a fresh problem. An excluded device's record goes at the next local midnight instead (see [LIST-09](#list-09-an-item-that-leaves-without-recovering)). An acknowledgment does not release it, since the item stays on the list.**

*Proof:* [`test_journal.py`](../tests/test_journal.py).

### LIST-12 A Lost Clocks File

**When the file holding each device's last report time is missing or damaged at a start, each device with learned history, or first seen more than 48 hours before and not stored as never reported, has its clock restarted at that load, and the time before counts as unwatched. A device frozen when the clocks were lost stays frozen until it reports. A system event and a Daily Brief sentence name the moment; no Repairs card is raised.**

*Proof:* [`test_clock_loss.py`](../tests/test_clock_loss.py), [`test_storage_tables.py`](../tests/test_storage_tables.py).

### LIST-13 An Outage Row Carries Its Time

**The row standing in for an upstream outage is dated from the moment the upstream went down, for each kind of upstream: a broker, a bridge, a Wi-Fi network or a whole integration, an integration dated from the first of its entries to fall. The push that goes with it carries no time; the moment the upstream went down decides when the push may go, once the outage has settled (see [UP](Rulebook__07_UP_Upstream_Outages.md)).**

*Proof:* [`test_entry_outages.py`](../tests/test_entry_outages.py), [`test_upstream_reporting.py`](../tests/test_upstream_reporting.py).
