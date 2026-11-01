# Native Linux parity

Version0.77: a read-only controller check shows register 0x76 (received
Source_Capabilities_Extended) has length0 on this TPS65994 firmware, so the five
Source_Cap_Extend exports remain firmware_provider_required with direct
controller evidence. Raw 0x41/0x42/0x78 are exposed root-only in `pd_extended`
without assigned meanings.

Version0.76: Adapter_Read_PD_ADO's original byte is absent from this firmware
(native_alert=true keeps the separate full received alert), so it is
firmware_provider_required. RF_WiFi_Main_Aux_Rssi and WMIGetHDDTemp no longer
demand privilege when their data are world-readable.

Version0.75 decodes balancing saturation, DAStatus2 uncompensated cell voltages
and reference temperature-region defaults from public TI documentation; lifetime
block3 bytes16..25 and OEM cache layouts remain raw (no public source).

Version0.74: GetEEPROM_Data (firmware sentinel) is firmware_provider_required and
Adapter_Read_PD_Get_Emark_Other joins its e-marker siblings as
hardware_provider_required. PowerLimit1/2 keep the original MSR package zone;
metrics adds both RAPL interfaces and the lowest enabled limit, so a high MSR
value is not mistaken for the binding limit.

Version0.73 moves the idle re-prime into the driver: the first PSYS or RAPL
read after a gap sleeps 120 ms once and samples again, so hwmon consumers such
as Vitals and sensors(1) also get a measurement on first read. Twenty-two
exports that the qualified firmware does not provide (bank6 handlers absent,
HealthyTable28-only ratings, family-0xffff specialty sensors, inactive GPU
channel) are now classed firmware_provider_required instead of
native_equivalent: their native code reproduces the original's availability
decision, but no measurement exists on this platform.

Version0.72 adds one measured PSYS retry after an idle re-prime and publishes
platform power in metrics.

Version0.71 closes two source-confirmed gaps. WMIGetGPUUsg returned DRM rows
alone whenever any existed, hiding i915 PMU data after a DRM failure; it now
collects every advertised provider with separate labels, errors, coverage and
row availability, never summed. WMIGetLCDModel's original query has no
internal-panel filter; its default now includes external names, with optional
internal_only. The final25 wrappers received scoped source reviews; only these
two changed behaviour. All252 exports now have explicit review bindings. This
is source-review coverage, not functional-parity, completion or hardware proof.

Version0.68 corrects an unsupported pack-power consistency rule. The DA1 format
defines pack power from SBS Voltage()*Current(), whereas cell powers use their
own V/I samples. An aligned cell-sum invariant is not established. The native
and Vitals providers now retain the signed reported pack field with its existing
range/identity/frame/freshness/topology checks; a cell error is local to that cell.
No power estimate is substituted. Eight earlier discharge observations that were
withheld by the sum gate now retain the exact centiwatt register value. Source
format references do not establish the physical OEM gauge vendor or calibration.

Version0.67 closes a disk-temperature hotplug identity gap. Existing per-disk
hwmon/SMART reads had no generation/node bracket; a reused path could publish a
replacement's temperature as the old disk's result. Native sysfs metadata,
diskseq, block-node and hwmon identities now bracket both sampling and final
publication. Celsius and partial-error output remain explicit. No physical
hotplug is induced for coverage; replacement cases are filesystem/transport
fixtures and current NVMe hardware is qualified separately.

Version0.66 reconciles the four original e-marker field widths. VID's original
return is a full32-bit ID Header despite its name; native retains default16-bit
vendor ID and adds explicit raw_header=true plus id_header_raw_vdo in reports.
PID16/XID32/Other32 already match the received VDO fields. Fixed-controller
read guards, acknowledgement/member validity and missing-data behavior remain.
No acknowledged cable identity is currently available; physical positive
qualification is separate from the recovered contract and decoder tests.

Version0.65 corrects RF_USBHDMIIsUsed to HDMI presence independently of USB
ancestry. The former USB/Type-C query remains explicit metric usb_display.
Original monitor enumeration has no Active-property filter; native cached DRM
status is a logical Linux equivalent, not a Windows instance-count calibration.
DP transport alone cannot establish a downstream adapter's HDMI identity.
WWAN reads now pin one existing ModemManager owner, enumerate bounded object
names without private properties and reject owner/inventory/SIM/radio changes.
No modem is attached; positive hardware qualification remains open.
Bluetooth's complete31-entry class switch and the tablet vendor/OEM path were
reviewed. Existing native major classes and advertised tablet switch remain;
a physical connected-class/fold test is still separate from source review.

Scope: native Linux functionality on the qualified UP3404VA.301. Windows/Wine
binary compatibility is owner-excluded. Other ASUS/ARM platforms need their
own recovered transport and hardware qualification.

Each of the 252 original names is inventoried below. Native Linux equivalents
use JSON schemas. A provider-required result means the code path exists but
the current machine cannot supply that feature; it does not establish device
qualification. Factory operations have simulated write tests and reviewed live
plans, not actual factory-write tests.

Version0.64 corrects a source-confirmed quantity mismatch: RF_USBIsTranster's
original boolean is a disk-time threshold, not USB bus bytes. The default native
provider now reports a measured disk counterpart, root exclusions and truthful
partial availability. Actual USB measurements remain explicitly selectable, with
loss/backlog/event-cap/ISO-error coverage and real sampling intervals. Windows
synthetic totals/counter calibration and unsupported root layouts stay unqualified.
SD capacity additionally preserves every selected card in optional detailed output.
S-Mode is Windows-only/not applicable; HDD usage remains filesystem capacity.

Version0.63 completes twelve wireless observation wrapper/shared-helper comparisons.
BSSID/association/primary channel/dBm and both RX/TX byte-rate quantities match
native measurements. The2.4GHz API now includes original1/6/11/other groups beside
its full channel map.5/6GHz group counts retain native band boundaries and explicit
unclassified frequencies, rather than original coarse/off-by-one frequency cuts.

AP census now brackets NetworkManager owner, inventory, kernel interface identity,
scan generation and BSS identity/frequency under a shared8-second deadline. Fixed
property reads avoid unrelated data. Known empty cache remains zero; a never-scanned
empty cache or changed/error provider remains unavailable. No scan or connection
operation is introduced. Antenna chains remain measured but physical Main/Aux
labels are unverified; original duplicate-RSSI fallback is not recreated.

Version0.61 recovers original package-energy/milliwatt scaling and exposes native
CPU0 package energy/actual-time watts without elevation. Raw energy evidence,
strict freshness/fault/wrap guards and independent MSR endpoint checks qualify
the measurement; PM baseline invalidation does not establish a physical suspend
test. Vitals adds a separate Processor package-power row. Four battery lifetime/
extrema source bodies/helpers reconcile with fresh target26-byte block3 and
LE16 extrema; the broken legacy cache and other layouts remain separate.

Version0.62 removes the native lower-half fan-request restriction: full byte0..255
and CLI requested percent0..100 now retain the existing ownership/low-RPM/fault
watchdog. Stored requests and mode readback are explicit; actual firmware duty
and RPM remain separate. Original global mutex and selector storage are replaced
by kernel serialization and the single qualified logical channel, with no
unsupported channel selection or general manual timer lease.

The immediate battery setter source passes Control_status to DEVS1179735 without
user-choice persistence. Native accepts meaningful percent0..100, matching Linux
ASUS RSOC; ToUser also records the caller choice. The native driver's readback is
its cached setting after acknowledgment, not a separate physical cutoff sensor.
Software range/fault qualification and installed same-value100 remain distinct
from unperformed low-threshold charging tests.

Version0.60 completes the eight PDO wrapper/shared-reader comparisons. Wrappers
select0..6 and the original reads little-endian DWORDs from fixed DD6 offsets.
The native per-port complete cache preserves raw objects while active-contract
conversion is unavailable, with no numerical conversion of unknown types.
All seven counts/selectors and both ports have positive/fault qualification;
real four-slot stock-source and unplug/port evidence remain separate from
unperformed physical nonfixed-contract qualification.

Version0.59 corrects frequency quantities from the original Intel kernel handlers:
current P-state ratio and single-active-core turbo ratio, using CPU0 and native
CPUID reference MHz without OC-mailbox writes. Separate CPUFreq policy readings
remain available. Per-field MSR faults stay unavailable, without a policy fallback.
XG firmware payload now follows the original31-byte copy boundary and verifies
the collection on the opened HID handle. Physical XG/other processor positives
remain unqualified. AC/PD state stays separate from actual electrical draw.

Version0.58 corrects two lifecycle/configuration source gaps. Original GetInfVersion
selects device description ASUS System Control Interface V2, obtains its driver
registry key and reads DriverVersion. Native now selects actual platform-driver
module metadata, rather than returning the frontend constant. Explicit version
kind separates independently versioned modules from versionless in-tree kernel
drivers. Missing/malformed/changing records remain errors, without a guessed value.

Original app registration associates its path with the current user's identity.
Native applies the actual caller/sudo identity and configuration context through
an unprivileged bounded worker, preserving private app records and unrelated keys.
Its revision/lock/atomic-replace contract covers actual file bytes and absence.
Root caller context no longer selects the wrong home or writes user paths with
effective root. No app launch, boot policy, hardware/factory mutation or changed
desktop/session authority is introduced.

