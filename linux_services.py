# SPDX-License-Identifier: GPL-2.0-only
"""Linux providers for the ASUS Windows application/device service exports.

Only metadata is inspected: process command lines, environments and credentials
are deliberately never collected. Wi-Fi queries use existing scan caches.
"""
from pathlib import Path
import datetime
import errno
import json
import math
import os
import platform
import re
import shutil
import struct
import subprocess
import time
import psutil
import wireless
import hardware_memory
import storage_inventory
import process_counters
import application_inventory
import cpu_metadata
import platform_metadata
import desktop_windows
import identity_inventory
import battery_summary

EMPTY_HW_READS={'WMIGetHDDTemp','RF_BTConnectedNum','RF_BTConnectedType','RF_BTIsUsed','RF_Net_Connected_Type','WMIGetMonitorBrightness',
                'BatteryHealthyTable_ACStatus','Power_Read_ACDCMode','WMIGetHDDUsage','WMIGetSSDUsage','WMIGetExternMonitorNum','WMIGetExternMonitorPropList',
                'AppList_HardwareConfig','System_Read_VolumeLevel'}|process_counters.NAMES|application_inventory.NAMES

def text(path,default=''):
    try:return Path(path).read_text().strip()
    except OSError:return default
def integer(path,default=None):
    try:return int(text(path),0)
    except ValueError:return default
SYSTEM_TOOL_DIRS=('/usr/sbin','/usr/bin','/sbin','/bin')
def system_tool(name):
    """Absolute path of a system tool from a fixed allowlist; never searches PATH."""
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,63}',name):raise ValueError('Invalid system tool name.')
    for directory in SYSTEM_TOOL_DIRS:
        path=os.path.join(directory,name)
        if os.path.isfile(path) and os.access(path,os.X_OK):return path
    raise OSError(errno.ENOENT,'Required system tool is not installed in '+':'.join(SYSTEM_TOOL_DIRS)+': '+name)
def run(args,timeout=8):
    if not os.path.isabs(args[0]):args=[system_tool(args[0]),*args[1:]]
    p=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    if p.returncode:raise OSError(errno.ENODATA,p.stderr.strip()[:300] or args[0]+' failed')
    return p.stdout
def missing(message):raise OSError(errno.ENODEV,message)

def ac_online(path=Path('/sys/class/power_supply/ADP1/online')):
    raw=path.read_text().strip()
    if raw not in ('0','1'):raise OSError(errno.EPROTO,'Invalid AC adapter online status.')
    return raw=='1'

def monitor_brightness(root=Path('/sys/class/backlight')):
    rows=[]
    for p in sorted(root.iterdir()):
        row={'device':p.name,'available':False}
        try:
            before=p.stat()
            def value(name):
                raw=(p/name).read_text().strip()
                if not raw.isascii() or not raw.isdecimal() or len(raw)>10 or int(raw)>2**31-1:
                    raise OSError(errno.EPROTO,'Invalid kernel backlight value.')
                return int(raw)
            maximum=value('max_brightness');actual=value('actual_brightness');check=value('max_brightness')
            after=p.stat()
            if maximum!=check or (before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino):
                raise OSError(errno.EAGAIN,'Backlight device or range changed during sampling.')
            if maximum<=0 or actual>maximum:raise OSError(errno.ENODATA,'Backlight value is outside its valid range.')
            row.update(available=True,percent=100*actual/maximum,actual_brightness=actual,max_brightness=maximum,
                       source='Linux actual_brightness / max_brightness; kernel-reported level')
        except OSError as error:row.update(errno=error.errno or errno.EIO,error=str(error))
        rows.append(row)
    return rows


