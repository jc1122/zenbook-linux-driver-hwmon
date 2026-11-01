# SPDX-License-Identifier: GPL-2.0-only
"""Policy and safety logic for the privileged Zenbook hardware service.

This module is free of D-Bus/GLib so it can be unit tested with fakes. The
daemon (zenbook_hardwared.py) wires it to the system bus and to polkit.
"""
from pathlib import Path
import errno
import json
import math
import os
import re
import secrets
import threading
import time

BUS_NAME='org.zenbook.Hardware1'
OBJECT_PATH='/org/zenbook/Hardware1'
INTERFACE='org.zenbook.Hardware1'
ERROR_PREFIX='org.zenbook.Hardware1.Error.'
GROUP='zenbook-hw'
HERE=Path(__file__).resolve().parent

PREFIX='org.zenbook.hardware.'
READ=PREFIX+'read'
READ_IDENTIFIERS=PREFIX+'read-identifiers'
SETTINGS=PREFIX+'settings'
FAN_LEASE=PREFIX+'fan-lease'
EC_OEM=PREFIX+'ec-oem'
FIRMWARE=PREFIX+'firmware'
DRIVER=PREFIX+'driver'
# Polkit defaults (allow_any, allow_inactive, allow_active) and whether calls
# are mutating (audited, stricter rate limit). Mirrors the .policy file.
ACTIONS={
    READ:(('no','no','yes'),False),
    READ_IDENTIFIERS:(('no','no','auth_admin_keep'),False),
    SETTINGS:(('no','auth_admin','auth_admin_keep'),True),
    FAN_LEASE:(('no','no','auth_admin_keep'),True),
    EC_OEM:(('no','no','auth_admin'),True),
    FIRMWARE:(('no','no','auth_admin'),True),
    DRIVER:(('no','no','auth_admin'),True),
}
# The only actions the zenbook-hw polkit rule may grant without a password.
GROUP_GRANTED=frozenset({READ,READ_IDENTIFIERS,SETTINGS,FAN_LEASE})
NEVER_GROUP_GRANTED=frozenset({EC_OEM,FIRMWARE,DRIVER})

# Exports that touch the caller's home, a caller-chosen path or the caller's
# journal identity. They stay in the unprivileged client.
CLIENT_ONLY={'WMISetAppPath':'writes the caller application configuration',
             'SaveEcLog':'writes a caller-chosen file; record through the client',
             'TraceOutput':'journal entries must carry the caller identity',
             'TraceOutputCritical':'journal entries must carry the caller identity'}
# The service applies the hardware part only; the client persists the choice
# as the user (the root service has no home access).
HARDWARE_ONLY={'WMISetBatteryHealthToUser':('charge-limit','percent','battery_charge_limit_percent'),
               'WMISetQuietFan':('profile','profile','platform_profile')}
FAN_EXPORTS={'HealthyTable_SetFanPwmDuty','HealthyTable_SetFanTestMode'}
# Typed CLI controls for the later client migration (no ASUS export exists for
# the keyboard backlight). Fan control is only available through leases.
# The two sysfs trigger writes (diagnostics_reprobe, battery_lifetime_refresh)
# cause EC broker traffic, so they need `settings`, like other writes.
CONTROLS={'profile':SETTINGS,'charge-limit':SETTINGS,'keyboard':SETTINGS,
          'battery-gauge':READ,'charger':READ,'reprobe':SETTINGS,'battery-history-refresh':SETTINGS,
          'usb-activity':READ,'power':READ}
# Plan/apply exports. Apply through the service needs a single-use token from
# PlanMutation; a caller-computed expected_sha256 alone never authorises it.
MUTATION_EXPORTS=frozenset({'Adapter_Clear_Charger_Data','Adapter_Clear_Power_Data_Flag','Adapter_Read_Charger_Interrupt',
    'Adapter_Read_Power_Data_Flag','Adapter_Set_Notify_Control','Power_Set_Monitor_PowerDropped','WOA_EC_write',
    'GPNV_Clear_CSC_Repair_Flag','GPNV_Set_ActivatedTime','GPNV_Set_ManufacturedTime','GPNV_Set_RandomUUID',
    'Update_AsusOsLanguage','StopWinIoDriver'})
