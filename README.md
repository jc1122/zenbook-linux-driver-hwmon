# Zenbook Linux driver (hwmon)

Linux driver for ASUS Zenbook laptops: fan, battery health, charger and USB-C
power, and temperature sensors through the standard hwmon interface, plus a
signed DKMS module, polkit-authorized D-Bus service, CLI, C library and GNOME
Vitals integration. Internally the project and kernel module are named after
the ASUS "HealthyTable" interface (`zenbook_healthytable`, hwmon `zenbook_ec`).

Native Linux hardware controls and diagnostics recovered from ASUS
`AsusWinIO64.dll`, with Linux equivalents for its application and OS services.
The kernel module exposes standard hwmon fan/temperature/voltage attributes;
the CLI and C library expose the additional diagnostics and reviewed OEM operations.

**Version 0.85.0. Qualified hardware: ASUS Zenbook Flip UP3404VA, BIOS .301,
HealthyTable protocol 15.** Other ASUS models and ARM firmware transports are
not qualified. The module refuses unknown machines.

Version 0.85 is a pre-publication tidy-up with no functional changes: static
analysis policy documented in [docs/STATIC_ANALYSIS.md](docs/STATIC_ANALYSIS.md),
neutral test fixtures, and SPDX/REUSE licensing labels.

Version0.84 fixes a false board-selector fault latch introduced in0.83.

Version0.83 closes the convergence audit's implementable items: cached
unprivileged kernel work, pinned module while the fan is manual, gated OEM
selector ops, a locked-down GNOME bridge, sandboxed exporter units, salted Wi-Fi
keys, parser fuzzing and a security policy.

Version0.82 makes the service portable to older PyGObject.

Version0.81 lets the service's GPU counters through seccomp (perf_event_open
allowed, other @debug calls denied).

Version0.80 fixes three service regressions found live in0.79 (GPU usage needs
CAP_PERFMON, slow-class reads coalesce instead of EAGAIN, tablet switch through
a stable device link).

Version0.79 introduces the privileged hardware service with polkit (group
`zenbook-hw` for unattended reads, settings and fan leases), removes the
keyring sudo route, restricts RAPL and EC-triggering attributes to root and
bounds how long the driver can hold the firmware EC mutex.

Version0.78 is a security hardening release: safe module removal with verified
automatic fan restoration, rate-limited failure paths, raw EC writes disabled by
default, safe log-file creation, an isolated C-library bridge and blocking static
analysis in CI.

Version0.77 adds a root-only, read-only `pd_extended` view of four received-PD
controller registers (sibling-chip TI layout, inferred for TPS65994); no command
or controller write is sent.

Version0.76 removes two unnecessary privilege requirements (per-chain Wi-Fi
signal and disk temperature from world-readable hwmon; SMART fallback still needs
root), adds per-chain signal to metrics and classifies the absent original PD
alert byte as firmware-provided.

Version0.75 applies public TI-reference decodes to history the port already reads:
recorded balancing time 255 is saturation (at least510 h), DAStatus2's tail is
uncompensated cell voltage (checked against compensated cells), and temperature
regions carry TI default boundaries labelled as defaults. Vitals shows the
saturated balancing value after the next ordinary login.

Version0.74 closes the second completion audit's findings: one fresh retry for
transient charger-worker failures and PD-identity contract changes, per-zone
RAPL limits (MSR and thermald-managed MMIO) with the lowest enabled limit in
metrics alongside EC CPU temperature and voltage, and two more exports
reclassified (GetEEPROM_Data firmware-provided, e-marker Other hardware-provided).

Version0.73 moves that retry into the driver: the first PSYS or RAPL package
read after an idle gap sleeps 120 ms once and samples again, so Vitals and any
hwmon reader get a measurement on first read. Twenty-two exports the qualified
firmware does not provide are classed `firmware_provider_required`.

Version0.72 closes the completion audit's remaining reliability gap. The first
PSYS platform-power read after an idle gap only re-primes the hardware counter;
`platform_power` now makes one measured retry after 120 ms, like package power,
and `zenbook-hardware metrics` includes it. Hard errors stay unavailable.

