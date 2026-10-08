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

Each holds the storage file, the clocks file, the power file where the
house has one (the batteries and power sources its owner set with the
pencil), and in place of the diagnostics download a small file with the
only things the suite reads from it: each device's name and the entry's
options.

Registry ids, config entry ids, device names, router client trackers,
Wi-Fi network names, notification targets and the power file's model
keys are stand-ins. A model key keeps its shape, maker, model and model
ID with the same parts empty, because an ESPHome device's maker is often
a name its owner chose. Everything
learned, every timestamp and every count is as the house recorded it.
The set is refreshed when the owner decides, as a commit of its own
with its new Test Baseline line and no product code.

Last refreshed 8 October 2026: `reference/` from the owner's files of
that morning on 0.25.0 (103 devices, 24 power entries), `second/` from
its files of the same morning on 0.24.11 (244 devices, 3 power
entries), the first captures with dated daily histories, both freeze
rules and a power file; `fourth/` unchanged since 21 September, and
byte-identical after the refresh, which shows the alias key held.
