# Qualification: 0.85.0, 2026-11-01

Pre-publication tidy-up; no functional change. Private audit references replaced by
docs/STATIC_ANALYSIS.md, test fixture user renamed, SPDX headers and REUSE.toml added.

- 870 Python tests, all C tests, W=1 and CI gates pass; `reuse lint` compliant.
- Installed signed 0.85: runtime/DKMS exact, MOK CMS verifies; fan automatic, cap100,
  profile, keyboard, four UEFI hashes, selector and PPD/thermald unchanged; reload
  kept the fan automatic.
- Exporter units succeed; full 230 reads identical to 0.84 after a wireless cache
  refresh; via-service parity holds; GPU/display 27+27; Vitals GJS passes on two
  consecutive runs (193 rows) after one transient first-run charger-row miss.

# Qualification: 0.84.0, 2026-11-01

Fixes the0.83 false board-selector latch found by the convergence re-audit;
analyzer findings resolved.

- 870 Python tests, all C tests (forced rebuild) including early-return/no-latch
  and walk-restore-failure/latch cases, W=1 and CI gates pass.
- Installed signed0.84: runtime/DKMS exact, MOK CMS verifies; fan automatic, cap100,
  profile, keyboard, four UEFI hashes, selector and PPD/thermald unchanged; reload
  kept the fan automatic; repeated ec_diagnostics reads leave fault_state clear.
- Exporter units succeed; full230 reads identical to0.83; via-service parity
  holds; GPU/display 27+27; Vitals GJS passes on two consecutive runs after one
  transient Wi-Fi cache-generation miss right after a fresh exporter run.

# Qualification: 0.83.0, 2026-11-01

Hardening batch 3 from the convergence audit; independent kernel review applied
(the stray-byte drain no longer runs on ECMT/mailbox busy).

- 870 Python tests including 42 property-based parser fuzz tests (eight
  fuzz-found robustness bugs fixed), all C tests with forced rebuild, W=1,
  checkpatch, bandit and blocking ruff gates pass.
- Installed signed0.83: runtime/DKMS exact, MOK CMS verifies; fan automatic, cap100,
  profile, keyboard, four UEFI hashes, selector and PPD/thermald unchanged; a
  controlled unload/reload kept the fan automatic with a clean kernel log.
- During a 4 s fan lease the module refcount was 1 (pinned while manual) and
  returned to 0 with automatic restoration; fault_state shows all latches clear.
- Sandboxed ssd/wireless exporter units run successfully and refresh their caches;
  NVMe SMART works with only CAP_SYS_ADMIN.
- Full230 reads identical to0.82; via-service parity holds (WOA_EC_read admin by
  design); GPU/display 27+27; two Vitals GJS runs with 193 rows. GNOME bridge
  upgraded with backup; it, the Vitals helpers and the zenbook-hw session group
  take effect at the next ordinary login. Kernel and userspace must be rolled
  back together (op 13 apply flag).

# Qualification: 0.82.0, 2026-11-01

0.82 changes only the service's signal-registration shim and a test fixture; the
0.81 live qualification below is re-checked after install (service activation,
GPU via service, via-service parity, fan lease and Vitals smoke).

## Qualification: 0.81.0, 2026-11-01

0.80 and0.81 fix the service regressions found live in0.79.

- 815+ Python tests, C fault-injection tests, W=1, checkpatch and bandit gates pass.
- Installed signed0.81: runtime/DKMS exact, MOK CMS verifies; fan automatic, cap100,
  profile, keyboard, four UEFI hashes, selector and PPD/thermald unchanged.
- The service process holds only CAP_PERFMON; perf_event_open is allowed while the
  other @debug syscalls stay denied. Through the service, GPU usage returns all
  five i915 engines (coverage complete), tablet mode reads through the switch's
  stable by-path link, and PF/safety status reads coalesce instead of EAGAIN.
- Every root-scope read through the service matches direct root except
  WOA_EC_read (admin authorization by design).
- Full230 reads: statuses identical to0.78 (193/37); 17 reads in root/service
  scope. GPU/display 27 user and 27 root census reports pass.
- Standalone GJS with the service-backed Vitals helpers: 193 rows on two
  consecutive runs; one earlier run missed the charger die temperature once on
  its first refresh (transient, not reproduced).

# Qualification: 0.79.0, 2026-11-01

Hardening batch 2: privileged service, client migration, attribute restriction
and ECMT hold bound. Independent reviews of the ECMT bound and the service
were applied before install.

- 810 Python tests, C fault-injection tests (stall at every step, healthy-but-slow
  at measured durations), W=1, checkpatch and bandit gates pass.
- Measured healthy uncached durations set the ECMT budgets (lifetime 8.3 s,
  SBS 5.7 s, identity 3.6 s, gauge_extra 3.0 s, PD 2.3 s, charger 1.5 s; budgets
  at least 4x). A dead EC now adds about 7.5 s of hold instead of up to 250 s.
- Installed signed0.79: runtime/DKMS exact, MOK CMS verifies; fan automatic,
  cap100, profile, keyboard, four UEFI hashes, selector and PPD/thermald
  unchanged. Service files and group installed; owner added to zenbook-hw.
- Live service: D-Bus activation under the sandbox, passwordless group reads,
  settings writes (same values) and a 5 s fan lease (manual to about 6250 rpm,
  automatic restored on release) all pass with AUDIT lines.
- dbus-daemon checks the calling process's groups: processes started before the
  group change need `sg zenbook-hw` or a new login; the running Vitals panel
  (old JavaScript reading files directly) loses restricted rows until login.
  The upgraded Vitals helpers pass the standalone GJS smoke test (193 rows).
- Full230 reads: statuses identical to0.78 (193/37); 17 reads moved to root or
  service scope. Through the service, root-scope reads match direct root except
  PF/safety status (slow-class EAGAIN), tablet mode (sandbox EPERM) and GPU
  usage (no CAP_PERFMON) - regressions for non-root callers fixed in0.80;
  WOA_EC_read requires admin by design.

## Retained 0.78.0 qualification


Security hardening batch 1 from the kernel threat model, userspace privilege
review and static analysis.

- 716 Python tests, all optimized/sanitized C tests (NDEBUG-guarded, memcpy
  copies), W=1 build with zero warnings, filtered checkpatch and bandit gates pass.
- Installed signed0.78: runtime/DKMS exact, MOK CMS verifies; fan automatic,
  cap100, profile, keyboard, four UEFI hashes, board selector and PPD/thermald
  unchanged.
- Controlled unload/reload of0.78 exercised the new remove path: fan stayed
  firmware-automatic before, during and after, with no kernel-log problems.
- Raw WOA_EC_write is refused by default (EPERM, policy message).
- Full230 reads identical to0.77 (193/37, 212 user/18 root); GPU/display 27+27
  census reports through native, CLI and the isolated C-library bridge; GJS 193
  rows; pd_extended unchanged. The first pack-power bracket check raced again
  and passed on rerun.

## Retained 0.77.0 qualification


Owner-requested read-only USB-C controller check. No command or controller
write is possible in the new path.

- 705 Python tests; PD-extended C tests (278 injected failures, length bound,
  absent registers, restoration, refused 0x08/0x09) and all retained checks pass.
- Installed signed0.77: runtime/DKMS exact, MOK CMS verifies; fan automatic,
  cap100, profile, keyboard, four UEFI hashes, board selector and PPD/thermald
  unchanged before and after the controller reads; no fault latch.
- Three identical root reads on the active connector: 0x41 len8, 0x42 len3,
  0x76 len0 (not implemented), 0x78 len4 `0f000000`. See PROTOCOL 0.77.
- Full230 reads identical to0.76 (193/37, 212 user/18 root); GPU/display 27+27;
  GJS 193 rows. The first pack-power bracket check raced again and passed on rerun.

## Retained 0.76.0 qualification


A final independent verification audit confirmed every earlier finding and the
0.75 decodes resolved on the installed system (216 read exports exercised,
252-row parity consistency, all hwmon attributes read first time) and found no
implementable port gap; it noted three polish items, all closed here.

- 705 Python tests including the privilege decision, parity and W=1 module build pass.
- Installed signed0.76: runtime/DKMS exact, MOK CMS verifies; fan automatic, cap100,
  profile, keyboard, four UEFI hashes, board selector and PPD/thermald unchanged.
- Unprivileged native/CLI/C RF_WiFi_Main_Aux_Rssi match an independent iw station
  dump (two chains), WMIGetHDDTemp matches NVMe hwmon; metrics carries
  wireless_chain_signal.
- Full230 reads on AC1: 193/37 with status/errno identical to0.75; the only scope
  changes are these two reads moving to user scope (212 user/18 root). GPU/display
  27+27 census reports and GJS 193 rows pass; Vitals helpers are the0.75 set.

## Retained 0.75.0 qualification


Public-source research (TI gauge manuals R1..R5/BQ4050/BQ40Z80, TI E2E, open
decoders, repair fora, Reddit, GitHub) yielded three decodes of bytes the port
already reads; no new register, controller or firmware request was added.

- 704 Python tests, Vitals battery helper tests, core/charger checks, parity and
  W=1 module build pass.
- Installed signed0.75: runtime/DKMS exact, MOK CMS verifies; fan automatic,
  cap100, profile, keyboard, four UEFI hashes, board selector and PPD/thermald
  unchanged.
- Live DAStatus2 tail 4179/4179/0/0 mV against compensated cells 4179/4180 mV
  selects the uncompensated-cell layout; native and metrics publish it. Both
  recorded balancing counters read 255 and are reported saturated (at least
  510 h). Temperature regions carry TI default boundaries with read_from_pack
  false.
- Reviewed Vitals battery-helper upgrade applied with backup and readback; only
  that helper changed. Standalone GJS shows both balancing rows as saturated
  (193 rows); the running Shell picks it up at the next ordinary login.
- Full230 reads on AC1 identical to0.74; GPU/display 27+27 census reports pass;
  the first pack-power bracket check raced again and passed on rerun.

## Retained 0.74.0 qualification


A second independent completion audit (consumer-side) found no unported sensor
provider; it found transient charger-worker EIO cached as Unavailable, one
PD-identity contract-change EAGAIN, PL1/PL2 reporting only the MSR zone while
thermald's lower MMIO limits are in force, two exports still classed
native_equivalent without data, and a power2/power3 labelling error in0.73.

- 703 Python tests, charger tests with bounded-retry cases (one transient worker
  failure retried once with fresh restoration; two failures stay EIO; restoration/
  busy never retried), core checks, parity and W=1 module build pass.
- Installed signed0.74: runtime/DKMS exact, MOK CMS verifies; fan automatic, cap100,
  profile, keyboard, four UEFI hashes, board selector, PPD/thermald unchanged.
- After 35 s idle each: hwmon power1_input (PSYS) and power3_input (RAPL) succeed
  on first read via the driver re-sample. Per-zone RAPL limits match powercap
  exactly (MSR 200/45 W, MMIO 35/25 W; lowest enabled 35 W); PowerLimit1 keeps the
  MSR value. Metrics carries cpu_power_limits, ec_cpu and platform_power. 40/40
  charger_adc and 10/10 pd_identity reads succeed (the transient is not
  inducible; retry paths are covered by fault-injection tests).
- Full230 reads on AC1 identical to0.73 (193/37, no scope change); GPU/display
  27+27 census reports; GJS 193 rows with Platform and RAPL power; helpers and
  preferences unchanged. The smoke harness's fixed charge-termination count was
  relaxed to monotonic after the real counter advanced 210 to 211; the first
  pack-power bracket check again raced the slower metrics run and passed on rerun.

## Retained 0.73.0 qualification


Version0.73 closes the remaining consumer-side idle gap: the driver re-samples
PSYS and RAPL package energy once after 120 ms when a read only re-primes an
idle, stale or stopped counter, so hwmon readers such as Vitals get a value on
first read. Twenty-two firmware-absent exports are reclassified
firmware_provider_required.

- 700 Python tests, core checks including the re-prime predicate, C/Node/GNOME
  parity, 252-route parity and W=1 module build pass.
- Installed signed0.73: runtime/DKMS source exact, MOK CMS signature verifies;
  fan automatic, cap100, profile, keyboard, four UEFI hashes, board selector and
  PPD/thermald authority unchanged; E5 firmware calls0.
- After 35 s idle each: raw hwmon power1_input (PSYS) succeeds on first read
  (driver re-sample path, read time over100 ms). Correction (0.74): the second
  raw read was power2_input, the USB-C input ADC, not RAPL; the RAPL first-read
  check is the native package-power report below (same driver path), and0.74
  re-tests power3_input directly; native platform_power needs
  no userspace retry; native package power and metrics CLI available.
- Full230 reads on AC1: 193 values/37 typed unavailable, status/errno and scope
  identical to0.72. GPU/display 27 user and 27 root census reports pass. GJS 193
  rows with Platform Power and RAPL package power available; Vitals helpers and
  preferences unchanged. Owner Shell activation remains pending.

## Retained 0.72.0 qualification


An independent read-only completion audit found no unported sensor or hardware
provider; it found PSYS platform power unavailable on the first read after an
idle gap, because the kernel helper re-primes rather than reports (ESTALE, then
EAGAIN inside100 ms). Version0.72 adds one measured retry after 120 ms, matching
package power, and publishes `platform_power` in metrics. Hard errors stay
unavailable; the kernel module is unchanged apart from its version.

- 700 Python tests, C core/diagnostic/OEM optimized and sanitized checks,
  Node/GNOME parity, 252-route parity and W=1 module build pass.
- Installed signed0.72: root-owned runtime/DKMS source exact, MOK CMS signature
  verifies; fan automatic, cap100, profile, keyboard, four UEFI hashes, board
  selector and PPD/thermald authority unchanged; E5 firmware calls0.
- After 35 s idle each, native `platform_power` (re-prime path taken, one retry),
  metrics CLI and charger CLI return measured platform watts.
- Full230 reads on AC1: 193 values/37 typed unavailable, identical status/errno
  and privilege scope to0.71. Native/CLI/C GPU/display 27 user and 27 root
  reports still match the independent census. Standalone GJS returns 193 rows with
  Platform Power available; Vitals helpers/preferences unchanged. The Vitals
  helper itself reads PSYS directly, so its first refresh after over30 s still
  shows Unavailable until the next refresh. Owner Shell activation remains pending.

## Retained 0.71.0 qualification


Version0.71 closes two gaps found by the final25-wrapper source review. No
original PE was executed. WMIGetGPUUsg previously returned DRM rows whenever any
existed, so a failed DRM read hid working i915 PMU data. Both advertised providers
are now collected with per-row provider labels, independent provider_errors,
per-provider EPROTO decode rows, identity/census rechecks before publication,
provider_coverage_complete and separate all_readings_available. Providers are not
summed, substituted or cross-calibrated; this is not every-GPU or Windows
per-process3D accounting. WMIGetLCDModel's original friendly-name query has no
internal filter; default now includes external rows and strict boolean
internal_only keeps the panel view. It is no longer an empty-argument read.

- 699 Python tests pass, including provider coexistence, DRM/PMU failure isolation,
  non-ASCII decode, discovery, identity replacement with original-error retention,
  census change, single-engine unavailability versus provider coverage, external
  and unknown-row defaults and strict selector checks. C core/diagnostic/OEM
  optimized and sanitized checks, Node/GNOME parity, 252-route parity and W=1
  module build pass.
- Installed signed0.71: root-owned runtime and DKMS source match the commit, MOK
  CMS signature verifies, fan automatic, cap100, profile, keyboard, four UEFI
  hashes, board selector and PPD/thermald authority unchanged, E5 firmware calls0.
- Native/CLI/C GPU and display: 27 user and 27 root reports match an independent
  sysfs connector and i915 PMU census, unchanged before and after. Internal-only,
  default and explicit-false LCD scopes and the external list agree on all three
  channels; invalid selectors are rejected. The unprivileged native/C GPU call
  stays EACCES; the authorized CLI route and root return five i915 engine rows with
  provider coverage complete. One live rcs0 sample with busy above running time
  stayed ENODATA, not clamped, while provider coverage stayed complete. This
  hardware has no DRM busy counter and no connected external monitor: DRM+PMU
  coexistence and external-name positives are fixture-only.
- Full230 reads on AC1: 193 values/37 typed unavailable (210 user/20 root,
  22 writes excluded). Versus the retained AC1 0.68 audit only the source-corrected
  0.70 alert-byte default differs. Wi-Fi rows briefly returned EAGAIN/needed root
  across a real NetworkManager scan generation change and returned with a fresh
  read-only cache. Standalone actual GJS returns 193 rows with positive charging
  gauge power; Vitals helpers and preferences are unchanged. Owner Shell
  activation remains pending an ordinary login.
- The other23 reviewed wrappers changed no behaviour. All252 exports now have
  explicit scoped source-review bindings, with no remaining review-metadata
  obligations. This is review coverage, not functional parity, completion or
  hardware qualification. Existing retained evidence flags, physical USB/display/
  provider-variant limits and owner/hardware/meter/boot/enabled-SB/suspend/fold
  checks remain. Qualified0.70.0 rollback is retained.

## Retained 0.70.0 qualification

Version0.70 corrects USB immediate-attachment quantities and the original alert
cache-byte API. Five USB wrappers/shared859-instruction helper and ten bank6
adapter wrapper fields were reconciled against native providers. No original PE
was executed. A Type-C laptop port is no longer substituted for an unknown/A
downstream dock socket. Logical user-visible connection counts, separate merged
socket counts, explicit host scope, cached bcdUSB distributions and native
class08 storage subset retain the original information with declared Linux units.

The original alert getter is one opaque DD6/26 byte, not a proved selection from
the full native ADO32. Its default now reports qualified bank absence without a
bank6 request; native_alert=true preserves the separate received32-bit reading.
Existing native alert reports and Vitals are unchanged. Nine adjacent adapter
diagnostics keep their source-confirmed selectors/widths and typed bank absence.

- make check passes681 Python tests, including27 USB cases and the new alert
  quantity/strict-selector tests. Optimized/sanitized core8188/diagnostic653/
  OEM16806 and210 status-failure boundaries, retained transport, six Node helpers,
  GNOME adapters and252-route parity pass. W=1 module passes.
- Fifty-one installed native/CLI/C reports agree with independent cached USB
  descriptor/port/interface/capability identity brackets on three direct devices:
  one user-visible non-C connection, two hardwired devices, version0200 once and
  0201 twice, known-empty storage subset. Default alert byte gives EOPNOTSUPP;
  explicit native ADO matches raw controller-cache brackets (or typed inactive
  state). No physical nonzero alert, downstream dock/storage/Type-C data positive
  is claimed. Their positive/error/peer/ancestry cases remain fixtures.
- Full230 reads give187 values/43 typed unavailable on actual AC0,210 user/20
  root,22 writes excluded. The sole status/errno change from0.69 battery evidence
  is the source-corrected default alert-byte absence; no privilege change.
- Actual GJS193/all12SBS matches Python on the captured gauge/package raw frames;
  all six helpers/hooks/preferences are unchanged. Root-owned runtime/DKMS source/
  MOK CMS, fan auto/request255, cap100/profile/keyboard/four UEFI hashes/board
  selector and PPD/thermald authority pass. Owner Shell activation awaits ordinary
  login; no reload/logout or physical USB/power transition requested.

Fifteen further source bindings give227 reviewed scopes and25 remaining metadata
obligations, not an API-missing count or completion percentage. Nineteen retained
evidence flags plus the explicit physical USB scope limits remain separate from
implemented native functionality. Unknown OEM/controller payloads and existing
owner/hardware/meter/boot/enabled-SB/suspend/fold checks remain. Qualified0.69.0
rollback is retained; no Vitals helper migration required.

## Retained 0.69.0 qualification

Version0.69 closes the filesystem-capacity mount replacement gap. A path-based
read could follow an unmounted selected partition to its containing filesystem.
The new provider samples a pinned directory with fstatvfs and matches fdinfo
mount ID/inode/dev_t to mountinfo and lsblk. Selected block generation, kernel
classification and mount tree, plus mount record and reopened path, are checked
again. Unknown mappings stay unavailable; readable sibling errors remain local.
No block device, filesystem probe, physical unmount or hotplug is requested.

- Complete SSD/HDD source comparison covers1578 instructions each, all local
  branches/calls and43 RIP references. Only MediaType4 versus3 and two log names
  differ; two other data loads have identical bytes. The recovered volume
  Size/SizeRemaining chain describes capacity. Linux per-filesystem records and
  reserved-space accounting remain explicit native equivalents.
- make check passes666 Python tests, including25 filesystem-capacity cases;
  optimized/sanitized core8188/diagnostic653/OEM16806,210 status-failure boundaries,
  retained transport, six Node helpers, GNOME adapters and252-route parity pass.
  W=1 module passes. Fixtures cover parent fallthrough, same-device overmount,
  detached mounts, changed generation/tree/options/path, independent errors,
  reserved space/zero, mapper paths, nsfs records, malformed data and deadlines.
- Six installed native/CLI/C reports agree with independent pinned mount and
  block-generation brackets: two actual SSD filesystems match independent totals
  and free/used outer reads within32MiB; rotating HDD is known empty. No physical
  rotating-media, unmount/hotplug or unqualified Btrfs backing-layout claim.
- Full230 read APIs give187 values/43 typed unavailable on actual AC0/discharge,
  with no status/errno/scope changes from retained0.68 battery evidence;210 user,
  20 root,22 writes excluded. The audit splitter now includes cached Wi-Fi routes
  even when cache expiry requires a live privileged fallback; real API permission
  checks/errors are preserved. No route can disappear between the two passes.
