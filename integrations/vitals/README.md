# Vitals charger monitoring

The adapter adds these rows under **Battery** in the existing Vitals extension:

- USB-C 1/2 state and contract voltage, current limit and power limit.
- Input voltage/current/power: measured by the ISL9241 ADC.
- Platform Power: measured Intel PSYS energy delta per elapsed time.

Limits are not consumption. Platform Power covers the whole platform and does
not identify a particular USB-C input. No current or power estimate is shown.
Recorded balancing time at the 255 counter limit shows `≥ 510 h (saturated)`.
Since0.73 the driver re-samples an idle re-primed PSYS/RAPL counter once, so the
first refresh after a long gap shows a measurement rather than Unavailable.
Since 0.79, readings whose driver attributes are root-only come from the
`org.zenbook.Hardware1` service (see below); the rest are world-readable hwmon
attributes. No sudo process, Shell evaluation or controller write is used by Vitals.
SSD health uses a sanitized root-owned cache refreshed by a system timer.

Driver0.59 adds **CPU0 Reported P-state Frequency** and **CPU0 Maximum Turbo
Ratio Frequency** under **Processor**. These use read-only CPU multiplier and
reference-clock reports, separately from normal CPUFreq policy readings.
Unavailable/failed data is shown explicitly; neither is an effective all-core
clock measurement. The new rows activate at the next normal desktop login.

Driver0.61 adds **CPU Package Power (RAPL)** under **Processor**. This is a
hardware package-energy delta divided by its measured interval, separate from
platform PSYS and USB-C input power. Freshness, counter units/wrap and complete
sample arithmetic are checked; errors stay unavailable. No elevation or power
limit change is involved.

After installing driver 0.12 or later, apply to a supported local Vitals layout:

```sh
python3 tools/install-vitals.py --backup /path/to/new/private-backup --apply
```

The installer first checks every source anchor, preserves unrelated local
customizations, backs up the files and verifies readback. Reapplication checks
the helper's exact content. Unsupported layouts fail before editing.

GNOME 50 deprecates ReloadExtension and caches already imported JavaScript.
The updated rows require the next logout/login. The installed adapter and
formatter were tested in a fresh GJS process against the actual hwmon files.
Once loaded, rows can be pinned through the ordinary Vitals menu. Existing
panel favorites are preserved.

Restore sensors.js and values.js from the backup, remove the added
helpers/zenbook-charger.js, then log out/in to roll back the integration.

Version 0.11 adds direct input ADC voltage/current and V*I power. A sample is
attributed only to a single active contract. Values remain unavailable on
transport/identity/ADC/freshness errors or ambiguous multiport input. The driver
uses 96 mV and 44.4 mA ADC steps, not a charger-current estimate. Generic hwmon
also exposes these readings separately from PSYS and negotiated PD limits.
The installer can upgrade the known 0.10 adapter without changing other custom
extension logic. A fresh GNOME login is required to discard cached JS modules.

Version 0.12 additionally shows charger die temperature, VBAT-pin/VSYS voltage,
battery charge/discharge ADCs, operating/protection status and complete source
profiles under **Battery**; thermal events/time under **Processor**; and SSD
wear/spare/errors/lifetime counters under **Storage**. Counts are since boot,
package copies are not summed, and historical SSD counters are labelled as such.
Stale SSD caches and invalid/disabled ADC channels become Unavailable. The
installer upgrades the reviewed 0.10/0.11 layouts and preserves panel favorites.
Rollback also removes helpers/zenbook-metrics.js when absent in the backup.

Version 0.13 names the five motherboard NTCs from matched BIOS/EC evidence and
adds 25 Battery rows for live gauge channels and recorded extrema. Fresh GJS
now exercises 77 total custom rows. TS3/TS4 remain Unavailable when off-scale.
Recorded values describe battery history, not present faults. The known 0.12
integration upgrades without replacing unrelated customizations or favorites.
The new helper is `helpers/zenbook-battery.js`; rollback restores sensors.js
and removes that helper if it did not exist in the backup. A fresh normal
login remains required. CPU/SSD/charger NTCs measure component areas; they are
separate from die temperatures and the external adapter.

0.14 adds 36 recorded battery event/reset rows (113 custom rows in total).
Zero event counts show `Never` for a complete last-cycle field. Two truncated
cycle fields and reset data absent on old kernels remain unavailable. Recorded
safety history is separate from live charger/battery protection. The installer
upgrades only the reviewed 0.13 battery helper; local edits are preserved by
refusing the overwrite. A normal new GNOME login loads the edited helper.