Version0.57.1 completes the four remaining native OEM wrapper comparisons.
Original contract-PDO reads accumulate bank6/21..1e as a little-endian object;
the qualified native counterpart reads the actual per-port EC contract cache,
with validity/AC/consistency gates and explicit port selection. Source errors
and unsupported sentinels map to typed native errors. It remains a negotiated
limit object, not a live current/power measurement.

CPU voltage follows original DSTS present-bit/low-mV selection and its Intel
driver fallback. The actual ASUS driver IOCTL80102080 reads MSR198[47:32], scales
by1000/8192 and truncates; native uses that same quantity rounded to integer mV.
Windows ATD wrappers use commandcode/param0/param1 and string value transport.
The explicit native HealthyTable namespace is separate, with no ARM address
reinterpretation or new model qualification. Raw bank6 writes now rely on actual
qualified bank/packet guards instead of an invented other-register predicate.
Read/write schemas and digest-bound raw recipe3 are explicit. All physical
factory/raw writes remain unperformed.
Completed OEM write transport is reported separately from unproven firmware
acknowledgment/readback; no reply exists on that fixed path.

Version0.56 grouped source review covers ten EFI functions and seven OEM controls.
All EFI variable names, GUID selection, five field widths/offsets, full256-byte
HEAL table and CSC command match their source. Independent installed native/CLI/C
record reads and all five review-plan digests agree; factory-write proof remains
simulation-only. Original secgpnv/Windows privilege plumbing is replaced by the
native efivarfs path; no vendor binary is executed. Other firmware families are
not physically qualified.

Two OEM command recipes were incomplete: power-drop monitor boolean encoding
and version24+ observed-bit power clearing. They now match the source, with
14/19/23 version gates and strict typed errors. Fixed adapter controls do not
infer capability from a nonzero bank6[0] byte. Existing qualified max-bank5 still rejects
missing bank6/7 before I/O. Native write plans bind revision2/recipe metadata;
old digests are rejected. Source/fault/trace fixtures do not establish new
physical device support.

Version0.55 closes the omitted user-choice side effects in two controls.
Battery-health ToUser and quiet/profile selections now save a successful native
caller-owned record, separately from the immediate-only battery setter. Native
paths and typed values replace Windows registry/app-relative files; Windows app
binary compatibility remains outside scope. The original setter contract does
not establish an automatic boot battery policy. Existing desktop Power Profiles
monitoring remains the profile authority. Private file ownership, privilege drop,
bounded parsing, concurrent revisions and partial hardware errors are explicit.

Version0.52 corrects connected-network type and Bluetooth class reports after
reviewing their full shared helpers. The network source prefers connected
physical Ethernet, cellular, then Wi-Fi, excluding tunnels. Native output retains
that priority with stable device-backed Linux link/carrier state and existing
NetworkManager type metadata. Generic Ethernet framing or interface names do not
identify cellular links. Unknown active types and changing identities remain
partial, rather than a false Ethernet/tunnel label or definitive low-priority
choice. This is media connectivity, not an Internet/default-route test. Native
cellular is generic WWAN and does not assert Windows3GPP2 technology.

Bluetooth connected rows now include optional raw Class-of-Device and the original
major-class classification, including Uncategorized/Other. Missing or invalid
Class remains unavailable independently of known connection count and other
metadata. No icon/UUID class guess, pairing, inquiry or device state change.
The pinned BlueZ owner is checked again before accepting the inventory.

Version0.51 replaces all60 remaining whole-snapshot field aliases after grouped
original-source review. Fan getters work independently during manual ownership;
EC telemetry rejects competing manual ownership and CLI show preserves independent
readings beside an explicit EC error. The numeric EC family selector, packed chip
word,14-byte chip-name buffer, full-charge status bit and signed charging current
follow the original quantities. Battery summaries distinguish current terminal
voltage from nominal design voltage, decode a validated manufacture date, and
retain exact remaining/full percentage plus the original decile bucket. Native
capacity counterparts use Linux charge counters in mAh, without energy estimates.
Profile/threshold support and configured RAPL watts use their own Linux providers.

BatteryInformation is the original opaque32-byte firmware-cache payload, with
fixed volatile read request10 and ready bit10. Cached PF uses request80, ready20
and four bytes. Explicit root-only reads preserve error/busy/timeout/ready gates,
bounded polling, two identical frames and status rechecks. Firmware error bit6
rejects data; no partial byte is padded with zero. PFalarm uses bit7 AND NOT bit6
of the same cache-status byte, independently of the separate BatteryError flag.
Source coverage, current firmware availability and physical qualification remain
separate. No reset, unseal, persistent battery configuration or factory test.

Version0.50.1 corrects nine legacy inventory field aliases. Recovered queries use
Baseboard.Manufacturer/Product, ComputerSystem.SystemFamily/Model, Bios.Name/
ReleaseDate, Processor.Name, VideoController.Caption and OperatingSystem caption/
architecture plus native version retrieval. Dedicated strict providers replace
unrelated whole-sensor snapshots, distinguish family/baseboard/system fields,
validate calendar dates/placeholders and retain source errors. CPU is a model-name
string; GPU captions are local PCI descriptions matched against stable numeric
identities, including unbound class03 devices, with independent name availability.
OS data separates declared distribution, kernel version and kernel ISA width.
No shell evaluation or invented default distribution/name occurs. Parsing and
selection faults retain partial coverage or typed unavailability. GetUWPVersion
also reports bundled bridge4 separately from actual desktop activation.

Four related battery wrappers also follow their actual source selections. ECChipID
is the numeric BB10 byte (zero is valid), separate from ASCII chip name. ASOC uses
the unrounded full/design fraction, Capacity uses remaining charge with explicit
native mAh units, and CellVoltage retains all four channels with independent
measurement availability. The fragmented summary helper was reviewed through its
full3b070..3b590 span; its first exception fragment alone omits the calculations.
Only existing Linux counters and qualified EC snapshot fields are used.

Version0.49 corrects the fourteen previously generic OS contracts after reviewing
the original export/helper bodies. CPUID returns actual four-register instruction
results (leaf input, original subleaf0); the C helper is unprivileged and checks
thread CPUID availability. CPU_ReadCPUUsage returns a busy fraction0..1, while
WMIGetCPUUsg uses percent0..100; model name is a first-processor string and CPU
architecture uses the original numeric enum. Local time uses the original local
calendar format. Exact fifth Type11 OEM string replaces the unrelated SKU value;
UUID/system/baseboard serial sources and placeholder errors are explicit. Chassis
keeps the code plus recovered ASUS classification. Card-reader caption selects
only USB0bda:0129. MAC queries enumerate device-backed current addresses, with
software-only links excluded and no permanent-address claim.

Bridge4 reports native normal Alt-Tab membership across workspaces in explicit
top-first compositor stack order. Each window receives PID-scoped CPU/RSS totals,
including valid zero/idle values and independent errors; these are shared process
values, not additive per-window memory. PID/start-tick checks reject reuse both
across samples and after the final window query. Titles remain opt-in. Existing
AT-SPI fallback uses pinned unique D-Bus owners directly, never initializes
libatspi or activates providers, and marks stack/focus/completeness unknown.
Bridge3 stays supported with unknown stack; actual owner Shell bridge4 activation
and logical NumLock transitions remain pending a normal login. Positive software
fixtures do not establish real compositor/device qualification.

Version0.48 ports six software-inventory contracts to explicit native package
reports. Source separates native/WOW6432 uninstall machine/user registrations,
DisplayName/Version/SystemComponent and AppxAllUserStore package registrations.
Linux categories use declared package databases, including components, rather
than infer Windows uninstall flags or manual executables. dpkg registered present
states retain held packages and mark partial configuration; authoritative ABI
width replaces fixed architecture lists. Independent and unclassified packages
stay separate. Flatpak apps plus --all runtimes include extensions and installation
scope. snapd's fixed installed-only Unix HTTP GET includes retained revisions;
installed manifests supply architectures, including the verified format default
all for an omitted/empty list. No host-ISA fallback is used. Good providers/records
survive other errors, with bounded parse details and explicit completeness.
Missing versions remain null. No install/refresh/store-search command is exposed.

Version0.47.1 replaces the unsorted same-UID AppList process provider. Original
CPU/memory queries rank positive process counters descending, limit5/10, and
include both CPU and memory fields. Native /proc/PID/stat/statm samples all visible
PIDs, excludes PID0, uses each process's user+system tick delta over a measured
monotonic interval, and reports resident bytes from kernel pages. PID/start-tick
identity prevents mixing replacements. Unknown/new/regressed/short or uncertain
CPU samples stay unavailable; incomplete candidates mark rankings incomplete.
A bounded error list retains total/truncation counts. No psutil name fallback,
command-line/environment read, UID filter, float clamp, original /10 formatting
constant or 32-bit memory overflow is carried over. Native CPU uses one CPU100%;
RSS is a resident counter, not private/unique memory. Tied ranks use PID order.

Version0.46 corrects AppList_HardwareConfig: original WmiMonitorBrightness
CurrentBrightness and default-render-endpoint volume/mute are represented by
per-backlight kernel actual/max levels and the default PipeWire output setting.
Display/audio availability is independent; valid zero, mute and amplification
are preserved. No CPU/process inventory substitutes for these values. The shared
System_Read_VolumeLevel reader validates the complete wpctl reply and exposes
muted effective percentage separately from the configured level. Queries reject
arguments before access and never modify brightness, routing, volume or mute.