- Fresh actual GJS193/all12SBS matches Python on captured gauge and CPU package
  raw frames. All six helpers, hooks and preferences are unchanged. A first RAPL
  read after a long idle gap correctly remained unavailable; the next actual
  existing-method refresh reports measured power. Initial evidence is retained;
  actual owner Shell activation still awaits ordinary login, without forced reload.
- Exact root-owned runtime/DKMS source/MOK CMS, firmware fan auto/request255,
  cap100/performance/keyboard/four UEFI hashes/board selector and existing
  PPD/thermald authority pass. No factory, charge-limit or power-policy change.
- Existing charging/discharge ADC and gauge proof from0.68 is retained. Owner
  Shell activation, absent hardware, unknown OEM/controller payloads and physical
  meter/boot/enabled-Secure-Boot/suspend/fold/nonfixed-PD remain separate.

Fifteen additional source contracts are explicitly bound to completed scoped
reviews, including the SSD counterpart;212 bindings/40 metadata obligations
remain. These counts are not missing APIs or a completion percentage. Nineteen
retained source/hardware/owner evidence flags remain explicit. Rollback retains
qualified0.68.0; no Vitals helper update is needed for0.69.

## Retained 0.68.0 qualification

Version0.68 corrects the unsupported pack/cell power-sum invariant. The compatible
DA1 format defines separate cell V/I pairs and SBS Voltage()*Current() pack power.
Both pack/average fields are signed centiwatts. Source references and the explicit
inference are in PROTOCOL.md; they do not identify the physical OEM gauge.
Native and Vitals providers now publish the reported pack field using existing
identity/frame/freshness/topology and200W per-field checks. Per-cell V/I checks
remain. Raw pack/average words and a diagnostic cell-sum comparison are added;
no locally calculated replacement power or new hardware request is introduced.

- make check passes649 Python tests, optimized/sanitized core8188/diagnostics653/
  OEM16806 with210 status failures, retained transport, six Node helpers, GNOME
  adapters and252-route parity. W=1 module passes. New cases preserve an independent
  pack value despite cell-sum/field errors, with unchanged out-of-range/stale guards.
- All eight retained0.67 discharge observations replay to their exact reported
  pack field (-14.48..-13.80W) instead of unavailable. Fresh installed native and
  metrics CLI return -25.05W from raw -2505cW with independent cache-read brackets;
  the CLI also exposes direct SBS and cached SBS diagnostics, formerly missing
  from its aggregate report. Providers retain individual ages/errors.
- Fresh actual GJS193/all12SBS displays Battery Gauge Power as -25.1W and agrees
  with Python on the exact same captured raw gauge frame, including cell/average
  power. Negative denotes battery discharge. Gauge power is computed internally,
  not an independent power ADC, charger-input estimate or external-meter calibration.
- Exactly one reviewed battery helper changed; backup/hash/readback and installer
  idempotence pass. Other five helpers, sensors.js/values.js hooks and preferences
  remain byte-identical. Actual owner Shell activation still requires normal login;
  no Shell reload or logout was forced.
- Full230 read APIs remain187 values/43 typed unavailable on actual AC0/discharge,
  210 user/20 root,22 writes excluded, no status/errno/scope changes from0.67.
  SBS/five NTCs/package power pass; input ADC remains ENODATA with no forward input.
- A subsequent natural AC1/charging transition qualifies positive charging ADC:
  eight read-only observations over38.31s give2.5308..2.9748A charging, zero
  discharge ADC,1.6428..2.7528A input and32.014886..54.175104W input power.
  Raw ADC conversion/product checks pass. Reported gauge pack power is positive
  23.42..24.43W and cached SBS current is+3.017A. Observations share caches and
  providers have different sample times; no instantaneous cross-provider equality
  or external-meter calibration is claimed. No charge limit or transition forced.
- Fresh AC native/metrics CLI and GJS193/all12SBS preserve the positive reported
  pack field; Python/GJS agree on the exact captured frame. Helpers/preferences
  still match. Full230 AC reads give194 values/36 typed unavailable, with exactly
  the14 expected inactive-to-active PD status/errno changes and no scope changes.
  Both original battery-phase evidence and subsequent AC evidence are retained.
- Exact root-owned runtime/DKMS source/MOK CMS, fan auto/request255, cap100,
  performance, keyboard/four UEFI hashes/board selector/PPD/thermald authority pass.
  Physical meter/boot/suspend/fold and absent peripherals
  remain separate. Unknown OEM payload semantics and55 source-review bindings
  remain explicit; these counts are not missing API counts or completion percentages.

Rollback retains qualified0.67.0 and the verified prior battery-helper backup.

Version0.67 closes the disk-temperature replacement race. The new provider
brackets sysfs block identity/diskseq/dev_t, device-node inode and associated
hwmon identity/ancestry around metadata, reads and final publication. SMART
standby/error policy remains; unknown/replaced readings are never zero degrees.
Original HDDTemp83430/827d0 and HDDInfoc8700/bb4f0 were reviewed completely:
SMART C2 raw-byte formatting and COM initialization flags are distinct from
the native Celsius/device representation.

- make check passes646 Python tests, including14 disk-temperature cases;
  optimized/sanitized core8188/diagnostic653/OEM16806 with210 status failures,
  retained transport, six Node helpers, GNOME adapters and252-route parity pass.
  W=1 kernel build passes. No physical hotplug is induced for coverage.
- Installed native/CLI/C temperature values match the existing associated NVMe
  hwmon, with independent unchanged generation/node/hwmon identity brackets and
  a declared2C outer-read comparison tolerance. SMART was not used on this live
  hwmon case. SATA/drivetemp/SMART positives remain transport/filesystem fixtures.
- Power state changed to actual AC0/BAT discharging. Full230 reads give187 values
  and43 typed unavailable,210 user/20 root,22 writes excluded. Fourteen PD status/
  errno changes match no active contract (seven formerly successful values and
  seven formerly ENODATA fields now ENODEV); PD providers are byte-identical to0.66.
  No other status or privilege change is present. Initial AC-only private harness
  assumptions were corrected; no production guard was weakened for qualification.
- Eight read-only battery observations over33.16s show signed SBS discharge,
  negative per-cell/average gauge powers and positive charger-side discharge ADC.
  Same-frame cell V/I and centiwatt fields agree within0.03W. Six PSYS readings
  are positive13.14..14.37W; startup/stale/read errors stay unavailable, not0W.
  Observations share caches; they are not eight independent hardware acquisitions.
  Different providers have different sample times; no cross-provider instantaneous
  equality or external-meter calibration is claimed. Input ADC correctly gives
  ENODATA with no forward input; positive charging ADC remains unqualified.
- The instantaneous pack-power sum-consistency guard withheld all eight observed
  pack readings despite nonzero raw fields. This is retained evidence requiring
  source timing/scaling review, not a passed calibration or fabricated total.
  Fresh GJS193 rows/all12SBS agree with Python on the exact same captured gauge
  frame, including unavailable pack power and inactive profiles/alerts. Six
  helpers/preferences are unchanged; actual owner Shell activation is pending.
- Exact root-owned runtime/DKMS source/MOK CMS and fan auto/request255, cap100,
  performance, keyboard/four UEFI hashes/board selector/PPD/thermald authority pass.
  Enabled-Secure-Boot coldboot and other physical variants remain separate.

The cumulative review registry now binds197 original names to scoped source
records. Remaining55 bindings are audit metadata obligations, not55 known missing
APIs. Nineteen retained source/positive-hardware/owner evidence flags remain;
new pack-power timing/scaling evidence is explicit. Qualified0.66.0 is retained.

Version0.66 reconciles all four original e-marker wrappers (333 instructions,
no unresolved branches). Original VID returns32-bit ID Header, PID16, XID32
and Other32 at the fifth VDO. Native VID keeps its useful16-bit default and
adds strict boolean raw_header=true for the original full32-bit value; reports
also expose id_header_raw_vdo. No discovery/controller value/4CC write is added.

make check passes636 Python tests plus retained optimized/sanitized
core8188/diagnostic653/OEM16806 and210 status-failure boundaries, transport,
six Node helpers, GNOME adapters and252-route parity. W=1 module passes.
High-bit/header byte order, unchanged VID16, ACK/short/missing gates and strict
pre-hardware selector checks pass. Installed native/CLI/C checks give the expected ENODATA for all four fields,
including the new full-header option:15 calls, with independent unchanged
contract/cable-cache brackets. No completed cable ACK is present, so no physical
nonzero identity is claimed. Full230 reads remain194 values/36 typed unavailable,
with unchanged status/errno and210 user/20 root. SBS/input ADC/five NTCs/package
power pass; fresh GJS193/all12SBS/six helpers/preferences pass. Exact runtime,
DKMS source and existing MOK CMS pass. Fan auto/request255, cap100, performance,
keyboard/four UEFI hashes/board selector and PPD/thermald authority are preserved.
Qualified0.65.0 is retained for rollback.

Version0.65 corrects the source-confirmed HDMI/USB quantity mismatch and pins
WWAN read context. All six remaining radio/display wrappers and shared source
paths were reviewed, including31 Bluetooth switch entries and WWAN parser/cache
offsets. Proprietary source was inspected privately, never executed or committed.

- make check passes633 Python tests, optimized/sanitized core8188,
  diagnostics653, OEM16806 with210 status-failure boundaries, retained transport,
  six Node/Vitals helpers, GNOME adapters and252-route parity. W=1 module passes.
- Installed0.65 native/CLI/C and hdmi-command reports match four independent DRM
  status brackets: one disconnected HDMI-A connector, false/count0, full coverage.
  No physical attached HDMI/USB display positive is claimed. Explicit USB display
  remains false/complete through native/CLI/C, separately from HDMI presence.
- Bluetooth returns a known-empty connected list through all three interfaces;
  all three WWAN exports give ENODEV through native, CLI and C. The existing
  ModemManager owner was read without activation; bounded object-name XML and
  owner/inventory/SIM/radio-transition, deadline and privacy fixtures pass.
  No physical modem or Bluetooth major-class positive is claimed.
- Root native/CLI/C tablet logical switch results agree; physical fold and raw
  OEM8e33 byte mapping remain unqualified. No radio/display/fold action requested.
- Full230 reads remain194 values/36 typed unavailable, no status/errno/privilege
  changes;210 user/20 root and22 writes excluded. SBS/input ADC/five NTCs/measured
  CPU package power pass. GJS193 rows/all12SBS, six helpers and preferences match;
  actual owner Shell activation remains pending an ordinary login.
- Exact root-owned runtime/DKMS source and existing MOK CMS signature pass.
  Firmware fan auto, request255, charge cap100, performance profile, keyboard,
  four UEFI hashes, board selector and PPD/thermald authority are preserved.
  Enabled Secure Boot coldboot remains a separate test.

The first private qualification harness assumed JSON errors for CLI and a
flat errno for C; these assumptions were corrected against their existing
interfaces. No production edit or installed-version replacement was needed.
Physical tests, unknown firmware fields and owner-session evidence remain
separate;19 retained evidence flags do not represent19 missing APIs.
Rollback remains the qualified0.64.0 release.

Complete four platform wrapper/shared-helper reviews confirm a quantity bug:
RF_USBIsTranster's original class0 comes from PhysicalDisk PercentDiskTime>20,
not USB bytes. Native default now uses measured queue-weighted disk time,
integer threshold, pinned root partition/slave exclusions, separate busy time
and raw endpoints. Windows synthetic_Total and cross-OS counter calibration are
explicitly omitted/unqualified. Unknown root layouts are not guessed. Reset,
hotplug/reuse, topology cycles/shared backing, threshold truncation, suspend and
partial-positive/unknown-zero cases pass; excluded-root failures cannot fabricate
non-root activity. The default API and disk-activity command are unprivileged.

Actual USB traffic remains selectable through metric usb_traffic and its CLI.
Opened character type, GETX header-only/zero-payload requests, per-reader loss/
queue statistics and owned baseline flush, actual elapsed/boottime and event cap
are preserved. Loss/backlog/cap/ISO errors cannot prove inactive or exact bytes;
positive lower bounds remain. Four actual native/CLI/C/command kernel reads pass,
all with complete0-byte bulk/ISO observations, zero dropped/pending and measured
intervals0.2001..0.2010s. Metadata events do not establish positive bulk/ISO traffic.

Four actual user disk API/CLI/C/command results match independent root-partition
mapping and outer sysfs counter brackets, with exact percentage arithmetic.
Only the root NVMe is present/excluded; a positive non-root physical threshold is
unperformed. S-Mode returns explicit Linux not-applicable through all three APIs.
HDD capacity is a known empty inventory; SSD peer mount capacities agree with
independent statvfs. SD scalar0/detailed empty match no inserted card; all matching
cards' capacities are preserved in fixtures. Real inserted-SD/HDD positives remain
separate from current negative and software qualification.

622 Python tests, optimized/sanitized core8188/diagnostic653/OEM16806,210 OEM status
failures, retained transport/six Node/GNOME/parity and W=1 build pass. Full230 reads
retain194 values/36 typed unavailable, with no status/errno changes. Default disk
predicate moves root->ordinary user, now210 user/20 root;22 writes stay excluded.
Fresh GJS193/all12SBS/six helpers/settings, installed source/runtime/root ownership/
existing-MOK CMS and owner fan-auto/cap100/profile/keyboard/four UEFI hashes/board
selector/desktop-power authority pass. Previous qualified rollback0.63.0 remains.

Four source scopes are reconciled and the Windows-only S-Mode flag closes.
Nineteen evidence flags remain, including positive hardware cases distinct from
known-empty/current source qualification. Next radio/display source audit must
follow helpers: the shared original HDMI predicate queries VideoOutputTechnology5,
while native currently restricts causality to USB. Its full helper/quantity review
is pending; no completion of that scope is claimed. Full goal stays active.

# Qualification: 0.63.0, 2026-11-01

Twelve complete original wireless wrappers/shared-helper dataflows, including the
resolved11-case PHY jump table, establish association BSSID/state/channel/dBm,
2.4GHz1/6/11/other groups,5/6GHz grouped counts, chain RSSI/fallback and separate
received/sent byte rates. Native now explicitly includes the four channel groups
beside its full channel map. Correct native bands/unclassified counts and genuine
chain values remain; original coarse frequency bugs and duplicate-antenna fallback
are not reproduced. Physical Main/Aux identity remains unverified.

AP cache reads now bracket daemon, inventory, kernel netdev, scan and BSS identity/
frequency, using fixed properties and an overall8-second budget/per-call3s bounds.
Fault cases cover replacement, rename/reuse, changed BSS, malformed/duplicate paths,
expiry, never-scanned unknown versus scanned-empty zero and no SSID/scan request.
All six quantities pass mixed2.4/5/6GHz/channel14/4.9GHz/unclassified/dedup fixtures.

Installed native/CLI/C give18 count/group comparisons against an independent raw
NetworkManager cache bracket, stable on the first attempt. Twelve link calls match
independent BSSID/channel/connection evidence; RSSI instants retain signed dBm and
are not simultaneous calibration. Three detailed RX/TX rate calls lie within
independent outer counter brackets and preserve their sum, without traffic creation.
Three root chain calls return measured chain values with unverified physical labels.
Original Windows and native Linux driver framing accounting remain distinct.

610 Python tests, optimized/sanitized core8188/diagnostic653/OEM16806,210 OEM
status failures, retained transport/six Node/GNOME/parity and W=1 build pass.
Full230 reads retain194 values/36 typed unavailable,209 user/21 root,22 writes
excluded; no status/errno changes. Fresh GJS193/all12SBS/six helpers/settings,
source/runtime/root ownership/existing-MOK CMS and fan-auto/cap100/profile/keyboard/
four UEFI hashes/board selector/desktop-power authority pass. Previous qualified
rollback0.62.0 remains; actual owner Shell activation awaits ordinary login.

All twelve wireless source/native scopes are reconciled. Eleven prior flags close;
Main/Aux physical mapping stays explicit among20 remaining evidence flags. These
are not20 missing APIs. Remaining OS/source/firmware and physical/session/peripheral/
boot qualifications keep the goal active/incomplete. No scan, connection, factory,
antenna, charger, fan-mode or power-policy mutation is introduced for coverage.

# Qualification: 0.62.0, 2026-11-01

Complete original fan selector/duty/test-mode bodies establish byte0..255,
selector0..4 and serialized boolean manual mode; the Windows mutex wait is not
a manual-mode expiry. Native now supports the full requested byte and CLI0..100%
while preserving kernel ownership, low-RPM/fault checks and automatic restoration.
Stored request, independent EC duty code and RPM remain separate quantities.
Raw fan writes are still rejected before transport for all256 possible values.

All256 actual API requests store/read back in automatic mode without applying
manual duty. Representative0/1/126/127/128/254/255 also pass installed CLI/C calls.
One readiness-gated manual120 point runs0.453s: five independent diagnostic reads
return code120, RPM3466..3517 exceeds1764 abort minimum, coretemp maximum67C.
Child and independent3-second supervisor restore automatic mode and request255;
supervisor completes0.609s. This is not all-byte electrical/RPM calibration or
a general manual timer lease. Logical fan0 and raw selection1 remain unchanged.

Original immediate battery control passes Control_status to DEVS1179735; Linux
ASUS RSOC accepts meaningful percentages0..100. Native validation, caller choice
schema and CLI now accept that range. All101 percentages are fixture-tested for
immediate/remembered distinction and invalid values. Installed native/CLI/C write
only the existing100 setting. ASUS acknowledgment/cached-setting readback is not
an independent physical cutoff measurement; no low charge-threshold test or
owner preference record mutation occurs.

606 Python tests, optimized/sanitized core8188/diagnostic653/OEM16806,210 OEM
status failures, retained transport/six Node/GNOME/parity and W=1 build pass.
Full230 reads retain194 values/36 typed unavailable,209 user/21 root,22 writes
excluded; no status/errno changes. Installed source/runtime/root ownership/MOK
CMS, retained SBS/input ADC/five NTCs and fan-auto/cap100/profile/keyboard/four
UEFI hashes/board selector/desktop-power authority pass. Fresh GJS193/all12SBS
and six helpers/settings remain qualified; actual owner Shell activation still
needs ordinary login. The first audit fixture incorrectly required GHz for a
valid400MHz sample; that assertion was corrected without production changes.
A subsequent unprimed single sysfs read reported unavailable package power after
an unsampled gap (its errno was not captured). A direct stale-gap/warmup check and
fresh primed GJS result are retained separately. No stale/estimated value is used.
Previous qualified rollback0.61.0 remains intact.

The four native-control source/implementation flags are reconciled.31 remaining
evidence flags include source/quantity review and physical/session/peripheral/
firmware/boot variants; they are not31 missing APIs. Factory writes, real low
charge cutoffs, zero/stall fan tests and absent peripherals are not performed
for coverage. The full goal remains active/incomplete.

# Qualification: 0.61.0, 2026-11-01

Original DLL and primary-driver source connect package power to MSR611 energy,
MSR606 units and nominal100ms milliwatt scaling. Native uses CPU0 package energy
over actual elapsed time, with public JSON evidence and power3_input microwatts.
Two fresh energy endpoints fall inside independent read-only MSR brackets; units
match606 exponent14. No thread/policy/energy-reset change occurs. Native/CLI/C
and ordinary unprivileged power command pass exact energy/time arithmetic and
public label/value agreement; calls remain separate instants and intervals.

Units, one-wrap arithmetic, stopped counters, ambiguous extra wraps, stale/invalid
fields, partial/duplicate JSON, descriptor closure, bounded warmup and no-elevation
cases pass. Long/slow/failed reads remain unavailable. Suspend/resume clear the
baseline in source; physical sleep/other-CPU/external-meter tests remain separate.

Four complete battery source bodies and shared gate/data helpers establish
version10/error/PF/refresh/ready behavior, three unsignedLE16 extrema and legacy
32-byte lifetime3 cache reads. Fresh native target data separately qualifies the
complete26-byte manufacturer block and block1 offsets16/18/20. All four installed
native/CLI/C results match independent raw lifetime packets. This does not claim
a healthy legacy cache or invent a six-byte suffix; opaque OEM bytes remain raw.

All601 Python tests, optimized/sanitized core4860/diagnostic653/OEM16806,210 OEM
status failures, retained transport/six Node/GNOME/parity and W=1 build pass.
Full230 reads retain194 values/36 typed unavailable, with no status/errno changes;
package power moves to ordinary-user scope (209 user/21 root),22 writes excluded.
Fresh actual GJS193 rows include123 Battery/10 Processor/13 Storage/45 Network/
2 Fan/all12SBS and a formatted CPU Package Power row. Six installed helpers and
preferences match source/readback, with owner Shell activation still pending login.

Installed source/runtime/root ownership/existing-MOK CMS, SBS/input ADC/five NTCs,
fan-auto/cap100/profile/keyboard/four UEFI hashes/selector and desktop-power authority
pass. Prior qualified rollback0.60.0 remains. Four native-control source scopes,
including the unimplemented lower PWM range, and other source/physical/session/
power/peripheral/boot qualifications remain open.

# Qualification: 0.60.0, 2026-11-01

Complete seven wrapper bodies/shared PDO reader establish index0..6, firmware14+
and exact little-endian DWORD/sentinel behavior. Expanded cases first reproduced
the native rejection of raw source objects with an unconverted nonfixed active
contract. The corrected provider preserves those raw objects, while fixed-limit
consistency, AC/validity/count/padding/member and repeated-read gates remain.
No voltage/current/power conversion is inferred for unknown types.

Positive software cases cover both ports, every count1..7, all seven generic/named
selectors, raw battery/variable/APDO objects and nonfixed active contracts. Every
read-failure boundary rejects partial output and leaves the destination unchanged.
Malformed public envelopes, invalid fixed fields and nonmember active objects
remain errors. Vitals tests retain raw types on both ports and the full seventh
object. Its reviewed helper migration preserves owner source/settings and rejects
unknown edits; the actual installed helper upgrade is independently read back.