def default_volume():
    """Read the session's default output level; never alter volume or mute."""
    try:out=run(['wpctl','get-volume','@DEFAULT_AUDIO_SINK@'],timeout=5)
    except FileNotFoundError as error:
        raise OSError(errno.ENODEV,'WirePlumber wpctl is not installed.') from error
    except subprocess.TimeoutExpired as error:
        raise OSError(errno.ETIMEDOUT,'Default audio output query timed out.') from error
    match=re.fullmatch(r'Volume: ([0-9]{1,16}(?:\.[0-9]{1,16})?)( \[MUTED\])?',out.strip())
    if not match:raise OSError(errno.EPROTO,'Invalid default audio output volume reply.')
    percent=float(match[1])*100
    if not math.isfinite(percent):raise OSError(errno.EPROTO,'Non-finite audio volume.')
    muted=bool(match[2])
    return {'available':True,'percent':percent,'muted':muted,
            'effective_percent':0.0 if muted else percent,
            'source':'WirePlumber wpctl default PipeWire output; software volume setting',
            'note':'Level may exceed 100% with software amplification. This is not measured sound pressure or per-application volume.'}


def hardware_config():
    """Original brightness/default-volume contract with independent availability."""
    try:
        rows=monitor_brightness()
        brightness={'available':any(row['available'] for row in rows),'devices':rows}
        if not rows:brightness.update(errno=errno.ENODEV,error='No kernel backlight devices.')
    except OSError as error:
        brightness={'available':False,'devices':[],'errno':error.errno or errno.EIO,'error':str(error)}
    try:volume=default_volume()
    except OSError as error:
        volume={'available':False,'errno':error.errno or errno.EIO,'error':str(error)}
    return {'brightness':brightness,'volume':volume,
            'note':'Independent sequential display and session-audio reads. Brightness is per kernel backlight; no arbitrary monitor is selected.'}

def keyboard_state():
    import input_state
    import session_state
    result=input_state.report();session=session_state.report()
    result.update(num_lock_led_consensus=result['num_lock'],num_lock_led_available=result['num_lock_available'],
                  num_lock_led_complete=result['num_lock_complete'],num_lock=session['num_lock'],
                  num_lock_available=session['available'],num_lock_complete=session['available'],num_lock_session=session,
                  source='GNOME desktop keymap toggle with separately labelled Linux input/LED metadata')
    result['note']+=' Primary num_lock is desktop-session state. LED observations never substitute for an unavailable logical toggle.'
    return result


def cpu():
    out={}
    for line in text('/proc/cpuinfo').splitlines():
        if ':' not in line:continue
        k,v=line.split(':',1);out.setdefault(k.strip(),v.strip())
    return {k:out.get(k) for k in ('vendor_id','cpu family','model','stepping','model name','flags','cpu MHz')}

def storage(timeout=8):
    value=run(['lsblk','--json','--bytes','--output','NAME,PATH,TYPE,ROTA,SIZE,RM,MAJ:MIN,MOUNTPOINTS'],timeout=timeout)
    if len(value)>2*1024*1024:raise OSError(errno.EOVERFLOW,'Block mount inventory exceeds its bound.')
    try:raw=json.loads(value)
    except ValueError:raise OSError(errno.EPROTO,'Invalid block mount inventory JSON.') from None
    if not isinstance(raw,dict) or not isinstance(raw.get('blockdevices'),list):
        raise OSError(errno.EPROTO,'Invalid block mount inventory object.')
    return raw['blockdevices']
def drives(kind,timeout=8):
    if kind in ('hdd','ssd'):
        # Classify against current kernel metadata; lsblk supplies only the
        # mount tree. A stale/incomplete tree must not hide a selected disk.
        selected=storage_inventory.selected(storage_inventory.report(),kind)
        tree=storage(timeout=timeout);result=[]
        for disk in selected:
            found=[r for r in tree if isinstance(r,dict) and r.get('name')==disk['device'] and r.get('type')=='disk']
            if len(found)!=1:raise OSError(errno.EAGAIN,'Selected disk is missing or duplicated in the mount inventory.')
            row=found[0]
            if (row.get('path')!=disk['path'] or type(row.get('rota')) is not bool or
                type(row.get('rm')) is not bool or row['rota']!=disk['rotational'] or row['rm']!=disk['removable'] or
                type(row.get('size')) is not int or row['size']!=disk['size']):
                raise OSError(errno.EAGAIN,'Selected disk metadata disagrees with the mount inventory.')
            result.append(row)
        return result
    rows=[x for x in storage(timeout=timeout) if x.get('type')=='disk' and (Path('/sys/class/block')/x['name']/'device').exists()]
    if kind=='sd':return [x for x in rows if x.get('rm') or x['name'].startswith('mmcblk')]
    return rows