Version0.71 closes two source-confirmed gaps. GPU utilization reports every
advertised DRM busy counter and i915 PMU with per-row `provider`, independent
`provider_errors`, `provider_coverage_complete` and `all_readings_available`;
one failed provider no longer hides another, and providers are never summed. `WMIGetLCDModel` now returns
internal and external monitor names as in the original; `internal_only: true`
keeps the panel-only view. All252 exports now have scoped source reviews; this
is review coverage, not functional-parity or hardware qualification.

Version0.70 separates a USB device's immediate socket from its laptop host port,
and adds cached USB-version/storage-subset reports. The original PD-alert byte
is unsupported on this firmware; use `native_alert: true` for the separate full
received USB-PD alert. Existing metrics and Vitals keep that native measurement.

GPU utilization preserves per-provider and per-engine availability and measured
intervals; invalid or multiplexed PMU samples stay unknown. Tablet mode reads only advertised switch
state, with complete-read requirements before reporting off. See the0.28 protocol
and validation notes for physical qualification limits.

Cached SBS read-attempt diagnostics are available under
`battery_gauge.smart_battery_diagnostics` in `zenbook-hardware metrics` and the
read-only `battery_sbs_diagnostics` sysfs attribute. They retain failed operations
after recovery. A confirmed completed failed SBS read can trigger one fresh, fully restored retry;
failed history stays visible. The underlying firmware failure cause remains unknown.

SBS battery measurements now use the firmware's native SMBus ReadWord worker.
It preserves the fixed read commands, complete-frame checks and restoration, and
reports its transport explicitly. The old combined-transfer path is retained as
regression/rollback evidence and is not a runtime fallback.

## Features

`zenbook-hardware preferences` reads the caller's private saved selections.
The battery-health `ToUser` API and the profile setter remember successful
choices; the immediate battery setter only changes the hardware limit.
These records do not add a charge policy or boot service. The existing Power
Profiles daemon retains profile ownership. See [API details](docs/API.md).

Battery summary APIs retain numeric EC chip ID0, full/design capacity fraction,
explicit remaining-charge units and all four cell-voltage channels with per-field
availability. These correct older name/unit/quantity aliases without adding a
firmware command or estimating energy.

Basic inventory APIs distinguish system family, baseboard product/manufacturer
and system model, expose CPU/GPU descriptions with explicit source/availability,
and separate the declared Linux distribution from kernel version and ISA width.
These reads avoid an unrelated sensor snapshot and need no elevation.

CPU/platform metadata follows reviewed original selection and units: raw CPUID
registers, CPU busy fraction versus percentage, first-processor model name,
numeric architecture, exact fifth OEM string, firmware identities and chassis
classification. Card-reader/MAC selection has explicit absence/error handling.
Window bridge4 adds native stack/focus and per-PID CPU/RSS, with opt-in titles and
a partial existing-registry fallback. Actual Shell activation needs a normal login.

Software-inventory APIs now report registered dpkg ABI32/64/independent packages, Flatpak apps and runtime extensions, and installed Snap revisions with source/scope and explicit provider/field errors. They perform no installation, refresh or store search.

Process APIs now return the busiest five and largest ten visible processes with CPU/RSS units, measured intervals and explicit incomplete-ranking errors. Metadata comes from procfs stat/statm only, without a same-user filter or command-line/environment reads.

`AppList_HardwareConfig` reports per-backlight brightness and default PipeWire output volume/mute with independent availability. `System_Read_VolumeLevel` shares the validated audio reader. Both are read-only; errors remain explicit.

Installed-memory APIs use validated SMBIOS device records for capacity, module
metadata and configured data rates. OS-usable memory and live OS usage remain
separate; firmware declarations are not independent physical measurements.

Original adapter-rating queries now follow the recovered x86 protocol gate.
Protocol15 provides no standard/sufficient/champion rating; the original needs
protocol28. `metrics.adapter_capabilities` explains this separately from working
PD limits and input ADC measurements. The complete firmware dispatcher also
proves legacy diagnostic bank6 absent: ten original queries report EOPNOTSUPP
with reasons in `metrics.adapter_diagnostics`. The native transport blocks absent
banks before port I/O; unsupported telemetry is separate from failed reads.

