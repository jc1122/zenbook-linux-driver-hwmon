# SPDX-License-Identifier: GPL-2.0-only
"""Read DRM percentages or fixed i915 engine PMU counters, without extrapolation."""
from pathlib import Path
import ctypes
import errno
import math
import os
import platform
import re
import struct
import time


def identity(path):
    info=path.stat()
    return info.st_dev,info.st_ino,str(path.resolve(strict=True))


def oserror(error):
    """Malformed sysfs text is a local protocol error, never a lost report."""
    if isinstance(error,OSError):return error
    return OSError(errno.EPROTO,f'Malformed GPU metadata ({type(error).__name__}).')


def unsigned(raw,maximum=0xffffffff):
    if not re.fullmatch(r'[0-9]{1,20}',raw) or int(raw)>maximum:
        raise OSError(errno.EPROTO,'Invalid unsigned GPU metadata.')
    return int(raw)


def failed(row,error):
    for key in ('sample_seconds','time_enabled_seconds','time_running_seconds','busy_nanoseconds','multiplexed'):
        row.pop(key,None)
    row.update(available=False,percent=None,errno=error.errno or errno.EIO,error=str(error))
    return row


def packet(fd):
    raw=os.read(fd,24)
    if len(raw)!=24:raise OSError(errno.EPROTO,'Incomplete GPU PMU counter packet.')
    return struct.unpack('=QQQ',raw)


def counter_result(before,after,elapsed,boot_elapsed):
    if not all(math.isfinite(x) for x in (elapsed,boot_elapsed)) or not .1<=elapsed<=5 or abs(boot_elapsed-elapsed)>.05:
        raise OSError(errno.ENODATA,'Invalid GPU sampling interval or suspend gap.')
    if before[2]>before[1] or after[2]>after[1] or any(b<a for a,b in zip(before,after)):
        raise OSError(errno.ENODATA,'GPU PMU counter reset or wrap during sampling.')
    busy,enabled,running=(b-a for a,b in zip(before,after))
    if not 0<running<=enabled or running!=enabled:
        raise OSError(errno.ENODATA,'GPU event was not running for its full enabled interval; no extrapolation supplied.')
    if abs(enabled/1e9-elapsed)>max(.02,elapsed*.05):
        raise OSError(errno.ENODATA,'GPU PMU enabled time disagrees with measured interval.')
    if busy>running:raise OSError(errno.ENODATA,'GPU busy counter exceeds its valid interval; no clamped percentage supplied.')
    return {'available':True,'percent':100*busy/running,'sample_seconds':elapsed,
            'time_enabled_seconds':enabled/1e9,'time_running_seconds':running/1e9,
            'busy_nanoseconds':busy,'multiplexed':False}


def open_event(kind,config,cpu):
    if platform.machine()!='x86_64':raise OSError(errno.ENODEV,'i915 perf syscall is qualified only on x86_64.')
    attr=ctypes.create_string_buffer(128)
    struct.pack_into('=IIQ',attr,0,kind,128,config)
    struct.pack_into('=Q',attr,32,3)  # TOTAL_TIME_ENABLED | TOTAL_TIME_RUNNING
    libc=ctypes.CDLL(None,use_errno=True)
    fd=libc.syscall(298,ctypes.byref(attr),-1,cpu,-1,8)  # FD_CLOEXEC
    if fd<0:raise OSError(ctypes.get_errno(),'Cannot open i915 engine utilization PMU.')
    return fd


def pmu_usage(pmu,clock=None,boot_clock=None,sleep=None):
    clock=clock or time.monotonic
    boot_clock=boot_clock or (lambda:time.clock_gettime(time.CLOCK_BOOTTIME))
    sleep=sleep or time.sleep
    before_identity=identity(pmu)
    kind=unsigned((pmu/'type').read_text().strip())
    cpus=(pmu/'cpumask').read_text().strip()
    if not re.fullmatch(r'[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*',cpus):
        raise OSError(errno.EPROTO,'Invalid GPU PMU CPU list.')
    cpu=unsigned(cpus.split(',')[0].split('-')[0],2**31-1)
    for segment in cpus.split(','):
        bounds=[unsigned(x,2**31-1) for x in segment.split('-')]
        if bounds[0]>bounds[-1]:raise OSError(errno.EPROTO,'Invalid GPU PMU CPU range.')
    paths=sorted((pmu/'events').glob('*-busy'))
    if not paths:raise OSError(errno.ENODEV,'No i915 engine busy events are advertised.')
    rows=[];opened=[]
    try:
        for event in paths:
            row={'engine':event.name,'pmu':pmu.name,'available':False,'percent':None};rows.append(row)
            fd=None
            try:
                match=re.fullmatch(r'(?:event|config)=(0x[0-9a-fA-F]+|[0-9]+)',event.read_text().strip())
                if not match or (event.with_name(event.name+'.unit')).read_text().strip()!='ns':
                    raise OSError(errno.EPROTO,'GPU PMU event layout or nanosecond unit is unavailable.')
                config=int(match[1],16 if match[1].startswith('0x') else 10)
                if config>0xffffffffffffffff:raise OSError(errno.EPROTO,'GPU PMU config exceeds64bits.')
                scale=event.with_name(event.name+'.scale')
                if scale.exists() and scale.read_text().strip() not in ('1','1.0'):
                    raise OSError(errno.EPROTO,'GPU PMU uses an unsupported counter scale.')
                fd=open_event(kind,config,cpu)
                start=clock();boot_start=boot_clock();snapshot=packet(fd)
                opened.append((row,fd,snapshot,start,boot_start));fd=None
            except (OSError,ValueError) as error:failed(row,oserror(error))
            finally:
                if fd is not None:os.close(fd)
        if opened:sleep(.25)
        for row,fd,before,start,boot_start in opened:
            try:
                after=packet(fd);boot_end=boot_clock();end=clock()
                row.update(counter_result(before,after,end-start,boot_end-boot_start))
            except OSError as error:failed(row,error)
        if before_identity!=identity(pmu) or paths!=sorted((pmu/'events').glob('*-busy')):
            raise OSError(errno.EAGAIN,'GPU PMU identity or event inventory changed during sampling.')
        return rows
    finally:
        for _,fd,*_ in opened:os.close(fd)