def disk_usage(kind):
    import filesystem_usage
    return filesystem_usage.report(kind,drives)
def disk_temperatures(kind):
    import disk_temperature
    return disk_temperature.report(kind)

def displays():
    import display_state
    return [r for r in display_state.report() if r['state']!='disconnected']


def windows(include_titles=False):
    return desktop_windows.call({'include_titles':include_titles})


def wifi():
    """Bounded existing AP cache, bracketed by daemon/netdev/BSS identities."""
    import dbus
    import wireless_native as native
    reader=native.Reader();nm=native.NM;root=wireless.NET_ROOT
    owner=reader.owner(nm)
    def unsigned(value,maximum=0xffffffff):
        if not isinstance(value,int) or isinstance(value,(bool,dbus.Boolean)) or not 0<=int(value)<=maximum:
            raise OSError(errno.EPROTO,'Invalid NetworkManager integer metadata.')
        return int(value)
    def scan_time(value):
        if not isinstance(value,int) or isinstance(value,(bool,dbus.Boolean)) or not -1<=int(value)<=2**63-1:
            raise OSError(errno.ENODATA,'Wireless scan-cache timestamp is unavailable.')
        if int(value)>time.clock_gettime(time.CLOCK_BOOTTIME)*1000+1000:raise OSError(errno.EPROTO,'Wireless scan timestamp is in the future.')
        return int(value)
    def devices():
        return native.paths(reader.call(owner,'/org/freedesktop/NetworkManager',nm,'GetDevices'),'/org/freedesktop/NetworkManager/Devices',256)
    def aps(path):
        value=reader.call(owner,path,nm+'.Device.Wireless','GetAllAccessPoints')
        return native.paths(value,'/org/freedesktop/NetworkManager/AccessPoint',4096)
    def get(path,interface,key):return reader.get(owner,path,nm+interface,key)
    def peer(path):
        address=get(path,'.AccessPoint','HwAddress');frequency=get(path,'.AccessPoint','Frequency')
        if not isinstance(address,str) or not re.fullmatch(wireless.MAC,address) or frequency is None:
            raise OSError(errno.EPROTO,'Cached BSS identity/frequency is unavailable.')
        frequency=unsigned(frequency,100000)
        if not frequency:raise OSError(errno.ENODATA,'Cached BSS frequency is unavailable.')
        return str(address).lower(),frequency
    inventory=devices();result=[];seen=set()
    for path in inventory:
        if unsigned(get(path,'.Device','DeviceType'))!=2:continue
        iface=get(path,'.Device','Interface')
        if not isinstance(iface,str) or not re.fullmatch(r'[^/\s\x00]{1,15}',iface) or iface in ('.','..') or iface in seen:
            raise OSError(errno.EPROTO,'Invalid or duplicate NetworkManager wireless interface.')
        seen.add(iface);netdev=root/iface
        if not (netdev/'wireless').is_dir():raise OSError(errno.ENODEV,'NetworkManager wireless interface has no matching kernel provider.')
        identity=wireless.identity(netdev)
        scan=scan_time(get(path,'.Device.Wireless','LastScan'));now=time.clock_gettime(time.CLOCK_BOOTTIME)*1000
        entries=aps(path)
        if scan==-1 and not entries:raise OSError(errno.ENODATA,'Wireless cache has never been scanned; an empty result is not an AP census.')
        row={'interface':str(iface),'ifindex':identity[2],'access_points':[],'last_scan_boottime_milliseconds':scan,
             'last_scan_age_seconds':None if scan==-1 else max(0,(now-scan)/1000),
             'source':'NetworkManager existing cached BSS observations; no active scan'}
        identities={}
        for entry in entries:
            address,frequency=peer(entry);identities[entry]=(address,frequency)
            strength=get(entry,'.AccessPoint','Strength')
            strength=int(strength) if isinstance(strength,int) and not isinstance(strength,(bool,dbus.Boolean)) and 0<=int(strength)<=100 else None
            row['access_points'].append({'bssid':address,'frequency_mhz':frequency,'strength_percent':strength})
        for entry in entries:
            if peer(entry)!=identities[entry]:raise OSError(errno.EAGAIN,'Cached BSS identity/frequency changed during sampling.')
        if scan_time(get(path,'.Device.Wireless','LastScan'))!=scan or aps(path)!=entries:
            raise OSError(errno.EAGAIN,'Wireless cached scan changed during sampling.')
        if unsigned(get(path,'.Device','DeviceType'))!=2 or get(path,'.Device','Interface')!=iface or wireless.identity(netdev)!=identity:
            raise OSError(errno.EAGAIN,'Wireless interface identity changed during cached sampling.')
        result.append(row)
    if devices()!=inventory or reader.owner(nm)!=owner:
        raise OSError(errno.EAGAIN,'NetworkManager device inventory or owner changed during cached sampling.')
    if not result:raise OSError(errno.ENODEV,'No wireless AP-cache provider is available.')
    return result

