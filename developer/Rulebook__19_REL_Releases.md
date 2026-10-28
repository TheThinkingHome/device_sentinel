# Device Sentinel Rulebook: Releases (REL)

*Version: rulebook, 28 October 2026, on Device Sentinel 0.27.11. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

How a release reaches a house, how much proof it gets before it is tagged, when it counts as stable, and what is written about it: release notes, the README and the wiki. Also the Battery Notes library refresh that rides with each Latest. How the code and the tests are written is under [CODE](Rulebook__20_CODE_Code_and_Tests.md); the battery library's use on the device page is under [DEV](Rulebook__04_DEV_Device_Identity.md).

### REL-01 Changes Reach a House Through a Release

**A change reaches the Panorama or any other house only through the repository: files uploaded to GitHub, a tagged release, and an install through HACS. Nobody edits the installed integration on a running system.**

*Proof:* procedure, not code.

### REL-02 Delivery Is a Zip

**Each delivery is a zip holding each changed or added file at its repository path, and only those files; one file wanted means a zip of one file. Zips are built on GitHub's main, not on the tag, so the maintainer's own README and CHANGELOG wording there is kept. A fix found after a version is uploaded and before it is released goes into that version rather than a new one. The build is proven as a set and uploaded as a set: when GitHub's tests fail on an import or an assertion for something already changed, a file that did not arrive is suspected before the code, and the cure is to upload the complete changed set again. After each upload, and before a tag, the branch is downloaded and compared byte for byte against the build that was tested.**

*Proof:* procedure, not code.

### REL-03 The Suite Runs on Each Push

**GitHub runs the suite on each push, from the repository, on pinned harnesses. It runs twice: on the lowest Home Assistant release Device Sentinel supports (2026.5.0) and on the release the test houses run (2026.10.1), until the lowest supported release reaches 2026.8.0. Any test during which Home Assistant reports a deprecated use by Device Sentinel fails, and a replacement Home Assistant recommends is tried on each supported release before it is used.**

*Proof:* `.github/workflows/test.yml`, `requirements_test.txt`, `requirements_test_floor.txt`, [`test_deprecation_guard.py`](../tests/test_deprecation_guard.py).

### REL-04 How Much Proof a Build Gets

**The maintainer decides at the start of each build how much proof it gets: one gate, two gates, two gates and an adversarial round, and so on. A standard gate runs the whole suite once on each harness with the test houses' files and once without, then the linters and the panel checks; a double gate runs each harness with the houses twice, for a Latest and the most complicated pre-releases. A release that adds a coordinator stack gets one gate, the simulations, adversarial rounds until one finds nothing, then two more gates.**

*Proof:* `device_sentinel_testdata/scripts/gate.sh`, the gate in use; `tools/setup_container.sh` writes an older one.

### REL-05 Adversarial Rounds Before a Latest

**Releases are tested aggressively. Before a release is published as Latest, and for each release that fixes a known gap or a ruled change, adversarial rounds continue until one round is clean; then each fix is folded in and the build is made again. Each finding is graded for how likely a person is to see it: Likely, Possible, Rare or Very rare. A Likely or Possible finding keeps the rounds going. A Rare or Very rare finding, such as one that needs two clock steps in a row, is recorded as a known limit and named in the release note, and does not keep the rounds going. The last round checks everyday use: days of each test house run against the previous release, and the attacks of each earlier round run again.**

*Proof:* procedure, not code.

### REL-06 Patch Upon Patch Means Stop

**When fixes start piling up in one area, the work stops and the area is discussed with the maintainer to find a simpler design before any more fixes are made.**

*Proof:* procedure, not code.

### REL-07 Tagged Is Not Yet Stable

**A release is stable only after it has run through a midnight and the next morning's reports on the reference system. Tagging and calling it stable are two events a night apart, and nobody is told to install in between unless the release exists to fix their outage. Calling it stable is when the storage snapshot is taken, so the snapshot holds data the release has proved it can write and read back. A change to the stored shape also owes a forward simulation before the tag: both test houses loaded, the new shape written onto each record it applies to, and each output rendered. A rebuild whose only difference from a release that has passed its night is the version line inherits that night, proved by comparing fresh copies of both byte for byte; any other change waits for its own night.**

