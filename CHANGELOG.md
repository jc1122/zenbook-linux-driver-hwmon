# Changelog

## 0.85.0

- Pre-publication tidy-up, no functional changes: static-analysis baseline and suppression policy moved into docs/STATIC_ANALYSIS.md (CI comments no longer point at private notes); test fixture user renamed; SPDX headers on sources and scripts plus a REUSE.toml covering JSON, data and Vitals snippet files.

## 0.84.0

- Fix a 0.83 regression: an unprivileged ec_diagnostics read during a transient EC error could latch the board-selector fault without touching the selector; the latch now requires a board walk whose restore failed. Clang analyzer findings resolved; threat model states the bridge allowlist limit for same-user processes.

## 0.83.0

- Kernel: probe-time cached ACPI _UPC map; 1 s caches for MSR frequency/voltage and EC diagnostics; module pinned while the fan is manual and bind attributes suppressed; OEM ops 11/13 require the apply flag; verified board-selector restore with a fault latch (also honoured by diagnostics); stray EC output byte drained only on the snapshot path, never on ECMT/mailbox busy; world-readable fault_state; rate-limited audit lines for privileged writes. Roll back kernel and userspace together (op 13 apply flag).
- GNOME bridge answers only the installed CLI/bridge of the session user, owns its name exclusively, and exposes window titles only on opt-in; clients verify the owner is gnome-shell.
- SSD/wireless exporter units sandboxed (systemd-analyze 1.2 each); Wi-Fi AP keys HMAC-salted per boot; sudo fallback runs python3 -I -B; C library linked with full RELRO/BIND_NOW and stack protector; ApplyMutation timeout reports outcome unknown and audits the late result.
- Property-based fuzz tests of firmware/sysfs/subprocess/D-Bus parsers; eight fuzz-found robustness bugs fixed. SECURITY.md and docs/THREAT_MODEL.md; blocking ruff security set, parser-fuzz CI job and advisory clang analyzer.

## 0.82.0

- Service portability: GLib signal shim for older PyGObject (GLibUnix.signal_add, GLib.unix_signal_add, unix_signal_add_full); installer path test is fixture-based.

## 0.81.0

- Service seccomp: allow perf_event_open (member of @debug) while denying the other @debug syscalls by name, so GPU usage works with CAP_PERFMON.

## 0.80.0

- Service: CAP_PERFMON (only capability) and perf_event_open for GPU usage; slow-class reads serve cached/coalesced results instead of EAGAIN; tablet-mode switch readable through its stable by-path device link; sandbox denials logged as AUDIT sandbox_denied.

## 0.79.0

- Privileged system service `org.zenbook.Hardware1` (D-Bus activated, sandboxed, uid 0 with no capabilities) with polkit actions per operation class, a `zenbook-hw` group rule (reads, settings, fan leases), time-limited fan leases with automatic restoration, single-use plan tokens for OEM mutations, result caching, rate classes and audit logging.
- CLI and C library route non-root privileged calls to the service; the Secret Service sudo-password route is removed (plain `sudo` remains for recovery).
- RAPL/PSYS energy and EC-broker-triggering attributes are root-only; Vitals reads them via `VitalsMetrics()`.
- Kernel bounds ECMT hold time per EC-broker session (stall detection, per-collector budgets from measured durations, bounded restore, fail-closed latch).

## 0.78.0

- Security hardening batch 1 (from the kernel threat model, userspace privilege review and static analysis):
  - Kernel: removal/shutdown sets a `removing` flag that blocks every write path and watchdog re-arming, disables the watchdog work synchronously, and retries the automatic-fan restoration with readback; ECMT/handle failures of EC-broker reads are cached; battery_gauge_status takes ECMT.
  - Raw `WOA_EC_write` is refused unless a root-owned policy file enables it.
  - `record`/`SaveEcLog` output is created through a no-follow directory walk, exclusively, and owned by the invoking user.
  - The C library runs the bridge isolated (`python3 -I -B`) with a fixed environment, closed inherited fds and a 60 s timeout.
  - Root-executed tools use absolute paths; validation asserts became explicit checks.
  - CI adds blocking sparse, `-fanalyzer`, filtered checkpatch, cppcheck and bandit gates; actions pinned to commit SHAs.