def bss_cache(iface):return wireless.parse_bss(wireless.query(iface,('scan','dump')))

def wifi_counter_snapshot(root,clock,boot_clock):
    start=clock();boot_start=boot_clock();rows={}
    for p in sorted(root.iterdir()):
        if not (p/'wireless').is_dir():continue
        try:
            def counter(path,maximum):
                raw=path.read_text().strip()
                if not raw.isascii() or not raw.isdecimal() or len(raw)>20 or int(raw)>maximum:
                    raise OSError(errno.EPROTO,'Invalid network counter.')
                return int(raw)
            index=counter(p/'ifindex',2**31-1)
            if index==0:raise OSError(errno.EPROTO,'Invalid network interface index.')
            info=p.stat()
            rows[p.name]={'identity':(index,str(p.resolve()),info.st_dev,info.st_ino),
                          'rx':counter(p/'statistics/rx_bytes',2**64-1),
                          'tx':counter(p/'statistics/tx_bytes',2**64-1)}
        except OSError as error:
            rows[p.name]={'errno':error.errno or errno.EIO,'error':'Wireless interface counters are unreadable or invalid.'}
    boot_end=boot_clock();end=clock()
    return {'time':(start+end)/2,'boot_time':(boot_start+boot_end)/2,
            'read_seconds':end-start,'interfaces':rows}

def wifi_byte_rates(args,root=Path('/sys/class/net'),clock=None,boot_clock=None,sleep=None):
    if not isinstance(args,dict) or set(args)-{'detailed'} or type(args.get('detailed',False)) is not bool:
        raise ValueError('Only an optional boolean detailed argument is accepted.')
    clock=clock or time.monotonic
    boot_clock=boot_clock or (lambda:time.clock_gettime(time.CLOCK_BOOTTIME))
    sleep=sleep or time.sleep
    before=wifi_counter_snapshot(root,clock,boot_clock);sleep(.25)
    after=wifi_counter_snapshot(root,clock,boot_clock)
    elapsed=after['time']-before['time'];boot_elapsed=after['boot_time']-before['boot_time']
    valid_interval=(math.isfinite(elapsed) and .1<=elapsed<=30 and math.isfinite(boot_elapsed) and
                    abs(boot_elapsed-elapsed)<=.05 and all(0<=s['read_seconds']<=.1 for s in (before,after)))
    names=sorted(set(before['interfaces'])|set(after['interfaces']))
    if not names:missing('No wireless interface counters are present.')
    rows=[]
    for name in names:
        a=before['interfaces'].get(name);b=after['interfaces'].get(name)
        row={'interface':name,'available':False}
        if not valid_interval:row.update(errno=errno.ENODATA,error='Invalid sampling interval, suspend gap or delayed counter snapshot.')
        elif a is None or b is None:row.update(errno=errno.ENODEV,error='Wireless interface was not present in both snapshots.')
        elif 'errno' in a or 'errno' in b:
            failure=a if 'errno' in a else b;row.update(errno=failure['errno'],error=failure['error'])
        elif a['identity']!=b['identity']:row.update(errno=errno.ENODEV,error='Wireless interface changed during sampling.')
        elif b['rx']<a['rx'] or b['tx']<a['tx']:row.update(errno=errno.ENODATA,error='Wireless byte counter reset or wrapped during sampling.')
        else:
            rx=(b['rx']-a['rx'])/elapsed;tx=(b['tx']-a['tx'])/elapsed
            row.update(available=True,rx_bytes_per_second=rx,tx_bytes_per_second=tx,bytes_per_second=rx+tx)
        rows.append(row)
    rates={r['interface']:r.get('bytes_per_second') for r in rows}
    if not args.get('detailed'):return rates
    return {'schema':1,'source':'Linux wireless-interface byte counters; measured monotonic interval',
            'sample_seconds':elapsed if math.isfinite(elapsed) else None,'rates_bytes_per_second':rates,'interfaces':rows,
            'note':'RX and TX counters are read sequentially, not atomically. No traffic generation, active scan or device setting is used. Unavailable counters are null, not zero.'}

