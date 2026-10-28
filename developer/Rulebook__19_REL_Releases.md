# Device Sentinel Rulebook: Releases (REL)

*Version: rulebook, 28 October 2026, on Device Sentinel 0.27.13. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

This section covers how a release reaches a house, how much proof it gets before it is tagged, when it counts as stable, and what is written about it: release notes, the README and the wiki. It also covers the Battery Notes library refresh that rides with each Latest. How the code and the tests are written is under [CODE](Rulebook__20_CODE_Code_and_Tests.md). The battery library's use on the device page is under [DEV](Rulebook__04_DEV_Device_Identity.md).

### REL-01 Changes Reach a House Through a Release

**A change reaches the Panorama or any other house only through the repository: files uploaded to GitHub, a tagged release, and an install through HACS. Nobody edits the installed integration on a running system.**

*Proof:* procedure, not code.

### REL-02 Delivery Is a Zip

**Each delivery is a zip holding each changed or added file at its repository path, and only those files.** One file wanted means a zip of one file.
- **Built on main:** zips are built on GitHub's main, not on the tag, so the maintainer's own README and CHANGELOG wording there is kept.
- **Late fixes:** a fix found after a version is uploaded and before it is released goes into that version rather than a new one.
- **A set, not single files:** the build is proven as a set and uploaded as a set. When GitHub's tests fail on an import or an assertion for something already changed, a file that did not arrive is suspected before the code. The cure is to upload the complete changed set again.
- **Before a tag:** after each upload, the branch is downloaded and compared byte for byte against the build that was tested.

*Proof:* procedure, not code.

### REL-03 The Suite Runs on Each Push

**GitHub runs the suite on each push, from the repository, on pinned harnesses.**
- **Two runs:** one on the lowest Home Assistant release Device Sentinel supports (2026.5.0), and one on the release the test houses run (2026.10.1). This holds until the lowest supported release reaches 2026.8.0.
- **Deprecations:** any test during which Home Assistant reports a deprecated use by Device Sentinel fails.
- **Replacements:** a replacement Home Assistant recommends is tried on each supported release before it is used.

*Proof:* `.github/workflows/test.yml`, `requirements_test.txt`, `requirements_test_floor.txt`, [`test_deprecation_guard.py`](../tests/test_deprecation_guard.py).

### REL-04 How Much Proof a Build Gets

**The maintainer decides at the start of each build how much proof it gets: one gate, two gates, two gates and an adversarial round, and so on.**
- **A standard gate:** runs the whole suite once on each harness with the test houses' files and once without, then the linters and the panel checks.
- **A double gate:** runs each harness with the houses twice, for a Latest and the most complicated pre-releases.
- **A new coordinator stack:** a release that adds one gets one gate, the simulations, adversarial rounds until one finds nothing, then two more gates.

*Proof:* `device_sentinel_testdata/scripts/gate.sh`, the gate in use; `tools/setup_container.sh` writes an older one.

### REL-05 Adversarial Rounds Before a Latest

**Releases are tested aggressively.**
- **When rounds run:** before a release is published as Latest, and for each release that fixes a known gap or a ruled change. Adversarial rounds continue until one round is clean. Then each fix is folded in and the build is made again.
- **Grading:** each finding is graded for how likely a person is to see it: Likely, Possible, Rare or Very rare.
- **Likely or Possible:** the finding keeps the rounds going.
- **Rare or Very rare:** such as one that needs two clock steps in a row. It is recorded as a known limit and named in the release note, and does not keep the rounds going.
- **The last round:** checks everyday use. Days of each test house are run against the previous release, and the attacks of each earlier round are run again.

*Proof:* procedure, not code.

### REL-06 Patch Upon Patch Means Stop

**When fixes start piling up in one area, the work stops. The area is discussed with the maintainer to find a simpler design before any more fixes are made.**

*Proof:* procedure, not code.

### REL-07 Tagged Is Not Yet Stable

**A release is stable only after it has run through a midnight and the next morning's reports on the reference system.**
- **A night apart:** tagging and calling it stable are two events a night apart. Nobody is told to install in between unless the release exists to fix their outage.
- **The storage snapshot:** it is taken when the release is called stable, so the snapshot holds data the release has proved it can write and read back.
- **A change to the stored shape:** also owes a forward simulation before the tag. Both test houses are loaded, the new shape is written onto each record it applies to, and each output is rendered.
- **Rebuilds:** a rebuild whose only difference from a release that has passed its night is the version line inherits that night. This is proved by comparing fresh copies of both byte for byte. Any other change waits for its own night.