# Mutations the sandbox can apply (EC/OEM requests through the driver). Firmware
# and driver applies need capabilities the service does not hold.
SERVICE_APPLY=frozenset(n for n in MUTATION_EXPORTS if n not in {'GPNV_Clear_CSC_Repair_Flag','GPNV_Set_ActivatedTime',
    'GPNV_Set_ManufacturedTime','GPNV_Set_RandomUUID','Update_AsusOsLanguage','StopWinIoDriver'})
# Heavy reads and firmware-cache refreshes: at most one per 10 s per uid and globally.
SLOW_CALLS=frozenset({'GetEEPROM_Data','BatteryHealthyTable_BatteryInformation','BatteryHealthyTable_PFStatus',
    'BatteryHealthyTable_SafetyStatus','BatteryHealthy_Read_PFStatus'})
SLOW_CONTROLS=frozenset({'reprobe','battery-history-refresh','charger'})
# Slow reads that read the same firmware cache form one shared refresh: the
# first read of a group in a window spends the slow budget; the group's other
# reads in that window ride along (each at most once, via the slow cache).
SLOW_GROUPS={'BatteryHealthyTable_PFStatus':'battery_gauge_status','BatteryHealthyTable_SafetyStatus':'battery_gauge_status',
    'BatteryHealthy_Read_PFStatus':'battery_pf_cache','BatteryHealthyTable_BatteryInformation':'battery_information',
    'GetEEPROM_Data':'eeprom'}
SLOW_SECONDS=10.0
SLOW_WAIT_SECONDS=5.0
SANDBOX_ERRNOS=frozenset({errno.EPERM,errno.EACCES})
# Reads that must always be fresh (fan state during leases/tests).
CACHE_EXEMPT=frozenset({'HealthyTable_FanCounts','HealthyTable_FanRPM','HealthyTable_GetFanTestMode','HealthyTable_Read_Fan',
    'ProArt_Read_Fan','Thermal_Read_Fan'})
CACHE_SECONDS=2.0
# VitalsMetrics(): only the Metrics() sections integrations/vitals/service.js
# converts, from the same provider functions metrics.report() uses. Excludes the
# expensive walks (ec_diagnostics, wireless, firmware, SMART, thermistors...).
VITALS_SECTIONS={'battery_gauge':('battery_diagnostics','report'),'battery_lifetime':('battery_diagnostics','lifetime_report'),
    'battery_gauge_extra':('battery_extra','report'),'battery_sbs':('battery_sbs','report'),
    'usb_pd_identity':('pd_identity','report'),'charger_input':('charger_adc','report'),'charger':('charger_metrics','report'),
    'platform_power':('pd_contract','platform_power'),'cpu_package_power':('package_power','report')}
TOKEN_SECONDS=60
GLOBAL_KEY=-1

MAX_ARGS_BYTES=65536
MAX_NAME=128
LEASE_MIN_SECONDS=1
LEASE_MAX_SECONDS=300
LOW_RPM_FLOOR=500
NAME_RE=re.compile(r'[A-Za-z0-9_]{1,128}')
DIGEST_RE=re.compile(r'[0-9a-f]{64}')
LEASE_RE=re.compile(r'[0-9a-f]{32}')


class ServiceError(OSError):
    """An error reported to clients with a stable errno."""


def error_detail(error):
    """Same errno mapping and detail fields as api_bridge.main()."""
    code=getattr(error,'errno',None) or (errno.EACCES if isinstance(error,PermissionError) else errno.EINVAL if isinstance(error,(ValueError,KeyError)) else errno.EIO)
    detail={'errno':code,'message':str(error)}
    if hasattr(error,'control_result'):detail['control']=error.control_result
    if hasattr(error,'committed'):detail['configuration_committed']=error.committed
    return detail


def success(result):
    return json.dumps({'ok':True,'result':result},allow_nan=False)


def failure(error):
    detail=error_detail(error)
    try:return json.dumps({'ok':False,'error':detail},allow_nan=False)
    except (TypeError,ValueError):
        return json.dumps({'ok':False,'error':{'errno':detail['errno'],'message':detail['message']}})


def dbus_error_name(code):
    return ERROR_PREFIX+errno.errorcode.get(code,'EIO')


