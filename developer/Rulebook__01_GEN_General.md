# Device Sentinel Rulebook: General (GEN)

*Version: rulebook, 27 October 2026, on Device Sentinel 0.27.10. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

What Device Sentinel is, what it watches, the Home Assistant it needs, how light it must stay, the words and names it uses on each surface, and what it writes to the log. Which devices are watched is under [WATCH](Rulebook__02_WATCH_What_Is_Watched.md); device names, types and power are under [DEV](Rulebook__04_DEV_Device_Identity.md); the Problem List's own rules are under [LIST](Rulebook__11_LIST_Problem_List.md).

### GEN-01 What Device Sentinel Is

**Device Sentinel is a Home Assistant integration, domain `device_sentinel`, that watches whether hardware is still alive: frozen and unavailable devices, low batteries and weak radio links. It sends its notifications itself, from inside the integration. What it finds goes on its own to-do list, the Problem List, where checking an item acknowledges it (see [LIST](Rulebook__11_LIST_Problem_List.md)).**

*Proof:* [`test_todo.py`](../tests/test_todo.py), [`test_notifications.py`](../tests/test_notifications.py).

### GEN-02 The Blueprints Gave the Behaviour, Not the Structure

**Device Sentinel replaces the Sentinel blueprints. What the blueprints did for a person carries over; how they were built does not, so a blueprint's structure is never a reason for Device Sentinel's.**

*Proof:* none found.

### GEN-03 Devices, Not Entities

**Device Sentinel watches devices. Frozen, unavailable and unknown are judged for a device as a whole, and the screens, the brief and the settings speak of devices. Nothing is muted or excluded by entity (see [MUTE](Rulebook__03_MUTE_Muting_and_Exclusion.md)), and an entity another integration adds never speaks for the device (see [WATCH](Rulebook__02_WATCH_What_Is_Watched.md)).**

*Proof:* [`test_absence_is_the_device.py`](../tests/test_absence_is_the_device.py), [`test_foreign_entities.py`](../tests/test_foreign_entities.py), [`test_classification_sources.py`](../tests/test_classification_sources.py).

### GEN-04 Minimum Home Assistant

**Device Sentinel needs Home Assistant 2026.5 or later.**

*Proof:* none found.

### GEN-05 Staying Light

**How much Device Sentinel costs a house is measured, never claimed: when a change threatens to make it heavier, the question is answered from its start time and its share of the processor on a real house, as Home Assistant reports them. The figure that set the rule was 0.4 seconds to start across 125 devices with eight days of history, with the whole house under two percent of the processor.**

*Proof:* none found.

### GEN-06 Titles in Title Case

**Anything that is a title is capitalized like a book title: report titles and headings, settings screen titles, section names, field labels and dropdown choices. Articles, coordinating conjunctions and short prepositions stay lowercase inside a title, and the first and last words are always capitalized ("Days Till Low Warning", "Delta Low (Fast-Device Grace, Minutes)"). Frequently asked questions stay sentence-case questions, and report file names stay their literal lowercase names. This differs from Home Assistant's own sentence case by decision.**

*Proof:* [`test_brief_wording.py`](../tests/test_brief_wording.py) (report headings), [`test_settings_screen_text.py`](../tests/test_settings_screen_text.py) (a settings label), `check_device_page_layout.js`, `check_repeat_offenders.js`, `check_rhythm_words.js` (dashboard headings).

### GEN-07 One Name for Each Integration

**An integration is named as Home Assistant shows it ("Z-Wave", not "zwave_js"), and where the dashboard's status boxes and outage lines already name it, the dashboard and the brief name it that way everywhere ("ZHA", not "Zigbee Home Automation"). The Settings device lists keep the integration's short id beside a name (see [DEV](Rulebook__04_DEV_Device_Identity.md)). A device of Zigbee2MQTT is named Zigbee2MQTT wherever its integration is named (Problem List, Devices tab, device page), and a child device keeps its own integration's name. A mute set on the MQTT integration still names MQTT. Tasmota devices, which reach Home Assistant through the MQTT broker, are listed on MQTT's page.**

*Proof:* [`test_recovery_one_way.py`](../tests/test_recovery_one_way.py), [`test_child_devices.py`](../tests/test_child_devices.py), [`test_dashboard_problem_list.py`](../tests/test_dashboard_problem_list.py), [`test_integration_names.py`](../tests/test_integration_names.py), `check_integration_names.js`.

### GEN-08 Device Sentinel Does Not Say "We"

**Device Sentinel's own text speaks of Device Sentinel, never "we": "Device Sentinel ruled out the usual causes".**

*Proof:* [`test_recovery_one_way.py`](../tests/test_recovery_one_way.py).

### GEN-09 Durations in Tables

**A duration reads the way the Daily Brief writes it, in a table cell and in a sentence alike. Below two days it takes a short form: seconds below 90 seconds, minutes below 90 minutes, then hours with one decimal (45s, 74m, 4.1h). From two days up it is said in words, in halves rounded down so the number is never larger than the truth: days, then weeks from a week and a half ("2 and a half days", "a week and a half", "6 weeks"). In a report's gap table, a gap held at the length set in How Much History to Keep reads "more than" it.**

*Proof:* [`test_long_durations.py`](../tests/test_long_durations.py) (the formatters); no test checks a table cell on each surface.

### GEN-10 The Log

**Home Assistant's log is for errors and debugging. Device Sentinel writes there an error, a fault that happens while nobody is watching, and what is needed to debug or find one. Anything else is not logged, and a routine count or summary is written at debug level at most.**

*Proof:* [`test_log_lines.py`](../tests/test_log_lines.py).
