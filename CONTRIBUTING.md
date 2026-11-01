# Development

Run `make check` and `make module`. CI runs userspace tests, sanitizer-backed
portable protocol tests and a kernel-header build. Hardware checks are separate
and never run in CI. Preserve the distinction between implemented behavior,
simulated protocol checks, successful real reads and physical validation.

For a new model, supply the exact model/BIOS/protocol, sanitized capability
results, matching recovered recipes and independent automatic restoration
tests. Do not relax model matching or infer physical sensor placement merely
because a byte looks like a plausible temperature. Do not add a catch-all EC,
MSR, SMBus or EFI write interface.

Never include ASUS proprietary binaries/disassembly, private ACPI/UEFI dumps,
device UUIDs/serials, user application/window inventories, credentials or signing
keys in issues or commits. Keep raw hardware qualification receipts private;
publish aggregate results with exact source revisions and test limitations.

New API providers need argument validation before privilege elevation, explicit
missing-hardware behavior and meaningful behavior/failure tests. An API name
mapped to a function does not prove the original operation was ported.
