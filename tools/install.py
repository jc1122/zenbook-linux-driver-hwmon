#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Install qualified DKMS source and root-owned Linux tools; retain rollback."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
VERSION='0.85.0'
MODULE='zenbook_healthytable'
PACKAGE='zenbook-healthytable'
KERNEL_FILES=('Makefile','dkms.conf','healthytable_core.h','healthytable_telemetry.h','healthytable_diagnostics.h','healthytable_eeprom.h','healthytable_frequency.h',
              'healthytable_history.h','healthytable_gauge.h','healthytable_gauge_block.h','healthytable_sbs.h','healthytable_oem.h','healthytable_voltage.h','healthytable_pd.h','healthytable_pd_identity.h','healthytable_power.h','healthytable_charger.h','zenbook_healthytable.c')
RUNTIME=('zenbook-hardware.py','capabilities.json','compat.py','native_oem.py','efi_oem.py','remembered_controls.py','user_preferences.py','driver_package.py','package_power.py','hdmi_presence.py','disk_temperature.py','filesystem_usage.py',
         'linux_services.py','network_status.py','field_reads.py','battery_summary.py','identity_inventory.py','cpu_metadata.py','platform_metadata.py','desktop_windows.py','process_counters.py','application_inventory.py','hardware_memory.py','storage_inventory.py','gpu_usage.py','tablet_mode.py','input_state.py','display_state.py','session_state.py','ec_diagnostics.py','diagnostic_log_layout.json','wireless.py','wireless_capabilities.py','wireless_native.py','wireless_inventory.py','export_wireless.py','usb_power.py','hardware_status.py','wwan.py','xgm_hid.py','usb_activity.py','disk_activity.py','usb_display.py','usb_inventory.py','auth.py','api_bridge.py','charger.py','extra_sensors.py','pd_contract.py','pd_sources.py','pd_identity.py','charger_adc.py','charger_metrics.py','cpu_throttling.py','ssd_health.py','metrics.py','specialty_thermal.py','qualified_ec.py','adapter_ratings.py','adapter_diagnostics.py','firmware_queries.py','eeprom_table.py','export_ssd.py','battery_diagnostics.py','battery_identity.py','battery_extra.py','battery_sbs.py','thermistors.py')

# Privileged service: daemon code lives in the versioned runtime (retained for
# rollback); system integration files are rewritten to point at that runtime.
SERVICE_RUNTIME=('service/zenbook_hardwared.py','service/hwd_core.py','service/authorization.json')
SERVICE_FILES={'service/org.zenbook.hardware.policy':'usr/share/polkit-1/actions/org.zenbook.hardware.policy',
               'service/49-zenbook-hardware.rules':'usr/share/polkit-1/rules.d/49-zenbook-hardware.rules',
               'service/org.zenbook.Hardware1.conf':'usr/share/dbus-1/system.d/org.zenbook.Hardware1.conf',
               'service/org.zenbook.Hardware1.service':'usr/share/dbus-1/system-services/org.zenbook.Hardware1.service'}
SERVICE_UNIT='etc/systemd/system/zenbook-hardwared.service'
SERVICE_GROUP='zenbook-hw'
MANAGED='Managed by asus-healthytable-linux'
PLATFORM_DEVICE=Path('/sys/devices/platform/zenbook_healthytable')
# The driver registers its platform device without an id (stable name) and the
# hwmon device under it (devm_hwmon_device_register_with_info(&pdev->dev,...)),
# so <platform>/hwmon contains only the hwmonN instance. That container is the
# narrowest index-independent writable path. Attributes the service writes
# (DAC still blocks 0444 files; other owner-writable nodes there are
# battery_history_refresh, uevent and power/*):
HWMON_CONTAINER=PLATFORM_DEVICE/'hwmon'
HWMON_WRITES=('pwm1','pwm1_enable','diagnostics_reprobe','battery_lifetime_refresh','oem_request')
UCSI_COMMAND='/sys/kernel/debug/usb/ucsi/USBC000:00/command'


def run(args):
    subprocess.run(args,check=True,timeout=240)


def atomic_library(source,destination):
    # Existing clients may still map the old library. Replacing its inode
    # preserves those mappings; truncating/copying over it does not.
    fd,temporary=tempfile.mkstemp(prefix='.'+destination.name+'-',dir=destination.parent)
    os.close(fd)
    try:
        shutil.copyfile(source,temporary);os.chmod(temporary,0o644)
        os.replace(temporary,destination)
    finally:
        if Path(temporary).exists():Path(temporary).unlink()


