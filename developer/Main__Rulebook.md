# Device Sentinel Rulebook

*Version: rulebook, 28 October 2026, on Device Sentinel 0.27.13.*

**What this is.** Each rule Device Sentinel follows, in plain words, grouped by subject into twenty sections, one file each. A rule says what holds today; under it, a Proof line names the tests that check it. The rulebook is the contract the code is written to: code comments and docstrings cite a rule by its ID, written "(rule [BAT-13](Rulebook__09_BAT_Battery.md#bat-13-how-long-a-battery-has-left))", after the reason in plain words.

**Status.** Adopted. The code follows these rules, and every comment and docstring cites them by ID. A change to how Device Sentinel behaves changes its rule here first.

## How the IDs Work

- **A rule ID names a subject and never changes:** [BAT-13](Rulebook__09_BAT_Battery.md#bat-13-how-long-a-battery-has-left) is how long a battery has left, whatever is decided about it later. A change rewrites the rule's text; the ID stays.
- **A number is given once.** It is never reused or renumbered. A new rule takes the next free number in its section, so numbers can run out of order on the page.
- **A retired rule keeps its ID,** marked "Retired." with a pointer to what replaced it, so an old citation never leads nowhere.
- **One home for each rule.** A rule lives where a reader would look for it first. A rule that touches another section points there by the section's code.

## Sections

290 rules in all.

| Code | Section | Rules | File |
|---|---|---|---|
| GEN | General | 10 | [`Rulebook__01_GEN_General.md`](Rulebook__01_GEN_General.md) |
| WATCH | What Is Watched | 12 | [`Rulebook__02_WATCH_What_Is_Watched.md`](Rulebook__02_WATCH_What_Is_Watched.md) |
| MUTE | Muting and Exclusion | 10 | [`Rulebook__03_MUTE_Muting_and_Exclusion.md`](Rulebook__03_MUTE_Muting_and_Exclusion.md) |
| DEV | Device Identity | 16 | [`Rulebook__04_DEV_Device_Identity.md`](Rulebook__04_DEV_Device_Identity.md) |
| FRZ | Freeze | 24 | [`Rulebook__05_FRZ_Freeze.md`](Rulebook__05_FRZ_Freeze.md) |
| UNAV | Unavailable | 8 | [`Rulebook__06_UNAV_Unavailable.md`](Rulebook__06_UNAV_Unavailable.md) |
| UP | Upstream Outages | 18 | [`Rulebook__07_UP_Upstream_Outages.md`](Rulebook__07_UP_Upstream_Outages.md) |
| STACK | Stacks | 13 | [`Rulebook__08_STACK_Stacks.md`](Rulebook__08_STACK_Stacks.md) |
| BAT | Battery | 18 | [`Rulebook__09_BAT_Battery.md`](Rulebook__09_BAT_Battery.md) |
| SIG | Signal | 15 | [`Rulebook__10_SIG_Signal.md`](Rulebook__10_SIG_Signal.md) |
| LIST | Problem List | 13 | [`Rulebook__11_LIST_Problem_List.md`](Rulebook__11_LIST_Problem_List.md) |
| NOTE | Notifications | 12 | [`Rulebook__12_NOTE_Notifications.md`](Rulebook__12_NOTE_Notifications.md) |
| BRIEF | Daily Brief | 16 | [`Rulebook__13_BRIEF_Daily_Brief.md`](Rulebook__13_BRIEF_Daily_Brief.md) |
| DASH | Dashboard | 16 | [`Rulebook__14_DASH_Dashboard.md`](Rulebook__14_DASH_Dashboard.md) |
| REC | Recommendations | 11 | [`Rulebook__15_REC_Recommendations.md`](Rulebook__15_REC_Recommendations.md) |
| REP | Repairs | 8 | [`Rulebook__16_REP_Repairs.md`](Rulebook__16_REP_Repairs.md) |
| CFG | Settings | 10 | [`Rulebook__17_CFG_Settings.md`](Rulebook__17_CFG_Settings.md) |
| STOR | Storage | 24 | [`Rulebook__18_STOR_Storage.md`](Rulebook__18_STOR_Storage.md) |
| REL | Releases | 17 | [`Rulebook__19_REL_Releases.md`](Rulebook__19_REL_Releases.md) |
| CODE | Code and Tests | 19 | [`Rulebook__20_CODE_Code_and_Tests.md`](Rulebook__20_CODE_Code_and_Tests.md) |