0.15 adds two Last Received PD Alert rows (115 custom rows total), reusing the
existing charger contract decoder. Zero displays `No alert recorded`; inactive,
stale, malformed or older-kernel data never display a fabricated zero. The
reviewed0.13/0.14 integration upgrades preserve unrelated source customizations.

0.17 adds `Battery Recorded FET Highest Temperature` and fills the two previously
truncated event-cycle rows from complete lifetime blocks (116 custom rows total).
Older kernels keep these fields unavailable. The reviewed0.15/0.16 helper upgrade
changes only `helpers/zenbook-battery.js`; owner hooks and favorites are preserved.
Unmatched OEM block2/3 bytes are available through the native raw report without
guessing balancing counters or runtime units. A normal new login loads the helper.

0.18 adds five rows frombattery_gauge_extra: Gauge Cell1/2 Power, Gauge Power,
Gauge Average Power and Gauge Algorithm Temperature. These are battery-side
values computed by the gauge; signed power is positive when charging. The
algorithm temperature is not an additional physical thermistor. The15-second
cache, identity, topology and same-frame cell-power checks suppress unavailable
or inconsistent values. The five rows bring the custom total to121 (101 Battery,
7 Processor,13 Storage). The reviewed0.17 upgrade changes the query method and
battery helper, preserving owner code and favorites. A normal new GNOME login
loads the edited JavaScript.


0.23 adds12 `Battery SBS` rows: pack voltage, signed current/average current,
selected temperature, requested charging current/voltage, relative/absolute SOC,
SOC maximum error, and remaining/full/design capacity. The rows bring the custom
total to133 (113 Battery,7 Processor,13 Storage). Capacities/SOC are gauge estimates;
requested values are not measured charger flow. Capacity mode selectsmAh orWh;
unknown capacity and maximum-request sentinels are explicit. The read-only
`battery_sbs` source has a30-second cache; invalid/stale frames showUnavailable.
The selected temperature may duplicate an existing pack sensor. The ordinary
next GNOME login loads changed JavaScript; installation does not log the owner out.


0.26 adds `Battery Recorded Firmware Runtime`, in stored two-hour steps. This
uses only qualified lifetime block3 word0; the old opaque four-byte prefix is not
a runtime value. Missing/partial/max/inconsistent frames showUnavailable for the
new row while retaining other good history. It is a recorded firmware counter,
not host uptime, battery age or an interpolated clock. The helper-only upgrade
preserves Sensors/Values hooks and favorites. The custom total becomes134 rows
(114 Battery,7 Processor,13 Storage); an ordinary new login loads the changed
JavaScript in a running GNOME session.


0.27 adds nine recorded-history rows: seven `Battery Recorded Region <code> Time`
rows (UT/LT/STL/RT/STH/HT/OT) and two `Battery Recorded Cell <n> Balancing Time`
rows. Values keep the2h step size; codes have no assumed Celsius thresholds and
balancing counters do not show current activity. Nonzero hardware accumulation
is untested. Partial/inconsistent/max data remainsUnavailable per field while
other good history survives. Helper-only upgrade preserves owner hooks/settings.
Total143 rows:123 Battery,7 Processor,13 Storage; ordinary new login may be needed.


0.79 makes the driver attributes that start EC broker/SMBus sessions or sample
RAPL/PSYS energy root-only (0400): charger ADC/metrics, PD identity, gauge
metrics/extra, SBS, lifetime, battery identity strings, `cpu_package_power` and
the matching hwmon channels (PSYS/USB-C input/RAPL power, charger and gauge
temperatures/voltages/currents). Vitals now takes those rows from one
`VitalsMetrics()` call (the Vitals subset of `Metrics()`, 2 s service cache) to the system service `org.zenbook.Hardware1` per refresh
(polkit `read`, allowed for the active session; no interactive prompt). The
Battery and Processor queries of one refresh share that request. The new helper
`helpers/zenbook-service.js` re-expresses the service's decoded sections in the
frame shapes the existing row builders check, so labels, units and validity
rules are unchanged. If the service is missing, denied or fails, those rows show
Unavailable; the PD contract, source profiles, CPU-reported frequency and fan
rows still read world-readable files. Generic Vitals temperature/voltage rows for
the restricted hwmon channels are no longer discovered; the named custom rows
cover the same quantities. The installer upgrades the reviewed 0.78 layout
(sensors.js blocks plus the new helper; row-builder helpers are unchanged and
their 0.78 hashes are accepted); a normal new login loads the changed JavaScript.
Rollback: restore sensors.js from the backup and remove `helpers/zenbook-service.js`
(an older driver keeps the attributes world-readable).