def hwmon():
    matches=[p for p in Path('/sys/class/hwmon').glob('hwmon*') if (p/'name').read_text().strip()=='zenbook_ec']
    if len(matches)!=1:raise RuntimeError('Expected one qualified HealthyTable device.')
    return matches[0]


def restore_auto():
    p=hwmon();(p/'pwm1_enable').write_text('2\n')
    if (p/'pwm1_enable').read_text().strip()!='2':raise RuntimeError('Automatic fan restoration failed.')


def install_module():
    model=Path('/sys/class/dmi/id/product_name').read_text().strip()
    bios=Path('/sys/class/dmi/id/bios_version').read_text().strip()
    if model!='Zenbook Flip UP3404VA_UP3404VA' or bios!='UP3404VA.301':
        raise RuntimeError('The EC transport is currently qualified only for UP3404VA.301.')
    previous=Path('/sys/module')/MODULE/'version'
    old=previous.read_text().strip() if previous.exists() else None
    source=Path('/usr/src')/(PACKAGE+'-'+VERSION)
    if source.exists():
        for name in KERNEL_FILES:
            if (source/name).read_bytes()!=(ROOT/'source'/name).read_bytes():
                raise RuntimeError('Existing DKMS version has different source; bump the version first.')
    else:
        source.mkdir(mode=0o755)
        for name in KERNEL_FILES:shutil.copyfile(ROOT/'source'/name,source/name);(source/name).chmod(0o644)
    if old!=VERSION:
        registered=subprocess.run(['/usr/sbin/dkms','status','-m',PACKAGE,'-v',VERSION],capture_output=True,text=True,check=True)
        if not registered.stdout.strip():run(['/usr/sbin/dkms','add','-m',PACKAGE,'-v',VERSION])
        kernel=os.uname().release
        run(['/usr/sbin/dkms','build','-m',PACKAGE,'-v',VERSION,'-k',kernel])
        try:
            if old:restore_auto()
            run(['/usr/sbin/dkms','install','-m',PACKAGE,'-v',VERSION,'-k',kernel])
            if old:run(['/usr/sbin/modprobe','-r',MODULE])
            run(['/usr/sbin/modprobe',MODULE])
            restore_auto()
            if previous.read_text().strip()!=VERSION:raise RuntimeError('Unexpected loaded driver version.')
            if int((hwmon()/'fan1_input').read_text())<500:raise RuntimeError('Fan RPM verification failed.')
        except BaseException:
            if previous.exists():restore_auto();run(['/usr/sbin/modprobe','-r',MODULE])
            if old:run(['/usr/sbin/dkms','install','-m',PACKAGE,'-v',old,'-k',kernel,'--force']);run(['/usr/sbin/modprobe',MODULE]);restore_auto()
            raise
    autoload=Path('/etc/modules-load.d/zenbook-healthytable.conf')
    if autoload.exists() and autoload.read_text()!=MODULE+'\n':raise RuntimeError('Existing autoload differs.')
    autoload.write_text(MODULE+'\n');autoload.chmod(0o644)