Version0.45 ports the omitted EEPROM E5 event stream and full bounded native
collector. The actual Windows ATK driver routes IOCTL22240c through the same ASUS
WMI GUID and zero-padded1024-byte buffer; its four-byteFE return is unsupported.
Recovered source checks5a/a5,9+byte6 and two consecutive failed reads. Native
frames remain opaque, validated against actual reply bounds, with explicit errors,
truncation and no complete-history claim. Version/date/common/BU selectors retain
their separate semantics, including selector-specific all-ones handling. Only an
explicit privileged table API collects records; cache/metrics never do. Current
versionFE blocks the new transport before WMI. Positive source/fixture contracts
and installed negative hardware proof are separate; no new model is qualified.

Version0.44.1 restores two omitted storage routes found by the full installed
read audit. Original HDDCaption selects fixed media (including SSDs), while
HDDInfo selects rotating disks; both now dispatch to cached storage_inventory.
Selection/field errors stay typed and unknown arguments are rejected before I/O.

Version0.44 exposes fixed probe-time firmware query replies without root or RPC
on each public read. GetSENSOR_WMI_Data preserves the original DSTS0x60068 raw
mask, including valid zero. The original EEPROM read uses DEVS0x60059/selectorE0:
its live return is0xfffffffe (unsupported method), distinct from the zero DSTS
support-query branches. ASL has a conditional WCHK/SMM fallback, so the earlier
claim of a direct DEVS-zero stub was incorrect. The native API reports the
recognized unsupported version result; no date/array/physical EEPROM is invented.
Cached metadata includes exact recipes, status and raw-valid flags. Provider,
transport and invalid-schema failures remain distinct. BIOS/CMOS inventory keeps
unknown table availability when its diagnostic provider fails. No contents read.

Version0.43 proves that the qualified firmware has no legacy adapter diagnostic
bank6. Its complete DD dispatcher implements banks1..5/81..85; all other banks
return without a response. Bounded scalar traces of the cached firmware exercise
three payload stages, omitted read/write banks and implemented-route controls;
BB50/51 return15/2 as on the native device. The kernel now prevents requests above
bank5 and marks unsupported telemetry separately from read failures. Ten original
bank6 getters use the qualified native availability contract (EOPNOTSUPP), without
privilege or retrying a missing bank. Rating/config metrics share that distinction.
Original bank6/7 mutation recipes remain recoverable in plans and simulations,
but the qualified native transport rejects their application before port I/O.
Input ADC, source PDOs, charger/battery measurements and fan control are separate.

Version0.42.1 corrects three original adapter-rating routes. Their x86 path requires
HealthyTable>=28, using bank12 two-byte values; DSTS0x1200f2 subindices1/2/3 are
ARM64-only in the original. Qualified protocol15 therefore returns EOPNOTSUPP
before any rating request or privilege escalation. No PDO limit/nominal wattage
or measured input draw substitutes for a distinct rating. A new metrics report
includes the source gate and existing bank6 config/quarantine observation; static
bank6 firmware absence remains unproven. Exact EC identity/ownership checks are
shared with specialty temperatures; no allowlist or firmware command added.

Version0.41 replaces nine guessed hwmon-label substring routes with the recovered
native platform dispatch and explicit per-role availability. The original uncached
EcFwRev vendor gate selects familyffff for raw vendor2; eight getters return an
unsupported zero sentinel. GPU TS1L instead falls back to HealthyTable bank2,
selector3, if legacy ASUS1000 is absent. That channel is already sampled/mapped
as EC GPU; its current zero remains ENODATA. Other eight roles return EOPNOTSUPP,
not zero degrees. Native identity/manual/census guards are mandatory; provider
errors remain distinct from proven platform unavailability. Windows registry
cache overrides are outside native scope. No new legacy command or location guess.

Version0.40 corrects eight storage inventory/size selectors. Original HDD list/model
queries select rotating media, HDD size selects all fixed media (including SSDs),
SSD list/model use non-rotating fixed media, and physical disk info separates these
classes from removable readers. SD caption intentionally lists generic removable
media; SD size applies its separately recovered caption filters, augmented with
explicit kernel SD/SDcombo type. Non-removable eMMC is not a removable SD card.
Kernel classifications are labelled, not independent physical media measurements.
A sysfs-only census validates identities/fields and preserves partial errors; exact
lists/totals are withheld when selection or selected metadata is incomplete.
Original HDD filesystem usage now selects rotating disks, matching MediaType3;
SSD usage selects the non-rotating fixed class. Both require current kernel class
agreement with the lsblk mount tree. Per-filesystem availability remains; the
separate all-drive temperature query retains its scope.

Version0.38 corrects installed-memory semantics for five original memory APIs.
Recovered Win32_PhysicalMemory properties map to validated cached SMBIOS Type17
records. Installed bytes and per-device manufacturer/part/capacity/speed/locator
replace the OS-usable-memory substitution. Configured data rate never falls back
to maximum speed. Missing/invalid/partial records withhold complete totals and
retain explicit errors; optional field errors do not erase valid capacity. All
five calls require privilege through the existing CLI/C permission contract.
Firmware declarations remain distinct from measurements and OS memory usage.

Version0.37 fixes USB data-inventory availability and connected root-port grouping.
Unknown mappings no longer become false Type-C or exact zero A/C counts; malformed
mandatory descriptors remain explicit failures. Optional metadata errors retain
verified presence. Hubs remain excluded from the legacy non-hub device count but
are included in connection queries. Reciprocal kernel peer and registered Type-C
links merge speed halves/aliases, without serial/name/vendor guesses or a control
operation. Power-only cable detection remains in the separate PD providers.

Version0.36 corrects the GNOME50 context adapter before owner activation: bridge3
resolves the stage's Clutter context/backend, then seat/keymap. The earlier Shell
Meta.Backend has no get_default_seat; its isolated transport proof did not validate
that caller domain. Installed typelib methods and GNOME50.1 source now back the
complete route. Client rejects old bridge2. Owner activation remains pending.

Version0.35 ports logical Num Lock through the existing GNOME seat keymap bridge.
Primary num_lock no longer substitutes kernel LEDs for desktop-session state;
num_lock_led_consensus and its availability remain separate. Same-user unique
owner/version/type guards and bounded calls prevent missing providers becoming
false. The actual GJS/D-Bus transport has isolated true/false proof; owner-session
activation and physical toggle transitions remain pending until a normal login.
No event stream, state write, Shell evaluation or logout automation is used.

Version0.34 preserves input and display metadata availability. Unreadable input
capabilities/LEDs no longer create an exact keyboard count or partial Num Lock
consensus. DRM status failures remain unknown; optional mode/base-EDID errors do
not erase known connection state. Header/checksum/version and identity text gates
prevent malformed monitor names; no event stream, modeset, DDC or state write.
The native Num Lock source is a complete LED consensus, not desktop-session state.

Version0.33 retains per-filesystem capacity failures in the two original disk-usage
APIs instead of returning incomplete/empty success lists. Readable rows preserve
kernel units/reserved-space semantics; unmounted present disks have explicit
unavailability. Repeated shared block-tree entries are deduplicated and no usage
percentage is inferred from a failed read. These are filesystem capacities, not
I/O activity. One discarded inventory query is removed from usage/temperature
routing; temperature behavior otherwise remains unchanged.

Version0.32 switches SBS measurements to the target native SMBus ReadWord worker
(opcode16/subindex9), qualified by34 fixed reads. Same16 READ commands and units,
exact identity/specification/mode gates and49-byte restoration remain. Complete
30-byte RX suffix is checked after every word, with a single suffix seed before
collection. Native completion/result is explicit; no combined-I2C fallback or
legacy software-SRAM observation is used. Installed concurrent checks are in the
validation notes; this does not establish infallible firmware or physical nonzero
charge/discharge accuracy.

Version0.31 adds a conditional fixed software-SRAM observer for the remaining SBS
failure. Its four bytes are double sampled before mandatory restoration under ECMT,
with no hardware status/FIFO access or writes. Raw copies may be stale/reused;
they are not fault measurements or inputs to data acceptance/retry/control.
Cached diagnostic reads add no I/O; collection now adds eight fixed SRAM reads
only on qualified unsuccessful completion. Underlying failure remains unresolved.

Version0.30 retries one complete fresh SBS collection only after the qualified
worker reports unsuccessful completion0x40 and all49 IPC bytes restore/read back.
ECMT is released for100ms first; failures remain in diagnostics. No retry applies
to identity/transport/short-frame or restoration errors. This does not reinterpret
a failed reply as data, change command support or identify the underlying bus cause.

Version0.29 adds read-only SBS attempt diagnostics without changing controller
requests, timing, retry policy or restoration. Cached phase/command/completion
observations retain failures after recovery. This instruments the demonstrated
intermittent EIO gap; it does not establish a fix or additional gauge support.

Version0.28 validates GPU per-engine PMU and tablet-switch availability. Invalid GPU
samples remain unavailable rather than clamped idle/full; no multiplexed count is
extrapolated. Tablet off requires a complete readable switch census; positive
state can survive an unrelated unreadable switch. Only fixed current-state ioctls
are used; input events are not read. Physical fold transitions and other GPU
hardware remain separate unperformed qualifications.

