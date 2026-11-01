# Threat model

This document summarises the threat model behind the 0.78–0.83 hardening
releases. It is derived from a source review of the kernel module, a privilege
review of the userspace stack and a static-analysis pass (all November 2026),
plus the owner decisions that shaped the privileged service. It describes the
design and its known limits; it is not a certification. Physical
qualification limits are tracked separately in `docs/VALIDATION.md`.

Terms: *EC* is the embedded controller; *ECMT* is the firmware's ACPI mutex
that serialises EC access between AML methods (battery, thermal, lid) and this
driver; the *EC broker* is the EC's SMBus worker, reached through a volatile
EC RAM mailbox, that talks to the charger, the USB-PD controllers and the
battery gauge.

## 1. Assets

| Asset | Why it matters |
|---|---|
| Fan and thermal safety | Firmware automatic fan control must come back after any loss of ownership (crash, unload, suspend, disconnect). |
| Charger, PD and gauge state | The project performs no charger configuration writes; the shared volatile mailbox must be restored after every session. |
| Kernel memory safety | Under Secure Boot with lockdown, even root should not be able to corrupt the kernel through this driver. |
| EC/ACPI availability | Holding ECMT for long stalls firmware battery, thermal and notify paths. |
| Firmware/factory data | EFI GPNV fields and EEPROM tables must not change without a reviewed, backed-up, read-back plan. |
| Privacy | Battery, adapter and cable identifiers; board serials and UUIDs; Wi-Fi location fingerprints; window titles. |
| Side channels | RAPL/PSYS energy counters (Platypus-class), P-state voltage. |
| Root integrity | The userspace stack must not hand unrestricted root to a compromised user session. |

## 2. Components and trust boundaries

| Component | Trust | Notes |
|---|---|---|
| Kernel module `zenbook_healthytable` (`source/`) | Trusted computing base | Port I/O to the HealthyTable mailbox, `ec_transaction()`, ECMT, ACPI `RDER`/`_UPC`, WMI, CPU0 MSR reads. Probe requires an exact DMI and BIOS match. |
| Privileged service `zenbook-hardwared` (`service/`) | Trusted, sandboxed | uid 0 with `CAP_PERFMON` only; D-Bus activated; polkit per call. |
| Root CLI (`sudo zenbook-hardware`) | Trusted | Direct in-process recovery path; bypasses the service. |
| Unprivileged CLI, C library (`lib/`), `api_bridge.py` | Untrusted callers | Route privileged requests to the service; never elevate themselves. |
| Exporter units (`systemd/`) | Trusted, sandboxed | Write sanitised world-readable caches for SMART and Wi-Fi data. |
| GNOME bridge (`gnome-bridge/`), Vitals (`integrations/vitals/`) | Session code | Run inside gnome-shell; read sysfs, caches and the service. |
| EC firmware | Semi-trusted peer | Same vendor as the BIOS, but has its own concurrency and returns every byte the driver parses. |
| ACPI/WMI firmware | Semi-trusted | Returns integers, packages and buffers whose length the firmware chooses. |
| Charger, PD controllers, battery gauge | Less trusted | Replaceable parts behind the EC broker. |
| External USB-C partners (adapters, cables) | Untrusted | Their PDOs, identity VDOs and extended messages reach the kernel indirectly through the PD controllers. |

Trust boundaries:

1. **User ↔ kernel**: sysfs mode bits (checked by kernfs at `open()`).
2. **User ↔ service**: D-Bus system bus policy (only root and `zenbook-hw`
   members may send) plus a polkit check on every method.
3. **Kernel ↔ firmware/hardware**: every value returned by the EC, ACPI, WMI,
   PD controllers and gauge is treated as untrusted input.
4. **Root ↔ kernel/hardware** (lockdown model): root is trusted, but driver
   allowlists, not root's goodwill, must prevent arbitrary EC or charger
   writes and kernel memory corruption.

## 3. Attackers

### A1. Unprivileged local user (any uid, including sandboxed apps with sysfs access)

Goals: drive EC/SMBus traffic, flood the EC, read side channels or
identifiers, starve the driver lock.

Mitigations:

- Attributes that start EC broker/SMBus sessions, the RAPL/PSYS energy
  counters and battery/PD identity attributes are root-only (0400). Vitals and
  the CLI read them through the service's `VitalsMetrics()`/`Metrics()`
  (owner decision: exposure was narrowed in the same release that moved the
  consumers, 0.79). Code: attribute modes and `ht_visible` in
  `source/zenbook_healthytable.c`.
- World-readable attributes are telemetry, fan and plain EC-port reads, with
  per-feature caches; ECMT and handle failures are cached too, so errors do
  not bypass the rate limit.
- Non-members of `zenbook-hw` cannot send to the service at all (bus policy).

### A2. Compromised process in the owner's session (same uid, possibly a `zenbook-hw` member)

Examples: a browser sandbox escape, a package install script, a malicious
extension, an agent tool.