def install_runtime(prefix):
    target=prefix/'lib/asus-healthytable'/VERSION
    if target.exists():
        for name in RUNTIME+SERVICE_RUNTIME:
            if not (target/name).is_file() or (target/name).read_bytes()!=(ROOT/name).read_bytes():raise RuntimeError('Installed runtime differs; bump version.')
        target.chmod(0o755);(target/'service').chmod(0o755)
    else:
        target.parent.mkdir(parents=True,exist_ok=True)
        staged=Path(tempfile.mkdtemp(prefix='.install-',dir=target.parent))
        try:
            for name in RUNTIME:shutil.copyfile(ROOT/name,staged/name);(staged/name).chmod(0o644)
            (staged/'service').mkdir(mode=0o755);(staged/'service').chmod(0o755)
            for name in SERVICE_RUNTIME:shutil.copyfile(ROOT/name,staged/name);(staged/name).chmod(0o644)
            staged.chmod(0o755)
            os.replace(staged,target)
        finally:
            if staged.exists():shutil.rmtree(staged)
    binary=prefix/'bin/zenbook-hardware';binary.parent.mkdir(parents=True,exist_ok=True)
    launcher='#!/bin/sh\nexec /usr/bin/python3 '+str(target/'zenbook-hardware.py')+' "$@"\n'
    if binary.exists() and not binary.read_text().startswith('#!/bin/sh\nexec /usr/bin/python3 '+str(prefix/'lib/asus-healthytable')):
        raise RuntimeError('Refusing to overwrite an unrelated launcher.')
    binary.write_text(launcher);binary.chmod(0o755)
    lib=prefix/'lib/libasus-healthytable.so.1';atomic_library(ROOT/'build/libasus-healthytable.so',lib)
    link=lib.with_name('libasus-healthytable.so')
    if link.exists() or link.is_symlink():
        if not link.is_symlink() or link.readlink()!=Path(lib.name):raise RuntimeError('Existing library link differs.')
    else:link.symlink_to(lib.name)
    include=prefix/'include';include.mkdir(exist_ok=True)
    shutil.copyfile(ROOT/'include/asus_healthytable.h',include/'asus_healthytable.h')
    run(['/usr/sbin/ldconfig'])
    return target


def install_metrics_service(target):
    import re
    devices=[p.name for p in Path('/sys/class/block').glob('nvme*n*')
             if re.fullmatch(r'nvme[0-9]+n[0-9]+',p.name) and not (p/'partition').exists()]
    service=(ROOT/'systemd/zenbook-hardware-ssd.service.in').read_text().replace('@RUNTIME@',str(target))
    service=service.replace('@DEVICES@','\n'.join('DeviceAllow=/dev/'+n+' r' for n in sorted(devices)))
    units={'zenbook-hardware-ssd.service':service,'zenbook-hardware-ssd.timer':(ROOT/'systemd/zenbook-hardware-ssd.timer').read_text(),
           'zenbook-hardware-wireless.service':(ROOT/'systemd/zenbook-hardware-wireless.service.in').read_text().replace('@RUNTIME@',str(target)),
           'zenbook-hardware-wireless.timer':(ROOT/'systemd/zenbook-hardware-wireless.timer').read_text()}
    for name,data in units.items():
        p=Path('/etc/systemd/system')/name
        if p.exists() and not p.read_text().startswith('# Managed by asus-healthytable-linux\n'):
            raise RuntimeError('Refusing to replace an unrelated metrics unit: '+name)
        p.write_text(data);p.chmod(0o644)
    run(['/usr/bin/systemctl','daemon-reload'])
    run(['/usr/bin/systemctl','enable','--now','zenbook-hardware-ssd.timer'])
    run(['/usr/bin/systemctl','start','zenbook-hardware-ssd.service'])
    run(['/usr/bin/systemctl','enable','--now','zenbook-hardware-wireless.timer'])
    run(['/usr/bin/systemctl','start','zenbook-hardware-wireless.service'])


def managed(path):
    """True for a missing file or one this project wrote earlier."""
    if not path.exists() and not path.is_symlink():return True
    if path.is_symlink() or not path.is_file():return False
    with path.open('rb') as handle:return MANAGED.encode() in handle.read(512)


def atomic_text(path,data,mode=0o644):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as handle:handle.write(data)
        os.chmod(temporary,mode);os.replace(temporary,path)
    finally:
        if Path(temporary).exists():Path(temporary).unlink()


def safe_sysfs(path):
    text=str(path)
    if not text.startswith('/sys/') or '..' in text.split('/') or not all(c.isalnum() or c in '/_:.+-' for c in text):
        raise RuntimeError('Refusing an unexpected sysfs path in the service sandbox: '+text)
    return text


