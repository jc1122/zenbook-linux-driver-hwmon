# SPDX-License-Identifier: GPL-2.0-only
"""Shared read-only identity/ownership snapshot for qualified native EC providers.

No new firmware recipes; uses the existing ec_telemetry and fan-mode attributes.
"""
from pathlib import Path
import errno
import json
import platform
import native_oem


def text(path,limit=16384):
    try:
        with path.open('r',encoding='utf-8',errors='strict') as stream:raw=stream.read(limit+1)
    except UnicodeDecodeError:raise OSError(errno.EPROTO,'Invalid native EC metadata encoding.') from None
    if len(raw)>limit:raise OSError(errno.EOVERFLOW,'Native thermal metadata exceeds the supported bound.')
    return raw.strip()


def legacy_devices(root):
    return sorted(p.name for p in root.iterdir() if p.name.split(':',1)[0].upper()=='ASUS1000')


def identity(path):
    st=path.stat()
    if text(path/'name')!='zenbook_ec':raise OSError(errno.ENODEV,'Native HealthyTable device identity changed.')
    return st.st_dev,st.st_ino


def snapshot(dmi=Path('/sys/class/dmi/id'),acpi=Path('/sys/bus/acpi/devices')):
    if (platform.machine()!='x86_64' or text(dmi/'product_name')!='Zenbook Flip UP3404VA_UP3404VA' or
        text(dmi/'bios_version')!='UP3404VA.301'):
        raise OSError(errno.EOPNOTSUPP,'EC identity adapter is qualified only for x86 UP3404VA.301.')
    try:path=native_oem.device()
    except RuntimeError:raise OSError(errno.ENODEV,'Native HealthyTable device is unavailable.') from None
    before=identity(path);legacy=legacy_devices(acpi)
    if text(path/'pwm1_enable')!='2':raise OSError(errno.EBUSY,'EC telemetry reads require firmware automatic fan control.')
    try:raw=json.loads(text(path/'ec_telemetry'))
    except ValueError:raise OSError(errno.EPROTO,'Invalid native EC telemetry JSON.') from None
    if not isinstance(raw,dict):raise OSError(errno.EPROTO,'Invalid native EC telemetry object.')
    for key,expected in [('protocol',15),('vendor',2),('chip_id',0)]:
        if type(raw.get(key)) is not int or raw[key]!=expected:raise OSError(errno.EOPNOTSUPP,'Unqualified native EC '+key+'.')
    for key,expected in [('chip_name_raw',[53,53,55,49]),('firmware_raw',[48,49])]:
        if (not isinstance(raw.get(key),list) or any(type(v) is not int for v in raw[key]) or raw[key]!=expected):
            raise OSError(errno.EOPNOTSUPP,'Unqualified native EC '+key+'.')
    if before!=identity(path) or legacy!=legacy_devices(acpi):raise OSError(errno.EAGAIN,'EC provider identity or legacy interface changed during sampling.')
    if text(path/'pwm1_enable')!='2':raise OSError(errno.EBUSY,'Automatic fan control changed during EC sampling.')
    return raw,legacy


def firmware_metadata():
    """Read cached firmware traits with the same qualified identity/owner gates."""
    try:path=native_oem.device()
    except RuntimeError:raise OSError(errno.ENODEV,'Native HealthyTable device is unavailable.') from None
    before=identity(path)
    snapshot()
    try:raw=json.loads(text(path/'firmware_diagnostics'))
    except ValueError:raise OSError(errno.EPROTO,'Invalid native firmware diagnostic JSON.') from None
    if not isinstance(raw,dict):raise OSError(errno.EPROTO,'Invalid native firmware diagnostic object.')
    if before!=identity(path):raise OSError(errno.EAGAIN,'Native EC provider changed during firmware metadata read.')
    if text(path/'pwm1_enable')!='2':raise OSError(errno.EBUSY,'EC provider ownership changed during firmware metadata read.')
    return raw