Before 0.79 this attacker could read the stored sudo password and become
unrestricted root. Mitigations now:

- The Secret Service sudo-password route is removed; the tool stores and
  reads no credential (`auth.py` route removed; plain interactive `sudo`
  remains for recovery).
- A `zenbook-hw` member is limited to the group-granted actions: reads,
  identifier reads, profile/charge-limit/keyboard settings within validated
  ranges, and fan leases of at most 300 s with automatic restoration. EC/OEM,
  firmware and driver actions need `auth_admin` (no `_keep` for EC/OEM and
  firmware). Code: `service/49-zenbook-hardware.rules`,
  `service/org.zenbook.hardware.policy`, `service/authorization.json`.
- Caller-computable plan digests never authorise an apply through the service;
  applies use single-use, 60 s tokens bound to the caller's bus name, uid,
  action, export, arguments and a recomputed plan. Code: `service/hwd_core.py`.
- Raw EC writes (`WOA_EC_write`) also need a root-owned policy file that is not
  installed. Code: `native_oem.py`.
- Per-uid rate limits, a bounded worker queue, 64 KiB argument limit, strict
  JSON parsing (duplicate keys and NaN rejected), and `AUDIT` journal lines
  for every mutating call, denial, plan/apply and lease event.
- `record`/`SaveEcLog` output is created by the unprivileged client (or, as
  root, through a no-follow directory walk and owned by the invoking user), so
  a swapped symlink cannot redirect a root file creation.
- The C library spawns the bridge with `python3 -I -B`, a fixed environment,
  closed inherited fds and a 60 s deadline, so a caller's `PYTHONPATH` or fds
  cannot inject code into a privileged caller's child.
- The GNOME bridge is a session-bus service; see residual risk R7.

### A3. Root

Root is trusted, but the design aims for two properties even against root:
no arbitrary EC/charger writes and no kernel memory corruption through the
driver.

- Kernel writes accept only range-checked values (`kstrtouint`, pwm 0..255,
  enable 0..2, 32-byte OEM requests with ABI, reserved-word, flag and per-op
  range checks). EC addresses come only from fixed tables; read addresses are
  allowlisted per feature. Code: `source/healthytable_oem.h`,
  `source/healthytable_core.h`.
- OEM ops that can mutate state, including the WMI DEVS EEPROM selector op,
  require the explicit apply flag.
- Module removal and shutdown set a `removing` flag that blocks every write
  path and watchdog re-arm, disable the watchdog synchronously and retry the
  automatic-fan restoration with readback (fixes a use-after-free and
  manual-fan-left-on race found in review). Code: `ht_remove` and the
  teardown helpers in `source/zenbook_healthytable.c`.
- The service itself runs under a systemd sandbox (`NoNewPrivileges`,
  `ProtectSystem=strict`, `ProtectHome`, `PrivateNetwork`, `PrivatePIDs`,
  `SecureBits=noroot-locked`, system-call filter, writable paths limited to
  specific sysfs files) and refuses to start if any part of its runtime tree is
  a symlink, not root-owned, or group/world-writable. Code:
  `service/zenbook-hardwared.service.in`, `service/zenbook_hardwared.py`.

### A4. Malicious or buggy firmware and peripheral data

Sources: EC replies, ACPI `_UPC` packages, WMI buffers, PD controller length
bytes, gauge blocks, external USB-C partner messages.

- Every length and count is bounds-checked before copy or emit: WMI EEPROM
  buffer size, magic and frame length; `_UPC` package shape and value ranges;
  PD length bytes against fixed buffers; PDO count 1..7; gauge string lengths
  and printable-text checks; sentinel-checked fixed frames. Code:
  `source/healthytable_eeprom.h`, `healthytable_pd.h`,
  `healthytable_pd_identity.h`, `healthytable_gauge_block.h`,
  `healthytable_sbs.h`.
- Structures emitted to userspace are zero-initialised; cached buffers are
  emitted only when their status is success. JSON emitters use
  `sysfs_emit_at` with worst-case sizes well below `PAGE_SIZE`.
- External partner bytes are emitted only as hex.
- Mailbox sessions require the shared mailbox to be idle, restore every
  touched byte with readback, and have per-collector time budgets with stall
  detection. A failed restoration or stall latches a fault that disables
  further controller requests until reload (fail closed).
- Userspace parsers validate types, ranges and sizes and reject malformed
  input (for example DOCTYPE/ENTITY in D-Bus introspection XML, duplicate JSON
  keys). Parser fuzz tests run in CI when present (`test_fuzz_parsers.py`).

## 4. Hardware safety invariants

| Invariant | Enforced by |
|---|---|
| Automatic fan is the default and is restored | Kernel watchdog (mode change, RPM below `max(baseline/2, 500)`, I/O error); suspend aborts if restoration fails; removal/shutdown retry with readback; service lease end, expiry, disconnect, low RPM, read failure, daemon stop and crash marker. |
| Mailbox left idle | Idle precondition, full restore with readback, fault latch. |
| No charger configuration writes | No charger register write path exists; charger reads use a fixed index allowlist. |
| No unreviewed factory writes | Plan, revision check, private backup, readback; not performed by the service. |
| Bounded ECMT hold | Per-collector budgets, stall detection, bounded restore. |