def service_read_write_paths(root=Path('/')):
    """Writable sysfs paths for the sandbox, all independent of the hwmon index:
    the driver's hwmon container directory plus canonical exact files. A '-'
    prefix tolerates absence (driver not loaded, debugfs locked down, no LED).
    root is '/' except in tests, which use a fake sysfs tree."""
    def host(path):return Path('/')/path.relative_to(root)
    def resolve(path):return host(path.resolve(strict=True))
    devices=[p for p in (root/'sys/class/hwmon').glob('hwmon*') if (p/'name').read_text().strip()=='zenbook_ec']
    if len(devices)!=1:raise RuntimeError('Expected one qualified HealthyTable device.')
    device=devices[0].resolve(strict=True)
    if host(device).parent!=HWMON_CONTAINER:
        raise RuntimeError('The zenbook_ec hwmon device is not directly below '+str(HWMON_CONTAINER)+'.')
    missing=[name for name in HWMON_WRITES if not (device/name).exists()]
    if missing:raise RuntimeError('The loaded driver lacks expected attributes: '+', '.join(missing))
    entries=['-'+safe_sysfs(HWMON_CONTAINER)]
    profile=root/'sys/firmware/acpi/platform_profile'
    if not profile.is_file() or profile.is_symlink():raise RuntimeError('platform_profile is unavailable.')
    entries.append(safe_sysfs(host(profile)))
    entries.append(safe_sysfs(resolve(root/'sys/class/power_supply/BAT0/charge_control_end_threshold')))
    keyboard=root/'sys/class/leds/asus::kbd_backlight/brightness'
    if keyboard.exists():entries.append('-'+safe_sysfs(resolve(keyboard)))
    entries.append('-'+safe_sysfs(UCSI_COMMAND))
    return 'ReadWritePaths='+' '.join(entries),safe_sysfs(HWMON_CONTAINER)


def tablet_switch_devices(input_root=Path('/sys/class/input'),by_path=Path('/dev/input/by-path')):
    """Stable by-path symlinks of the input devices advertising SW_TABLET_MODE
    (bit 1 of the lowest capabilities/sw word). systemd resolves each symlink
    to its device number when the service starts, so a changed eventN is
    followed. Devices without a by-path link are skipped (tablet mode then stays
    a root/sudo read)."""
    import re
    links={}
    if by_path.is_dir():
        for link in sorted(by_path.iterdir()):
            if link.is_symlink() and re.fullmatch(r'[A-Za-z0-9_:.+-]+-event',link.name):
                try:links.setdefault(link.resolve(strict=True).name,str(link))
                except OSError:pass
    result=[]
    for event in sorted(input_root.glob('event[0-9]*')):
        try:words=(event/'device/capabilities/sw').read_text().split()
        except OSError:continue
        if words and re.fullmatch(r'[0-9a-fA-F]{1,16}',words[-1]) and int(words[-1],16)&2 and event.name in links:
            path=links[event.name]
            if Path(path).parent!=by_path or not all(c.isalnum() or c in '/_:.+-' for c in path):
                raise RuntimeError('Refusing an unexpected input device path: '+path)
            result.append(path)
    return result


def group_members(name):
    import grp
    import pwd
    group=grp.getgrnam(name)
    return sorted(set(group.gr_mem)|{p.pw_name for p in pwd.getpwall() if p.pw_gid==group.gr_gid})


def ensure_group():
    """Create zenbook-hw if absent. An existing group is reported with its
    members (they receive passwordless polkit grants), never silently adopted."""
    import grp
    try:grp.getgrnam(SERVICE_GROUP)
    except KeyError:
        run(['/usr/sbin/groupadd','--system',SERVICE_GROUP]);return {'created':True,'members':[]}
    members=group_members(SERVICE_GROUP)
    import sys
    print('warning: group '+SERVICE_GROUP+' already exists; members receive passwordless read/settings/fan-lease grants: '+
          (', '.join(members) if members else '(none)'),file=sys.stderr)
    return {'created':False,'members':members}