Firmware diagnostic replies are cached at module probe. The original p_sensor
mask (including zero) and EEPROM-table availability are public in native APIs
and `metrics.firmware_diagnostics`, without repeated firmware calls or root auth.
The current EEPROM version query is firmware-unsupported; BIOS/CMOS storage
metadata is a separate view and its contents are not read.

The original EEPROM table collector now includes its E5 event frames, common/BU
register lists and local manufacture-date conversion. Collection is explicit and
privileged when a real version responds; cached metrics never consume the stream.
On this BIOS the version is unsupported, so the fixed E5 transport rejects calls
before WMI access. Frames remain raw, with partial errors and a64-record bound;
no checksum, temperature or complete-history meaning is guessed.

Specialty-temperature availability follows the original hardware dispatch. Eight
roles are unsupported on this EC; GPU TS1L maps to the existing EC GPU channel,
currently inactive. `metrics` explains each role in `specialty_temperatures`.
No physical location is inferred from an unrelated hwmon label.

Storage inventory queries use cached kernel metadata with distinct rotating,
non-rotating fixed, fixed-capacity and removable selectors. SD size uses original
caption matches or an explicit Linux SD type; eMMC is not guessed from its name.
Incomplete selection/capacity remains unavailable instead of a partial total.
HDD filesystem usage now follows rotating disks, and both usage queries validate
their kernel classification against the mount tree.

USB queries retain partial errors and unknown connector mappings. Verified kernel
port links group speed halves; connected hubs are included in connection counts.

Input and display queries preserve unknown/error states. Monitor identity uses
validated cached base EDID; logical Num Lock uses the GNOME seat keymap, with
input-LED consensus reported separately.

Disk capacity APIs retain readable filesystems beside explicit failed/unmounted
rows, with source-labelled filesystem capacity and no fabricated zero usage.

- Fan RPM, firmware automatic control, full speed and manual requested duty 0–100%, with
  a kernel watchdog and restoration on suspend, unload and shutdown.
- CPU-reported P-state voltage from Intel MSR 0x198, available through standard hwmon.
- CPU, board and battery temperatures; pack/cell voltage, signed current,
  capacities, cycles, charging targets and raw battery lifetime/safety diagnostics.
- Additional core/package, SSD, Wi-Fi and ACPI temperatures from existing Linux drivers.
- Complete raw battery lifetime blocks, recorded FET maximum and all16 event
  last-cycle fields; unknown OEM tail formats remain explicit.
- Recorded battery firmware runtime from a qualified16-bit counter in two-hour
  steps; separate from the legacy opaque field, host uptime and battery age.
- Seven firmware-region duration histories without guessed Celsius thresholds,
  plus two applicable recorded cell-balancing counters; current balancing and
  nonzero physical accumulation remain separate qualifications.
- Gauge-returned cell/pack/average power and gauge-algorithm temperature, with
  signed battery flow and a separate15-second cache.
- Direct SBS pack voltage, current/average current, selected battery temperature,
  charge requests, capacity mode and gauge SOC/error estimates (`battery_sbs`),
  with a separate30-second cache and12 optional Vitals rows.
- Per-drive temperature availability: an unsupported disk does not hide working
  hwmon/SMART readings from other disks.
- USB-C active fixed-supply contract, negotiated voltage/current limit and EC
  adapter wattage through the firmware's read-only EC cache.
- Measured platform power from Intel's PSYS hardware energy counter, exposed
  as read-only hwmon `power1_input`; optional Vitals Battery rows for power/PD limits.
- Read-only wireless link RSSI/channel/PHY/reported rates and active-peer signal
  chains; explicit dBm cached counts, separate from relative signal quality.
- Read-only UCSI power roles and advertised/requested values, kept separate from
  electrical measurements; validated per-policy CPUFreq and driver metadata.
- Direct ISL9241 input voltage/current ADC and power calculated from those two
  measurements: `in7_input`, `curr3_input`, `power2_input`, `charger_adc`. The
  qualified board uses 44.4 mA and 96 mV steps; this is sampled charger input,
  with no external meter calibration. Vitals can display these separately from PD limits.
