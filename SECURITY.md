# Security policy

## Supported versions

Only the latest release (the version in `capabilities.json` and the top entry
of `CHANGELOG.md`) receives security fixes. Older releases stay installable for
rollback, but fixes are not backported. The project supports only the
qualified hardware (ASUS Zenbook Flip UP3404VA, BIOS .301, HealthyTable
protocol 15); the kernel module refuses other machines, and reports about
unqualified hardware are handled as feature requests.

## Reporting a vulnerability

Report vulnerabilities privately through a GitHub security advisory:
<https://github.com/jc1122/zenbook-linux-driver-hwmon/security/advisories/new>
(repository **Security** tab, **Report a vulnerability**). Do not open a
public issue or pull request for an unfixed vulnerability.

Please include the release, the affected component (kernel module, privileged
service, CLI, C library, GNOME bridge, Vitals integration, installer), steps
to reproduce and the impact you expect. Do not include device serial numbers,
firmware dumps, credentials or other personal data; redact them from logs.
Reports are acknowledged on a best-effort basis by a single maintainer; the
fix and advisory are published together.

Do not test against hardware you do not own, and do not attempt fan, charger
or firmware writes to demonstrate an issue. A source-level argument or a
reproduction in the unit tests (which use fakes, not hardware) is enough.

## Verifying releases

Release tags (`vX.Y.Z`) and release commits are signed with an SSH key held on
a hardware security key. GitHub marks them **Verified**. The maintainer's
signing keys are published at
<https://api.github.com/users/jc1122/ssh_signing_keys> (not
`github.com/jc1122.keys`, which lists authentication keys). To verify locally:

```sh
curl -s https://api.github.com/users/jc1122/ssh_signing_keys \
  | python3 -c 'import json,sys; [print("22999250+jc1122@users.noreply.github.com", k["key"]) for k in json.load(sys.stdin)]' \
  > allowed_signers
git -c gpg.ssh.allowedSignersFile=allowed_signers verify-tag vX.Y.Z
```

The kernel module is built and signed on your own machine by DKMS with your
own Machine Owner Key; the project never ships prebuilt or pre-signed modules
or signing keys.

## Scope

In scope:

- `source/` kernel module (`zenbook_healthytable`): memory safety, sysfs
  permission errors, unprivileged access to EC/SMBus traffic, fan or charger
  safety failures, lifecycle races.
- `service/` privileged D-Bus service (`org.zenbook.Hardware1`), its polkit
  policy, D-Bus policy, systemd unit and authorization table.
- The CLI (`zenbook-hardware`), `api_bridge.py`, the C library
  (`lib/asus_healthytable.c`), the exporter units in `systemd/`, the GNOME
  bridge and the Vitals integration.
- The installer (`tools/install.py`) and its generated files.

Out of scope:

- Vulnerabilities in ASUS firmware (EC, BIOS, ACPI/WMI) themselves; report
  those to ASUS. How this project handles malformed firmware data is in scope.
- Attacks that require root, except where they defeat a stated hardware safety
  guarantee or corrupt kernel memory (see `docs/THREAT_MODEL.md`).
- Physical attacks, and hardware or models other than the qualified one.
- Denial of service by a member of the trusted `zenbook-hw` group within the
  documented rate limits.

## Privilege model summary

Full details are in `docs/API.md` ("Privileged service") and
`docs/THREAT_MODEL.md`.

- **Kernel module.** Access control is the sysfs mode bits. Telemetry, fan and
  plain EC-port reads are world-readable. Attributes that drive EC broker/SMBus sessions, RAPL/PSYS
  energy counters and device identifiers are root-only (0400). Writes (`pwm1`,
  `pwm1_enable`, `oem_request`, refresh triggers) are root-only and checked
  against fixed allowlists; no raw EC address, SMBus target or charger
  configuration register is reachable from userspace.
- **Privileged service.** `zenbook-hardwared` owns `org.zenbook.Hardware1` on
  the system bus. It is D-Bus activated, runs as uid 0 with `CAP_PERFMON` as
  its only capability, under a systemd sandbox (`NoNewPrivileges`,
  `ProtectSystem=strict`, `ProtectHome`, `PrivateNetwork`, `PrivatePIDs`,
  system-call filter, writable paths limited to specific sysfs files) and
  refuses to start if its runtime tree is not root-owned and non-writable by
  others.
- **Polkit actions.** Every method is authorized per call against the caller's
  unique bus name (never a PID): `read`, `read-identifiers`, `settings`,
  `fan-lease`, `ec-oem`, `firmware`, `driver`. If polkit is unavailable, the
  call is denied.
- **`zenbook-hw` group.** Only root and members may send to the service. A
  polkit rule grants members `read`, `read-identifiers`, `settings` and
  `fan-lease` without a password. EC/OEM, firmware/factory and driver
  load/unload always require `auth_admin` (no `_keep` for EC/OEM and
  firmware), for members too. The installer creates the group but adds no
  members.
- **Mutations.** A caller-computed plan digest never authorizes an apply
  through the service. Applies use single-use, 60-second tokens bound to the
  caller, action, export, arguments and a freshly recomputed plan.
- **Raw EC writes are disabled by policy.** `WOA_EC_write` is refused unless
  the policy file `/etc/zenbook-hardware/allow-raw-ec-write` exists as a
  regular root-owned file, not group- or world-writable, in a root-owned
  directory; the `ec-oem` polkit action is required in addition. The installer
  does not create the file.
- **Root CLI recovery path.** `sudo zenbook-hardware ...` runs the providers
  directly in-process without the service. It is the recovery and rollback
  route when the service is unavailable. The tool stores no credentials and
  never reads a keyring; the former Secret Service sudo-password route was
  removed in 0.79.
- **Audit.** Every mutating call (including denials), plan/apply and fan lease
  event is logged to the journal as an `AUDIT` line without argument values or
  results.

## Hardware safety guarantees

These are design guarantees covered by tests with fakes. Physical
qualification limits are listed in `docs/VALIDATION.md`.

- **Firmware automatic fan control is the default** and is restored:
  - by the kernel watchdog (every second while the driver owns manual mode)
    when the mode changes underneath it, RPM falls below
    `max(baseline/2, 500)`, or an I/O error occurs;
  - on suspend, which is aborted if restoration fails;
  - on module removal or shutdown, which first blocks every write path and
    watchdog re-arm and then retries restoration with readback;
  - by the service when a fan lease is released, expires (at most 300 s),
    its holder disconnects, RPM is low, a fan read fails, the daemon stops,
    or, through a lease marker, after a daemon crash.
- **Fail-closed latches.** If an EC mailbox session cannot be restored and
  read back, or an EC broker session stalls past its time budget, the driver
  latches a fault and refuses further charger, gauge, SBS and PD controller
  requests until the module is reloaded. Every collector requires the shared
  mailbox to be idle before starting and restores every byte it touched.
- **No charger configuration or factory writes without review.** Factory/EFI
  writes require a reviewed plan, a revision check, a private backup and
  readback; the service cannot perform them (no capability for it).
- **Bounded EC lock hold time.** EC broker sessions have per-collector time
  budgets so that an unprivileged-triggered or stalled session cannot hold the
  firmware's EC mutex indefinitely.
