# SPDX-License-Identifier: GPL-2.0-only
"""Legacy adapter diagnostic availability on the qualified .301 firmware.

Its complete DD dispatcher implements banks1..5/81..85. The original bank6
diagnostic requests reach the silent default; a timeout is not the evidence.
The native kernel excludes these requests and reports a separate support mask.
"""
import errno
import qualified_ec

FIELDS={
    'Adapter_Read_Power_Big_Data_Config':('adapter_config',0,1),
    'Adapter_Read_Charger_Information':('adapter_charger_info',0x28,1),
    'Adapter_Read_PDO_Watt':('adapter_PDO_watts_raw',0x22,4),
    'Adapter_Read_PD_Get_Source_Cap_Extend_VID':('adapter_source_VID',0x29,2),
    'Adapter_Read_PD_Get_Source_Cap_Extend_PID':('adapter_source_PID',0x2b,2),
    'Adapter_Read_PD_Get_Source_Cap_Extend_XID':('adapter_source_XID',0x2d,4),
    'Adapter_Read_PD_Get_Source_Cap_Extend_FWVersion':('adapter_firmware',0x31,1),
    'Adapter_Read_PD_Get_Source_Cap_Extend_HWVersion':('adapter_hardware',0x32,1),
    'Adapter_Read_PD_Get_Status_Temperature':('adapter_temperature_raw',0x33,1),
    'Adapter_Read_PD_Get_Status_EventFlag':('adapter_status_flags',0x34,1),
}
NAMES=set(FIELDS)
SOURCE='Qualified UP3404VA.301 firmware DD dispatcher: banks1..5/81..85 only; bank6 has no handler or response'
REASON='This firmware does not implement the original bank6 adapter diagnostics.'


def validate(name,args):
    if name not in NAMES:raise KeyError(name)
    if not isinstance(args,dict) or args:raise ValueError('This adapter diagnostic query takes no arguments.')


def configuration(raw):
    """Decode qualified module metadata; older modules retain unknown support."""
    maximum=raw.get('max_dd_bank');unsupported=raw.get('unsupported_mask')
    if (type(maximum) is not int or maximum!=5 or type(unsupported) is not int or
        not 0<=unsupported<2**64 or not unsupported&(1<<23)):
        raise OSError(errno.EPROTO,'Native module does not provide the qualified adapter support metadata.')
    failed=raw.get('unavailable_mask');config=raw.get('adapter_config')
    if type(failed) is not int or not 0<=failed<2**64 or type(config) is not int or config!=-1 or failed&(1<<23):
        raise OSError(errno.EPROTO,'Native adapter support and configuration metadata disagree.')
    return {'available':False,'raw_config':None,'read_failure_latched':False,
            'static_firmware_absence_proven':True,'status':'firmware_bank_unimplemented',
            'errno':errno.EOPNOTSUPP,'new_request_sent':False,'source':SOURCE}


def report():
    result={'schema':1,'provider_available':False,'diagnostics':[],'source':SOURCE,
            'note':'These original charger diagnostics are separate from measured input ADC, negotiated source PDOs and battery sensors.'}
    try:
        raw,legacy=qualified_ec.snapshot()
        config=configuration(raw)
        result.update(provider_available=True,configuration=config,implemented_dd_banks=[1,2,3,4,5])
        for name,(field,selector,width) in FIELDS.items():
            result['diagnostics'].append({'api':name,'available':False,'value':None,'errno':errno.EOPNOTSUPP,
                'status':'firmware_bank_unimplemented','reason':REASON,'original_bank':6,
                'original_selector':selector,'original_width_bytes':width,'request_sent':False,'source':SOURCE})
    except OSError as error:
        result.update(errno=error.errno or errno.EIO,error=str(error))
        result['diagnostics']=[{'api':name,'available':False,'value':None,'status':'provider_unavailable',
            'errno':error.errno or errno.EIO,'reason':str(error),'request_sent':False,'source':SOURCE} for name in FIELDS]
    return result


def call(name,args):
    validate(name,args);row=next(r for r in report()['diagnostics'] if r['api']==name)
    raise OSError(row['errno'],row['reason'])


def legacy_received_alert():
    """Original DD6/26 is one opaque cache byte, not a four-byte USB-PD ADO."""
    raw,_=qualified_ec.snapshot()
    configuration(raw)  # Require the qualified whole-bank absence evidence.
    raise OSError(errno.EOPNOTSUPP,'This firmware does not implement original bank6/0x26 alert-cache byte; use native_alert=true for the separate received32-bit USB-PD ADO.')
