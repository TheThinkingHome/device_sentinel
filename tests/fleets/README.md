# Fleets

Real houses' Device Sentinel storage, anonymized, so the suite and
continuous integration run on data no constructed house has the shape
of. `tools/anonymise_fleet.py` builds this folder from the private
archive's real files and an alias key the owner keeps; neither is ever
committed.

| Folder | House |
|---|---|
| `reference/` | the owner's own system, Zigbee2MQTT and ZHA |
| `second/` | the second fleet: ZHA, Z-Wave, Matter, ESPHome and UniFi |
| `fourth/` | the fourth fleet: Lutron Caseta, Z-Wave and Frigate |
| `fifth/` | the fifth fleet: Alarm.com, SmartThings, Tuya, Hue, ZHA, Z-Wave and ESPHome |
| `upgrade/reference/`, `upgrade/second/` | the first two houses as they stood on 0.25, kept for the tests that prove an upgrade from a house written before the history file |

Each holds the storage file, the clocks file, the history file where the
house is on 0.26.2 or later (every day older than the storage file's
thirty), the answers file where the house has one (what powers each device and what it is, as its owner set
them with the pencil), and in place of the diagnostics download a small file with the
only things the suite reads from it: each device's name and the entry's
options.

Registry ids, config entry ids, device names, router client trackers,
Wi-Fi network names, notification targets and the answers file's model
keys are stand-ins. A model key keeps its shape, maker, model and model
ID with the same parts empty, because an ESPHome device's maker is often
a name its owner chose. Everything
learned, every timestamp and every count is as the house recorded it.
The set is refreshed when the owner decides, as a commit of its own
with its new Test Baseline line and no product code.

A test reads a house through `fleet_data` in `tests/conftest.py`, which
joins the history file back in front of each series and table, so every
test sees the whole house as it would before 0.26.2. A house with no
history file, such as the upgrade houses and `fourth/`, reads as it
stands.

Last refreshed 5 November 2026: `reference/` from the owner's files of
that morning on 0.28.3, `second/` from Tim Plas's files of 2 November on
0.27.17, and the new `fifth/` from the house of a friend of his, of
4 November on 0.27.17 (115 devices, no history file: a house that sends
only the diagnostics, storage, clocks and answers files). `fourth/` came
out byte-identical.