Installed native/CLI/C pass84 comparisons against an independent raw-cache bracket:
four actual stock-source objects match, and absent slots5..7 retain ENODATA.
Historical physical port1/unplug/port2/port1 capture has151 samples, nine stable
offline samples with source suppression and complete port2 profiles. That prior
physical result is retained separately; an actual nonfixed contract is unqualified.

All595 Python tests, optimized/sanitized core4858/diagnostic653/OEM16806,210 OEM
status failures, retained transport/six Node/GNOME/parity and W=1 build pass.
Full230 reads retain194 values/36 typed unavailable with no status/errno changes;
22 mutation/configuration writes remain excluded. Fresh actual GJS192/all12SBS,
six installed helpers/preferences, source/runtime/root ownership/existing-MOK CMS,
SBS/input ADC/five NTCs and fan-auto/cap100/profile/keyboard/four UEFI hashes/
selector/desktop-power authority all pass. Prior qualified rollback0.59.0 remains.
Owner Shell activation, unknown fields and physical/session/power/boot variants
remain separate from this source/native qualification.

# Qualification: 0.59.0, 2026-11-01

Complete original frequency exports and primary Intel driver handlers establish
P-state/turbo multipliers and the original mailbox-derived reference. Native
replaces that mailbox write with the qualified CPU's direct CPUID.16H reference
and samples fixed read-only MSRs on CPU0. All byte-ratio values and reference
bounds have conversion checks. Per-field faults stay independent, with strict
JSON/quantity validation and no CPUFreq fallback. Original scheduling and native
fixed CPU0 placement differ explicitly; other CPU variants remain unqualified.

Installed independent read-only CPUID/MSR sampling obtains three matching stable
current-frequency brackets in three attempts, verifies maximum4600MHz and
reference100MHz, and restores only its own thread affinity. Native/CLI/C current
values have valid ratios at separate instants; maximum agrees with independent
MSR/sysfs. AC and PD booleans independently match ADP1 and UCSI role/type/path
fields. CLI show preserves separate policy and reported-ratio metadata.

XG source review corrects the31-byte firmware boundary; a sentinel immediately
outside the original copy is excluded. Complete replies, malformed/changed open
descriptors, wrong collections and ioctl faults are covered before any feature
request. Current real device absence remains ENODEV; no physical XG pass claimed.

All589 Python tests, optimized/sanitized core1232/diagnostic653/OEM16806,210 OEM
status failures, retained transport/six Vitals Node/GNOME/parity and W=1 build
pass. Full230 installed reads retain194 values/36 typed unavailable with no
status/errno changes; the two corrected frequency results change float to integer
MHz intentionally.22 mutation/configuration writes stay excluded from that census.

Fresh actual GJS Sensors/Values produce192 rows:123 Battery,9 Processor,13 Storage,
45 Network and2 Fan, including both frequency rows formatted in GHz and all12SBS.
The six installed helpers match source; existing Vitals preferences are unchanged.
Overlapping refresh, read failure, provider replacement and destruction tests pass.
Actual owner Shell activation remains pending ordinary login, without forced reload.

Installed source/runtime/root ownership/existing-MOK CMS, SBS/input ADC/five NTCs,
fan-auto/cap100/profile/keyboard/four UEFI hashes/selector and desktop/power authority
pass. The private qualification harness initially parsed human-readable show output;
the corrected check uses its existing --json option, without a runtime change.
Prior qualified rollback0.58.0 remains. Full source/physical/session/peripheral/boot
qualification and undocumented fields remain open.

# Qualification: 0.58.0, 2026-11-01

Original lifecycle source review separates installed system-control DriverVersion,
loaded driver version/reference count and the frontend literal. Installed native,
CLI and C now agree with the actual asus-nb-wmi binding and independent modinfo:
asus_wmi has no declared version, so its verified kernel release is explicitly
labelled as such. Missing, invalid, out-of-tree versionless or changing metadata
has no frontend fallback. Nine provider tests cover those cases and timeouts.

Actual native/C root and mixed real/effective UID calls register applications in
an isolated caller-owned0600 record, preserving unrelated keys and preferences.
The worker uses the account's registered groups; an actual group-accessible file
qualifies this after privilege drop. User CLI custom context also passes. No
application is executed. Stale/absent revisions, malformed/oversized JSON, links,
ownership, concurrent changes and commit uncertainty have focused tests.

Native/CLI/C loaded/frontend versions, reference counts, idempotent initialization,
client release, stop review-plan digest and uint32 addition agree. Stop is not
physically applied for this check; prior live stop/initialize evidence is retained.
Six fixed journal markers independently match message and info/critical priority.

All581 Python tests, optimized/sanitized core716/diagnostic653/OEM16806,210 OEM
status failures, retained transport/five Vitals Node/GNOME/parity and W=1 build
pass. Full230 installed reads retain194 values/36 typed unavailable with no
status/errno changes; GetInfVersion intentionally changes string to structured
metadata.22 mutation/configuration writes remain excluded from the read census.
Installed source/runtime/root ownership/existing-MOK CMS, SBS/input ADC/five NTCs
and fresh actual GJS190/all12SBS pass. Fan-auto, cap100/profile/keyboard/four UEFI
hashes, board selector and desktop/power authority are preserved. Previous
qualified rollback0.57.1 remains. Source/physical/session/peripheral/boot limits
are separate and the complete port goal remains open.

# Qualification: 0.57.1, 2026-11-01

Full four-wrapper/shared-helper comparison distinguishes the ATD command-code
interface from native HealthyTable logical bytes. The remaining invented
bank6[0] nonzero guard is removed; exact read/write parameters, native allowlist,
qualified bank ceiling, protected fan/cache selectors and reviewed apply remain.
Raw plans bind recipe3 and expose the actual packet. Mocked packet/zero-I/O and
protected-selector tests pass; no physical raw/factory write is performed.
Applied OEM results now distinguish transport completion from unknown firmware
acknowledgment and unverified readback. No reply exists on that fixed write path.

Primary original kernel-driver analysis connects IOCTL80102080 to MSR198[47:32]
and stored1/8192*1000 constants. Native rounding differs from source truncation
by at most1mV. Installed native voltage has matching stable brackets against
independent read-only MSR samples; native/CLI/C source/kind/units agree while
different calls remain different instants. It is a CPU-reported P-state value,
not an independent rail ADC. No voltage/clock/policy write occurs.
An initial full-Python sequential comparison failed its matching-bracket gate
and remains inconclusive. A bounded C helper reads MSR/hwmon back-to-back on its
own temporarily pinned CPU0 thread, restores affinity, and obtains three stable
matching brackets in four attempts. No global CPU policy is changed.

Installed native/CLI/C contract-PDO values match independent complete public EC
cache bytes for default/explicit active port; inactive-port errors are retained.
Raw read agrees with independent fan count. Raw review plans agree across all
interfaces and with independently recomputed digests; invalid parameters fail
before authentication. Full230 read calls retain194 values/36 typed unavailable,
with no status/errno regression and22 mutation/configuration writes excluded.

All564 Python tests, optimized/sanitized core716/diagnostic653/OEM16806 and
retained transport/Node/GNOME/parity suites plus W=1 build pass. Installed source/
runtime/root ownership/existing-MOK CMS, native SBS/input ADC/five NTCs, actual
GJS190/all12SBS and owner settings/four UEFI hashes/board selector/power authority
remain verified. Intermediate0.57.0 was unpublished and unqualified after the
write-ack metadata finding; retain it as evidence. Prior qualified rollback0.56.0.
Remaining source/field and physical/session/peripheral/boot limits stay explicit.

# Qualification: 0.56.0, 2026-11-01

Grouped source review covers ten EFI functions/three shared helpers and seven
OEM control/read functions. EFI offsets, raw UUID/full HEAL bytes, native branch
selection and caller-supplied language match the source. All ten installed
native/CLI/C reads/plans independently agree with direct record slices and
result digests;16 retained backup/revision/immutable simulations pass. No factory
write is performed and no new firmware family is physically qualified.

Two omitted OEM recipes are corrected: monitor05/85 and version24+ observed-mask
clearing86/35. Original14/19/23 version gates and14..23 whole-flag clearing remain;
fixed controls no longer infer capability from a zero/nonzero bank6[0] byte.
Positive fixtures cover all256 byte versions, zero/ff masks, newly arriving bits
and210 injected status failures, with16798 optimized/sanitized checks. Current
max-bank5 rejects unsupported6/7 before I/O. Reviewed plans bind recipe revision2;
old digests cannot authorize corrected operations.

All561 Python tests, optimized/sanitized core716/diagnostic653 and retained
transport suites, five Vitals Node adapters, GNOME adapters/parity and W=1 module
build pass. Installed native/CLI/C review plans expose exact encodings and match
independent digests without apply. PD-name data agrees with twelve independent
fixed-register reads. Installed source/runtime/root ownership/existing-MOK CMS,
full230 reads194 values/36 typed unavailable, fresh actual GJS190/all12SBS and
native SBS/input ADC/five NTCs pass. Availability/error status remains unchanged.
Fan-auto, cap100/profile/keyboard, four UEFI hashes, board selector and existing
desktop/power authority are preserved. Prior0.55.0 remains qualified rollback.
Factory controls on real responding banks, broader source/OEM fields and
physical/session/boot/peripheral qualifications remain separately unverified.

# Qualification: 0.55.0, 2026-11-01

Grouped original control/helper review found omitted remembered user-choice
side effects in battery-health ToUser and quiet/profile setters. Native private
records now follow successful verified writes; the immediate battery setter
retains its distinct behavior. Source review of exact installed Power Profiles
daemon0.30 verifies existing native external-profile monitoring/persistence.
No automatic boot battery policy or competing daemon is introduced.

All559 Python tests, optimized/sanitized core715/diagnostic653 and retained
transport suites, five Vitals Node adapters, GNOME adapters/parity and W=1 build
pass. New tests cover actual worker persistence, caller ownership/privilege drop,
sanitized environment, duplicate/oversize/invalid JSON, symlink/hardlink/mode
rejection, bounded locks, stale revisions, lost replies, partial effects and
conditional compensation without undoing later external selections. Unexpected
control/lifecycle parameters fail before authentication.

Installed native/CLI/C same-value controls independently read back owner100%
cap/performance selections and private0600 UID1000 files in an isolated caller
configuration directory. Native/C root workers drop to the actual sudo caller;
actual user CLI keyring elevation preserves custom configuration context.
The immediate setter leaves an absent record absent. Read-only preferences
agree with independent user-file reads. No alternate profile/cap transition or
automatic charge-policy reapplication is claimed.

Installed source/runtime/root ownership/existing-MOK CMS checks pass. Full230
reads retain194 values/36 typed unavailable with no status/errno changes;22
mutation/configuration writes stay excluded. Fresh GJS actual Sensors/Values
retains190 rows, including45 Network/2 Fan/all12SBS. Native SBS/input ADC/five
NTCs pass. Fan-auto, profile/cap/keyboard, four UEFI hashes, board selector,
desktop Power Profiles properties/state file, thermald authority, disabled
legacy tuning services and default user auth/app/preference files are preserved.
Previous qualified0.54.1 remains available for rollback. Full-source/OEM field
and physical/session/peripheral/boot qualification gaps remain open.

# Qualification: 0.54.1, 2026-11-01

Original SaveEcLog data coverage is recovered from six source table groups69
entries,23 nested descriptors and all eight special dispatch branches. Static
initializer/CFG reconstruction executes no vendor binary. Current native layout
matches all functional names/selectors/widths/minimum versions exactly. Every
one of52 target DD scalar selector bytes has an explicit cached BIOS case.
The existing raw-data/EEPROM implementation is reused with its original guards.

All537 Python tests, optimized/sanitized diagnostic653 checks, retained core715
and transport suites, five Vitals Node adapters, GNOME adapters/parity and W=1
module build pass. Diagnostic tests inject failures at201 full-collection request
boundaries,20 selector requests and155 partial-transaction stages. They verify
exact saved-selector restoration, no fan policy write, bounded strings, raw
units, typed errors, version/manual gates and no automatic-mode duty request.
Private logging also verifies mode0600, exclusive creation, symlink/overwrite
rejection and invalid arguments before file creation/elevation. Source manifest
verification text had the earlier202-request count;0.55 corrects it to201,
matching the final collector after removing the automatic-mode duty request.

Installed0.54.1 source/runtime equality, root ownership and existing-MOK CMS
verification pass. Three independently bracketed EC snapshots retain all69
entries and preserve the real board selector. On protocol15,45 entries provide
data;23 newer-version entries and the strict11-byte manufacturer block remain
unavailable. The last currently times out; its partial payload is withheld.
The ordinary native battery identity remains independently available. The
separate32-byte project firmware revision and indexed board data are present.

The target DD2/35 handler tests9130 bit7. Five bounded cached-source traces
prove no automatic reply and manual0/97/127 ->0/194/254 codes. Installed fixed
reads confirm raw fan selector1, count1 and automatic mode; native logical
channel0 is kept separate. The automatic reader sends no DD2/35 request. An
owned bounded manual test observes EC duty254 versus requested PWM255, while
full EC diagnostics reject manual ownership. Child and independent parent restore
automatic control. The duty code is not an electrical PWM measurement.

SaveEcLog passes native/CLI/C, each creating one private complete JSONL sample
with69 diagnostic entries plus the retained native snapshot. Raw EEPROM remains
EOPNOTSUPP on currentFE firmware and E5 call count stays0. The standalone
unprivileged diagnostic command passes. Background metrics do not consume events.
Fresh GJS loads actual installed Sensors/Values and verifies190 rows: retained
188 plus Fan EC Duty Code/Control, all45 Network and12 SBS rows. Automatic duty
is explicitly unavailable while control remains Automatic. Installer readback
and idempotence pass; normal owner login is still needed for running Shell.

Full230 read calls retain194 values/36 typed unavailable,208 user/22 root, with
no availability/errno regression;22 mutation/config writes remain excluded.
Native SBS/input ADC/five NTCs pass. Fan-auto, owner100% cap, profile/keyboard,
board selector and four UEFI hashes are preserved. The intermediate unpublished
0.54.0 was not qualified: its zero-selector/automatic-duty assumptions were
corrected before publication. Last previously qualified rollback is0.53.0.
Full-goal source reconciliation, unknown firmware payloads and existing physical/
session/power/boot/peripheral qualification limits remain open.

# Qualification: 0.53.0, 2026-11-01

Grouped original wireless helper review corrects seven quantities: associated
AP HT/VHT/HE capability ceiling, kernel peer association family, two descriptive
card inventories and three complete nine-bin RSSI distributions. Existing link
rates and explicit threshold counts remain separately available. Native bins
count decade boundaries once; standard arithmetic replaces anomalous source
table entries. HE fastest-standard-GI and EHT/legacy-mode limits are explicit.

All526 Python tests, optimized/sanitized C714 and retained transport suites,
four Vitals Node adapters, GNOME adapters/parity and W=1 module build pass.
Coverage includes independent Rx/Tx/bandwidth-specific MCS maps, contiguous160
versus80+80, HE optional operations/6GHz/PPE, bounds/duplicates, source identities,
cache boot/age/trust, partial histograms, exact dBm bins and descriptive PCI/USB
names. Synthetic non-local cases are not physical qualification of other devices.

Installed0.53.0 native/CLI/C agree for all seven changed APIs; three explicit
threshold calls retain scalar counts. Independent current supplicant capability
extraction confirms HE160, four streams, MCS11 and the separately calculated
4803.922 Mbit/s ceiling at0.8us GI. This is advertised AP capability metadata,
not this laptop's negotiated speed or throughput. Kernel peer headers report
HE association. Local card descriptions are available separately from drivers.
Existing cached APs provide real dBm, observation ages and known zero6GHz count;
no new radio scan or configuration is used.

The separate root collector works with no capabilities, no IP address families,
IPAddressDeny=any, read-only system/home and only the parsed metrics directory
writable. The existing private-network NVMe collector is preserved. Public
readers verify association generation and reject caches older than45 seconds.
Installed source/runtime equality, root ownership and existing-MOK CMS pass.

Full230 read calls retain194 values/36 typed unavailable,208 user/22 root;
no availability/errno changes. The three RSSI reads now use the unprivileged
public cache. All22 mutation/config writes are excluded. Retained native SBS,
actual charger input ADC and five NTCs pass. Fresh GJS loads actual installed
Sensors/Values and verifies188 rows:45 Network plus retained123 Battery,
7 Processor and13 Storage, including all12 SBS. Installer readback/idempotence
passes. Running Shell needs ordinary login to load new JavaScript.

Fan automatic control, owner100% charge limit, profile/keyboard and four UEFI
hashes remain unchanged. Session activation, nonzero battery-flow, absent
peripherals, unsupported firmware payloads, meter accuracy, enabled Secure Boot,
cold boot and physical suspend/resume remain unqualified. This release closes
seven source-confirmed software gaps; full-goal completion is not asserted.

# Qualification: 0.52.0, 2026-11-01

Original network-type helper9e2a0 and Bluetooth shared helper941d0 were reviewed,
including the Bluetooth class switch's indirect jump table. Native physical type
selection corrects the prior generic interface-up list, which mixed tunnels with
Ethernet and omitted cellular identity/priority. Source preference is Ethernet,
WWANPP2, Wi-Fi; native cellular is generic and explicitly does not assert3GPP2.
The modem-capability provider excludes analog POTS, requires verified cellular
bits (including5GNR0x40) and leaves missing/mixed/unknown families unclassified.
Only the capability property is requested, not APN/operator/device identifiers.
Known virtual types stay outside scope even when a backing device link exists.

Nineteen new tests cover physical/virtual/WWAN data-interface mapping, preference,
partial or unknown types, carrier/admin state, races, owner identity, provider
absence/denial/malformed data/deadline, analog/cellular capabilities, all recovered
Bluetooth major classes and absent/invalid class. BlueZ optional class metadata
is independent of known connection count; the unique daemon owner is rechecked.
All500 Python tests, retained optimized/sanitized C714 and other transport suites,
Node/parity and local W=1 kernel build pass. Signed installed0.52.0 has exact
source/runtime content, root ownership and a verified existing-MOK CMS signature.

All four network/Bluetooth APIs pass native/CLI/C and reject extra arguments.
The current physical Wi-Fi path agrees with independent ip ifindex/link flags
and nmcli device type/state. Live BlueZ connected count is0, independently read;
positive Bluetooth major-class, Ethernet preference and cellular examples are
fixture-qualified, not physical positive results. No daemon activation, scan,
pairing, route/connection/profile change or traffic generation is used.

Full230 read calls retain194 values/36 typed unavailable outcomes,205 user/25
root, with no availability/errno change from0.51.0;22 writes remain excluded.
Native SBS, input ADC/five NTCs and actual GJS143/all12 SBS remain available.
Fan firmware-auto, owner100% charge threshold, profile/keyboard and four UEFI
hashes are preserved. Existing session, power-flow, peripheral, boot and source-
evidence limits remain open. Indexing98 older source bodies is not proof that
those98 ledger entries are missing implementations or newly complete.

---

# Qualification: 0.51.0, 2026-11-01

The grouped source review covers all60 remaining whole-snapshot field routes,
including exception-fragment fallthrough for the14-byte chip buffer and fan
array helper. All60 now have dedicated providers and source-specific evidence.
Nineteen new Python tests cover independent providers, source quantities, signed
boundaries, flags/family/date/percentage/indices, support/denial and cache errors.
All481 Python tests and retained Node/parity checks pass. Optimized and sanitized
core builds pass714 assertions, including every cache-request failure boundary,
no publication of partial data, version/status/timeout/busy/readiness gates,
changed payload/state and bounded polling. Other transport suites remain passing.
Local W=1 kernel build and signed installed source/runtime/root ownership pass;
the module CMS signature verifies with the existing MOK certificate.

Native, CLI and C interfaces qualify all60 contracts:58 return values, while the
original battery-information and cached-PF paths reject the firmware's existing
cache error bit6 with EIO. The same error existed before installation (status7f),
and the collector does not bypass it or send refresh requests from that state.
The14-byte chip buffer is complete and its four-byte prefix matches the packed
chip-name value; numeric familyffff is distinct from ASCII firmware01. Battery
charge-counter quantities, date, percentage bucket and EC flags agree with their
independent sources. Dynamic samples are checked as samples, not falsely claimed
byte-identical. Missing positive firmware cache data remains an explicit limit.

A bounded full-speed test passes ten fan/profile/charge/RAPL getters and CLI show
while EC telemetry correctly reports EBUSY. Low-RPM checks stay active, child
finally restores automatic mode and the independent parent restores/readbacks it
again. No profile, charge threshold, keyboard or four UEFI records change.
Native SBS, charger input ADC, five NTCs and actual GJS143 rows/all12 SBS pass.
Full230 read-only calls yield194 values/36 typed unavailable results,205 user/25
root. Only the two source-correct firmware-cache failures change availability
from0.50.1;22 mutation/config writes remain excluded. Firmware automatic fan and
owner100% charge threshold are preserved.

Current code and this hardware's available measurements do not prove all physical
qualifications. Actual owner Shell bridge/logical NumLock, meaningful nonzero
battery-flow transition, absent peripheral positives, fold/suspend/cold boot and
enabled Secure Boot remain unresolved. OEM battery-region Celsius settings,
ambiguous balancing maxima and remaining raw bytes are not guessed. Firmware
bank6/EEPROM/protocol-gated absences remain explicit, not missing decoder values.

---

# Qualification: 0.50.1, 2026-11-01

