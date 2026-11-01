# SPDX-License-Identifier: GPL-2.0-only
"""Existing desktop window providers plus PID-scoped, read-only process counters."""
import errno
import json
import os
from pathlib import Path
import re
import time
import process_counters

NAME='org.zenbook.HardwareBridge'
PATH='/org/zenbook/HardwareBridge'
# The bridge runs inside GNOME Shell; any other owner of the well-known name is
# a same-user impostor and its data is not trusted.
SHELL_EXECUTABLES=('/usr/bin/gnome-shell',)
TITLES_DISABLED='org.zenbook.HardwareBridge.Error.TitlesDisabled'
PROC=Path('/proc')


class TitlesDisabled(OSError):
    """The bridge owner has not opted in to exposing window titles."""


def validate(args):
    if not isinstance(args,dict) or set(args)-{'include_titles'} or type(args.get('include_titles',False)) is not bool:
        raise ValueError('Only an optional boolean include_titles argument is accepted.')


def _dbus_error(error):
    name=error.get_dbus_name()
    return (errno.ENODEV if name.endswith(('ServiceUnknown','NameHasNoOwner')) else
            errno.EACCES if name.endswith(('AccessDenied','AuthFailed','NotAuthorized')) else
            errno.ETIMEDOUT if name.endswith(('NoReply','TimedOut','Timeout')) else
            errno.EOPNOTSUPP if name.endswith(('UnknownMethod','UnknownInterface')) else errno.EIO)


def _manager(bus,method,value):
    return bus.call_blocking('org.freedesktop.DBus','/org/freedesktop/DBus',
                             'org.freedesktop.DBus',method,'s',(value,),timeout=2)


def _owner(bus,name):
    import dbus
    value=_manager(bus,'GetNameOwner',name)
    if not isinstance(value,str) or not re.fullmatch(r':[0-9]+\.[0-9]+',value):
        raise OSError(errno.EPROTO,'Invalid existing desktop provider owner.')
    uid=_manager(bus,'GetConnectionUnixUser',value)
    if isinstance(uid,(bool,dbus.Boolean)) or not isinstance(uid,int) or uid!=os.geteuid():
        raise OSError(errno.EACCES,'Desktop provider belongs to another user.')
    return value


def _start_time(pid,proc):
    raw=(proc/str(pid)/'stat').read_text(errors='strict')
    fields=raw[raw.rindex(')')+2:].split()
    if len(fields)<20 or not fields[19].isdigit():raise OSError(errno.EPROTO,'Invalid desktop provider process state.')
    return fields[19]


def _shell_owner(bus,name,proc=None):
    """Pin the bridge's unique owner and verify it is the GNOME Shell process."""
    import dbus
    proc=PROC if proc is None else proc
    owner=_owner(bus,name)
    pid=_manager(bus,'GetConnectionUnixProcessID',owner)
    if isinstance(pid,(bool,dbus.Boolean)) or not isinstance(pid,int) or not 0<pid<2**31:
        raise OSError(errno.EPROTO,'Invalid desktop provider process.')
    try:
        before=_start_time(int(pid),proc);exe=os.readlink(proc/str(int(pid))/'exe');after=_start_time(int(pid),proc)
    except (OSError,ValueError,UnicodeError):raise OSError(errno.EACCES,'Desktop provider process cannot be verified.') from None
    if before!=after or exe not in SHELL_EXECUTABLES:
        raise OSError(errno.EACCES,'Desktop provider name is not owned by GNOME Shell.')
    if _manager(bus,'GetConnectionUnixProcessID',owner)!=pid:raise OSError(errno.EAGAIN,'Desktop provider process changed.')
    return owner


def decode(raw,include_titles,version):
    if not isinstance(raw,str) or len(raw)>1024*1024:raise OSError(errno.E2BIG,'Window metadata exceeds its bound.')
    try:data=json.loads(raw)
    except ValueError:raise OSError(errno.EPROTO,'Invalid window metadata JSON.') from None
    if (not isinstance(data,dict) or data.get('source')!='GNOME Shell' or
        type(data.get('titles_included')) is not bool or data['titles_included']!=include_titles or
        not isinstance(data.get('windows'),list) or len(data['windows'])>4096):
        raise OSError(errno.EPROTO,'Invalid compositor window report.')
    if version=='4' and (type(data.get('schema')) is not int or data['schema']!=1 or type(data.get('complete')) is not bool or
                         type(data.get('enumeration_errors')) is not int or not 0<=data['enumeration_errors']<=4096 or
                         (data['complete'] and data['enumeration_errors'])):
        raise OSError(errno.EPROTO,'Invalid compositor completeness metadata.')
    rows=[];seen=set()
    for value in data['windows']:
        if (not isinstance(value,dict) or type(value.get('id')) is not int or not 0<=value['id']<2**32 or
            value['id'] in seen or type(value.get('pid')) is not int or not 0<=value['pid']<2**31 or
            type(value.get('focused')) is not bool or type(value.get('minimized')) is not bool):
            raise OSError(errno.EPROTO,'Invalid compositor window identity/state.')
        seen.add(value['id'])
        if not include_titles and 'title' in value:raise OSError(errno.EPROTO,'Provider returned unrequested window titles.')
        keys=['app_id','application']+(['title'] if include_titles else [])
        if any(value.get(k) is not None and (not isinstance(value[k],str) or len(value[k])>65536) for k in keys):
            raise OSError(errno.EPROTO,'Invalid compositor window text field.')
        if version=='4' and (type(value.get('z_order')) is not int or value['z_order']!=len(rows)):
            raise OSError(errno.EPROTO,'Invalid top-first compositor stack order.')
        row={k:value.get(k) for k in ['id','pid','app_id','application','focused','minimized']+(['title'] if include_titles else [])}
        row['z_order']=value['z_order'] if version=='4' else None
        rows.append(row)
    return {'available':True,'windows':rows,'source':'GNOME Shell','bridge_version':version,
            'complete':version=='4' and data['complete'],'titles_included':include_titles,
            'enumeration_errors':data.get('enumeration_errors',0),
            'coverage':'Native normal Alt-Tab windows across workspaces; compositor stack top-first. Bridge3 lacks verified stack metadata.'}