- Charger die temperature, VBAT-pin/system voltages, battery-side ADC currents,
  live protection flags and regulation state; CPU throttle counts/total/longest
  times; NVMe SMART wear, spare, warning, error and lifetime counters.
- Performance profiles, battery charge cap, keyboard brightness, CPU/GPU/memory,
  storage, monitors, process/application/window inventories and radio metadata.
- USB host connector classification from ACPI `_UPC`; USB traffic counters
  include disks, network, video and audio and never request transfer payloads.
- XG Mobile GC31/GC33 firmware query over the recovered HID feature protocol.
- Typed ModemManager WWAN technology, primary-SIM home-provider and measured
  signal queries. Physical modem qualification remains pending.
- Wi-Fi byte rates over measured intervals, with reset/hotplug/suspend checks
  and optional per-interface RX/TX diagnostics; unreadable counters stay unavailable.
- Complete battery-reported manufacturer/model identity and raw gauge byte,
  read independently of the laptop's ACPI manufacturer/model strings.
- HDMI presence from cached DRM connection status, independently of USB. The
  explicit USB display metric retains DRM ancestry and configured Type-C video
  modes, with unknown results for unmapped outputs.
- Validated Bluetooth, backlight and AC status with explicit provider failures;
  missing hardware data does not become an invented zero or off state.
- UEFI GPNV fields, fixed EEPROM/sensor queries and adapter EC operations, with
  explicit review plans for factory mutations.
- A documented JSON CLI and a native Linux C ABI for all inventoried API names.

There are 252 original names in the [API inventory](capabilities.json).
A route, its protocol implementation and a successful hardware test are separate
facts. The [parity report](docs/PARITY.md) records those distinctions, including
features absent from the qualified laptop. Windows/Wine binary compatibility
is outside this project's native Linux scope.

## Build and test

On Ubuntu/Debian, install the compiler, DKMS and matching kernel headers, plus
`python3-psutil`, `python3-dbus`, `python3-gi`, `python3-pyatspi`, `iw`, `iproute2`,
`dmidecode`, `pciutils`, `usbutils`, `smartmontools` and `wireplumber`.
Installed Snap architecture metadata uses optional `python3-yaml`; missing parser/manifest fields remain explicitly unavailable.
The portable Vitals decoder tests use Node.js.

```sh
make check
make module
sudo make install
zenbook-hardware show
zenbook-hardware metrics
```

The installer keeps older DKMS versions for rollback, builds/signs through
DKMS, restores automatic control before replacing the module, and restores the
previous module if loading fails. Runtime Python files are installed root-owned
under `/usr/local/lib/asus-healthytable/0.85.0/`. The native C library and header
are installed under `/usr/local/lib/` and `/usr/local/include/`.

Secure Boot requires the DKMS signing certificate to be trusted by the machine.
A signature made with the existing enrolled MOK has been verified locally;
loading with Secure Boot enabled still needs a boot test.

## Use

```sh
zenbook-hardware show --json
zenbook-hardware fan full
zenbook-hardware fan 75
zenbook-hardware fan auto
zenbook-hardware profile balanced
zenbook-hardware charge-limit 80
zenbook-hardware keyboard 1
zenbook-hardware power
zenbook-hardware charger
zenbook-hardware firmware-storage
zenbook-hardware api CPU_ReadCpuVoltage
zenbook-hardware battery-history
zenbook-hardware capabilities
zenbook-hardware api GetNum_Key
zenbook-hardware api GetSENSOR_WMI_Data
zenbook-hardware api RF_USB_C_Num
zenbook-hardware api GetXgmFw
```

Normal hwmon monitoring is unprivileged. As a normal user, privileged commands
and API calls go to the polkit-authorised system service `org.zenbook.Hardware1`
(`zenbook-hardwared`); nothing is elevated with sudo behind your back:

| Caller | Privileged operations |
|---|---|
| `sudo zenbook-hardware ...` (root) | run directly in-process, as before (recovery route) |
| normal user, service available | sent to the service; the CLI may show a polkit password prompt (`--non-interactive` disables it), the C library never prompts and gets `EACCES` when not authorised |
| normal user, service unavailable | fails with `privileged service unavailable; run with sudo`; `--sudo-fallback` re-runs the command with plain interactive `sudo` |