Nine original inventory export bodies confirm exact baseboard/system/BIOS/CPU/
GPU/OS selections. Corrected family/baseboard aliases, manufacturer provenance,
processor name, graphics captions and distribution/architecture/version content.
Dedicated read-only providers replace unrelated whole-sensor snapshots. Native
sources/units remain explicit; placeholders, dates, fields, races and partial
providers are validated. GetUWPVersion labels bundled bridge4 separately from
actual session discovery. The unpublished installed0.50.0 intermediate passed all
nine API/CLI/C/source-reference checks and is retained unchanged for recovery.

The wider getter audit found four older battery-wrapper defects: numeric BB10
chip ID was mapped to the ASCII name, ASOC fraction to a rounded percentage,
remaining Capacity to full capacity, and four CellVoltage outputs to only cell1.
Reviewed complete original function/helper spans and official BATTERY_INFORMATION/
STATUS field offsets. Corrected native providers preserve valid zero, same-unit
full/design fraction, explicitly labelled remaining mAh and all four raw channels
with independent measured-value availability. No energy estimate, guessed cell
count, percent clamp or new firmware recipe is introduced.

Fifteen inventory tests and eight battery-wrapper tests add strict source-selection,
quote/escape/nonexecution/precedence, file/device identity, local PCI parsing,
metadata/error handling, fraction/remaining/zero units and four-channel partial
coverage checks. All462 Python tests, retained optimized/sanitized C/Node/parity
checks and local W=1 build pass. Signed installed0.50.1 source/runtime/root ownership
and existing-MOK CMS verify. Nine identity APIs plus bundled version metadata pass
native/CLI/C and independent dmidecode/lscpu/PCI/uname/os-release checks. Four battery
summary APIs pass native/CLI/C with direct Linux charge counters and cached chip/
cell references; dynamic cell values use their own samples. Numeric chip ID0,
unrounded full/design fraction, remaining mAh and all four channel states agree.

Retained37 hardware/config/process/inventory contracts plus fourteen metadata APIs,
five memory APIs, C NVMe, native SBS, input ADC/five NTCs and isolated actual GJS/
D-Bus bridge4 pass. The native owner session still uses partial AT-SPI; actual Shell
bridge4 activation/logical NumLock remain pending a normal login. Full230 read-only
calls retain196 values/34 expected typed unavailable outcomes (207 user/23 root),
with no status/errno changes from0.49. Twenty-two mutation/config writes remain
excluded. Actual GJS143 rows/all12SBS pass. E5 makes zero firmware calls with one
guard rejection. Firmware-auto, profile/charge/keyboard and four UEFI hashes remain
preserved. The broader native-port objective is incomplete: the remaining60 direct
field routes and external physical/source requirements need their completion audit.
A successful read alone does not prove every original field/variant.

# Qualification: 0.49.0, 2026-10-31

Reviewed fourteen original CPU/platform/window contracts, including the CPUID
export beyond its initial exception fragment, original driver instruction and
full chassis switch/byte table. Corrected fraction/percent units, raw CPUID,
first CPU model string, numeric architecture, exact OEM array index4, firmware
identity sources, fixed USB reader identity, physical-adapter MAC selection and
local-calendar formatting. Native schemas document platform counterparts.

All439 Python tests and retained optimized/sanitized C, Node and252-name parity
checks pass. New tests cover strict CPUID arguments/vendor registers/NULL errors,
load intervals and invalid frames, OEM framing/count/revisions/selection, UUID/
placeholder errors, chassis mappings, USB positive/partial/negative selection,
MAC software exclusion/identity changes, window schema/title privacy/stack,
existing unique-owner D-Bus routes, unavailable providers, PID metrics including
idle/shared/new/reused/denied cases, and atomic C-library replacement preserving
existing open inodes. Root read-only probe independently compares UUID/system/
board serial with dmidecode and exact fifth OEM string with the full cached DMI
table, in RAM with only hashes/counts retained. Actual chassis31 is Notebook;
selected USB reader is completely absent and device-backed MAC census is complete.

Local W=1 module build passes. Installed signed0.49 source/runtime contents and
root ownership match; the existing MOK CMS verifies. All14 metadata contracts
pass native/CLI/C checks (dynamic load/time use their own intervals). Actual
existing AT-SPI exposes seven windows, zero enumeration errors, all CPU/RSS
available and no requested/read/returned titles; compositor fields remain unknown.
The isolated actual GJS/D-Bus bridge4 passes native/CLI/C stack/focus/title opt-in
and real server-PID counters, plus logical NumLock false/true. Bridge files are
staged with backup/readback; enabled/disabled preferences are preserved. This
software fixture does not establish actual owner GNOME bridge activation.

Retained26 hardware, three display/audio, two process and six software-inventory
native/CLI/C checks pass, plus five memory APIs, C NVMe, native SBS, input ADC/five
NTCs and actual GJS143 rows/all12SBS. Full230 read-only audit retains196 values/
34 expected typed unavailable outcomes,207 user/23 root, with no status/errno
changes from0.48. Twenty-two mutations/config writes remain excluded from this
read audit. E5 makes zero firmware calls with one guard rejection. Firmware-auto,
profile/charge/keyboard and four UEFI hashes are preserved. Normal-login/nonzero-
power and absent peripheral/firmware/boot qualifications remain open; no factory
writes are run for coverage. Full objective completion still requires its audit.

# Qualification: 0.48.0, 2026-10-31

Reviewed original six inventory exports: native/WOW6432 uninstall roots, machine/
user helpers, DisplayName/Version/SystemComponent and AppxAllUserStore package
registrations. Corrected native held-package omission, hardcoded ABI lists,
64-only assignment of architecture-independent packages, omitted Flatpak runtime/
extension records and swallowed Flatpak/Snap failures. Native registered-package
categories include components; no Windows uninstall visibility or arbitrary manual
application classification is inferred.

Eighteen new tests cover present/removed/partial/held-state queries, ABI32/x32/
s390x/all/unknown, malformed/bounded records, missing/timeout/encoding/tool errors,
Flatpak scope/runtime/extension flags and optional versions, partial/genuine-empty
providers, Snap revisions/version spaces/malformed identities, manifest declared/
default architectures and identity/race/safe-YAML failures. An actual local Unix
HTTP fixture verifies the fixed read-only GET/v2/snaps?select=all request without
authorization/store-search endpoints. A source-verified snapd2.77.1 omitted/empty
architecture format default is labelled all, without a host-ISA fallback.
All404 Python tests, retained optimized/sanitized C/Node/parity and local W=1
module build pass. Signed installed0.48 passes all six new native/CLI/C contract
comparisons, including the larger native report. Direct dpkg, complete Flatpak
refs and snap list --all independently agree. ABI32 is a known-empty selection;
architecture-independent registrations remain separate. Flatpak extensions and
Snap retained revisions are included; missing Flatpak versions remain unavailable
and all installed Snap architectures are declared or source-defaulted correctly.
The qualified DB has no held records; held-selection behavior is fixture-covered.
Snap CLI row order changed during the first reference comparison; a direct study
proved identical sorted row content. Corrected semantic-order comparison passes;
this private verifier correction changes no installed runtime/source bytes.

Thirty-one retained native/CLI/C contracts pass, with process values evaluated
within their own sampling intervals. Source/runtime ownership and exact hashes,
existing-MOK CMS, five memory APIs, C NVMe temperature, native SBS, input ADC/five
NTCs and actual GJS143/all12SBS pass. Auto/profile/charge/keyboard/four UEFI hashes
preserved. E5 remains guarded before WMI (zero firmware calls/one rejection).
Fresh230 read-only calls retain196 values/34 expected typed unavailable outcomes,
with no status/errno changes from0.47.1 (207 user/23 root;22 mutation/config writes
excluded). This is not every field/variant, physical absent-device or factory-write
proof. Full goal remains active:14 generic OS-provider source contracts and the
existing owner-controlled session/power/device/boot qualifications remain open.

# Qualification: 0.47.1, 2026-10-31

Original CPU/memory workers and leaf comparators confirm Name/IDProcess/
PercentProcessorTime/WorkingSet, nonzero PID, descending positive CPU/RSS and
limits5/10. Eight bounded scalar cases validate exact comparator instructions.
The source's /10 presentation factor and signed32-bit WorkingSet conversion are
not native physical scales; native CPU uses one CPU100% and RSS bytes retain
integer precision. Empty/small vectors are safe. Windows execution is not tested.

New native stat/statm reader samples every visible PID, without UID filtering,
psutil name expansion, command-line/environment access or global CPU cache. PID/
start-tick identity guards replacement both across samples and around statm.
CPU deltas use user+system ticks and per-process measured monotonic intervals;
invalid/regressed/short/uncertain values stay unavailable. Valid zero remains0.
CPU/memory errors are independent, rank incompleteness is explicit, error details
are bounded with total/truncation counts, and dynamic/new/exited PID coverage is
reported. RSS is kernel statm resident pages, not private/unique memory.

The unpublished immutable0.47.0 intermediate exposed a source mismatch during
independent procps validation: PID1 stat RSS differed from statm/procps despite
stable records.0.47.1 uses statm with surrounding stat identity checks and keeps
valid CPU if memory is denied. Seventeen new regression tests cover sorting,
limits, both counters, units/values above100%, privacy, names/encoding, PID churn/reuse,
invalid/partial/bounded errors, read uncertainty and statm selection/bracketing.
All386 Python tests and retained optimized/sanitized C/Node/parity suites pass;
local W=1 module build passes. Final signed installed0.47.1 passes two new
native/CLI/C contracts, with per-result CPU delta formula, RSS units, rank order,
positive filters/limits and incomplete-census metadata checked. Their measured
values come from different intervals and are not claimed equal. Native samples
see PID1 without elevation; independently parsed stable procps RSS agrees.
Three retained brightness/volume contracts and26 hardware native/CLI/C contracts,
five memory APIs, C NVMe temperature, exact root-owned source/runtime and existing
MOK CMS pass. Native SBS, input ADC/five NTCs and actual GJS143/all12SBS remain.
Auto/profile/charge/keyboard/four UEFI hashes preserved. E5 still rejects before
WMI, firmware calls0/guard rejection1; no positive physical table is claimed.

A fresh installed230-call read-only audit (207 user/23 root) returns196 values/
34 expected typed unavailable outcomes, with no status/errno changes from0.44.1
(95x22/61x8/19x4). The two process payloads deliberately change from an unranked
array to the documented native report.22 mutation/config writes were excluded.
This is route/outcome coverage, not every field/variant or absent-device proof.
Full goal remains active; owner login/nonzero power questions and remaining OS
provider semantic/device/boot qualifications remain separate.

# Qualification: 0.46.0, 2026-10-31

Recovered AppList_HardwareConfig's actual CurrentBrightness/default-render-audio
contract from the original helpers. Endpoint GUIDs and public Microsoft SDK
vtable order identify scalar level/mute; source multiplies by100/truncates and
reports0 when muted. Native API preserves per-backlight kernel actual/max and
PipeWire configured/muted/effective levels, with independent availability and
per-device errors. An audio error cannot hide a valid backlight and vice versa.
No process inventory is read. Software amplification is retained; no claim of
sound pressure or identical Windows/Linux audio curves is made. Empty arguments
are required before provider access. Shared standalone volume reader rejects
malformed replies and maps missing tool/timeouts to typed unavailable errors.
Eight new regression tests cover zero/mute/gain, invalid numeric/token forms,
missing/timeout/error, partial/empty providers and argument rejection. All369
Python tests, retained optimized/sanitized C/Node/parity suites pass.

The EEPROM1024-byte padded request now allocates only after its firmware gate,
with ENOMEM before any firmware-call count. Input frees immediately after WMI,
including failure. This removes the preexisting1072-byte stack-frame warning
without changing its fixed selectors, zero padding, reply rules or guard.
Final local W=1 build removes the stack-frame warning. Signed installed0.46
passes three targeted native/CLI/C contracts, cross-checked against direct sysfs
and wpctl reads bracketed by unchanged display/audio settings (1.5%/94%).
Twenty-six retained API/CLI/C contracts, five memory APIs, C NVMe temperature,
exact root-owned runtime/kernel and existing-MOK CMS verification pass. Native
SBS, input ADC, five NTCs and actual GJS143/all12SBS remain available. E5 guard
still rejects before WMI (zero firmware calls, one rejection), and the cached
live DSDT matches source. Auto/profile/charge/keyboard/four UEFI hashes preserved.
These are native software/provider checks, not physical audio calibration,
positive EEPROM data, absent-peripheral or boot/suspend qualification. The full
goal remains active; original AppList CPU/memory counter selection still needs
semantic review. Owner login and nonzero-power questions remain pending.

# Qualification: 0.45.1, 2026-10-31

Corrected kernel-header portability after the first0.45.0 CI run. Its userspace
job passed, but Linux6.8 keeps ASUS_WMI_MGMT_GUID private while local7.0 exports
the macro in a public header. A verified GUID fallback under ifndef now builds
on both kernels; no method, device or model support is expanded. Both code-fix
CI jobs pass, and all361 Python/retained C/Node/parity checks plus the local W=1
module build pass. Installed0.45.0 sources/runtime remain unchanged for rollback.
The native EEPROM feature qualification below retains its original scopes.

Installed signed 0.45.1 passes all 26 retained native/CLI/C contracts, five memory APIs, native SBS/input ADC/five NTCs, exact source ownership and MOK CMS verification. The final GJS run exports 143 rows and all 12 SBS values. Fixed E5 rejection leaves actual firmware calls at zero, with one guard rejection. Three synthetic C/API cases cover v7, v8 and 64 maximum frames; positive physical tables remain unqualified. Automatic fan control, profile, charge limit, keyboard and four UEFI hashes are preserved.

# Qualification: 0.45.0, 2026-10-31

Recovered the omitted EEPROM E5 buffered path and checked the actual Windows
adapter. Read-only ntfscat extraction of the exact installed package supplies
AsusWmiAcpi.sys: IOCTL22240c routes through its request handler to IoWMIOpenBlock/
IoWMIExecuteMethod on the ASUS management GUID, pads input to1024 zeroed bytes,
and rejects a four-byteFE reply. No NTFS mount/journal write or Windows execution.
The Linux fixed GUID/method transport matches this source route.

- Bounded traces of original instructions exercise six magic/length scenarios
  and three two-consecutive-failure loop scenarios. The source consumes9+byte6
  bytes with5a/a5 magic and uses a caller output-budget factor0.7. Native bounds
  validate actual reply size rather than reproduce its unsafe256-byte temporary
  copy for declared257..264-byte frames. Remaining event fields stay opaque.
- Native scalar table collection handles version/date/common/BU selectors,
  version>7 BU presence, local calendar dates and selector-specific all-ones
  values. Date/count sentinel handling is distinct from valid raw register words;
  the kernel no longer rejects a successful all-ones EEPROM data word globally.
  Existing firmware error statuses remain errors. Changed versions and invalid/
  oversized counts abort before publishing partial register lists.
- Only explicit supported-table calls collect frames under privilege/collection
  locking. Metrics/cache never collect or advance the stream. A fixed root RPC
  accepts only DEVS60059/E5 with zero value/flags, exact padded input and bounded
  ACPI_BUFFER replies. A successful probe-time version is mandatory; older modules
  without buffer ABI1 cannot start collection. Cached module-local counters expose
  actual firmware calls versus guard rejections without making a new query.
- Two unusable replies stop event collection; a valid reply resets that count.
  Errors and complete frames are retained separately,64-record truncation is
  explicit, and complete history/checksums/temperature/unit meanings are not
  inferred. No EEPROM write, cursor reset or event-clear command is added.
- Seventeen new Python tests cover framing, old/new version selectors, failure/
  partial/budget behavior, changed version/counts, timezone/sentinel semantics,
  privilege/no-I/O gates, transport ABI and optional support metadata. All361
  Python tests, retained C/Node/parity suites and W=1 module build pass. Optimized
  and sanitized C core suites each pass554 checks, including seventeen new frame/
  selector/status checks. Positive physical table behavior remains unqualified.

Installed signed0.45 passes26 retained native/CLI/C contracts, exact root-owned
runtime/kernel and existing-MOK CMS verification, five memory APIs, C NVMe temp,
native SBS/input ADC/five NTCs and actual GJS143/all12SBS. The loaded kernel rejects
RPC13 before WMI: firmware-call counter remains0, guard-rejection delta1. Three
private synthetic C-transport/actual installed API collector cases cover versions7,
8 and64 maximum264-byte frames (41,854-byte JSON), with zero hardware I/O. These
are synthetic endpoints, not positive physical table proof. Vitals test first
failed on a stale private output path; corrected-path rerun exits0. Sensor files
and favorites unchanged. Automatic fan/settings/four UEFI hashes preserved.

Known remaining software gap: AppList_HardwareConfig source publishes monitor
brightness and default volume, while the current native route returns CPU/memory/
processes. That row's older metadata parity label is not completion evidence.
Correcting this original contract is the next task; full goal remains incomplete.

Installed qualification is recorded privately in eeprom-stream-port. Current
firmware still returns unsupportedFE for the version: no positive EEPROM contents
or physical E5 reading is claimed. Full goal remains active pending the broader
completion audit and required external-state qualifications.

# Qualification: 0.44.1, 2026-10-31

Final publication includes the0.44 firmware-query changes below plus two storage
dispatch fixes discovered by a fresh full230-call installed read audit. The local
immutable0.44.0 intermediate was not published or overwritten. Its audit gave
194 values,34 typed unavailable results and two unexpected KeyErrors for
WMIGetHDDCaption/Info, exposing omitted routes from0.40's dispatcher refactor.

Original source literals distinguish Caption's Win32_DiskDrive fixed-media query
(including SSDs) from Info's MSFT_PhysicalDisk MediaType3 query (rotating disks).
Both now use the cached kernel storage provider with those separate selections,
strict empty arguments and typed field errors. Two regression tests cover public
dispatch, media selection, partial fields and validation before access. All344
Python tests, retained optimized/sanitized C/four Node/252parity/W=1 pass.

Final installed0.44.1 passes26 targeted native/CLI/C contracts, including both
storage results cross-checked against independent lsblk selections. The full
230-call read-only re-audit gives196 values/34 expected typed unavailable results,
zero unexpected errors (207 user/23 root). These are route/availability checks;
22 mutation/configuration operations were excluded, and this does not prove every
payload variant or positive absent-peripheral behavior. Root-owned runtime/kernel
source, existing-MOK CMS, five memory APIs and C NVMe temperature pass. Native SBS,
input ADC, five NTCs and GJS143/all12 SBS retained; settings/four UEFI hashes preserved.

# Qualification: 0.44.0, 2026-10-31

EEPROM source review corrects an earlier method-domain error: both direct zero
branches for0x60059 are DSTS support queries. The original API's read-version
uses DEVS0x60059/selector0xe0 through helperRVA3a570. The DEVS branch has a
conditional WCHK/SMM fallback, not a direct-zero EEPROM implementation. A fresh
root read of the live DSDT matches the cached source exactly (length/checksum/
SHA256 verified). The fixed original version query returns status-ENODEV19 with
raw0xfffffffe, the recognized firmware unsupported-method result. p_sensor is
separately DSTS0x60068 and returns a valid zero mask. The fixed probe preserves
automatic fan ownership and does not enumerate EEPROM registers or write them.
Static ASL alone is not claimed to prove SMM support absence.

- The module now caches these three fixed query replies during probe. Public
  firmware_diagnostics reads only those cached structures: exact recipes,
  statuses, raw values and raw-valid flags. No refresh/control/raw-query entry
  point is exposed. Replies are explicitly module-probe capability snapshots.
- Two original APIs use the qualified public provider without root or RPC on
  each read: a valid raw p_sensor mask, and typed EEPROM-table unavailability.
  Provider/transport/invalid-schema failures differ from the recognized firmware
  unsupported result. A newly responding table remains unqualified until its
  layout is verified; no version/date/array is invented from a support-mask zero.
  The old unreachable EEPROM decoder with its unqualified Unix-date assumption
  was removed; the original fixed selector allowlist remains recovered.
- firmware-storage retains BIOS/CMOS inventory without reading contents and
  reports unknown table availability when its separate diagnostic provider fails.
  metrics.firmware_diagnostics carries the typed status rather than an unconditional
  EEPROM-absent string. Existing sensor/power/PD availability providers are retained.
- Twelve new Python tests cover no-root/no-RPC dispatch, valid zero/nonzero mask,
  sentinel versus support query/transport errors, exact recipe/schema/scalar
  validation, unknown table support, argument checks, and shared EC identity/
  ownership/JSON bounds. All342 Python tests, retained optimized/sanitized C,
  four Node suites,252-name parity and W=1 module build pass.

Installed qualification is recorded in the private firmware-query-port audit.
This provides no raw EEPROM contents or another-model/table layout qualification.

# Qualification: 0.43.0, 2026-10-31

The complete cached qualified EC firmware DD dispatcher has cases1..5 and81..85;
its default is a return without a response. A bounded private scalar model steps
command-length setup and all three payload stages. Eighteen scenarios cover
implemented read/write route controls and silent banks0/6/7/12/86/87. BB50/51
identity controls return15/2. Positive route controls stop before bank handlers;
these are source proofs, not new physical measurements or Windows execution.
No new flash/EC/PD/BMS request was used for this source review.

- Qualified module IO now has max_dd_bank5. The transport rejects absent-bank
  requests before any port access, including legacy bank6/7 mutations. Original
  protocol fixtures still cover their recovered recipes independently. Fifty-four
  additional optimized/sanitized C checks verify no-I/O rejection, telemetry
  support-mask coverage, no false failure latch and retained thermistor selection.