def _bridge(bus,include_titles):
    import dbus
    try:
        owner=_shell_owner(bus,NAME);obj=bus.get_object(owner,PATH,introspect=False)
        version=obj.GetVersion(dbus_interface=NAME,timeout=2)
        if version not in ('3','4'):raise OSError(errno.EOPNOTSUPP,'Unsupported desktop bridge version.')
        result=decode(obj.GetWindows(include_titles,dbus_interface=NAME,timeout=2),include_titles,version)
        if _manager(bus,'GetNameOwner',NAME)!=owner:raise OSError(errno.EAGAIN,'Window provider owner changed.')
        return result
    except dbus.DBusException as error:
        if error.get_dbus_name()==TITLES_DISABLED:
            raise TitlesDisabled(errno.EACCES,'Window titles are disabled; the desktop user can opt in with '
                                 'expose_window_titles in ~/.config/zenbook-hardware/bridge.json.') from None
        raise OSError(_dbus_error(error),'Existing compositor window query is unavailable.') from None


def _accessibility(bus,include_titles):
    import dbus
    registry=None
    try:
        owner=_owner(bus,'org.a11y.Bus')
        proxy=bus.get_object(owner,'/org/a11y/bus',introspect=False)
        address=proxy.GetAddress(dbus_interface='org.a11y.Bus',timeout=2)
        if not isinstance(address,str) or not address.startswith('unix:') or ';' in address or len(address)>1024:
            raise OSError(errno.EPROTO,'Invalid existing accessibility bus address.')
        registry=dbus.bus.BusConnection(address)
        registry_owner=_owner(registry,'org.a11y.atspi.Registry')
        deadline=time.monotonic()+8
        accessible='org.a11y.atspi.Accessible'
        def invoke(destination,path,interface,method,signature='',args=()):
            remaining=deadline-time.monotonic()
            if remaining<=0:raise OSError(errno.ETIMEDOUT,'Accessibility enumeration exceeded its time bound.')
            # Unique owners cannot activate a service, including during a race
            # with an application or registry exiting. Never initialize libatspi.
            return registry.call_blocking(destination,path,interface,method,signature,args,timeout=min(.4,remaining))
        def refs(value,limit):
            if not isinstance(value,(list,tuple)) or len(value)>limit:
                raise OSError(errno.E2BIG,'Accessibility census exceeds its bound.')
            for item in value:
                if (not isinstance(item,(list,tuple)) or len(item)!=2 or not isinstance(item[0],str) or
                    not re.fullmatch(r':[0-9]+\.[0-9]+',item[0]) or not isinstance(item[1],str) or
                    not re.fullmatch(r'/(?:[A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)*)?',item[1])):
                    raise OSError(errno.EPROTO,'Invalid existing accessible-object reference.')
            return value
        def name(destination,path):
            value=invoke(destination,path,'org.freedesktop.DBus.Properties','Get','ss',(accessible,'Name'))
            if not isinstance(value,str) or len(value)>65536:raise OSError(errno.EPROTO,'Invalid accessible name.')
            return value
        applications=refs(invoke(registry_owner,'/org/a11y/atspi/accessible/root',accessible,'GetChildren'),2048)
        rows=[];failures=0
        for destination,path in applications:
            if time.monotonic()>=deadline:failures+=1;break
            try:
                pinned=_owner(registry,destination)
                pid=_manager(registry,'GetConnectionUnixProcessID',pinned)
                if isinstance(pid,(bool,dbus.Boolean)) or not isinstance(pid,int) or not 0<pid<2**31:
                    raise OSError(errno.EPROTO,'Invalid accessible application PID.')
                children=refs(invoke(pinned,path,accessible,'GetChildren'),4096)
                application=None
                for window_owner,window_path in children:
                    if time.monotonic()>=deadline:failures+=1;break
                    try:
                        if window_owner!=pinned:raise OSError(errno.EPROTO,'Accessible window belongs to another application.')
                        role=invoke(pinned,window_path,accessible,'GetRole')
                        if isinstance(role,(bool,dbus.Boolean)) or not isinstance(role,int):
                            raise OSError(errno.EPROTO,'Invalid accessible role.')
                        # AT-SPI role enum: DIALOG16, FRAME23, WINDOW69.
                        if role not in (16,23,69):continue
                        if application is None:application=name(pinned,path)
                        row={'id':None,'pid':int(pid),'application':application,'app_id':None,
                             'focused':None,'minimized':None,'z_order':None}
                        if include_titles:row['title']=name(pinned,window_path)
                        if len(rows)>=4096:raise OSError(errno.E2BIG,'Accessibility window census exceeds its bound.')
                        rows.append(row)
                    except (OSError,dbus.DBusException):failures+=1
            except (OSError,dbus.DBusException):failures+=1
        if _manager(bus,'GetNameOwner','org.a11y.Bus')!=owner or _manager(registry,'GetNameOwner','org.a11y.atspi.Registry')!=registry_owner:
            raise OSError(errno.EAGAIN,'Accessibility provider owner changed.')
        return {'available':True,'windows':rows,'source':'AT-SPI','complete':False,
                'titles_included':include_titles,'enumeration_errors':failures,
                'coverage':'Only applications exposed to an existing accessibility registry. Compositor identity, stack, focus and minimization are unavailable.'}
    except dbus.DBusException as error:raise OSError(_dbus_error(error),'Existing accessibility registry is unavailable.') from None
    finally:
        if registry is not None:registry.close()