From 0.79 the driver's gauge, lifetime, battery identity, received PD identity,
charger and package-power attributes are root-only. As a normal user, `show`,
`metrics`, `record` and `power` read those sections through the service
(`Metrics()`/`power`); without the service they stay typed unavailable.
Non-root `fan full|0..100` holds a bounded service lease (`--duration`, 1..300 s,
default 60) and returns to firmware automatic when it ends, on Ctrl-C or if the
process dies; `fan auto` restores automatic immediately. Firmware writes, driver
load/unload and `metrics --refresh-ssd` need `sudo zenbook-hardware`.

The former `~/.config/zenbook-hardware/auth.json` Secret Service route is
removed. An existing file is left in place and ignored (a one-line notice is
printed); no keyring is read. Group `zenbook-hw` members get read, settings and
fan-lease actions without a password (see [API](docs/API.md)).

`SaveEcLog` and `record` create new private JSONL files and refuse overwrites.
Window titles are opt-in. Process command lines and environments are not read.
`zenbook-hardware disk-activity` reports the original disk-time predicate without
root. Despite its name, `RF_USBIsTranster` defaults to that disk quantity. Actual
USB activity uses `zenbook-hardware usb-activity` or the API's explicit
`{"metric":"usb_traffic"}` option. Incomplete captures retain lower-bound bytes
and never claim an inactive bus from missing observations.

The USB activity metric lazily loads the standard `usbmon` module when needed;
it requests only fixed headers, counts bulk/isochronous completions and never
requests packet payloads or records individual events.

## Native C API

```c
#include <asus_healthytable.h>
#include <stdio.h>
int main(void) {
    char *result = NULL;
    int status = asus_ht_call("{\"name\":\"wmiadd\",\"args\":{\"value\":41}}", &result);
    if (result) puts(result);
    asus_ht_free(result);
    return status != 0;
}
```

Compile with `cc example.c -lasus-healthytable`. The call uses an anonymous RAM
request and a bounded response pipe, invokes the installed Python provider
without a shell, and never elevates implicitly. The returned envelope is
`{"ok":true,"result":...}` or `{"ok":false,"error":{"errno":...,"message":...}}`.
See [API details](docs/API.md).

## OEM records and review

Read APIs cover activation/manufacturing timestamps, the raw stored UUID,
HEAL/CSC status and the OS language record. Mutations return a plan by default.
Apply requires the digest from that exact plan:

```sh
zenbook-hardware api GPNV_Set_ActivatedTime --args '{"value":"2026-10-30 12:00:00"}'
# Review the returned plan, then use the same arguments with:
# --apply --expect-sha256 THE_REVIEWED_DIGEST
```

UEFI writes preserve attributes and unrelated bytes, reject stale revisions,
refuse variable creation, save a verified private original under
`/var/lib/zenbook-hardware/firmware-backups/`, and check exact readback.
Immutable records additionally require `allow_immutable=true`; original flags
are restored even on failure. Installation and qualification do not mutate
factory fields. Those write paths are tested with simulated records.

## Desktop integration

Vitals can read the standard hwmon attributes directly. Install the optional
`gnome-bridge/` directory as
`~/.local/share/gnome-shell/extensions/zenbook-hardware-bridge@local/`, then enable
it with `gnome-extensions enable zenbook-hardware-bridge@local`. A newly installed
local extension may require the next login before Shell discovers it. The CLI
uses AT-SPI as a current-session fallback with explicit coverage metadata.
The reviewed installer `python3 tools/install-bridge.py` previews bridge updates;
use `--apply --backup /absolute/new/private/directory` to install while retaining
existing desktop preferences. Bridge3 also supplies logical Num Lock for GetNum_Key.
Without the live bridge, session Num Lock stays unavailable; LED state is separate.
No unsafe Shell evaluation or logout automation is used.

The optional [Vitals charger integration](integrations/vitals/README.md) adds
PD voltage/current/power **limits** and separately labelled **Platform Power**
under Battery. It reads the cached `pd_contract` and `power1_input` attributes
without privilege. Input voltage/current/power, charger ADCs and advertised
source profiles are shown separately. CPU and SSD additions are described below. GNOME 50 requires the next logout/login to load updated
extension JavaScript; changing files or toggling an already loaded extension
does not prove the running instance uses them.