- Telemetry skips unsupported bank6 and adds unsupported_mask/max_dd_bank,
  separate from failed-read unavailable_mask. Ten original read APIs now report
  EOPNOTSUPP through an exact native identity/ownership provider. Transport,
  stale-module and contradictory metadata errors retain their own errno.
- Eight new Python tests cover public no-root/no-RPC dispatch, absent support
  versus timed-out probe, schema/conflict failures, transport/identity errors,
  legacy-device presence, rating-report agreement and validation before I/O.
  All330 Python tests, retained optimized/sanitized C/four Node suites,252-name
  parity and W=1 module build pass.

Installed signed0.43 qualification passes: all ten diagnostic read APIs return95
through native/CLI/C without root; three ratings and nine specialty roles retain
their expected95/61. Metrics support/config reports agree with direct telemetry;
bank6 has unsupported bits and no failed configuration latch. A root-only fixed
bank6 read is rejected95 by the loaded kernel. Exact root-owned runtime/kernel
source and existing-MOK CMS verification pass. Five memory APIs retain independent
SMBIOS/dmidecode agreement; native SBS and C NVMe temperature remain available.
Input ADC, five NTCs and actual GJS143/all12 SBS pass. Automatic fan, owner profile,
charge limit, keyboard backlight and four UEFI hashes are preserved. Vitals files
and preferences were not changed; owner GNOME bridge activation remains pending.

The bank6 support gap is closed for UP3404VA.301. This does not add bank6 hardware,
substitute other metrics for original fields, qualify another firmware, or prove
positive absent-peripheral behavior. Installed qualification is recorded privately.

# Qualification: 0.42.1, 2026-10-31

Installed signed DKMS/runtime0.42.1 on the qualified UP3404VA.301.

- Recovered full spans for all three rating exports (including compiler-split
  unwind regions). The original x86 path requires HealthyTable>=28 and absent
  ASUS1000, reading bank12 byte pairs1/0,3/2,5/4. Its DSTS0x1200f2 alternatives
  are behind the ARM64 branch. Bounded original-instruction traces show15/27
  return0xffffffff without transfer,28 reaches the EC reader, legacy presence
  blocks it, and only the ARM scenario reaches WMI. No transfer/PE native code
  or Windows API is executed by these private scalar traces.
- The old native provider tried ARM WMI on x86. Corrected three routes now use
  public exact native identity and return EOPNOTSUPP for protocol15 without a
  rating request or root authentication. Source-specific rating meanings are
  kept separate from measured input draw, EC adapter watts and negotiated PDO
  limits. No nominal65W or ADC result is substituted for an unavailable rating.
- Shared qualified_ec identity/ownership/census adapter preserves specialty
  thermal behavior. Eight new tests cover public dispatch/no RPC, distinct
  legacy/architecture/protocol gates, transport failures, no fallback values,
  raw zero/nonzero config, inconsistent/invalid data and validation before I/O.
  All322 Python tests, retained optimized/sanitized C/four Node suites,252-name
  parity and W=1 module build pass.
- Three installed native/CLI/C rating queries give95; retained nine specialty
  queries retain expected95/61 behavior. CLI metrics.adapter_capabilities agrees
  with direct telemetry: protocol15 and latched bank6 configuration unavailability.
  Five board NTCs and direct charger-input ADC remain available. The diagnostic
  report reads normal telemetry/quarantine; it adds no dedicated bank6 probe or
  support-absence claim. Normal kernel refresh/reprobe policy remains unchanged.
- Exact root-owned runtime/kernel source and existing-MOK CMS pass. Retained
  native SBS, five memory APIs and C disk-temperature queries pass. Auto fan,
  owner profile/charge cap/keyboard backlight and four UEFI hashes are preserved.
  Actual GJS Sensors/Values retains143 rows/all12 SBS; Vitals files are unchanged.
  Kernel change is only version metadata; no bank12 allowlist, firmware setting,
  controller command or higher-protocol/ARM qualification is added.

Full goal remains active/incomplete. Protocol28 and ARM are source-trace positive
controls, not qualified native hardware here. Static bank6 producer/support and
remaining controller-field semantics still need source evidence. Earlier full
read-only0.32 and targeted0.40/0.41 proofs retain their scopes; normal owner GNOME
login and meaningful nonzero-flow requests remain pending without new prompts.

# Qualification: 0.41.0, 2026-10-31

Installed signed DKMS/runtime0.41.0 on the qualified UP3404VA.301.

- Recovered original EcFwRev and EcChipId helpers and architecture guard. Native
  raw vendor2 has no high bit, selecting the original uncached familyffff; eight
  specialty getters return unsupported zero. Raw firmware bytes remain ASCII01.
  A private bounded scalar trace of original export instructions confirms eight
  zero returns and the distinct GPU TS1L fallback. Family3031 gives nine zero
  returns; supported-family3032 positive controls reach a real getter in all nine.
  No Windows API, PE native execution or firmware operation is performed by that
  trace. Windows registry-cache overrides are explicitly outside native scope.
- GPU TS1L's familyffff fallback requires ASUS1000 absence and HealthyTable
  support, then reads DD02/03/00. This is the existing EC GPU channel already
  sampled/mapped by the kernel; the old substring route did not connect it to the
  original API. Current raw0 remains ENODATA under the existing hwmon range policy.
  Other eight roles now give EOPNOTSUPP with a source-backed availability report.
  No ACFET/choke/connector/VRAM/VRM/upper-CPU placement is inferred from a board NTC.
- Thirteen new tests cover a valid64C channel distinct from99C CPU, eight original
  unsupported sentinels, zero/out-of-range/malformed data, transport failures,
  unknown identity/model/BIOS/architecture, legacy-interface presence/census changes,
  manual ownership/transition, bounded framing and arguments before I/O. All314
  Python tests, retained optimized/sanitized C/four Node suites,252-name parity and
  W=1 module build pass. Positive real TS1L temperatures remain unperformed.
- All nine installed native/CLI/C endpoints agree with expected errno behavior;
  metrics.specialty_temperatures agrees with direct telemetry and five board NTCs
  remain available. Same-user GNOME bridge is still unavailable; the existing
  normal-login request remains pending. No repeated prompt or forced logout.
- Exact root-owned runtime/kernel source and existing-MOK CMS pass; retained native
  SBS, five memory APIs and C temperature checks pass. Auto fan/profile/charge cap,
  keyboard backlight and four UEFI hashes remain unchanged. Kernel change is only
  version metadata. Actual GJS Sensors/Values still returns143 rows/all12 SBS.
  No CC/CE/E4 request, new register/allowlist, channel enable or
  firmware setting was added; existing telemetry and fan-mode reads are reused.

Full goal remains active/incomplete. The nine targeted native availability contracts
are distinct from proving a new physical measurement or full252-export completion.
Earlier0.32 full read-only and0.40 storage proof retain their original scopes.

# Qualification: 0.40.0, 2026-10-31

Installed signed DKMS/runtime0.40.0 on the qualified UP3404VA.301.

- Original query/helper recovery distinguishes rotating HDD list/model, all-fixed
  capacity, non-rotating fixed SSD list/model and physical-disk classes. SD caption
  intentionally queries generic removable media; its size helper separately checks
  SD CARD/SDHC CARD/SDXC CARD captions. Native explicit MMC SD/SDcombo type augments
  that selector; MMC/eMMC and boot/RPMB subareas are not guessed from mmcblk names.
  These are labelled Linux kernel classifications, not independent physical-media
  measurements. Inventory reads cached sysfs only, without block-device/SMART/
  filesystem/serial reads or control commands.
- Twenty new tests cover distinct media selectors, SD/eMMC/native non-removable SD,
  zero sectors,512-byte units despite4K logical sectors, virtual/partition/subarea
  exclusion, optical SCSI types, malformed/unknown/partial fields, stale identity,
  duplicate dev_t, hotplug, strict arguments and mount-tree disagreements. All301
  Python tests, retained optimized/sanitized C and four Node suites,252-name parity
  and W=1 build passed.
- The recovered HDD usage query selects MediaType3, then disk/partition/volume
  Size/SizeRemaining; filesystem capacity semantics were right, the all-drive HDD
  selection was wrong. It now follows rotating disks. Both usage providers require
  current kernel classification and lsblk parent metadata to agree, retaining
  existing per-filesystem failure/unmounted rows. Samples remain sequential.
- Earlier live source checks found one external rotating HDD, one NVMe and an
  empty removable reader, all matching independent lsblk fields. Old HDD list/model
  included all3; the new selector returned1. The external HDD subsequently left
  the kernel census. Final installed native/CLI/C agree for all8 inventory names
  and both usage APIs on the current2-node census:1 NVMe and1 removable reader,
  no rotating HDD. Direct lsblk classification/capacity and statvfs totals for2
  SSD filesystems agree. Positive inserted SD/eMMC cases remain fixture-only;
  final HDD usage with a connected disk was not physically repeated.
- Exact root-owned runtime/kernel source and existing-MOK CMS pass; retained native
  SBS, five memory APIs and C storage-temperature queries pass. Actual GJS
  Sensors/Values retains143 rows/all12SBS. Auto fan, owner profile, charge cap,
  keyboard backlight and four UEFI hashes remain unchanged.

An immutable local0.39 intermediate qualified the inventory source/runtime before
HDD-usage source recovery; it was not published. Final implementation is0.40.
Full goal remains active/incomplete. The earlier0.32 full read-only audit retains
its original scope; these targeted checks do not replace it. Normal GNOME login,
meaningful nonzero battery flow and other firmware/peripheral qualifications
remain pending without new prompts or idle capture restarts.

# Qualification: 0.38.0, 2026-10-31

Installed signed DKMS/runtime0.38.0 on the qualified UP3404VA.301.

- Original WMI literals prove that MemInfo and MemSize query physical-memory
  devices/capacity. Their old Linux mappings returned OS virtual-memory data.
  New Type17 provider returns firmware-declared installed bytes and module fields;
  normal OS-usable memory/usage inventory is unchanged. Live source comparison
  found16GiB installed versus16,360,939,520 OS-usable bytes, eight firmware memory
  device records,4800MT/s configured and6400MT/s maximum. All selected fields match
  independent dmidecode output. Firmware records do not establish removable modules
  or independently measured electrical/clock values.
- Thirteen new tests cover KiB/MiB/extended capacities, unknown/empty slots,
  malformed frames/strings/extended fields, optional metadata errors, duplicate
  handles, partial/unreadable data, census/record changes, strict arguments and
  privilege before I/O. Configured rate never substitutes maximum speed; modern
  SMBIOS transfer-rate units are labelledMT/s. All281 Python tests, retained
  optimized/sanitized C suites, four Node suites,252-name parity and W=1 build pass.
- All five installed original memory names agree across privileged native/CLI/C
  and the selected independent SMBIOS reference fields. All five unprivileged
  native/C calls returnEACCES; normal user CLI uses the existing configured
  authentication and returns the same values. The C library never elevates itself.
  No raw serial/asset-tag decoding, /dev/mem access, SPD transaction or new daemon.
- Exact root-owned runtime/kernel source and existing-MOK CMS verification pass.
  Retained native SBS and C storage-temperature queries pass. Actual GJS
  Sensors/Values retains143 rows/all12 SBS. Fan remains automatic; owner profile,
  charge cap, keyboard backlight and four UEFI hashes remain unchanged.

Full goal remains active/incomplete. These five corrected memory contracts do not
replace the earlier0.32 full read-only audit. Existing GNOME login and meaningful
nonzero battery-flow qualifications remain pending; no forced logout, new prompt
or idle capture restart. Other unavailable firmware/peripheral paths keep their
previous evidence and limitations.

# Qualification: 0.37.0, 2026-10-31

Installed signed DKMS/runtime0.37.0 on the qualified UP3404VA.301.

- Reproduced the old aggregate USB bug: an unclassified connection returned
  type_c=false and exact A/C count0. New queries retain unknown/null counts with
  coverage/observed metadata. Mandatory descriptor/address errors remain explicit
  rows and prevent exact device counts; optional metadata failures retain presence.
  Hubs remain excluded from USBNum/Port but are included in connection queries.
- Fourteen new tests cover partial/unclassified/invalid metadata, empty hubs,
  positive Type-C amid unknowns, optional errors, hotplug/identity changes, strict
  arguments, reciprocal peers, cross-controller rejection, conflicting labels,
  registered Type-C aliasing and identical identifiers on separate ports. Device
  IDs/names never merge devices or infer connector shape. All268 Python tests,
  retained optimized/sanitized C/Node/parity and W=1 module build passed.
- Installed ordinary-user native/CLI/C agree for all five original USB queries
  and an explicit Type-C hub selection. Direct sysfs non-hub census, reciprocal
  root-peer sets and native ACPI _UPC table agree:7 non-hub/9 total topology nodes,
  4 observed root ports/groups,1 Type-A and1 Type-C group. Active Type-C root has
  validated peer metadata; devices simultaneously attached to both speed halves
  and registered Type-C-link positives remain fixture-only qualifications.
  No power-only charger cable or physical peripheral connector identity is inferred.
- Installed root-owned runtime/kernel-source equality, existing-MOK CMS and retained
  native SBS/C storage/temperature checks passed. Kernel change is version metadata;
  hardware controls/allowlists remain. Auto fan, owner profile, charge cap, keyboard
  backlight and four UEFI hashes were preserved. No USB authorization, power,
  configuration, bind/unbind, reset, controller or event-payload request was used.

- Fresh actual GJS Sensors/Values after reload returned all143 rows/all12 SBS.
  Vitals helper/source/favorites were unchanged by this release.

Full goal remains active/incomplete. Earlier full230-export audit is retained0.32
proof. Changed USB contracts have targeted qualification, not a newly repeated
full-scope audit. Bridge3 normal-login request remains pending without a forced
logout or repeated prompt; logical desktop state is not inferred from LEDs.

# Qualification: 0.36.0, 2026-10-31

Installed signed DKMS/runtime0.36.0 and bridge3 on the qualified UP3404VA.301.

- Final target checking found the0.35 bridge2 caller used Shell Meta.Backend,
  which has no get_default_seat in installed Mutter18. Its synthetic transport
  tests did not prove the actual GNOME caller domain. Owner bridge was inactive;
  no activation was requested before correction.0.35 is superseded for this path.
- Bridge3 receives global.stage and resolves Stage.get_context -> Clutter.Context
  get_backend -> Clutter.Backend get_default_seat -> Seat.get_keymap -> keymap
  get_num_lock_state. Installed typelib checks prove each method exists and the
  wrong Meta.Backend seat getter does not. GNOME50.1 keyboardManager source uses
  the equivalent stage.context backend route. Tests now include missing stage/
  context/backend and the full adapter chain; client rejects old bridge2.
- All254 Python tests, all retained optimized/sanitized C/Node suites,252-name
  parity and W=1 module build passed. Actual isolated GJS/D-Bus false/true again
  passed through installed native/CLI/C with the corrected stage/context chain.
  Test fixture uses local GIO VFS and no unrelated service activation was observed.
  This qualifies the adapter/wire contract, not the owner's real session state.
- Real owner-session native/CLI/C still report ENODEV/null logical Num Lock,
  while hardware LED data remain separately available. Bridge3 installed with a
  private backup/readback and unchanged enabled=true/disabled=false preferences.
  Normal new login is still required for Shell discovery. No forced logout,
  unsafe evaluation, input-event stream, key contents or state toggle is used.
- Installed runtime/kernel-source equality, existing-MOK CMS verification, retained
  native SBS/C storage/temperature checks passed. Automatic fan, owner profile,
  charge cap, keyboard backlight and four UEFI hashes remained unchanged.

- Fresh actual GJS Sensors/Values after reload returned all143 rows/all12 SBS.
  Vitals files and favorites were unchanged.

Full goal remains active/incomplete. Real owner GNOME activation/state and other
remaining firmware/provider/physical qualifications are not proven by these tests.

# Qualification: 0.35.0, 2026-10-31

Installed signed DKMS/runtime0.35.0 on the qualified UP3404VA.301.

- Original Num Lock session semantics now have a fixed read-only GNOME bridge2
  getter. Primary num_lock is the logical seat-keymap toggle; hardware LED consensus
  and availability remain separate. No missing bridge becomes false or an LED
  substitute. Caller UID, pinned unique owner, version and Boolean type are checked,
  followed by an ownership recheck. Only an existing selected Unix session bus and
  existing bridge are queried, with2s call timeouts and no activation request.
- Six new/254 Python tests cover false/true, wrong types/versions/UID, owner changes,
  missing/access/timeout providers, missing bindings and autolaunch rejection.
  Strict JS getter tests verify one read, real false/true and unavailable/error
  cases. All retained optimized/sanitized C/Node suites,252-name parity and W=1
  module build passed. Kernel change is version metadata; hardware controls and
  qualified native SBS transport are retained.
- Actual GJS exports the real D-Bus interface and production getter on an isolated
  private session bus with controlled false/true backend values. Installed native,
  CLI and C paths agree for both, including session values that differ from actual
  LEDs. This is wire/schema qualification, not the owner's live GNOME state.
  Initial fixture startup autoactivated unrelated GVfs on its private bus and its
  FUSE attempt failed; corrected fixture uses GIO_USE_VFS=local and the clean
  repeat passed. Original log is retained; no production activation path was added.
- In the real owner session the bridge is still undiscovered/unowned. Installed
  native/CLI/C agree on explicit ENODEV/null logical state while readable LED data
  remains available. Bridge2 was installed with a private backup and exact readback;
  prior enabled=true/disabled=false settings were preserved. Installed GNOME50.1
  typelib has both getter methods, and its D-Bus source explicitly rejects reload.
  A normal login is required before real owner-session qualification. No logout,
  unsafe evaluation, input-event content, toggle or other state write was performed.
- Root-owned runtime/kernel-source equality and existing-MOK CMS signature passed.
  Native SBS and retained C storage/temperature checks passed. Firmware-auto fan,
  owner profile, charge cap, keyboard backlight and four UEFI hashes were preserved.

- Fresh actual GJS Sensors/Values after reload returned all143 rows/all12 SBS.
  Vitals files and favorites were unchanged by this release.

The full port remains active/incomplete. Owner GNOME activation and real logical
state are not qualified by the isolated bus or method-existence checks. Earlier
0.32/0.33/0.34 API and physical qualification limits remain retained evidence.

# Qualification: 0.34.0, 2026-10-31

Installed signed DKMS/runtime0.34.0 on the qualified UP3404VA.301.

- Reproduced old input/display failures using fixture metadata: an unreadable input
  device was omitted from the exact count, an invalid LED was discarded from Num
  Lock consensus and an unreadable external status became monitor count0. Current
  providers retain unknown/error states rather than those successful negatives.
- Eight input and eleven display regression tests cover partial/missing census,
  malformed bitmaps/binary LEDs, LED disagreement, changed identity/state/inventory,
  readable siblings, optional mode/EDID failures and all four original API routes.
  EDID header/checksum/version/manufacturer and model text are validated; bad
  identity cannot become a printed name. Valid base fields remain usable despite
  unparsed extensions. No raw EDID serial or input-event content is exposed.
- All248 Python tests, retained optimized/sanitized C/Node suites,252-name parity
  and W=1 module build passed. Kernel change is version metadata; native SBS and
  hardware controls/allowlists are unchanged. Two new root-owned metadata modules
  are included in the versioned installer runtime.
- Installed ordinary-user native/CLI/C calls agree for GetNum_Key and three display
  queries. Direct sysfs checks agree: three input event devices advertising both
  keys, consistent Num Lock LEDs, zero connected external DRM outputs and one
  internal output. The internal base EDID identity agrees with direct bytes; it
  has no monitor-name descriptor, so no textual model is invented. Positive external
  hardware transitions and desktop-session Num Lock are not qualified by this test.
  Counts/state are sequential observations, not a unique physical-keyboard count
  or an atomic multi-device snapshot. Unknown C API arguments fail with EINVAL.
- Retained native SBS and C filesystem/temperature queries passed. Installed runtime/
  kernel-source equality and existing-MOK CMS verification passed. Firmware-auto
  fan, owner profile, charge limit, keyboard backlight and four UEFI hashes stayed
  unchanged. No input event stream, DDC/modeset or device/state write was used.

- A fresh actual GJS Sensors/Values run after reload returned all143 rows/all12
  SBS readings. Vitals files and favorites were unchanged by this release.

The full goal remains active/incomplete.0.32 full230-export audit and0.33 filesystem
qualification remain separate retained evidence. These four changed contracts do
not establish every original API, absent peripheral or deferred physical test.

# Qualification: 0.33.0, 2026-10-31

Installed signed DKMS/runtime0.33.0 on the qualified UP3404VA.301.

- Reproduced an installed0.32 storage-usage bug with a simulated denied mount:
  the failed filesystem disappeared while its readable sibling remained. Current
  providers retain both, with explicit availability/errno and no fabricated values.
  Present disks without mounted filesystems differ from an empty disk census.
- Eight added tests cover partial/all mount failures, unmounted/absent disks,
  reserved space and valid zero, malformed capacity/percentage data, shared
  block-tree children, both original API dispatches and rejected arguments.
  A discarded inventory query was also removed from disk usage/temperature routing.
  Temperature decoding/control behavior is otherwise unchanged. These reads do
  not request mounts, SMART, device control or additional firmware operations.
- All229 Python tests, retained optimized/sanitized C and Node suites,252-name
  parity and W=1 module build passed. The kernel change is its version metadata;
  the qualified native SMBus collector and fixed hardware allowlists are retained.
- Installed ordinary-user native/CLI/C usage calls agree on path/mount/availability
  and total bytes. All-drive results include three available filesystems plus one
  explicit unmounted disk; SSD results include two available filesystems. Independent
  os.statvfs calls agree with every total. Used/free values are sequential snapshots,
  so exact equality across separate calls is not claimed. Unknown arguments are
  rejected before inventory; partial errors do not turn a whole API into failure.