## 0.77.0

- Add root-only `pd_extended`: read-only received-PD registers 0x41 (PD3 status), 0x42 (PD3 configuration), 0x76 (RX Source_Capabilities_Extended) and 0x78 (RX Status) per active port, with the register's own length byte (0 = not implemented). Same pointer-and-read operation, contract bracketing, mailbox restoration and fault latch as pd_identity; no 4CC command or controller write.

## 0.76.0

- RF_WiFi_Main_Aux_Rssi no longer requires root (unprivileged station dump); metrics adds wireless_chain_signal.
- WMIGetHDDTemp requires root only when a selected disk lacks a world-readable hwmon temperature and needs the SMART fallback.
- Classify Adapter_Read_PD_ADO (original byte absent from this firmware) as firmware_provider_required.

## 0.75.0

- Decode recorded cell-balancing 255 as saturated (at least 510 h, TI 2 h x U8 limit) in native history and Vitals.
- Decode DAStatus2 bytes 16..23 as uncompensated cell voltages, gated on tracking the compensated cells and zero inactive cells; keep the raw tail and its old key.
- Publish TI default temperature-region boundaries as reference metadata with read_from_pack false.

## 0.74.0

- Retry one fresh complete charger ADC/metrics transaction after a transient worker failure (-EIO) and one fresh bracketed PD-identity sample after a contract change (-EAGAIN); restoration, protocol, identity and busy errors are not retried.
- Add cpu_power_limits (MSR and MMIO package RAPL zones, lowest enabled limit) and ec_cpu (EC CPU temperature, CPU-reported voltage) to metrics. Original PowerLimit1/2 keep the MSR zone.
- Classify GetEEPROM_Data as firmware_provider_required and Adapter_Read_PD_Get_Emark_Other as hardware_provider_required; fill CPU_ReadCpuVoltage validation. Correct the power2_input (USB-C ADC) versus power3_input (RAPL) labelling in 0.73 notes.

## 0.73.0

- Driver re-samples PSYS and RAPL package energy once after 120 ms when a read only re-primes an idle, stale or stopped counter, so hwmon consumers (Vitals, sensors) see a measurement on first read; protocol/MSR errors and a second failure stay unavailable.
- Classify the 22 exports the qualified firmware does not provide as firmware_provider_required instead of native_equivalent.

## 0.72.0

- Retry the PSYS platform-power read once after 120 ms when the first read after an idle gap only re-primes the counter (ESTALE/ENODATA/EAGAIN); hard errors stay unavailable. Include platform_power in `zenbook-hardware metrics`.

## 0.71.0

- Collect every advertised GPU provider (DRM busy, i915 PMU) with per-row provider labels, independent provider_errors, identity/census rechecks, provider_coverage_complete and all_readings_available. A failed provider no longer hides another; providers are never summed.
- Return internal and external monitor names from WMIGetLCDModel as in the original query; optional boolean internal_only keeps the panel-only view. Scoped source reviews now bind all252 exports (review coverage, not parity or hardware proof).

## 0.64.0

- Correct RF_USBIsTranster to the recovered non-system disk-time predicate, with unprivileged measured counters, root-topology exclusion and explicit partial state. Retain actual USB measurements through a selected metric and dedicated CLI command.
- Track USB observer loss/backlog/event caps and real intervals; incomplete captures expose lower-bound data without false inactivity or exact-byte claims. Add optional per-card SD capacities beside the existing scalar total.

## 0.63.0

- Add original2.4GHz channel1/6/11/other groups beside the full channel map. Reconcile twelve wireless observation source contracts and retain separate receive/send rates and unlabelled antenna chains.
- Bracket cached AP counts by daemon, netdev, scan and BSS identities under an overall deadline. Read fixed properties only; preserve true zero versus unavailable and avoid scan/connection changes.

## 0.62.0