Version0.27 exposes seven recorded firmware temperature-region durations and two
applicable cell-balancing counters from the complete lifetime frames. Region codes
retain unknown actual Celsius thresholds; these are history, not additional
thermistors or current balancing/region status. Two-hour units follow the matched
compatible layout with time-cadence/coherence evidence; nonzero physical balancing
accumulation remains untested. Extra OEM block3 bytes remain raw.

Version0.26 adds qualified recorded battery firmware runtime from block3 word0
(U16,2h steps), corroborated by a same-word live cadence interval and the published
compatible layout. Full raw block and old opaque4-byte compatibility field remain;
the new typed field is separate. First8-word consistency/maximum/complete-frame
guards withhold unqualified values. Temperature-region meanings, reset behavior
and extra OEM bytes remain unknown; this counter is not host uptime or battery age.

Version0.25 separates wireless link measurements from AP-cache queries. Current
association/RSSI/channel/reported PHY/rate and active-peer chains use fixed
read-only nl80211 queries, independent of NetworkManager and AP cache presence.
Kernel RSSI counts require explicit dBm; relative quality cannot produce a strong
RSSI count or a false zero. NetworkManager AP counts use an existing bounded
cache, verified timestamps/identities and unique BSSID/frequency observations.
Counts are cached BSS observations, not a fresh physical AP census; no active
scan is requested. Kernel driver association supplies card metadata separately.

Version0.24 corrects UCSI power metadata and status availability. UCSI voltage/
current fields are contract/Type-C advertisements, not ADC measurements; native
show/metrics keep them separate from the ISL9241 shared-input ADC. The PD input
Boolean uses validated role/path/type state, preserving unknown/error states.
CPU frequency reads use a dedicated complete-policy provider with per-policy
availability and source semantics; loaded-module metadata has no empty/zero
fallback. Real signed battery current-1mA is preserved, distinct from missing raw
words. See the provider qualification and simulated boundary/error cases below.

Version0.23 adds direct read-only SBS measurements beyond the original API
inventory. `battery_sbs` and the CLI gauge report expose pack voltage/current,
average current, selected battery temperature, desired charge values, gauge SOC
and its error margin, capacity mode/capacities, design voltage and cycles. Gauge
estimates and requests are explicit; no energy conversion from nominal voltage.
The original252 API mappings retain their existing sources. Installed readings
still need meaningful charge/discharge qualification; see `docs/VALIDATION.md`.

Version0.20 recovers complete battery-reported identity strings and the original
raw gauge byte, replacing empty cache values. ACPI laptop strings are separate.
Physical IC vendor identification remains unverified.

Version0.18 adds live gauge power/algorithm temperature and replaces the three
WWAN inventory dumps with typed read-only ModemManager data. Actual modem
qualification remains pending; signal timestamps and unmatched OEM tail fields
remain explicit rather than inferred.

Complete lifetime blocks in0.17 recover the recorded FET maximum and two event
cycle tails. Exact OEM block2/3 lengths differ from the TI reference; their
additional bytes and runtime units remain uninterpreted. Full raw transport
coverage does not establish field semantics.

Additional native metrics in 0.12: charger die/pin ADCs and live protection,
CPU thermal counters, NVMe SMART health and complete source PDO profiles. These extend the Linux interface;
they do not substitute charger die temperature for the original physical
choke/ACFET/connector APIs. See `zenbook-hardware metrics`.

Notable boundaries:

- No XG Mobile or WWAN hardware is connected. XG firmware has recovered HID
  request/response tests; actual-device validation is pending.
- WOA-named APIs offer explicit x86 HealthyTable access. ARM ATD_STS command
  transport is not implemented or qualified by this x86-only project.
- Core, SSD, Wi-Fi and ACPI temperatures are also aggregated from Linux hwmon.
- The all-drive temperature API preserves working readings alongside explicit
  per-device failures. Installed CLI and C checks retained the NVMe reading
  beside two unavailable rows (standby and failed provider).
- Active fixed USB-C contracts use the recovered EC ACPI cache. Nominal limits
  are available. The separate native ISL9241 provider reads input voltage and
  current ADCs and computes input watts. Source PDOs use complete per-port
  RX_SOURCE_CAPS EC caches; other ASUS diagnostic-bank queries remain unavailable. This does not replace the original
  opaque ASUS Charger_Information API with a different schema.
- PSYS sampled platform power is an additional read-only native measurement.
  It is separate from USB-C input current/power. The optional Vitals adapter
  displays platform power, input ADC measurements and explicitly labelled PD limits.
- Charger ADC access uses the OEM combined-read firmware worker, including its
  pending-transaction drain. Only fixed read-only registers are accepted. Volatile
  mailbox bytes are restored and verified, with a fault latch on restoration failure.
  The 10 milliohm input-shunt scale is qualified from this BIOS current-DAC code;
  external meter calibration and physical suspend/resume are still unverified.
- The five board thermistors now have matched ACPI/EC labels. Nine separate
  specialty temperature API names and Wi-Fi main/aux identities still lack
  verified physical mappings; CPU/charger NTCs are not relabelled as ACFET/choke.
- Full GNOME enumeration uses the optional bridge after the next login. AT-SPI
  is a current-session fallback with explicit limited coverage.
- Full byte fan requests remain subject to low-RPM/fault restoration; actual duty/RPM calibration is separate.
- Fresh lifetime prefixes replace the repeated EC cache in the original peak
  and lifetime APIs. Qualified extrema are decoded; runtime units, trailing
  scratch bytes and other block layouts remain explicitly unqualified.

Implementation parity and physical validation are not interchangeable.
See [validation](VALIDATION.md) and [protocol notes](PROTOCOL.md).