def _no_constants(value):raise ValueError('Non-finite JSON value.')


def _finite_float(text):
    value=float(text)
    if not math.isfinite(value):raise ValueError('Non-finite JSON value.')
    return value


def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate JSON key.')
        result[key]=value
    return result


def parse_args(args_json):
    if not isinstance(args_json,str):raise ServiceError(errno.EINVAL,'Arguments must be a JSON string.')
    if len(args_json.encode('utf-8','surrogatepass'))>MAX_ARGS_BYTES:raise ServiceError(errno.E2BIG,'Request exceeds 64 KiB.')
    try:args=json.loads(args_json or '{}',object_pairs_hook=_unique,parse_constant=_no_constants,parse_float=_finite_float)
    except (ValueError,RecursionError) as error:raise ServiceError(errno.EINVAL,'Invalid JSON arguments: '+str(error)) from None
    if not isinstance(args,dict):raise ServiceError(errno.EINVAL,'API arguments must be a JSON object.')
    return args


def parse_call(name,args_json,apply,expected_sha256,authorization):
    """Validate a Call request; returns (name, args, apply, digest, action)."""
    if not isinstance(name,str) or not NAME_RE.fullmatch(name) or name not in authorization:
        raise ServiceError(errno.EINVAL,'Unknown ASUS API name.')
    if not isinstance(apply,bool):raise ServiceError(errno.EINVAL,'apply must be a boolean.')
    if not isinstance(expected_sha256,str) or (expected_sha256 and not DIGEST_RE.fullmatch(expected_sha256)):
        raise ServiceError(errno.EINVAL,'expected_sha256 must be empty or 64 lowercase hex digits.')
    return name,parse_args(args_json),apply,expected_sha256 or None,authorization[name]


def load_authorization(exports,path=None):
    """Load the export -> action table; refuse any gap, extra or unknown action."""
    path=Path(path or HERE/'authorization.json')
    data=json.loads(path.read_text())
    if not isinstance(data,dict) or data.get('schema')!=1 or not isinstance(data.get('exports'),dict):
        raise ValueError('Invalid authorization table schema.')
    table=data['exports'];exports=set(exports)
    missing=sorted(exports-set(table));extra=sorted(set(table)-exports)
    if missing:raise ValueError('Exports without a polkit action: '+', '.join(missing))
    if extra:raise ValueError('Authorization entries for unknown exports: '+', '.join(extra))
    unknown=sorted({a for a in table.values()}-set(ACTIONS))
    if unknown:raise ValueError('Unknown polkit actions: '+', '.join(unknown))
    return dict(table)


def is_mutating(action):return ACTIONS[action][1]


class RateLimiter:
    """Token buckets per (uid, class). Keyed by uid so reconnecting does not reset."""
    # slow: one refresh per 10 s on average with a burst of 3, so a full CLI
    # `show` (gauge-status, PF-cache and battery-information groups) fits.
    LIMITS={'read':(20.0,40.0),'mutating':(2.0,10.0),'slow':(0.1,3.0)}

    def __init__(self,clock=time.monotonic,limits=None,max_keys=4096):
        self.clock=clock;self.limits=dict(limits or self.LIMITS);self.max_keys=max_keys;self.buckets={}
        self.lock=threading.Lock()

    def allow(self,uid,kind):return self.allow_all([(uid,kind)])

    def allow_slow(self,uid):
        """Slow class: the caller's bucket and the global bucket must both allow."""
        return self.allow_all([(uid,'slow'),(GLOBAL_KEY,'slow')])

    def allow_all(self,keys):
        now=self.clock()
        with self.lock:
            if len(self.buckets)>=self.max_keys and any(k not in self.buckets for k in keys):self.buckets.clear()
            refreshed={}
            for key in keys:
                rate,burst=self.limits[key[1]]
                tokens,last=self.buckets.get(key,(burst,now))
                refreshed[key]=min(burst,tokens+(now-last)*rate)
            allowed=all(t>=1 for t in refreshed.values())
            for key,tokens in refreshed.items():self.buckets[key]=(tokens-1 if allowed else tokens,now)
            return allowed


