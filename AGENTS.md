# ASUS HealthyTable Linux

Keep protocol recovery separate from device support and hardware validation.
A dispatch entry alone does not establish functional parity. Update
`capabilities.json` and `docs/PARITY.md` when changing a provider.

Run `make check` for userspace and protocol changes, and `make module` for
kernel changes. Hardware tests must restore automatic fan control. Firmware
factory writes require the existing plan, revision check and backup mechanism.
Do not test factory mutations merely to increase coverage.

Do not commit proprietary ASUS binaries, private firmware dumps, device
identifiers, user inventories, credentials, signing keys or raw local audits.
Keep model/BIOS qualification restrictions until another device is tested.