*Proof:* procedure, not code.

### REL-08 What Ships First

**Recording comes before judging, and judging before sending: no message leaves Device Sentinel until the measurements behind it are trusted.**
- **New capabilities:** a new capability ships alone first, as pure observation, and is confirmed on the test houses before anything is built to read it.
- **Groundwork:** a settings surface or other groundwork may ship ahead of the part that will use it, where it touches neither detection nor learning.

*Proof:* procedure, not code.

### REL-09 Nothing Correct Waits on a Person's Review

**Nothing that keeps a judgment correct depends on a person remembering to review something. A notice of growth informs; the code handles the spike itself.**

*Proof:* procedure, not code.

### REL-10 Version Numbers

**Version numbers count releases, not features or steps of a plan. The line stays at 0.x until the public release, which the maintainer decides.**

*Proof:* procedure, not code.

### REL-11 Release Notes

**A release note tells someone deciding whether to update what they gain, in active voice and plain words, as short as the change allows.**
- **A pre-release note:** has a GitHub title of the version and a benefit title, and no heading in the body. It opens with a paragraph that says what the release does and credits whoever asked, with links. Then come sections titled by what the reader gets, each a bold outcome sentence with one or two plain sentences, and Upgrading last.
- **A fix release:** uses Fixed and What You Will See.
- **A Latest note:** covers each release since the previous Latest, grouped by what changed for the reader, and adds the Integration Status table, numbered phases and Known Limits.
- **Titles:** state the benefit positively.
- **Left out:** no pre-release notice, no project words, no method, no test counts, and no history beyond what the reader saw.
- **The template:** the working form is `Main__Release_Notes_Template.md`. Where a published note and the template disagree, the published note wins.

*Proof:* procedure, not code.

### REL-12 A Release Note Is a Promise

**What a release note says Device Sentinel does, it must do. A claim the software cannot keep is a defect, whether it ships in words or in code.**

*Proof:* procedure, not code.

### REL-13 The README

**The README exists to earn an install: the problem, what is caught, what reaches a phone, and how to install.** It is neither documentation nor a changelog.
- **When it changes:** when one of its claims stops being the best true case for installing, not because a feature shipped.
- **Latest Releases:** its Latest Releases list names Latest releases only.
- **The maintainer's wording:** the maintainer's own README and CHANGELOG wording on main is kept.

*Proof:* procedure, not code.

### REL-14 The Wiki

**The wiki gives a reader the reason to install Device Sentinel, the grounds to trust it, and enough to set it up correctly. It does not explain how it works.**
- **Where a reader lands:** a page a stranger lands on carries the reason and the trust. A page opened beside a setting carries what that setting needs, with the reasoning below.
- **Updates:** the maintainer picks when the wiki is updated, and pages change by targeted edits, one fact at a time.
- **Links from the integration:** each wiki link the integration carries, on a settings screen, a repair card or a report, is pinned by a test to a published page name. A wrong name opens a blank "create this page" screen rather than an error.

*Proof:* [`test_hardening.py`](../tests/test_hardening.py).

### REL-15 The Battery Notes Library Is Refreshed for Each Latest

**Before each Latest, the copy of Battery Notes' device library that Device Sentinel ships is replaced with the current one from Battery Notes' repository.**
- **The refresh tool:** checks each entry has the fields Device Sentinel reads, reports how many devices were added, removed and changed, and writes the new copy unchanged.
- **By hand:** the date and count line in the library's licence notice is updated by hand.

*Proof:* [`tools/update_battery_library.py`](../tools/update_battery_library.py), [`test_power_source.py`](../tests/test_power_source.py).

### REL-16 Each Entity Names Its Kind and Release

**Each Device Sentinel entity carries two attributes: its kind and the version of Device Sentinel that wrote it.**

*Proof:* [`test_button_kinds.py`](../tests/test_button_kinds.py), [`test_notifications.py`](../tests/test_notifications.py), [`test_exclusions.py`](../tests/test_exclusions.py).

### REL-17 The Development Rig Is One File

**The rig's development tools are one file, with each app a separate entry pointing at it, so another person runs the rig by copying one file. It is developer tooling and never ships with the integration.**

*Proof:* procedure, not code.