class ResultCache:
    """Short-lived cache of serialised successful read replies, served on the
    main loop without the provider worker. Authorisation still runs per call."""

    def __init__(self,clock=time.monotonic,seconds=CACHE_SECONDS,max_entries=256):
        self.clock=clock;self.seconds=seconds;self.max_entries=max_entries;self.entries={}

    @staticmethod
    def key(name,args):return (name,json.dumps(args,sort_keys=True,separators=(',',':')))

    def get(self,key):
        hit=self.entries.get(key)
        if hit and self.clock()-hit[0]<self.seconds:return hit[1]
        self.entries.pop(key,None);return None

    def put(self,key,value):
        now=self.clock()
        if len(self.entries)>=self.max_entries:
            self.entries={k:v for k,v in self.entries.items() if now-v[0]<self.seconds}
            while len(self.entries)>=self.max_entries:self.entries.pop(next(iter(self.entries)))
        self.entries[key]=(now,value)


def slow_wait(limiter,uid):
    """Seconds until the caller's and the global slow buckets both hold a token."""
    now=limiter.clock();longest=0.0
    with limiter.lock:
        for key in ((uid,'slow'),(GLOBAL_KEY,'slow')):
            rate,burst=limiter.limits['slow']
            tokens,last=limiter.buckets.get(key,(burst,now))
            tokens=min(burst,tokens+(now-last)*rate)
            if tokens<1:longest=max(longest,(1-tokens)/rate)
    return longest


def sandbox_denials(value,limit=10000):
    """Count result rows that report EPERM/EACCES (a sandbox or permission
    denial inside an otherwise successful reply). Values are not inspected."""
    count=0;stack=[value];seen=0
    while stack and seen<limit:
        item=stack.pop();seen+=1
        if isinstance(item,dict):
            if item.get('errno') in SANDBOX_ERRNOS and type(item.get('errno')) is int:count+=1
            stack.extend(v for v in item.values() if isinstance(v,(dict,list)))
        elif isinstance(item,list):stack.extend(v for v in item if isinstance(v,(dict,list)))
    return count


def cacheable(name,action,apply):
    return action in (READ,READ_IDENTIFIERS) and not apply and name not in CACHE_EXEMPT and name not in MUTATION_EXPORTS and name not in SLOW_CALLS


class MutationTokens:
    """Single-use apply tokens bound to the caller's unique bus name, uid, the
    polkit action, the export, its canonical arguments and the plan digest
    (recomputed from a fresh plan/readback at apply time). 60 s lifetime."""

    def __init__(self,clock=time.monotonic,seconds=TOKEN_SECONDS,max_tokens=64,token=lambda:secrets.token_hex(16)):
        self.clock=clock;self.seconds=seconds;self.max_tokens=max_tokens;self.token=token;self.tokens={}

    def _expire(self):
        now=self.clock()
        self.tokens={k:v for k,v in self.tokens.items() if v['expires']>now}

    def issue(self,sender,uid,action,name,args,digest):
        if not isinstance(digest,str) or not DIGEST_RE.fullmatch(digest):raise ServiceError(errno.EPROTO,'The plan carries no valid digest.')
        self._expire()
        # One outstanding token per caller connection and export.
        self.tokens={k:v for k,v in self.tokens.items() if not (v['sender']==sender and v['name']==name)}
        if len(self.tokens)>=self.max_tokens:raise ServiceError(errno.EBUSY,'Too many outstanding mutation plans.')
        value=self.token()
        self.tokens[value]={'sender':sender,'uid':uid,'action':action,'name':name,
                            'args':json.dumps(args,sort_keys=True,separators=(',',':')),'digest':digest,'expires':self.clock()+self.seconds}
        return value

    def consume(self,value,sender,uid):
        if not isinstance(value,str) or not LEASE_RE.fullmatch(value):raise ServiceError(errno.EINVAL,'Invalid mutation token.')
        self._expire()
        entry=self.tokens.get(value)
        if entry is None:raise ServiceError(errno.ENOENT,'Unknown, expired or already used mutation token.')
        if entry['sender']!=sender or entry['uid']!=uid:raise ServiceError(errno.EACCES,'The mutation token belongs to another caller.')
        del self.tokens[value]
        return {**entry,'args':json.loads(entry['args'])}


