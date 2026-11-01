# SPDX-License-Identifier: GPL-2.0-only
"""Validated CPUFreq readings and loaded-driver metadata, without zero defaults."""
from pathlib import Path
import errno
import json
import os
import re
import native_oem

CPUFREQ=Path('/sys/devices/system/cpu/cpufreq')
MODULE=Path('/sys/module/zenbook_healthytable')
NAMES={'CPU_ReadCpuFrequency':'current','CPU_ReadCpuMaxFrequency':'maximum'}
FIELDS={'scaling_cur_freq':'current_mhz','cpuinfo_max_freq':'maximum_mhz'}


def identity(path):
    stat=path.stat()
    return stat.st_dev,stat.st_ino


def unsigned(raw):
    if not re.fullmatch(r'[0-9]{1,10}',raw) or int(raw)>0xffffffff:
        raise OSError(errno.EPROTO,'Invalid kernel unsigned integer.')
    return int(raw)


def driver_value(name):
    if name not in ('version','refcnt'):raise ValueError('Only fixed driver version/refcount reads are supported.')
    before=identity(MODULE);raw=(MODULE/name).read_text().strip()
    if name=='version':
        if not re.fullmatch(r'[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}',raw):
            raise OSError(errno.EPROTO,'Invalid loaded-driver version.')
        value=raw
    else:value=unsigned(raw)
    if before!=identity(MODULE):raise OSError(errno.EAGAIN,'Loaded driver changed during sampling.')
    return value


def policies(root):return sorted((p for p in root.iterdir() if re.fullmatch(r'policy[0-9]+',p.name)),key=lambda p:p.name)


def frequencies(root=None):
    root=CPUFREQ if root is None else root
    output={'available':False,'policies':[],'maximum_observed_policy_mhz':None,'maximum_possible_policy_mhz':None,
            'source':'Linux CPUFreq scaling_cur_freq / cpuinfo_max_freq',
            'note':'Maximum across sequential policy reads, not a simultaneous all-core clock. scaling_cur_freq is driver-reported and may reflect a requested P-state rather than exact instantaneous hardware frequency. cpuinfo_max_freq is a possible frequency, not the current policy limit.'}
    try:
        paths=policies(root)
        if not paths:raise OSError(errno.ENODEV,'No CPUFreq policies are available.')
        for path in paths:
            row={'policy':path.name,'current_mhz':None,'maximum_mhz':None,'errors':{}}
            try:
                before=identity(path)
                for name,key in FIELDS.items():
                    try:
                        value=unsigned((path/name).read_text().strip())
                        if not value:raise OSError(errno.ENODATA,'CPUFreq value is zero/unavailable.')
                        row[key]=value/1000
                    except OSError as error:row['errors'][key]={'errno':error.errno or errno.EIO,'error':str(error)}
                if before!=identity(path):raise OSError(errno.EAGAIN,'CPUFreq policy changed during sampling.')
            except OSError as error:
                for key in FIELDS.values():
                    row[key]=None;row['errors'][key]={'errno':error.errno or errno.EIO,'error':str(error)}
            output['policies'].append(row)
        if [p.name for p in paths]!=[p.name for p in policies(root)]:
            raise OSError(errno.EAGAIN,'CPUFreq policy inventory changed during sampling.')
        for key,aggregate in [('current_mhz','maximum_observed_policy_mhz'),('maximum_mhz','maximum_possible_policy_mhz')]:
            if all(row[key] is not None for row in output['policies']):
                output[aggregate]=max(row[key] for row in output['policies'])
        output['available']=all(output[k] is not None for k in ('maximum_observed_policy_mhz','maximum_possible_policy_mhz'))
    except OSError as error:output.update(errno=error.errno or errno.EIO,error=str(error))
    return output


def _pairs(items):
    result={}
    for key,value in items:
        if key in result:raise ValueError('Duplicate frequency field.')
        result[key]=value
    return result


def reported_snapshot():
    fd=os.open(native_oem.device()/'cpu_reported_frequency',os.O_RDONLY|os.O_CLOEXEC)
    try:raw=os.read(fd,4097)
    finally:os.close(fd)
    try:
        if len(raw)>4096:raise ValueError('Oversize frequency report.')
        result=json.loads(raw,object_pairs_hook=_pairs)
        if set(result)!={'schema','cpu','reference_mhz','current','maximum'}:raise ValueError('Unknown frequency schema.')
        if type(result['schema']) is not int or result['schema']!=1 or type(result['cpu']) is not int or result['cpu']!=0:
            raise ValueError('Unknown frequency CPU or version.')
        reference=result['reference_mhz']
        if type(reference) is not int or not 1<=reference<=1000:raise ValueError('Invalid reference clock.')
        for key in ('current','maximum'):
            row=result[key]
            if not isinstance(row,dict) or set(row)!={'errno','ratio','mhz','raw_msr_hex'}:raise ValueError('Invalid frequency result.')
            if any(type(row[n]) is not int for n in ('errno','ratio','mhz')) or not 0<=row['errno']<=4095:
                raise ValueError('Invalid frequency value types.')
            if not isinstance(row['raw_msr_hex'],str) or not re.fullmatch(r'0x[0-9a-f]{16}',row['raw_msr_hex']):
                raise ValueError('Invalid frequency register.')
            register=int(row['raw_msr_hex'],16)
            expected=(register>>8)&127 if key=='current' else register&255
            if row['errno']:
                if row['ratio'] or row['mhz']:raise ValueError('Unavailable frequency contains a value.')
                row['ratio']=row['mhz']=None
            elif not expected or (key=='maximum' and expected==255) or row['ratio']!=expected or row['mhz']!=expected*reference:
                raise ValueError('Frequency does not match its reported ratio and reference clock.')
        return {**result,'available':not any(result[k]['errno'] for k in ('current','maximum')),
                'source':'CPU0 MSR198[14:8] / MSR1ad[7:0] times CPUID.16H ECX[15:0]',
                'note':'CPU-reported P-state and single-active-core turbo ratio, not measured effective clocks or a simultaneous all-core maximum. Fixed CPU0 sampling, no mailbox or MSR writes.'}
    except (ValueError,TypeError,KeyError,UnicodeError):
        raise OSError(errno.EPROTO,'Invalid CPU-reported frequency snapshot.') from None


def reported_frequencies():
    try:return reported_snapshot()
    except (OSError,RuntimeError) as error:
        return {'available':False,'errno':getattr(error,'errno',None) or errno.EIO,'error':str(error)}


def call(name,args):
    if args:raise ValueError('This CPU frequency query takes no arguments.')
    row=reported_snapshot()[NAMES[name]]
    if row['errno']:raise OSError(row['errno'],'CPU-reported frequency is unavailable.')
    return row['mhz']
