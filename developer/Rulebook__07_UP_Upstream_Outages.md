# Device Sentinel Rulebook: Upstream Outages (UP)

*Version: rulebook, 29 October 2026, on Device Sentinel 0.27.13. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

What happens when something between a device and Home Assistant stops: the MQTT broker, a bridge or coordinator, an integration, or a Wi-Fi network. This section covers how each one is seen to fail and recover, which devices an outage claims, the row, the pushes, the bus events, and the storms a whole integration can throw. How each stack is read is under [STACK](Rulebook__08_STACK_Stacks.md). A device's own frozen and unavailable verdicts are under [FRZ](Rulebook__05_FRZ_Freeze.md) and UNAV. Mutes are under [MUTE](Rulebook__03_MUTE_Muting_and_Exclusion.md), and how the Daily Brief tells an outage is under [BRIEF](Rulebook__13_BRIEF_Daily_Brief.md).

### UP-01 What an Upstream Is, and the Order

**An upstream is what a device reaches Home Assistant through. Each device is asked about its upstreams in a fixed order, and the first one down claims it.**
- **The four kinds:** the MQTT broker, a bridge or coordinator (Zigbee2MQTT's bridge, ZHA's coordinator), a Wi-Fi network, or the device's own integration entry.
- **The order:** broker, bridge, Wi-Fi, then integration.
- **The broker:** it is upstream only to the devices that reach Home Assistant through it: MQTT's own devices and those of an integration whose manifest depends on MQTT, such as Tasmota.
- **Reach:** an integration outage covers only its own entry's devices. A Wi-Fi outage can cover a device of any integration ([UP-15](#up-15-what-a-wi-fi-outage-claims)).

*Proof:* [`test_reachability.py`](../tests/test_reachability.py), [`test_upstream_reporting.py`](../tests/test_upstream_reporting.py), [`test_outage_pairs_and_counts.py`](../tests/test_outage_pairs_and_counts.py).

### UP-02 Watching the Broker

**Device Sentinel watches the MQTT broker itself, because nothing else can see it fail.** While the broker is down, no bridge event is written.
- **A restart:** seen when the broker's reported start time moves forward by more than 30 seconds, so two restarts inside 30 seconds read as one. A restart's outage runs from the last message before it to the first after it, never from the broker's previous start.
- **A broker that dies while Home Assistant runs:** seen by silence past six times its own learned publish interval, with a floor of 30 seconds.
- **At the minute check:** a broker restart since the last minute check is told as Home Assistant stops, with its length.
- **Inside a Home Assistant restart:** a broker restart inside Device Sentinel's own unwatched gap is the restart. The restart's row covers it, and no broker row is written.
- **The sensor:** Broker: MQTT reads running, down or unknown, and says when the broker last started. It reads unknown until it first hears the broker.
- **When the sensor is on:** on by default where Device Sentinel found any stack, ZHA and Z-Wave included, and off otherwise. So a house on ZHA alone has a broker sensor that reads unknown.
- **Silent for a whole run:** a broker heard in an earlier run that says nothing for a whole run past the startup grace is down from the start of that run. One never heard is left alone.

*Proof:* [`test_broker.py`](../tests/test_broker.py), [`test_boot_claim.py`](../tests/test_boot_claim.py), [`test_upstream_events_fleet.py`](../tests/test_upstream_events_fleet.py), [`test_broker_restart_at_stop.py`](../tests/test_broker_restart_at_stop.py).

### UP-03 How a Bridge or Integration Is Seen to Fail