class AuditLog:
    """Structured audit lines on stdout (the journal). Never carries argument
    values, results or provider messages, which may contain identifiers."""
    FIELDS=('event','uid','sender','action','name','command','apply','arg_keys','result','errno','lease','seconds','reason','token','count')

    def __init__(self,stream=None):
        self.stream=stream;self.lock=threading.Lock()

    def write(self,**fields):
        record={k:fields[k] for k in self.FIELDS if k in fields and fields[k] is not None}
        line='AUDIT '+json.dumps(record,sort_keys=True,separators=(',',':'))
        stream=self.stream
        if stream is None:
            import sys
            stream=sys.stdout
        with self.lock:
            stream.write(line+'\n');stream.flush()
        return record


def arg_keys(args):
    return sorted(str(k)[:64] for k in args)[:16] if isinstance(args,dict) else None


class SysfsFan:
    """Fan attributes of the zenbook_ec hwmon device located by a callable."""

    def __init__(self,locate):self.locate=locate

    def _read(self,name):return int((Path(self.locate())/name).read_text().strip())
    def mode(self):return self._read('pwm1_enable')
    def rpm(self):return self._read('fan1_input')
    def write_mode(self,mode):(Path(self.locate())/'pwm1_enable').write_text(str(mode)+'\n')
    def write_duty(self,duty):(Path(self.locate())/'pwm1').write_text(str(duty)+'\n')


def restore_auto(fan,attempts=3):
    """Firmware automatic (pwm1_enable=2) with independent readback."""
    last=None
    for _ in range(attempts):
        try:
            fan.write_mode(2)
            if fan.mode()==2:return True
        except (OSError,ValueError,RuntimeError) as error:last=error
    if last:raise ServiceError(getattr(last,'errno',None) or errno.EIO,'Automatic fan restoration failed.')
    raise ServiceError(errno.EIO,'Automatic fan restoration did not read back.')


def minimum_rpm(baseline):
    """Same threshold as the kernel watchdog (healthytable_core.h ht_minimum_rpm)."""
    return baseline//2 if baseline//2>LOW_RPM_FLOOR else LOW_RPM_FLOOR


def parse_fan_request(value):
    """CLI-compatible fan request: 'full' or integer percent 0..100."""
    if value=='full':return 0,None
    if not isinstance(value,str) or not value.isascii() or not value.isdecimal() or len(value)>3 or not 0<=int(value)<=100:
        raise ServiceError(errno.EINVAL,'Fan request must be full or 0..100 percent.')
    percent=int(value);return 1,(percent*255+50)//100


