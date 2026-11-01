# Native Linux API

## Privileged service (0.79)

`zenbook-hardwared` owns `org.zenbook.Hardware1` on the system bus (object
`/org/zenbook/Hardware1`, interface `org.zenbook.Hardware1`). It runs as root
from the versioned runtime (`/usr/bin/python3 -I -B <runtime>/service/zenbook_hardwared.py`),
imports the existing providers in-process and exits after 60 s idle. It is
started only by D-Bus activation; the unit has no `[Install]` section. Non-root
CLI and C ABI callers route privileged operations to it (see "Client routing"
below); root CLI use (`sudo zenbook-hardware ...`) stays the direct, in-process
recovery and rollback route.

### Client routing

A non-root caller whose request needs privilege (`compat.needs_root`) no longer
elevates with sudo. The CLI, `api_bridge.py` and therefore `asus_ht_call` send it
to `org.zenbook.Hardware1` (python3-gi GDBus) and decode the same envelope, so
results, JSON shapes, exit codes and errno values equal the direct path.
Root callers never use the bus.

| Caller | Route | Polkit interaction |
|---|---|---|
| root (`sudo zenbook-hardware ...`) | direct in-process (unchanged) | none |
| non-root CLI | service | allowed (`ALLOW_INTERACTIVE_AUTHORIZATION`) when stdin is a terminal or `DISPLAY`/`WAYLAND_DISPLAY` is set; `--non-interactive` disables it |
| non-root `api_bridge.py` / C ABI | service | never; denial is `EACCES` (return 1 with the envelope) |

- Service unavailable (no name owner, activation failure, no python3-gi): the
  bridge and C ABI report `EACCES` with `privileged service unavailable; run with
  sudo`. The CLI prints the same message and exits 1. Only with the explicit
  `--sudo-fallback` option does it re-run the command with plain interactive
  `sudo` (no stored credential).
- Polkit denial: `EACCES` (also mapped from
  `org.freedesktop.PolicyKit1.Error.NotAuthorized` and `...DBus.Error.AccessDenied`).
  Lease errors `org.zenbook.Hardware1.Error.<ERRNO>` keep their errno.
- Client-side exports (`SaveEcLog`/`record`, `TraceOutput*`, `WMISetAppPath`)
  run unprivileged in the client. A non-root `record` therefore reports the
  root-only raw EEPROM data as a typed unavailable entry; `sudo zenbook-hardware
  record` keeps the complete log.
- Firmware writes (`apply` on GPNV/OEM-language exports), `StopWinIoDriver`
  apply, `InitializeWinIo` with the module absent and `metrics --refresh-ssd`
  are not sent: `EACCES` (C ABI) or a "requires root; run with sudo
  zenbook-hardware" error (CLI). Their plans still go to the service.
- `WMISetQuietFan`, `WMISetBatteryHealthToUser` and the CLI `profile` command:
  the service applies the hardware setting; the client then records the choice
  as the user with the existing revision-checked preferences code and returns
  the direct path's result (`"remembered":true`, `preferences`, recovery and
  `hardware_restored` semantics). `client_persistence` is consumed, not shown.
- CLI `fan` as non-root: `auto` calls `SetFanAuto`; `full` or a percentage holds
  a lease for `--duration` seconds (1..300, default 60; requested from the
  service with a 1 s expiry backstop), then releases it. Ctrl-C, SIGTERM or
  SIGHUP release early; if the process dies the service restores automatic on
  disconnect. Output is one JSON object with the start state and a `lease`
  object (`id`, `seconds`, `request`, `reason`, `automatic_restored`,
  `mode_after`). Root `fan` keeps the direct sysfs write and ignores
  `--duration`. One-shot `HealthyTable_SetFanPwmDuty`/`SetFanTestMode` API calls
  from a non-root caller hold no lease and get the service's `EPERM`
  (`{"manual":false}` is allowed).
- Root-only driver attributes (0.79): `Thermal_Read_CpuPackagePower`, the seven
  `BatteryHealthy_Read_*` lifetime exports, the five battery identity exports,
  the e-marker identity exports and `Adapter_Read_PD_ADO` with
  `native_alert:true` now need privilege and are routed. PDO source capabilities,
  `Adapter_Read_Contract_PDO` (cached `pd_contract`) and `CPU_ReadCpuVoltage`
  stay unprivileged. Non-root `show`, `metrics` and `record` take
  `cpu_package_power`, `battery_identity`, `battery_gauge`, `battery_lifetime`,
  `battery_gauge_extra`, `battery_sbs`, `battery_sbs_diagnostics`,
  `usb_pd_identity`, `charger_input`, `charger` and `platform_power` from
  `Metrics()`; other sections stay local (the service sandbox has no netlink or
  SMART). `power` and `charger` use `Control`. If the service is unavailable or
  refuses, a one-line notice is printed and the local typed-unavailable values
  remain.
- An unprivileged caller may point `DBUS_SYSTEM_BUS_ADDRESS` at another `unix:`
  bus (tests); the C ABI passes that variable only for non-root, non-setid
  callers. Routing is refused inside the service process itself.
- `~/.config/zenbook-hardware/auth.json` and the Secret Service sudo route are
  removed. If the file exists, privileged CLI routes print a one-line notice; the
  file is not read, changed or deleted, and no keyring is accessed.

### Methods

| Method | Signature | Polkit action |
|---|---|---|
| `Call(name, args_json, apply, expected_sha256)` | `ssbs -> s` | per export, from `service/authorization.json` |
| `PlanMutation(name, args_json)` | `ss -> s` | the export's action (`ec-oem`/`firmware`/`driver`) |
| `ApplyMutation(token)` | `s -> s` | the token's action, re-checked |
| `Metrics()` | `-> s` | `read` |
| `VitalsMetrics()` | `-> s` | `read` |
| `Control(command, args_json)` | `ss -> s` | `settings` for `profile` `{"value":"quiet|balanced|performance"}`, `charge-limit` `{"value":0..100}`, `keyboard` `{"value":0..3}` and the sysfs triggers `reprobe`, `battery-history-refresh`; `read` for `battery-gauge`, `charger` `{"connector":1|2}` (optional), `usb-activity`, `power` |
| `AcquireFanLease(seconds, request)` | `us -> s lease_id` | `fan-lease` |
| `ReleaseFanLease(lease_id)` | `s -> s` | none; only the holder's bus connection (or uid 0) |
| `SetFanAuto()` | `-> s` | `read` (restoring the safe state ends any lease) |
| property `Version` | `s` | none |
| signal `FanLeaseEnded(lease_id, reason)` | `ss` | |

`Call`, `Metrics`, `Control` and `SetFanAuto` return the C-bridge envelope:
`{"ok":true,"result":...}` or `{"ok":false,"error":{"errno":N,"message":...}}`,
with `control`/`configuration_committed` when the provider supplies them. The
errno mapping is the same as `api_bridge.py` (tested for equivalence). Service
refusals use: `EINVAL` invalid name/JSON/digest (duplicate keys and NaN are
rejected), `E2BIG` arguments over 64 KiB, `EACCES` polkit denial or polkit
unavailable (fails closed), `EAGAIN` rate limit, `EBUSY` too many queued
requests, `ETIMEDOUT` provider call over 45 s, `EPERM` manual-fan export
without a lease or `Call` apply without a token, `EOPNOTSUPP` operations the sandbox cannot or must not do.
Lease methods report failures as D-Bus errors
`org.zenbook.Hardware1.Error.<ERRNO-NAME>` (for example `...Error.EBUSY`).

`expected_sha256` is empty or 64 lowercase hex digits. `Call` with
`apply=true` on any plan/apply export (`native_oem` mutations, EFI writes,
`StopWinIoDriver`) is refused with `EPERM`: the caller-computable digest alone
never authorises an apply through the service. Use the token flow instead:

1. `PlanMutation(name, args_json)` authorises the export's action, computes the
   provider plan and returns it with `service_token` (128-bit, single use,
   `service_token_expires_in`=60 s) when the service can apply it
   (`service_apply_supported`). The token is bound to the caller's unique bus
   name, uid, action, export, canonical arguments and the plan digest. One
   outstanding token per connection and export; at most 64 overall.
2. `ApplyMutation(token)` checks the binding (a foreign caller gets `EACCES`
   and does not consume it), consumes the token, re-runs polkit (`ec-oem` is
   `auth_admin` without `_keep`), recomputes a fresh plan (current model/BIOS
   and, for EFI fields, current variable bytes) and refuses with `EAGAIN` if
   its digest differs, then applies with that digest. Unknown, used or expired
   tokens give `ENOENT`.

The root direct path (`sudo zenbook-hardware api ... --apply --expect-sha256`,
`api_bridge.py` as root) keeps its existing digest semantics.

Exports the service refuses with `EOPNOTSUPP`:

- `WMISetAppPath`, `SaveEcLog`, `TraceOutput`, `TraceOutputCritical`: they write
  the caller's configuration, a caller-chosen path or journal entries that must
  carry the caller's identity, so they stay in the unprivileged client.
- Driver load (`InitializeWinIo` while the module is absent): no
  `CAP_SYS_MODULE`.

Firmware writes and `StopWinIoDriver` can be planned, but their plans carry no
token (`service_apply_supported=false`): they need `CAP_LINUX_IMMUTABLE`, the
backup directory or `CAP_SYS_MODULE`, which the service does not hold.

`WMISetBatteryHealthToUser` and `WMISetQuietFan` apply and read back the
hardware setting only. They return the control result plus
`"remembered":false` and `"client_persistence":{"field":...,"value":...}`; the
client records the choice as the user, because the service has no home access.

`VitalsMetrics()` returns the same envelope with only the `Metrics()` sections
that `integrations/vitals/service.js` converts: `battery_gauge`,
`battery_lifetime`, `battery_gauge_extra`, `battery_sbs`, `usb_pd_identity`,
`charger_input`, `charger`, `platform_power` and `cpu_package_power`, plus
`schema: 1`. They come from the same provider functions as `metrics.report()`
(a test checks both the section list against `service.js` and the providers
against `metrics.py`). Expensive walks (`ec_diagnostics`, wireless, firmware
queries, SMART cache, thermistors, adapter tables) are excluded. A failing
section becomes `{"available":false,"errno":N,"error":...}` without hiding the
others. Like `Metrics()`, the reply is cached for 2 s in a cache shared by all
callers. Hits are answered on the main loop without the worker, and concurrent
misses coalesce into one provider run (at most 64 waiters).

### Fan leases

`request` is `full` or a decimal percent `0..100` (CLI mapping
`duty=(percent*255+50)//100`); `seconds` is 1..300. One lease exists at a
time, and only from firmware-automatic mode (`EBUSY` otherwise). While a lease
is held, its holder may also use `HealthyTable_SetFanPwmDuty` and
`HealthyTable_SetFanTestMode` through `Call`; `{"manual":false}` is always
allowed. The service restores `pwm1_enable=2` with readback on release,
expiry, holder disconnect (`NameOwnerChanged`), low RPM (below
`max(baseline/2, 500)` RPM, the kernel watchdog's formula, checked every
second), a fan read failure, daemon stop (SIGTERM/SIGINT/SIGHUP) and, through
the lease marker `/run/zenbook-hardware/fan-lease.json`, after a crash
(`ExecStopPost=--restore-fan-auto` and the next start). If another agent
returns the fan to automatic, the lease ends without another write. Failed
restoration keeps the marker and is retried every second. The kernel driver's
own low-RPM watchdog stays independent.

### Polkit actions (`/usr/share/polkit-1/actions/org.zenbook.hardware.policy`)

| Action | any / inactive / active | Exports |
|---|---|---|
| `org.zenbook.hardware.read` | no / no / yes | all other exports, `Metrics`, read controls, `SetFanAuto` |
| `org.zenbook.hardware.read-identifiers` | no / no / auth_admin_keep | `WMIGetSN`, `WMIGetType2SN`, `WMIGetBoardUUID`, `WMIGet90Number`, `WMIGetMacAddress`, `RF_AP_MAC`, `BatteryHealthyTable_SerialNumber`, `GPNV_Get_RandomUUID` |
| `org.zenbook.hardware.settings` | no / auth_admin / auth_admin_keep | `WMISetBatteryHealth`, `WMISetBatteryHealthToUser`, `WMISetQuietFan`, profile/charge-limit/keyboard controls, `reprobe` and `battery-history-refresh` triggers |
| `org.zenbook.hardware.fan-lease` | no / no / auth_admin_keep | `AcquireFanLease`, `HealthyTable_SetFanPwmDuty`, `HealthyTable_SetFanTestMode` |
| `org.zenbook.hardware.ec-oem` | no / no / auth_admin | `native_oem` mutations including `WOA_EC_write`, and raw `WOA_EC_read` |
| `org.zenbook.hardware.firmware` | no / no / auth_admin | `GPNV_Set_*`, `GPNV_Clear_CSC_Repair_Flag`, `Update_AsusOsLanguage` |
| `org.zenbook.hardware.driver` | no / no / auth_admin | `InitializeWinIo`, `StopWinIoDriver` |

