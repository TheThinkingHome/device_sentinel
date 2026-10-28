# Device Sentinel Rulebook: Device Identity (DEV)

*Version: rulebook, 27 October 2026, on Device Sentinel 0.27.10. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

What a device is called, what kind of device it is, what powers it, how it connects, which other devices it is grouped with, and what firmware it has run. How the battery itself is read and judged is under [BAT](Rulebook__09_BAT_Battery.md); where the answers are stored is under [STOR](Rulebook__18_STOR_Storage.md); the Power Not Set, Type Not Set and Model With More Than One Type cards are under [REC](Rulebook__15_REC_Recommendations.md); the rest of the device page is under [DASH](Rulebook__14_DASH_Dashboard.md).

### DEV-01 A Device Is Never Shown as Its Id

**Each surface asks one place for a device's name, which tries in order: the name the person gave it; the integration's name for it; its make, model and MAC address where all three are known; its integration and MAC address; its integration and the last eight characters of its id. A device is never shown to a person as its 32-character registry id. The diagnostics download is the one exception: it is for maintainers, is keyed by id, and gives the registry's own name, which can be empty.**

*Proof:* [`test_naming.py`](../tests/test_naming.py), [`test_nameless_surfaces.py`](../tests/test_nameless_surfaces.py), [`test_fleet_invariants.py`](../tests/test_fleet_invariants.py).

### DEV-02 The Name a Device Has Today

**Each surface that shows a stored name, the brief and Repeat Offenders included, shows the name the device has today, never the name it had when the row was written. Only a device Home Assistant no longer knows is named by what it was called then.**

*Proof:* [`test_brief_wording.py`](../tests/test_brief_wording.py), [`test_name_today.py`](../tests/test_name_today.py).

### DEV-03 Long Names

**A device name is shown at most 60 characters long, the cut marked with an ellipsis. Two names that differ only after the cut read the same, and are listed as sharing a name.**

*Proof:* [`test_naming.py`](../tests/test_naming.py).

### DEV-04 Names in the Settings Lists

**In the Settings lists where a person picks devices, each device carries its integration's short name in brackets, "Kitchen Plug (zha)", so the same hardware listed by two integrations can be told apart. The integration is added once, and each Settings list carries it, Low Battery and Signal included. The brief and the dashboard keep the plain name.**

*Proof:* [`test_exclusions.py`](../tests/test_exclusions.py), [`test_settings_list_names.py`](../tests/test_settings_list_names.py), [`test_plain_names.py`](../tests/test_plain_names.py), [`test_stale_picks.py`](../tests/test_stale_picks.py).

### DEV-05 Renaming a Device

**A device is renamed from its device page, through Home Assistant's own registry. A name another device already shows, ignoring capitals, is held: the page warns, naming the other device's area, and offers Change name or Save anyway. An empty name puts back the integration's name. A name holding hidden or control characters is refused. Accents, single emoji, skin tones and country flags are welcome; an emoji joined from several, such as a family, the rainbow flag or the England flag, or one newer than Home Assistant's own character tables, is refused, and a person who wants one renames the device on its Home Assistant page.**

*Proof:* [`test_device_actions.py`](../tests/test_device_actions.py), [`test_hostile_names.py`](../tests/test_hostile_names.py), `check_device_actions.js`.

### DEV-06 What Powers a Device

**What powers a device comes from, in order: the answer given for that device, the answer given for its model, then the Battery Notes library shipped inside Device Sentinel; otherwise it reads "Not known". An answer entered on one device covers each device of the same model, meaning the same manufacturer, model and model ID exactly as Home Assistant reports them; the hardware version is left out. A device with no manufacturer or no model keeps its answer to itself. The library is read-only and never downloaded while running; an installed Battery Notes is never read, linked or depended on. The lookup is Battery Notes' own and nothing looser, because a match that is not certain is worse than "Not known" and a report to the library. A malformed library entry is skipped and the rest kept, with one warning naming the count, and a device's own fields are read as text.**

*Proof:* [`test_power_source.py`](../tests/test_power_source.py), [`test_fleet_answers.py`](../tests/test_fleet_answers.py).