- Restore the full fan request byte range and CLI0–100%, preserving ownership, raw-write exclusion, low-RPM/fault checks and automatic restoration. Report stored request versus applied mode explicitly.
- Accept meaningful battery limits0–100% through the existing ASUS provider and caller preference schema. Clarify cached acknowledged setting versus physically measured charge cutoff.

## 0.61.0

- Expose CPU-package RAPL power through read-only hwmon and unprivileged API/CLI/metrics, with explicit energy/time evidence, bounded freshness/wrap checks and baseline reset across suspend.
- Add a separate CPU Package Power Vitals row and reviewed migration. Reconcile fresh battery lifetime/extrema reads with the original guarded legacy-cache routines.

## 0.60.0

- Preserve all seven raw source PDOs when the active contract has an unconverted nonfixed type. Keep fixed-limit checks, source-membership/AC/freshness gates and explicit raw Vitals rendering.
- Qualify both ports, every count1..7, seven named selectors and all read-failure boundaries; retain physical nonfixed-contract limits.

## 0.59.0

- Correct CPU frequency APIs to source-reported P-state/turbo ratios with read-only CPU0 MSR/CPUID sampling; retain CPUFreq separately and add two labelled Vitals Processor rows.
- Correct XG firmware payload to31 bytes and validate the complete collection descriptor on the opened HID handle before its fixed firmware query. Physical XG qualification remains pending.

## 0.58.0

- Replace the frontend constant in GetInfVersion with installed metadata for the actual bound ASUS system-control driver. Keep declared module versions, in-tree kernel versions and loaded HealthyTable/frontend versions distinct.
- Register application paths in the actual caller's private configuration, including sudo/custom-directory callers. Drop effective root before user-file access, preserve unrelated settings and use bounded revision-checked atomic updates.

## 0.57.1

- Remove the unsupported bank6 byte-zero capability assumption from native logical EC writes. Keep the qualified bank ceiling, packet allowlist, protected fan/cache selectors and explicit reviewed apply.
- Bind raw-write plans to recipe revision3 and show the exact native wire packet. Validate raw read/write and OEM scalar-read parameters before elevation.
- Report completed write transport separately from firmware acceptance/readback; the protocol supplies no firmware acknowledgment for these writes.
- Complete the four-wrapper source comparison, including the original kernel driver's CPU-voltage bitfield/scaling and native cached contract-PDO semantics. Keep Windows ATD addresses distinct from native logical registers.

## 0.56.0

- Correct power-drop monitor command encoding and version24+ power-flag read/clear masks. Preserve protocol14..23 legacy clearing, source version gates, typed failures and current firmware bank guards.
- Remove an unsupported bank6 byte-zero capability assumption from fixed adapter controls. Reviewed OEM plans now bind recipe revision2 and expose the affected command encodings; older digests cannot authorize changed recipes.
- Complete source and independent native/CLI/C qualification of all ten existing EFI read/plan functions without factory writes.

## 0.55.0

- Port the omitted successful user-choice records for battery-health ToUser and quiet/profile setters. Preserve the immediate-only battery setter and existing Power Profiles authority; add a read-only preferences command.
- Drop to the actual caller before user-file access, retain custom configuration context across sudo, and use private bounded records with revision checks. Report partial hardware effects and avoid undoing later external selections.
- Reject unexpected control/lifecycle arguments before privilege elevation.

## 0.54.1

- Restore the original EC diagnostic log data: six groups/69 version-gated entries, indexed descriptors, separate32-byte project firmware revision and bounded EEPROM/raw-data results. Preserve private files, typed errors, raw units and exact selector restoration.
- Add independent EC fan-duty and mode reporting in CLI/metrics/Vitals; keep last requested PWM separate from the EC duty code.

## 0.53.0

- Correct AP capability rate, kernel association PHY, descriptive Wi-Fi card inventories and the three original nine-bin RSSI distributions. Retain observed rates and explicit threshold counts separately.
- Add bounded read-only Wi-Fi metadata collection with an unprivileged cache/CLI and Vitals Network rows; preserve independent errors, source units, identity and freshness.

## 0.52.0