| Original API | Native route | Parity | Verification |
| --- | --- | --- | --- |
| `Adapter_Clear_Charger_Data` | `native_oem` | recovered_protocol | live_plan_verified; writes_simulated_only |
| `Adapter_Clear_Power_Data_Flag` | `native_oem` | recovered_protocol | live_plan_verified; writes_simulated_only |
| `Adapter_Read_ChampionPort_Watt` | `adapter_ratings` | firmware_provider_required | original_protocol_and_architecture_gates; qualified_identity; explicit_unavailability |
| `Adapter_Read_Charger_Information` | `adapter_diagnostics` | firmware_provider_required | complete_firmware_DD_switch; qualified_support_mask; explicit_unavailability |
| `Adapter_Read_Charger_Interrupt` | `native_oem` | recovered_protocol | live_plan_verified; writes_simulated_only |
| `Adapter_Read_Contract_PDO` | `native_oem` / EC ACPI cache | native_equivalent | Active fixed PDO cross-checked with cached voltage/current/watts; disconnect gate |
| `Adapter_Read_PDO` | `pd_sources` / EC RX_SOURCE_CAPS | native_equivalent | Complete fixed cache; active-contract cross-check; absent slot ENODATA |
| `Adapter_Read_PDO1` | `pd_sources` / EC RX_SOURCE_CAPS | native_equivalent | Complete fixed cache; active-contract cross-check; absent slot ENODATA |
| `Adapter_Read_PDO2` | `pd_sources` / EC RX_SOURCE_CAPS | native_equivalent | Complete fixed cache; active-contract cross-check; absent slot ENODATA |
| `Adapter_Read_PDO3` | `pd_sources` / EC RX_SOURCE_CAPS | native_equivalent | Complete fixed cache; active-contract cross-check; absent slot ENODATA |
| `Adapter_Read_PDO4` | `pd_sources` / EC RX_SOURCE_CAPS | native_equivalent | Complete fixed cache; active-contract cross-check; absent slot ENODATA |
| `Adapter_Read_PDO5` | `pd_sources` / EC RX_SOURCE_CAPS | native_equivalent | Complete fixed cache; active-contract cross-check; absent slot ENODATA |
| `Adapter_Read_PDO6` | `pd_sources` / EC RX_SOURCE_CAPS | native_equivalent | Complete fixed cache; active-contract cross-check; absent slot ENODATA |
| `Adapter_Read_PDO7` | `pd_sources` / EC RX_SOURCE_CAPS | native_equivalent | Complete fixed cache; active-contract cross-check; absent slot ENODATA |
| `Adapter_Read_PDO_Watt` | `adapter_diagnostics` | firmware_provider_required | complete_firmware_DD_switch; qualified_support_mask; explicit_unavailability |
| `Adapter_Read_PD_ADO` | `pd_identity / adapter_diagnostics` | firmware_provider_required | Original DD6/26 byte is unavailable on this firmware; native_alert=true explicitly selects separate received ADO32, without asserting a byte mapping. |
| `Adapter_Read_PD_Get_Emark_Other` | `pd_identity` | hardware_provider_required | received identity provider implemented; current connection has no ACK |
| `Adapter_Read_PD_Get_Emark_PID` | `pd_identity` | hardware_provider_required | Fresh fixed reads; see 0.13 qualification |
| `Adapter_Read_PD_Get_Emark_VID` | `pd_identity` | hardware_provider_required | Fresh fixed reads; see 0.13 qualification |
| `Adapter_Read_PD_Get_Emark_XID` | `pd_identity` | hardware_provider_required | Fresh fixed reads; see 0.13 qualification |
| `Adapter_Read_PD_Get_Source_Cap_Extend_FWVersion` | `adapter_diagnostics` | firmware_provider_required | complete_firmware_DD_switch; qualified_support_mask; explicit_unavailability |
| `Adapter_Read_PD_Get_Source_Cap_Extend_HWVersion` | `adapter_diagnostics` | firmware_provider_required | complete_firmware_DD_switch; qualified_support_mask; explicit_unavailability |
| `Adapter_Read_PD_Get_Source_Cap_Extend_PID` | `adapter_diagnostics` | firmware_provider_required | complete_firmware_DD_switch; qualified_support_mask; explicit_unavailability |
| `Adapter_Read_PD_Get_Source_Cap_Extend_VID` | `adapter_diagnostics` | firmware_provider_required | complete_firmware_DD_switch; qualified_support_mask; explicit_unavailability |
| `Adapter_Read_PD_Get_Source_Cap_Extend_XID` | `adapter_diagnostics` | firmware_provider_required | complete_firmware_DD_switch; qualified_support_mask; explicit_unavailability |
| `Adapter_Read_PD_Get_Status_EventFlag` | `adapter_diagnostics` | firmware_provider_required | complete_firmware_DD_switch; qualified_support_mask; explicit_unavailability |
| `Adapter_Read_PD_Get_Status_Temperature` | `adapter_diagnostics` | firmware_provider_required | complete_firmware_DD_switch; qualified_support_mask; explicit_unavailability |
| `Adapter_Read_PD_IC_PN` | `native_oem` | recovered_protocol | live_value_returned |
| `Adapter_Read_Power_Big_Data_Config` | `adapter_diagnostics` | firmware_provider_required | complete_firmware_DD_switch; qualified_support_mask; explicit_unavailability |
| `Adapter_Read_Power_Data_Flag` | `native_oem` | recovered_protocol | live_plan_verified; writes_simulated_only |
| `Adapter_Read_Standard_Watt` | `adapter_ratings` | firmware_provider_required | original_protocol_and_architecture_gates; qualified_identity; explicit_unavailability |
| `Adapter_Read_Sufficient_Watt` | `adapter_ratings` | firmware_provider_required | original_protocol_and_architecture_gates; qualified_identity; explicit_unavailability |
| `Adapter_Set_Notify_Control` | `native_oem` | recovered_protocol | live_plan_verified; writes_simulated_only |
| `AppList_CpuUsage` | `linux_services` | native_equivalent | original selection/units recovered; native rank/identity/partial sampling qualification |
| `AppList_HardwareConfig` | `linux_services` | native_equivalent | source contract, typed availability; read-only native qualification |
| `AppList_MemUsage` | `linux_services` | native_equivalent | original selection/units recovered; native rank/identity/partial sampling qualification |
| `AppList_OpenWindows` | `linux_services / desktop_windows` | native_equivalent | bridge4_JS_and_wire_schema_tests; selected_PID_and_reuse_tests; caller_authorization_title_opt_in_and_Shell_owner_tests; real_Shell_activation_pending; AT_SPI_partial_fallback |
| `App_Get_UWPApp` | `linux_services` | native_equivalent | original registration sources; native scope/ABI/provider/error and installed-package qualification |
| `App_Get_Win32App` | `linux_services` | native_equivalent | original registration sources; native scope/ABI/provider/error and installed-package qualification |
| `App_Get_Win32WOW6432App` | `linux_services` | native_equivalent | original registration sources; native scope/ABI/provider/error and installed-package qualification |
| `BatteryHealthyTable_ACStatus` | `linux_services` | native_equivalent | Direct validated0/1 ACPI status; no fabricated offline |
| `BatteryHealthyTable_BatteryError` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_BatteryInformation` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_CellVoltage1` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_CellVoltage2` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_CellVoltage3` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_CellVoltage4` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_ChargingCurrent` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_ChargingVoltage` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_Current` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_CycleCount` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_DesignVoltage` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_DeviceName` | `battery_identity` / fixed SBS block READ | native_equivalent | Complete manufacturer/model probe;455 fault points; native/C exact raw agreement |
| `BatteryHealthyTable_ECChipID` | `linux_services / battery_summary` | native_equivalent | source_property_and_units; valid_zero_and_partial_channel_tests; installed_scope_in_docs_VALIDATION |
| `BatteryHealthyTable_ECChipName` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_FullChargeCapacity` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_FullCharged` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_GaugeIC` | `battery_identity` / fixed SBS block READ | native_equivalent | Complete manufacturer/model probe;455 fault points; native/C exact raw agreement |
| `BatteryHealthyTable_LidStatus` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_ManufactureDate` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_ManufactureName` | `battery_identity` / fixed SBS block READ | native_equivalent | Complete manufacturer/model probe;455 fault points; native/C exact raw agreement |
| `BatteryHealthyTable_ManufactureNameBySMBus` | `battery_identity` / fixed SBS block READ | native_equivalent | Complete manufacturer/model probe;455 fault points; native/C exact raw agreement |
| `BatteryHealthyTable_PFStatus` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_PackageVoltage` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_ReadVendorType` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_ReadVersion` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_RemainingCapacity` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_Rsoc` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_SafetyStatus` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_SerialNumber` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_Temperature` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthyTable_TimeoutStatus` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthy_Check_PFalarm` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `BatteryHealthy_Read_LifetimeBlock1` | `battery_diagnostics` | native_equivalent | Complete fixed payload; sentinel/prefix/restoration checks; unmatched OEM fields raw |
| `BatteryHealthy_Read_LifetimeBlock3` | `battery_diagnostics` | native_equivalent | Complete raw26-byte frame plus U16 runtime/seven region durations in2h steps; thresholds unknown; see0.27 |
| `BatteryHealthy_Read_LifetimeBlock4` | `battery_diagnostics` | native_equivalent | Complete fixed payload; sentinel/prefix/restoration checks; unmatched OEM fields raw |
| `BatteryHealthy_Read_LifetimeBlock5` | `battery_diagnostics` | native_equivalent | Complete fixed payload; sentinel/prefix/restoration checks; unmatched OEM fields raw |
| `BatteryHealthy_Read_MaxCellDeltaVoltage` | `battery_diagnostics` | native_equivalent | Fresh fixed reads; see 0.13 qualification |
| `BatteryHealthy_Read_MaxChargeCurrent` | `battery_diagnostics` | native_equivalent | Fresh fixed reads; see 0.13 qualification |
| `BatteryHealthy_Read_MaxDischargeCurrent` | `battery_diagnostics` | native_equivalent | Fresh fixed reads; see 0.13 qualification |
| `BatteryHealthy_Read_PFStatus` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `Battery_Get_LidStatus` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `Battery_Read_ASOC` | `linux_services / battery_summary` | native_equivalent | source_property_and_units; valid_zero_and_partial_channel_tests; installed_scope_in_docs_VALIDATION |
| `Battery_Read_Capacity` | `linux_services / battery_summary` | native_equivalent | source_property_and_units; valid_zero_and_partial_channel_tests; installed_scope_in_docs_VALIDATION |
| `Battery_Read_CapacityPercentage` | `field_reads` | native_equivalent | source + fault/decoder tests; live state separate |
| `Battery_Read_CellVoltage` | `linux_services / battery_summary` | native_equivalent | source_property_and_units; valid_zero_and_partial_channel_tests; installed_scope_in_docs_VALIDATION |
| `Battery_Read_ChargingVoltage` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `Battery_Read_Current` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `Battery_Read_CycleCount` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `Battery_Read_DesignVoltage` | `field_reads` | native_equivalent | source + fault/decoder tests; live state separate |
| `Battery_Read_DesignedCapacity` | `field_reads` | native_equivalent | source + fault/decoder tests; live state separate |
| `Battery_Read_FullChargedCapcity` | `field_reads` | native_equivalent | source + fault/decoder tests; live state separate |
| `Battery_Read_ManufactureDate` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `Battery_Read_ManufactureName` | `battery_identity` / fixed SBS block READ | native_equivalent | Complete manufacturer/model probe;455 fault points; native/C exact raw agreement |
| `Battery_Read_PackageVoltage` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `Battery_Read_Temperature` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `CPU_ReadCPUUsage` | `linux_services / cpu_metadata` | native_equivalent | fraction_units_and_idle_busy_fault_tests; live_range |
| `CPU_ReadCpuFrequency` | `hardware_status` / fixed CPU0 MSR/CPUID | native_equivalent | Source P-state ratio; read-only reference; independent errors; CPUFreq separate |
| `CPU_ReadCpuId` | `linux_services / cpu_metadata` | native_equivalent | raw_CPUID_C_helper_and_vendor_check; argument_and_unavailability_tests |
| `CPU_ReadCpuMaxFrequency` | `hardware_status` / fixed CPU0 MSR/CPUID | native_equivalent | Source single-core turbo ratio; read-only reference; independent errors; CPUFreq separate |
| `CPU_ReadCpuVoltage` | `native_oem` / `in6_input` | native_equivalent | Read-only CPU-reported P-state voltage from MSR 0x198; see VALIDATION.md |
| `CPU_ReadRegCPUInfo` | `linux_services / cpu_metadata` | native_equivalent | first_processor_selection_and_live_model_name |
| `EC_ReadEcChipId` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `EC_ReadEcChipName` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `EC_ReadEcFwRev` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `EC_ReadProjectInformation` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `GPNV_Clear_CSC_Repair_Flag` | `efi_oem` | recovered_protocol | live_plan_verified; writes_simulated_only |
| `GPNV_Get_ActivatedTime` | `efi_oem` | recovered_protocol | live_value_returned |
| `GPNV_Get_HEAL_table` | `efi_oem` | recovered_protocol | live_value_returned |
| `GPNV_Get_HEAL_table_CSC_Repair_Flag` | `efi_oem` | recovered_protocol | live_value_returned |
| `GPNV_Get_ManufacturedTime` | `efi_oem` | recovered_protocol | live_value_returned |
| `GPNV_Get_RandomUUID` | `efi_oem` | recovered_protocol | live_value_returned |
| `GPNV_Set_ActivatedTime` | `efi_oem` | recovered_protocol | live_plan_verified; writes_simulated_only |
| `GPNV_Set_ManufacturedTime` | `efi_oem` | recovered_protocol | live_plan_verified; writes_simulated_only |
| `GPNV_Set_RandomUUID` | `efi_oem` | recovered_protocol | live_plan_verified; writes_simulated_only |
| `GetApplist_UWP` | `linux_services` | native_equivalent | original registration sources; native scope/ABI/provider/error and installed-package qualification |
| `GetApplist_x64` | `linux_services` | native_equivalent | original registration sources; native scope/ABI/provider/error and installed-package qualification |
| `GetApplist_x86` | `linux_services` | native_equivalent | original registration sources; native scope/ABI/provider/error and installed-package qualification |
| `GetDriverVersion` | `lifecycle/configuration` / validated module metadata | native_equivalent | Fixed read, identity bracket and explicit missing/malformed errors; actual zero refcount retained |
| `GetEEPROM_Data` | `firmware_queries` | firmware_provider_required | original_scalar_and_E5_source; bounded_protocol_fixtures; current_unsupported_no_IO |
| `GetInfVersion` | `lifecycle/configuration` | native_equivalent | actual_binding_and_independent_modinfo_native_CLI_C_verified |
| `GetIoDllVersion` | `lifecycle/configuration` | native_equivalent | live_value_returned |
| `GetNum_Key` | `lifecycle/configuration` | native_equivalent | Fixed GNOME session-toggle transport/isolated wire qualified; Shell-owner verified; real owner activation pending; input/LED data separate |
| `GetRefCount` | `lifecycle/configuration` / validated module metadata | native_equivalent | Fixed read, identity bracket and explicit missing/malformed errors; actual zero refcount retained |
| `GetSENSOR_WMI_Data` | `firmware_queries` | native_equivalent | original_DSTS60068; typed_cached_raw_mask; valid_zero |
| `GetUWPVersion` | `lifecycle/configuration` | native_equivalent | native_component_version_metadata; active_session_availability_separate |
| `GetXgmFw` | `lifecycle/configuration` | hardware_provider_required | source31_byte_boundary_and_open_collection_tests; actual_device_absent |
| `HealthyTable_FanCounts` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `HealthyTable_FanRPM` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `HealthyTable_GetFanTestMode` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `HealthyTable_Read_BoardTS0L_Temperature` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `HealthyTable_Read_Cpu_Temperature` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `HealthyTable_Read_Fan` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `HealthyTable_SetFanIndex` | `native_controls` | native_equivalent | source + single-channel native/CLI/C checks; no selector mutation |
| `HealthyTable_SetFanPwmDuty` | `native_controls` | native_equivalent | all256 requests and fault/restoration software tests; installed staging and bounded manual test recorded separately |
| `HealthyTable_SetFanTestMode` | `native_controls` | native_equivalent | source + all-mode/fault software tests; bounded hardware restoration separately qualified |
| `InitializeWinIo` | `lifecycle/configuration` / validated module metadata | native_equivalent | Fixed read, identity bracket and explicit missing/malformed errors; actual zero refcount retained |
| `Power_PD_Charging` | `usb_power` / UCSI role/path/type state | native_equivalent | Known PD/PPS sink input; errors remain unknown; optional limits are not measurements |
| `Power_Read_ACDCMode` | `linux_services` | native_equivalent | Direct validated0/1 ACPI status; no fabricated offline |
| `Power_Set_Monitor_PowerDropped` | `native_oem` | recovered_protocol | live_plan_verified; writes_simulated_only |
| `ProArt_Read_Cpu_Temperature` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `ProArt_Read_Fan` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `RF_AP_MAC` | `linux_services` / nl80211 link/station | native_equivalent | Complete source/shared-helper review; quantity/unit/identity/deadline/fault tests; installed native/CLI/C and independent reads recorded separately. |
| `RF_BTConnectedNum` | `linux_services` | native_equivalent | Bounded existing-owner BlueZ read; known-empty and provider errors distinct |
| `RF_BTConnectedType` | `linux_services` / BlueZ Class | native_equivalent | Connected metadata and optional major class; absent/invalid/owner-change tests |
| `RF_BTIsUsed` | `linux_services` | native_equivalent | Successful connection state required; errors never become false |
| `RF_Net_Connected_Type` | `network_status` | native_equivalent | Source helper + physical/type/priority/owner/error tests; installed state separate |
| `RF_PhyMode` | `linux_services` / nl80211 link/station | native_equivalent | Source/unit/error/cache/identity tests; installed native/CLI/C subset and root cached-count qualification |
| `RF_USBHDMIIsUsed` | `linux_services` / `hdmi_presence` | native_equivalent | Cached HDMI presence; separate explicit USB/partner DP metric; source/fault tests, physical positive pending |
| `RF_USBISTYPEC` | `linux_services / usb_inventory` | native_equivalent | Immediate socket/user visibility, separate host scope, cached bcdUSB distributions and class08 storage subset; guarded partial metadata and physical limits explicit. |
| `RF_USBIsTranster` | `linux_services` | native_equivalent | Complete wrapper/shared-helper source review; threshold/root/identity/reset/suspend/partial and usbmon loss/ABI/fault tests; installed qualification separately recorded. |
| `RF_USBNum` | `linux_services / usb_inventory` | native_equivalent | Immediate socket/user visibility, separate host scope, cached bcdUSB distributions and class08 storage subset; guarded partial metadata and physical limits explicit. |
| `RF_USBPort` | `linux_services / usb_inventory` | native_equivalent | Immediate socket/user visibility, separate host scope, cached bcdUSB distributions and class08 storage subset; guarded partial metadata and physical limits explicit. |
| `RF_USB_A_Num` | `linux_services / usb_inventory` | native_equivalent | Immediate socket/user visibility, separate host scope, cached bcdUSB distributions and class08 storage subset; guarded partial metadata and physical limits explicit. |
| `RF_USB_C_Num` | `linux_services / usb_inventory` | native_equivalent | Immediate socket/user visibility, separate host scope, cached bcdUSB distributions and class08 storage subset; guarded partial metadata and physical limits explicit. |
| `RF_WWAN_Access_Technology` | `linux_services` / `wwan` | hardware_provider_required | Typed getter/roaming/signal tests; installed ENODEV; physical modem absent |
| `RF_WWAN_Home_Provider` | `linux_services` / `wwan` | hardware_provider_required | Typed getter/roaming/signal tests; installed ENODEV; physical modem absent |
| `RF_WWAN_RSSI` | `linux_services` / `wwan` | hardware_provider_required | Typed getter/roaming/signal tests; installed ENODEV; physical modem absent |
| `RF_WiFiCardName` | `linux_services` / wireless sysfs/driver | native_equivalent | Source/unit/error/cache/identity tests; installed native/CLI/C subset and root cached-count qualification |
| `RF_WiFiChannel` | `linux_services` / nl80211 link/station | native_equivalent | Complete source/shared-helper review; quantity/unit/identity/deadline/fault tests; installed native/CLI/C and independent reads recorded separately. |
| `RF_WiFiIsConnected` | `linux_services` / nl80211 link/station | native_equivalent | Complete source/shared-helper review; quantity/unit/identity/deadline/fault tests; installed native/CLI/C and independent reads recorded separately. |
| `RF_WiFiMaxRate` | `linux_services` / nl80211 link/station | native_equivalent | Source/unit/error/cache/identity tests; installed native/CLI/C subset and root cached-count qualification |
| `RF_WiFiRssi` | `linux_services` / nl80211 link/station | native_equivalent | Complete source/shared-helper review; quantity/unit/identity/deadline/fault tests; installed native/CLI/C and independent reads recorded separately. |
| `RF_WiFi_2_4G_AP_Ch_Num` | `linux_services` / NetworkManager existing BSS cache | native_equivalent | Complete source/shared-helper review; quantity/unit/identity/deadline/fault tests; installed native/CLI/C and independent reads recorded separately. |
| `RF_WiFi_2_4G_AP_Num` | `linux_services` / NetworkManager existing BSS cache | native_equivalent | Complete source/shared-helper review; quantity/unit/identity/deadline/fault tests; installed native/CLI/C and independent reads recorded separately. |
| `RF_WiFi_2_4G_AP_RSSI_Num` | `linux_services` / kernel BSS cache; explicit dBm | native_equivalent | Source/unit/error/cache/identity tests; installed native/CLI/C subset and root cached-count qualification |
| `RF_WiFi_5G_AP_Band_Num` | `linux_services` / NetworkManager existing BSS cache | native_equivalent | Complete source/shared-helper review; quantity/unit/identity/deadline/fault tests; installed native/CLI/C and independent reads recorded separately. |
| `RF_WiFi_5G_AP_Num` | `linux_services` / NetworkManager existing BSS cache | native_equivalent | Complete source/shared-helper review; quantity/unit/identity/deadline/fault tests; installed native/CLI/C and independent reads recorded separately. |
| `RF_WiFi_5G_AP_RSSI_Num` | `linux_services` / kernel BSS cache; explicit dBm | native_equivalent | Source/unit/error/cache/identity tests; installed native/CLI/C subset and root cached-count qualification |
| `RF_WiFi_6G_AP_NUII_Num` | `linux_services` / NetworkManager existing BSS cache | native_equivalent | Complete source/shared-helper review; quantity/unit/identity/deadline/fault tests; installed native/CLI/C and independent reads recorded separately. |
| `RF_WiFi_6G_AP_Num` | `linux_services` / NetworkManager existing BSS cache | native_equivalent | Complete source/shared-helper review; quantity/unit/identity/deadline/fault tests; installed native/CLI/C and independent reads recorded separately. |
| `RF_WiFi_6G_AP_RSSI_Num` | `linux_services` / kernel BSS cache; explicit dBm | native_equivalent | Source/unit/error/cache/identity tests; installed native/CLI/C subset and root cached-count qualification |
| `RF_WiFi_Main_Aux_Rssi` | `linux_services` / nl80211 link/station | native_equivalent | Complete source/shared-helper review; quantity/unit/identity/deadline/fault tests; installed native/CLI/C and independent reads recorded separately. Physical Main/Aux mapping remains unverified. |
| `SaveEcLog` | `native_controls` | native_equivalent | live_private_log_verified |
| `ShutdownWinIo` | `lifecycle/configuration` | native_equivalent | live_value_returned |
| `StopWinIoDriver` | `lifecycle/configuration` | native_equivalent | live_stop_initialize_and_independent_restore_verified |
| `System_Check_S_Mode` | `linux_services` | not_applicable | Complete original helper/body review and native/CLI/C not-applicable readback. |
| `System_Read_LocalTime` | `linux_services / platform_metadata` | native_equivalent | format_and_current_local_time |
| `System_Read_TabletMode` | `linux_services` / `tablet_mode` | native_equivalent | Advertised switch current state; partial negative is unavailable; see0.28 |
| `System_Read_VolumeLevel` | `linux_services` | native_equivalent | source contract, typed availability; read-only native qualification |
| `Thermal_Read_ACFET_Temperature` | `specialty_thermal` | firmware_provider_required | original_dispatch_traces; qualified_native_identity; explicit_unavailability |
| `Thermal_Read_BatteryConnector_Temperature` | `specialty_thermal` | firmware_provider_required | original_dispatch_traces; qualified_native_identity; explicit_unavailability |
| `Thermal_Read_BoardTS0L_Temperature` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `Thermal_Read_BoardTS0R_Temperature` | `specialty_thermal` | firmware_provider_required | original_dispatch_traces; qualified_native_identity; explicit_unavailability |
| `Thermal_Read_ChargerChoke_Temperature` | `specialty_thermal` | firmware_provider_required | original_dispatch_traces; qualified_native_identity; explicit_unavailability |
| `Thermal_Read_CpuDptf_PowerLimit1` | `field_reads` | native_equivalent | source + fault/decoder tests; live state separate |
| `Thermal_Read_CpuDptf_PowerLimit2` | `field_reads` | native_equivalent | source + fault/decoder tests; live state separate |
| `Thermal_Read_CpuPackagePower` | `native_controls` | native_equivalent | live_value_returned |
| `Thermal_Read_Cpu_Temperature` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `Thermal_Read_Fan` | `field_reads` | recovered_protocol | source + fault/decoder tests; live state separate |
| `Thermal_Read_GpuTS1L_Temperature` | `specialty_thermal` | firmware_provider_required | original_dispatch_traces; qualified_native_identity; explicit_unavailability |
| `Thermal_Read_GpuTS1R_Temperature` | `specialty_thermal` | firmware_provider_required | original_dispatch_traces; qualified_native_identity; explicit_unavailability |
| `Thermal_Read_GpuVram_Temperature` | `specialty_thermal` | firmware_provider_required | original_dispatch_traces; qualified_native_identity; explicit_unavailability |
| `Thermal_Read_GpuVrm_Temperature` | `specialty_thermal` | firmware_provider_required | original_dispatch_traces; qualified_native_identity; explicit_unavailability |
| `Thermal_Read_UpCpu_Temperature` | `specialty_thermal` | firmware_provider_required | original_dispatch_traces; qualified_native_identity; explicit_unavailability |
| `TraceOutput` | `lifecycle/configuration` | native_equivalent | actual_native_CLI_C_journal_message_priority_verified |
| `TraceOutputCritical` | `lifecycle/configuration` | native_equivalent | actual_native_CLI_C_journal_message_priority_verified |
| `Update_AsusOsLanguage` | `efi_oem` | recovered_protocol | live_plan_verified; writes_simulated_only |
| `WMICheckBatteryHealthSupport` | `field_reads` | native_equivalent | source + fault/decoder tests; live state separate |
| `WMICheckQuietFanSupport` | `field_reads` | native_equivalent | source + fault/decoder tests; live state separate |
| `WMIGet90Number` | `linux_services / platform_metadata` | native_equivalent | cached_type11_and_independent_DMI_table_match; framing_fault_tests |
| `WMIGetBatteryHealth` | `field_reads` | native_equivalent | source + fault/decoder tests; live state separate |
| `WMIGetBiosManufacture` | `linux_services / identity_inventory` | native_equivalent | native_DMI_CPU_OS_PCI_sources; see_docs_VALIDATION_for_installed_interface_scope |
| `WMIGetBiosReleaseDate` | `linux_services / identity_inventory` | native_equivalent | native_DMI_CPU_OS_PCI_sources; see_docs_VALIDATION_for_installed_interface_scope |
| `WMIGetBiosVersion` | `linux_services / identity_inventory` | native_equivalent | native_DMI_CPU_OS_PCI_sources; see_docs_VALIDATION_for_installed_interface_scope |
| `WMIGetBoardUUID` | `linux_services / platform_metadata` | native_equivalent | independent_dmidecode_system_uuid_match; sentinel_fault_tests |
| `WMIGetCPUArchitecture` | `linux_services / cpu_metadata` | native_equivalent | numeric_enum_cases; live_x64_9 |
| `WMIGetCPUInfo` | `linux_services / identity_inventory` | native_equivalent | native_DMI_CPU_OS_PCI_sources; see_docs_VALIDATION_for_installed_interface_scope |
| `WMIGetCPUUsg` | `linux_services / cpu_metadata` | native_equivalent | percent_units_and_fault_tests; live_range |
| `WMIGetCardReaderCaption` | `linux_services / platform_metadata` | native_equivalent | exact_ID_positive_and_partial_fixtures; live_complete_absence |
| `WMIGetComputerFamilyName` | `linux_services / identity_inventory` | native_equivalent | native_DMI_CPU_OS_PCI_sources; see_docs_VALIDATION_for_installed_interface_scope |
| `WMIGetExternMonitorNum` | `linux_services` | native_equivalent | Input/DRM availability regression and installed native/CLI/C checks; 0.71 source review: native connector classification, not Windows instance/type accounting |
| `WMIGetExternMonitorPropList` | `linux_services` | native_equivalent | Input/DRM availability regression and installed native/CLI/C checks; 0.71 source review: typed partial rows, no invented output-technology number |
| `WMIGetGPUInfo` | `linux_services / identity_inventory` | native_equivalent | native_DMI_CPU_OS_PCI_sources; see_docs_VALIDATION_for_installed_interface_scope |
| `WMIGetGPUUsg` | `linux_services` / `gpu_usage` | native_equivalent | 0.71: all advertised DRM/i915 providers labelled with separate errors, coverage and row availability; no summing; not Windows per-process3D maximum. installed 0.71 native/CLI/C census-matched; DRM+PMU and external positives fixture-only |
| `WMIGetHDDCaption` | `linux_services` / storage_inventory | native_equivalent | original_fixed_caption_selection; dispatch_and_error_regressions; installed_native_CLI_C |
| `WMIGetHDDInfo` | `linux_services` / storage_inventory | native_equivalent | original_rotating_info_selection; dispatch_and_error_regressions; installed_native_CLI_C |
| `WMIGetHDDList` | `linux_services` | native_equivalent | selection_and_availability_regressions; live_sysfs_lsblk_agreement |
| `WMIGetHDDModel` | `linux_services` | native_equivalent | selection_and_availability_regressions; live_sysfs_lsblk_agreement |
| `WMIGetHDDSize` | `linux_services` | native_equivalent | selection_and_availability_regressions; live_sysfs_lsblk_agreement |
| `WMIGetHDDTemp` | `linux_services` | native_equivalent | Per-device availability; NVMe retained beside standby/failed-provider rows; mixed-provider/failure tests |
| `WMIGetHDDUsage` | `linux_services / filesystem_usage` | native_equivalent | Complete source flow; pinned mount ID/inode/dev_t and selected disk generation/classification/tree; per-filesystem errors and explicit unknown mappings. |
| `WMIGetLCDModel` | `linux_services` | native_equivalent | 0.71: default internal and external connected/unknown names as original; strict boolean internal_only keeps panel view. installed 0.71 native/CLI/C census-matched; DRM+PMU and external positives fixture-only |
| `WMIGetMacAddress` | `linux_services / platform_metadata` | native_equivalent | device_relation_and_address_fault_tests; live_hardware_census; no_permanent_address_claim |
| `WMIGetMemFrequency` | `linux_services` | native_equivalent | validated_Type17_parser; live_selected_fields_match_dmidecode |
| `WMIGetMemInfo` | `linux_services` | native_equivalent | validated_Type17_parser; live_selected_fields_match_dmidecode |
| `WMIGetMemManufacture` | `linux_services` | native_equivalent | validated_Type17_parser; live_selected_fields_match_dmidecode |
| `WMIGetMemModel` | `linux_services` | native_equivalent | validated_Type17_parser; live_selected_fields_match_dmidecode |
| `WMIGetMemSize` | `linux_services` | native_equivalent | validated_Type17_parser; live_selected_fields_match_dmidecode |
| `WMIGetModelName` | `linux_services / identity_inventory` | native_equivalent | native_DMI_CPU_OS_PCI_sources; see_docs_VALIDATION_for_installed_interface_scope |
| `WMIGetMonitorBrightness` | `linux_services` | native_equivalent | Per-backlight actual/max and identity/range checks; real zero and failures distinct |
| `WMIGetOSInfo` | `linux_services / identity_inventory` | native_equivalent | native_DMI_CPU_OS_PCI_sources; see_docs_VALIDATION_for_installed_interface_scope |
| `WMIGetPhysicalDiskInfo` | `linux_services` | native_equivalent | selection_and_availability_regressions; live_sysfs_lsblk_agreement |
| `WMIGetProductName` | `linux_services / identity_inventory` | native_equivalent | native_DMI_CPU_OS_PCI_sources; see_docs_VALIDATION_for_installed_interface_scope |
| `WMIGetQuietFan` | `field_reads` | native_equivalent | source + fault/decoder tests; live state separate |
| `WMIGetSDCardCaption` | `linux_services` | native_equivalent | selection_and_availability_regressions; live_sysfs_lsblk_agreement |
| `WMIGetSDCardSize` | `linux_services` | native_equivalent | Complete original source/helper review; per-card/scalar/selection/error fixtures; current no-card readback separate from unperformed inserted-card physical positive. |
| `WMIGetSN` | `linux_services / platform_metadata` | native_equivalent | independent_dmidecode_system_serial_match; placeholder_errors |
| `WMIGetSSDList` | `linux_services` | native_equivalent | selection_and_availability_regressions; live_sysfs_lsblk_agreement |
| `WMIGetSSDModel` | `linux_services` | native_equivalent | selection_and_availability_regressions; live_sysfs_lsblk_agreement |
| `WMIGetSSDUsage` | `linux_services / filesystem_usage` | native_equivalent | Complete source flow; pinned mount ID/inode/dev_t and selected disk generation/classification/tree; per-filesystem errors and explicit unknown mappings. |
| `WMIGetSystemChassisTypes` | `linux_services / platform_metadata` | native_equivalent | recovered_full_switch_table; classification_tests; live31_Notebook |
| `WMIGetType2SN` | `linux_services / platform_metadata` | native_equivalent | independent_dmidecode_baseboard_serial_match; placeholder_errors |
| `WMIGetWiFiBytesPersec` | `linux_services` | native_equivalent | Complete source/shared-helper review; quantity/unit/identity/deadline/fault tests; installed native/CLI/C and independent reads recorded separately. |
| `WMIGetWiFiCardName` | `linux_services` / wireless sysfs/driver | native_equivalent | Source/unit/error/cache/identity tests; installed native/CLI/C subset and root cached-count qualification |
| `WMISetAppPath` | `lifecycle/configuration` | native_equivalent | native_CLI_C_sudo_and_mixed_UID_private_record_readback_verified |
| `WMISetBatteryHealth` | `native_controls` | native_equivalent | source + full0..100 simulated range and typed errors; installed same-value100 only |
| `WMISetBatteryHealthToUser` | `native_controls` | native_equivalent | source + full0..100 simulated range; retained private caller persistence and installed same-value100 |
| `WMISetQuietFan` | `native_controls` | native_equivalent | live_same_value_write_and_private_user_record_readback |
| `WOA_EC_read` | `native_oem` | native_equivalent | live_value_returned |
| `WOA_EC_write` | `native_oem` | native_equivalent | live_plan_verified; writes_simulated_only |
| `wmiadd` | `lifecycle/configuration` | native_equivalent | live_value_returned |