*Proof:* procedure, not code.

### REL-08 What Ships First

**Recording comes before judging, and judging before sending: no message leaves Device Sentinel until the measurements behind it are trusted. A new capability ships alone first, as pure observation, and is confirmed on the test houses before anything is built to read it. A settings surface or other groundwork may ship ahead of the part that will use it, where it touches neither detection nor learning.**

*Proof:* procedure, not code.

### REL-09 Nothing Correct Waits on a Person's Review

**Nothing that keeps a judgment correct depends on a person remembering to review something. A notice of growth informs; the code handles the spike itself.**

*Proof:* procedure, not code.

### REL-10 Version Numbers

**Version numbers count releases, not features or steps of a plan. The line stays at 0.x until the public release, which the maintainer decides.**

*Proof:* procedure, not code.

### REL-11 Release Notes

**A release note tells someone deciding whether to update what they gain, in active voice and plain words, as short as the change allows. A pre-release note has a GitHub title of the version and a benefit title, no heading in the body, an opening paragraph that says what the release does and credits whoever asked, with links, sections titled by what the reader gets, each a bold outcome sentence with one or two plain sentences, and Upgrading last. A fix release uses Fixed and What You Will See. A Latest note covers each release since the previous Latest, grouped by what changed for the reader, and adds the Integration Status table, numbered phases and Known Limits. Titles state the benefit positively. No pre-release notice, no project words, no method, no test counts, and no history beyond what the reader saw. The working form is `Main__Release_Notes_Template.md`; where a published note and the template disagree, the published note wins.**

*Proof:* procedure, not code.

### REL-12 A Release Note Is a Promise

**What a release note says Device Sentinel does, it must do. A claim the software cannot keep is a defect, whether it ships in words or in code.**

*Proof:* procedure, not code.

### REL-13 The README

**The README exists to earn an install: the problem, what is caught, what reaches a phone, and how to install. It is neither documentation nor a changelog. It changes when one of its claims stops being the best true case for installing, not because a feature shipped. Its Latest Releases list names Latest releases only. The maintainer's own README and CHANGELOG wording on main is kept.**

*Proof:* procedure, not code.

### REL-14 The Wiki

**The wiki gives a reader the reason to install Device Sentinel, the grounds to trust it, and enough to set it up correctly; it does not explain how it works. A page a stranger lands on carries the reason and the trust; a page opened beside a setting carries what that setting needs, with the reasoning below. The maintainer picks when the wiki is updated, and pages change by targeted edits, one fact at a time. Each wiki link the integration carries, on a settings screen, a repair card or a report, is pinned by a test to a published page name, since a wrong name opens a blank "create this page" screen rather than an error.**

*Proof:* [`test_hardening.py`](../tests/test_hardening.py).

### REL-15 The Battery Notes Library Is Refreshed for Each Latest

**Before each Latest, the copy of Battery Notes' device library that Device Sentinel ships is replaced with the current one from Battery Notes' repository. The refresh tool checks each entry has the fields Device Sentinel reads, reports how many devices were added, removed and changed, and writes the new copy unchanged; the date and count line in the library's licence notice is updated by hand.**

*Proof:* [`tools/update_battery_library.py`](../tools/update_battery_library.py), [`test_power_source.py`](../tests/test_power_source.py).

### REL-16 Each Entity Names Its Kind and Release

**Each Device Sentinel entity carries two attributes: its kind and the version of Device Sentinel that wrote it.**

*Proof:* [`test_button_kinds.py`](../tests/test_button_kinds.py), [`test_notifications.py`](../tests/test_notifications.py), [`test_exclusions.py`](../tests/test_exclusions.py).

### REL-17 The Development Rig Is One File

**The rig's development tools are one file, with each app a separate entry pointing at it, so another person runs the rig by copying one file. It is developer tooling and never ships with the integration.**

*Proof:* procedure, not code.
