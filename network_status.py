# SPDX-License-Identifier: GPL-2.0-only
"""Connected physical network types, independent of routes and tunnel activity.

The original prefers Ethernet, cellular, then Wi-Fi. Native WWAN is a generic
cellular category: it does not claim that every modem uses Windows WWANPP2.
"""
from pathlib import Path
import errno
import re
import time
from platform_metadata import text

NET=Path('/sys/class/net')
NM='org.freedesktop.NetworkManager'
ROOT='/org/freedesktop/NetworkManager'
DEVICE=NM+'.Device'
PRIORITY=('ethernet','wwan','wifi')
TYPES={1:'ethernet',2:'wifi'}
VIRTUAL_TYPES={10,11,13,15,16,17,18,19,20,21,22,24,25,26,29,30,31,32}


def interface(value,empty=False):
    if not isinstance(value,str) or not (empty and value=='' or re.fullmatch(r'[^/\s\x00]{1,15}',value) and value not in ('.','..')):
        raise OSError(errno.EPROTO,'Invalid network interface name.')
    return str(value)


def manager_snapshot():
    import dbus
    deadline=time.monotonic()+5
    def timeout():
        remaining=deadline-time.monotonic()
        if remaining<=0:raise OSError(errno.ETIMEDOUT,'NetworkManager metadata deadline expired.')
        return min(5,remaining)
    try:
        bus=dbus.SystemBus()
        def owner():return bus.call_blocking('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetNameOwner','s',(NM,),timeout=timeout())
        unique=owner()
        if not isinstance(unique,str) or not re.fullmatch(r':[0-9]+\.[0-9]+',unique):raise OSError(errno.EPROTO,'Invalid NetworkManager owner.')
        remote=bus.get_object(unique,ROOT,introspect=False)
        def devices():
            paths=remote.GetDevices(dbus_interface=NM,timeout=timeout())
            if not isinstance(paths,(list,tuple)) or len(paths)>256 or any(not isinstance(p,str) or not re.fullmatch(ROOT+r'/Devices/[0-9]+',p) for p in paths) or len(set(paths))!=len(paths):
                raise OSError(errno.EPROTO,'Invalid NetworkManager device inventory.')
            return sorted(map(str,paths))
        paths=devices();rows={}
        for path in paths:
            props=bus.get_object(unique,path,introspect=False).GetAll(DEVICE,dbus_interface='org.freedesktop.DBus.Properties',timeout=timeout())
            if not isinstance(props,dict):raise OSError(errno.EPROTO,'Invalid NetworkManager device metadata.')
            kind=props.get('DeviceType')
            if not isinstance(kind,int) or isinstance(kind,(bool,dbus.Boolean)) or not 0<=kind<=2**32-1:raise OSError(errno.EPROTO,'Invalid network device type.')
            control=interface(props.get('Interface'));ip=interface(props.get('IpInterface'),True)
            name=ip or control
            if name in rows:raise OSError(errno.EPROTO,'Duplicate NetworkManager data interface.')
            classification=TYPES.get(int(kind));excluded=int(kind) in VIRTUAL_TYPES
            caps=None;class_error=None
            if kind==8:
                try:
                    # Read only capabilities, not APN/operator/device identity.
                    caps=bus.get_object(unique,path,introspect=False).Get(
                        DEVICE+'.Modem','CurrentCapabilities',dbus_interface='org.freedesktop.DBus.Properties',timeout=timeout())
                    if not isinstance(caps,int) or isinstance(caps,(bool,dbus.Boolean)) or not 0<=caps<=2**32-1:
                        raise OSError(errno.EPROTO,'Invalid current modem capabilities.')
                    caps=int(caps)
                    if caps&(2|4|8|64) and not caps&1:classification='wwan'
                    elif caps==1:excluded=True # Analog POTS is not cellular.
                except (OSError,dbus.DBusException) as error:
                    caps=None;class_error={'errno':getattr(error,'errno',None) or errno.ENODATA,'error':'Current modem family is unavailable.'}
            rows[name]={'device_type':int(kind),'kind':classification,'control_interface':control,
                        'excluded':excluded,'current_modem_capabilities':caps,'classification_error':class_error}
        if paths!=devices() or unique!=owner():raise OSError(errno.EAGAIN,'NetworkManager owner/device inventory changed.')
        return {'owner':str(unique),'interfaces':rows}
    except dbus.DBusException as error:
        name=error.get_dbus_name()
        code=errno.ENODEV if name.endswith(('NameHasNoOwner','ServiceUnknown')) else errno.EACCES if name.endswith(('AccessDenied','AuthFailed','NotAuthorized')) else errno.ETIMEDOUT if name.endswith(('NoReply','TimedOut','Timeout')) else errno.EIO
        raise OSError(code,'NetworkManager read-only device classification failed.') from None