- Existing native SBS readings remain available with native completion/result0/1.
  Root-owned installed runtime/kernel-source equality and existing-MOK CMS signature
  verification passed. Retained C all-drive temperature query preserves the NVMe
  reading beside explicit unavailable devices. Firmware-auto fan, owner profile,
  charge cap, keyboard and four UEFI hashes were preserved.

- A fresh actual GJS Sensors/Values run after the module reload returned all143
  rows, including all12 SBS readings. Vitals helper/source/favorites were unchanged
  by this release; no current-session restart or logout was requested.

The full objective remains active/incomplete. Full230-export audit from0.32 is
retained; this release specifically requalifies the changed usage providers and
retained integration, rather than treating two calls as a fresh full-scope audit.
No previously unperformed physical qualification is claimed by these simulated
failure checks or the kernel version update.

# Qualification: 0.32.0, 2026-10-31

Installed signed DKMS/runtime0.32.0 on the qualified UP3404VA.301.

- Target-ROM table entry9/read direction/two-byte copy led to a bounded private
  native SMBus ReadWord probe. All16 fixed SBS words twice plus specification/mode
  brackets (34 reads) completed with control0/worker-result1. Thirty-two complete
  RX-tail checks with two sentinels proved exactly two changed bytes. All49 IPC
  bytes restored/read back; independent Linux capacities/cycles agreed. Selector5
  was a disproven analysis hypothesis and was never requested.
- Production uses opcode16/subindex9, with no combined-I2C fallback or legacy
  software-SRAM observer. It seeds the30-byte RX suffix once and checks every byte
  after every word before any next request. Sentinels, exact identity, both channel
  mappings, specification/mode brackets, manual exclusion, full restoration and
  the shared fault latch remain. Native unsuccessful completion has a distinct
  bounded-retry predicate; unexpected status and restoration failures never retry.
- All221 Python tests, retained Node/C suites,252-name parity and W=1 module build
  passed. Optimized and ASan/UBSan builds each exercise944 ordinary/985 sentinel-retry
  native failure points,753 retained legacy failures and all30 suffix-corruption
  positions. Traced/untraced I/O, return values, output commitment and restored
  bytes agree at injected failures. Short/overlong data, wrong selector/status,
  mode changes and failed restoration are rejected.
- First installed fresh native collection took5.62s. Four cold actual concurrent
  GIO rounds (35s before each) returned all five battery providers and all12 SBS
  rows, each with exactly one successful attempt and no failure/retry. Native
  completion/result were0/1, with legacy bus/software fields null. This qualifies
  the replacement on these observed refreshes; it does not establish infallibility
  or identify the physical cause of the retired combined-transfer failures.
- A fresh actual GJS Sensors/Values run with the updated transport-aware helper
  returned143 rows (123 battery,7 processor,13 storage) including all12 SBS rows.
  Only that helper changed; owner favorites and Sensors/Values were preserved.
  Ordinary-user native/CLI/C history agrees with raw payloads, including seven
  region durations and withheld255 balancing fields. Native/CLI SBS capacities
  and cycles agree with Linux; typed diagnostics validate the new transport.
- Fresh installed-runtime audit executed230 read-only original exports (204 user,
  26 privileged):196 values and34 explicit unavailable results. All unavailable
  results were existing firmware/peripheral absence, unadvertised PDO slots or
  missing cable identity. Compared with the0.15 baseline, all status/errno outcomes
  were unchanged except the repaired all-drive temperature query now succeeding.
  No mutation was executed; automatic fan, profile, charge cap, keyboard and four
  UEFI hashes remained unchanged. Successful calls alone do not qualify every
  payload field, physical peripheral or factory-write behavior.
- Installed root-owned runtime/kernel-source equality and existing-MOK CMS
  verification passed. Firmware-auto fan, owner profile,100% charge cap, keyboard
  and four UEFI hashes were preserved. Meaningful nonzero physical battery flow,
  cold boot, enabled-Secure-Boot loading and physical suspend remain unperformed.

The full native-port objective remains active/incomplete. Old combined-transfer
failure receipts are historical; that path is not used as a fallback. The original
five-hour history capture and short power capture remain terminal, not live jobs.

# Qualification: 0.31.0, 2026-10-31

Installed signed DKMS/runtime0.31.0 on the same qualified UP3404VA.301.

- Controlled0.30 ordering study completed seven isolated/sequential cases. All
  returned SBS data; three needed the bounded retry. No particular preceding
  provider was established as the cause. Per-read elapsed fields in that private
  study were evaluated before I/O and are explicitly not used as timing evidence;
  case order, native cache ages and attempt counter deltas remain valid.
- Added four fixed software-SRAM copy reads, twice, only immediately after qualified
  failed completion0x40 and before mandatory49-byte restoration under ECMT. The
  observer cannot change the collection result or retry policy; restoration still
  runs after an observer error, and restoration failures retainEUCLEAN/shared latch.
  No BMS command, hardware/FIFO/status/read-clear register or write is added.
- Eight observer read failures, unequal passes and mismatched context are tested;
  observer failure still restores the full original IPC and withholds failed data.
  Existing753-point traced/untraced collector I/O/restoration parity is retained.
  All219 Python tests, retained optimized/sanitized C and Node suites,252-name
  parity and W=1 module build passed.
- Three actual concurrent GIO refreshes returned all12 SBS rows. The third exercised
  a first-attempt0x40 failure and successful fresh retry. Its software observation
  was stable/context-compatible rawc7000101 (status-copy/return/channel/acquisition).
  These non-atomic software copies may be stale/reused, so current-operation
  provenance and a physical hardware fault are explicitly unproven. They are
  cached raw diagnostics, never inputs to measurements, acceptance, retry or control.
  This is observability, not an SBS reliability fix.
- Installed root-owned runtime/kernel source byte identity and existing-MOK CMS
  verification passed. Retained C storage/history and native/CLI typed diagnostics
  passed. A separate actual GJS Sensors/Values run returned143 rows/all12 SBS
  values; expected balancing unavailability remained. Three cached diagnostic
  reads added no collection. Firmware-auto fan,
  owner profile, charge cap, keyboard and four UEFI hashes were preserved.

Full-port objective remains active/incomplete. The known intermittent SBS failure
when both attempts fail remains open; a target-firmware native SMBus word-read
transport is a static-analysis lead, not yet a requested or qualified protocol.
Original five-hour history reader is terminal with151 successful samples; do not
reuse/restart its old PID/handle. No new capture for nonzero gauge power has run.

# Qualification: 0.30.0, 2026-10-31

Installed signed DKMS/runtime0.30.0 on the same qualified UP3404VA.301.

- Target firmware and0.29 traces identify unsuccessful completed transfer0x40,
  rather than pending work. Added at most one complete fresh fixed SBS collection
  after that narrowly checked result and successful49-byte restoration/readback.
  ECMT is released during100ms backoff, then reacquired. All identity, direction,
  sentinel, specification/mode and restoration gates run again. No failed RX word
  or old measurement becomes successful data.
- Retry predicate rejects unobserved/unexpected status, unknown/unsupported command,
  wrong phase, transport/short-frame/protocol/mode and restoration failures. EUCLEAN
  still latches controller access off. Traced/untraced753-point I/O/restoration
  parity remains valid for the collector. All218 Python tests, retained optimized/
  sanitized C and Node suites,252-name parity and W=1 module build passed.
- Three actual concurrent GIO refreshes produced two complete SBS frames/all12 rows
  and one failed refresh. One live first-attempt0x40 failure recovered on the second
  complete collection; another remained0x40 on both attempts and stayed unavailable.
  End counters5 attempts/2 successes/3 failures/2 retries/1 recovered refresh prove
  the bounded path was exercised. Other four battery providers succeeded throughout.
  This establishes a useful recovery path, not complete SBS reliability or the
  underlying physical bus cause. The original failed frames remain in diagnostics.
- Subsequent ordinary-user native/CLI metrics returned valid SBS data and typed
  diagnostics; retained raw/native/CLI/C region history agreed exactly. A separate
  actual GJS Sensors/Values pass returned143 rows with all12 SBS values,143 total,
  while retaining expected balancing unavailability. This later successful pass
  does not erase the concurrent-refresh failure above. Vitals source/helper and
  owner settings were unchanged by0.29/0.30; a running Shell may still need normal
  new login to load earlier integration changes.
- Repeated cached diagnostic reads caused no new collection. Native metrics expose
  validated attempts/retries/recovered counts and historical last failure separately
  from actual battery values. No-attempt/null states are retained. Installed runtime/
  kernel source/root ownership and existing-MOK CMS verification passed; retained
  C storage-temperature check passed. Firmware-auto fan, owner profile, charge cap,
  keyboard and four UEFI hashes were preserved.

- The original five-hour lifetime reader completed normally at13:51UTC with151
  successful samples, zero errors and four changes (two each for words0/4).
  Same-word interval bounds remain7200..7440s and runtime-minus-region sums3/4 raw
  ticks. Balancing bytes remain255/255/0/0, with no converted valid duration; the
  extra10-byte OEM tail stayed unchanged and unqualified. No new BMS request or
  setting was used. The original PID/exec handle are now terminal.

The intermittent SBS failure remains open when both attempts fail; investigation
must use source-backed diagnostics rather than raising retry counts or guessing
unknown firmware data. The full-port objective remains
active; the original lifetime capture is complete. No new command, charger/gauge
setting, reset or unseal was introduced.

# Qualification: 0.29.0, 2026-10-31

Installed signed DKMS/runtime0.29.0 on the same qualified UP3404VA.301.

- Added cached read-only SBS attempt diagnostics. No controller request, timing,
  retry or restoration policy changed. Three metadata reads left attempt count0
  unchanged after installation. Operation and restoration errors remain separate;
  failed history survives recovery and null status is distinct from actual0.
- Traced and untraced helper outcomes, I/O counts, output commitment and restored
  memory agree across all371 ordinary and382 sentinel-retry failure injections in
  both optimized and ASan/UBSan builds. Completion/bus-status phases are exercised
  separately; restoration failures still returnEUCLEAN and retain the shared latch.
  All217 Python tests, retained C/Node suites,252-name parity and W=1 build passed.
- Three actual concurrent GIO refreshes reproduced SBS EIO. Every trace identifies
  first command0x1a, word-completion phase, completion_status64(0x40), operation-EIO
  and restoration_status0. The other four battery providers succeeded. The target
  firmware branch records0x40 for an unsuccessful combined transfer, not a
  pending request; the underlying bus failure cause is not yet established.
- Installed root-owned runtime/kernel source byte identity and existing-MOK CMS
  signature verified. Retained C storage-temperature query passed. Automatic fan,
  profile, charge cap, keyboard and four UEFI hashes were preserved. No arbitrary
  BMS/controller request, gauge setting/reset/unseal or input event read was used.

This release locates the demonstrated gap; it does not claim an SBS reliability
fix. A bounded complete fresh retry after verified restoration is the next
controlled check. Full-port objective and original live capture remain active.

# Qualification: 0.28.0, 2026-10-31

Installed signed DKMS/runtime0.28.0 on the same qualified UP3404VA.301.

- Source audit found GPU PMU reset/out-of-range readings clamped into idle/full,
  unvalidated DRM percentages, no interval/suspend gates and an initial-packet
  descriptor leak. Tablet mode silently skipped evdev errors and could report
  off from a partial census. These demonstrated availability gaps are fixed.
- All five actual Intel i915 engine events advertise ns units and returned valid
  complete, nonmultiplexed perf packets. Render activity was naturally nonzero
  in the probe, while other engines recorded actual0%; no GPU load was generated.
  Each engine now reports its own measured duration. Sampling/reset/wrap/suspend,
  unit, percentage, changed-provider and packet errors remain unavailable, never
  clamped or extrapolated. Per-engine errors preserve other valid engines.
- The one advertised tablet switch returned false with a complete unchanged
  census. Current laptop mode agreed through native/API/CLI/C. Only capability
  and current-state ioctls were issued; no event stream was read, key recorded,
  device grabbed or input service changed. Physical fold transition remains
  unperformed; a synthetic positive tests logic only. Device identity/capabilities
  are rechecked across the complete input inventory before reporting off.
- Thirteen targeted tests cover0/50/100% counters, reset/overshoot/multiplexing,
  short packets and initial-failure descriptor closure, no-access/unknown-unit
  failures, actual-vs-requested intervals/suspend, DRM invalid values, strict API
  arguments, tablet positive/negative/partial availability, exact read-only ioctls,
  character-device identity and non-tablet replacement during a negative census.
  All215 Python tests, retained optimized/ASan/UBSan C fault suites,252-name parity
  and three Node adapters passed. W=1 module build passed.
- Installed native/API/CLI/C reads returned five valid engine rows and false
  tablet mode. Separate sequential GPU samples are not required to have identical
  percentages. Retained battery history exposed all seven region durations and
  kept255/255 balancing values unavailable. Vitals helper is byte-unchanged from
  0.27 and still supplies143 rows; a running Shell may need ordinary new login.
- A fresh143-row GJS pass preserved the seven region histories, balancing
  unavailability and charger readings, but its SBS rows were unavailable. This
  failed full-sensor smoke is retained. A later direct sysfs/native SBS read
  returned a valid frame; no errno was retained from the first pass, so its cause
  is not established. Bounded concurrent GIO reads are recorded separately; a
  successful recovery is not a claim that the transient has been fixed. Three
  recorded concurrent GIO rounds produced two SBS EIO failures followed by one
  valid frame/all12 SBS rows; the other four providers succeeded throughout.
  This reproducible intermittent read failure remains an open port gap.
- Kernel source differs from0.27 only by version. Automatic fan, owner profile,
  charge cap, keyboard and four UEFI hashes were preserved. No charger/gauge/fan
  setting, perf permission, input permission, logout or hardware fold was used to
  qualify these readers. Installed source/runtime identity and MOK CMS verification
  are retained in the private qualification audit.

The full objective remains active/incomplete. OEM history bytes/thresholds,
ambiguous balancing maxima, unavailable firmware adapter providers, nonzero
new gauge power/current and absent-device/boot/suspend hardware qualifications
remain open. The original five-hour lifetime capture remains live; do not restart
it merely because an observation wait times out.

# Qualification: 0.27.0, 2026-10-31

Installed signed DKMS/runtime0.27.0 on the same qualified UP3404VA.301.

- The original same live capture now has two word4 edges:12200→12201 at10:47..10:49
  and12201→12202 at12:49..12:51UTC. Its independent increment interval is bounded
  at7199.99994..7440.00014s, matching the previously observed word0 cadence and
  compatible first8-U16 time layout. All121 capture prefixes checked during review
  satisfied the runtime/region sum relationship. No stimulus or new BMS command
  was used.
- Seven recorded region durations are now reported in2h steps with firmware codes
  UT/LT/STL/RT/STH/HT/OT. Installed values were4/96/3446/24404/0/0/0h. The sum27950h
  differs from27956h recorded runtime by6h, within independent quantization bounds.
  Actual configured Celsius thresholds are unavailable; no degrees, new physical
  thermistors or current active region are assigned. OEM bytes16..25 remain raw.
- The compatible8-byte block2 balancing layout is implemented for the two applicable
  cells only, with inactive storage validation. Actual counters are255/255, stable
  throughout the capture; both converted durations remain unavailable. They are
  not zero readings or qualified510h totals. Current balancing state and meaningful
  nonzero accumulation/reset/saturation behavior remain unverified. This is recovered
  protocol with explicit unavailable hardware values, not complete physical qualification.
- Eight focused tests cover region order/units/sum/step/zero/threshold absence,
  original API metadata, partial/max/inconsistent prefixes, applicable-cell layout,
  per-cell maximum isolation and inactive storage. Synthetic nonzero balancing
  values exercise parsing only. All202 Python tests, retained optimized/sanitized C
  protocols,252-name parity and three Node adapters passed. W=1 module build passed.
- Raw/native/CLI/C block3 region metadata agreed exactly. Native/CLI balancing metadata
  retained raw255/255 and null converted hours. Complete original raw payload and old
  opaque four-byte compatibility field are unchanged; the old unit flag remainsfalse.
- A reviewed helper-only Vitals upgrade preserved Sensors/Values and owner settings.
  Fresh actual GJS Sensors/Values returned143 rows:123 Battery,7 Processor,13 Storage.
  Seven region-duration strings rendered with step size; both balancing rows correctly
  displayedUnavailable. A normal new login may be needed for a running Shell to load
  the changed helper; no forced logout or unsafe eval was used.
- Installed kernel/runtime byte identity, root ownership and MOK CMS signature passed.
  Kernel source differs from0.26 only by version. Automatic fan, profile, charge cap,
  keyboard and four UEFI hashes were preserved. No balance activation, reset, unseal,
  protected-dataflash read or configuration write was performed.

The full objective remains active. Ten extra OEM block3 bytes, actual region thresholds,
ambiguous balancing maxima, other unavailable adapter providers and physical nonzero
new gauge power/current remain open. WWAN/XG/positive USB display, enabled Secure Boot,
cold boot, physical suspend/resume and external-meter accuracy are unperformed hardware
qualifications. The original capture is still live and must not be restarted on timeout.

# Qualification: 0.26.0, 2026-10-31

Installed signed DKMS/runtime0.26.0 on the same qualified UP3404VA.301.

- The compatible primary reference defines lifetime block3 offset0 as U16
  recorded firmware runtime in2h steps, followed by seven temperature-region
  counters. The OEM complete reply is26bytes. Two observed word0 increments
  (13976→13977→13978) give7199.9999..7440.0001s between edges, supporting that
  stored resolution. All108 capture frames checked at installation satisfied
  total-minus-other-seven in0..7; observed differences were3/4. No gauge setting,
  reset, unseal, speedup mode or new BMS request was used.
- New `recorded_firmware_runtime` decodes only that first U16 and reports27956h
  in2h steps. The pinned0.17 capture, current raw sysfs frame, native report,
  CLI and C block3 API agreed on raw13978 and its converted recorded value.
  This is a quantized historical firmware counter, not battery age or host
  uptime. Reset/wrap behavior and oscillator accuracy are not claimed.
- The old four-byte `runtime_counter_raw` remains145050 in this sample and its
  `runtime_unit_verified` remainsfalse. Applying the new scale to that opaque
  compatibility value would be wrong. The new nested U16 field is separate;
  the original complete26-byte raw payload is unchanged. Other temperature-region
  meanings/thresholds and OEM tail bytes remain raw.
- Complete-frame, exact identity/firmware, prefix equality and freshness gates
  remain mandatory. Maximum-valued or inconsistent time prefixes suppress only
  the interpreted runtime while retaining other good history. Five focused tests
  cover U16-vs-legacy-U32, recorded zero, two-hour steps without interpolation,
  partial/max/mismatched frames, stale/wrong identities and original-API metadata.
  All194 Python tests, retained optimized/sanitized C protocols,252-name parity
  and three Node adapters passed. W=1 module build passed.
- The reviewed Vitals change replaced only its battery helper, with backup;
  Sensors/Values hooks and owner favorites/settings were preserved. A fresh GJS
  process using actual Sensors/Values returned134 rows:114 Battery,7 Processor,
  13 Storage. `Battery Recorded Firmware Runtime` rendered `27956 h (2 h steps)`.
  A running Shell can retain imported old code until an ordinary new login;
  no forced logout or unsafe eval was used.
- Kernel source differs from0.25 only by version. Installed kernel/runtime bytes,
  root ownership and MOK CMS signature verified. Retained storage C API and battery/SBS checks passed. Automatic fan, profile, charge cap,
  keyboard and four UEFI hashes were preserved.

The full objective remains active. The same original capture is still live;
word4 has one edge and additional region semantics remain unqualified. Meaningful
nonzero new gauge power/current, remaining OEM bytes, unavailable adapter providers,
WWAN/XG and positive USB-display hardware qualification remain open. Enabled Secure
Boot, cold boot, physical suspend/resume and external-meter accuracy remain
separate unperformed tests; no factory mutation was used to increase coverage.

# Qualification: 0.25.0, 2026-10-31

Installed signed DKMS/runtime0.25.0 on the same qualified UP3404VA.301.

- A source audit found unspecified0..100 BSS signal quality being parsed as dBm,
  link connection state depending on AP-cache membership, and broad PHY marker
  searches that could use SSID text. Current nl80211 link/station metadata is now
  independent of NetworkManager/AP cache; only explicit dBm and bitrate-line
  MCS metadata qualify. Fractional whole-MHz iw formatting is supported, with
  no floor conversion of non-channel frequencies.5935MHz/channel2 and4.9GHz
  formulas match Linux; actual positive hardware was5GHz/channel36/802.11ax.
- Active-peer aggregate and two chain RSSIs were returned. The parser matches
  the associated peer rather than the first station, and physical main/aux
  antenna mapping remains unknown. Connection, identity, association and inventory
  failures stay unavailable; a known positive can survive another bad interface.
- Root cached-BSS reads completed without triggering a scan. The actual kernel
  cache contained one explicit-dBm record; RSSI counts were0/1/0 for2.4/5/6GHz.
  Counts are existing kernel observations, not a fresh physical AP census.
  NetworkManager's independently aging cache contained additional observations;
  the two caches are no longer joined into a misleading threshold count.
- Unprivileged NetworkManager AP counts use the existing unique owner, fixed
  bounded Get reads, validated BSS identity/frequency/LastScan and stable scan/
  device inventory. Known scanned-empty data can return0; never-scanned empty,
  malformed or failed reads cannot. Quality percentages stay percentages. The
  parsed count output retains no SSID values. Card/driver and generic up-interface
  metadata no longer depend on that AP cache.0.19 byte-rate sampling is retained.
