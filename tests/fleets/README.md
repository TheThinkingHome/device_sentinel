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

Each holds the storage file, the clocks file, and in place of the
diagnostics download a small file with the only things the suite reads
from it: each device's name and the entry's options.

Registry ids, config entry ids, device names, router client trackers,
Wi-Fi network names and notification targets are stand-ins. Everything
learned, every timestamp and every count is as the house recorded it.
The set is refreshed when the owner decides, as a commit of its own
with its new Test Baseline line and no product code.

Last refreshed 25 September 2026: `reference/` and `second/` from their
files of 24 September, both on 0.22.28; `fourth/` unchanged since 21
September.
