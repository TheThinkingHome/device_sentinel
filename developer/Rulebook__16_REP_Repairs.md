# Device Sentinel Rulebook: Repairs (REP)

*Version: rulebook, 28 October 2026, on Device Sentinel 0.27.13. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

This section covers what Device Sentinel raises in Home Assistant's Settings, Repairs, and how those cards behave. What is wrong with a device goes on the Problem List (LIST), never here. How storage is checked, repaired and restored is under [STOR](Rulebook__18_STOR_Storage.md). A lost clocks file is in [LIST-12](Rulebook__11_LIST_Problem_List.md#list-12-a-lost-clocks-file). Switched-off sensors are a recommendation under [REC](Rulebook__15_REC_Recommendations.md).

### REP-01 What a Repairs Card Is For

**A Repairs card is about what is wrong with Device Sentinel's ability to do its job, or with the plumbing beneath it. It is never about a device.**
- **Why:** each open card lights the Settings badge. A frozen sensor there would make Repairs a noisier copy of the Problem List and teach a person to ignore the badge.
- **Plumbing outages:** an outage of that plumbing never becomes a card. It is told on the Problem List and by its push (see [UP](Rulebook__07_UP_Upstream_Outages.md)).

*Proof:* [`test_repairs.py`](../tests/test_repairs.py).

### REP-02 The Four Cards

**Device Sentinel raises four cards: A Device Sentinel Notification Target No Longer Exists, Device Sentinel Restored Its Storage, Device Sentinel Repaired Its Storage, and Device Sentinel Repaired Its Storage Structure.**
- **The target card:** its fix removes the targets whose service is gone from the high-priority, normal-priority and Daily Brief lists, and leaves the rest alone.
- **The three storage cards:** they say what was done and where the originals are, and ask nothing.
- **Retired cards:** four older cards are retired and cleared for an install that still holds one: Cannot See Everything It Watches, Has Nowhere to Send Anything, The System Clock Was Reset or Paused, and Activity Clocks Were Reset.

*Proof:* [`test_repairs.py`](../tests/test_repairs.py), [`test_restore.py`](../tests/test_restore.py), [`test_clock_loss.py`](../tests/test_clock_loss.py).

### REP-03 One Card Per Problem

**Each kind of problem has one card, under a name that stays the same across releases. When the problem comes back, that card is updated. It is never joined by a second.**

*Proof:* [`test_repairs.py`](../tests/test_repairs.py).

### REP-04 A Card Lasts Only as Long as Its Cause

**A card is removed by its fix, or at the first judging moment after its condition clears ([REP-07](#rep-07-when-cards-are-judged)).**
- **Storage cards put down:** a storage card the person put down with Submit stays gone until a new repair to storage.
- **After a restart:** cards are not saved across a restart. Each start judges the conditions again and raises what still holds, after the startup grace, so a card can never outlive what it describes.

*Proof:* [`test_repairs.py`](../tests/test_repairs.py), [`test_restore.py`](../tests/test_restore.py), [`test_storage_card_acknowledged.py`](../tests/test_storage_card_acknowledged.py).

### REP-05 Severity

**A card is a warning.** Error is kept for setup and storage failing outright. Critical, Home Assistant's word for a house in danger, is never used. All four cards are warnings, since each describes something already handled or easily fixed.

*Proof:* [`test_repairs.py`](../tests/test_repairs.py), [`test_restore.py`](../tests/test_restore.py).

### REP-06 Fix and Ignore

**A card offers Fix only where there is something to fix or to put down. Any other card carries a link to the wiki.**
- **Cards with a fix:** the card shows its words on the fix screen's first step and carries no separate description.
- **The target card:** it opens with its fix and an Ignore side by side. The Ignore hides the card as Home Assistant's own would.
- **The three storage cards:** Restored Its Storage, Repaired Its Storage and Repaired Its Storage Structure have nothing to decide. Their fix is Home Assistant's own confirmation, with no Ignore, and Submit is the person's way to put the card down.

*Proof:* [`test_repairs_ignore.py`](../tests/test_repairs_ignore.py), [`test_repairs.py`](../tests/test_repairs.py).

### REP-07 When Cards Are Judged

**The conditions are judged when the startup grace closes and right after the scheduled Daily Brief is sent, and at no other routine moment.** Nothing is raised inside the startup grace.
- **Not at midnight:** nobody reads a card then, and a nightly restart would clear it before morning.
- **Not on each tick:** a card that comes back while it is being read is worse than one raised a few hours late.
- **After the send:** judging after the brief is sent means a card can never delay or stop the brief.

*Proof:* [`test_repairs.py`](../tests/test_repairs.py).

### REP-08 After a Restore

**When Device Sentinel restores its storage from the last-good copy, the Restored Its Storage card says why and what was lost.**
- **Home Assistant's card:** Home Assistant's own critical card about the same unreadable file tells a person to fix the file by hand or restore the whole system. It is then removed, since its advice is wrong once the file is back.
- **Limits:** only cards about Device Sentinel's own file are touched. A failed restore leaves Home Assistant's card standing.

*Proof:* [`test_restore.py`](../tests/test_restore.py).
