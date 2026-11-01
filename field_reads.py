# SPDX-License-Identifier: GPL-2.0-only
"""Source-reviewed native field reads, with independent provider dependencies.

Windows calling conventions/string formatting are outside the native JSON API.
Fixed firmware-cache payloads remain opaque; no factory writes or guessed units.
"""
from pathlib import Path
import datetime
import errno
import json
import os
import re
import qualified_ec
import native_oem
import battery_diagnostics
from platform_metadata import text
from battery_summary import unsigned

FIELDS={
    "BatteryHealthyTable_BatteryError": "battery.error",
    "BatteryHealthyTable_BatteryInformation": "battery",
    "BatteryHealthyTable_CellVoltage1": "ec.battery_cell1_mV",
    "BatteryHealthyTable_CellVoltage2": "ec.battery_cell2_mV",
    "BatteryHealthyTable_CellVoltage3": "ec.battery_cell3_mV",
    "BatteryHealthyTable_CellVoltage4": "ec.battery_cell4_mV",
    "BatteryHealthyTable_ChargingCurrent": "ec.battery_charge_current_mA",
    "BatteryHealthyTable_ChargingVoltage": "ec.battery_charge_voltage_mV",
    "BatteryHealthyTable_Current": "ec.battery_current_mA",
    "BatteryHealthyTable_CycleCount": "ec.battery_cycles",
    "BatteryHealthyTable_DesignVoltage": "ec.battery_design_voltage_mV",
    "BatteryHealthyTable_ECChipName": "ec_info.chip_name",
    "BatteryHealthyTable_FullChargeCapacity": "ec.battery_full_mAh",
    "BatteryHealthyTable_FullCharged": "battery.full",
    "BatteryHealthyTable_LidStatus": "ec.lid_status_flags",
    "BatteryHealthyTable_ManufactureDate": "ec.battery_manufacture_date_raw",
    "BatteryHealthyTable_PFStatus": "gauge.permanent_failure_raw",
    "BatteryHealthyTable_PackageVoltage": "ec.battery_voltage_mV",
    "BatteryHealthyTable_ReadVendorType": "ec.vendor",
    "BatteryHealthyTable_ReadVersion": "ec.protocol",
    "BatteryHealthyTable_RemainingCapacity": "ec.battery_remaining_mAh",
    "BatteryHealthyTable_Rsoc": "ec.battery_percent",
    "BatteryHealthyTable_SafetyStatus": "gauge.safety_status_raw",
    "BatteryHealthyTable_SerialNumber": "ec.battery_serial_raw",
    "BatteryHealthyTable_Temperature": "ec.battery_temperature_dK",
    "BatteryHealthyTable_TimeoutStatus": "ec.battery_timeout_flags",
    "BatteryHealthy_Check_PFalarm": "history.legacy_pf_gate",
    "BatteryHealthy_Read_PFStatus": "history.permanent_failure_raw",
    "Battery_Get_LidStatus": "ec.lid_status_flags",
    "Battery_Read_CapacityPercentage": "battery.percent",
    "Battery_Read_ChargingVoltage": "ec.battery_charge_voltage_mV",
    "Battery_Read_Current": "ec.battery_current_mA",
    "Battery_Read_CycleCount": "ec.battery_cycles",
    "Battery_Read_DesignVoltage": "ec.battery_design_voltage_mV",
    "Battery_Read_DesignedCapacity": "battery.design_mAh",
    "Battery_Read_FullChargedCapcity": "ec.battery_full_mAh",
    "Battery_Read_ManufactureDate": "ec.battery_manufacture_date_raw",
    "Battery_Read_PackageVoltage": "ec.battery_voltage_mV",
    "Battery_Read_Temperature": "ec.battery_temperature_dK",
    "EC_ReadEcChipId": "ec.chip_id",
    "EC_ReadEcChipName": "ec_info.chip_name",
    "EC_ReadEcFwRev": "ec_info.firmware",
    "EC_ReadProjectInformation": "ec.vendor",
    "HealthyTable_FanCounts": "fan.count",
    "HealthyTable_FanRPM": "fan.rpm",
    "HealthyTable_GetFanTestMode": "fan.manual",
    "HealthyTable_Read_BoardTS0L_Temperature": "ec.board_celsius",
    "HealthyTable_Read_Cpu_Temperature": "ec.cpu_celsius",
    "HealthyTable_Read_Fan": "fan",
    "ProArt_Read_Cpu_Temperature": "ec.cpu_celsius",
    "ProArt_Read_Fan": "fan",
    "Thermal_Read_BoardTS0L_Temperature": "ec.board_celsius",
    "Thermal_Read_CpuDptf_PowerLimit1": "power_limits_watts.package-0/long_term",
    "Thermal_Read_CpuDptf_PowerLimit2": "power_limits_watts.package-0/short_term",
    "Thermal_Read_Cpu_Temperature": "ec.cpu_celsius",
    "Thermal_Read_Fan": "fan",
    "WMICheckBatteryHealthSupport": "battery.charge_limit_supported",
    "WMICheckQuietFanSupport": "profile_choices",
    "WMIGetBatteryHealth": "battery.charge_limit_percent",
    "WMIGetQuietFan": "profile"
}
NAMES=set(FIELDS)
ROOT_READS={'BatteryHealthyTable_BatteryInformation','BatteryHealthy_Read_PFStatus',
            'BatteryHealthyTable_SafetyStatus','BatteryHealthyTable_PFStatus'}
