# Device Sentinel Rulebook: Code and Tests (CODE)

*Version: rulebook, 27 October 2026, on Device Sentinel 0.27.10. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

How Device Sentinel's code is written and checked: the code standard, comments and the rule IDs they cite, the header on each file, the linters and the type checker, and how tests are written, pinned and fed. How a release is proven and shipped is under [REL](Rulebook__19_REL_Releases.md); how stored files are checked is under [STOR](Rulebook__18_STOR_Storage.md).

### CODE-01 Docstrings and Comments

**Each module and each function that is not trivial opens with a docstring in plain English that gives the decision and the reason for it; the same text is never repeated in a comment block. Inline comments say why, never narrate what the line does. Names are written out in full, except the standard Python short names such as `err`, `msg` and `ent`. A comment or docstring stands on its own: the reason comes first in plain words, and the ID of the rule in this rulebook follows at the end as a bookmark, written "(rule [UP-05](Rulebook__07_UP_Upstream_Outages.md#up-05-devices-behind-a-down-upstream))". Comments and docstrings cite rule IDs and nothing else: no decision number, review, release history, person or date, since the rulebook and its record hold those. A version number stays only where the code itself compares with that version. `tools/check_comments.py` lists any line that breaks this, and `tools/compare_code.py` proves a change to comments alone changes no code.**

*Proof:* [`test_rule_citations.py`](../tests/test_rule_citations.py).

### CODE-02 Citations Are Checked

**Each rule ID cited in the code or the tests must exist in the rulebook, and a test checks it. The check proves that a cited rule exists, not that it is the right one.**

*Proof:* `test_citations.py`.

### CODE-03 The Header on Each File

**Each Python and YAML file opens with five lines, above its docstring: the copyright line, the GPL-3.0-or-later line pointing at the repository's LICENSE, the project line naming The Thinking Home and xeazy.com, the article link, and the repository link. A new file carries it from the start. JSON files have no comments and are covered by the LICENSE and the README.**

*Proof:* none found.

### CODE-04 Lint and the Type Checker

**A rule nobody checks is not a rule. GitHub lints the integration and its tests on each push, with the linter's version pinned so a new linter release cannot turn an unrelated push red. The type checker runs on the build and must report no new error against the previous release. A type annotation that no longer describes the code is a defect, fixed by making the code say what it does, never by silencing the checker.**

*Proof:* `.github/workflows/lint.yml`, `tools/setup_container.sh`.

### CODE-05 Each Workflow Runs Read-Only

**Each GitHub workflow is limited to reading the repository's contents, so it never holds more access than its check needs, even if the repository's default is widened later. The one exception is the CodeQL workflow, which may also write security events, because it cannot post its findings without that.**

*Proof:* `.github/workflows/lint.yml`, `test.yml`, `validate.yml`, `codeql.yml`.

### CODE-06 The Event Loop and Background Jobs

**No file or folder is touched from Home Assistant's event loop. A question about the file system asked during setup goes to a background job, once, with the look and the change in the same job. A background job's own failure is never left to Home Assistant: the code that starts it catches the failure, logs it with what started it, and carries on, so a report that cannot be written is a missing report and not a broken integration. A Daily Brief whose write failed is not emailed.**

*Proof:* [`test_hardening.py`](../tests/test_hardening.py), [`test_reports.py`](../tests/test_reports.py), [`test_www_retired.py`](../tests/test_www_retired.py).

### CODE-07 Pairing Two Lists States Its Intent

**Where two lists are walked side by side, the code says what a difference in length means. Lists built together in one function must match, and a mismatch is an error. Lists read from storage may differ, and the code says why beside it.**

*Proof:* [`test_hardening.py`](../tests/test_hardening.py).

### CODE-08 An Accepted Value Is Used

**A function that accepts a value uses it, or it does not accept it. The exception is a value that Home Assistant or a shared interface requires a function to accept, such as `hass` in a platform's setup or `user_input` in a settings step.**