- Replace the generic interface-up list with connected physical Ethernet/cellular/Wi-Fi classification and original priority. Exclude virtual/tunnel links and preserve unknown types, stable identities, bounded existing-owner reads and partial coverage.
- Add original Bluetooth major-class metadata from optional BlueZ Class-of-Device. Preserve missing/invalid class separately from known connected counts and reject changed daemon ownership.

## 0.51.0

- Review and replace all60 remaining whole-snapshot field routes with independent providers. Correct battery quantities, flags, signed current, date/percentage formatting, EC family/packed name/14-byte buffer and indexed ProArt RPM.
- Implement guarded fixed32-byte battery information and four-byte PF cache collectors; preserve firmware error/ownership/readiness and reject partial/changing payloads.
- Fan getters remain usable during bounded manual ownership; CLI show preserves independent readings beside an explicit EC error. Keep profile, threshold and RAPL getters independent of EC telemetry.

## 0.22.0

- Keep Bluetooth service/permission/timeout and malformed connection-status
  failures distinct from zero connected devices. Bind the existing unique BlueZ
  owner without daemon activation; retain valid counts beside missing optional
  metadata. No pairing, discovery, connection or device setting is used.
- Validate each backlight's actual/max brightness and recheck its identity/range.
  Missing or invalid values are unavailable; preserve other panels and real0%.
- Read the two AC-status APIs directly from validated0/1 data. Failed reads no
  longer become offline; CLI show retains an explicit unknown/error state.
- Preserve unknown battery error bytes and legacy PF-gate inputs rather than
  asserting a fault or clearing a gate from missing data.
- Keep unreadable fan modes and battery-full state unknown instead of asserting
  manual fan control or a non-full battery.

## 0.21.0

- Replace the USB display product-name heuristic with connected DRM USB ancestry
  and configured partner DisplayPort alt-mode evidence. Interpret the kernel's
  partner sink configuration as a local DP source; local capability alone is
  insufficient. Read status/identity/configuration again to reject changing data.
- Preserve known positive evidence alongside per-object errors. Unmapped external
  or virtual displays and missing providers are unknown rather than false.
  No EDID/serial read, modeset, role swap or alt-mode setting is requested.
- Check target UCSI capabilities and one fixed optional cable-property GET:
  cable-details/PD-message access is not advertised, and the cable GET returned
  only zeros with the contract preserved. Keep cable data unavailable and the
  platform's PD capability revision separate from the charger's revision.

## 0.20.0

- Recover battery-reported ManufacturerName and DeviceName through fixed SBS
  block READ commands0x20/0x21. Replace empty legacy-cache strings in sysfs,
  native identity APIs, CLI and metrics without substituting ACPI laptop names.
- Determine complete1..32-byte lengths with two different receive sentinels and
  identical replies. Restore/verify all48 mailbox bytes and share the controller
  fault latch. Add455 communication-failure boundaries and five decoder/API tests.
- Preserve exact raw strings and the original fourth-manufacturer-byte gauge
  convention. Reject blank/nonprintable display text, retain explicit unavailable
  fields and keep physical vendor identification unverified.

## 0.19.0

- Measure Wi-Fi byte rates over the actual monotonic interval, preserving the
  native interface-to-rate map. Missing, reset, replaced or hotplugged counters
  are null rather than fabricated zero or negative rates.
- Reject suspend gaps and delayed snapshots; retain healthy interfaces when
  another fails. Add optional per-interface RX/TX/error diagnostics. Read Linux
  counters directly without depending on NetworkManager or requesting scans.

## 0.18.0

- Add complete live DAStatus frames through the fixed battery block worker:
  gauge-computed cell/pack/average powers and the gauge algorithm temperature.
  Preserve the fast existing sensor path and use a separate15-second cache.
- Prove complete changing replies with a receive sentinel and bounded collision
  retry; preserve each frame and all48 mailbox bytes. Add315 normal and386 retry
  communication-failure boundaries.
- Validate cell power units against same-frame V/I without substituting a
  calculated replacement; expose unidentified DA2 tail bytes as raw data.
