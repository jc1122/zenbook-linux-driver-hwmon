# SPDX-License-Identifier: GPL-2.0-only
"""Original adapter-rating availability on the qualified x86 HealthyTable EC.

Original x86 getters require protocol>=28 and use bank12 byte pairs. Their
DSTS0x1200f2 alternative is ARM64-only. UP3404VA.301 has protocol15, so no rating
request is valid here. Negotiated PDO limits, EC adapter watts and input ADC
measurements remain separate native providers.
"""
import errno
import qualified_ec
import adapter_diagnostics

RATINGS={'Adapter_Read_Standard_Watt':('Standard adapter rating',[1,0]),
         'Adapter_Read_Sufficient_Watt':('Sufficient adapter rating',[3,2]),
         'Adapter_Read_ChampionPort_Watt':('Champion-port adapter rating',[5,4])}
NAMES=set(RATINGS)
MINIMUM_PROTOCOL=28
SOURCE='Recovered original x86 rating gates; HealthyTable>=28, bank12, two-byte rating'


def validate(name,args):
    if name not in NAMES:raise KeyError(name)
    if not isinstance(args,dict) or args:raise ValueError('This adapter-rating query takes no arguments.')


def diagnostic_config(raw):
    """Existing telemetry/quarantine observation, not a new support probe."""
    if 'max_dd_bank' in raw or 'unsupported_mask' in raw:
        try:return adapter_diagnostics.configuration(raw)
        except OSError as error:
            return {'available':False,'raw_config':None,'read_failure_latched':None,
                    'static_firmware_absence_proven':False,'status':'invalid_telemetry',
                    'errno':error.errno,'new_request_sent':False,'source':adapter_diagnostics.SOURCE}
    value=raw.get('adapter_config');mask=raw.get('unavailable_mask')
    result={'available':False,'raw_config':None,'read_failure_latched':None,
            'source':'Existing ec_telemetry bank6 configuration and unavailable_mask bit23',
            'new_request_sent':False,'static_firmware_absence_proven':False}
    if type(mask) is not int or not 0<=mask<2**64 or type(value) is not int or not -1<=value<=255:
        return {**result,'status':'invalid_telemetry','errno':errno.EPROTO}
    failed=bool(mask&(1<<23));result['read_failure_latched']=failed
    if failed and value!=-1:return {**result,'status':'inconsistent_telemetry','errno':errno.EPROTO}
    if failed or value==-1:return {**result,'status':'no_accepted_configuration','errno':errno.ENODATA}
    return {**result,'available':True,'raw_config':value,'status':'reported_raw_configuration',
            'note':'Configuration bits remain opaque here; this is not an electrical measurement.'}


def report():
    result={'schema':1,'provider_available':False,'ratings':[],'source':SOURCE,
            'note':'Original rating meanings are distinct from negotiated limits, requested power and measured input draw. Windows registry overrides and ARM transport are outside this qualified native x86 provider.'}
    try:
        raw,legacy=qualified_ec.snapshot()
        if type(raw.get('protocol')) is not int or raw['protocol']!=15:
            raise OSError(errno.EOPNOTSUPP,'Adapter rating identity is unqualified; a newer protocol alone does not qualify another firmware.')
        result.update(provider_available=True,current_protocol=15,minimum_rating_protocol=MINIMUM_PROTOCOL,
                      legacy_ASUS1000_present=bool(legacy),legacy_diagnostic_config=diagnostic_config(raw))
        for name,(label,indices) in RATINGS.items():
            result['ratings'].append({'api':name,'label':label,'available':False,'watts':None,
                 'errno':errno.EOPNOTSUPP,'status':'legacy_interface_blocks_original_path' if legacy else 'requires_newer_protocol',
                 'reason':'Legacy ASUS1000 presence blocks the original rating getter.' if legacy else
                          'The original x86 rating getter requires HealthyTable28; this EC provides HealthyTable15.',
                 'original_bank':12,'original_byte_indices_high_to_low':indices,'request_sent':False,'source':SOURCE})
    except OSError as error:
        result.update(errno=error.errno or errno.EIO,error=str(error))
        result['ratings']=[{'api':name,'label':label,'available':False,'watts':None,'status':'provider_unavailable',
                           'errno':error.errno or errno.EIO,'reason':str(error),'request_sent':False,'source':SOURCE}
                          for name,(label,indices) in RATINGS.items()]
    return result


def call(name,args):
    validate(name,args);row=next(r for r in report()['ratings'] if r['api']==name)
    # The qualified protocol15 never enters the original protocol28 reader.
    raise OSError(row['errno'],row['reason'])