The remaining providers were refreshed during 0.12 work: the EEPROM diagnostic
query returned ENODEV, `p_sensor` was 0, and ACFET/connector/choke APIs found no
validated physical labels. UCSI still returned a truncated count-prefixed PDO
list with unverified target identity. The new complete source capability
reader uses separately recovered per-port EC caches, not that truncated reply. The Linux PD objects contain revision
metadata but no source/sink-capability directories or cable-identity attributes
on this connection. No values are inferred for these absent providers.

## 0.13 provider boundaries

ACPI SEN1–SEN5 name the CPU, SSD, ambient, DDR and charger NTCs. Their TSR4,
TSR2, TSR9, TSR6 and TSR5 fields match the recovered one-based HealthyTable
selector dispatch. This fixes a selector error and the missing DDR reading.
It does not establish exact ACFET/choke/connector/upper-CPU placements.

Fresh DE queries expose target-qualified battery DAStatus prefixes and lifetime
extrema. The identity is an OEM gauge, not a proven TI part number; decoding
uses an exact firmware/layout guard, two-cell topology and range/sign checks.
History queries read each qualified prefix twice. Byte 31 is shared firmware
scratch and is excluded. Original block APIs return explicit partial-prefix
objects instead of pretending that all 32 cached bytes are valid battery data.

