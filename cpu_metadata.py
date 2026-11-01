# SPDX-License-Identifier: GPL-2.0-only
"""Native read-only CPUID, CPU identity and aggregate busy counters."""
from pathlib import Path
import ctypes
import errno
import math
import platform
import re
import time

NAMES={'CPU_ReadCpuId','CPU_ReadRegCPUInfo','CPU_ReadCPUUsage','WMIGetCPUUsg','WMIGetCPUArchitecture'}
LIBRARY='/usr/local/lib/libasus-healthytable.so'


def uint32(value):
    if type(value) is not int or not 0<=value<=0xffffffff:
        raise ValueError('CPUID leaf/subleaf must be unsigned32-bit integers.')
    return value


def validate(name,args):
    if name not in NAMES:raise ValueError('Unknown CPU metadata query.')
    if not isinstance(args,dict):raise ValueError('CPU arguments must be an object.')
    if name=='CPU_ReadCpuId':
        if set(args)-{'leaf','subleaf'}:raise ValueError('Only CPUID leaf and subleaf are accepted.')
        uint32(args.get('leaf',0));uint32(args.get('subleaf',0))
    elif args:raise ValueError('This CPU metadata query takes no arguments.')


def cpuid(leaf=0,subleaf=0,library=LIBRARY):
    uint32(leaf);uint32(subleaf)
    try:
        lib=ctypes.CDLL(str(library));read=lib.asus_ht_cpuid
    except (OSError,AttributeError) as error:
        raise OSError(errno.EOPNOTSUPP,'Native CPUID read helper is unavailable.') from error
    read.argtypes=[ctypes.c_uint32,ctypes.c_uint32,ctypes.POINTER(ctypes.c_uint32)]
    read.restype=ctypes.c_int;registers=(ctypes.c_uint32*4)()
    result=read(leaf,subleaf,registers)
    if result:raise OSError(-result if result<0 else errno.EPROTO,'CPUID is unavailable on this architecture/thread.')
    return {'leaf':leaf,'subleaf':subleaf,**dict(zip(('eax','ebx','ecx','edx'),map(int,registers))),
            'source':'Native CPUID instruction on the calling thread; raw unsigned registers',
            'note':'Original leaf query uses subleaf0. CPU placement is chosen by the scheduler; topology/cache leaves can differ between logical CPUs. Unsupported leaves retain hardware-defined register results.'}


def model_name(path=Path('/proc/cpuinfo')):
    with path.open('r',encoding='utf-8') as stream:
        try:raw=stream.read(1024*1024+1)
        except UnicodeError:raise OSError(errno.EPROTO,'Invalid CPU information encoding.') from None
    if len(raw)>1024*1024:raise OSError(errno.E2BIG,'CPU information exceeds its bound.')
    for line in raw.split('\n\n',1)[0].splitlines():
        key,separator,value=line.partition(':')
        if separator and key.strip()=='model name':
            value=value.strip()
            if not value or len(value)>4096 or any(ord(c)<32 or ord(c)==127 for c in value):
                raise OSError(errno.ENODATA,'No valid first-processor model name.')
            return value
    raise OSError(errno.ENODATA,'First-processor model name is not supplied.')


def architecture(machine=None):
    raw=platform.machine() if machine is None else machine
    if not isinstance(raw,str) or not raw:raise OSError(errno.ENODATA,'Native processor architecture is unavailable.')
    value=raw.casefold()
    if value in ('x86_64','amd64'):return 9
    if value in ('aarch64','arm64'):return 12
    if re.fullmatch(r'i[3-6]86|x86',value):return 0
    if re.fullmatch(r'armv[4-8][a-z0-9]*|arm',value):return 5
    if value in ('ia64','itanium'):return 6
    if value.startswith(('ppc','powerpc')):return 3
    if value.startswith('mips'):return 1
    if value.startswith('alpha'):return 2
    raise OSError(errno.EOPNOTSUPP,'Native processor architecture has no verified WMI enum mapping.')


def _cpu_times(path):
    with path.open('rb') as stream:raw=stream.readline(4097)
    parts=raw.split()
    if len(raw)>4096 or not parts or parts[0]!=b'cpu' or not 5<=len(parts)<=17:
        raise OSError(errno.EPROTO,'Invalid aggregate CPU counter frame.')
    values=[]
    for value in parts[1:]:
        if not value.isdigit() or len(value)>20 or int(value)>2**64-1:
            raise OSError(errno.EPROTO,'Invalid aggregate CPU tick counter.')
        values.append(int(value))
    # Linux guest/guest_nice are already included in user/nice. Only the
    # first8 counters form the total; unavailable old-kernel fields are zero.
    return (values+[0]*8)[:8]


def usage_fraction(path=Path('/proc/stat'),clock=time.monotonic,wait=time.sleep):
    before=_cpu_times(path);start=clock();wait(.1);after=_cpu_times(path);end=clock()
    if (type(start) not in (int,float) or type(end) not in (int,float) or
        not math.isfinite(start) or not math.isfinite(end) or end-start<.05):
        raise OSError(errno.EAGAIN,'Invalid CPU sampling interval.')
    delta=[b-a for a,b in zip(before,after)]
    if any(v<0 for v in delta):raise OSError(errno.EAGAIN,'Aggregate CPU counters regressed.')
    total=sum(delta)
    if total<=0:raise OSError(errno.ENODATA,'No CPU tick interval is available.')
    inactive=delta[3]+delta[4]  # Native Linux idle plus iowait.
    return (total-inactive)/total


def call(name,args):
    validate(name,args)
    if name=='CPU_ReadCpuId':return cpuid(args.get('leaf',0),args.get('subleaf',0))
    if name=='CPU_ReadRegCPUInfo':return model_name()
    if name=='WMIGetCPUArchitecture':return architecture()
    value=usage_fraction()
    return value if name=='CPU_ReadCPUUsage' else value*100