*Proof:* [`test_trim.py`](../tests/test_trim.py).

### CODE-09 Setup Survives Information That Has Not Arrived

**A feature that reads other entities' states at setup must still work on a boot where those states have not yet arrived. It looks again only while information is still arriving and stops either way once it has; an entity it creates once can be created late, when the feature becomes possible.**

*Proof:* [`test_wifi_medium.py`](../tests/test_wifi_medium.py), [`test_wifi_outage.py`](../tests/test_wifi_outage.py).

### CODE-10 Device Names Are Escaped

**A device, integration or area name may come from the device itself rather than the person, so it is escaped wherever Device Sentinel writes it: a page, a report file or a notification card.**

*Proof:* [`test_hostile_names.py`](../tests/test_hostile_names.py), [`test_device_labels.py`](../tests/test_device_labels.py).

### CODE-11 A File Is Split by Measuring

**A large file is split where counting the calls between its parts shows a seam, not where a guess puts one. Each report is its own file, except the maintainer reports, which share one file, and recording and wording live apart because they never call each other. Before a file is split, the tests are searched for imports from it; where a thing has moved, the test imports it from its new home rather than the old file pretending it is still there. A split is proved by comparing each function before and after, the suite passing, and each report written again from real house data and matching byte for byte.**

*Proof:* none found.

### CODE-12 Tests Are Named for Their Subject

**Each test file is named for the subject it proves, never for a release or a round of work. A large test file is split by subject, with each helper copied to each file that uses it so each file reads on its own; the proof is that the collected test names are the same before and after.**

*Proof:* none found.

### CODE-13 No Test Depends on the Clock

**A test that reads the time of day is pinned to a clock of its own, or keeps its offsets on the past side of the moment it runs. A pin is proved by running the test at several hours of the day. A test that passes at one hour and fails at another is worse than no test, because it teaches that a red suite can be ignored.**

*Proof:* [`test_brief_stitching.py`](../tests/test_brief_stitching.py), [`test_brief_window.py`](../tests/test_brief_window.py), [`test_learning_rhythm.py`](../tests/test_learning_rhythm.py), [`test_storage_timing.py`](../tests/test_storage_timing.py), [`test_untrusted_gaps.py`](../tests/test_untrusted_gaps.py).

### CODE-14 Each Settings Screen Is Checked Against Its Words

**Each settings screen is tested both ways: the fields it offers and the fields its text names are the same set. A section names and explains itself; its fields need a label and nothing more.**

*Proof:* [`test_hardening.py`](../tests/test_hardening.py).

### CODE-15 Tests Run With the Real Registry Wait

**Each test runs with the same short wait after a device or entity change that a running system has; no test gets instant updates. A test that changes the registry and then reads Device Sentinel's view of it lets the wait finish first.**

*Proof:* [`test_registry_bursts.py`](../tests/test_registry_bursts.py), [`helpers.py`](../tests/helpers.py).

### CODE-16 Panel Checks Use a Real House's Data

**A dashboard check is built from replies captured from a real house, not from samples made by hand.**

*Proof:* [`tools/panel_checks/check_real_device.js`](../tools/panel_checks/check_real_device.js), `check_device_finders.js`, `check_tables_hold_columns.js`.

### CODE-17 Test Data Names No Real Network

**The tests name invented Wi-Fi networks, never the owner's.**

*Proof:* none found.

### CODE-18 A Link Is Checked by Its Host

**A test that a link uses the house's external address reads the link apart and checks its scheme and host, never just whether the address appears somewhere in the text.**

*Proof:* [`test_device_labels.py`](../tests/test_device_labels.py).

### CODE-19 A Cut Is Recorded as Fully as a Build

**When a detection is cut back or an idea is dropped, the record keeps each attempt, why it failed, and the design that would work, so the ground is not walked again blind.**

*Proof:* procedure, not code.
