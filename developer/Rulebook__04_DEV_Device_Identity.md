# Device Sentinel Rulebook: Device Identity (DEV)

*Version: rulebook, 29 October 2026, on Device Sentinel 0.27.14. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

This section covers what a device is called, what kind of device it is, what powers it and how it connects. It also covers which other devices it is grouped with and what firmware it has run. How the battery itself is read and judged is under [BAT](Rulebook__09_BAT_Battery.md), and where the answers are stored is under [STOR](Rulebook__18_STOR_Storage.md). The Power Not Set, Type Not Set and Model With More Than One Type cards are under [REC](Rulebook__15_REC_Recommendations.md); the rest of the device page is under [DASH](Rulebook__14_DASH_Dashboard.md).

### DEV-01 A Device Is Never Shown as Its Id

**A device is never shown to a person as its 32-character registry id.** Each surface asks one place for a device's name.
- **The order it tries:** the name the person gave it; the integration's name for it; its make, model and MAC address where all three are known; its integration and MAC address; its integration and the last eight characters of its id.
- **The one exception:** the diagnostics download. It is for maintainers, is keyed by id, and gives the registry's own name, which can be empty.

*Proof:* [`test_naming.py`](../tests/test_naming.py), [`test_nameless_surfaces.py`](../tests/test_nameless_surfaces.py), [`test_fleet_invariants.py`](../tests/test_fleet_invariants.py).

### DEV-02 The Name a Device Has Today

**Each surface that shows a stored name, the brief and Repeat Offenders included, shows the name the device has today. It never shows the name the device had when the row was written. Only a device Home Assistant no longer knows is named by what it was called then.**

*Proof:* [`test_brief_wording.py`](../tests/test_brief_wording.py), [`test_name_today.py`](../tests/test_name_today.py).

### DEV-03 Long Names

**A device name is shown at most 60 characters long, with an ellipsis marking the cut. Two names that differ only after the cut read the same, and are listed as sharing a name.**

*Proof:* [`test_naming.py`](../tests/test_naming.py).

### DEV-04 Names in the Settings Lists

**In the Settings lists where a person picks devices, each device carries its integration's short name in brackets, "Kitchen Plug (zha)". That way the same hardware listed by two integrations can be told apart.**
- **Where:** the integration is added once, and each Settings list carries it, Low Battery and Signal included.
- **Elsewhere:** the brief and the dashboard keep the plain name.

*Proof:* [`test_exclusions.py`](../tests/test_exclusions.py), [`test_settings_list_names.py`](../tests/test_settings_list_names.py), [`test_plain_names.py`](../tests/test_plain_names.py), [`test_stale_picks.py`](../tests/test_stale_picks.py).

### DEV-05 Renaming a Device

**A device is renamed from its device page, through Home Assistant's own registry.**
- **A name already in use:** a name another device already shows, ignoring capitals, is held. The page warns, naming the other device's area, and offers Change name or Save anyway.
- **An empty name:** puts back the integration's name.
- **Hidden characters:** a name holding hidden or control characters is refused.
- **Emoji:** accents, single emoji, skin tones and country flags are welcome. An emoji joined from several, such as a family, the rainbow flag or the England flag, or one newer than Home Assistant's own character tables, is refused. A person who wants one renames the device on its Home Assistant page.

*Proof:* [`test_device_actions.py`](../tests/test_device_actions.py), [`test_hostile_names.py`](../tests/test_hostile_names.py), `check_device_actions.js`.

### DEV-06 What Powers a Device

**What powers a device comes from, in order: the answer given for that device, the answer given for its model, then the Battery Notes library shipped inside Device Sentinel. Otherwise it reads "Not known".**
- **A model's answer:** an answer entered on one device covers each device of the same model, meaning the same manufacturer, model and model ID exactly as Home Assistant reports them. The hardware version is left out. A device with no manufacturer or no model keeps its answer to itself.
- **The library:** it is read-only and never downloaded while running. An installed Battery Notes is never read, linked or depended on.
- **No looser match:** the lookup is Battery Notes' own and nothing looser, because a match that is not certain is worse than "Not known" and a report to the library.
- **Bad entries:** a malformed library entry is skipped and the rest kept, with one warning naming the count. A device's own fields are read as text.

*Proof:* [`test_power_source.py`](../tests/test_power_source.py), [`test_fleet_answers.py`](../tests/test_fleet_answers.py).

### DEV-07 The Power Row