def query(include_titles):
    errors=[]
    address=os.environ.get('DBUS_SESSION_BUS_ADDRESS','')
    if not address.startswith('unix:') or ';' in address or len(address)>1024:
        return {'available':False,'windows':[],'complete':False,'titles_included':include_titles,
                'errno':errno.ENODEV,'error':'No existing local desktop bus.'}
    try:
        import dbus
        bus=dbus.SessionBus()
        for source,read in [('GNOME Shell',_bridge),('AT-SPI',_accessibility)]:
            try:
                result=read(bus,include_titles);result['provider_errors']=errors;return result
            except TitlesDisabled as error:
                # Owner policy, not an outage: never route titles around it.
                errors.append({'source':source,'errno':error.errno,'error':str(error)});break
            except OSError as error:errors.append({'source':source,'errno':error.errno or errno.EIO,'error':str(error)})
    except ImportError:errors.append({'errno':errno.ENODEV,'error':'Desktop D-Bus bindings unavailable.'})
    except dbus.DBusException as error:errors.append({'errno':_dbus_error(error),'error':'Existing desktop bus unavailable.'})
    return {'available':False,'windows':[],'complete':False,'titles_included':include_titles,
            'errno':errors[-1]['errno'],'error':'No existing window metadata provider.','provider_errors':errors}


def call(args):
    validate(args);titles=args.get('include_titles',False);before=query(titles)
    if not before['available']:return before
    pids=sorted({row['pid'] for row in before['windows'] if row['pid']>0})
    try:measurements=process_counters.sample_pids(pids)
    except OSError as error:measurements={'processes':[],'sampling':{},'errno':error.errno or errno.EIO,'error':str(error)}
    result=query(titles)
    if not result['available']:return result
    values={row['pid']:row for row in measurements['processes']};complete=True;identity_errors={}
    for pid in {row['pid'] for row in result['windows']} & values.keys():
        try:process_counters.verify_identity(pid,values[pid]['start_ticks'])
        except OSError as error:
            del values[pid];identity_errors[pid]={'process_errno':error.errno or errno.EIO,'process_error':str(error)}
    for window in result['windows']:
        sample=values.get(window['pid'])
        window.update(process_name=sample['name'] if sample else None,
                      cpu_percent=sample['cpu_percent'] if sample else None,
                      cpu_available=bool(sample and sample['cpu_available']),
                      rss_bytes=sample['rss_bytes'] if sample else None,
                      rss_available=bool(sample and sample['rss_available']))
        if sample:
            for key in ['cpu_errno','cpu_error','rss_errno','rss_error','start_ticks',
                        'sample_interval_seconds','cpu_time_delta_ticks','sample_read_window_seconds']:
                if key in sample:window[key]=sample[key]
        else:window.update(identity_errors.get(window['pid']) or {'process_errno':errno.ENODATA,'process_error':'No valid sample for the reported window PID.'})
        complete&=window['cpu_available'] and window['rss_available']
    result.update(process_metrics_complete=complete,process_sampling=measurements.get('sampling',{}),
                  process_sample_errors=measurements.get('sample_errors',[]),
                  process_sample_error_count=measurements.get('sample_error_count',0),
                  provider_changed=before.get('source')!=result.get('source'),
                  note='CPU uses one CPU100%; RSS bytes and CPU are process totals shared by windows of the same PID, not additive per-window allocations. Zero-based z_order0 is topmost among native normal windows. Titles are opt-in; no provider activation, input events or process command lines/environments are read.')
    if 'errno' in measurements:result.update(process_errno=measurements['errno'],process_error=measurements['error'])
    return result
