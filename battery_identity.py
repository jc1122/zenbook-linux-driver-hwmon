# SPDX-License-Identifier: GPL-2.0-only
"""Exact battery-reported SBS identity, separate from the ACPI laptop identity."""
import errno
import battery_diagnostics as battery

NAMES={'BatteryHealthyTable_DeviceName':'model',
       'BatteryHealthyTable_ManufactureName':'manufacturer',
       'BatteryHealthyTable_ManufactureNameBySMBus':'manufacturer',
       'Battery_Read_ManufactureName':'manufacturer',
       'BatteryHealthyTable_GaugeIC':'gauge_identifier_raw'}


def decode(data):
    battery.validate(data,300)
    raw={}
    for key in ('manufacturer','model'):
        value=data.get(key+'_hex')
        if not isinstance(value,str) or not 2<=len(value)<=64 or len(value)%2:
            raise ValueError('Invalid battery '+key+' block length.')
        raw[key]=battery.payload(data,key+'_hex',len(value)//2)
    def display(value):
        return value.decode('ascii') if all(32<=v<=126 for v in value) and value.strip() else None
    return {'available':True,'source':'Fixed firmware SBS block READ commands0x20/0x21',
            'manufacturer':display(raw['manufacturer']),'model':display(raw['model']),
            'manufacturer_raw_hex':raw['manufacturer'].hex(),'model_raw_hex':raw['model'].hex(),
            'gauge_identifier_raw':raw['manufacturer'][3] if len(raw['manufacturer'])>=4 else None,
            'gauge_identifier_source':'Fourth byte of battery-reported ManufacturerName; original ASUS raw-byte convention',
            'device_type_hex':'4556','firmware_hex':data['firmware_hex'],
            'physical_gauge_vendor_verified':False,'age_milliseconds':data['age_milliseconds'],
            'maximum_cache_seconds':300,
            'note':'Battery-reported strings are not the ACPI laptop manufacturer/model and may encode opaque manufacturer data. Nonprintable or blank text is unavailable; exact raw bytes remain available. The ASUS gauge byte is not the device-type identifier or a verified physical vendor.'}


def report():return battery.read('battery_identity',decode)


def call(name,args):
    if name not in NAMES:raise KeyError(name)
    if not isinstance(args,dict) or args:raise ValueError('This battery identity read takes no arguments.')
    result=report()
    if not result['available']:raise OSError(result.get('errno') or errno.ENODEV,result.get('error','Battery identity is unavailable.'))
    value=result[NAMES[name]]
    if value is None:raise OSError(errno.ENODATA,'The requested battery identity field is unavailable.')
    return value
