# SPDX-License-Identifier: GPL-2.0-only
"""Qualified ISL9241 input ADC, separate from PD limits and Intel PSYS."""
import errno
import json
import os
import native_oem


def decode(data):
    if not isinstance(data,dict):raise OSError(errno.EPROTO,'Charger ADC reply is not a JSON object.')
    words=data.get('words')
    if (data.get('schema')!=1 or not isinstance(words,list) or len(words)!=10 or
        any(type(w) is not int or not 0<=w<=65535 for w in words) or
        words[:2]!=[0x49,0x0e]):
        raise OSError(errno.EPROTO,'Invalid charger ADC identity/schema.')
    if (not words[2]&1 or not words[9]&1 or words[3]&0x800 or
        any(not w&0x4000 or not 1<=((w>>5)&7)<=3 for w in [words[4],words[8]])):
        raise OSError(errno.ENODATA,'Charger ADC is disabled or no forward input is present.')
    v0,v1=words[5]>>6,words[7]>>6
    if words[6]>255 or any(words[i]&~0x3fc0 for i in [5,7]) or abs(v1-v0)>1:
        raise OSError(errno.EPROTO,'Invalid or changing charger ADC registers.')
    mv,ua=v1*96,words[6]*44400
    uw=(mv*ua+500)//1000
    expected={'input_millivolts':mv,'input_microamps':ua,'input_microwatts':uw,
              'current_resolution_microamps':44400,'voltage_resolution_millivolts':96,
              'input_shunt_milliohms':10,'maximum_cache_seconds':2}
    if (not 4000<=mv<=24000 or any(type(data.get(k)) is not int or data[k]!=v for k,v in expected.items()) or
        type(data.get('age_milliseconds')) is not int or not 0<=data['age_milliseconds']<=2000):
        raise OSError(errno.EPROTO,'Charger ADC conversion/freshness mismatch.')
    return {'available':True,'voltage_volts':mv/1000,'current_amperes':ua/1_000_000,
            'power_watts':uw/1_000_000,'measurement':True,'power_from_measured_voltage_and_current':True,
            'source':'ISL9241 input ADC via firmware-mediated combined register reads',
            'scope':'shared charger input, sampled; excludes AC adapter conversion losses',
            'current_resolution_amperes':.0444,'voltage_resolution_volts':.096,
            'maximum_cache_seconds':2,'age_milliseconds':data['age_milliseconds'],
            'input_shunt_milliohms':10,'calibration':'model-qualified firmware current scaling; no external meter calibration',
            'raw_words':words}


def report():
    try:
        # os.read preserves sysfs EAGAIN. Buffered text reads on Python 3.14
        # can instead raise an uninformative 'Read returned None' error.
        fd=os.open(native_oem.device()/'charger_adc',os.O_RDONLY|os.O_CLOEXEC)
        try:raw=os.read(fd,4096)
        finally:os.close(fd)
        return decode(json.loads(raw))
    except (OSError,RuntimeError,ValueError,TypeError) as error:
        return {'available':False,'measurement':False,'source':'ISL9241 input ADC',
                'errno':getattr(error,'errno',None) or errno.ENODEV,'error':str(error)}