- Eighteen targeted tests cover unit confusion, weak/strong/unknown cached RSSI,
  duplicate observations across interfaces, missing/empty/unknown states, active
  peer chains, misleading SSID markers, decimal/special channels, hotplug/roam,
  daemon/permission/timeouts, never-scanned cache and no-scan/no-NM link routing.
  All189 Python tests, retained optimized/sanitized C suites,252-name parity and
  three Node adapters passed. W=1 module build passed.
- All18 changed wireless API providers were exercised across the installed root
  qualification and11 ordinary-user native/CLI/C queries. Static peer/channel/PHY/
  driver values agreed; sequential RSSI, rate and AP counts were valid with no
  claim of exact cross-call equality. Kernel/runtime source identity, root ownership
  and MOK CMS passed. Kernel source differs from0.24 only by its version. Fan
  automatic, profile, charge cap, keyboard and four UEFI hashes were preserved.
  Existing133-row Vitals JavaScript is unchanged.
- The same original lifetime capture remains live. It now has two word0 edges:
  13976→13977 at09:59..10:01UTC and13977→13978 at12:01..12:03UTC. The monotonic
  interval is bounded at7199.9999..7440.0001 seconds; boottime agrees within frame/
  clock granularity. This supports the compatible older reference's two-hour
  resolution, but this release does not yet convert unknown OEM history fields.
  Word4 has one edge; the26-byte OEM frame and extra fields still need qualification.

The full objective remains active. Meaningful nonzero charge/discharge of the
new gauge power/current readings, remaining OEM data semantics, unavailable
adapter providers and absent WWAN/XG/positive USB-display qualification remain
open. Enabled Secure Boot, cold boot, suspend/resume and external-meter accuracy
are separate unperformed tests. No scan, network change, gauge reset/unseal/
configuration or extra hardware-control experiment was used for this release.

# Qualification: 0.24.0, 2026-10-31

Installed signed DKMS/runtime0.24.0 on the same qualified UP3404VA.301.

- Linux7.0 source confirms that UCSI voltage/current properties are synthesized
  from PDO/RDO or Type-C advertisements. The old summary incorrectly labelled
  positive UCSI voltage as an electrical measurement. The actual source-facing
  phone port had online0/Discharging and nominal5V/3A; those fields now remain
  explicit non-measurement metadata, with legacy measurement slots null. The
  PD input port's zero contract values are unavailable, not zero measured draw.
- UCSI online/status/selected USB type, identity and inventory are validated.
  Source-facing Type-C, non-PD input, disabled sink path, offline defaults, PPS,
  partial/unknown/error/changing state are covered by tests. Known PD positives
  survive another unavailable port; negatives require complete known state.
  Optional electrical metadata errors do not erase known input state. PDO types
  and partner targets of these UCSI values are not independently qualified.
- The separate shared-input ISL9241 ADC remains a measurement source and is now
  included directly in CLI show. The installed sample was19.68V/1.1544A,22.718592W,
  separate from the phone's5V/3A advertisement. This adds no wall-meter calibration
  or per-port ADC attribution claim. Existing133-row Vitals code is unchanged.
- Dedicated CPUFreq APIs use validated per-policy data instead of the complete
  EC snapshot. All16 actual policies were readable; possible maximum4600MHz
  matched independent cpuinfo_max_freq reads. Current values varied between
  sequential queries and are not claimed identical or simultaneous. The source
  is driver-reported scaling frequency, not a guaranteed exact hardware clock.
  Partial policies preserve good rows while withholding an unproven aggregate;
  missing/zero/malformed/negative values and identity/inventory changes are tested.
- Loaded version/refcount now require valid fixed module data with an identity
  bracket. Empty/missing/malformed values cannot return success; an actual zero
  refcount remains valid. Existing-driver InitializeWinIo passed without an
  extra unload. The driver was not stopped just to increase lifecycle coverage.
- Valid signed16-bit current0xffff now remains-1mA through original field APIs;
  missing/invalid raw words become null. Boundary handling is simulated. This
  installed run observed raw/signed0; it does not count as physical-1mA or
  meaningful charge/discharge qualification.
- Eighteen targeted tests and all171 Python tests, retained optimized/sanitized
  C protocols,252-name parity and three Node adapters passed. W=1 module build
  passed. Kernel source differs from0.23 only in its version string. Exact installed
  kernel/runtime identity, root ownership and MOK CMS signature passed.
- Seven ordinary-user native/CLI/C queries passed: PD input state, module version,
  refcount, both CPU frequencies and both original battery-current APIs. Static
  values agreed exactly; dynamic CPU current frequency was valid and positive,
  not advertised as an exact match across independent sequential reads. UCSI
  roles/status matched independent power_supply and Type-C state. Automatic fan,
  owner profile, charge cap, keyboard and four UEFI hashes were preserved.

The full goal remains active. The original lifetime capture is still live and
has two different words with one increment each; cadence and runtime units remain
unqualified. Physical nonzero battery charge/discharge, unknown OEM fields,
unavailable adapter providers, WWAN/XG and positive USB-display qualification,
enabled Secure Boot, cold boot, suspend/resume and external-meter accuracy remain
open; no absent hardware, fault-free status or unknown location is invented.

# Qualification: 0.23.0, 2026-10-31

Installed signed DKMS/runtime0.23.0 on the same qualified UP3404VA.301.

- A fixed private test recovered16 standard SBS READ words through the existing
  firmware combined-read worker. Two passes completed32 reads and restored all49
  volatile mailbox bytes. No gauge register data, calibration or battery setting
  was written. BatteryStatus and private identifiers were excluded.
- The installed provider reports direct pack voltage/current, average current,
  selected battery temperature, desired charge current/voltage, gauge relative/
  absolute SOC and maximum-error estimate, remaining/full/design capacity, design
  voltage and cycles. Specification0x0031 and capacity mode are checked; mode and
  specification are bracketed. Capacity energy mode is covered by simulated
  decoding; the actual pack remains in charge-capacity mode. Sequential words
  are not advertised as simultaneous samples. The cache is30 seconds.
- The first installed read took3.04 seconds and reported8.320V. Direct voltage
  matched the independently read gauge cell sum within50mV. Linux's battery
  voltage was7.971V, identical to its design voltage, and was not used to overwrite
  the direct measurement. Capacities and cycle count matched independent Linux
  readings exactly. Gauge/SBS selected temperatures agreed within2C.
- Actual state was Full with AC connected: measured current0A, averaged current
  -0.001A and charge requests0. These readings do not qualify meaningful nonzero
  current sign/scale under charge or discharge. The previous unplug request is
  still pending; a completed all-AC capture was not silently restarted.
- All153 Python tests and optimized/ASan/UBSan C suites passed. New transport tests
  inject371 ordinary and382 sentinel-retry failures, checking unchanged output,
  complete words, command/address/direction allowlists, mode changes and verified
  restoration. Three Node adapters and252-name parity passed. W=1 module build
  passed without code warnings.
- Installed kernel/runtime hashes and root ownership match source, and the MOK
  CMS signature verifies. Ordinary-user native and CLI metrics agree; retained
  original C ABI reads pass. The new SBS JSON is an additional native interface,
  not a new original Windows export. Manual fan mode rejects SBS and retained
  hardware groups withEBUSY; automatic control and owner profile, charge cap,
  keyboard and four UEFI hashes were restored/preserved.
- The reviewed Vitals upgrade changed only its Sensors hook and battery helper,
  preserving owner code/formatters/settings with a backup. A fresh GJS process
  using actual Sensors/Values returned133 rows:113 Battery,7 Processor,13 Storage.
  All12 new SBS rows had valid values and formatting. The running GNOME Shell
  can retain older imported JavaScript until an ordinary new login; no forced
  logout or Shell unsafe evaluation was used.

The full objective remains active. The original five-hour lifetime capture is
still running, with two increments in different words but no same-word interval
or qualified runtime units. Unmapped OEM bytes, physical nonzero charge/discharge,
positive USB-display and absent WWAN/XG qualification remain explicit. Enabled
Secure Boot, cold boot, physical suspend/resume and external-meter accuracy are
still untested; compatible protocol data does not identify the physical gauge IC.

# Qualification: 0.22.0, 2026-10-31

Installed signed DKMS/runtime 0.22.0 on the same qualified UP3404VA.301.

- A source audit found Bluetooth D-Bus errors becoming an empty list, backlight
  failures becoming0% through default values, and missing AC data becoming false.
  The new providers preserve explicit errors and per-backlight availability.
  Known zero traffic/connections/brightness remain valid when actually read.
- Bluetooth resolves an existing unique BlueZ owner without activation, then
  performs the fixed ObjectManager read with a timeout. Mandatory connection
  status must be a valid Boolean; optional malformed metadata does not discard
  valid connections. No discovery, pairing, connection or device-setting method
  is called. The live state was zero connected devices, independently checked
  against a separate BlueZ snapshot; positive and error cases are simulated.
- Brightness validates actual/max values, identity and a repeated range read.
  One actual backlight returned a valid percentage and matched direct sysfs.
  Mixed good/zero/missing/invalid and changing-range cases are tested. This is
  the kernel backlight level, not optical calibration or external-monitor DDC.
- Both AC APIs use a dedicated fixed0/1 read and matched the actual connected
  adapter. Missing/denied/invalid reads are tested as errors. CLI show uses a
  nullable status and explicit error. Battery fault/full and manual-fan status
  also keep invalid/missing inputs unknown; the legacy PF predicate cannot be
  cleared or asserted from missing status data.
- Six ordinary-user native, CLI and C ABI queries agreed with independent BlueZ,
  backlight and AC reads. The current fan/manual, battery/full/error and AC fields
  in CLI show are correct. Eleven targeted availability tests and all147 Python
  tests, retained optimized/sanitized protocols,252-name parity and three Node
  adapters passed. W=1 module build passed without code warnings.
- Kernel source differs from0.21 only in its version string. Installed runtime/
  kernel-source identity, root ownership and MOK CMS checks passed. Automatic
  fan, profile, charge cap, keyboard and four UEFI hashes were preserved.
  The qualified121-row Vitals integration is unchanged.

The original full objective remains active. The existing history capture is still
live with one observed lower-word increment and unqualified units. The completed
short power capture did not observe unplug/discharge; its pending owner test was
not counted as passed or silently restarted. Unmapped OEM fields and unavailable
hardware/provider/physical qualifications below remain open.

# Qualification: 0.21.0, 2026-10-31

Installed signed DKMS/runtime 0.21.0 on the same qualified UP3404VA.301.

- RF_USBHDMIIsUsed now uses DRM USB ancestry and partner DP alt-mode evidence
  instead of a DisplayLink product-name match. The kernel DP driver confirms
  that its configuration describes the partner role: a sink partner with an
  active mode and selected pins implies local source transport. Local mode
  capability, virtual-driver names and arbitrary external monitors are not
  treated as verified USB output.
- Seven filesystem/route tests cover direct USB graphics, internal-only output,
  partner/local and source/sink distinctions, unconfigured/USB modes, unmapped
  and virtual displays, missing/malformed providers, changing connector/SVID/mode
  data and preserving independent positive evidence beside failures. All136
  Python tests, retained optimized/sanitized protocol suites,252-name parity and
  three Node adapters passed. W=1 module build passed without code warnings.
- Installed native, ordinary-user CLI and C ABI reads returned false with one
  embedded connected display and complete metadata coverage. Independent DRM
  status snapshots before/after agreed. No USB display is attached, so the
  positive hardware paths remain physically unqualified; fixture tests are
  not counted as attached-adapter tests.
- Fresh UCSI GET_CAPABILITY returned two connectors, features0 and platform
  PD revision0x0200. A fixed optional GET_CABLE_PROPERTY returned only zero bytes
  while the active contract and automatic fan stayed unchanged. No usable cable
  information or partner PD revision was inferred. No PD-message/discovery,
  reset, role or power-setting command was sent.
- Kernel source differs from0.20 only in its version string. Signed DKMS build,
  installed runtime/kernel identity, root ownership and MOK CMS checks passed.
  Automatic fan and profile/charge/keyboard/four UEFI hashes were preserved;
  the previous121-row Vitals integration is unchanged.

The separate history capture has observed its first lower-word counter increment;
one edge does not qualify cadence or time units. It continues for the planned
five-hour window. The175-sample short power capture finished with Full/AC status
throughout and only tiny connected-pack values: no unplug or meaningful discharge
test occurred. The owner action remains pending; do not call the completed capture
an active recording. Remaining provider, field and physical-validation gaps below
are still open, and the full goal remains active.

# Qualification: 0.20.0, 2026-10-31

Installed signed DKMS/runtime 0.20.0 on the same qualified UP3404VA.301.

- A fresh audit found successful empty manufacturer/model API values and a zero
  gauge byte derived from that empty string. The original bank1 string cache read
  timed out. No ACPI laptop name was substituted for the battery-reported identity.
- A bounded fixed probe read SBS ManufacturerName/DeviceName using the qualified
  firmware block worker. Two sentinel passes recovered complete10/7-byte strings.
  All48 volatile bytes matched independent restoration readback; the normal0.19
  driver, automatic fan and owner settings were restored afterward.
- Installed0.20 `battery_identity` returned exactly those raw strings. Both old
  sysfs text attributes, CLI show and all five native identity APIs now agree.
  The original raw gauge-byte convention is the fourth reported manufacturer
  byte, without physical vendor interpretation. Exact device/firmware IDs remain
  separate. The unknown physical gauge vendor is still not identified.
- Ordinary-user native, CLI and C ABI calls passed for all five APIs. They use
  the dedicated provider without an unrelated full sensor snapshot. Invalid
  arguments, malformed/stale/wrong-identity data and missing driver/field cases
  have explicit errors. Nonprintable text remains unavailable while raw bytes
  are retained; a missing gauge byte does not default to zero.
- All129 Python tests,252-name parity and three Node adapters passed. Optimized
  and ASan/UBSan tests cover455 new communication-failure boundaries plus the
  retained886 lifetime,315 normal/386 retry live-frame and earlier fault suites.
  All1..32-byte lengths, sentinel-valued data, changing/empty replies, identity
  rejection and exact restoration are covered. W=1 module build passed without
  code warnings.
- Installed runtime/kernel-source identity, root ownership and MOK CMS signature
  passed. Nine JSON monitors, both identity text attributes and temp17_input all
  returned EBUSY during bounded manual ownership, including caches. Automatic
  mode, profile, charge cap, keyboard and four UEFI hashes were preserved.
  Existing metric groups remained available. Vitals JavaScript is unchanged from
  the previously qualified121-row0.18 integration.

The separate long history capture continues. A short read-only capture is prepared
for owner-controlled unplug/reconnect qualification of nonzero battery power;
that physical test is not yet counted as passed. Newer R4/R5 manuals contain a
DA2 length/table mismatch, so the unmatched OEM tail remains raw. Remaining field,
provider and physical-validation gaps below are still open; full completion is
not claimed.

# Qualification: 0.19.0, 2026-10-31

Installed signed DKMS/runtime 0.19.0 on the same qualified UP3404VA.301.

- Wi-Fi throughput now uses the actual monotonic sampling interval, validates
  interface identity and counters, and rejects suspend gaps, resets, hotplug and
  delayed snapshots. Default numeric maps are retained; unavailable interfaces
  return null. Optional detailed output gives separate RX/TX rates and errors.
  This read no longer depends on NetworkManager or requests any scan or traffic.
- Six targeted tests cover oversleep, valid zero traffic, counter errors and
  partial availability, identity replacement, unplug, suspend and bad arguments.
  All 124 Python tests, retained optimized/sanitized protocol suites, three Node
  adapters and the 252-name parity check passed.
- Installed native and unprivileged C ABI reads returned valid rate data. In an
  independent before/after Linux counter bracket, the reported RX/TX byte deltas
  were bounded by the surrounding raw deltas. One native interval was
  0.25032674199610483 seconds with combined throughput about 1.046 MB/s.
  This validates that sample, not continuous operation or an airtime measurement.
- Kernel source differs from 0.18 only in the version string; DKMS rebuilt and
  loaded it. Installed runtime/source identity, root ownership and MOK CMS checks
  passed. Automatic fan, profile, charge cap, keyboard and four UEFI hashes were
  preserved. The Vitals integration is unchanged from the qualified 0.18 helper.

The five-hour passive history capture remains live. All unresolved OEM-field,
absent-hardware and physical-qualification limits below still apply. Full native
port completion is not claimed.

# Qualification: 0.18.0, 2026-10-31

Installed signed DKMS/runtime 0.18.0 on the same qualified UP3404VA.301.

- A fixed read-only probe returned DAStatus frames of 32/24 bytes, restored and
  independently verified all 48 volatile mailbox bytes, and reloaded the normal
  driver. The installed provider retains the exact OEM identity/firmware gates.
  Each live frame comes from one complete transaction; changing measurements do
  not need to match another sample. Short/long responses and sentinel collisions
  are covered by the bounded retry and failure tests.
- Battery reports now include two gauge-computed cell powers, pack/average power
  and algorithm temperature. The installed sample returned zero instantaneous
  powers, -0.01 W average and 29.15 C algorithm temperature. A later Vitals frame
  returned zero average. Nonzero physical power scaling and external accuracy
  remain unverified. Same-frame V/I checks reject inconsistent cell encoding;
  they never substitute a calculated reading. The algorithm temperature is not
  an additional physical thermistor. The eight-byte OEM DA2 tail remains raw.
- Three WWAN exports now use fixed read-only ModemManager property queries with
  distinct technology, home/serving operator and per-radio signal schemas.
  Ten tests cover roaming, LTE/NR, transport privacy, stale/invalid data and field
  failures. Installed native and unprivileged C ABI queries all returned ENODEV,
  as expected without a modem. No physical WWAN qualification is claimed.
- All 118 Python tests, 252-name parity checks and three Node adapters passed.
  Optimized and ASan/UBSan tests cover 315 normal and 386 sentinel-retry live-frame
  communication failures, plus the retained 886 lifetime and earlier fault suites.
  W=1 module build passed without code warnings.
- Installed runtime/kernel-source identity, root ownership and MOK CMS signature
  verification passed. Eight monitoring JSON attributes and temp17_input rejected
  manual fan ownership. Automatic mode, profile, charge cap, keyboard and four
  UEFI hashes were preserved. Existing metric groups and disk C ABI passed.
- The reviewed Vitals upgrade preserved owner code and favorites and is idempotent.
  A fresh GJS process using the actual Sensors/Values classes returned 121 rows:
  101 Battery, 7 Processor and 13 Storage. All five new fields were numeric and
  formatted correctly, including 29 C algorithm temperature. The running Shell
  loads edited JavaScript at the next ordinary login.

A separate five-hour read-only lifetime capture is running to test OEM counter
cadence; a short observation has not qualified time units. Unknown OEM fields,
unsupported legacy adapter/specialty sensors, absent peripherals, nonzero charging,
external calibration and boot/Secure Boot/suspend qualification remain open.
The full native-port goal is active and incomplete. Private hardware receipts and
raw inputs remain outside Git.

# Qualification: 0.17.0, 2026-10-31

Installed signed DKMS/runtime0.17.0 on the same qualified UP3404VA.301.

- Static firmware analysis recovered the separate opcode0x10/subindex11 SMBus
  block worker. A private fixed read probe returned identity length2 and lifetime
  lengths32/8/26/32/32. Different RX sentinels established the complete written
  extents; both reads agreed and all old prefixes matched. All48 volatile mailbox
  bytes, normal driver, automatic fan and owner settings were restored.
- The installed provider uses the fixed read-only worker, exact OEM identity and
  firmware prefix, double sentinel passes, expected lengths and old-prefix checks.
  It returned complete raw blocks, a recorded FET maximum48 C and resistance-disable
  last cycle244. All16 event last-cycle fields are complete. The full raw block
  APIs returned32/26/32/32 bytes through the unprivileged installed C ABI.
- Blocks2/3 are8/26 bytes, differing from the TI reference20/4. Bytes after the
  established four-byte prefixes remain raw. No cell-balancing interpretation or
  runtime-unit conversion is published. Physical gauge vendor remains unverified.
- All103 Python tests, optimized/ASan/UBSan886 block-worker failure points,
  retained core/charger/gauge/PD fault suites,252-name parity and three Node
  adapters passed. Short/long replies, stale RX bytes, changing data, wrong identity,
  prefix mismatch and restoration failures reject partial output. W=1 build passed
  without code warnings.
- Installed runtime/kernel source identity, root ownership and MOK CMS verification
  passed. Seven monitor attributes rejected manual ownership including cached
  lifetime data. Automatic fan, profile, charge cap, keyboard and four UEFI hashes
  were preserved. Previous releases remain available for rollback.
- The reviewed Vitals helper update preserved owner hooks/favorites. Actual fresh
  GJS Sensors/Values returned116 rows:96 Battery,7 Processor,13 Storage. The new
  FET history formatted as48 C and the resistance-disable cycle as244. Edited
  JavaScript loads in the running Shell at the next ordinary login.

Remaining unknown field semantics, unsupported legacy adapter/specialty providers,
absent peripherals and physical qualification limits are explicit. The full goal
remains active. No raw firmware, disassembly, identifiers or private receipts are
committed.

# Qualification: 0.16.0, 2026-10-31

Installed signed DKMS/runtime0.16.0 on the same qualified UP3404VA.301.
Kernel code is byte-identical to0.15 after normalizing the version string.

- A fresh baseline audit called all230 non-mutating exports:195 returned values,
  35 returned explicit unavailable errors. These are call outcomes, not230
  independent semantic or physical qualifications. No setter or read-and-clear
  diagnostic was executed. Fourteen additional native/UEFI/configuration/lifecycle
  plans were verified with apply=false; four firmware record hashes were unchanged.
