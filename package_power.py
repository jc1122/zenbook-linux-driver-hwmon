# SPDX-License-Identifier: GPL-2.0-only
"""Read-only CPU-package RAPL energy/time measurement, separate from PSYS/input."""
import errno
import json
import os
import time
import native_oem

FIELDS={'schema','cpu','energy_before','energy_after','energy_exponent',
        'elapsed_microseconds','power_microwatts','maximum_cache_seconds','age_microseconds'}

def pairs(items):
    value={}
    for key,item in items:
        if key in value:raise ValueError('Duplicate package-power field.')
        value[key]=item
    return value

def decode(data):
    if not isinstance(data,dict) or set(data)!=FIELDS or any(type(v) is not int for v in data.values()):
        raise OSError(errno.EPROTO,'Invalid package-power schema or field types.')
    if data['schema']!=1 or data['cpu']!=0 or data['maximum_cache_seconds']!=1:
        raise OSError(errno.EPROTO,'Unknown package-power schema, CPU or cache bound.')
    if not 0<=data['age_microseconds']<1_000_000:raise OSError(errno.ESTALE,'Package-power sample is stale.')
    a,b=data['energy_before'],data['energy_after'];exponent=data['energy_exponent'];elapsed=data['elapsed_microseconds']
    if not 0<=a<=0xffffffff or not 0<=b<=0xffffffff or not 1<=exponent<=31 or not 100_000<=elapsed<=30_000_000:
        raise OSError(errno.EPROTO,'Invalid package energy/time sample.')
    if elapsed>=((1<<(32-exponent))*1000):raise OSError(errno.ESTALE,'Additional package-energy wraps cannot be excluded.')
    delta=(b-a)&0xffffffff
    if not delta:raise OSError(errno.ENODATA,'Stopped package energy counter.')
    expected=((delta*1_000_000_000)>>exponent)*1000//elapsed
    if not 0<expected<=1_000_000_000 or data['power_microwatts']!=expected:
        raise OSError(errno.EPROTO,'Package power does not match its energy/time sample.')
    return {'available':True,'measurement':True,'watts':{'package-0':expected/1_000_000},
            'sample_seconds':elapsed/1_000_000,'energy_sample':data,
            'source':'CPU0 MSR611 package energy / actual elapsed time; MSR606 energy unit',
            'scope':'Package containing logical CPU0; distinct from PSYS platform power and USB-C input draw',
            'note':'Mean power over the reported interval; one32-bit counter wrap handled. No energy reset, MSR/mailbox write or power-limit change.'}

def read():
    fd=os.open(native_oem.device()/'cpu_package_power',os.O_RDONLY|os.O_CLOEXEC)
    try:raw=os.read(fd,4097)
    finally:os.close(fd)
    try:
        if len(raw)>4096:raise ValueError('Oversize package-power report.')
        data=json.loads(raw,object_pairs_hook=pairs)
    except (ValueError,TypeError,UnicodeError):raise OSError(errno.EPROTO,'Invalid package-power JSON.') from None
    return decode(data)

def report():
    for attempt in range(2):
        try:return read()
        except (OSError,RuntimeError) as error:
            code=getattr(error,'errno',None) or errno.EIO
            if attempt==0 and code in (errno.ENODATA,errno.ESTALE,errno.EAGAIN):
                time.sleep(.12);continue
            return {'available':False,'errno':code,'error':str(error),'measurement':True,
                    'source':'CPU0 RAPL package energy counter; no fallback estimate'}

def require_report():
    data=report()
    if not data['available']:raise OSError(data['errno'],data['error'])
    return data