def census(root,pattern):
    try:paths=sorted(p for p in root.iterdir() if re.fullmatch(pattern,p.name))
    except FileNotFoundError:return []
    if len(paths)>64:raise OSError(errno.EOVERFLOW,'GPU provider census exceeds its bound.')
    return paths


def report(drm_root=Path('/sys/class/drm'),pmu_root=Path('/sys/bus/event_source/devices')):
    rows=[];errors=[];guards=[];discoveries=[];sources=[]
    def discover(root,pattern,provider):
        try:paths=census(root,pattern);discoveries.append((root,pattern,provider,paths));return paths
        except OSError as error:
            errors.append({'provider':provider,'errno':error.errno or errno.EIO,'error':str(error)});return []
    for path in discover(drm_root,r'card[0-9]+','drm_busy'):
        value=path/'device/gpu_busy_percent'
        row={'device':path.name,'provider':'drm_busy','available':False,'percent':None}
        try:
            # Missing optional counters do not hide PMU providers; other read
            # failures are explicit rows rather than false counter absence.
            try:value.stat()
            except FileNotFoundError:continue
            before=(identity(path),identity(path/'device'),str((path/'device').resolve(strict=True)))
            percent=unsigned(value.read_text().strip(),100)
            if before!=(identity(path),identity(path/'device'),str((path/'device').resolve(strict=True))):
                raise OSError(errno.EAGAIN,'DRM device changed during sampling.')
            row.update(available=True,percent=percent)
            guards.append(('drm_busy',path,before,[len(rows)]))
        except (OSError,ValueError) as error:failed(row,oserror(error))
        rows.append(row);sources.append('DRM driver busy percentage')
    pmus=discover(pmu_root,r'i915(?:_[0-9a-fA-F_.]+)?','i915_pmu')
    for pmu in pmus:
        start=len(rows)
        try:
            before=identity(pmu);samples=pmu_usage(pmu)
            rows.extend({**r,'provider':'i915_pmu'} for r in samples)
            guards.append(('i915_pmu',pmu,before,list(range(start,len(rows)))))
        except (OSError,ValueError) as error:rows.append(failed({'pmu':pmu.name,'provider':'i915_pmu'},oserror(error)))
        sources.append('i915 perf PMU')
    for provider,path,before,indices in guards:
        try:
            after=(identity(path),identity(path/'device'),str((path/'device').resolve(strict=True))) if provider=='drm_busy' else identity(path)
            if after!=before:raise OSError(errno.EAGAIN,'GPU provider identity changed before publication.')
        except OSError as error:
            errors.append({'provider':provider,'device':path.name,'errno':error.errno or errno.EIO,'error':str(error)})
            # Keep the original errno of rows that had already failed.
            for index in indices:
                if rows[index]['available']:failed(rows[index],error)
    for root,pattern,provider,before in discoveries:
        try:
            if census(root,pattern)!=before:raise OSError(errno.EAGAIN,'GPU provider census changed during sampling.')
        except OSError as error:errors.append({'provider':provider,'errno':error.errno or errno.EIO,'error':str(error)})
    if not rows:
        if errors:raise OSError(errors[0]['errno'],errors[0]['error'])
        raise OSError(errno.ENODEV,'No DRM busy counter or supported i915 PMU is present.')
    return {'available':any(r['available'] for r in rows),'engines':rows,'source':' + '.join(dict.fromkeys(sources)),
            # Provider coverage concerns discovery and whole-device reads; a single
            # unavailable engine sample is reported by all_readings_available.
            'provider_coverage_complete':not errors and not any(not r['available'] and (r['provider']=='drm_busy' or 'engine' not in r) for r in rows),
            'all_readings_available':all(r['available'] for r in rows),'provider_errors':errors,
            **({'requested_sample_seconds':.25} if pmus else {}),
            'note':'Sequential advertised-provider observations, not a census of every physical GPU or Windows per-process3D maximum. DRM rows are device busy percentages; i915 rows are per-engine busy nanoseconds over measured running intervals. Providers have separate identities/availability and are not substituted, summed or cross-calibrated. Multiplexed, reset, delayed, suspended, replaced or out-of-range samples remain unavailable; no utilization is extrapolated or clamped.'}