## 5. Residual risks

Ranked roughly by impact. "Owner-gated" means it requires physical access to
the qualified machine or an owner decision.

- **R1. Secure Boot/lockdown not enabled on the qualified machine.** The
  module is signed through DKMS with an enrolled key, but loading it with
  Secure Boot enforced and kernel lockdown active has not been qualified. The
  driver has no `capable()` or `security_locked_down()` checks; under lockdown
  root keeps the allowlisted write set (fan, board thermistor selector, cache
  refresh triggers, allowlisted OEM ops). The allowlists, not lockdown, prevent
  arbitrary EC writes. *Owner-gated.*
- **R2. Debug-kernel run pending.** The lifecycle fixes (removal races, ECMT
  budgets) are verified by review, unit tests with fakes and sanitizer builds
  of the shared headers, not yet by a KASAN/lockdep/KCSAN kernel on the real
  machine. *Owner-gated.*
- **R3. Firmware-dependent findings that source review cannot settle:**
  - whether AML or the EC itself uses the HealthyTable I/O ports or the 0xde
    gauge broker concurrently with the driver (no shared lock exists for the
    plain port protocol);
  - whether the EC broker worker can complete after the driver has restored
    the mailbox following a timeout (stall detection and the idle precondition
    reduce, but do not eliminate, this);
  - the exact semantics of the allowlisted WMI DEVS EEPROM selectors (treated
    as mutating and apply-gated until proven read-only).
- **R4. Fan left manual if every teardown restoration attempt fails.** Removal
  retries with readback, but `remove()` cannot fail; if the EC refuses every
  attempt, the fan stays in its last manual state with no watchdog. Bounded
  fan-off by root through `pwm1` is likewise accepted under the root-trusted
  model.
- **R5. Unbounded unprivileged work on a few world-readable attributes.** At
  the time of writing, some world-readable attributes (for example the ACPI
  `_UPC` namespace walk and CPU0 frequency/voltage MSR reads) are not cached,
  so a tight read loop costs AML execution or IPIs on CPU0. Availability
  impact only.
- **R6. Kernel writes are not audited.** Root writes to sysfs produce no
  record; only the service audits its own calls. A root-opened fd passed to
  another process keeps write access (standard kernfs behaviour).
- **R7. GNOME bridge and session data.** The bridge publishes window
  information on the session bus to same-uid clients; consumers check only
  the owner's uid. Same-uid code can already observe most session state, so
  the bridge is a convenience boundary, not a security one. The bridge's
  caller allowlist (`trusted_scripts`) cannot stop processes running as the
  same user: its configuration and the extension directory are user-writable,
  so same-uid code can add itself or replace the extension. The allowlist only
  filters other callers on the session bus.
- **R8. Service runs as uid 0.** It holds no capability except `CAP_PERFMON`
  (read-only performance monitoring, which includes side-channel observation)
  and is confined by the sandbox and `PrivatePIDs`, but a dedicated system user
  would remove uid 0 entirely. Not done yet.
- **R9. Group membership is the gate for unattended automation.** By owner
  decision the polkit rule does not require a local or active session, so any
  process running as a `zenbook-hw` member can use the group-granted actions.
- **R10. Wi-Fi cache location fingerprinting.** The Wi-Fi cache is
  world-readable and includes signal strengths. Access-point grouping keys
  must stay salted with a root-only per-boot secret (`wireless_native.py`): an
  unsalted hash of BSSID and frequency can be brute-forced and geolocated by
  any local account.
- **R11. Physical qualification gaps.** Cold boot, suspend/resume with
  manual fan ownership, fold transitions, enabled Secure Boot and some
  peripheral classes are listed as pending in `docs/VALIDATION.md`.
  *Owner-gated.*

## 6. Verification in CI

`.github/workflows/check.yml` runs, on every push and pull request:

- `userspace`: `make check` (C protocol tests with ASan/UBSan, Python tests,
  parity check);
- `kernel`: module build;
- `kernel-static`: `W=1 -Werror`, sparse, gcc `-fanalyzer`, substantive
  checkpatch (blocking), full checkpatch (advisory);
- `c-static`: cppcheck warnings and gcc `-fanalyzer` on the userspace library
  (blocking);
- `python-static`: bandit Medium+ with a reviewed baseline and the ruff
  correctness/security set in `tools/ci/ruff.toml` (blocking); broad ruff and
  mypy (advisory);
- `clang-analyzer`: clang static analyzer on the library and protocol test
  harnesses (advisory);
- `parser-fuzz`: parser fuzz tests when `test_fuzz_parsers.py` exists
  (blocking).

Hardware tests are never run in CI.