### DEV-07 The Power Row

**The device page's Power row reads, for example, "2× CR2032", "USB Powered" or "Not known", with an icon for where the answer came from and a pencil. The library's icon is redrawn from Battery Notes' own, in light and dark, and opens the Battery Notes repository in a new tab; a person's answer carries Device Sentinel's shield. Hovering names the source, and on a device covered by another device's answer it names that device, "Entered on Button Master Shower". An answer that covers a model reads "set on Button Master Shower, covers 4 devices of this model", and the brief records where it was set: "power set to 2× AAA, for all 4 devices of this model, from its device page", or "from the Recommendations tab". Power is set only on the device page and in the Recommendations tab's Power Not Set list; the battery problem row and the Daily Brief show it as plain text, with no icons. In Simple the row is read-only, and a device with no answer reads "Not known" there as in Advanced. The Type row shows a person's answer the same way: the shield, the hover naming where it was entered, and the line saying which device set it and how many devices of the model it covers.**

*Proof:* `check_power_row.js`, `check_device_page_layout.js`, `check_simple_dashboard.js`, `check_recommendations.js`, [`test_power_source.py`](../tests/test_power_source.py), [`test_action_source.py`](../tests/test_action_source.py), `check_device_type.js`.

### DEV-08 The Pencil's Choices

**The pencil offers AA, AAA, CR2032, CR2450, Rechargeable, CR123A, CR2, CR2477, CR1632 and CR2430, then Mains Powered, USB Powered, USB Direct to Server and PoE Powered, then Other with a text box. A quantity of 1 to 8 sits beside the battery choices. "Use the library" clears this device's answer; where its model has an answer, the button reads "Use the model's answer" instead. There is no "Irreplaceable" or "Not Replaceable", and no "Mains" or "Backup power" label until the mains power project ships. Text under Other is tidied to single spaces and refused if empty, over 40 characters, or holding hidden or control characters; text that means USB Direct to Server, whatever its capitals, reads as that choice from the moment it is saved.**

*Proof:* `check_power_row.js`, [`test_power_source.py`](../tests/test_power_source.py), [`test_hostile_names.py`](../tests/test_hostile_names.py).

### DEV-09 Sending a Battery to Battery Notes

**After a battery type is added or changed, on the device page or in the Recommendations tab's Power Not Set list, a button opens Battery Notes' New Device form filled in, titled "[Device]: <manufacturer> <model> (<model ID>)"; a correction uses the same form, and Battery Notes' author reviews each entry by hand. The button is not offered for a wired choice, one typed under Other included, for an answer that says exactly what the library says, or for a device with no manufacturer or model.**

*Proof:* `check_power_row.js`, [`test_power_source.py`](../tests/test_power_source.py).

### DEV-10 A Device's Type

**Device Sentinel works out each device's type from, in order: a known model; its role on its network; an appliance integration; its own entities; and last, a role read from the device itself (a printer, an ESPHome device or Bluetooth proxy, a Zigbee router, a Z-Wave repeater, a hub). With nothing matched it reads "Not known", never a guess, in Simple and Advanced alike. The person's answer from the pencil wins and covers each device of the model. The button that puts Device Sentinel's own answer back reads "Use what its entities say" where the entities gave it, "Use Device Sentinel's answer" where a known model or a role gave it, and "Use the model's answer" where its model has an answer. Type shows as a row on the device page, read-only in Simple, and as a column and filter on the Devices tab. The point is comparing hardware of one kind across brands and versions. The diagnostics list each device's entities by domain, device class and category, without their readings.**

*Proof:* [`test_device_type.py`](../tests/test_device_type.py), [`test_device_type_roles.py`](../tests/test_device_type_roles.py), [`test_diagnostics_entities.py`](../tests/test_diagnostics_entities.py), `check_device_type.js`, `check_simple_dashboard.js`.

### DEV-11 The Type List

