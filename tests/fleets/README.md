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

Each holds the storage file, the clocks file, the answers file where the
house has one (what powers each device and what it is, as its owner set
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

Last refreshed 11 October 2026: `reference/` from the owner's files of
that morning on 0.25.6 (104 devices; 24 power and 12 type answers by
model), `second/` from its files of 10 October on 0.25.3 (244 devices;
5 power and 23 type answers), the first captures with an answers file
in place of the power file; `fourth/` unchanged since 21 September, and
byte-identical after the refresh, which shows the alias key held.