def physical(root):
    rows={}
    for path in sorted(root.iterdir()):
        interface(path.name)
        try:device=(path/'device').stat()
        except FileNotFoundError:continue
        st=path.stat();index=text(path/'ifindex')
        if not re.fullmatch(r'[0-9]{1,10}',index) or not 0<int(index)<=2**31-1:raise OSError(errno.EPROTO,'Invalid network interface identity.')
        rows[path.name]=(st.st_dev,st.st_ino,int(index),device.st_dev,device.st_ino)
    if len(rows)>256:raise OSError(errno.EOVERFLOW,'Physical network inventory exceeds its bound.')
    return rows


def link(path):
    flags=text(path/'flags')
    if not re.fullmatch(r'0x[0-9a-fA-F]{1,8}',flags):raise OSError(errno.EPROTO,'Invalid network interface flags.')
    state=text(path/'operstate')
    if state not in ('unknown','notpresent','down','lowerlayerdown','testing','dormant','up'):raise OSError(errno.EPROTO,'Invalid network operational state.')
    up=bool(int(flags,16)&1)
    carrier=None
    if up:
        raw=text(path/'carrier')
        if raw not in ('0','1'):raise OSError(errno.EPROTO,'Invalid physical media state.')
        carrier=raw=='1'
    return {'administratively_up':up,'operstate':state,'carrier':carrier,'connected':up and carrier}


def failure(error):return {'errno':getattr(error,'errno',None) or errno.EPROTO,'error':str(error)}


def report(root=None):
    root=NET if root is None else root
    before=physical(root);rows=[];errors=[];nm=None
    try:nm=manager_snapshot()
    except OSError as error:errors.append({'provider':'NetworkManager',**failure(error)})
    for name,identity in before.items():
        row={'interface':name,'ifindex':identity[2],'connected':None,'type':None,'type_available':False,'scope_applicable':None}
        path=root/name
        try:
            a=link(path)
            try:(path/'wireless').stat();wifi=True
            except FileNotFoundError:wifi=False
            metadata=nm['interfaces'].get(name) if nm else None
            kind=metadata['kind'] if metadata else None
            excluded=bool(metadata and metadata.get('excluded'))
            if not excluded and wifi and kind not in (None,'wifi'):raise OSError(errno.EAGAIN,'Kernel and NetworkManager network classifications disagree.')
            if not excluded and not wifi and kind=='wifi':raise OSError(errno.EAGAIN,'NetworkManager Wi-Fi interface lacks kernel wireless identity.')
            if wifi and not excluded:kind='wifi'
            row.update(a,type=kind,type_available=kind is not None,scope_applicable=False if excluded else True if kind else None,
                       type_source='NetworkManager DeviceType/capability exclusion' if excluded else 'Linux physical wireless device' if wifi else 'NetworkManager DeviceType' if kind else None)
            if metadata:
                row['device_type']=metadata['device_type']
                if metadata['device_type']==8:row['current_modem_capabilities']=metadata.get('current_modem_capabilities')
            if a!=link(path):raise OSError(errno.EAGAIN,'Physical link state changed during sampling.')
            if row['connected'] and kind is None and not excluded:
                row['type_error']=metadata.get('classification_error') if metadata and metadata.get('classification_error') else {'errno':errno.ENODATA,'error':'Connected physical interface has no verified Ethernet/cellular/Wi-Fi classification.'}
        except OSError as error:
            row.update(connected=None,type=None,type_available=False,**failure(error))
        rows.append(row)
    stable=True
    try:
        if before!=physical(root):raise OSError(errno.EAGAIN,'Physical network identity/inventory changed.')
        if nm is not None and nm!=manager_snapshot():raise OSError(errno.EAGAIN,'Network device classifications changed during sampling.')
    except OSError as error:stable=False;errors.append({'provider':'inventory_consistency',**failure(error)})
    candidates=[r for r in rows if r['scope_applicable'] is not False]
    known={r['type'] for r in candidates if r['connected'] is True and r['type'] is not None}
    ordered=[kind for kind in PRIORITY if kind in known]
    unknown=not stable or any(r['connected'] is None or r['connected'] is True and r['type'] is None for r in candidates)
    connected=None if not stable else True if any(r['connected'] is True for r in candidates) else None if unknown else False
    preferred=ordered[0] if ordered else None
    primary=preferred if stable and (not unknown or preferred=='ethernet') else None
    complete=not unknown
    return {'available':complete or primary is not None,'complete':complete,
            'connected':connected,'primary_type':primary,'preferred_known_type':preferred,
            'connected_types':ordered,'priority':list(PRIORITY),'interfaces':rows,'errors':errors,
            'source':'Linux device-backed physical links and existing NetworkManager DeviceType',
            'note':'Connected physical media, not Internet reachability or default-route selection. Virtual/tunnel devices are excluded. Cellular is generic WWAN, without a3GPP2 claim. No scan, activation or settings operation.'}