- Replace the shared unfiltered WWAN dump with three typed read-only providers:
  access-technology flags, primary-SIM home provider and cached modem signal.
  Keep roaming network, quality percent, RSSI and NR RSRP distinct. No modem
  setting, SIM unlock, scan or connection operation is used.
- Add five Battery rows to Vitals while preserving owner code and favorites.

## 0.17.0

- Recover complete battery lifetime blocks through the fixed firmware SMBus
  block worker, avoiding the DE buffer's overlapping scratch byte. Restore and
  verify all48 touched mailbox bytes; latch failures across controller readers.
- Require the exact OEM identity/firmware,32/8/26/32/32 lengths, two equal replies
  with different RX sentinels, and agreement with the existing validated prefixes.
- Publish complete raw blocks, recorded FET maximum and both formerly truncated
  last-cycle fields through the native API. Add the FET maximum to Vitals.
- Keep unmatched OEM block2/3 bytes and runtime units uninterpreted: the measured
  lengths differ from the TI reference. Preserve older-kernel partial results.

## 0.16.0

- Keep each disk's temperature result independent: an unsupported or failed SMART
  device no longer discards working hwmon/SMART readings from other disks.
- Return explicit per-device availability and errors; validate finite plausible
  temperatures and match hwmon device ancestry exactly.
- Ask SMART to stop on standby or unsupported ATA power-mode checks. Do not guess
  USB bridge protocols or retry with power checks disabled.
- Audit all 230 non-mutating exports and 14 reviewed plans without executing
  factory, charger, flag-clearing or driver-stop operations.

## 0.15.0

- Add the controller's last received 32-bit PD Alert Data Object through the
  existing guarded, contract-bracketed monitor. Expose it in the native API and
  Vitals; zero means no alert recorded, separate from current protection status.
- Port the opaque e-marker Other API to the fifth received identity VDO. Require
  an ACK and enough VDOs; omitted data stays ENODATA.
- Verify original specialty thermal reads/capability gates: all four fixed
  CC/CE/E4 queries time out on this BIOS and recover to automatic fan mode.
- Preserve explicit gaps: alternate full battery block reads failed qualification;
  the existing battery provider remains authoritative.

## 0.14.0

- Add fresh lifetime shutdown/reset counters through the fixed read-only block-2
  prefix. Decode the 16 safety, charging and gauging event counters and complete
  last-event cycle fields; suppress two truncated cycle fields.
- Add recorded-event rows to Vitals and preserve owner code during the reviewed
  0.13 helper upgrade. Older kernels show unavailable reset counts.
- Keep the runtime counter raw: a short observation did not establish its units
  or update cadence. Reject older-controller extended-status
  interpretations whose payload lengths disagree with the actual TPS65994BF.

## 0.13.0

- Correct one-based thermistor selection, restoring the original selector even
  after failures. Add BIOS-derived SSD/ambient/CPU/charger/DDR NTC labels.
- Add live battery-gauge internal/TS/cell/FET temperatures, BAT/PACK pin voltage
  and signed per-cell sample current through fixed read-only manufacturer queries.
- Replace cached peak/history API values with fresh, coherent lifetime prefixes;
  decode qualified cell/current/power/temperature extrema. Exclude overlapping
  firmware scratch and keep unqualified runtime units/block layouts explicit.
- Add fixed received-PD identity reads and typed e-marker VID/PID/XID APIs.
  Empty identity responses return ENODATA; no discovery or power command is sent.
- Add Vitals battery diagnostics and recorded-history rows while preserving pins.

## 0.12.0

- Add charger-controller die temperature, VBAT/VSYS ADCs, battery charge/discharge
  ADCs, operating state and live protection flags. Read-to-clear status is excluded.
- Add per-CPU throttle counts/durations without summing duplicated package copies.
- Add sanitized NVMe SMART health through a root-owned, once-per-minute cache.
- Integrate Battery/Processor/Storage metrics into Vitals with stale-data suppression.
- Recover complete per-port source PDOs from the EC RX_SOURCE_CAPS cache, including
  the fourth PDO truncated by UCSI. Route indexed and numbered PDO APIs to it.