**The types are Appliance, Bluetooth Proxy, Button, Camera, CO Alarm, Cover, Dashboard, Door/Window Sensor, ESPHome Device, Fan, Hub, IR Remote, Leak Sensor, Light, Lock, Matter Bridge, Motion Sensor, Multi Sensor, NAS, Plant Waterer, Plug, Presence Sensor, Printer, Router, Siren, Smoke Alarm, Soil Sensor, Switch, Temperature Sensor, Thermostat, Thread Border Router, Thread Router, UPS, Vacuum, Valve, Vibration Sensor, Voice Assistant, Z-Wave Controller, Z-Wave Repeater, Zigbee Coordinator (ZHA), Zigbee Coordinator (Zigbee2MQTT) and Zigbee Router, then Other. An ESPHome device is typed by its entities, one with a Bluetooth adapter under it is a Bluetooth Proxy, and ESPHome Device is the last resort. A Multi Sensor reports motion with temperature, humidity and light, all four. A device with a vacuum entity is a Vacuum, ahead of its camera; one with a cover and a lock is a Cover; one with a remote entity and no media player is an IR Remote; a device of ge_home, geappliances, home_connect or miele is an Appliance. Words typed under Other that name a listed type, in any case or spacing or by an earlier name (ZHA Coordinator, Zigbee2MQTT Coordinator, Z2M Coordinator, Z-Wave Coordinator, RF IR Remote), are saved as the list's name.**

*Proof:* [`test_device_type.py`](../tests/test_device_type.py), [`test_device_type_roles.py`](../tests/test_device_type_roles.py), [`test_type_list_names.py`](../tests/test_type_list_names.py).

### DEV-12 Types Where Devices Are Compared

**Battery Trends, Classification and the Devices tab each sort and filter by type. Clicking a type, in a row or from the list at the top, narrows the whole page to it; Classification's filter combines with its All, Watched, Muted and Set aside chips. By Model counts by type and lists each type with its count where a model's devices disagree. Each page keeps its own type choice; switching tabs never carries it over.**

*Proof:* [`test_type_columns.py`](../tests/test_type_columns.py), `check_type_filters.js`.

### DEV-13 How a Device Connects and Its Addresses

**A device's page says how it connects, from its integration's declared class, in six approved phrasings, such as "Through the maker's cloud. It stops reporting if their servers or your internet go down." The Connects row is left out for a device that reports changes on the local network as they happen, as most do. Each address has its own row named by its kind: MAC Address, Zigbee Address, Bluetooth Address, UPnP ID, Z-Wave Node and, for a Matter device, Serial Number.**

*Proof:* `check_connects_line.js`, `check_tab_addresses.js`, [`test_device_page.py`](../tests/test_device_page.py).

### DEV-14 Model Groups

**Devices of the same maker, model and hardware version form a group, with firmware shown inside it; two models of one name on different hardware are different hardware. The model id names the group where the device gives one, and the model name is what a person reads. A device that gives no firmware stays in its group, shown as "not given"; one that gives no hardware version joins its model's only given version, and stands with the others that give none where the model gives several or none. A group's data is recorded and shown before anything is judged on it, and the owner decides how each use of it is built.**

*Proof:* [`test_model_groups.py`](../tests/test_model_groups.py).

### DEV-15 Firmware History

**A device's firmware version is recorded once it has held ten minutes, checked each minute after the startup grace, so a version that flickers back at a restart is never recorded. Firmware history is kept for the How Much History to Keep setting's days, and the current version always stays. A recorded update has the battery's scale measured again (see [BAT](Rulebook__09_BAT_Battery.md)). In Advanced the device page shows the current firmware with its recorded history beneath; Simple never shows it.**

*Proof:* [`test_firmware_hold.py`](../tests/test_firmware_hold.py), [`test_model_groups.py`](../tests/test_model_groups.py), [`test_device_page_firmware.py`](../tests/test_device_page_firmware.py), `check_device_page_layout.js`, `check_simple_dashboard.js`.

### DEV-16 What the Diagnostics Say About Hardware

**The diagnostics download names what the hardware is, not only how it behaves: each device's manufacturer, model, model id and hardware and software versions, and a block naming the house's stacks, its MQTT broker if one runs, and each router integration. These are read live when the file is downloaded and stored nowhere.**

*Proof:* [`test_infrastructure.py`](../tests/test_infrastructure.py).