**The device page's Power row reads, for example, "2× CR2032", "USB Powered" or "Not Set", with an icon for where the answer came from and a pencil.**
- **The icons:** the library's icon is redrawn from Battery Notes' own, in light and dark, and opens the Battery Notes repository in a new tab. A person's answer carries Device Sentinel's shield.
- **Hovering:** it names the source. On a device covered by another device's answer it names that device, "Entered on Button Master Shower".
- **A model's answer:** an answer that covers a model reads "set on Button Master Shower, covers 4 devices of this model". The brief records where it was set: "power set to 2× AAA, for all 4 devices of this model, from its device page", or "from the Recommendations tab".
- **Where power is set:** on the device page, in the Recommendations tab's Power Not Set list, and from "Not Set" in Battery Trends' CELL column ([DASH-04](Rulebook__14_DASH_Dashboard.md#dash-04-what-simple-shows)). The battery problem row and the Daily Brief show it as plain text, with no icons.
- **In Simple:** an answer is read-only, in grey. A device with no answer reads "Not Set" there as in Advanced, a link that sets it.
- **Its own words:** "Not Set" and "Not known" are refused as a battery typed under Other.
- **The Type row:** it shows a person's answer the same way: the shield, the hover naming where it was entered, and the line saying which device set it and how many devices of the model it covers.

*Proof:* `check_power_row.js`, `check_device_page_layout.js`, `check_simple_dashboard.js`, `check_recommendations.js`, [`test_power_source.py`](../tests/test_power_source.py), [`test_action_source.py`](../tests/test_action_source.py), `check_device_type.js`, `check_not_set.js`.

### DEV-08 The Pencil's Choices

**The pencil offers AA, AAA, CR2032, CR2450, Rechargeable, CR123A, CR2, CR2477, CR1632 and CR2430, then Mains Powered, USB Powered, USB Direct to Server and PoE Powered, then Other with a text box.**
- **Quantity:** a quantity of 1 to 8 sits beside the battery choices.
- **Use the library:** "Use the library" clears this device's answer. Where its model has an answer, the button reads "Use the model's answer" instead.
- **Not offered:** there is no "Irreplaceable" or "Not Replaceable", and no "Mains" or "Backup power" label until the mains power project ships.
- **Text under Other:** it is tidied to single spaces, and refused if empty, over 40 characters, or holding hidden or control characters. Text that means USB Direct to Server, whatever its capitals, reads as that choice from the moment it is saved.

*Proof:* `check_power_row.js`, [`test_power_source.py`](../tests/test_power_source.py), [`test_hostile_names.py`](../tests/test_hostile_names.py).

### DEV-09 Sending a Battery to Battery Notes

**After a battery type is added or changed, a button opens Battery Notes' New Device form, filled in.**
- **Where:** on the device page, in Simple and Advanced and after "Not Set" there, or in the Recommendations tab's Power Not Set list.
- **The form:** it is titled "[Device]: <manufacturer> <model> (<model ID>)". A correction uses the same form, and Battery Notes' author reviews each entry by hand.
- **Not offered:** for a wired choice, one typed under Other included; for an answer that says exactly what the library says; or for a device with no manufacturer or model.

*Proof:* `check_power_row.js`, [`test_power_source.py`](../tests/test_power_source.py).

### DEV-10 A Device's Type

**Device Sentinel works out each device's type. With nothing matched it reads "Not Set", never a guess, in Simple and Advanced alike, and "Not Set" opens the way to set it ([DASH-04](Rulebook__14_DASH_Dashboard.md#dash-04-what-simple-shows)).**
- **The order:** a known model; its role on its network; an appliance integration; its own entities; and last, a role read from the device itself (a printer, an ESPHome device or Bluetooth proxy, a Zigbee router, a Z-Wave repeater, a hub).
- **The person's answer:** the answer from the pencil wins and covers each device of the model.
- **Putting the answer back:** the button that puts Device Sentinel's own answer back reads "Use what its entities say" where the entities gave it, "Use Device Sentinel's answer" where a known model or a role gave it, and "Use the model's answer" where its model has an answer.
- **Where it shows:** as a row on the device page, and as a column and filter on the Devices tab, in Simple and Advanced. Once set it is read-only in Simple.
- **The words "Not Set":** a person cannot give them as a type of their own, nor "Not known".
- **Why:** the point is comparing hardware of one kind across brands and versions.
- **Diagnostics:** they list each device's entities by domain, device class and category, without their readings.

*Proof:* [`test_device_type.py`](../tests/test_device_type.py), [`test_device_type_roles.py`](../tests/test_device_type_roles.py), [`test_diagnostics_entities.py`](../tests/test_diagnostics_entities.py), `check_device_type.js`, `check_simple_dashboard.js`.

### DEV-11 The Type List

**The types are Appliance, Bluetooth Proxy, Button, Camera, CO Alarm, Cover, Dashboard, Door/Window Sensor, ESPHome Device, Fan, Hub, IR Remote, Leak Sensor, Light, Lock, Matter Bridge, Motion Sensor, Multi Sensor, NAS, Plant Waterer, Plug, Presence Sensor, Printer, Router, Siren, Smoke Alarm, Soil Sensor, Switch, Temperature Sensor, Thermostat, Thread Border Router, Thread Router, UPS, Vacuum, Valve, Vibration Sensor, Voice Assistant, Z-Wave Controller, Z-Wave Repeater, Zigbee Coordinator (ZHA), Zigbee Coordinator (Zigbee2MQTT) and Zigbee Router, then Other.**
- **ESPHome:** an ESPHome device is typed by its entities. One with a Bluetooth adapter under it is a Bluetooth Proxy, and ESPHome Device is the last resort.
- **Multi Sensor:** it reports motion with temperature, humidity and light, all four.
- **Which type wins:** a device with a vacuum entity is a Vacuum, ahead of its camera. One with a cover and a lock is a Cover. One with a remote entity and no media player is an IR Remote. A device of ge_home, geappliances, home_connect or miele is an Appliance.
- **Words under Other:** words typed under Other that name a listed type, in any case or spacing or by an earlier name (ZHA Coordinator, Zigbee2MQTT Coordinator, Z2M Coordinator, Z-Wave Coordinator, RF IR Remote), are saved as the list's name.

*Proof:* [`test_device_type.py`](../tests/test_device_type.py), [`test_device_type_roles.py`](../tests/test_device_type_roles.py), [`test_type_list_names.py`](../tests/test_type_list_names.py).

### DEV-12 Types Where Devices Are Compared

**Battery Trends, Classification and the Devices tab each sort and filter by type.**
- **Choosing a type:** from the list at the top, it narrows the whole page to that type, "Not Set" included. Classification's filter combines with its All, Watched, Muted and Set aside chips.
- **A type in a row:** it is words, with nothing to press. A row with no type reads "Not Set", which sets it ([DASH-04](Rulebook__14_DASH_Dashboard.md#dash-04-what-simple-shows)).
- **By Model:** it counts by type, and lists each type with its count where a model's devices disagree.
- **Each page its own:** each page keeps its own type choice; switching tabs never carries it over.

*Proof:* [`test_type_columns.py`](../tests/test_type_columns.py), `check_type_filters.js`, `check_not_set.js`.

### DEV-13 How a Device Connects and Its Addresses

**A device's page says how it connects, from its integration's declared class, in six approved phrasings.**
- **An example:** "Through the maker's cloud. It stops reporting if their servers or your internet go down."
- **Left out:** the Connects row is left out for a device that reports changes on the local network as they happen, as most do.
- **Addresses:** each address has its own row named by its kind: MAC Address, Zigbee Address, Bluetooth Address, UPnP ID, Z-Wave Node and, for a Matter device, Serial Number.

*Proof:* `check_connects_line.js`, `check_tab_addresses.js`, [`test_device_page.py`](../tests/test_device_page.py).

### DEV-14 Model Groups

**Devices of the same maker, model and hardware version form a group, with firmware shown inside it.** Two models of one name on different hardware are different hardware.
- **Names:** the model id names the group where the device gives one, and the model name is what a person reads.
- **No firmware given:** the device stays in its group, shown as "not given".
- **No hardware version given:** the device joins its model's only given version. Where the model gives several or none, it stands with the others that give none.
- **Using the data:** a group's data is recorded and shown before anything is judged on it, and the owner decides how each use of it is built.

*Proof:* [`test_model_groups.py`](../tests/test_model_groups.py).

### DEV-15 Firmware History

**A device's firmware version is recorded once it has held ten minutes, so a version that flickers back at a restart is never recorded.**
- **Checking:** each minute after the startup grace.
- **Keeping:** firmware history is kept for the How Much History to Keep setting's days, and the current version always stays.
- **After an update:** a recorded update has the battery's scale measured again (see [BAT](Rulebook__09_BAT_Battery.md)).
- **On the device page:** in Advanced it shows the current firmware with its recorded history beneath. Simple never shows it.

*Proof:* [`test_firmware_hold.py`](../tests/test_firmware_hold.py), [`test_model_groups.py`](../tests/test_model_groups.py), [`test_device_page_firmware.py`](../tests/test_device_page_firmware.py), `check_device_page_layout.js`, `check_simple_dashboard.js`.

### DEV-16 What the Diagnostics Say About Hardware

**The diagnostics download names what the hardware is, not only how it behaves. It gives each device's manufacturer, model, model id and hardware and software versions, and a block naming the house's stacks, its MQTT broker if one runs, and each router integration. These are read live when the file is downloaded and stored nowhere.**

*Proof:* [`test_infrastructure.py`](../tests/test_infrastructure.py).
