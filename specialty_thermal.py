# SPDX-License-Identifier: GPL-2.0-only
"""Qualified native equivalents of the nine original specialty getters.

Original uncached EcFwRev dispatch uses vendor BB/51. Vendor2 lacks the high
bit, selecting familyffff; eight exports return the unsupported zero sentinel.
GPU TS1L instead tries HealthyTable BB/50 then DD/02/03/00 if ASUS1000 is absent.
That channel is already sampled as gpu_celsius and mapped to hwmon EC GPU.
Windows registry cache overrides are outside the native Linux contract.
No CC/CE/E4 probe or inferred physical-location label is used here.
"""
import errno
from qualified_ec import snapshot

ROLES={'Thermal_Read_ACFET_Temperature':'ACFET','Thermal_Read_BatteryConnector_Temperature':'Battery connector',
       'Thermal_Read_BoardTS0R_Temperature':'Board TS0R','Thermal_Read_ChargerChoke_Temperature':'Charger choke',
       'Thermal_Read_GpuTS1L_Temperature':'GPU TS1L','Thermal_Read_GpuTS1R_Temperature':'GPU TS1R',
       'Thermal_Read_GpuVram_Temperature':'GPU VRAM','Thermal_Read_GpuVrm_Temperature':'GPU VRM',
       'Thermal_Read_UpCpu_Temperature':'Upper CPU'}
NAMES=set(ROLES)
GPU='Thermal_Read_GpuTS1L_Temperature'
SOURCE='Recovered original specialty-temperature dispatch; qualified UP3404VA.301 native hardware identity'


def validate(name,args):
    if name not in NAMES:raise KeyError(name)
    if not isinstance(args,dict) or args:raise ValueError('This specialty-temperature query takes no arguments.')


def report():
    result={'schema':1,'sensors':[],'source':SOURCE,'provider_available':False,
            'note':'Native hardware dispatch; Windows registry cache overrides are not imported. Firmware role names do not independently establish physical sensor placement.'}
    try:
        raw,legacy=snapshot()
        result.update(provider_available=True,identity={'protocol':15,'vendor_raw':2,'chip_id_raw':0,'chip_name':'5571',
                    'firmware_ascii':'01','original_uncached_family':'0xffff','legacy_ASUS1000_present':bool(legacy)},
                    any_sensor_available=False)
        for name,role in ROLES.items():
            row={'api':name,'role':role,'available':False,'celsius':None,'source':SOURCE}
            if name!=GPU:
                row.update(errno=errno.EOPNOTSUPP,status='unsupported_original_platform_dispatch',
                           reason='The original getter provides no measurement on this EC platform; its zero sentinel is not a temperature.')
            elif legacy:
                row.update(errno=errno.EOPNOTSUPP,status='unqualified_legacy_interface',
                           reason='The original fallback is gated by legacy ASUS1000 presence; this alternative path is unqualified.')
            else:
                value=raw.get('gpu_celsius')
                row.update(raw_celsius=value if type(value) is int and 0<=value<=255 else None,
                           source='Original HealthyTable_Read_GpuTS1L_Temperature; existing EC GPU channel, bank2 selector3')
                if type(value) is not int or not 0<=value<=255:
                    row.update(errno=errno.EPROTO,status='invalid_channel',reason='No valid byte was returned for the EC GPU channel.')
                elif not 0<value<=125:
                    row.update(errno=errno.ENODATA,status='inactive_or_out_of_range_channel',reason='EC GPU channel has no valid temperature under the native hwmon range policy.')
                else:
                    row.update(available=True,celsius=value,status='measured_channel');result['any_sensor_available']=True
            result['sensors'].append(row)
    except OSError as error:
        result.update(any_sensor_available=False,errno=error.errno or errno.EIO,error=str(error))
        result['sensors']=[{'api':name,'role':role,'available':False,'celsius':None,'status':'provider_unavailable',
                           'errno':error.errno or errno.EIO,'reason':str(error),'source':SOURCE} for name,role in ROLES.items()]
    return result


def call(name,args):
    validate(name,args);row=next(r for r in report()['sensors'] if r['api']==name)
    if not row['available']:raise OSError(row['errno'],row['reason'])
    return [{'label':'EC GPU TS1L','celsius':row['celsius'],'source':row['source']}]