**Zigbee2MQTT's bridge says for itself when it is down. ZHA, and a stack with no reader of its own, are read from their config entries.**
- **ZHA:** it says nothing, so its coordinator is down when no ZHA config entry has read loaded for 60 seconds. A house can hold several ZHA entries, and any one loaded means up.
- **Stacks with no reader:** a device whose stack has no reader of its own is behind its own config entry. That entry is down when it reads anything but loaded for 60 seconds.
- **After Home Assistant has started:** an entry is called down only after it has been seen loaded (a start is under [UP-04](#up-04-starting-up-during-an-outage)). An integration with no watched device behind it is not watched.
- **ESPHome and Tasmota:** they never fail setup, so an outage of either integration is not seen this way.
- **The start time:** where a reader can say when the outage began, that moment is its start, provided it is a real moment in the past. Otherwise the start is when the reader noticed.

*Proof:* [`test_zha_reader.py`](../tests/test_zha_reader.py), [`test_stacks.py`](../tests/test_stacks.py), [`test_reachability.py`](../tests/test_reachability.py), [`test_upstream_loading.py`](../tests/test_upstream_loading.py).

### UP-04 Starting Up During an Outage

**An upstream that has not loaded since Home Assistant started is loading, not down. Nothing is recorded for it inside the startup grace.**
- **After the grace:** one that never loaded and reads down is down from the start of the run. For an integration only a failed setup counts (setup error, retrying setup or migration error).
- **Inside the grace:** a device whose upstream reads down, or whose integration failed to set up, waits with that upstream.
- **The Problem List:** it is first written only after the bridge readers run and the remembered upstream state is restored.
- **An outage from before the restart:** one still open is resumed from when it went down, so its recovery carries its real length.
- **An outage first found at a start:** with no earlier down on record, it is dated from the start of the run and claims each device behind it, including one that failed before the restart.
- **Diagnostics:** each start records how long each upstream took to load.

*Proof:* [`test_boot_claim.py`](../tests/test_boot_claim.py), [`test_upstream_loading.py`](../tests/test_upstream_loading.py), [`test_entry_outages.py`](../tests/test_entry_outages.py), [`test_reachability.py`](../tests/test_reachability.py).

### UP-05 Devices Behind a Down Upstream

**While a device's upstream is down, its problems are not listed or pushed on their own. One row names the upstream and counts the devices behind it.**
- **Problems from before:** a device whose problem began before the outage keeps its own row, except under an outage dated from the start of a run ([UP-04](#up-04-starting-up-during-an-outage)) and the Wi-Fi lookback ([UP-15](#up-15-what-a-wi-fi-outage-claims)).
- **Muted devices:** an integration outage holds the devices behind it whether or not they are muted for unavailable.
- **A one-device entry:** a device that is its integration entry's only device is never claimed by that entry's outage. It is judged on its own, listed as unavailable with its connection's reason beneath it ("Its SwitchBot connection failed to start."), and stays listed through restarts. An entry of several devices still claims them. A one-device entry whose device is muted for unavailable stays silent.
- **Old rows:** an integration outage row written before 0.22.23 names no entry and can never close, so it is left off the integration's page.
- **The record:** nothing is lost. Each device's verdict, episodes and taints are kept.
- **Counts:** the Device: Frozen sensor counts frozen devices only. The outage row carries the outage's count.
- **Not a fault:** the upstream row is not a device fault and takes no part in incidents, device events or the journal.

*Proof:* [`test_upstream_reporting.py`](../tests/test_upstream_reporting.py), [`test_upstream_outage_row.py`](../tests/test_upstream_outage_row.py), [`test_reachability.py`](../tests/test_reachability.py), [`test_entry_outages.py`](../tests/test_entry_outages.py), [`test_outage_pairs_and_counts.py`](../tests/test_outage_pairs_and_counts.py), [`test_integration_outage_fleet_james.py`](../tests/test_integration_outage_fleet_james.py).

### UP-06 A Restart or Outage Says Nothing About the Devices

**Home Assistant's restart, and a broker, bridge, coordinator, integration or network going down and coming back, is no act on a device. It earns no credit for the device's recovery, on any stack.** Through the outage, the startup grace and the rejoin window, each device keeps its state.
- **A working device:** stays working until its own window says otherwise.
- **A frozen device:** stays frozen. A value a stack hands back from its cache on the return is not the device speaking.
- **What counts as the device:** a reading the integration fetches from the device itself is the device answering. That covers HomeKit Device and ESPHome, and the pollers of a printer, a NAS or a UPS that restore nothing ([WATCH-12](Rulebook__02_WATCH_What_Is_Watched.md#watch-12-a-value-handed-back-at-a-start)). Z-Wave's dead to alive and ZHA's own Last Seen are read as the device too (see [STACK](Rulebook__08_STACK_Stacks.md)).
- **An unavailable device:** stays unavailable while its stack says so, and recovers when its stack says it is available.
- **Muted for unavailable:** a device whose own outage began at least three minutes before the hold, or before Device Sentinel last listened, is a real return.
- **Reports:** restarts are still matched to events to keep their noise out of reports.
- **Learning:** a gap across Device Sentinel's own clean stop is learned minus the time it was stopped. An unclean stop learns nothing of the silence before it (see [FRZ](Rulebook__05_FRZ_Freeze.md)).
- **Maintenance Mode:** a person's declaration, not a restart.

*Proof:* [`test_restart_handback.py`](../tests/test_restart_handback.py), [`test_bridge_hold.py`](../tests/test_bridge_hold.py), [`test_recovery_one_way.py`](../tests/test_recovery_one_way.py), [`test_dead_node_recovery.py`](../tests/test_dead_node_recovery.py), [`test_attribution.py`](../tests/test_attribution.py), [`test_polled_device_returns.py`](../tests/test_polled_device_returns.py).

### UP-07 Outage Time Is Not a Device's Silence

**When an upstream comes back, the time it was down is taken out of each of its devices' silence, as Device Sentinel's own downtime is.**
- **Verdicts:** a device frozen or unavailable before the outage keeps that verdict, and its last-heard time is never changed.
- **Learning:** a gap an outage touched is not learned, unless the outage was shorter than the device's rhythm and lay wholly inside it. A device with no usable rhythm learns no gap an outage touched, and an outage still open counts as running to the report (see [FRZ](Rulebook__05_FRZ_Freeze.md)).

*Proof:* [`test_outage_credit.py`](../tests/test_outage_credit.py), [`test_open_outage_learning.py`](../tests/test_open_outage_learning.py), [`test_outage_inside_rhythm.py`](../tests/test_outage_inside_rhythm.py).

### UP-08 The Rejoin Window

**When a bridge, coordinator or integration comes back, the devices it carried keep its claim for three minutes while they rejoin.** Its row says recovering and counts what has not come back.
- **Integrations:** an integration holds this per config entry.
- **Wi-Fi:** when a Wi-Fi outage closes, each device it claimed gets the same three minutes.
- **The row:** a device that returns inside the window writes no row. One that does not writes a row dated from the outage, not from the window's end.

*Proof:* [`test_bridge_hold.py`](../tests/test_bridge_hold.py), [`test_upstream_outage_row.py`](../tests/test_upstream_outage_row.py), [`test_integration_handback.py`](../tests/test_integration_handback.py), [`test_bridge_pairing.py`](../tests/test_bridge_pairing.py), [`test_wifi_outage.py`](../tests/test_wifi_outage.py).

### UP-09 Pushing an Outage

**An upstream outage settles for 60 seconds before it is pushed. It is pushed twice: when it is down, and when it is over.**
- **Recovering:** sends no push. The row says it.
- **Sound:** only the first push about an upstream makes a sound. The second is silent.
- **Flapping trackers:** a tracker that flaps during the settle cannot push again, because the phase has not changed.
- **The counts:** the down push states how many devices sit behind the upstream, devices muted for unavailable included. The recovery push gives how long it was down and that number, and claims no count already back.

*Proof:* [`test_upstream_reporting.py`](../tests/test_upstream_reporting.py), [`test_upstream_outage_row.py`](../tests/test_upstream_outage_row.py), [`test_wifi_row.py`](../tests/test_wifi_row.py).

### UP-10 The Upstream Bus Events

**An outage fires `device_sentinel_upstream_down` and, when it ends, `device_sentinel_upstream_restored`.**
- **What each carries:** kind (broker, bridge, integration or wifi), name, since and devices. The restored adds for_seconds.
- **Devices:** how many watched devices sit behind the upstream, including those muted for unavailable. It is the same on both halves.
- **Integrations:** an integration outage is told per config entry, each entry with its own pair and count. The name on both events is the integration's domain, for a one-device entry too.
- **In the brief and on the page:** the Daily Brief and the integration's page tell a one-device entry by its device's name. An entry with nothing to count prints no count sentence.
- **Wi-Fi:** a Wi-Fi down also carries how many claimed devices already read unavailable, which decides nothing.
- **The startup grace:** nothing is announced during it. An outage that began inside it, or stood across the restart, is held and announced once afterwards with its real start. One that came and went inside the grace says nothing.
- **A down always gets its restored:** an outage open across a restart is owed its recovery, sent even inside the grace with the count it was announced with. An entry deleted while down closes as removed, and one no longer watched closes as such, never as a recovery.

*Proof:* [`test_upstream_events_fleet.py`](../tests/test_upstream_events_fleet.py), [`test_outage_pairs_and_counts.py`](../tests/test_outage_pairs_and_counts.py), [`test_reachability.py`](../tests/test_reachability.py), [`test_wifi_outage.py`](../tests/test_wifi_outage.py).

### UP-11 The Outage Row and Its Counts

**The row names the upstream as a person would and counts against the total behind it: "Zigbee2MQTT down: 74 of 77 total devices unavailable", or for a network, "WiFi network unavailable: 34 of 74 total devices down".**
- **Its line:** says when it stopped, and what went down with it ("Its one device went down with it", "All 77 devices behind it went down with it", "60 of the 77 devices behind it went down with it", or before any has gone, "None of its 4 devices have gone down yet"). It says those devices are counted here instead of listed, and closes: "Each device keeps its own state while it is down. Anything still down afterwards is listed on its own."
- **A Wi-Fi row:** has its own line, which names the network: "The 'Home' WiFi network became unavailable at 3:01 AM. Currently, 34 of its 74 total devices became unavailable. Device Sentinel is tracking these devices independently and this total will change as this outage develops."
- **Recovering:** the row counts against the devices that went down: "3 of the 56 devices that went down remain unavailable", and with nothing back yet, "ZHA is back: waiting for 14 devices to reconnect".
- **The total:** includes devices muted for unavailable. An integration's row counts its own config entry's devices.
- **The start time:** stays fixed as the count changes.
- **Where it shows:** the Problem List, the notification card and the pushes read the same rows.
- **After it ends:** an ended outage keeps the most devices it had down at once, and the Daily Brief tells it by that: "56 of its 74 devices went down", or "Its one device went down."

*Proof:* [`test_outage_wording.py`](../tests/test_outage_wording.py), [`test_upstream_outage_row.py`](../tests/test_upstream_outage_row.py), [`test_outage_worst.py`](../tests/test_outage_worst.py), [`test_forward_outage_shape.py`](../tests/test_forward_outage_shape.py), [`test_upstream_reporting.py`](../tests/test_upstream_reporting.py), [`test_wifi_row.py`](../tests/test_wifi_row.py).

### UP-12 Seeing a Wi-Fi Outage

**Seeing a Wi-Fi outage and saying which devices went with it are separate jobs.**
- **From the host's radio:** Device Sentinel sees the outage from the host's own radio. A network chosen in Your IoT WiFi Networks is up while any access point broadcasts it, whatever the signal strength.
- **The Confirmation Delay:** when its last access point goes missing, the outage waits the Confirmation Delay (60 seconds by default). If one returns inside it, nothing is said. If not, the outage is declared and dated from when it went.
- **From router trackers:** where no network is chosen and router trackers are tied to watched devices, a burst declares instead. Three tied trackers, or a tenth of the tied set if that is more, going from home to not_home inside 60 seconds starts a 60-second hold. The outage is declared if as many are still gone at its end, dated from the first fall.
- **What does not count:** a tracker going unavailable is the router failing and does not count. Nothing counts during the startup grace.
- **Neither:** a house with neither a chosen network nor tied trackers has no Wi-Fi outage and pays nothing for it.

*Proof:* [`test_wifi_scan.py`](../tests/test_wifi_scan.py), [`test_wifi_declaration.py`](../tests/test_wifi_declaration.py), [`test_wifi_declaration_fleet.py`](../tests/test_wifi_declaration_fleet.py), [`test_wifi_outage.py`](../tests/test_wifi_outage.py).

### UP-13 Tying a Device to Its Router Tracker

**A watched device is tied to a router tracker by hardware address only. Names are never matched, at any strength.**
- **The two ways:** a MAC address shared between the tracker and the device's registry connections, or the tracker's full 12-character MAC inside one of the device's identifiers. A picker, the third way, is not built.
- **Renames:** the tie is kept as the tracker's entity ID. It survives a rename because the ties are rebuilt by hardware address, though a renamed tracker starts its wired or wireless score again ([UP-14](#up-14-wired-or-wireless)).
- **The trackers' own integration:** a device published by the integration that supplies the trackers is never tied to that integration's own tracker.

*Proof:* [`test_wifi_declaration.py`](../tests/test_wifi_declaration.py), [`test_wifi_declaration_fleet.py`](../tests/test_wifi_declaration_fleet.py), [`test_wifi_outage.py`](../tests/test_wifi_outage.py).

### UP-14 Wired or Wireless

**A tracker the router marks wired (TP-Link's `connection: wired`, Fritz's `connection_type: LAN`) is never tied, so it never counts toward declaring an outage. A tracker with no marker keeps its tie.**
- **Counting:** wired and wireless readings are counted per tracker, only while it is home. An away tracker keeps what it was last judged.
- **A skipped tracker:** one that comes home reading wireless is checked again, and rejoins once its kept score no longer reads wired. So a long wired history keeps it skipped.
- **Plain statements:** what a router states outright is read as stated. A named network and a band say wireless as plainly as an SSID does.
- **Mixed readings:** a minority below a tenth of a tracker's readings is ignored. At or above a tenth, once twenty readings sit behind it, the tracker goes to unknown, which keeps the tie.
- **Kept and published:** the scores and the count of readings the scoring rejected are kept per tracker across restarts. They are published in the diagnostics, with the trackers skipped as wired.

*Proof:* [`test_wifi_medium.py`](../tests/test_wifi_medium.py), [`test_wifi_outage.py`](../tests/test_wifi_outage.py).

### UP-15 What a Wi-Fi Outage Claims

**A Wi-Fi outage claims each device that failed inside it, for the life of the outage, not only while its own tracker is away.** That is a tied device whose tracker fell in it, and any other device whose failure began at or after its start.
- **Radio stacks:** a device a radio stack owns (Zigbee, Z-Wave or Matter) is never claimed. Its own bridge answers for it.
- **Wired devices:** a wired device is claimed, though a wired tracker never counts toward declaring.
- **The lookback:** a tied device whose tracker fell in the outage, and whose own failure began no more than five minutes before the outage's start, belongs to the outage. The start is when the first tracker left, or when the network went if the outage was seen from the host's radio. The outage is then dated from the earliest such failure.
- **The burst hold:** when enough tied devices to declare an outage fail inside one burst window, each one's row waits seven minutes for the router. The outage claims it if one is declared. If not, its row appears, dated from its own failure.
- **While an outage stands:** a burst device that failed within five minutes before it waits as long as the outage does.
- **The row:** names the network: "The 'Home' WiFi network became unavailable at 3:01 AM."

*Proof:* [`test_wifi_row.py`](../tests/test_wifi_row.py), [`test_wifi_lookback.py`](../tests/test_wifi_lookback.py), [`test_wifi_burst_hold.py`](../tests/test_wifi_burst_hold.py), [`test_wifi_trace_second.py`](../tests/test_wifi_trace_second.py), [`test_outage_hostile.py`](../tests/test_outage_hostile.py).

### UP-16 Ending a Wi-Fi Outage

**A Wi-Fi outage is ended by the return of the devices that fell in it, not by a count of devices still away.**
- **The fallen set:** the trackers that left no more than 60 seconds before the outage's start or at any time after it. It grows while the outage stands. A tracker already away when the outage began is not a casualty.
- **Coming home:** a member that comes home leaves the set for good. Leaving again later is a new event, though it still counts as a loss during the settle.
- **Hearing the network:** this does not end the outage, unless nothing fell in it. An outage with an empty fallen set ends when the network is heard.
- **Recovering:** begins when the network is heard or 40 percent of the fallen set is home, whichever comes first. The row says so and counts what has not reconnected.
- **The settle:** runs while returns keep arriving. It closes after two checks in a row with none, or at once when the whole set is home. Three losses during the settle reopen the outage and the row goes back to down.
- **At the close:** what is still away is handed back to its own detection after the rejoin window ([UP-08](#up-08-the-rejoin-window)).

*Proof:* [`test_wifi_recovery.py`](../tests/test_wifi_recovery.py), [`test_wifi_recovery_fleet.py`](../tests/test_wifi_recovery_fleet.py), [`test_wifi_outage_fleet.py`](../tests/test_wifi_outage_fleet.py), [`test_wifi_row.py`](../tests/test_wifi_row.py).

### UP-17 Storms

**A storm is one integration's entry republishing many devices at once: 15 different devices inside 2 seconds.**
- **The record:** each is recorded as a `storm_open` and `storm_closed` pair in the system events and as a row in a series. A storm that starts inside the startup grace is not recorded.
- **Synchronized pollers:** an integration with ten or more storms in an hour is a synchronized poller. Its storms are still recorded and counted and its devices still learn, but it writes no event and no episode stamp. The verdict is worked out again from the last hour, so a poller that settles loses it within the hour.
- **Keeping storms:** raw storm rows are kept one hour. At the midnight fold each integration that stormed that day keeps one row: the count, and the middle interval, device count and length.
- **Left out of the tally:** a storm is left out when an upstream outage or a maintenance window was open at its start, or one closed or Home Assistant restarted in the five minutes before.

*Proof:* [`test_storm_tally.py`](../tests/test_storm_tally.py), [`test_attribution.py`](../tests/test_attribution.py), [`test_learning_rhythm.py`](../tests/test_learning_rhythm.py), [`test_noisy_integration.py`](../tests/test_noisy_integration.py).

### UP-18 Advice on a Noisy Integration

**An integration with three or more unexplained storms a day on two of the last seven days gets one line on the Recommendations tab.**
- **The line:** it opens with the condition, a colon, then what it costs and where to change it. It names the integration as a poller, says how often it republishes, and says it should be excluded on the Exclusions and Muting screen.
- **When it goes:** the line is gone when the integration quiets or is excluded.

*Proof:* [`test_noisy_integration.py`](../tests/test_noisy_integration.py), [`test_storm_tally.py`](../tests/test_storm_tally.py).