- The audit exposed a disk-temperature aggregation bug: a failed SMART device
  discarded a working NVMe hwmon reading. The fixed provider returns a row for
  each disk. Installed CLI and C ABI returned a valid NVMe temperature and two
  explicit unavailable rows (one standby, one failed provider). The NVMe reading
  matched a fresh independently selected hwmon device within3 C.
- Four regression tests cover mixed working/unsupported disks, standby and
  unsupported ATA checks, malformed/timeout responses and exact hwmon ancestry.
  All101 Python tests, optimized/ASan/UBSan protocol suites,252-name parity checks
  and three Node adapters passed. W=1 module build passed without code warnings.
- Installed runtime/kernel-source equality, root ownership and CMS signature
  verification against the existing MOK passed. Existing metric groups returned
  available data. Automatic fan, profile, charge cap, keyboard and four firmware
  hashes were preserved. Previous releases remain available for rollback.

The affected temperature read was rechecked after the fix; the230-call receipt
is the0.15 baseline. Missing fields within a successful aggregate remain explicit.
No Vitals JavaScript changed in this release. Remaining battery layout/runtime,
legacy adapter/specialty-sensor and absent-peripheral limitations remain open;
full native-port completion is not claimed. Physical boot/Secure Boot/suspend,
external calibration and nonzero live charging qualifications are still pending.

# Qualification: 0.15.0, 2026-10-31

Installed signed DKMS/runtime0.15.0 on the same qualified UP3404VA.301.

- 97 Python tests passed; optimized/ASan/UBSan PD communication-failure coverage
  expanded to320 boundaries. Wrong alert lengths preserve the previous output
  and restore all volatile mailbox bytes. The transmitted-alert0x75 pointer is
  rejected. Existing gauge/core/charger fault suites and all three Node adapters
  passed; W=1 module build passed without code warnings.
- Installed unprivileged native API and C ABI returned a full received ADO of0.
  This means no alert recorded, not current protection status. E-marker Other
  returned ENODATA because this connection has no acknowledged cable identity.
  Synthetic checks cover nonzero ADO/masks, short identity ACKs, older kernels,
  stale caches, malformed bits and inactive ports.
- All seven monitor attributes still rejected manual ownership including caches.
  Automatic fan, platform profile, charge cap, keyboard and four UEFI hashes were
  preserved. Installed runtime/kernel source identity and MOK CMS verification
  passed; previous releases are retained.
- Fresh actual Vitals Sensors/Values GJS returned115 rows:95 Battery,7 Processor,
  13 Storage, including No alert recorded / No active contract on the two ports.
  One initial check lacked charger die temperature while C API reads overlapped;
  no errno was captured and a causal explanation is unproven. Follow-up raw
  metrics had valid_mask31 and53.136 C, then the sequential GJS check passed.
  Unavailable values were not replaced with stale readings. The running Shell
  still needs an ordinary new login to load edited JavaScript.
- Four fixed original thermal/config queries (CC00/02, CC00/04, CE00, E400)
  all timed out. Every query resynchronized successfully and read firmware fan
  mode0 (automatic); the normal installed driver and owner settings were restored.
  These legacy providers supply no extra readings on this BIOS. Their absence
  does not justify assigning physical specialty labels to the five BIOS NTCs.
- A private alternate battery manufacturer-data probe returned one valid device
  identity (length2,4556), then a longer read failed; a later fixed read attempt
  also failed. Both restored the mailbox and normal0.14 driver; the established
  gauge/history providers still worked afterward. This path is not shipped.

Full objective remains active: complete battery fields/runtime semantics, remaining
OEM adapter providers and broad API/hardware qualification still need work. Existing
physical calibration, boot/Secure Boot/suspend and absent-peripheral limits remain.
Raw/private inputs and probe receipts stay outside Git.

# Qualification: 0.14.0, 2026-10-31

Installed signed DKMS/runtime 0.14.0 on the same UP3404VA.301 / HealthyTable15.
Previous releases are retained. The source addition is a fixed read-only 0x61
four-byte reset prefix, queried twice with the other lifetime prefixes.

- 93 Python tests passed. Optimized/ASan/UBSan suites retained the core, charger
  and PD checks; gauge metric failure points remain 77, lifetime expands to 301.
  All three Node adapters and the W=1 kernel build passed.
- The independent fixed 0x61 probe returned shutdown/partial/full/watchdog reset
  counts 4/0/4/0. The installed double-read provider returned the same values.
- Event history returned 210 valid charge terminations (last cycle292), 18 Qmax
  updates (last179), 3267 resistance updates (last292), 4 resistance disables.
  BAT0 cycle_count independently returned292. These qualify the compatible
  exact-target layout, not independently induced safety-fault behavior. Recorded
  safety counts were zero; they are not present-alarm readings.
- The last discharge-short-circuit and resistance-disable cycle fields extend
  past the qualified prefix and remain unavailable. No missing high byte is
  padded or inferred. Power-event fields remain unavailable on older drivers.
- The runtime prefix stayed145047 during 203 seconds spanning several fresh
  queries. This establishes neither its units nor its update cadence; a slow
  flash-backed update remains possible. No seconds/hours conversion is published.
- A fixed PD received-data probe on both endpoints returned alert/extended/status
  payload lengths4/0/4, compared with4/24/7 in the older public controller manual.
  No extended identity or external temperature was decoded from incompatible
  data. No discovery/4CC/reset/role/charger command was sent.
- Seven monitor JSON attributes rejected manual ownership, including cached data.
  Automatic fan mode, platform profile, charge limit, keyboard and four UEFI
  hashes were preserved. Runtime/kernel source identity and MOK CMS checks passed.
- Vitals adds36 recorded-event/reset rows. Fresh actual Sensors/Values GJS checks
  exercise113 rows total; the reviewed helper update preserves owner code.
  An ordinary new GNOME login is still required to load edited JavaScript.

The full port objective remains active. External adapter status/temperature,
complete gauge payload tails/cell-balancing/runtime format, exact specialty sensor
placements and actual absent-peripheral qualification remain open. EEPROM is a
firmware stub on this BIOS. Cold boot, enabled-Secure-Boot loading, physical
suspend/resume, nonzero live charger charging and external calibration are not passes.

# Qualification: 0.13.0, 2026-10-31

Installed on the same UP3404VA.301 / HealthyTable 15 machine. Signed DKMS and
runtime 0.13.0 retain all previous release sources for rollback.

- 90 Python tests passed. The optimized and ASan/UBSan suites passed 483 core
  assertions, 77 gauge-metric packet failures, 279 lifetime packet failures,
  292 PD identity communication failures, and the retained 146 input / 180
  extra-charger failure boundaries. All three Node adapters passed.
- Kernel W=1 build passed without code warnings. Compiler-name and missing BTF
  metadata notices are unchanged environment notices.
- All five corrected thermistor values matched independent EC cache reads:
  SSD 39, ambient 43, CPU 56, charger 46, DDR 37 degrees C in one paired check.
  The original selector 4 was restored. Fault tests cover restoration after a
  missing thermistor reply. The old loop duplicated the previous channel and
  omitted DDR; this is an implementation correction, not just a label change.
- Live battery gauge reads returned internal / TS1 / TS2 temperatures and
  selected cell/FET temperature. TS3/TS4 were off-scale and remained unavailable.
  BAT/PACK pin voltages and signed cell sample currents were exposed separately.
- Fresh lifetime prefixes returned cell extrema 4.436/4.439 V maximum and
  2.939/2.916 V minimum, 144 mV recorded imbalance, 7.274 A charge peak,
  9.590 A discharge peak, and cell/internal temperature ranges -2..46 / -2..49 C.
  These are gauge history, not present faults or independently calibrated values.
  The vendor of the physical OEM gauge remains unverified; the exact target
  identity/firmware and compatible layout are guarded. Runtime units, other
  lifetime layouts and byte 31 are not assigned unsupported interpretations.
- A private fixed read-only TCPC probe completed mode/source/identity reads on
  both endpoints, restored all mailbox bytes and restored the installed driver.
  The installed received-identity reader works; both direct identity records
  had status zero, so VID/PID/XID remain ENODATA. No discovery, role, reset,
  controller-setting or 4CC command was sent.
- All seven public charger/PD/gauge JSON attributes rejected manual ownership
  with EBUSY, including cached data. Automatic mode was restored. Profile,
  charge limit, keyboard and the four UEFI record hashes were preserved.
- Fresh GJS exercised actual Vitals Sensors/Values: 77 rows (57 Battery,
  7 Processor, 13 Storage), including formatted battery temperatures and historical
  peaks. Existing panel favorites were read back unchanged. An ordinary new
  GNOME login remains necessary to load edited JavaScript in Shell.

Remaining gaps: exact ACFET/choke/connector/upper-CPU/specialty GPU placements,
external adapter temperature and extended status, identities not supplied by
this connection, the BIOS's stub EEPROM interface, unqualified lifetime fields
and absent WWAN/XG Mobile hardware. Nonzero live charger charge-current ADC,
external meter calibration, cold boot, enabled-Secure-Boot loading and physical
suspend/resume remain separate unperformed qualifications. Raw device receipts
and proprietary firmware/disassembly remain outside Git.

# Earlier qualification: 0.12.0, 2026-10-31

Same exact UP3404VA.301 / HealthyTable 15, kernel 7.0.0-38-generic; Secure Boot
owner-disabled. Signed DKMS/runtime 0.12.0 installed. Older releases retained.

- 80 Python tests; 481 core transport assertions in optimized/ASan/UBSan builds,
  including 122 source-cache read-failure boundaries; 146 input ADC and 180 extra
  charger failure boundaries in both builds; both Node decoders passed.
- Kernel W=1 build passed with no code warnings. The installed C ABI returns
  the complete fourth source PDO (409925) without privilege.
- Public 0444 JSON/hwmon expose charger die temperature, VBAT-pin and system
  voltage, charge/discharge ADCs, state and realtime protection. Manual ownership
  rejects all four charger/PD snapshots with EBUSY; automatic fan mode restored.
- Profile, charge cap, keyboard brightness and all four UEFI hashes preserved.
- Installed minute timer produces sanitized, root-owned SSD health. Current wear
  3%, spare 100%, critical mask/media errors/error-log count zero. Historical
  unsafe shutdowns and temperature-duration counters are not current faults.
- A 151-sample physical capture observed A → none → B → none → A. Five B samples
  contained all four complete advertised PDOs. Nine stable offline samples
  suppressed source profiles and input values. The reads are sequential and
  cached: transition rows can straddle cable changes/firmware detection; no atomic
  or instantaneous unplug guarantee is claimed. One report took 6.802 seconds.
- Battery discharge ADC returned 3.108–6.0384 A. Two ADC-disabled samples correctly
  reported unavailable channels. Charge ADC returned zero with a full battery;
  nonzero charging is untested. VBAT pin is labelled separately because its
  value differs from the BMS pack reading. No external calibration is claimed.
- Fresh independent GJS exercised the actual Vitals Sensors/Values classes:
  32 Battery, 7 Processor and 13 Storage rows. All three groups are enabled.
  Current Shell requires the next ordinary logout/login to load changed JS.

No forced throttling, charger setting, role reset, factory record, EC firmware,
or power-policy change was used. Remaining hardware/provider boundaries:
cable identity/extended source status, ASUS EEPROM diagnostics, specialty
physical thermal labels, missing WWAN/XG Mobile, nonzero charging and external
meter accuracy. Cold boot, enabled-Secure-Boot loading and physical suspend/resume
remain unverified. Private raw receipts stay outside Git.

# Earlier qualification: through 0.11.1, 2026-10-30

Test machine: ASUS Zenbook Flip UP3404VA, BIOS .301, HealthyTable 15,
Ubuntu 26.04, Linux 7.0.0-38-generic. Secure Boot is owner-disabled.
This is one-machine qualification, not a claim about other ASUS platforms.

| Check | Result |
| --- | --- |
| Portable protocol tests, optimized and ASan/UBSan | 353 assertions in each run, passed |
| Python behavior/failure tests | 67 passed |
| Kernel W=1 build | passed; no code warnings |
| Original export inventory | 252 names, explicit routes/evidence/parity classifications |
| Prior 0.8.1 native read audit | 230 operations: 189 values, 41 explicit unavailable results |
| Unexpected implementation/dispatch errors | zero in that prior read audit |
| Installed native C client | live fan RPM and utility result; EACCES for privileged call |
| Reversible installed API controls | five same-value writes/readbacks passed |
| Bounded full-speed regression | 4015 to 6213 RPM; worker and parent restored automatic |
| Module signature | CMS verification against existing enrolled MOK passed |
| Profile, charge cap, keyboard brightness | preserved |
| UEFI factory records | hashes unchanged; no factory mutation executed |
| USB connector metadata | 21 ACPI port packages, complete walk |

A successful value can be zero or an empty inventory. It does not establish the
presence of an external device. Unavailable results include the firmware's
nonresponding ASUS adapter bank/wattage and EEPROM queries, absent WWAN
and XG Mobile devices, and specialty temperature channels with no validated
physical provider. The sensor-mask API now successfully returns the BIOS's
empty mask through the correct DSTS 0x60068 query.

XG feature transactions, malformed replies, device-number reuse, EOF/handle
cleanup and exact device selection have synthetic protocol tests. No actual
GC31/GC33 is connected. UEFI field updates have simulated revision/layout,
backup/preservation, stale-plan, immutable restoration and failure tests;
actual factory mutations were intentionally not part of qualification.

The first unprivileged installed C-client check found a root-only staging
folder. The installer now explicitly sets runtime directories to 0755 and
runtime files to 0644; a deployment regression test covers installation and
idempotent permission repair. The final installed client passes.

Remaining physical validation: cold boot, Secure Boot enabled loading, physical
suspend/resume, a connected XG Mobile/WWAN device and a new login activating the
optional GNOME compositor bridge. Main/aux antenna physical labels, neutral
board sensor locations and raw battery-lifetime interpretation remain unproven.
Raw audit receipts and hardware identifiers are kept outside this repository.

## Additional sensors

The CPU-voltage fallback was first verified by reading MSR 0x198 on the logical
processors without any MSR write. The driver now exposes CPU 0's P-state
voltage as read-only in6_input (0444). Installed API/hwmon and an independent
/dev/cpu/0/msr read both returned 1104 mV in the final qualification pair;
sequential reads can differ as the processor changes P-state. These are
CPU-reported values, not an independently measured rail voltage. The standard
ASUS WMI voltage query remains unsupported but no longer blocks the native API.

The report now aggregates 18 additional existing Linux hwmon readings: CPU
package/cores, NVMe sensors, Wi-Fi and ACPI. Those source labels are preserved;
the nine unvalidated specialty component locations remain unavailable.

Read-only UCSI GET queries identify a count-prefixed PDO payload. Complete
objects decode to 5 V/3 A, 9 V/3 A and 15 V/3 A; a fourth object is truncated.
The BIOS returns the same payload for offset/count and source/sink/local/partner
selector variations, so these are unverified firmware diagnostic profiles.
The tool reports target_verified=false and does not infer a negotiated contract,
charger maximum rating or actual draw. Live VBUS/current counters remain zero
and are represented as unavailable. Controller part number: TI TPS65994BF.

## EC charger port in 0.9.0

The adapter now has a working native alternative to UCSI and the unavailable
ASUS adapter bank. ACPI RDER reads a fixed set of contract-cache addresses.
The cache layout, parser and clearing paths were checked against this machine's
EC firmware code. Only selected recovery evidence is stored privately;
proprietary firmware images and disassembly are not repository contents.

Both EC ports report the stock adapter's 20 V / 3.25 A / 65 W fixed contract,
raw PDO 0x00064145 and whole-watt cache 65. The physical owner test captured
port A, unplugged with no contract, port B, then port A again; Linux type-C
partner presence independently matched each connector. One transition sample
returned EAGAIN because the two snapshots differed. No stale contract was
accepted during the observed unplug interval. The installed ordinary-user
CLI successfully elevated and reported the port B contract during that test.

Tests cover partial/unknown schemas, invalid status bytes, inconsistent PDOs,
unsupported supply types, stale data after unplug, independent port selection,
ambiguous contracts, fixed-address bounds and read errors. Factory/configuration
hashes remain unchanged and fan automatic was independently restored after a
bounded full-speed regression. No raw EC/SMBus/controller write was executed.
The installed native C contract-PDO API returned the actual PDO, and independent
CMS verification passed against the existing enrolled MOK. Repository kernel
and runtime files exactly match the installed source/runtime.
The original contract-PDO API now uses the EC alternative; the unrelated
proprietary PDO-watt, sufficient/champion ratings and source/cable/ADC queries
retain their explicit unavailable results. This is useful contract telemetry,
not full controller feature parity or instantaneous power measurement.

BIOS flash (32 MiB, read-only provider) and CMOS NVRAM (114 bytes) are exposed
by Linux NVMEM. The new inventory reads only metadata, not storage contents.
These providers are separate from the unsupported ASUS EEPROM diagnostic table.
No factory records or firmware contents were changed. Firmware hashes, profile,
charge cap and keyboard state were preserved during both driver installations;
the final build passed a full-speed/automatic regression with independent
restoration.

## PSYS and Vitals in 0.10.0

The public pd_contract and power1_input attributes are mode 0444. The installed
contract API works unprivileged. PSYS direct-MSR samples matched Linux's
energy_uj deltas in two intervals; installed power1_input returned 31.773849 W
against independent Linux sampling at 31.773798 W. No model-based current or
power estimate is provided. An external meter has not been used to validate
board calibration.

All 67 Python tests, 353 optimized/sanitized protocol checks, the Node Vitals
decoder test and a local W=1 build pass. New cases cover energy-counter wrap,
stopped counters, bounded sampling gaps, overflow-safe arithmetic, public
monitoring privilege, unavailable data and preserving existing Vitals edits.
A fresh GJS process read 13 actual adapter rows and formatted 3.25 A, 65.0 W
and measured platform power (27.7 W in the recorded smoke sample).

Vitals is active in the current session, but its updated JavaScript awaits
the next logout/login: GNOME 50's native ReloadExtension returns NotSupported
and the current instance cannot be claimed to use the new source. Existing
panel favorites are preserved. No Shell unsafe mode or logout was triggered.
The installed module signature verifies against the enrolled MOK, installed
kernel/runtime match the repository, and the bounded fan regression restored
automatic mode in both worker and parent. Existing power profile, charge cap,
keyboard brightness and four UEFI hashes were preserved.

## Read-only charger-access investigation

A temporary signed probe compiled with W=1, matched four 0x92 reads to the
known RDER cache, then read six fixed SMBus status/staging registers. All ten
kernel EC transactions returned success. The probe completed in 0.153 seconds
and unloaded itself through its parent cleanup. Fan mode stayed automatic,
RPM stayed 3546 and the native PD snapshot was unchanged. This was a controlled
read-only transport qualification, not a charger-ADC transaction test.
The installed release remains 0.10.0 with the documented ADC limitation.

## Direct charger input ADC in 0.11.0

The native firmware-mediated probe read manufacturer/device 0x0049/0x000e,
Control3 0x4003, and the fixed ADC registers. It restored and independently
verified all ten volatile request bytes and returned to the installed driver.
The firmware adapter DAC half-scale conversion and battery-current conversion,
with Control4's 2:1 shunt setting, qualify the board's 10 milliohm input scale.
No charging setting, direct host bus-controller write or EC firmware update was used.

The signed 0.11.0 DKMS/runtime was installed and read back. CMS signature
verification against the enrolled MOK, exact source/runtime comparison,
installed C contract API (409925) and 0444 monitoring modes passed. PSYS
21.627701 W matched the independent Linux conversion at 21.624370 W.
The bounded full-speed fan test restored automatic control through both
worker and parent; profile, charge cap, keyboard and four UEFI hashes matched.

The owner physically unplugged the stock charger, connected the other USB-C
port, and returned it to the original. A 17-sample capture observed A → none →
B → none → A. Three port-B samples returned ADC measurements; all four offline
samples were unavailable. One transient EAGAIN sample (masked as ENODEV by Python text buffering) was rejected while
connected, so the provider does not promise an uninterrupted stream. The
snapshot/identity/error checks suppress values on any failed request.
Observed connected samples spanned 6.99–51.81 W; a new fresh GJS process read
15 actual Vitals rows, including 19.7 V / 2.13 A / 41.9 W and 37.2 W PSYS.
Current Shell JS remains cached until the next normal login.

71 Python tests, 353 existing C assertions in optimized/sanitized builds,
146 charger communication-failure injection points in both builds, Node ADC
and contract tests, and the W=1 module build passed. The load check overlapped
the physical unplug and hit its thermal stop gate, so it is not an isolated
charger-vs-load calibration. External meter accuracy, enabled-Secure-Boot
loading, cold boot and physical suspend/resume remain unverified.

A subsequent 20-sample run returned 14 values and six unavailable reads.
Independent unbuffered reads identified the actual errno as EAGAIN: input
voltage changed beyond the one-step consistency threshold. Version 0.11.1
adds at most two fresh V/I/V retries without relaxing that threshold, plus
unbuffered Python reads that preserve the actual errno. Fault tests cover
both successful retry and persistently changing voltage; retries are bounded.

The installed 0.11.1 follow-up returned 20/20 fresh valid snapshots with no
unavailable reads, spanning 13.10688–51.553728 W. CMS signature, exact installed
kernel/runtime equality and the C contract API passed again. PSYS34.006721 W
matched Linux34.004921 W. All three charger monitoring interfaces returned
EBUSY during a bounded manual-fan check and worked again after automatic mode
restoration. Profile, charge cap, keyboard and UEFI hashes remained unchanged.
The additional Python errno-regression test brings the current count to72.
