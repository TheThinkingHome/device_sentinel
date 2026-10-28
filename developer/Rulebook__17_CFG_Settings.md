# Device Sentinel Rulebook: Settings (CFG)

*Version: rulebook, 28 October 2026, on Device Sentinel 0.27.13. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

How the configuration screens are laid out and worded, what the entities Device Sentinel creates are called and which are switched on, and the Data Trim tool on the Advanced screen. What each setting judges is in its own section (BAT, SIG, FRZ, UNAV, NOTE, MUTE). What the trim does to the stored files is in [STOR](Rulebook__18_STOR_Storage.md).

### CFG-01 The Configuration Menu

**The gear on the integration opens Device Sentinel Configuration, a menu of eight sections. A saved setting takes effect at once, with no restart.**
- **The order:** Notifications and Daily Brief, Exclusions and Muting, Low Battery, Signal Strength, Freeze and Unavailable Detection, WiFi, Advanced and Extended Diagnostics. The menu's text names each of the eight in a line.
- **Saving:** each section saves when Submit is pressed and returns to the menu. The menu says so: closing the dialog keeps what was already submitted.

*Proof:* [`test_config_screens.py`](../tests/test_config_screens.py), [`test_settings.py`](../tests/test_settings.py).

### CFG-02 How a Screen Is Laid Out

**A screen shows its plain settings first, then its lists in a named section below them.** Each section has its heading and explanation above its choosers.
- **Muting sections:** on Low Battery, Signal Strength and Freeze and Unavailable Detection, the muting sections open collapsed, since the settings are what a person came for. Exclusions and Muting has no plain settings and shows its two sections open.
- **Where a setting sits:** a setting that tunes one detector sits on that detector's screen.
- **Advanced:** holds what crosses detectors: whether the dashboard opens in Simple or Advanced, the Repeat Offender Threshold, the Storage Write Interval, How Much History to Keep, the Maintenance Window in Minutes, and the Data Trim section.

*Proof:* [`test_config_screens.py`](../tests/test_config_screens.py), [`test_settings.py`](../tests/test_settings.py).

### CFG-03 What a Screen Says

**A screen says what a setting does at the moment it is set.** It may add a short note on how Device Sentinel behaves afterwards, where a person could not choose the setting sensibly without it. The rest, and the reasons, belong on the wiki.
- **Wiki links:** each screen ends with a link that names the wiki page it opens, such as "Low Battery on the wiki", and the menu offers all the documentation. The address of a wiki link is kept out of the screen text and supplied when the screen is drawn.
- **Days Till Low Warning:** its text says a battery's date is a range drawn from that battery's own history.

*Proof:* [`test_hardening.py`](../tests/test_hardening.py), [`test_screen_text.py`](../tests/test_screen_text.py).

### CFG-04 Labels in Title Case

**Screen titles, section headings, field labels and dropdown choices are set in Title Case, book-title style.**
- **Short words:** articles, conjunctions and prepositions of three letters or fewer are lowercase in the middle ("Hardware to Study"). Longer ones are capitalized ("Days Till Low Warning").
- **First and last words:** always capitalized ("Send the Full Brief To").
- **Exceptions:** questions in the frequently asked questions stay sentence case, and report file names stay as written.

*Proof:* [`test_settings_screen_text.py`](../tests/test_settings_screen_text.py), [`test_brief_wording.py`](../tests/test_brief_wording.py).

### CFG-05 Device and Integration Choosers

**A chooser offers what Device Sentinel finds in the house, rather than asking for a typed name. Each chooser takes several picks and is sorted by name, ignoring capitals. A pick kept for a device that has gone sorts in with the rest, not at the end.**

*Proof:* [`test_config_screens.py`](../tests/test_config_screens.py).

### CFG-06 Entity Names

**An entity of a family is named with its subject, a colon and its state, so the list in Home Assistant groups them.**
- **The family names:** Signal: Weak, Signal: Rails, Battery: Low, Battery: Falling, Device: Frozen, Devices: Watched, Devices: Learned, Devices: Set Aside, Maintenance: Ends, Bridge: Zigbee2MQTT, Bridge: ZHA, Bridge: WiFi and Broker: MQTT.
- **Plain names:** Status, the Problem List and the buttons keep plain names.
- **Renames:** a rename changes only the name shown. The entity id stays, so history and automations carry on.

*Proof:* [`test_entity_defaults.py`](../tests/test_entity_defaults.py).

### CFG-07 What an Entity Says

**On a device page, an entity's name and state are the whole explanation. Anything a person cannot understand from those two is renamed or retired.**
- **Status:** reads Watching, Learning or Problem, and leaves Learning once the first device has learned its rhythm.
- **Counts:** a count an automation might act on is a number, with the devices it counts in its attributes.

*Proof:* [`test_device_page.py`](../tests/test_device_page.py), [`test_fresh_install.py`](../tests/test_fresh_install.py), [`test_notifications.py`](../tests/test_notifications.py), [`test_status_sensor_states.py`](../tests/test_status_sensor_states.py).

### CFG-08 Which Entities Are On at First Install

**An entity is switched on at first install only if a person reads it daily or acts on it in the first week.**
- **On:** Status, Devices: Watched, Devices: Learned, Maintenance: Ends, the Problem List, the Regenerate Reports and Maintenance Mode buttons, and each bridge sensor.
- **Broker: MQTT:** on where a bridge stack was found and off elsewhere.
- **Off:** the five problem counts and Devices: Set Aside.
- **Who decides:** the dashboard never decides a default, and a house already installed keeps the choices it has.

*Proof:* [`test_entity_defaults.py`](../tests/test_entity_defaults.py).

### CFG-09 Primary or Diagnostic

**An entity that reports news about the house is primary: the problem counts, the bridge sensors and Broker: MQTT. An entity that counts what Device Sentinel watches is diagnostic: Devices: Watched, Devices: Learned and Devices: Set Aside.**

*Proof:* [`test_entity_defaults.py`](../tests/test_entity_defaults.py).

### CFG-10 Data Trim

**Advanced's Data Trim section erases the learned history of the devices or integrations a person picks, when the screen is saved.**
- **The choosers:** they offer each device and integration Device Sentinel finds, whatever its state, and a device picked twice is allowed.
- **A backup first:** a copy of the stored files goes to trim_backups first, and nothing is erased if the copy fails.
- **What goes:** the device's record, older history included (STOR), its silence episodes, incidents and Problem List items, and its Battery Last Replaced answer, so the device starts clean.
- **What stays:** its mutes and exclusions, the house's own events, and all bridge, broker, pairing and storm state.
- **Afterwards:** the choosers are emptied, storage is written at once, and the Daily Brief reports the trim in one row: one act, one row.

*Proof:* [`test_trim.py`](../tests/test_trim.py), [`test_history_file.py`](../tests/test_history_file.py), [`test_battery_last_replaced.py`](../tests/test_battery_last_replaced.py).