BATTERY=Path('/sys/class/power_supply/BAT0')
PROFILE=Path('/sys/firmware/acpi')
POWERCAP=Path('/sys/class/powercap')


def validate(name,args):
    if name not in NAMES or not isinstance(args,dict):raise ValueError('Unknown native field query.')
    if name=='ProArt_Read_Fan':
        if set(args)-{'index'} or type(args.get('index',0)) is not int or not 0<=args.get('index',0)<=255:
            raise ValueError('Fan index must be an integer0..255.')
    elif args:raise ValueError('This field read takes no arguments.')


def value(raw,key,maximum=65535):
    v=raw.get(key)
    if v is None or type(v) is int and v==-1:raise OSError(errno.ENODATA,'Native field is unavailable: '+key)
    if type(v) is not int or not 0<=v<=maximum:raise OSError(errno.EPROTO,'Invalid native field: '+key)
    return v


def fan(field,index=0):
    # The loaded driver accepts only the qualified one-fan model/BIOS/protocol.
    p=native_oem.device();before=qualified_ec.identity(p)
    def get(name,maximum):
        s=text(p/name)
        if not re.fullmatch(r'[0-9]{1,6}',s) or int(s)>maximum:raise OSError(errno.EPROTO,'Invalid fan '+name+'.')
        return int(s)
    if index!=0:raise OSError(errno.ENODEV,'This qualified machine has only fan index0.')
    if field=='fan.count':r=1
    elif field=='fan.rpm':r=get('fan1_input',65534)
    elif field=='fan.manual':
        mode=get('pwm1_enable',2);r=mode in (0,1)
    else:
        mode=get('pwm1_enable',2)
        r={'count':1,'rpm':get('fan1_input',65534),'mode':mode,'manual':mode in (0,1),
           'manual_pwm_requested':get('pwm1',255),'manual_pwm_minimum':0}
        if mode!=get('pwm1_enable',2):raise OSError(errno.EAGAIN,'Fan mode changed during sampling.')
    if before!=qualified_ec.identity(p):raise OSError(errno.EAGAIN,'Fan provider changed during sampling.')
    return r