class FanLeases:
    """At most one manual-fan lease. Automatic restoration happens on expiry,
    holder disconnect, low RPM, external mode change, release and stop.

    The kernel driver has its own independent low-RPM watchdog; this is the
    second, userspace layer. A marker file records an active lease so that a
    crashed daemon is followed by restoration (ExecStopPost and next start).
    """

    def __init__(self,fan,audit,clock=time.monotonic,marker=None,token=lambda:secrets.token_hex(16),on_end=None):
        self.fan=fan;self.audit=audit;self.clock=clock;self.marker=Path(marker) if marker else None;self.token=token
        self.on_end=on_end;self.lease=None;self.restore_pending=False;self.lock=threading.RLock()

    def needs_ticks(self):
        with self.lock:return bool(self.lease or self.restore_pending)

    def active(self):
        with self.lock:return dict(self.lease) if self.lease else None

    def held_by(self,owner):
        with self.lock:return bool(self.lease and self.lease['owner']==owner)

    def _write_marker(self):
        if not self.marker:return
        tmp=self.marker.with_name('.'+self.marker.name+'.tmp')
        fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
        try:os.write(fd,json.dumps({'lease':self.lease['id'],'uid':self.lease['uid']}).encode())
        finally:os.close(fd)
        os.replace(tmp,self.marker)

    def _clear_marker(self):
        if self.marker:
            try:self.marker.unlink()
            except FileNotFoundError:pass

    def acquire(self,owner,uid,seconds,request):
        if type(seconds) is not int or not LEASE_MIN_SECONDS<=seconds<=LEASE_MAX_SECONDS:
            raise ServiceError(errno.EINVAL,'Lease duration must be 1..300 seconds.')
        mode,duty=parse_fan_request(request)
        with self.lock:
            if self.lease:raise ServiceError(errno.EBUSY,'Another fan lease is active.')
            if self.restore_pending:raise ServiceError(errno.EBUSY,'Automatic fan restoration is still pending.')
            if self.fan.mode()!=2:raise ServiceError(errno.EBUSY,'The fan is not under firmware automatic control.')
            baseline=self.fan.rpm()
            self.lease={'id':self.token(),'owner':owner,'uid':uid,'expires':self.clock()+seconds,
                        'minimum_rpm':minimum_rpm(baseline),'mode':mode,'duty':duty}
            try:
                self._write_marker()
                if duty is not None:self.fan.write_duty(duty)
                self.fan.write_mode(mode)
                if self.fan.mode()!=mode:raise ServiceError(errno.EIO,'Manual fan mode did not read back.')
            except BaseException:
                self._end('acquire_failed');raise
            self.audit.write(event='fan_lease_acquired',uid=uid,sender=owner,action=FAN_LEASE,lease=self.lease['id'],seconds=seconds,result='ok')
            return self.lease['id']

    def _end(self,reason,restore=True):
        lease=self.lease;restored=None;code=None
        try:
            if restore:restored=restore_auto(self.fan)
        except ServiceError as error:
            restored=False;code=error.errno
        finally:
            self.lease=None
            # Keep the marker and retry every tick until automatic mode reads back.
            self.restore_pending=restored is False
            if restored is not False:self._clear_marker()
        if lease:
            self.audit.write(event='fan_lease_ended',uid=lease['uid'],sender=lease['owner'],action=FAN_LEASE,lease=lease['id'],
                             reason=reason,result='ok' if restored is not False else 'error',errno=code)
            if self.on_end:self.on_end(lease['id'],reason)
        return {'lease':lease['id'] if lease else None,'reason':reason,'automatic_restored':restored,'mode':self._mode()}

    def _mode(self):
        try:return self.fan.mode()
        except (OSError,ValueError):return None

    def release(self,lease_id,owner,privileged=False):
        if not isinstance(lease_id,str) or not LEASE_RE.fullmatch(lease_id):raise ServiceError(errno.EINVAL,'Invalid lease id.')
        with self.lock:
            if not self.lease or self.lease['id']!=lease_id:raise ServiceError(errno.ENOENT,'No such active fan lease.')
            if self.lease['owner']!=owner and not privileged:raise ServiceError(errno.EPERM,'Only the lease holder may release it.')
            return self._end('released')

    def set_auto(self,reason='set_auto'):
        with self.lock:
            if self.lease:return self._end(reason)
            restored=restore_auto(self.fan);self.restore_pending=False;self._clear_marker()
            return {'lease':None,'reason':reason,'automatic_restored':restored,'mode':self._mode()}

    def owner_vanished(self,owner):
        with self.lock:
            if self.lease and self.lease['owner']==owner:return self._end('holder_disconnected')
        return None

    def tick(self):
        """Called about once per second while a lease is active."""
        with self.lock:
            if self.restore_pending and not self.lease:
                try:restore_auto(self.fan)
                except ServiceError:return None
                self.restore_pending=False;self._clear_marker()
                self.audit.write(event='fan_restore_retry',action=FAN_LEASE,result='ok')
                return None
            if not self.lease:return None
            if self.clock()>=self.lease['expires']:return self._end('expired')
            try:mode=self.fan.mode();rpm=self.fan.rpm()
            except (OSError,ValueError,RuntimeError):return self._end('fan_read_failed')
            if mode==2:return self._end('restored_externally',restore=False)
            if rpm<self.lease['minimum_rpm']:return self._end('low_rpm_abort')
            return None

    def stop(self):
        with self.lock:
            if self.lease:return self._end('service_stopping')
        return None

    def recover(self):
        """Restore automatic mode if a previous instance left a lease marker."""
        if self.marker and self.marker.exists():
            with self.lock:
                restored=restore_auto(self.fan);self._clear_marker()
                self.audit.write(event='fan_lease_recovered',action=FAN_LEASE,reason='stale_marker',result='ok' if restored else 'error')
                return True
        return False