- Recheck unsupported cable/EEPROM and physical temperature mappings; keep explicit
  unavailable results instead of assigning unverified readings.

## 0.11.1

- Retry changing V/I/V ADC sequences at most twice, retaining the original
  consistency threshold and refusing stale or unmeasured substitutes.
- Preserve sysfs EAGAIN in Python using an unbuffered read. Python 3.14 buffered
  text reads had obscured this as an uninformative device-unavailable error.

## 0.11.0

- Read the ISL9241 charger through the EC's OEM combined-transaction worker,
  which drains pending firmware SMBus work. Fixed read-only registers only;
  save/restore and verify the volatile mailbox, with a fault latch on failure.
- Expose actual sampled input voltage/current ADCs and their V*I power through
  hwmon, JSON CLI and Vitals. Qualify the board's 10 milliohm current scale;
  keep input measurements, negotiated limits and Intel PSYS separate.
- Test request failures at all 146 communication boundaries, restoration faults,
  identity/ADC/calibration/freshness checks and single-connector attribution.
- Upgrade the existing Vitals adapter while preserving unrelated customizations.

## 0.10.0

- Read-only PSYS platform power in hwmon power1_input, measured from hardware
  energy deltas; verified against Linux's independent sysfs conversion.
- Public cached PD monitoring attribute, kept separate from privileged RPC.
  Original contract-PDO reads now work without elevation.
- Optional Vitals Battery integration displays platform power and clearly
  labelled USB-C contract limits, with explicit unavailable ADC input rows.
  Existing Vitals customizations are preserved; GNOME 50 activation needs the
  next logout/login. No current/power estimates or charger writes were added.

## 0.9.0

- Recover the EC's active USB-C fixed-supply contract through the firmware's
  serialized ACPI read mailbox, bypassing the unavailable ASUS adapter bank.
- Expose nominal voltage, current limit, power limit, EC wattage and the real
  active PDO. Port A and B both report the stock adapter's 20 V / 3.25 A / 65 W.
- Require two equal snapshots, AC/validity gates and consistent PDO/limit
  fields. A physical unplug and port-swap test verified stale-value suppression
  and both connector mappings; a changing sample returned EAGAIN as intended.
- Route Adapter_Read_Contract_PDO to this native provider. Other unsupported
  adapter-bank operations and instantaneous current/power measurements remain
  unavailable; no charger reset, role change or write command is added.

## 0.8.1

- CPU-reported P-state voltage from read-only Intel MSR_PERF_STATUS, exposed as
  hwmon in6_input and through the existing CPU voltage API without privilege.
- Aggregate existing per-core/package, SSD, Wi-Fi and ACPI temperatures into
  the main report, preserving source labels.
- Fixed GET-only UCSI charger diagnostics with explicit ASUS target ambiguity, count-prefix and
  truncation handling; never infer missing PDO flags or live current/power.
- Metadata-only BIOS flash/CMOS storage inventory, kept separate from the
  unavailable ASUS EEPROM diagnostic table.

## 0.7.1

- Validate HID device identity again after opening the handle; accurately report ACPI walk truncation.
- Standalone repository, reproducible build/test entrypoints, DKMS installer,
  optional configured keyring authentication and native Linux C ABI.
- Actual GC31/GC33 XG Mobile firmware feature-report query, replacing USB
  product-name detection.
- Corrected GetNum_Key to report Num Lock/keyboard inventory and corrected
  GetSENSOR_WMI_Data to query DSTS 0x60068.
- ACPI `_UPC` USB connector reporting, per-device host classification and
  metadata-only USB traffic counters across device classes.
- Grouped cached Wi-Fi AP channel/U-NII counts.
- Explicit implementation/evidence/verification entries for the 252 original
  names, separate from hardware availability and outside-scope Windows ABI.

## 0.6 and earlier

Local native fan, thermal, battery/history, OEM RPC, UEFI factory records and
Linux service providers. These revisions were developed in a maintenance tree
before this standalone repository was created. Earlier local reports counted
API-name routes too broadly; 0.7 corrects identified behavior mismatches and
records functional parity separately.
