# Project doc update for 0.6.1 (2026-07-21)

Paste-ready. One diary entry with rulings 95 and 96, appended after the 0.6.0 entry. The status block's "0.6.0 built and gated" line can stay; if you want it current, swap the version to 0.6.1 and add the clause noted below.

---

## Optional status-line clause

At the end of the 0.6.0 status block, append: The 0.6.1 follow-up surfaced the todo state where a person and a maintainer read it: the telemetry STATUS cell shows a fault's problem-list state (open, acknowledged, or a fault present but no item), and the diagnostics download carries the additions journal beside the items, so a downloaded file reflects the whole todo layer.

---

## New diary entry

### 2026-07-21 (later still), 0.6.1: the todo state made legible

0.6.0 shipped the populated list; deploying it exposed a reading gap on both ends. A diagnostics download carried the todo items but not the additions journal, so a download could not show whether the notification-facing half of the layer was working, and the first-fleet download proved it: two correct items, FJ40 not_reported and Window Living Room Left signal (rail), but no journal to corroborate the additions. And the nightly reports named a fault but not whether it had reached the list or been acknowledged, which is the thing a person acts on. Both fixed here, no engine change.

The STATUS cell gained a todo icon for a Reported device with a fault (#95): (○) listed and open, (✓) acknowledged, (✗) a fault present but no item. The four-way rule matters: the icon is judged against the union of the three problem lists, not against the todo alone, so a healthy Reported device wears no icon and only a genuine fault earns one. The (✗) state is the hand-delete window before the sync re-adds, near-instant in normal operation, which makes it a free health check: a device sitting at (✗) across a nightly report is a sync that stopped re-adding. The icon lives in the existing STATUS cell in parentheses, not a new column, so the table width is unchanged.

The diagnostics download gained todo_journal beside todo_items (#96), the one-line change banked when the journal was built. It belongs in the JSON because a feed of timestamped events has no clean home in a per-device table, and it belongs in the download because most notification questions, once Step 8 exists, are journal questions: a download that carries it answers them without an SSH session into .storage.

Gates: 197 tests (7 new), three stable runs, ruff clean, bandit zero, strings/en byte-parity untouched.

### Rulings 95 and 96 (2026-07-21)

95. **The telemetry STATUS cell shows a fault's problem-list state as an icon.** A Reported device with a fault carries (○) open, (✓) acknowledged, or (✗) fault-present-no-item in parentheses after Reported; a healthy Reported device stays plain. Judged against the union of the three problem lists so only a real fault earns an icon. The (✗) case is the post-hand-delete window and doubles as a sync health check. In the existing cell, not a new column.

96. **The additions journal is surfaced in the diagnostics download.** todo_journal joins todo_items in the JSON, so a download reflects the whole todo layer: current items and the addition history the notification engine will act on. A feed belongs in JSON, not in a per-device table; the download is where a maintainer reads it.