Received PD identities have a native fixed reader, but both qualified controller
ports returned zero response status. A completed ACK is required for VID/PID/XID.
The EEPROM support DSTS0x60059 and sensor-mask DSTS0x60068 branches return
zero directly. Correction in0.44: DEVS0x60059 is separate, has a conditional
SMM fallback, and the live version query returns unsupported0xfffffffe. GPU specialty sensors are not established on this integrated-GPU
machine; no XG Mobile or WWAN device is connected. These remain explicit hardware
or firmware boundaries rather than substituted readings.

## 0.14 additional qualification

The block-2 read-only prefix supplies shutdown/partial/full/watchdog reset counts.
Blocks 4/5 now decode 16 recorded event types and 14 complete last-cycle fields.
The last charge termination and resistance update both report cycle 292, matching
BAT0; inducing safety faults is not part of qualification. Two truncated cycle
fields remain unavailable. The runtime prefix did not change over 203 seconds
and is not assigned the public reference's seconds unit.

A fixed read-only probe of received PD alert/source-extended/status registers on
both endpoints returned lengths 4/0/4. The older public reference specifies 4/24/7.
Only the alert layout matches; source identity/status/temperature decoding through
those older extended layouts remains unqualified. No arbitrary register scan,
4CC, discovery, reset or power command was issued. The ordinary driver and automatic
fan were restored after both fixed probes.