## Limits and rollback

- Fan requests span0..255; firmware duty codes/RPM can differ. The low-RPM/fault watchdog may restore automatic mode. Manual mode has no general timer lease.
- Five thermistors now have BIOS-derived CPU/SSD/ambient/DDR/charger labels.
  They are component-area temperatures, separate from internal die sensors.
  Additional specialty placements and some battery lifetime fields remain unverified.
- The ASUS CPU-voltage query is unsupported, but the Intel MSR fallback works.
  It reports P-state voltage, not an independently measured motherboard rail.
- `charger` reads the active contract from a separately recovered EC cache.
  The stock adapter reports a 20 V / 3.25 A / 65 W limit. These are negotiated
  limits; the separate ISL9241 ADC supplies sampled input voltage/current and watts.
  PSYS reports sampled platform power separately; it is not a per-port USB-C
  current measurement and has not been calibrated against an external meter.
  Two identical snapshots, AC presence, validity bits and consistent PDO/limit
  fields are required. Read requests are denied during manual fan ownership.
  Fixed contracts are supported; other PDO types return explicit unavailable.
- The original ASUS adapter diagnostic bank and EEPROM table remain unsupported.
  Complete source PDOs instead use the fixed per-port RX_SOURCE_CAPS EC cache,
  bracketing the profile reads with contract fields and requiring two identical
  whole snapshots. The separate truncated UCSI diagnostics are not used.
  Cable identity and proprietary adapter diagnostics remain unavailable.
- `firmware-storage` inventories the separate BIOS flash/CMOS NVMEM providers
  without reading contents; it is not the ASUS EEPROM diagnostic table.
- No WWAN modem or XG Mobile is attached to the qualified laptop. Their code
  paths have protocol/provider tests, not physical device qualification.
- Physical antenna main/aux identities are not inferred from chain indices.
- Cold boot, enabled-Secure-Boot loading and physical suspend/resume need
  separate physical validation.

Restore automatic mode before unloading: `zenbook-hardware fan auto`, then
`sudo modprobe -r zenbook_healthytable`. To restore an older retained release,
run `sudo dkms install -m zenbook-healthytable -v OLD_VERSION -k "$(uname -r)" --force`
and `sudo modprobe zenbook_healthytable`. Remove the dedicated modules-load file
only when disabling autoload. The runtime installation does not alter firmware
factory records or remove earlier DKMS sources.

## License and provenance

GPL-2.0-only, except files explicitly marked MIT. Files carry SPDX headers;
files that cannot (JSON, documentation, verbatim Vitals snippets) are labelled
in `REUSE.toml`. Protocol facts were recovered
from locally installed software; proprietary binaries, disassemblies, private
firmware dumps, signing material and live device identifiers are not included.
See [protocol notes](docs/PROTOCOL.md) and [development notes](CONTRIBUTING.md).

## Extra metrics and Vitals

`zenbook-hardware metrics` reads CPU throttling, charger ADC/protection and the
sanitized SSD health cache without elevation. `metrics --refresh-ssd` refreshes
SMART through the configured privileged helper. The installer enables
`zenbook-hardware-ssd.timer`, which refreshes sanitized NVMe metrics every minute
at `/run/zenbook-hardware-metrics/ssd.json`. Device identity/serials and raw SMART
logs are not published. Cache age beyond 180 seconds is unavailable. Disable the
timer to stop collection; standard sensor/fan operation is independent.

The optional Vitals integration places charger data in **Battery**, thermal
counts/durations in **Processor**, and NVMe health in **Storage**. Use the
integration installer with a private backup directory, then start a fresh
normal GNOME session. Existing extension customizations and pinned sensors are
preserved. CPU counts are since boot; per-CPU package copies are not summed.
VBAT-pin ADC voltage is explicitly separate from battery-gauge pack voltage.
The charger status reader excludes the read-to-clear interrupt register0x90.

Cable identity, ASUS EEPROM diagnostics and unverified
specialty temperature mappings remain unavailable on this firmware. Missing
WWAN/XG Mobile hardware is not emulated. See [parity](docs/PARITY.md).