def install_service(target,root=Path('/'),read_write=None,hwmon_path=None,tablet_devices=None):
    """Install polkit/D-Bus/systemd integration for the runtime at target.
    Creates the zenbook-hw group but adds no members and enables nothing; the
    unit has no [Install] section and starts only by D-Bus activation.
    Transactional: on any failure every written file is restored or removed."""
    destinations=[root/d for d in SERVICE_FILES.values()]+[root/SERVICE_UNIT]
    for path in destinations:
        if not managed(path):raise RuntimeError('Refusing to replace an unrelated file: '+str(path))
    for name in SERVICE_RUNTIME:
        if not (target/name).is_file():raise RuntimeError('Runtime lacks the service: '+name)
    if read_write is None:read_write,hwmon_path=service_read_write_paths()
    unit=(ROOT/'service/zenbook-hardwared.service.in').read_text().replace('@RUNTIME@',str(target))
    if tablet_devices is None:tablet_devices=tablet_switch_devices()
    devices='\n'.join('DeviceAllow='+path+' r' for path in tablet_devices) or '# No by-path SW_TABLET_MODE device: tablet mode is not readable here.'
    unit=unit.replace('@READ_WRITE_PATHS@',read_write).replace('@HWMON@',hwmon_path or '').replace('@TABLET_DEVICES@',devices)
    if any(p in unit for p in ('@RUNTIME@','@READ_WRITE_PATHS@','@HWMON@','@TABLET_DEVICES@')):raise RuntimeError('Unresolved placeholder in the service unit.')
    group=ensure_group()
    # Policy and bus configuration first, so the name can never be activated
    # without its ownership restriction; the activation file goes last.
    plan=[(root/SERVICE_FILES[source],(ROOT/source).read_text()) for source in
          ('service/org.zenbook.hardware.policy','service/49-zenbook-hardware.rules','service/org.zenbook.Hardware1.conf')]
    plan+=[(root/SERVICE_UNIT,unit),(root/SERVICE_FILES['service/org.zenbook.Hardware1.service'],(ROOT/'service/org.zenbook.Hardware1.service').read_text())]
    previous={path:(path.read_bytes() if path.exists() else None) for path,_data in plan}
    written=[]
    try:
        for path,data in plan:atomic_text(path,data);written.append(path)
        run(['/usr/bin/systemctl','daemon-reload'])
        run(['/usr/bin/busctl','call','org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','ReloadConfig'])
    except BaseException:
        for path in reversed(written):
            try:
                if previous[path] is None:path.unlink()
                else:atomic_text(path,previous[path].decode())
            except OSError:pass
        for command in (['/usr/bin/systemctl','daemon-reload'],['/usr/bin/busctl','call','org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','ReloadConfig']):
            try:run(command)
            except (OSError,subprocess.SubprocessError):pass
        raise
    return {'unit':str(root/SERVICE_UNIT),'runtime':str(target),'group':SERVICE_GROUP,'group_created':group['created'],'tablet_devices':tablet_devices,
            'group_members':group['members'],'enabled':False}


def remove_service(root=Path('/')):
    """Rollback to a service-less release: remove only files this project wrote.
    Versioned runtimes and the zenbook-hw group are retained."""
    removed=[]
    paths=[root/SERVICE_FILES['service/org.zenbook.Hardware1.service'],root/SERVICE_UNIT,
           root/SERVICE_FILES['service/org.zenbook.Hardware1.conf'],root/SERVICE_FILES['service/49-zenbook-hardware.rules'],
           root/SERVICE_FILES['service/org.zenbook.hardware.policy']]
    for path in paths:
        if path.exists() or path.is_symlink():
            if not managed(path):raise RuntimeError('Refusing to remove an unrelated file: '+str(path))
    if (root/SERVICE_UNIT).exists():run(['/usr/bin/systemctl','stop','zenbook-hardwared.service'])
    for path in paths:
        if path.exists():path.unlink();removed.append(str(path))
    run(['/usr/bin/systemctl','daemon-reload'])
    run(['/usr/bin/busctl','call','org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','ReloadConfig'])
    return removed


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-only',action='store_true')
    parser.add_argument('--without-service',action='store_true',help='Do not install the privileged D-Bus service files')
    parser.add_argument('--remove-service',action='store_true',help='Remove the privileged service files only (rollback) and exit')
    parser.add_argument('--service-only',action='store_true',help='Regenerate the service files for the installed runtime of this version and exit')
    args=parser.parse_args()
    if os.geteuid()!=0:raise PermissionError('Run sudo make install after make check.')
    if args.remove_service:
        print(json.dumps({'removed':remove_service()},indent=2));return
    if args.service_only:
        print(json.dumps(install_service(install_runtime(Path('/usr/local'))),indent=2));return
    if not args.runtime_only:install_module()
    target=install_runtime(Path('/usr/local'))
    install_metrics_service(target)
    if not args.without_service:install_service(target)
    print(json.dumps({'version':VERSION,'runtime':str(target),'fan_mode':(hwmon()/'pwm1_enable').read_text().strip(),
                      'rpm':int((hwmon()/'fan1_input').read_text()),'source_sha256':{
                          n:hashlib.sha256((ROOT/'source'/n).read_bytes()).hexdigest() for n in KERNEL_FILES}},indent=2))


if __name__=='__main__':main()