BLUETOOTH_MAJOR={1:'Computer',2:'Phone',3:'LAN/Network Access Point',4:'Audio/Video',
                 5:'Peripheral',6:'Imaging',7:'Wearable',8:'Toy',9:'Health',31:'Uncategorized'}

def bluetooth_class(value,boolean_type=bool):
    if value is None:return {'available':False,'raw':None,'major_code':None,'major':None,
                             'errno':errno.ENODATA,'error':'Device has no Class-of-Device property; no class is inferred from its icon or service UUIDs.'}
    if not isinstance(value,int) or isinstance(value,(bool,boolean_type)) or not 0<=value<=0xffffff:
        return {'available':False,'raw':None,'major_code':None,'major':None,'errno':errno.EPROTO,'error':'Invalid Bluetooth Class-of-Device value.'}
    major=(int(value)>>8)&31
    return {'available':True,'raw':int(value),'major_code':major,'major':BLUETOOTH_MAJOR.get(major,'Other'),
            'source':'org.bluez.Device1.Class bits8..12; device-reported major class'}


def bluetooth():
    import dbus
    try:
        bus=dbus.SystemBus()
        # Bind an already-running daemon by unique owner, avoiding activation
        # and accidental rebinding if BlueZ restarts during this query.
        owner=bus.call_blocking('org.freedesktop.DBus','/org/freedesktop/DBus',
                               'org.freedesktop.DBus','GetNameOwner','s',('org.bluez',),timeout=5)
        if not isinstance(owner,str) or not owner.startswith(':'):
            raise OSError(errno.EPROTO,'Invalid BlueZ owner identity.')
        objects=bus.get_object(owner,'/',introspect=False).GetManagedObjects(
            dbus_interface='org.freedesktop.DBus.ObjectManager',timeout=5)
    except dbus.DBusException as error:
        name=error.get_dbus_name()
        code=errno.ENODEV if name.endswith(('ServiceUnknown','NameHasNoOwner')) else errno.EACCES if name.endswith(('AccessDenied','AuthFailed','NotAuthorized')) else errno.ETIMEDOUT if name.endswith(('NoReply','TimedOut','Timeout')) else errno.EIO
        raise OSError(code,'BlueZ connected-device enumeration failed.') from None
    if not isinstance(objects,dict) or len(objects)>4096:raise OSError(errno.EPROTO,'Invalid BlueZ object inventory.')
    out=[]
    for path,interfaces in objects.items():
        if not isinstance(interfaces,dict):raise OSError(errno.EPROTO,'Invalid BlueZ interface inventory.')
        if 'org.bluez.Device1' not in interfaces:continue
        d=interfaces['org.bluez.Device1']
        if not isinstance(d,dict) or not isinstance(d.get('Connected'),(bool,dbus.Boolean)) or int(d['Connected']) not in (0,1):
            raise OSError(errno.EPROTO,'BlueZ device has no valid connection status.')
        if not d['Connected']:continue
        row={'address':None,'name':None,'icon':None,'uuids':None,
             'device_class':bluetooth_class(d.get('Class'),dbus.Boolean)};errors=[]
        if row['device_class'].get('errno')==errno.EPROTO:errors.append('device_class')
        address=d.get('Address')
        if isinstance(address,str) and re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}',address):row['address']=str(address)
        else:errors.append('address')
        for prop,key,maximum in [('Alias','name',1024),('Icon','icon',128)]:
            value=d.get(prop)
            if value is not None:
                if isinstance(value,str) and 0<len(value)<=maximum and all(ord(c)>=32 and ord(c)!=127 for c in value):row[key]=str(value)
                else:errors.append(key)
        uuids=d.get('UUIDs')
        if uuids is not None:
            if isinstance(uuids,(list,tuple)) and len(uuids)<=256 and all(isinstance(u,str) and re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',u) for u in uuids):row['uuids']=[str(u) for u in uuids]
            else:errors.append('uuids')
        if errors:row['unavailable_metadata_fields']=errors
        out.append(row)
    try:
        current=bus.call_blocking('org.freedesktop.DBus','/org/freedesktop/DBus',
                                 'org.freedesktop.DBus','GetNameOwner','s',('org.bluez',),timeout=5)
    except dbus.DBusException:
        raise OSError(errno.EAGAIN,'BlueZ owner disappeared during connected-device sampling.') from None
    if current!=owner:raise OSError(errno.EAGAIN,'BlueZ owner changed during connected-device sampling.')
    return out
def usb_connector_capabilities():
    import usb_inventory
    return usb_inventory.capabilities()


def upc_connector(kind,connectable):
    import usb_inventory
    return usb_inventory.upc_connector(kind,connectable)


def host_usb_connector(name,caps,root=None):
    import usb_inventory
    return usb_inventory.host_connection(name,caps,root or Path('/sys/bus/usb/devices'))


def usb():
    import usb_inventory
    return usb_inventory.report()['devices']


def validate_usb_activity(args):
    if not isinstance(args,dict) or set(args)-{'metric'} or args.get('metric','disk_activity') not in ('disk_activity','usb_traffic'):
        raise ValueError('Only metric disk_activity or usb_traffic is accepted.')

def usb_transfer(args=None):
    args={} if args is None else args;validate_usb_activity(args)
    if args.get('metric')=='usb_traffic':
        from usb_activity import sample
        return sample()
    import disk_activity
    return disk_activity.report()

def validate_display_activity(args):
    if not isinstance(args,dict) or set(args)-{'metric'} or args.get('metric','hdmi_presence') not in ('hdmi_presence','usb_display'):
        raise ValueError('Only metric hdmi_presence or usb_display is accepted.')

def display_activity(args):
    validate_display_activity(args)
    if args.get('metric')=='usb_display':
        import usb_display
        return usb_display.report()
    import hdmi_presence
    return hdmi_presence.report()

def tablet_mode():
    import tablet_mode as provider
    return provider.value()


def gpu_usage():
    import gpu_usage as provider
    return provider.report()


def call(name,args):
    if name in hardware_memory.NAMES:return hardware_memory.call(name,args)
    if name in storage_inventory.NAMES:return storage_inventory.call(name,args)
    if name in process_counters.NAMES:return process_counters.call(name,args)
    if name in application_inventory.NAMES:return application_inventory.call(name,args)
    if name in cpu_metadata.NAMES:return cpu_metadata.call(name,args)
    if name in identity_inventory.NAMES:return identity_inventory.call(name,args)
    if name in battery_summary.NAMES:return battery_summary.call(name,args)
    if name in platform_metadata.NAMES:return platform_metadata.call(name,args)
    if name=='AppList_OpenWindows':return desktop_windows.call(args)
    if name in EMPTY_HW_READS and args:raise ValueError('This hardware query takes no arguments.')
    if name in ('BatteryHealthyTable_ACStatus','Power_Read_ACDCMode'):return ac_online()
    if name=='WMIGetWiFiBytesPersec':return wifi_byte_rates(args)
    if name.startswith('AppList_'):
        if name=='AppList_HardwareConfig':return hardware_config()
        raise ValueError('Unknown application-list query.')
    if name=='System_Check_S_Mode':return {'applicable':False,'platform':'Linux','reason':'Windows S Mode has no Linux counterpart'}
    if name=='System_Read_TabletMode':return tablet_mode()
    if name=='System_Read_VolumeLevel':return default_volume()
    if name in ('WMIGetExternMonitorNum','WMIGetExternMonitorPropList','WMIGetLCDModel'):
        import display_state
        return display_state.call(name,args)
    if name=='WMIGetMonitorBrightness':
        return monitor_brightness()
    if name.startswith(('WMIGetHDD','WMIGetSSD','WMIGetSDCard')):
        kind='all' if 'HDD' in name else 'ssd' if 'SSD' in name else 'sd'
        if name.endswith('Usage'):return disk_usage('hdd' if 'HDD' in name else 'ssd')
        if name.endswith('Temp'):return disk_temperatures(kind)
    if name=='WMIGetGPUUsg':
        return gpu_usage()
    if name.startswith('RF_BT'):
        rows=bluetooth()
        return len(rows) if name.endswith('Num') else bool(rows) if name.endswith('IsUsed') else rows
    if name.startswith('RF_WWAN'):
        import wwan
        return wwan.call(name,args)
    if name.startswith('RF_USB'):
        if name=='RF_USBIsTranster':return usb_transfer(args)
        if name=='RF_USBHDMIIsUsed':
            return display_activity(args)
        import usb_inventory
        return usb_inventory.call(name,args)
    if name in wireless.LINK_NAMES or name in wireless.RSSI_NAMES:return wireless.call(name,args)
    if name in ('RF_WiFiCardName','WMIGetWiFiCardName'):return wireless.cards()
    if name=='RF_Net_Connected_Type':
        import network_status
        return network_status.report()
    if name.startswith('RF_WiFi'):
        rows=wifi()
        band='2.4' if '_2_4G_' in name else '6' if '_6G_' in name else '5'
        unique={(a['bssid'],a['frequency_mhz']):a for x in rows for a in x['access_points']}
        aps=[a for a in unique.values() if wireless.band(a['frequency_mhz'])=={'2.4':'2_4G','5':'5G','6':'6G'}[band]]
        if name.endswith('Ch_Num'):
            channels={}
            for ap in aps:
                ch=wireless.channel(ap['frequency_mhz'])
                if ch is None:raise OSError(errno.ENODATA,'Cached BSS has no qualified channel number.')
                channels[str(ch)]=channels.get(str(ch),0)+1
            groups={key:channels.get(key,0) for key in ('1','6','11')}
            groups['other']=len(aps)-sum(groups.values())
            return {'channels':channels,'channel_groups':groups,'total_aps':len(aps)}
        if name.endswith(('Band_Num','NUII_Num')):
            limits=((5150,5250,'U-NII-1'),(5250,5350,'U-NII-2A'),(5470,5725,'U-NII-2C'),(5725,5895,'U-NII-3')) if band=='5' else ((5925,6425,'U-NII-5'),(6425,6525,'U-NII-6'),(6525,6875,'U-NII-7'),(6875,7125,'U-NII-8'))
            counts={label:sum(lo<=a['frequency_mhz']<hi for a in aps) for lo,hi,label in limits}
            return {'bands':counts,'total_aps':len(aps),'unclassified':len(aps)-sum(counts.values())}
        return len(aps)
    raise KeyError(name)

ROOT_READS={'WMIGetBoardUUID','WMIGetSN','WMIGetType2SN','WMIGetMemInfo','WMIGetMemSize','WMIGetMemFrequency',
 'WMIGetMemManufacture','WMIGetMemModel','System_Read_TabletMode',
'RF_WiFi_2_4G_AP_RSSI_Num','RF_WiFi_5G_AP_RSSI_Num','RF_WiFi_6G_AP_RSSI_Num','WMIGetGPUUsg','WMIGet90Number'}