`WOA_EC_write` additionally stays subject to the root-owned
`/etc/zenbook-hardware/allow-raw-ec-write` policy file. The polkit subject is
always `system-bus-name` (the caller's unique name, not a PID). Interactive
authentication is requested only when the caller sets
`ALLOW_INTERACTIVE_AUTHORIZATION` on its message.

`/usr/share/polkit-1/rules.d/49-zenbook-hardware.rules` returns `YES` for
members of the `zenbook-hw` group for `read`, `read-identifiers`, `settings`
and `fan-lease` only. EC/OEM, firmware and driver actions keep `auth_admin`
for everyone. By owner decision (2026-11-01) the rule deliberately does not
require `subject.local` or `subject.active`, so unattended automation without
a logind session (user services, agents) keeps working; group membership is
the gate. The installer creates the group (`groupadd --system`), adds no
members, and if the group already exists prints its members (including
primary-group members) as a warning instead of adopting it silently.

The D-Bus policy lets only root own the name and only root and `zenbook-hw`
members send to it; everyone else is denied by the bus (`<deny>` in the
default context). Polkit is still checked for every method, so `read`'s
`allow_active=yes` matters only for those callers.

`test_service_core.py` fails if any `capabilities.json` export lacks an action,
if the table names an unknown export or action, or if an EC/OEM, firmware or
driver export maps to a group-granted action. The service also refuses to
start when the table and `capabilities.json` disagree.

### Limits, caching, audit and sandbox

- Requests: name `[A-Za-z0-9_]{1,128}`, arguments 64 KiB, one provider worker
  with at most 8 queued requests and a 45 s reply bound. Each job records its
  own start time; any job still running after 120 s makes the service restore
  the fan and exit (it is restarted on demand).
- Caching: successful `read`/`read-identifiers` results are cached per
  (export, canonical arguments) for 2 s, and `Metrics`/`VitalsMetrics` for 2 s (shared by all callers; concurrent misses
coalesce). Fan reads
  (`HealthyTable_FanRPM`, `HealthyTable_FanCounts`, `HealthyTable_GetFanTestMode`,
  `HealthyTable_Read_Fan`, `Thermal_Read_Fan`, `ProArt_Read_Fan`) and all
  mutations are never cached. Polkit runs on every call; cache hits are then
  answered on the main loop without the worker, so a slow provider call does
  not delay them. Lease supervision also runs on the main loop.
- Rate limits per caller uid: reads 20/s (burst 40), mutating actions 2/s
  (burst 10). Slow class, on average one refresh per 10 s with a burst of 3,
  per uid and globally, for `GetEEPROM_Data`, the firmware-cache reads
  `BatteryHealthyTable_BatteryInformation`, `BatteryHealthyTable_PFStatus`,
  `BatteryHealthyTable_SafetyStatus` and `BatteryHealthy_Read_PFStatus`, and
  the controls `reprobe`, `battery-history-refresh` and `charger` (UCSI).
  Slow reads avoid `EAGAIN` where possible:
  - The last successful result for the same (export, arguments) is served for
    10 s from a separate slow cache.
  - Concurrent identical requests join one in-flight refresh.
  - Reads of the same firmware cache form one shared refresh group. `PFStatus`
    and `SafetyStatus` both read `battery_gauge_status`; the PF cache, battery
    information and EEPROM table are their own groups. After a group refresh,
    the group's other reads in the next 10 s run without spending budget, each
    at most once because of the slow cache.
  - Without budget, one refresh is queued for up to 5 s until the buckets
    refill.

  `EAGAIN` is returned only when no cached result exists and the budget would
  not refill within 5 s. A full CLI `show` (three groups) fits in the burst.
  The trigger controls do not queue and return `EAGAIN` instead. A refusal
  does not consume the caller's token.
- Every call to a mutating action (including its denial or refusal), every
  plan/apply and every lease event writes one `AUDIT {json}` line to the
  journal with event, uid, sender, action, name or command, apply, argument key
  names, result, errno and at most 8 characters of a token. Argument values,
  results and provider messages are never logged.
- Message size: the bus delivers messages up to its global limit; per-service
  limits cannot be set from a `system.d` file without changing the limit for
  the whole bus. The service rejects arguments over 64 KiB before parsing, and
  only root and `zenbook-hw` members can send to it at all.
- Code integrity: the service runs with `-I -B`, sets
  `sys.dont_write_bytecode` and a nonexistent `sys.pycache_prefix` (so no
  `__pycache__` bytecode is read or written), and as root refuses to start if
  any path below the runtime (including `__pycache__`) or any parent directory
  is a symlink, not root-owned, or group/world-writable.
- Restart: `Restart=on-failure` with `RestartSec=2s` growing over
  `RestartSteps=5` to `RestartMaxDelaySec=60s`; `StartLimitBurst=10` in
  `StartLimitIntervalSec=300`, so abuse delays activation for at most five
  minutes rather than disabling it.
- The unit (`/etc/systemd/system/zenbook-hardwared.service`) limits
  `CapabilityBoundingSet` and `AmbientCapabilities` to `CAP_PERFMON` alone and
  adds `SystemCallFilter=perf_event_open`, which `@system-service` does not
  include. `@debug` is not denied as a group (that would override the allow);
  its other members (`lookup_dcookie`, `pidfd_getfd`, `ptrace`, `rtas`,
  `s390_runtime_instr`, `sys_debug_setcontext`) are denied by name. `WMIGetGPUUsg` opens the system-wide i915 engine-busyness PMU, and
  this system's `perf_event_paranoid` requires `CAP_PERFMON` for that. It is
  ambient because uid 0 under `SecureBits=noroot-locked` gets no capabilities
  otherwise. It grants read-only performance monitoring (including side-channel
  observation), inherited by the few fixed helper tools the providers execute.
  No other capability is held. The unit also has `NoNewPrivileges`, `ProtectSystem=strict`,
  `ProtectHome`, `PrivateTmp`, `PrivateNetwork`, `PrivatePIDs`,
  `RestrictAddressFamilies=AF_UNIX`, `SystemCallFilter=@system-service` minus
  privileged/resource/mount/module/raw-io groups and `MemoryDenyWriteExecute`.
  `/sys` and `/proc/sys` are read-only except paths that do not depend on the
  hwmon index, generated by the installer. The first is the driver's hwmon
  container `/sys/devices/platform/zenbook_healthytable/hwmon`. The platform
  device is registered without an id and the hwmon device is its child
  (`devm_hwmon_device_register_with_info(&pdev->dev, ...)`), so the container
  holds only the `hwmonN` instance. The service writes `pwm1`, `pwm1_enable`,
  `diagnostics_reprobe`, `battery_lifetime_refresh` and `oem_request` there;
  DAC still blocks the 0444 attributes, and the only other owner-writable
  nodes are `battery_history_refresh`, `uevent` and `power/*`. The rest are
  exact files: `platform_profile`, BAT0 `charge_control_end_threshold`
  (canonical ACPI path), the keyboard LED `brightness` and the UCSI debugfs
  `command` file. The unit records the container in
  `ZENBOOK_HWMON_CONTAINER`. If the hwmon device is ever found elsewhere, the
  service logs a warning and `tools/install.py --service-only` regenerates the
  unit. Mounts are set up at each start, so a new `hwmonN` after a reboot or
  module reload needs no reinstall; a module reload while the service runs
  takes effect at its next start (60 s idle exit). The only device is
  `/dev/usbmon0` (read), plus, read-only, exactly the input device(s)
  advertising `SW_TABLET_MODE`. The installer finds them from
  `/sys/class/input/event*/device/capabilities/sw` (bit 1) and writes their
  stable `/dev/input/by-path/*-event` symlinks as `DeviceAllow=` entries; on
  the qualified machine that is `platform-INTC1078:00-event` (Intel HID
  switches). systemd resolves the symlink when the service starts, so a
  renumbered `eventN` is followed. Other input devices (keyboard, touchpad,
  lid) stay denied. Without a by-path link, tablet mode stays a root/sudo-only
  read.
- uid 0 without capabilities can still signal other uid-0 processes (no
  `CAP_KILL` is needed for the same uid). `PrivatePIDs=yes` puts the service in
  its own PID namespace, so it cannot see or signal them. Future work: a
  dedicated system user (`User=zenbook-hw-svc`) with udev rules or ACLs that
  grant exactly the listed attributes (re-applied after `diagnostics_reprobe`
  and module reloads) would remove uid 0 entirely. It needs kernel-side group
  permissions or a udev `RUN` chown, and it is not done yet.
- Unavailable inside the service, which reports an error instead: the SMART
  fallback (`smartctl`), the i915 perf PMU for `WMIGetGPUUsg`, netlink-based
  wireless queries, the XG Mobile hidraw device, `modprobe usbmon`, and
  per-process `/proc` data (`PrivatePIDs`).
- Sandbox denials: when a provider fails with `EPERM`/`EACCES`, or a
  successful report contains rows with those errnos (for example every PMU
  engine unavailable), the service logs
  `AUDIT {"event":"sandbox_denied","name":...,"count":N}` (or the whole-reply
  `errno`), without values or messages, so such regressions show up in the
  journal. The integration tests check this marker. The unprivileged client or the existing
  exporters provide those data.
- `MemoryDenyWriteExecute` and PyGObject: callbacks use libffi closures. At
  every start, before owning the name, the service runs a GLib callback self
  test; `zenbook_hardwared.py --self-test` runs it alone. If it fails because
  libffi lacks static trampolines, the service logs "PyGObject callback
  self-test failed" and exits. In that case copy
  `service/zenbook-hardwared-mdwe-off.conf` from the source tree to
  `/etc/systemd/system/zenbook-hardwared.service.d/50-mdwe-off.conf` and run
  `systemctl daemon-reload`. In this repository's tests the integration run
  passes under `MemoryDenyWriteExecute` plus the unit's system-call filter, in
  a transient user unit.

Installation and rollback: `make install` also writes the polkit, D-Bus and
unit files and the daemon code lives in the versioned runtime. Each file is
refused if an unrelated file exists. The step is transactional: if any write
or reload fails, every written file is restored to its previous content or
removed (the group, if created, is kept). `tools/install.py --without-service`
skips the step, `--service-only` regenerates it for the installed runtime of
this version, and `--remove-service` removes only these managed files
(retaining runtimes and the group) to return to a service-less release.


## Gauge-reported pack power in0.68

The unprivileged metrics CLI/report now includes battery_gauge_extra, battery_sbs
and cached battery_sbs_diagnostics beside the existing legacy gauge report.
Each provider retains its own availability and sample age; these are separate
acquisitions. A failed provider does not erase other available sensor groups.

battery_gauge_extra preserves gauge_power_watts directly from the signed DA1
pack field at bytes28..29, scaled from centiwatts. It remains gauge-computed
battery-side power, separate from charger-input ADC and PSYS; no local power
estimate replaces a register. The report adds gauge_power_raw_centiwatts,
gauge_average_power_raw_centiwatts and power_sum_comparison (cell_sum_watts,
pack_minus_cell_sum_watts, time_alignment_verified=false,
used_as_validity_gate=false). Values outside the existing200W field bound remain
unavailable, while their raw words stay visible. Invalid cell power affects that
cell, independently of valid pack/average fields.

Pack uses gauge SBS Voltage()*Current(); each cell uses its own simultaneous
V/I pair. The reply does not establish a shared sampling instant, so a5percent
cell-sum agreement is not a validity condition. Sum comparison is diagnostic.
Identity, complete frame, cache age, two-cell topology and per-cell scale checks
remain. Vitals Battery Gauge Power displays the same reported field. Existing
labels/counts/preferences are retained; owner Shell activation remains separate.

## Disk temperature identity in0.67

WMIGetHDDTemp remains a root-only, no-argument physical-disk query. Each row
is a Celsius value with source and identity_verified=true, or typed unavailable
without celsius. Metadata and results are bracketed by sysfs device identity,
64-bit diskseq and matching block dev_t/node identity; hwmon names, inode and
real ancestry are rechecked. Changing inventory is EAGAIN. A replacement before
publication discards that disk's value while preserving other verified devices.

The provider uses associated nvme/drivetemp temp1_input first; otherwise it
retains smartctl -A -j -n standby,3,5 without a permissive retry. The subprocess
may open a disk; autodetection/SCSI bridges do not guarantee no spin-up. The
module itself only stats device nodes. No discovery, scan, reset or block write.
One call has a10-second read budget, per-SMART timeout at most8 seconds and
at most64 physical disks. Missing diskseq is explicit EOPNOTSUPP; unknown
metadata, ambiguous hwmon providers and failed samples are never zero degrees.

## E-marker ID header in0.66

Adapter_Read_PD_Get_Emark_VID keeps its default16-bit vendor ID. With
{"raw_header":true} it returns the complete unsigned32 ID Header VDO,
matching all four bytes returned by the original ASUS function. raw_header is
a strict boolean available only on this query; optional connector remains1/2.
The native received-identity report adds id_header_raw_vdo beside vendor_id and
raw_vdos_hex. No vendor bits or product-type bits are lost or conflated.
A missing/pending/short/invalid acknowledgement remains typed unavailable,
including when raw_header is requested. No discovery or controller write occurs.

## HDMI presence and stable WWAN reads in0.65

RF_USBHDMIIsUsed with no arguments, or {"metric":"hdmi_presence"}, reads
unprivileged cached DRM HDMI-A/B connector status. The schema1 object includes
hdmi_connected (true/false/null), count (exact only with complete coverage),
minimum_count, coverage_complete and per-connector availability. A known
positive remains true with partial failures; unknown-only evidence remains null.
No HDMI connectors in a readable DRM inventory gives false/0. No DRM provider
is ENODEV. Connection/identity changes are rejected. The hdmi CLI is equivalent.
No USB ancestry, EDID, enabled mode or visible picture is required or asserted.
DP/Type-C transport alone does not identify a downstream HDMI adapter.

{"metric":"usb_display"} retains the separate USB/Type-C schema documented
below. Existing clients needing usb_display must request this metric explicitly.

WWAN schemas remain unchanged. Calls bind all getters and bounded object-name
introspection to one existing unique ModemManager owner, then recheck inventory
and owner. SIM changes invalidate home-provider results; state, access technology,
quality and signal-setup changes invalidate the corresponding radio result.
EAGAIN rejects mixed context. Introspection reads names/signatures, not private
identifier/property inventories. No connect/enable/scan/polling mutation occurs.

## Disk predicate and USB measurements in0.64

`RF_USBIsTranster` defaults to the original disk-activity quantity despite its
name: integer disk-time percent strictly greater than20 on non-system disks.
Native schema1 uses measured Linux queue-weighted I/O time, exposes raw before/
after counters, separate busy percent, root exclusions and per-disk availability.
`active` is true with a qualified positive, false with complete known negatives,
or null if only incomplete evidence exists. Root-backed disks are identified via
kernel partition/slave topology. Unknown root mappings fail rather than guessing.
Windows synthetic `_Total` and cross-OS counter calibration are not reproduced.
`zenbook-hardware disk-activity` and the default API require no root.

Actual USB measurement remains available through `zenbook-hardware usb-activity`
or `RF_USBIsTranster` with `{"metric":"usb_traffic"}`; those reads require root.
Only successful bulk/isochronous completion headers contribute, with no payload
request. `sample_seconds` is measured; `requested_seconds` is the nominal window.
Dropped/backlogged/capped capture or ISO frame errors set `capture_complete` false,
`bytes` null and retain `observed_successful_bytes` as a lower bound. A positive
observation can prove activity; incomplete zero evidence yields `active` null.
This is completion accounting, not electrical USB bus bandwidth.

`WMIGetSDCardSize` keeps its scalar total by default. Optional `{"detailed":true}`
returns `total_bytes`, `cards` (device/bytes/model/card_type/source) and provenance.
No-card is a known zero/empty list. Per-card records preserve the information the
original last-match Windows buffer lost; no media probe or raw block read occurs.

## Wireless observations in0.63

`RF_WiFi_2_4G_AP_Ch_Num` returns `channels`, `channel_groups` and `total_aps`.
`channels` retains every observed primary channel, including14; `channel_groups`
has explicit `1`, `6`, `11` and `other` counts. AP totals count unique BSSID/frequency
pairs across receivers.5/6GHz group APIs retain labelled U-NII counts, band total
and `unclassified`; a cache census does not establish complete physical RF coverage.

All six cached-count APIs use the existing NetworkManager owner/inventory and
fixed properties, with kernel netdev identity, scan and per-BSS identity/frequency
brackets. The shared deadline is8 seconds, individual waits at most3 seconds.
Replacement, malformed data, changed scan or expiry is an error, never a false zero.
A genuinely scanned empty cache is a valid zero; never-scanned empty is unavailable.
Only fixed `GetDevices`, `GetAllAccessPoints` and property `Get` reads occur. See the
[NetworkManager method and LastScan semantics](https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.Device.Wireless.html).

BSSID, connected state, primary channel and signed dBm remain independent link
reads. `RF_WiFi_Main_Aux_Rssi` reports actual chain/aggregate dBm with explicit
unverified physical Main/Aux mapping. It does not duplicate aggregate RSSI as two
antenna measurements. `WMIGetWiFiBytesPersec` detailed mode preserves separate
receive/send byte rates; its default map is the explicitly documented RX+TX sum.

## Fan and charge-control ranges in0.62

`HealthyTable_SetFanPwmDuty` accepts byte0..255 and returns `requested_pwm`,
`stored_pwm`, `request_readback_verified`, `mode` and `deferred_while_automatic`.
Automatic mode stores a request without applying manual duty. A concurrent writer
can change readback; the verification field reports that difference explicitly.
`HealthyTable_SetFanTestMode` accepts a boolean and returns `requested_manual`,
`mode`, `mode_readback_verified` and the stored `requested_pwm`. Native mode0 is
full speed/manual, mode1 manual, mode2 automatic. Unknown modes never verify auto.
The CLI `fan` accepts requested percentages0..100, mapped to a byte with nearest
rounding. Firmware codes, actual RPM and electrical PWM are separate quantities.

Kernel ownership and the one-second low-RPM/fault watchdog remain active, with
verified automatic restoration on faults, suspend, removal and shutdown. Raw fan
register writes cannot bypass it. Manual mode has no general timer lease; callers
conducting a bounded test must arrange their own independent restoration deadline.
The one qualified native channel uses logical index0; its raw firmware selection1
is not changed by `HealthyTable_SetFanIndex`. Other fan channels are unqualified.

## CPU package power in0.61

`Thermal_Read_CpuPackagePower` and `power` are now unprivileged. The structured
result retains `watts`/`sample_seconds` and adds availability, scope and complete
energy/time evidence. It reads the package containing logical CPU0, using fixed
MSR611 energy and MSR606 units. It is distinct from platform PSYS and USB-C input
ADC draw. No energy reset, mailbox write or power-limit update is exposed.

`cpu_package_power` publishes a schema1 energy/time snapshot and `power3_input`
publishes microwatts with its label. A successful sample is cached for less than
one second. Counters use actual elapsed time, with one32-bit wrap handling;
intervals that could hide additional wraps at the1000W accepted ceiling are
rejected. Counter faults, stopped counters, read latency over10ms, invalid ages
and incomplete data remain unavailable. Suspend/resume invalidate the baseline.
The native frontend allows one120ms warmup retry. Other CPU/model variants remain
unqualified. `show`/`metrics` include the report; Vitals adds a Processor row.

## Raw PDO availability in0.60

`Adapter_Read_PDO` uses index0..6; fixed wrappers `Adapter_Read_PDO1` through
`Adapter_Read_PDO7` select those same slots. Optional connector1/2 selects one
active source; two active sources require explicit selection. Missing slots
return ENODATA, rather than zero or an original transport-error sentinel.

All source objects remain available when the active contract is nonfixed.
Those objects and active-contract identifiers remain explicitly raw and
unconverted. Fixed-supply limit conversion retains its existing consistency
checks; unknown supply types never acquire guessed voltage/current/power units.
AC/port-validity gates, complete source count/padding, active-object membership
and repeated-read coherence remain required. Vitals source-profile rows retain
raw nonfixed objects. Physical nonfixed-contract qualification is still pending.

## CPU frequency and XG replies in0.59

`CPU_ReadCpuFrequency` now returns CPU0's reported P-state multiplier times
reference MHz; `CPU_ReadCpuMaxFrequency` returns its single-active-core turbo
ratio times the same reference. The read-only `cpu_reported_frequency` hwmon
attribute samples CPUID.16H and MSRs198/1ad on CPU0, with independent field
errors. Missing/invalid values stay unavailable. The API takes no arguments.
No MSR or overclocking-mailbox write is performed. These are reported ratios,
separate from effective clock measurements and a maximum across CPUFreq policies.
Other CPU/firmware families remain unqualified.

`show` and `metrics` expose `cpu_reported_frequency` with explicit CPU, reference,
raw fields and units. Existing `cpu_frequencies` retains separate per-policy
CPUFreq metadata. Scalar `show` frequency aliases follow the corrected API.
Vitals adds two labelled Processor rows through ordinary read-only sysfs access.

`GetXgmFw` retains its fixed GC31/GC33 firmware-only query. The opened HID handle
must still match the vendor/product and complete ff31/0076 collection descriptor
before any feature request. A complete64-byte reply is required; only firmware
bytes2..32 (31 bytes) are returned, matching the original copy boundary. Native
`firmware_raw_hex` therefore contains31 bytes, and `firmware_payload_bytes` is31.
Physical responding-device qualification remains pending.

## Component versions and application registration in0.58

`GetInfVersion` takes no arguments and reports the installed ASUS system-control
platform driver selected by the real `asus-nb-wmi` binding. The native result is
schema1 metadata with `driver`, `module`, `module_file`, `version`, `version_kind`,
`declared_module_version`, `kernel_release`, `in_tree`, component, device and source.
An explicit module version uses `declared_module_version`; a versionless in-tree
driver uses its verified current-kernel release, labelled `kernel_release`.
Versionless out-of-tree modules, missing providers and invalid/changing metadata
remain typed errors. The query runs bounded read-only modinfo requests against
the selected current-kernel file, bracketing its identity and the device binding.
It never loads or unloads a module.

This is distinct from `GetDriverVersion` (loaded HealthyTable module version),
`GetRefCount` (its actual kernel module references) and `GetIoDllVersion` (native
frontend version). No frontend constant substitutes for an installed driver.
The native metadata object replaces Windows INF/registry formatting; Wine ABI
compatibility remains outside scope.

`WMISetAppPath` keeps its absolute installed-executable/desktop-file `path`,
review-plan and explicit-apply interface. File validation and all configuration
I/O now run as the actual caller, including sudo/effective-root callers, using
the same custom configuration context as saved preferences.
Workers use that account's UID, primary GID and registered groups; inherited
privileged groups are not carried over. `compat.json`
requires an owned0600 regular file without hard links in a private owned directory.
Reads/plans create nothing. Updates lock, recheck a content revision, preserve
unrelated keys and atomically replace/read back a bounded JSON record. Its
`expected_sha256` now covers actual file bytes, or a distinct absent-file state;
older canonical-object plans require a fresh review. Known identical settings
are unchanged. The application is only registered, never executed. Authentication
and remembered hardware choices remain separate files.

Configuration errors expose `configuration_committed`: `false` when no update
was committed, `true` when replacement happened before an error, or `null` when
a lost worker reply leaves the result uncertain. Read the saved record before
retrying an uncertain update.

## Native OEM wrappers in0.57.1

The WOA-named native logical byte APIs require exactly `address_space`, `bank`,
`register` and, for a write, `value`. Only the explicit `healthytable` namespace
is accepted. Read and write parameters are distinct; extra/missing keys and
invalid byte/bank values fail before privilege elevation. CPU-voltage and
PD-controller-name reads take no arguments. The contract-PDO selector retains
its optional connector1/2 and negotiated-limit semantics.

Raw-write plans bind `recipe_revision:3` and include the exact `wire_bank`,
register and byte value under `protocol_recipe`. Other fixed OEM controls
retain revision2. Older raw plan digests cannot authorize the revised operation.
The primitive no longer reads an unrelated bank6 byte as a capability test.
Qualified bank limits, fixed packet allowlist, protected fan/cache selectors
and explicit reviewed apply remain mandatory. Missing bank6 is still rejected
before port I/O; no arbitrary hardware write is performed for qualification.

Applied OEM results distinguish `transport_completed:true` from
`firmware_acknowledged:null` and `readback_verified:false`. The fixed write path
has no firmware reply. `applied` records that the reviewed operation was sent;
it does not establish the resulting hardware state. A failed/partial transport
remains an error. No physical factory/raw write is used to test this metadata.

CPU voltage remains the original Intel driver's MSR0x198[47:32] quantity,
expressed in mV. Native rounding can differ from the original truncation by1mV.
It is a CPU-reported P-state value, with explicit source, rather than a separate
voltage-rail ADC. Independent native MSR reads and the installed public hwmon
provider use the same bitfield and scale. No voltage control is exposed.

## OEM control recipes in0.56

Reviewed OEM mutation plans now include `recipe_revision:2`, bound into their
digest. The monitor/notify and power-flag read-clear plans include
`protocol_recipe` descriptions. A previous recipe's plan digest cannot authorize
the corrected operation. Execution still requires explicit apply and the exact
reviewed digest; no mutation occurs while planning.

`Power_Set_Monitor_PowerDropped` accepts native integer `value`0/1. The command
byte is5/133, separately from that user setting. It requires protocol19+.
`Adapter_Read_Power_Data_Flag` reads the complete flags byte, then clears it:
protocol14..23 uses the legacy whole-flag clear, while24+ writes only the
observed mask to the bit-clear register. Real0/255 masks are retained. A new
flag arriving outside the observed mask survives the newer recipe. Transport
failures remain errors, including failure after reading or partially clearing.
`Adapter_Set_Notify_Control` requires23+, while the existing adapter clears,
charger read/clear and12-byte PD-controller-name read require14+.

The qualified .301 firmware has no DD bank6/7 handlers. Those controls therefore
remain unavailable before port I/O. Corrected positive recipes are source/fixture
qualified, not new physical support or a broader model allowlist. No firmware
command, factory write or notification policy is applied merely for testing.

## Saved user choices in0.55

`WMISetBatteryHealth` accepts only integer `percent`0..100 and immediately
sets/verifies the Linux charge-threshold attribute. The ASUS driver checks firmware
acknowledgment, then caches that setting; this is not an independently measured
physical charging cutoff. `WMISetBatteryHealthToUser` also
records the verified successful selection for the caller. `WMISetQuietFan`
accepts only `profile` (`quiet`, `balanced`, `performance`), verifies the native
platform profile and records it. The direct CLI `profile` command shares this
behavior; `charge-limit` remains immediate-only. The setter APIs require root.

`zenbook-hardware preferences` reads `$XDG_CONFIG_HOME/zenbook-hardware/preferences.json`
(default caller home `.config`), returning schema1, `values`, content `revision`,
`exists`, `owner_uid` and path. The optional values are
`battery_charge_limit_percent` and `platform_profile`. This is a record of
successful choices, not a claim that the current hardware still matches them.
There is no automatic battery-limit reapplication, boot service or policy loop.
The existing desktop Power Profiles daemon observes native profile changes and
retains its own persistence, holds, actions and power-limit ownership.

User-file access runs as the current UID, or the actual `SUDO_UID` account after
dropping root and supplementary groups. Elevation retains the caller's custom
configuration directory. Records/locks require owned0600 regular files without
hard links, inside an owned private directory. Reads are bounded; updates lock,
check the reviewed revision, merge only known fields and atomically replace the
record. Read-only missing-file queries create nothing. `compat.json` app-path
registration and authentication configuration remain independent.

Invalid preferences fail before the hardware write. If saving fails afterward,
structured CLI/C errors include `control` with the hardware result and restoration
status. Only a known uncommitted failure with unchanged preferences and matching
device/value allows conditional compensation. Unknown commit status, a changed
revision or a later external hardware selection is retained for explicit review.
A lost save reply can be recovered by independent successful record readback.
All control/lifecycle parameters are validated before authentication; unknown
or missing keys are rejected.

`RF_Net_Connected_Type` returns a native report with `available`, `complete`,
`connected`, `primary_type`, `preferred_known_type`, `connected_types`, ordered
`priority`, per-interface observations and errors. Each interface marks `scope_applicable`;
known virtual devices and analog-only modems are outside the type preference. Supported type labels are
`ethernet`, `wwan` and `wifi`. It reports connected physical media; it does not
claim Internet access or select a route. Virtual/tunnel links are excluded.
Unknown active classifications can prevent a definitive preferred type; useful
known observations remain visible with partial coverage. A changing inventory
invalidates the summary. The query takes no arguments and changes no settings.

`RF_BTConnectedType` retains its connected-device rows and adds `device_class`:
`available`, raw24-bit `raw`, `major_code`, `major` and source, or explicit
missing/invalid metadata. Known connection counts remain independent of this
optional property; Bluetooth LE devices may omit it. `RF_BTConnectedNum` and
`RF_BTIsUsed` still report only confirmed connected rows. No inquiry or pairing.


Version0.51 field contracts: fan getters read only their own hwmon attributes;
`ProArt_Read_Fan` accepts optional integer `index` (default0), returning scalar
RPM. Other indices are absent on this single-fan qualified model. All other60
field reads reject arguments. Missing or denied independent providers remain
errors, rather than being replaced by unrelated snapshot data.

`EC_ReadEcFwRev` is a numeric family selector (65535 here), not the ASCII version
in `show.ec_info.firmware`. `EC_ReadEcChipName` is the original big-endian packed
four-byte word; `BatteryHealthyTable_ECChipName` returns all14 bytes as `data_hex`
plus optional ASCII `text`. Original chip ID remains a separate numeric byte.

`Battery_Read_DesignVoltage` has a misleading original name: it reads present
terminal voltage, returned in mV from Linux `voltage_now`. The low-level
`BatteryHealthyTable_DesignVoltage` retains nominal EC design voltage.
`Battery_Read_DesignedCapacity` and `Battery_Read_FullChargedCapcity` use Linux
charge counters, returned in mAh. `Battery_Read_CapacityPercentage` returns
`percent`, `legacy_bucket_percent`, `remaining_mAh`, `full_mAh` and source/note.
The bucket truncates then rounds half-up to tens; exact percent is not clamped.
`Battery_Read_ManufactureDate` returns a validated ISO date; the low-level raw
packed date remains separate. `BatteryHealthyTable_ChargingCurrent` preserves
the original signed16 conversion, including -1mA. The native SBS target-current
metric retains its separate unsigned command semantics.

`BatteryHealthyTable_BatteryInformation` returns an opaque32-byte `data_hex`
frame with status, timeout, ready bit and `refresh_requested`. `BatteryHealthy_Read_PFStatus`
returns the little-endian U32 from the four-byte cache. Both require explicit
root reads; fixed original volatile refresh requests may occur. Firmware error,
busy, missing readiness, changing frames and transport failures return typed
errors. A ready cached frame does not establish independent measurement age.
`BatteryHealthy_Check_PFalarm` is the legacy cache bit7 AND NOT bit6 predicate,
not a separate physical fault measurement.

`WMICheckQuietFanSupport` returns `supported`, `quiet_enabled`, current `profile`
and actual `choices`; `WMIGetQuietFan` returns the current native profile string.
Battery-health APIs read actual Linux charge-threshold support/value, preserving
access errors. Thermal PL1/PL2 getters return configured package0 RAPL constraint
watts, selected by long_term/short_term names, independently of EC availability.


`capabilities.json` is the inventory of original ASUS names. Results are native
JSON values; no Windows struct, C++ string or COM ABI is exposed.

## Battery summary quantities

`BatteryHealthyTable_ECChipID` returns the original numeric BB10 chip ID, including
valid0. ASCII EC model/name bytes remain a separate chip-name value.

`Battery_Read_ASOC` returns the original full/design capacity fraction, without
percent conversion, rounding or clamping above1. Its native same-unit counters
are Linux charge_full and charge_full_design. This is the original wear/capacity
ratio; the Smart Battery AbsoluteStateOfCharge command has a separate meaning.
A zero design denominator or changed/unavailable counters produce typed errors.

`Battery_Read_Capacity` reports remaining charge as `{value,units:"mAh",quantity:
"remaining_charge",source,note}` from Linux charge_now, including valid zero.
It replaces the incorrect full-capacity alias. Windows BATTERY_STATUS capacity
uses mWh or relative units; no energy conversion or estimate is supplied here.

`Battery_Read_CellVoltage` reports all four source `cells`, each with `channel`,
`available`, `millivolts`, `raw_millivolts` and any error. Raw zero/sentinels retain
an unavailable measurement; they do not become measured zero volts or a physical
cell-count claim. `frame_complete` covers valid raw fields; `measured_channels`
counts positive voltage readings. Healthy channels survive missing/invalid peers.
Qualified EC identity/ownership checks remain mandatory. All four APIs reject
arguments and are read-only; no new firmware recipe is introduced.

## Firmware, processor, GPU and OS identity

Nine inventory reads now use dedicated providers instead of the generic sensor
snapshot. All take no arguments and need no elevation. The original names retain
their actual property selections, including their misleading naming:

| API | Native source/result |
| --- | --- |
| `WMIGetBiosManufacture` | Baseboard manufacturer, kernel `board_vendor` |
| `WMIGetModelName` | Baseboard product, `board_name` |
| `WMIGetComputerFamilyName` | System family, `product_family` |
| `WMIGetProductName` | System product/model, `product_name` |
| `WMIGetBiosVersion` | Native firmware `bios_version` counterpart of BIOS Name |
| `WMIGetBiosReleaseDate` | Validated `bios_date` as ISO calendar `YYYY-MM-DD` |
| `WMIGetCPUInfo` | First-processor model-name string |
| `WMIGetGPUInfo` | PCI graphics identities with local, ID-matched captions |
| `WMIGetOSInfo` | Distribution caption, kernel version and kernel ISA width |

Firmware placeholder/missing/denied/invalid fields stay unavailable. No family,
baseboard or vendor field falls back to an unrelated system-model field. Date
conversion does not invent a time or timezone. Native firmware version/PCI caption
counterparts are not asserted equal to live Windows driver/WMI display strings.

The GPU report has `adapters`, `present`, `selection_complete`, bounded selection
errors and a separate caption provider. Each adapter preserves numeric class/
vendor/device identity if its caption is unavailable. `caption_available` and
`caption_error` distinguish missing utility/database/name or mismatched identities.
Class03 PCI devices include unbound hardware; DRM binding is not required. Unknown
classes prevent complete absence claims. Device/class/census changes are rejected.
Caption lookup uses fixed read-only pciutils sysfs access, machine format and C
locale, without DNS queries/rescans/writes. Large native PCI domains are supported.
Non-PCI graphics remain outside this qualified PCI provider.

OS output separates `distribution`, `kernel` and `architecture`, with independent
availability and `complete`. Distribution fields come exclusively from /etc/
os-release, falling back to /usr/lib/os-release only if the former is absent.
Declarations are parsed without executing a shell, expanding variables or inventing
a default Linux caption. Missing optional fields remain null; duplicate keys use
the last value, invalid selected values stay unknown. File changes and malformed/
oversized encodings remain explicit. Kernel output excludes hostname. Kernel ISA
width is not inferred from the client executable or userspace word size.

`GetUWPVersion` reports the native frontend release and bundled bridge protocol4,
with Windows UWP explicitly inapplicable. Bundled protocol does not prove active
GNOME discovery; desktop APIs report actual session availability separately.

## CPU and firmware metadata

`CPU_ReadCpuId` accepts optional unsigned32-bit `leaf` and `subleaf` (defaults0).
It returns raw unsigned `eax`, `ebx`, `ecx`, `edx`, input leaf/subleaf and source.
The original query always used subleaf0; the optional subleaf is a native extension.
The scheduler chooses the calling CPU, so topology/cache leaves may vary. The
additive C ABI1 helper `asus_ht_cpuid(leaf, subleaf, uint32_t registers[4])` returns
0 or negative errno, with zeroed outputs on unavailable execution; NULL is EINVAL.
Unsupported leaves retain hardware-defined results. No module or root is needed.

`CPU_ReadCPUUsage` takes no arguments and returns a busy fraction0..1 over100ms;
`WMIGetCPUUsg` returns percent0..100 over its own interval. Native Linux idle includes
iowait; guest counters are not double counted. Invalid/regressed/zero intervals
are unavailable. `CPU_ReadRegCPUInfo` returns the first processor's model name
string. `WMIGetCPUArchitecture` returns the numeric architecture enum (x64=9,
ARM64=12), not a free-form machine string. This describes the native kernel ISA.

`System_Read_LocalTime` returns local `YYYY-MM-DD HH:MM:SS`. The root identity
queries return validated system UUID, system/product serial, baseboard serial and
exact fifth SMBIOS Type11 OEM string. Missing/placeholder fields are ENODATA;
ambiguous multiple OEM records are unsupported. `WMIGetSN` is a native firmware
system-serial counterpart; equality to a live Windows BIOS property is unproven.
`WMIGetSystemChassisTypes` returns raw `code`, ASUS `classification` and source:
Desktop3/13/35, Notebook10/30/31/32, otherwise unknown.

`WMIGetCardReaderCaption` returns matching cached USB0bda:0129 `readers`, `present`
(true/false/null), and `complete`. A complete negative differs from an unknown
USB census. `WMIGetMacAddress` returns device-backed `adapters`, per-address errors,
`complete` and the excluded software-interface count. Addresses are current link
addresses, which may be randomized; no permanent factory MAC claim is made.

## Desktop windows

`AppList_OpenWindows` accepts only optional boolean `include_titles` (defaultfalse).
A bridge4 report includes native normal Alt-Tab windows across all workspaces,
compositor identity, PID, application, focus/minimized state, and zero-based
`z_order` (0=topmost among selected windows). CPU percent uses one CPU100%; RSS
bytes and process name come from scoped procfs samples, with valid idle/zero rows
retained. Multiple windows of one PID share process totals; do not sum them as
independent window allocations. A new/reused/denied PID gets explicit unavailable
metrics. Window enumeration and process-metric completeness are separate.

The client pins existing same-user providers and never activates services. Bridge3
is supported with unknown stack/completeness. The direct existing-registry AT-SPI
fallback is partial and leaves compositor identity, stack, focus and minimized
state null. No provider yields `available:false`, not a known empty desktop.
Titles are read/returned only when explicitly requested and the desktop user has
opted in with `{"expose_window_titles": true}` in a private, user-owned
`~/.config/zenbook-hardware/bridge.json`; otherwise the request fails with `EACCES`
and titles are never fetched from AT-SPI instead. No process command lines,
environments, input events, Shell evaluation or logout/reload is used.

Bridge trust is mutual. The bridge answers only callers with the session UID whose
process is the system Python running the installed runtime (or a script listed in
`trusted_scripts`); this narrows the audience and is not a boundary against
same-user code. The client (`AppList_OpenWindows` and `GetNum_Key`) trusts the
bridge only when the pinned unique-name owner is a same-user `/usr/bin/gnome-shell`
process, otherwise `EACCES`.

## Registered software inventory

The six `GetApplist_*` / `App_Get_*App` inventory reads take no arguments and
return native package reports, replacing the old arrays. Native/WOW6432 names
select Debian ABI64/32; installed package state comes from db:Status-Status,
independent of the desired hold/install selection. Present but unconfigured
packages retain their state and `fully_installed:false`. Removed/config-files
entries are excluded. `architecture_independent` and `unclassified_packages`
are separate from selected `packages`; no architecture-independent record is
assigned a guessed width. ABI metadata uses dpkg-architecture; missing/unknown
metadata makes selection incomplete while preserving the registered records.

UWP-named reads return Flatpak apps, runtimes/extensions and all installed Snap
revisions. Flatpak rows identify branch, origin and user/system installation.
Snap active/retained status is explicit. Snap declared architectures come from
the matching installed revision manifest, with the snap format's default all
labelled when omitted/empty. Missing/inconsistent/unreadable manifests preserve
version/name with architecture unavailable; they never use the host architecture.
Optional PyYAML safely parses these manifests. Missing Flatpak versions are null,
with `version_available:false`; declared package architecture is not an ELF probe.

`providers` records each source's availability, errors and scope. `available`
means at least one requested source was read; `complete` covers collection and
selection, independently of optional field availability. A failed source differs
from a successful empty list. Valid records survive malformed peers; parse errors
are bounded to64 with total/truncation counts. dpkg is a system database; bundle
user scope follows registered Flatpak installations. Other users' private roots,
arbitrary executables and manual/unregistered apps are not inferred. Native
registered-package categories include components and do not emulate Windows
uninstall flags/string layouts. Queries request no install, refresh or store search.

## Process CPU and resident memory

`AppList_CpuUsage` and `AppList_MemUsage` take no arguments. Both now return
an object containing ranked `processes` plus sample/coverage metadata, replacing
the old unranked array. CPU selects up to five positive CPU values; memory selects
up to ten positive RSS values. Both include PID, kernel comm name, identity start
ticks, RSS bytes and CPU percentage when a baseline is available. Equal counters
sort by PID. Every PID visible in the caller's procfs namespace is considered;
there is no same-user filter or implicit elevation. Kernel comm names may be
truncated or have undecodable bytes replaced, labelled by `name_encoding_loss`.
No command lines or environments are read. Resident memory uses statm, bracketed
by matching stat identities; a failed memory read does not erase valid CPU.

CPU is user+system tick delta divided by a per-process monotonic interval, with
one CPU as100%. Multithreaded work may exceed100%; values are not clamped. This
is independent of the original library's /10 presentation constant. RSS is the
kernel statm resident-page counter times native page size, not unique/private
memory;
large values retain Python integer precision. Both queries wait0.2 seconds
between two sequential censuses. Per-process intervals, tick delta and total
read-window width accompany valid CPU values; a read uncertainty spanning the
interval is unavailable rather than a precise-looking percentage.

New/replaced PIDs, regressions, short intervals and missing/denied records are
explicit. A memory row may retain valid RSS with `cpu_available:false` and null
CPU percentage. `ranking_complete:false` means an unknown candidate might rank
higher. `sample_errors` has at most64 details with total/truncation counts.
`available:false` and errno ENODATA indicate no valid requested-counter candidates;
a valid empty/no-positive sample remains available. Initial/final PID counts and
new/exited/reused counts describe dynamic coverage, not an atomic global census.

## Display and audio configuration

`AppList_HardwareConfig` takes no arguments and returns `brightness` and
`volume` objects. Brightness contains `available` and per-device `devices`,
using the same actual/max kernel measurements as `WMIGetMonitorBrightness`.
Individual device errors remain visible. No backlight or an unreadable provider
is unavailable, not a fabricated zero; successful audio survives display errors.

Volume contains `available`, configured `percent`, `muted` and
`effective_percent` (zero when muted). `System_Read_VolumeLevel` uses the same
reader, retaining its existing percent/muted fields. Missing wpctl, provider
errors, timeout and malformed replies produce typed errors; the combined config
captures these in its volume object. PipeWire software gain may exceed 100% and
is not clamped. This session setting is not sound pressure or an application's
volume. Display/audio are sequential observations, not an atomic snapshot. No
brightness, volume, mute or routing setting is changed.

## CLI

`zenbook-hardware api NAME --args JSON` executes a read or ordinary reversible
control. Factory mutations and driver stop return a plan; execution requires
`--apply --expect-sha256 DIGEST` from the reviewed plan.

Important parameter forms:

| API | Arguments |
| --- | --- |
| `HealthyTable_SetFanPwmDuty` | `{"duty":192}`; permitted requested range 0–255 |
| `HealthyTable_SetFanTestMode` | `{"manual":true}`; false restores automatic |
| `HealthyTable_SetFanIndex` | `{"index":0}`; qualified device has one fan |
| `WMISetBatteryHealth`, `WMISetBatteryHealthToUser` | `{"percent":80}` |
| `WMISetQuietFan` | `{"profile":"balanced"}`; quiet/balanced/performance |
| `AppList_OpenWindows` | `{"include_titles":false}` |
| `SaveEcLog` | `{"path":"new.jsonl","samples":10,"interval":1}`; see log path rules below |
| `RF_USBISTYPEC` | optional `device` topology and `scope`: `attachment` (default) or `host` |
| `RF_USB_A_Num` / `RF_USB_C_Num` | optional `scope`: `attachment` (default) or `host` |
| `RF_USBNum` | optional boolean `detailed`; default remains the non-hub device count |
| `Adapter_Read_PDO` | `{"index":0}`; zero-based, 0–6; optional `connector`: 1 or 2 |
| `Adapter_Read_PDO1`–`Adapter_Read_PDO7` | optional `connector`: 1 or 2; missing advertised slot returns ENODATA |
| `Adapter_Read_PD_ADO` | default original byte: unsupported here; `native_alert: true` selects full received ADO32 with optional connector |
| `Adapter_Read_Contract_PDO` | optional `{"connector":1}` or 2; defaults to the sole valid EC contract |
| `WMIGetLCDModel` | optional boolean `internal_only`; default returns connected/unknown internal and external rows |
| `GetNum_Key` | no arguments; Num Lock plus attached keyboard count |
| `GetSENSOR_WMI_Data` | no arguments; actual DSTS 0x60068 `p_sensor` mask |
| `GetXgmFw` | no arguments; eligible GC31/GC33 firmware query |
| `WOA_EC_read` | `{"address_space":"healthytable","bank":2,"register":48}` |
| `WOA_EC_write` | same plus `value`, reviewed apply required; disabled by default (EPERM) |

`WOA_EC_write` is refused, for planning and apply alike and before any
elevation, with EPERM "raw EC writes are disabled; owner policy forbids
arbitrary EC writes". It is enabled only while
`/etc/zenbook-hardware/allow-raw-ec-write` is a regular file owned by root and
not group/world-writable, inside a root-owned directory that is not
group/world-writable (checked without following symlinks). When enabled, the
existing plan and exact-digest apply path is unchanged. Other OEM mutations are
unaffected.

`SaveEcLog` / `zenbook-hardware record PATH` creates a new 0600 file. Every
directory component is opened without following symlinks, so a path through a
symlinked directory fails with ENOTDIR/ELOOP; a relative path is resolved
against the current directory. When it runs as root for a sudo or pkexec
caller (`SUDO_UID`/`SUDO_GID` or `PKEXEC_UID`), the target directory must be
owned by that caller (otherwise EACCES) and the new log is chowned to the
caller.

The WOA-named routes are explicitly native x86 equivalents. They do not accept
or reinterpret ARM ATD command addresses. This laptop has no ATD_STS provider;
the original ARM transport is outside the qualified machine scope.

`zenbook-hardware charger [--connector 1|2]` returns both EC port records or
filters one. Available records contain `voltage_volts`, `current_limit_amperes`,
`power_limit_watts`, `ec_reported_watts` and the raw active PDO. These describe
the negotiated supply, not instantaneous draw. Absent/invalid contracts are
null; stale cached PDO bytes are suppressed when AC or contract validity clears.
The original contract-PDO API returns the USB-PD object as an integer.
In 0.10 it uses the public cached monitoring attribute without privilege.
The report also includes `platform_power`, with hardware-counter sampled watts,
source and scope. `independent_usb_c_input_measurement` remains false. Since
0.73 the driver itself re-samples once after 120 ms when a read only re-primes
an idle, stale or stopped counter (PSYS hwmon `power1_input` and RAPL `power3_input`/
`cpu_package_power` alike; `power2_input` is the separate USB-C input ADC); the userspace retry from0.72 remains as a bound.
Protocol/MSR errors and a second failure remain unavailable.
`zenbook-hardware metrics` carries the same `platform_power` object. Since0.76 metrics also carries `wireless_chain_signal` (per-chain dBm, physical
main/aux mapping unverified); RF_WiFi_Main_Aux_Rssi and hwmon-backed WMIGetHDDTemp
work without privilege. Since0.74 metrics
also carries `cpu_power_limits` (MSR and MMIO package RAPL zones with per-zone
long/short/peak limits and the lowest enabled limit; the original PowerLimit1/2
scalars keep the MSR zone) and `ec_cpu` (EC CPU temperature and CPU-reported
P-state voltage). The full metrics report takes several seconds because fresh
SBS/identity/EC transactions are serialized. Charger ADC/metrics and PD identity
transactions get one fresh retry after a transient worker failure or a contract
change between bracketing snapshots. Linux UCSI
`usb_c_power` rows and EC `connector`1/2 rows are separate providers; no
cross-provider connector mapping is asserted.
Other proprietary adapter APIs retain their original providers and explicit unavailable
errors; no sufficient/champion-port rating or proprietary PDO-watt encoding
is inferred from the EC's nominal 65 W limit.

Version0.70 `RF_USB_A_Num`/`RF_USB_C_Num` count user-connectable USB device
connections at their attachment ports, including downstream hubs. As in the
original enumeration, logical companion-device connections are separate counts;
`socket_count` additionally merges known peer/Type-C halves into physical sockets.
The original "A" branch includes all known non-Type-C connections; `quantity`
says so, while detailed connector shapes
retain `A`, `C`, `other` or `unknown`. `RF_USBISTYPEC` describes the immediate
attachment socket. A device behind a USB-C dock never inherits that root type
for an unknown or known USB-A downstream socket. Optional `scope: "host"`
classifies each connection at the laptop/root port separately; its `socket_count`
retains used-root-connector reporting. `connect_type` supplies user visibility; raw _UPC
connectivity alone does not establish it. Unknown sockets/counts stay nullable.

`RF_USBPort` rows include `attachment_connection`, separate `host_connection`,
raw `usb_specification_bcd` (cached bcdUSB) and cached interface classes with a
nullable `usb_mass_storage_class`. Descriptor specification, firmware bcdDevice
and link speed are distinct. `RF_USBNum` with `detailed: true` returns the existing
device total, exact raw-version bins0200/0210/0300/0310/0320, other raw versions,
unknown-version coverage and a mass-storage subset with its own classification/
version completeness. Native mass-storage selection uses device/interface class08;
it does not depend on Windows friendly names. A missing/changed optional descriptor
keeps device presence while withholding its field/classification. No descriptor,
configuration, scan, reset or power request is sent.

Wi-Fi per-channel and U-NII APIs return grouped AP counts from
cached scan data. They do not trigger a scan or infer physical antenna labels.

## Adapter ratings and diagnostic availability (0.42.1)

`Adapter_Read_Standard_Watt`, `Adapter_Read_Sufficient_Watt` and
`Adapter_Read_ChampionPort_Watt` take no arguments. On qualified UP3404VA.301 they
return EOPNOTSUPP without root authentication or a rating/WMI request: this EC
provides HealthyTable15, while their original x86 path requires28 or newer and
uses bank12 byte pairs1/0,3/2 and5/4. The original DSTS0x1200f2 alternative is
ARM64-only. Linux uses current x86 hardware identity and active ACPI-device
presence; it does not import Windows registry cache overrides. A different
firmware/protocol remains unqualified until its transport is independently tested.

`metrics.adapter_capabilities` contains each rating's nullable watts, availability,
status/reason and the original protocol/recipe metadata. These ratings are distinct
from negotiated PDO voltage/current/power limits, EC adapter watts and measured
input voltage/current/power. Those existing measurements remain in their own
providers; a nominal65W contract is not evidence for an unavailable rating.

`legacy_diagnostic_config` distinguishes the qualified0.43 module's source-proven
unsupported bank from an older module's failed-read quarantine. Current0.43
metadata reports static_firmware_absence_proven true with EOPNOTSUPP and no
failed-read latch. Older metadata leaves static absence unproven. Invalid or
contradictory metadata remains unavailable. No dedicated probe is added; the
qualified kernel now skips absent banks entirely. See the0.43 section below.
Shared qualified_ec identity/ownership/census guards propagate provider errors.

## Specialty-temperature availability (0.41)

`metrics.specialty_temperatures` reports all nine original specialty roles with
`available`, nullable `celsius`, source, status and errno/reason. `provider_available`
means the exact native hardware identity was read; it does not mean a sensor is
active. Read errors/changed identity/manual ownership remain provider failures.

The nine original API names take no arguments. Eight return EOPNOTSUPP on the
qualified EC: ACFET, battery connector, board TS0R, charger choke, GPU TS1R,
GPU VRAM/VRM and upper CPU. Original uncached EcFwRev dispatch selects familyffff
when raw vendor2 lacks the high bit; those original getters return unsupported
zero. That is not a zero-degree measurement or a missing Linux label mapping.
Native Linux uses current hardware identity, without importing Windows registry
cache overrides. The separate raw firmware bytes remain ASCII01.

`Thermal_Read_GpuTS1L_Temperature` has a distinct source-backed fallback: the
existing HealthyTable bank2/selector3 channel, gated by protocol support and
absence of legacy ASUS1000. It returns the native list of label/celsius/source
rows when the channel meets the existing hwmon range policy (1..125C). Current
raw0 is retained only in diagnostics and produces ENODATA;255/out-of-range and
malformed data never become temperatures. A legacy ASUS1000 interface or unknown
model/BIOS/EC identity withholds the unqualified path. Existing hwmon EC GPU uses
the same channel and remains hidden when inactive at module probe.

Five separately proven board NTC area labels stay in board_thermistors; they do
not establish any of these specialty placements. The new route does not search
arbitrary hwmon label substrings, issue CC/CE/E4 probes, enable a channel or change
firmware/fan policy. Measurements are EC-reported; physical die/location is not
independently established by an export's name.

## Storage inventory and device capacity (0.40)

These eight queries take no arguments and run without privilege. They read cached
sysfs metadata only: no block-device open, filesystem probe, SMART, serial read or
power/reset command. Capacity is kernel sectors multiplied by512, independent of
the logical sector size. Normal partitions, virtual disks and MMC boot/RPMB
subareas are excluded from the physical-device census; non-disk SCSI types are
not selected. Identity, major/minor number, metadata and census are checked again.

| API | Native selection and result |
| --- | --- |
| `WMIGetHDDList`, `WMIGetHDDModel` | Kernel-reported rotating disks; metadata rows or model strings |
| `WMIGetSSDList`, `WMIGetSSDModel` | Kernel-reported non-rotating fixed disks; metadata rows or model strings |
| `WMIGetHDDSize` | Total bytes across fixed disks, including SSDs, matching its original fixed-media query |
| `WMIGetPhysicalDiskInfo` | Rotating/non-rotating fixed classes plus rows whose membership is unknown |
| `WMIGetSDCardCaption` | Model strings for generic removable disks, matching the original caption query |
| `WMIGetSDCardSize` | Total bytes for explicit Linux SD/SDcombo types, or removable models containing SD CARD, SDHC CARD or SDXC CARD, case-insensitive |

The SD-size helper's caption filter differs from its caption API's broader query.
Linux's explicit SD type also works when a host marks that card non-removable.
MMC/eMMC is not selected as SD; a name beginning mmcblk alone proves neither SD
nor removability. Through generic USB readers, a matching caption is selector
evidence and does not independently establish the inserted card's physical type.
A zero total means zero capacity in the known selected set, not universal absence
of SD hardware. Non-rotating fixed is the Linux equivalent used by the SSD APIs,
including fixed flash devices; it is not an independent media-type measurement.
See [kernel block attributes](https://github.com/torvalds/linux/blob/master/Documentation/ABI/stable/sysfs-block)
and [the MMC type provider](https://github.com/torvalds/linux/blob/master/drivers/mmc/core/bus.c).

Metadata rows retain `available`, `field_errors`, nullable fields and source.
`available` validates the node identity; individual optional/required field errors
remain explicit. Physical info also has nullable `matches_physical_media`, referring
to the native classes above. Unknown selection prevents an exact list or size
(ENODATA). Unknown selected size/model prevents a partial total/model list. Known
zero sectors are retained. No disks returns an empty list or zero selected bytes;
a failed census remains an error. The all-drive HDD temperature API is separate.

`WMIGetHDDUsage` follows rotating disks and `WMIGetSSDUsage` follows non-rotating
fixed disks, then reports mounted filesystem capacity/availability. This corrects
the former all-drive HDD-usage selection. Kernel classification is validated first;
missing, duplicate or inconsistent selected disks in the lsblk mount tree return
EAGAIN. Partial filesystem-read errors remain rows, and unmounted disks retain
ENODATA rows. The recovered Size/SizeRemaining properties describe capacity,
not I/O activity; no serial-number join is needed for the native kernel topology.
These are sequential observations, not an atomic snapshot of mounts/hotplug.

Version0.69 reads capacity through a pinned directory descriptor. Its mount ID,
inode and filesystem device number must match mountinfo and the selected lsblk
node. Selected disk generations/classifications and mount inventory are checked
again, as are the mount record and current path. An unmount, overmount or changed
association cannot silently report the parent filesystem's capacity. Successful
rows add `mount_id`, `filesystem_device` and `identity_verified`. Unknown synthetic
or multi-device mappings, including unqualified Btrfs backing layouts, remain
unavailable. No block device, filesystem probe or mount control is requested;
lsblk requests only kernel identity/classification/mount columns.

## Installed memory (0.38)

The five memory APIs take no arguments and require a privileged caller because
Linux protects SMBIOS records. Non-root CLI and C ABI callers reach them through
the privileged service; the C ABI returns EACCES when polkit denies or the
service is unavailable and never elevates itself.
Only cached `/sys/firmware/dmi/entries/17-*/raw` records are read, with bounded
frames, string indices, record identities/census and duplicate-handle checks.
There is no /dev/mem, SPD transaction or OS-memory fallback.

- `WMIGetMemInfo` returns a report with `devices`, `installed_capacity_bytes`,
  `capacity_available`, `known_capacity_bytes` and record/population counts.
  Each record includes capacity in bytes, locator/bank, manufacturer, part number,
  maximum and configured data rates, plus explicit per-field errors. Empty slots
  are retained. An unreadable or unknown-size device withholds the complete total.
- `WMIGetMemSize` returns installed bytes only when the complete capacity is known;
  otherwise it returns ENODATA. It no longer returns OS-usable memory.
- `WMIGetMemFrequency`, `WMIGetMemManufacture` and `WMIGetMemModel` return per-device
  `locator`, `value`, `available` and source/error metadata. Empty slots are omitted.
  Configured data rate has `units: "MT/s"`; a missing configured value is not
  replaced by the module maximum. No measured clock frequency is inferred.

These are firmware inventory declarations, including soldered memory devices,
not a physical module count or live electrical measurement. Serial numbers and
asset tags are not decoded or exported. The ordinary `show` inventory memory view
retains OS-usable capacity and usage. The original Windows source queried
Win32_PhysicalMemory, whose capacity is backed by SMBIOS Type17. See
[Microsoft's class documentation](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-physicalmemory)
and [DMTF SMBIOS3.8, section7.18](https://www.dmtf.org/sites/default/files/standards/documents/DSP0134_3.8.0.pdf).

## Disk temperatures (0.16)

`WMIGetHDDTemp` is a native all-drive temperature query. Since 0.16 it returns
one row per detected physical disk, including SSDs. A successful row contains
`device`, `available: true`, `celsius` and `source` (Linux hwmon or SMART).
An unavailable row contains `device`, `available: false`, `errno` and `error`,
with no `celsius` field. A single disk's failure does not remove other rows.
No detected disks returns an empty list. Inventory failure can still fail the
whole query. SMART fallback requires appropriate device access.

The query prefers a matching hwmon device, then uses `smartctl -A -j -n
standby,3,5`. It requests exit on standby and unsupported ATA power checks, with
no permissive retry or guessed bridge type. Device autodetection and SCSI bridge
behavior can still wake a drive; a universal no-spin-up guarantee is not claimed.
See the [smartctl manual](https://raw.githubusercontent.com/smartmontools/smartmontools/main/src/smartctl.8.in).

## Complete battery lifetime data (0.17)

`battery_lifetime` retains schema1 and its legacy `blockN_prefix_hex` fields.
New kernels additionally set `complete_blocks: true` and provide `block1_hex`
through `block5_hex`, of exactly32,8,26,32,32 bytes. Existing prefixes must agree
with these payloads. Missing, short, changing or mismatched data is an error;
the reader does not fall back to stale partial data after a failed full read.

`zenbook-hardware battery-history` and `metrics` include `raw_blocks`,
`complete_blocks`, `unmapped_block_bytes`, the recorded `fet_maximum` temperature,
and complete last-cycle fields for all16 events. Raw block APIs now report
`complete: true` for these full payloads. Older kernels keep the previous partial
results, with the FET maximum and incomplete last-cycle fields unavailable.

Complete bytes do not imply complete semantic decoding: OEM block2 bytes4..7
and block3 bytes4..25 differ from the reference layout and have no published
balancing/time interpretation. The runtime prefix remains a raw counter with
`runtime_unit_verified: false`. These records describe history, not active faults.
The legacy `runtime_counter_raw` value is only the first four bytes interpreted
as an integer for compatibility; whether those bytes form one field is unverified.

## Hardware availability (0.22)

Bluetooth count/type/use queries require a successful read from an already-running
BlueZ daemon. A valid empty result remains zero/false/an empty list; service,
permission, timeout or malformed mandatory connection data returns an error.
The query binds the existing unique owner and never activates, scans, pairs,
connects or changes a device. Optional unreadable/invalid device metadata is null
and listed in `unavailable_metadata_fields`; valid connection counts are retained.

`WMIGetMonitorBrightness` returns per-backlight rows with `available`. A good row
has `percent`, `actual_brightness`, `max_brightness` and `source`; a failed row
has errno/error and omits percent. Zero is valid only with actual0 and a positive
maximum. Device/range changes return EAGAIN for that row. The value is the Linux
backlight level relative to its maximum, not an optical calibration or a DDC read
of every external monitor. [Kernel backlight reference](https://docs.kernel.org/gpu/backlight.html).

`BatteryHealthyTable_ACStatus` and `Power_Read_ACDCMode` take no arguments and read
the fixed ACPI adapter's0/1 status directly. Missing, denied or malformed data is
an error. CLI show uses null plus `ac_status_error` when unavailable. Bluetooth
and brightness queries also reject arguments. Unknown battery-status bytes now
produce unknown battery error/PF-gate fields rather than fabricated booleans.
The legacy PF gate remains a busy predicate, not a battery health diagnosis.
Unreadable/invalid fan modes and unknown battery status also remain unknown;
they do not assert manual fan control or a non-full battery.

## USB display transport (0.21)

`RF_USBHDMIIsUsed` with `{"metric":"usb_display"}` runs unprivileged. Its schema1 result
retains `usb_display` and `connected_displays`, adding `available`,
`coverage_complete`, `typec_displayport`, `unmapped_external_displays` and `errors`.
`usb_display` is true for a connected DRM connector with a verified USB ancestor,
or an active partner DP mode with selected pins and partner sink configuration.
The kernel's `configuration` describes the partner: sink means local source.
`local_displayport_role` makes that distinction explicit.

An embedded-only, completely readable display inventory returns false. Missing
providers, changing metadata or unmapped external/virtual outputs return unknown
(JSON null), preserving positive evidence from other objects when available.
Product names, DisplayLink branding, an evdi driver name and local mode capability
are insufficient. A reported transport does not prove a visible picture, associate
an arbitrary external monitor with a particular Type-C port, or identify an HDMI
adapter. The read performs no EDID/serial access, mode change or role swap.

## Battery identity (0.20)

`BatteryHealthyTable_DeviceName`, `BatteryHealthyTable_ManufactureName`,
`BatteryHealthyTable_ManufactureNameBySMBus`, `Battery_Read_ManufactureName` and
`BatteryHealthyTable_GaugeIC` now use the dedicated battery identity provider.
They take no arguments and run unprivileged. Name queries return the full reported
SBS string, including the native SMBus-name query; Windows buffer compatibility
is outside scope. GaugeIC returns the original raw fourth ManufacturerName byte,
not a verified vendor, the gauge DeviceType or a default zero for missing data.

Read-only `battery_identity` hwmon JSON contains exact manufacturer/model hex
blocks, device/firmware gates and a300-second cache age. The separate SBS commands
are block READ20/21, not ManufacturerAccess selectors20/21. Two sentinel passes
establish complete variable lengths and matching data; all48 volatile bytes are
restored and verified. Manual ownership and restoration faults reject reads;
resume and explicit diagnostics reprobe invalidate the cache.

`show` includes decoded values and source details in `battery.identity`; `metrics`
adds `battery_identity`. Exact raw bytes remain available when printable text is
unavailable. Blank/nonprintable strings and missing fields never become successful
empty text. The existing `battery_manufacturer`/`battery_model` sysfs attributes
now use this provider too. ACPI laptop strings remain separate. Raw gauge
identifiers do not establish the physical IC vendor.

## Wi-Fi throughput (0.19)

`WMIGetWiFiBytesPersec` retains its default map from interface name to combined
RX+TX bytes per second. An unavailable interface now has a JSON null value,
including counter resets, hotplug/replacement, failed reads, suspend gaps and
invalid sampling intervals. A genuine zero byte delta remains a valid zero rate.
The rate uses the measured monotonic interval rather than the requested sleep.

Optional `{"detailed":true}` returns schema1 with `sample_seconds`, the same
`rates_bytes_per_second` map and an `interfaces` list containing availability,
separate RX/TX rates or errno/error. Other arguments are rejected. Valid interfaces
remain available when another fails. Counters are read sequentially rather than
atomically; no traffic, scan, connection or hardware setting is requested. The
provider reads Linux wireless-interface counters without a NetworkManager dependency.
Accounting follows that Linux driver; cross-OS framing equivalence is unqualified.

## Live gauge additions (0.18)

`battery-gauge`, `show --json` and `metrics` include `additional_metrics` in the
gauge report. The new read-only `battery_gauge_extra` hwmon JSON attribute has
schema1, exact32-byte `da1_hex` /24-byte `da2_hex`, target identity/firmware and
cache age0..15000ms. `temp17_input` / `Battery gauge algorithm` exposes the
qualified eighth DA2 word in millidegrees Celsius.

The report provides two `cells` with voltage/current and `power_watts`, signed
`gauge_power_watts`, `gauge_average_power_watts`, and `gauging_temperature_celsius`.
Positive power means charging. These power values are computed by the gauge
from its voltage/current samples; they are separate from USB-C input ADCs and
PSYS, and are not independent power-ADC measurements. Inconsistent cell power
encodings become unavailable; a locally computed substitute is never returned.
The algorithm temperature is an input used by gauging, not a new thermistor.
Since0.75 DA2 bytes16..23 decode as `uncompensated_cells` (U16 mV, TI DAStatus2
layout without UserTemperature) only when active cells track the DA1 compensated
values within500 mV and inactive cells are zero; otherwise the object is
unavailable (ENODATA). The raw tail stays in `da2_tail_hex`, with
`unmapped_da2_tail_hex` kept as a compatibility alias.

Each block is one complete reply, but the DA1 and DA2 replies can have different
sample times. This uses a separate15-second cache; the existing5-second gauge
temperature/current report is retained. Manual ownership and restoration faults
deny the new monitor, including cached data. Older kernels report the additional
metrics unavailable.

## WWAN native schemas (0.18)

All three WWAN APIs accept an optional `{"modem":"/org/freedesktop/ModemManager1/Modem/0"}`
selector and otherwise return one row per enumerated modem. A missing modem
returns ENODEV; per-device/property errors do not hide other available data.

- `RF_WWAN_Access_Technology`: registered `technologies`, `raw_mask`,
  `unknown_mask` and `modem_state`. LTE/NR combinations stay separate flags.
- `RF_WWAN_Home_Provider`: `home_provider` comes only from the primary SIM's
  operator fields. `serving_provider` is separate and may differ while roaming.
  Missing home information is not filled with the serving network.
- `RF_WWAN_RSSI`: `measurements` keeps per-radio `rssi_dbm`, `rsrp_dbm`,
  `rsrq_db`, `snr_db` and other supported measured fields. The requested RSSI is
  available only if an actual RSSI field exists. Quality percent is never
  converted to dBm, and NR RSRP is never renamed RSSI.

Signal data is the existing ModemManager cache. Disabled polling/thresholds
suppress stale dictionaries; active polling or unsolicited thresholds permit
readout, with `freshness_verified: false` and `sample_age_seconds: null` because
the service exposes no sample timestamp. Recent generic quality is labelled
separately. No polling configuration, modem enable/connect/scan or SIM/PIN method
is called. Only fixed property getters are used; IMSI/ICCID/IMEI, phone numbers
and authentication/bearer inventories are not requested.

See the upstream [modem properties](https://www.freedesktop.org/software/ModemManager/doc/latest/ModemManager/gdbus-org.freedesktop.ModemManager1.Modem.html),
[SIM operator fields](https://www.freedesktop.org/software/ModemManager/doc/latest/ModemManager/gdbus-org.freedesktop.ModemManager1.Sim.html)
and [signal interface](https://www.freedesktop.org/software/ModemManager/doc/latest/ModemManager/gdbus-org.freedesktop.ModemManager1.Modem.Signal.html).

## C ABI version 1

`asus_ht_call(request_json, &response_json)` accepts an object with `name`,
optional `args`, optional boolean `apply` and optional `expected_sha256`.
Unknown names/fields and malformed parameters are rejected. The same provider
dispatch and field extraction are used by CLI and C clients.

The return value is 0 for a successful result, 1 for a provider error envelope,
or negative errno for a local transport failure. Release a returned allocation
with `asus_ht_free`. Requests are limited to 64 KiB and responses to 16 MiB.
Calls may block while a provider samples hardware, but at most 60 seconds: the
bridge is then killed and the call returns `-ETIMEDOUT` (record long
`SaveEcLog` captures with the CLI instead). The bridge runs as
`/usr/bin/python3 -I -B` with a fixed environment (`PATH=/usr/sbin:/usr/bin:/sbin:/bin`,
`LANG=C.UTF-8`); only an unprivileged, non-setid caller additionally passes
`HOME`, `XDG_RUNTIME_DIR`, `XDG_CONFIG_HOME` and `DBUS_SESSION_BUS_ADDRESS`.
The child gets a reset signal mask and default dispositions, no other caller
descriptors, and correct stdin/stdout even if the caller has fds 0–2 closed.
No shell is invoked and privileges are never elevated implicitly. Root-side
helper tools are run by absolute path from `/usr/sbin`, `/usr/bin`, `/sbin`
or `/bin`, never through `PATH`.

## Errors and privilege

ENODEV/ENODATA mean an absent device, unsupported firmware query, missing state
or unvalidated physical sensor label. EACCES/EPERM describe privilege or policy
restrictions. EINVAL is malformed input. These outcomes are not successful
hardware measurements. A zero value returned by a responding provider remains
distinct from no provider.

OEM requests are serialized and response nonces detect interference. Mutations
are rejected while watchdog-owned manual fan mode is active. Raw fan registers
are accessible only through the public guarded fan controls.

## Charger input measurements

`zenbook-hardware charger` includes `input_measurements` alongside negotiated
PD limits and independent `platform_power`. Available input data provides
`voltage_volts`, `current_amperes`, `power_watts`, ADC resolution and cache age.
Power is V*I from actual ADC samples. It is not the 65 W adapter rating, a
battery-flow estimate or AC wall consumption. Connector attribution requires
one active fixed PD contract. `available: false` means no validated measurement.

The qualified kernel also offers world-readable `charger_adc` schema 1 and
standard hwmon `in7_input` (mV), `curr3_input` (rounded mA), `power2_input` (µW).
The JSON keeps current in µA. Resolution is 44.4 mA and 96 mV, with a two-second
cache. No external meter calibration is claimed. All reads require automatic
fan operation; requests during manual fan control return EBUSY. No charger
configuration or arbitrary register interface is provided.

## Extended metrics (0.12)

`zenbook-hardware metrics` returns `cpu_throttling`, `ssd_health`, `charger_input`
, `charger` and `usb_pd_source_capabilities`. Use `metrics --refresh-ssd` for an explicit privileged SMART refresh.
`show --json` also includes `cpu_throttling`, `ssd_health` and `charger_metrics`.
`charger` additionally includes `controller_metrics`.

`charger_metrics` hwmon JSON schema 1 contains14 raw words, a per-channel validity
mask, integer converted units and cache age. Standard read-only channels are
`temp9_input` (charger die m°C), `in8_input` (system rail mV), `in9_input` (VBAT-pin
mV), `curr4_input` (charge ADC mA), `curr5_input` (discharge ADC mA). ADC-disabled,
invalid or saturated channels are unavailable while valid status can remain readable.
The battery shunt is model-qualified at5mΩ; resolutions are44.4mA charging,
88.8mA discharging,64mV VBAT,96mV VSYS and about1.625°C die temperature.
VBAT is the IC pin, not a replacement for the battery gauge's pack measurement.

CPU reports preserve decimal strings for64-bit counters and every logical CPU;
summary values are explicitly the maximum per-CPU observations. They describe
thermal events since boot, not instantaneous thermal state or unique package
interrupt totals. Vitals also compares updates for recent observed activity.

SSD reports expose only a whitelist of health fields. Counters are decimal
strings, including128-bit data-unit counts; data units are rounded512000-byte
units, not exact byte totals. Wear above100% is valid. Historical unsafe shutdown
and temperature-duration counts are not current faults. Cache age includes
suspend time and must be0..180seconds. Raw SMART identifiers are not exported.

## Complete source capabilities (0.12)

`pd_source_caps` is a world-readable schema 1 snapshot: 81 bytes encoded as hex.
The first 23 bytes use the existing `pd_contract` layout; two 29-byte records
follow (count, then seven complete LE32 PDO slots, unused slots zero). Each
pass brackets the per-port source-cache reads with all contract fields; two
identical complete passes are required. Inactive ports are zeroed. The two-second
cache is invalidated across suspend. Manual fan ownership returns EBUSY.

`charger` includes `source_capabilities`; `metrics` includes
`usb_pd_source_capabilities`. The decoder requires a valid active fixed contract,
a first 5 V fixed PDO, 1–7 nonzero objects and the active PDO in the list. Fixed
profiles expose voltage/current/power limits. Other supply types retain their
raw object with explicit unqualified conversion. Source limits do not identify
the cable or measure draw. Generic and numbered PDO APIs return original raw
32-bit objects; slots beyond the advertised count return ENODATA.

## Battery diagnostics and PD identities (0.13)

Public 0444 `battery_gauge_metrics` schema 1 contains device/firmware hex plus a
20-byte DAStatus1 and 14-byte DAStatus2 prefix. Cache is 5 seconds; age is supplied.
Standard hwmon `temp10_input` through `temp16_input` expose gauge internal, TS1,
TS2, TS3, TS4, selected cell and FET temperature in m°C. Inputs outside -40..125°C
return ENODATA; currently TS3/TS4 are off-scale/unavailable. These are battery
pack channels, distinct from motherboard thermistors and the charger die.

Public `battery_lifetime` schema 1 contains double-read prefixes for blocks 1,3,4,5
(lengths31,4,31,31), with a 60-second cache. Root-only
`battery_lifetime_refresh` accepts only 1, invalidates that cache and reads again.
The default `battery-history` command returns the fresh decoded report;
`--refresh` explicitly forces this reader. The legacy `battery_history` raw cache
remains separately available for diagnosis and is not a source of peak values.

The three original maximum-current/cell-difference APIs now use the guarded
fresh prefix. MaxDischargeCurrent preserves its original raw 16-bit return;
the metrics report also supplies the signed interpretation as positive peak
discharge magnitude. Original LifetimeBlock APIs return
`{data_hex,complete:false,source,note}` for the qualified prefix. Byte 31 and
unqualified trailing fields are excluded. No full Windows binary ABI is claimed.

`metrics` adds `board_thermistors`, `battery_gauge`, `battery_lifetime` and
`usb_pd_identity`; `charger` also includes `received_identities`.
`pd_identity` schema 1 contains a contract snapshot and two 25-byte received
identity records per port, with a 5-second cache. The contract brackets the
fixed controller reads; inactive ports are zeroed, not stale. Decoder requires
an acknowledged response, 3–6 VDOs and a valid VID before returning identity data.
The three e-marker VID/PID/XID APIs accept only optional connector 1/2 and return
ENODATA when no acknowledged cable identity exists. `available:true` for the
monitor means its reader worked; each identity has its own availability flag.

## Battery event history (0.14)

`battery_lifetime` retains schema 1 and adds `block2_prefix_hex` (4 bytes). Blocks
1/2/3/4/5 have lengths 31/4/4/31/31, each queried twice. Consumers of older drivers
may omit block 2; reset counts must then be unavailable, not zero.

The native report adds `power_event_counts` and `lifetime_events` with names,
16-bit counts, categories and `last_event_cycle_count`. A count of zero means no
last event; 0xffff is not a cycle number. `last_cycle_field_complete=false` means
the field extends beyond the qualified prefix. In particular, the last discharge
short-circuit and resistance-disable cycle values are unavailable. Recorded
safety counts are separate from live safety/PF status. Runtime remains raw.

## Received alerts and opaque e-marker VDO (0.15)

`pd_identity` schema1 adds a four-byte `alert_hex` per port; existing fields and
five-second caching remain. It is read-only controller register0x74, payload
length4. The same active-contract snapshots bracket identities and alerts, and
inactive ports are zeroed by the collector. Older kernels without `alert_hex`
report the alert reader unavailable. Low16 reserved ADO bits must be zero for
the qualified layout. The report supplies `raw_ado`, `alert_type` and fixed /
hot-swappable battery change masks. ADO zero means no alert recorded, without
claiming current fault status or proving that an alert was ever received.

`Adapter_Read_PD_ADO` accepts only optional connector1/2 and returns the full
unsigned32-bit received ADO in the native JSON API. The previous legacy cache
byte is not a binary-compatible return contract. `Adapter_Read_PD_Get_Emark_Other`
uses the same connector selector and requires ACK plus at least5 identity VDOs;
it returns raw VDO index4, preserving the original opaque field offset.

## Legacy adapter diagnostic availability (0.43)

`metrics.adapter_diagnostics` lists the ten original bank6 read APIs, selectors,
widths and typed availability. On qualified UP3404VA.301 these return EOPNOTSUPP:
the firmware DD switch has only banks1..5/81..85, and its default sends no reply.
The native module's `max_dd_bank` and per-field `unsupported_mask` distinguish
this source-proven absence from `unavailable_mask` (failed optional reads).
`adapter_capabilities.legacy_diagnostic_config` reports the same distinction.
Older modules lack this proof metadata and cannot claim static support absence.
No zero reading, negotiated wattage or current ADC is substituted. The separate
working PD/input/charger/battery providers retain their schemas. Recovered OEM
mutation plans remain available; applications targeting absent banks are rejected
by the qualified kernel transport before I/O, including the bank7 monitor.

## Cached firmware diagnostics (0.44)

`metrics.firmware_diagnostics` reports three fixed module-probe replies: DSTS
EEPROM support0x60059, original DEVS read-version0x60059/selector0xe0 and DSTS
p_sensor0x60068. The public GetSENSOR_WMI_Data returns a raw hexadecimal mask;
zero is a valid empty mask and is not a temperature. GetEEPROM_Data returns
EOPNOTSUPP for the recognized unsupported-method version result. It does not
return a version number/date based on a support mask or substitute BIOS storage.
Each reply carries method, device, selector, signed status and raw-valid metadata.
Reading this cache makes no firmware request or authentication prompt. Replies
remain the module-probe snapshot until reload; this is explicit cached capability
metadata, not live sensor measurements. Unknown/error/malformed replies never
prove firmware absence. A newly responding table remains unqualified until its
layout is verified, without automatic register enumeration. `firmware-storage`
keeps its separate BIOS/CMOS inventory and typed table availability; it reads no
storage contents. Probe adds only the fixed recovered read-version query and two
support/mask queries. No EEPROM write or new raw WMI interface is exposed.

Version0.45 implements the original buffered E5 path as well as common/BU scalar
registers and the manufacture timestamp. GetEEPROM_Data still takes no native
arguments. If a real supported version responds and buffer ABI1 is present, an
explicit call requires root and collects the table; cached metrics do not collect
or advance event data. Current qualified firmware still reports unsupported
versionFE, so public calls return EOPNOTSUPP without root or E5 access.

The fixed root transport accepts only DEVS60059/E5, no apply flag or raw method
selector. It mirrors the actual ATK driver's1024-byte zero padding and recognizes
the unsupported scalar/four-byteFE reply. Kernel and userspace check5a/a5 magic,
length9+byte6 and actual reply bounds before accepting a complete frame. Unlike
the original256-byte temporary copy, a declared257..264-byte frame is never read
past the reply. event contains complete opaque frame objects with raw_hex; data
padding, payload types, checksums, temperatures and units are not inferred.

The collector preserves original version>7 BU selection and the two-consecutive-
unusable-reply stop rule. It has an explicit64-frame limit, records transport/
framing failures, marks truncation and never claims complete EEPROM history.
Scalar failures/count overflows abort instead of publishing partial register lists.
A successful all-ones scalar reply reaches the selector-aware decoder: date/count
sentinels differ from raw register words. Missing date is null with its raw value;
valid timestamps use the native system's local calendar date.

firmware_diagnostics.eeprom_buffer_transport exposes cached module-local firmware
call/guard-rejection counters. Reading them makes no WMI request. An older module
without buffer ABI1 cannot start positive table collection. EEPROM buffer handling
has source/injected protocol proof; a responding physical table is unqualified
on the current machine. No EEPROM write, reset or event-clear command is exposed.


Version 0.53 corrects seven wireless quantities. RF_WiFiMaxRate returns the derived
advertised AP HT/VHT/HE ceiling in Mbit/s. It uses capability/operation IEs, not
NetworkManager MaxBitrate or observed Tx/Rx speed. HE uses the fastest standard
0.8 us GI; EHT is outside this getter's original scope and explicitly flagged.
RF_PhyMode reads enabled current mac80211 peer capabilities; unproven legacy
a/b/g stays unavailable. Card-name APIs add actual descriptive PCI/USB names,
keeping driver and name availability separate.

RF_WiFi_{2_4G,5G,6G}_AP_RSSI_Num defaults to nine dBm bins with total, missing
signal, outside-bin count, observation age and completeness. Intervals are lower
inclusive and upper exclusive: [-20,-10) through [-100,-90). Explicit numeric
threshold_dbm retains a scalar threshold count when the signal inventory is
complete. Unknown signal never becomes zero; percentages are not converted.

`zenbook-hardware wireless` and metrics.wireless_capabilities read a root-owned
45-second cache after checking boot and current association generation. They
never authenticate or refresh it. API calls can explicitly use the existing
privileged read path when that cache is unavailable. An independent 20-second
collector reads existing supplicant data/current kernel peer files, without
scan, connection, settings, daemon activation or network administration. Card
descriptions remain independently readable. Vitals uses the same cached command.


Version0.54.1 restores the original SaveEcLog data coverage. The API and native
`record` command write new private mode0600 JSONL files, containing the retained
native snapshot plus ec_diagnostics. Its six source table groups contain69
entries, with original selectors, widths, minimum versions, raw values or exact
unavailable errors. Twenty-three nested field descriptors define indexed board,
VR, fan and consumer-VR data. Unsupported version rows make no request.

`zenbook-hardware ec-diagnostics` and metrics.ec_diagnostics expose the same
fixed EC data without collecting EEPROM events. The explicit logger includes
the existing bounded GetEEPROM_Data result/error, retaining its FE/version,
privilege and truncation guards. Current firmware is unsupported for that table;
this remains EOPNOTSUPP with no E5 transaction. File writes never overwrite an
existing file or symlink. Samples are sequential captures separated by the
requested minimum delay, not a promise of uniform simultaneous sampling.

The32-byte BB20..3f ProjectFWRevision is separate from EC firmware BB3/4 and the
four-byte chip name. Raw battery modes/statuses, current and temperature codes
remain raw; a source label alone does not establish units or measurement validity.
Source raw-hex words have explicit little-endian byte representation. Board
selectors use the qualified one-based mapping and exact verified restoration.
Current protocol15 has no indexed VR sensors; consumer/GPIO/newer status fields
stay explicitly unavailable rather than fabricated zeros.

`fan_diagnostics` is an independent read-only sysfs object, available during
manual ownership. It reports RPM, EC mode, fixed single-channel index and the
even0..254 duty code read from DD2/35. This code is distinct from pwm1's last
requested manual value and from an electrical PWM measurement. `show`, metrics
and Vitals expose it; Vitals adds Fan EC Duty Code and Fan EC Control.

On this BIOS, DD2/35 is gated by actual manual mode. Automatic mode returns no
duty reply: the native reader skips that request and reports duty_errno95 and
duty_code null, while retaining mode/RPM/count. It reads the real duty code in
manual mode. Schema2 distinguishes this availability. The native fixed channel
index0 is separate from selection_raw (observed1); the RPM path does not use
that raw selector. No selector is rewritten merely to normalize the report.


## Original alert cache byte and native received ADO (0.70)

`Adapter_Read_PD_ADO` originally reads one byte at DD bank6/0x26. This qualified
firmware has no bank6 handler, so its default returns EOPNOTSUPP without that
request. The byte's mapping to the native32-bit alert is unknown; no low/high byte
is substituted. `{"native_alert":true}` explicitly selects the existing full
received USB-PD ADO and permits optional connector1/2. `native_alert` is a strict
boolean; a connector without native mode is rejected before any read. The normal
identity/charger/metrics reports and Vitals keep their explicitly labelled full
received alert. This correction does not change the controller collector, send a
PD command or hide the useful native measurement.


## GPU providers and monitor names (0.71)

`WMIGetGPUUsg` collects every advertised provider: DRM `gpu_busy_percent`
(`provider: "drm_busy"`, device percent) and i915 PMUs (`provider: "i915_pmu"`,
per-engine busy nanoseconds over measured running intervals). A failed DRM read
no longer hides PMU rows, nor the reverse. Discovery/census errors appear in
`provider_errors` with provider and errno; decode/parse failures become
per-provider EPROTO rows. Device identities (PMU resolved path included) and the
provider census are rechecked before publication; a change fails only rows that
were available, and already failed rows keep their errno.
`provider_coverage_complete` is true when every advertised provider was enumerated
and read without a provider error or provider-level failure row; one unavailable
engine sample does not clear it. `all_readings_available` separately reports
whether every published row is available. `source` joins the providers present;
`requested_sample_seconds` appears only when a PMU exists. Providers are not
substituted, summed or cross-calibrated. This is neither a census of every
physical GPU nor the Windows per-process3D maximum.

`WMIGetLCDModel` follows the original unfiltered monitor friendly-name query: its
default returns connected/unknown internal and external DRM rows. Optional
`{"internal_only":true}` returns the former strict internal-panel view. The
selector must be boolean; other display queries take no arguments. Validation
happens before any metadata read.