## Sensor mappings and fresh battery diagnostics (0.13)

The board thermistors use **one-based** firmware selectors. The earlier 0–4
loop duplicated the previous channel and never selected DDR; the corrected 1–5
loop preserves the previous valid selector, including on read failure. BIOS
ACPI labels now identify SSD, ambient, CPU, charger and DDR NTCs in hwmon/Vitals.
Ambient is the BIOS name, not a calibrated room thermometer.

`metrics` now includes live `battery_gauge` temperatures, cell sample currents,
BAT/PACK pin voltages and `battery_lifetime` recorded extrema. `battery-history`
uses fresh manufacturer reads instead of the repeated EC cache. Gauge firmware
and the two-cell topology are checked; unknown identities/layouts are refused.
Unused/off-scale TS3/TS4 inputs remain unavailable. Lifetime byte 31 overlaps
firmware SMBus scratch and is excluded. Some block formats/runtime units remain
raw rather than being assigned unsupported meanings. No battery unseal, reset,
calibration, lifetime reset or charging configuration is exposed.

`pd_identity` reads the controller's received partner/cable identity registers
through fixed firmware-mediated pointer reads and restores the volatile mailbox.
This port's controller currently has no completed identity response; e-marker
APIs return ENODATA. No discovery, role or reset command is issued. Identity
values are never inferred from advertised PDOs or the adapter label. The DSTS EEPROM support query and generic-sensor mask return zero. The original
DEVS EEPROM version read is separate and returns the unsupported-method sentinel;
no EEPROM version/date is synthesized from those zero support values. See [validation](docs/VALIDATION.md).

## Battery event history (0.14)

`battery-history` and `metrics` now decode recorded safety, charging and gauging
counters: 16 event types, with the complete last-event cycle fields, and shutdown,
partial/full reset and watchdog reset counts. These are historical events, not
current alarms. Last charge-termination and resistance-update cycles matched the
battery's current cycle count during qualification. Event semantics use the
compatible published layout under the existing exact OEM firmware guard.
Two last-cycle fields cross excluded byte 31 and remain unavailable. The reset
prefix is four bytes; later cell-balancing fields are not assigned a layout.

The runtime counter was unchanged across fresh reads spanning over three minutes,
so a direct seconds conversion is not qualified. The current PD controller also
returns extended/status lengths unlike the older public reference. Neither a zero
length source-extended reply nor its four-byte status register is decoded into
external adapter identity or temperature. No PD request or setting was sent.

## Received PD alerts (0.15)

`metrics` and `charger` now include each active port's last received PD Alert
Data Object, with the full raw32-bit value, alert-type byte and battery-change
masks. Zero is labelled **No alert recorded**; this history register does not
establish present charger protection state. Inactive, stale or malformed data
remain unavailable. `Adapter_Read_PD_ADO` returns the full native32-bit ADO;
the original Windows function read a one-byte legacy cache. Native JSON schemas
are documented separately from Windows binary compatibility.

`Adapter_Read_PD_Get_Emark_Other` requires an acknowledged cable identity with
at least five VDOs and returns the opaque fifth word. The current connection
provides no cable identity ACK, so the getter still returns ENODATA. No value
is inferred or replaced with zero. The monitor sends only fixed register pointers;
no PD message, discovery, role/reset or controller-setting command is issued.

Four fixed original thermal/config reads (CC00/02, CC00/04, CE00, E400) all timed
out on this BIOS; every query resynchronized and preserved automatic fan control.
These legacy providers cannot currently supply the specialty thermal readings.
An alternate full battery-block path also failed qualification and was not shipped.

Wi-Fi capability, association, card and cached RSSI reports: `zenbook-hardware wireless`. Vitals Network rows use the same fresh parsed cache; capability rates are derived metadata, not throughput.

Fixed raw diagnostic tables: `zenbook-hardware ec-diagnostics`; private full logs: `zenbook-hardware record new.jsonl --samples 1`. Vitals Fan EC Duty Code reports the firmware code separately from requested manual PWM.
This BIOS exposes that duty code only in actual manual mode; automatic mode keeps RPM/control available and reports duty unavailable.
