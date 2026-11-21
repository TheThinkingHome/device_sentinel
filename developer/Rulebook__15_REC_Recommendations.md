# Device Sentinel Rulebook: Recommendations (REC)

*Version: rulebook, 21 November 2026, on Device Sentinel 0.30.0. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

This section covers what Device Sentinel suggests a person change about their own setup: the Recommendations tab and its cards, the ticks and counts, and the lines the emailed Daily Brief carries for them. The rest of the brief is under [BRIEF](Rulebook__13_BRIEF_Daily_Brief.md). The dashboard around the tab, and Simple and Advanced in general, are under [DASH](Rulebook__14_DASH_Dashboard.md). What each card's answer does to a device (power, type, a battery replacement) is under [DEV](Rulebook__04_DEV_Device_Identity.md) and BAT.

### REC-01 The Recommendations Tab

**The tab opens with "N recommendations to help Device Sentinel run better. None of them is required."** Each card is a suggestion a person can ignore.
- **What N counts:** the rows and written lines not ticked. It is the same count the tab name and the Active Recommendations button carry ([REC-08](#rec-08-counts)).
- **No favourites:** no card is singled out as more needed than another.
- **The order:** the written recommendations come first, then the cards about single devices, then a closing paragraph saying these are suggestions drawn from what Device Sentinel has observed.
- **Nothing to suggest:** the tab reads "Nothing to recommend right now." and nothing else.
- **N at zero with ticked rows left:** that line opens the tab, and the ticked cards and the closing paragraph still show beneath it.

*Proof:* [`tools/panel_checks/check_recommendations.js`](../tools/panel_checks/check_recommendations.js), [`test_recommendations.py`](../tests/test_recommendations.py).

### REC-02 The Written Recommendations

**A written recommendation is about the house's setup rather than one device.** It stands until its condition is gone.
- **How a line reads:** it opens with its condition, a colon, then what it costs and where to change it.
- **The lines, worst first:** all lines show. A notification target that no longer exists, no target set at all, a Links in Reports address Home Assistant no longer holds, a detection family muted or excluded for all the devices it judges, a wireless adapter with no network chosen (router ties or not, since 0.29.0: the scan hears an outage directly, where ties infer one from devices leaving the router; an adapter switched off is said), Zigbee2MQTT availability switched off, a router integration watched again with no card of its own, and a polling integration worth excluding.
- **Integrations to exclude:** each integration Device Sentinel recommends excluding has a card of its own instead ([REC-03](#rec-03-integrations-worth-excluding)).
- **Dismissing a line:** each line can be ticked Acknowledged ([REC-07](#rec-07-acknowledged)). Nothing else dismisses it.

*Proof:* [`test_recommendations.py`](../tests/test_recommendations.py), [`test_recommendation_acknowledgement.py`](../tests/test_recommendation_acknowledgement.py).

### REC-03 Integrations Worth Excluding

**Device Sentinel carries, as data, the one list of integrations whose devices come and go for reasons that are not faults ([MUTE-02](Rulebook__03_MUTE_Muting_and_Exclusion.md#mute-02-excluded-integrations)).**
- **Which get a card:** each one with a watched device, neither excluded nor muted for everything, has its own card.
- **The card:** "Google Cast Is Usually Excluded: Device Sentinel found the Google Cast integration, with 2 devices. It is usually excluded because its devices go unavailable whenever they are switched off. Exclude it here, or tick the box to keep watching it.", its devices listed by name, an Exclude button and the tick.
- **Silencing it:** only the tick silences a card. One excluded and taken back comes back.
- **On the Integrations tab:** the same recommendation shows under the integration's name. It stops when the card is ticked or the integration is muted for everything.
- **Older ticks:** a tick given to one of the three lines that once named several of these integrations together answers the card of each integration it named.
- **Pollers:** a poller measured on the house keeps its own line ([REC-02](#rec-02-the-written-recommendations)).

*Proof:* [`test_recommendations.py`](../tests/test_recommendations.py), [`test_integrations_tab.py`](../tests/test_integrations_tab.py).

### REC-04 The Device Cards

**Each card lists the watched devices it covers, by name with the area, and each name opens the device's page.** A device leaves a card once its condition is gone.
- **The cards, in order:** Confirm Battery Replacement (or Confirm Battery Charge) for a detected new battery (BAT), Power Not Set, the switched-off cards of [REC-05](#rec-05-switched-off-sensors), No Area Assigned, Devices Sharing a Network Address ([UP-19](Rulebook__07_UP_Upstream_Outages.md), since 0.28.0, each row naming the address), Devices Sharing A Name (since 0.29.4, a device whose name another shows, without regard to capitals, in the same area, or with no area, a child device's parent's area counting as its own ([DEV-18](Rulebook__04_DEV_Device_Identity.md#dev-18-a-child-devices-name-and-area)); devices of one name in areas of their own are told apart by them and not listed, unless their notifications would read the same, as two "Thermostat (Z-Wave)" do ([NOTE-13](Rulebook__12_NOTE_Notifications.md#note-13-a-message-says-where-the-device-is))), Slow Reporting Devices ([REC-06](#rec-06-slow-reporting-devices)), and last Type Not Set and Model With More Than One Type.
- **Power Not Set:** lists each watched device with no power type, mains included, and stays that way.
- **After a restart (since 0.29.1):** Models That May Report Live and Models That May Report Cached Values come after Slow Reporting Devices, one row a model: what was seen and how often, a button that sets the model, and what the setting does. A row leaves once its model is set. Their counts are under [WATCH-12](Rulebook__02_WATCH_What_Is_Watched.md#watch-12-a-value-handed-back-at-a-start). Neither is in the emailed brief.
- **One row per model (since 0.28.10):** Power Not Set, Type Not Set and Model With More Than One Type draw one row for each model, since one answer covers each device of the model ([DEV-06](Rulebook__04_DEV_Device_Identity.md#dev-06-what-powers-a-device), [DEV-10](Rulebook__04_DEV_Device_Identity.md#dev-10-a-devices-type)): the maker and model, how many devices, one chooser and one tick for them all. The row opens to list its devices, each opening its page, where one can be set differently. A device with no model, or one that stands for none, keeps its own row. The title counts both, "Power Not Set (21 models, 144 devices)", and the card's sentence says one answer sets each device of that model. Grouped by the answer's own key, maker, model and model ID, so a row's count is what its answer covers.
- **A unit and its parts:** a model whose devices split only as a unit and the parts under it, each of one type over parts of another, as a Lightwave unit is a hub over its sockets, is not on Model With More Than One Type: that split is true, not a conflict.
- **Where each is fixed:** every card is answered in its own rows. Power and type are set in the list. A switched-off sensor is turned on in the list. No Area Assigned has an area chooser and Save on each row, which moves that device in Home Assistant. Devices Sharing A Name has a name box and Save on each row; a name that could not be told apart from another device's, by the test above, is held for "Save anyway", as on the device page ([DASH-10](Rulebook__14_DASH_Dashboard.md#dash-10-confirmations-and-refusals)). Model With More Than One Type names the model and how its devices split, such as "1 Light, 2 Plug", then the type choices, which set the model's type for every device of it, clearing the answers its devices had of their own, or the row would stay; its list gives each device's type now. On the device page a device's own answer is still its own.
- **The card sentences:** "Choose each one's area here.", "Give each its own name here, or set the area where it reads Not Set.", "Pick the type for the model here, and one answer sets each device of that model." and, on Power Not Set and Type Not Set, "One answer sets each device of that model."
- **AREA on a card:** an area nobody set reads "Not Set", a link that sets it ([DASH-04](Rulebook__14_DASH_Dashboard.md#dash-04-what-simple-shows)). On No Area Assigned the row's own chooser does that.
- **Where it was set:** each save from a card is one brief row "from the Recommendations tab" ([BRIEF-07](Rulebook__13_BRIEF_Daily_Brief.md#brief-07-last-24-hours)).

*Proof:* [`test_recommendations.py`](../tests/test_recommendations.py), [`test_power_source.py`](../tests/test_power_source.py), [`test_device_type.py`](../tests/test_device_type.py), [`test_device_actions.py`](../tests/test_device_actions.py), [`tools/panel_checks/check_recommendations.js`](../tools/panel_checks/check_recommendations.js), `check_recommendation_models.js`, [`test_recommendation_models.py`](../tests/test_recommendation_models.py), `check_device_page_layout.js`, `check_type_filters.js`, [`test_wifi_addresses.py`](../tests/test_wifi_addresses.py), `check_wifi_address.js`.

### REC-05 Switched-Off Sensors

**A sensor is switched on one device at a time, by an administrator.** Nothing switches on a whole kind at once.
- **Where:** from its card, or in Advanced from the device's page. A battery voltage sensor is switched on from its card only.
- **The cards:** Last Seen Sensor Switched Off, Battery Sensor Switched Off, Z-Wave Status Switched Off, Signal Sensor Switched Off and Battery Voltage Switched Off.
- **The chips:** each card has a chip per device that names the sensor and what it reports: "Turn on its Last Seen", "Turn on its battery percentage sensor", "Turn on its Z-Wave status", "Turn on its signal sensor" and "Turn on its battery voltage sensor".
- **Firmware update checks:** since 0.28.7 a device's own firmware update entity is switched on the same way, from its network's page only, never a beta channel's ([DASH-17](Rulebook__14_DASH_Dashboard.md#dash-17-the-networks-tab)). No card asks for it (James, 15 November 2026, 12:13): an integration that ships it switched off doesn't push its updates, and a device with it off is judged as one with none ([REC-12](#rec-12-firmware-updates)).
- **Which entities count:** only a device's own entities, never one another integration added, such as Battery Notes'. A device is listed only when none of its own entities of that kind is on.
- **Battery Voltage Switched Off:** lists only a device with a battery reading, whose power is not set to mains, USB or PoE, and whose voltage nothing else already reports.
- **Its wording:** "These devices have battery voltage entities which can be used for more accurate battery reporting and forecasting." With one device listed it reads "This device has a battery voltage entity which can be used for more accurate battery reporting and forecasting."

*Proof:* [`test_switched_off_sensors.py`](../tests/test_switched_off_sensors.py), [`test_battery_voltage_card.py`](../tests/test_battery_voltage_card.py), [`tools/panel_checks/check_recommendations.js`](../tools/panel_checks/check_recommendations.js).

### REC-06 Slow Reporting Devices

**The Slow Reporting Devices card lists each watched device whose wait in use is over 36 hours.** It offers a freeze mute with a "Mute freeze" chip and changes nothing by itself.
- **Left off:** a device already muted for freeze or for everything, and one the freeze rules never judge frozen (see [FRZ](Rulebook__05_FRZ_Freeze.md)).
- **The card reads:** "These devices go quiet for long periods. They are often devices that sleep until a person triggers or interacts with them. Because these devices do not report on a rhythm, Device Sentinel has trouble accurately reporting a frozen verdict. Often a freeze verdict for this device is noise and the best practice is to mute it. Device Sentinel will still report when it becomes unavailable or its battery runs low."

*Proof:* [`test_recommendations.py`](../tests/test_recommendations.py), [`tools/panel_checks/check_recommendations.js`](../tools/panel_checks/check_recommendations.js).

### REC-07 Acknowledged

**Each row of a device card, each written recommendation and each network's card has an Acknowledged tick that can be taken off again (network cards since 0.29.7; James, 18 November 2026, 07:40: all recommendations dismiss with the same tick).**
- **A ticked row:** stays listed, faded to 75%, and leaves the counts and the Daily Brief. The tick is kept in the answers file.
- **The tick itself:** it and the word "Acknowledged" never fade, so it still reads as something to press, here and on the Daily Brief's Problem List. A ticked box's hover reads "Acknowledged. Press to take it back."
- **At the midnight run:** a tick whose device has left the card, or whose line has gone, is forgotten. So a problem that comes back on a later day is active again. A network card's tick is kept with the network, the kind of card and what it is about (an outage pattern's time, a noise card's channel, a Zigbee channel card's reason, and for the house's Wi-Fi card since 0.29.8 its advice: the channel it names and whether the Wi-Fi covers a Zigbee or Thread channel or only sits in a crowd, never the channel the router is on, so a router that picks its own channel each night keeps the tick while the advice is the same; a tick given on 0.29.7 still holds), and is kept at midnight while the card is shown, or was shown on the dashboard in the last two days, which covers radio noise, read only when the dashboard asks.
- **Back the same day:** one that leaves and comes back the same day, or across a restart, comes back ticked.
- **Already ticked:** a sensor a person switched off themselves starts ticked.
- **Battery replacements:** a Confirm Battery Replacement row is answered, not ticked.
- **A whole card (since 0.29.8; asked for by Uncleabubear on the Home Assistant forum):** a device card's heading carries its own Acknowledged tick, which can be pressed with the card closed. Ticked, the card fades, its heading shows no count, and it leaves the counts and the Daily Brief, rows added later included. Its rows keep their own ticks underneath. Opening the card, or working on any of its rows, takes the card's tick off, and it can be ticked again. The tick is kept in the answers file while the card is shown, and forgotten at the midnight run once the card has gone. A Confirm Battery Replacement card has none.

*Proof:* [`test_recommendation_acknowledgement.py`](../tests/test_recommendation_acknowledgement.py), [`test_recommendation_card_tick.py`](../tests/test_recommendation_card_tick.py), [`test_radio_channels.py`](../tests/test_radio_channels.py), [`tools/panel_checks/check_recommendations.js`](../tools/panel_checks/check_recommendations.js), `check_acknowledged_rows.js`.

### REC-08 Counts

**N counts the rows and lines not ticked, in the cards and lines the dashboard's mode shows.**
- **The tab:** reads "Recommendations (N)".
- **The button:** a highlighted "Active Recommendations (N)" button in the top band opens the tab, and is hidden at zero.
- **The Daily Brief tab:** carries "N active recommendations on the Recommendations tab." at its top.
- **Card titles:** each card's title carries "(N)" for its rows not ticked, with no number at zero and none on a written recommendation.

*Proof:* [`tools/panel_checks/check_recommendations.js`](../tools/panel_checks/check_recommendations.js), [`test_recommendation_acknowledgement.py`](../tests/test_recommendation_acknowledgement.py).

### REC-09 What Simple Shows

**Simple shows what Device Sentinel needs to work at its best, and nothing extra.** All other cards and lines are Advanced only. The test, ruled by James, 15 November 2026, 10:30: if it affects how Device Sentinel or the device works, it goes in both. If it is cosmetic, or only makes the dashboard better to use (adding battery types, adding types, anything that makes navigating the dashboard easier), it is Advanced only, because it is not used in Simple ([DASH-04](Rulebook__14_DASH_Dashboard.md#dash-04-what-simple-shows)).
- **In Simple:** Firmware Updates (since 0.29.2: a firmware update changes how the device works), Models That May Report Live and Models That May Report Cached Values (since 0.29.1: a wrong setting lists a working device or misses a dead one), Notifications Recipient Not Valid and Not Set, Last Seen, Battery, Z-Wave Status, Signal Sensor and Battery Voltage Switched Off, Slow Reporting Devices, Devices Sharing a Network Address, Devices Sharing A Name, a family muted for all its devices ("All devices are muted..."), the Wi-Fi adapter with no network chosen (since 0.29.0: how Device Sentinel hears a Wi-Fi outage at all), each integration recommended for exclusion ([REC-03](#rec-03-integrations-worth-excluding)), and Confirm Battery Replacement.
- **Why the sensor cards:** Simple's device page offers no sensor to turn on, so each such sensor has its card here.

*Proof:* [`test_recommendation_acknowledgement.py`](../tests/test_recommendation_acknowledgement.py), [`test_battery_voltage_card.py`](../tests/test_battery_voltage_card.py), [`tools/panel_checks/check_recommendations.js`](../tools/panel_checks/check_recommendations.js), [`tools/panel_checks/check_simple_dashboard.js`](../tools/panel_checks/check_simple_dashboard.js).

### REC-10 In the Emailed Daily Brief

**The emailed Daily Brief, and its file in `/config/device_sentinel/`, carries a Recommendations section above Last 24 Hours.** It counts as Advanced does.
- **What it lists:** each written recommendation not ticked, then one line per device card with its title, its count of rows not ticked in brackets, and a link opening that card on the tab where Links in Reports allows one.
- **Exclusion cards:** each integration's exclusion card not ticked is there each morning until it is answered ([REC-03](#rec-03-integrations-worth-excluding)).
- **Left out:** Slow Reporting Devices, Type Not Set and Model With More Than One Type stay out, because a slow device or a missing or mixed type is not a fault.
- **Firmware Updates is in:** "2 models have devices that need a firmware update. See them on the Recommendations tab." A device behind is something to put right, found conservatively so it is not a false detection (James, 15 November 2026, 10:30). A card whose rows are all ticked stays out too.
- **The dashboard's Daily Brief tab:** carries the count of [REC-08](#rec-08-counts) and, under it, the Confirm Battery Replacement card's line while that card has a row not answered ("Battery replaced on X, detected Oct 18. Confirm it on the Recommendations tab."). It carries no other recommendation lines.

*Proof:* [`test_recommendations.py`](../tests/test_recommendations.py), [`test_recommendation_acknowledgement.py`](../tests/test_recommendation_acknowledgement.py), [`test_battery_voltage_card.py`](../tests/test_battery_voltage_card.py).

### REC-11 Cards Stay Open

**A card the person opened stays open after a tick or an action, and the page keeps its place. A card the person closed stays closed. This is remembered while the dashboard is open, and nothing is kept in the browser. A brief's link opens its card and scrolls to it once.**

*Proof:* [`tools/panel_checks/check_recommendations.js`](../tools/panel_checks/check_recommendations.js).

### REC-12 Firmware Updates

**The Firmware Updates card lists each model with devices behind on firmware, one row a model (since 0.29.2).** Each row is ticked on its own, which also covers an owner holding firmware back.
- **Which devices are behind (James, 14 November 2026, 10:51; 15 November, 12:13):** (1) a device with a firmware update entity of its own, switched on: the entity decides, and the device is behind only while Home Assistant offers it an update. A device with several, such as a coordinator's own firmware and its radio's, is behind when any one of them offers an update, and the row reads that one's versions. (2) A device with no update entity switched on that gives a hardware version: compared with the devices of the same maker, model and hardware version, and behind when below the newest in that group. A device whose own entity decides still shows the version its group can reach. (3) Neither: never behind. One model name can hold different hardware, each on its own current firmware, so a mix of versions alone says nothing. Watched devices only.
- **An update entity switched off counts as none:** an integration that ships it switched off, as ESPHome and first-generation Shelly do, doesn't push its updates, and Device Sentinel doesn't ask for it to be turned on ([REC-05](#rec-05-switched-off-sensors)).
- **What is compared:** versions written with dots, such as 6.10.0 (1.0 and 1.0.0 are one version), and a first-generation Shelly's firmware by the version in it ("20230913-111730/v1.14.0-gcb84623" reads as 1.14.0, and the older "20200827-070450/v1.8.3@4a8bc427" as 1.8.3; the "@" is read only in that pattern). A single number, such as a build number or a date, is read as text and never compared, and so is "Zigbee2MQTT 2.14.3", which Zigbee2MQTT fills in for a device that gives none.
- **A device that names no model** ([DEV-06](Rulebook__04_DEV_Device_Identity.md#dev-06-what-powers-a-device)), such as an ESPHome board: never compared, since nothing says two such devices are the same; only its own update entity, switched on, can say it is behind, and then it has a row of its own, named for the device: "Bluetooth Proxy requires a firmware update. It is on 2026.10.1. The new firmware is 2026.11.0."
- **A model's row:** "28 of your LightwaveRF L42MK3 plugs require a firmware update. 17 are on the new firmware: 6.10.0. 28 are on an old firmware: 6.06.0. 6 are not reported." The noun is the type set for the model, as a plural, or "devices" when the model's devices have no type or more than one (James, 15 November 2026, 10:30). With no device on the new firmware it reads "The new firmware is 52."; with several old versions, "on old firmware: 2.1.1, 2.0.0".
- **The devices:** the row opens to the devices that are behind, each linking to its Home Assistant device page, where the update entity's Install button is.
- **Zigbee2MQTT:** a row with a Zigbee2MQTT device behind adds "Open the Zigbee2MQTT dashboard, select OTA, tick the box that selects all devices and press Check selected.", the first words a link to its dashboard when it is in the sidebar. Zigbee2MQTT finds a model's update on one device at a time, so a check of every device finds the rest, and each then offers its update (James, 15 November 2026, 10:40).
- **Where:** in Simple and Advanced ([REC-09](#rec-09-what-simple-shows)), and in the emailed Daily Brief ([REC-10](#rec-10-in-the-emailed-daily-brief)).

*Proof:* [`test_firmware_updates.py`](../tests/test_firmware_updates.py), [`tools/panel_checks/check_firmware_card.js`](../tools/panel_checks/check_firmware_card.js).

### REC-13 Channel Cards

**Since 0.29.6, a network's recommendations can include a better channel: one card for the house's Wi-Fi, one for a Zigbee network. Each shows on the network's page and on the Recommendations tab under the network's name ([DASH-18](Rulebook__14_DASH_Dashboard.md)).**
- **Wi-Fi:** one card at most, for the 2.4 GHz channel of the house's own Wi-Fi that needs it most (one over a Zigbee or Thread channel first, then the most crowded), when it covers one of the house's Zigbee or Thread channels or shares the air with a neighbour heard at 50% or more. Only channels 1, 6 and 11 are offered, never one that covers a Zigbee or Thread channel, and of those the one whose strongest neighbour is weakest. The card is made only when that channel is quieter, or when the move takes the Wi-Fi off a Zigbee or Thread channel. "Your Wi-Fi on channel 4 overlaps a neighbour's network on channel 1, heard at 52%. If your router lets you choose, channel 6 is clearer: it covers none of your Zigbee or Thread channels, and the strongest network heard near it is at 34%.", then "A mesh router that picks its own channel may change it back. Device Sentinel only hears Wi-Fi where your server is."
- **Zigbee:** only when a neighbour's network heard at 50% or more covers its channel and some of its devices show the cost, a bad signal day or short drop-outs ([SIG-08](Rulebook__10_SIG_Signal.md#sig-08-the-bad-signal-day), [SIG-17](Rulebook__10_SIG_Signal.md#sig-17-short-drop-outs)). Only 11, 15, 20 and 25 are offered, never another Zigbee network's channel or a Thread channel, and only one where no network heard at 50% or more covers it. "Zigbee2MQTT is on channel 11, inside a neighbour's Wi-Fi on channel 1, heard at 52%, and 2 of its devices have a weak link. Channel 20 is clearer.", then "Changing a Zigbee channel can mean pairing some devices again, and some coordinators cannot do it. Wake battery devices afterwards so they follow."
- **The house's own Wi-Fi first:** where the house's own Wi-Fi covers a Zigbee channel, only the Wi-Fi card is made, since moving the Wi-Fi is the smaller job.
- **Acknowledged:** a router that does not let its channel be changed makes the card one to tick ([REC-07](#rec-07-acknowledged)). Ticked, it stays on the network's page and the Recommendations tab, faded, and leaves the count; the overlap warnings it would clear leave the device pages ([SIG-20](Rulebook__10_SIG_Signal.md#sig-20-an-overlap-judged-bad)). A card about anything else (the house's Wi-Fi on another channel, or now covering a Zigbee or Thread channel; a Zigbee network on another channel) is a new card and shows unticked. Unticked, as after a router update that allows a channel change, it counts again.
- **Two lines for a crowd (since 0.30.0):** a Wi-Fi card made for a neighbour at 50% or more stays while a neighbour is heard at 40% or more, and for a day after the last scan that heard one there, told with the neighbour as last heard over the line. So a neighbour wavering about 50% neither drops a ticked card nor brings an unticked one back, and a router that moves itself (from channel 4 to 3) keeps the same card while the advice is the same. Held in memory: after a restart a ticked card holds from its tick, and an unticked one waits for 50% again.
- **Otherwise** the card ends when the scan no longer shows the overlap. Device Sentinel never changes a channel.

*Proof:* [`test_radio_channels.py`](../tests/test_radio_channels.py), [`test_wifi_channel_card_hold.py`](../tests/test_wifi_channel_card_hold.py), [`tools/panel_checks/check_radio_channels.js`](../tools/panel_checks/check_radio_channels.js).