def battery_counter(name,root=None):
    root=BATTERY if root is None else root
    def identity():
        st=root.stat()
        if text(root/'type')!='Battery' or text(root/'present')!='1':raise OSError(errno.ENODEV,'Battery is absent.')
        return st.st_dev,st.st_ino
    before=identity()
    keys={'Battery_Read_DesignVoltage':['voltage_now'],
          'Battery_Read_DesignedCapacity':['charge_full_design'],
          'Battery_Read_FullChargedCapcity':['charge_full'],
          'Battery_Read_CapacityPercentage':['charge_now','charge_full']}[name]
    a=[unsigned(root/key) for key in keys]
    if len(keys)==2:
        if a[1]==0:raise OSError(errno.ENODATA,'No positive full charge capacity.')
        # The original truncates then rounds half-up to a decile. Preserve both
        # quantities explicitly; no RSOC substitution or assumed100% ceiling.
        percent=100*a[0]/a[1];bucket=((100*a[0]//a[1]+5)//10)*10
        r={'percent':percent,'legacy_bucket_percent':bucket,'remaining_mAh':a[0]/1000,
           'full_mAh':a[1]/1000,'source':'Linux power_supply charge_now / charge_full',
           'note':'Charge-counter ratio; legacy bucket is truncated percent rounded half-up to tens.'}
        if a!=[unsigned(root/key) for key in keys]:raise OSError(errno.EAGAIN,'Battery charge counters changed during sampling.')
    else:r=a[0]/1000
    if before!=identity():raise OSError(errno.EAGAIN,'Battery identity changed during sampling.')
    return r


def profiles():
    choices=text(PROFILE/'platform_profile_choices').split();profile=text(PROFILE/'platform_profile')
    if not choices or len(choices)!=len(set(choices)) or profile not in choices:
        raise OSError(errno.EPROTO,'Invalid native platform profile/choices.')
    if choices!=text(PROFILE/'platform_profile_choices').split():raise OSError(errno.EAGAIN,'Platform choices changed.')
    return profile,choices


def charge_limit(support=False):
    st=BATTERY.stat()
    if text(BATTERY/'type')!='Battery' or text(BATTERY/'present')!='1':raise OSError(errno.ENODEV,'Battery is absent.')
    try:r=unsigned(BATTERY/'charge_control_end_threshold')
    except FileNotFoundError:
        if not support:raise
        r=None
    end=BATTERY.stat()
    if (st.st_dev,st.st_ino)!=(end.st_dev,end.st_ino):raise OSError(errno.EAGAIN,'Battery identity changed.')
    if r is not None and r>100:raise OSError(errno.EPROTO,'Invalid charge threshold.')
    return r is not None if support else r


def power_limit(short=False,root=None):
    root=POWERCAP if root is None else root;matches=[]
    for zone in root.glob('intel-rapl:*'):
        if text(zone/'name')!='package-0':continue
        st=zone.stat()
        for f in zone.glob('constraint_*_name'):
            if text(f)!=('short_term' if short else 'long_term'):continue
            v=unsigned(f.with_name(f.name.replace('_name','_power_limit_uw')))
            if (st.st_dev,st.st_ino)!=(zone.stat().st_dev,zone.stat().st_ino) or text(f)!=('short_term' if short else 'long_term'):
                raise OSError(errno.EAGAIN,'RAPL constraint identity changed.')
            matches.append(v/1000000)
    if len(matches)!=1:raise OSError(errno.ENODEV,'Expected one package0 RAPL constraint.')
    return matches[0]



def power_limits(root=None):
    """Both package RAPL interfaces (MSR and MMIO). The original scalar APIs keep the
    MSR package0 constraint; hardware enforces the lowest enabled limit across
    interfaces, reported separately. Read-only; no limit is written or estimated."""
    root=POWERCAP if root is None else root;zones=[];errors=[]
    for prefix,interface in (('intel-rapl:','msr'),('intel-rapl-mmio:','mmio')):
        for zone in sorted(root.glob(prefix+'*')):
            if zone.name.count(':')!=1:continue
            try:
                if text(zone/'name')!='package-0':continue
                before=(zone.stat().st_dev,zone.stat().st_ino);row={'interface':interface,'zone':zone.name,'enabled':text(zone/'enabled')=='1'}
                for f in sorted(zone.glob('constraint_*_name')):
                    name=text(f)
                    if name not in ('long_term','short_term','peak_power'):continue
                    row[name+'_watts']=unsigned(f.with_name(f.name.replace('_name','_power_limit_uw')))/1000000
                    try:row[name+'_window_microseconds']=unsigned(f.with_name(f.name.replace('_name','_time_window_us')))
                    except OSError:row[name+'_window_microseconds']=None
                if before!=(zone.stat().st_dev,zone.stat().st_ino):raise OSError(errno.EAGAIN,'RAPL zone identity changed.')
                zones.append(row)
            except OSError as error:errors.append({'zone':zone.name,'errno':error.errno or errno.EIO,'error':str(error)})
    if not zones and errors:raise OSError(errors[0]['errno'],errors[0]['error'])
    if not zones:raise OSError(errno.ENODEV,'No package RAPL zone is present.')
    def lowest(key):
        values=[z[key] for z in zones if z['enabled'] and isinstance(z.get(key),(int,float)) and z[key]>0]
        return min(values) if values and not errors else None
    return {'available':True,'zones':zones,'zone_errors':errors,
            'lowest_enabled_long_term_watts':lowest('long_term_watts'),'lowest_enabled_short_term_watts':lowest('short_term_watts'),
            'original_api_interface':'msr','source':'Linux powercap intel-rapl (MSR) and intel-rapl-mmio package-0 constraints',
            'note':'Configured limits, not consumption. The lowest enabled value across interfaces is the binding configured limit; per-zone values are kept. Firmware/thermald may change MMIO limits at any time.'}


def metadata(attribute):
    p=native_oem.device();before=qualified_ec.identity(p)
    try:r=json.loads(text(p/attribute))
    except ValueError:raise OSError(errno.EPROTO,'Invalid native cache metadata.') from None
    if not isinstance(r,dict):raise OSError(errno.EPROTO,'Invalid native cache object.')
    if before!=qualified_ec.identity(p):raise OSError(errno.EAGAIN,'Native device changed during sampling.')
    return r


def cache_payload(attribute,length,bit):
    if os.geteuid()!=0:raise PermissionError(errno.EACCES,'An explicit privileged cache read is required.')
    r=metadata(attribute)
    raw=r.get('data_hex');s=value(r,'status',255)
    # timeout_flags is range-validated and returned in **r, but does not gate
    # readiness; whether a set flag should mean "not ready" awaits owner review.
    value(r,'timeout_flags',255)
    if type(r.get('schema')) is not int or r.get('schema')!=1 or type(r.get('refresh_requested')) is not bool or r.get('ready_bit')!=bit:
        raise OSError(errno.EPROTO,'Invalid cache contract.')
    if s&0xc0 or not s&bit:raise OSError(errno.ENODATA,'Battery firmware cache is not ready.')
    if not isinstance(raw,str) or not re.fullmatch('[0-9a-f]{'+str(2*length)+'}',raw):raise OSError(errno.EPROTO,'Incomplete battery firmware cache payload.')
    return {**r,'opaque':True,'source':'Fixed original HealthyTable battery cache transaction',
            'note':'Raw firmware cache bytes; no decoded measurements or independently measured cache age.'}


def family(raw):
    vendor=value(raw,'vendor',255)
    if not vendor&128:return 65535
    data=raw.get('firmware_raw')
    if not isinstance(data,list) or len(data)!=2 or any(type(x) is not int or not 0<=x<=255 for x in data):
        raise OSError(errno.EPROTO,'Invalid family selector bytes.')
    code=int.from_bytes(bytes(data),'big')
    if all(x in b'0123456789ABCDEF' for x in data) and bytes(data) not in (b'AB',b'AC',b'CF'):return 32767
    return code


def ec_value(name):
    raw,_=qualified_ec.snapshot();field=FIELDS[name]
    if name=='EC_ReadEcFwRev':return family(raw)
    if name=='EC_ReadEcChipName':
        data=raw.get('chip_name_raw')
        if not isinstance(data,list) or len(data)!=4 or any(type(x) is not int or not 0<=x<=255 for x in data):raise OSError(errno.EPROTO,'Invalid packed chip-name bytes.')
        return int.from_bytes(bytes(data),'big')
    if name=='BatteryHealthyTable_BatteryError':return bool(value(raw,'battery_status_flags',255)&0x80)
    if name=='BatteryHealthyTable_FullCharged':return bool(value(raw,'battery_status_flags',255)&0x10)
    if name=='Battery_Read_ManufactureDate':
        date=value(raw,'battery_manufacture_date_raw')
        try:return datetime.date(1980+(date>>9),(date>>5)&15,date&31).isoformat()
        except ValueError:raise OSError(errno.ENODATA,'Invalid packed battery manufacture date.') from None
    if field=='ec.battery_current_mA':return battery_diagnostics.signed_current(value(raw,'battery_current_mA_raw'))
    if name=='BatteryHealthyTable_ChargingCurrent':return battery_diagnostics.signed_current(value(raw,'battery_charge_current_mA'))
    key=field.removeprefix('ec.')
    maximum=255 if key in ('protocol','vendor','chip_id','battery_status_flags','battery_timeout_flags','lid_status_flags','cpu_celsius','board_celsius') else 65535
    return value(raw,key,maximum)


def call(name,args):
    validate(name,args)
    field=FIELDS[name]
    if field.startswith('fan'):
        return fan('fan.rpm' if name=='ProArt_Read_Fan' else field,args.get('index',0))
    if name in ('Battery_Read_CapacityPercentage','Battery_Read_DesignVoltage','Battery_Read_DesignedCapacity','Battery_Read_FullChargedCapcity'):
        return battery_counter(name)
    if name=='WMICheckBatteryHealthSupport':return charge_limit(True)
    if name=='WMIGetBatteryHealth':return charge_limit()
    if name in ('WMIGetQuietFan','WMICheckQuietFanSupport'):
        profile,choices=profiles()
        if name=='WMIGetQuietFan':return profile
        quiet=[x for x in ('quiet','low-power') if x in choices]
        return {'supported':bool(quiet),'quiet_enabled':profile in quiet,'profile':profile,'choices':choices}
    if name.startswith('Thermal_Read_CpuDptf_PowerLimit'):return power_limit(name.endswith('2'))
    if name=='BatteryHealthyTable_BatteryInformation':return cache_payload('battery_information',32,0x10)
    if name=='BatteryHealthy_Read_PFStatus':
        data=cache_payload('battery_pf_cache',4,0x20)
        return int.from_bytes(bytes.fromhex(data['data_hex']),'little')
    if name=='BatteryHealthy_Check_PFalarm':
        data=metadata('battery_cache_state')
        return battery_diagnostics.legacy_pf_gate(value(data,'status',255))
    if field.startswith('gauge.'):
        if os.geteuid()!=0:raise PermissionError(errno.EACCES,'Explicit privileged gauge read required.')
        return value(metadata('battery_gauge_status'),field.split('.')[1],0xffffffff)
    if name=='BatteryHealthyTable_ECChipName':
        data=metadata('ec_chip_name');raw=data.get('data_hex')
        if type(data.get('schema')) is not int or data.get('schema')!=1 or not isinstance(raw,str) or not re.fullmatch('[0-9a-f]{28}',raw):raise OSError(errno.EPROTO,'Invalid14-byte chip-name buffer.')
        decoded=bytes.fromhex(raw).split(b'\0',1)[0]
        data['text']=decoded.decode('ascii') if all(32<=c<=126 for c in decoded) else None
        return data
    return ec_value(name)