## 0.15 provider checks

Full received ADO is now a native provider rather than the unsupported legacy
cache byte. Opaque e-marker Other is routed to received VDO index4, gated by ACK
and count. No cable ACK is currently available for physical validation.

Recovered original BoardTS0R/GpuTS1R CC reads and external-thermal CE/E4 capability
gates all timed out, then independently recovered to automatic fan mode. These
queries do not supply extra specialty temperatures on the qualified BIOS. The
five working BIOS NTCs retain their actual names and are not relabelled.

A fixed alternate battery manufacturer-data read returned one valid identity,
then longer and later reads failed. All mailbox bytes and the installed driver
were restored. That path is not qualified and is not part of the public driver.
Existing partial battery prefixes remain authoritative; the goal is still active.


0.53 grouped wireless source reconciliation corrects seven native contracts:
AP capability ceiling instead of observed rate, current kernel association
capabilities instead of rate encoding, two human card-name inventories instead
of module names, and three full nine-bin RSSI distributions instead of one
threshold. Default histogram shape changes intentionally; explicit threshold
arguments retain scalar behavior. Original table anomalies/endpoint omissions
are corrected, not copied. Higher EHT ceiling, exact legacy a/b/g and unknown
physical antenna mapping remain explicit limits; no duplicate antenna or
quality-to-dBm fallback is introduced. These are native APIs, not Wine ABI.


0.54.1 corrects SaveEcLog's previous generic-snapshot-only replacement. Native
JSONL now retains all six original table groups/69 entries and23 nested field
descriptors, the distinct32-byte project firmware revision and the source
raw-data/EEPROM path. Unsupported/error payloads remain explicit. Source
Win32 paths, JSON spelling and binary ABI are outside the owner-selected native
scope; data coverage and hardware effects are retained. Original zero-based
board iteration is corrected for this target's one-based selectors, with exact
restoration. The previously absent EC duty code is separately available through
native CLI/metrics/Vitals without conflating requested PWM with observed RPM.
