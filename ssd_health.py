# SPDX-License-Identifier: GPL-2.0-only
"""Read-only NVMe SMART collection and sanitized, freshness-checked public cache."""
from pathlib import Path
import errno
import json
import math
import os
import re
import stat
import subprocess
import time

CACHE=Path('/run/zenbook-hardware-metrics/ssd.json')
COUNTERS={'data_units_read':'data_units_read','data_units_written':'data_units_written',
          'host_reads':'host_read_commands','host_writes':'host_write_commands',
          'controller_busy_time':'controller_busy_minutes','power_cycles':'power_cycles',
          'power_on_hours':'power_on_hours','unsafe_shutdowns':'unsafe_shutdowns',
          'media_errors':'media_errors','num_err_log_entries':'error_log_entries',
          'warning_temp_time':'warning_temperature_minutes','critical_comp_time':'critical_temperature_minutes'}
WARNING_NAMES=('spare_below_threshold','temperature_threshold','reliability_degraded','media_read_only','volatile_memory_backup_failed')


def boottime():return time.clock_gettime(time.CLOCK_BOOTTIME)


def integer(value,maximum):
    return value if type(value) is int and 0<=value<=maximum else None


def decode_smart(data,device,exit_status=0):
    if not re.fullmatch(r'nvme[0-9]+n[0-9]+',device):raise ValueError('Only NVMe namespaces are supported.')
    raw=data.get('nvme_smart_health_information_log')
    if exit_status&7 or not isinstance(raw,dict):
        return {'device':device,'available':False,'error':'NVMe SMART query failed or returned no health log.'}
    warning=integer(raw.get('critical_warning'),255)
    wear=integer(raw.get('percentage_used'),255)
    spare=integer(raw.get('available_spare'),100)
    if warning is None or wear is None or spare is None:raise ValueError('Invalid NVMe health status fields.')
    passed=data.get('smart_status',{}).get('passed')
    row={'device':device,'available':True,'smart_passed':passed if type(passed) is bool else None,
         'critical_warning_mask':warning,'warning_flags':{n:bool(warning&(1<<i)) for i,n in enumerate(WARNING_NAMES)},
         'unknown_warning_bits':warning&~31,'wear_used_percent':wear,'available_spare_percent':spare,
         'available_spare_threshold_percent':integer(raw.get('available_spare_threshold'),100),'counters':{}}
    temperature=raw.get('temperature')
    if type(temperature) is int and -80<=temperature<=150:row['temperature_celsius']=temperature
    for source,key in COUNTERS.items():
        value=integer(raw.get(source),2**128-1)
        if value is not None:row['counters'][key]=str(value)
    # NVMe data units are 1000 * 512 bytes, rounded up by the hardware counter.
    for direction in ['read','written']:
        key='data_units_'+direction
        if key in row['counters']:row['counters']['data_'+direction+'_bytes_rounded']=str(int(row['counters'][key])*512000)
    return row


def collect(root=Path('/sys/class/block'),runner=subprocess.run):
    rows=[]
    for path in sorted(root.glob('nvme*n*')):
        if not re.fullmatch(r'nvme[0-9]+n[0-9]+',path.name) or (path/'partition').exists():continue
        if len(rows)>=16:break
        try:
            result=runner(['/usr/sbin/smartctl','-a','-j','-n','standby,0','/dev/'+path.name],capture_output=True,text=True,timeout=15)
            rows.append(decode_smart(json.loads(result.stdout),path.name,result.returncode))
        except (OSError,ValueError,subprocess.TimeoutExpired):rows.append({'device':path.name,'available':False,'error':'NVMe SMART query unavailable.'})
    return {'schema':1,'source':'NVMe SMART via read-only smartctl query','generated_boottime_seconds':boottime(),
            'devices':rows,'counter_encoding':'decimal strings; NVMe data units represent rounded 512000-byte units',
            'contains_device_identifiers':False}


def read_cached(path=CACHE,now=None,expected_uid=0):
    try:
        fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
        try:
            info=os.fstat(fd)
            if info.st_uid!=expected_uid or info.st_mode&0o022 or not stat.S_ISREG(info.st_mode):raise OSError(errno.EACCES,'Untrusted SSD metrics cache.')
            raw=os.read(fd,65537)
        finally:os.close(fd)
        if len(raw)>65536:raise ValueError('SSD cache exceeds size limit.')
        data=json.loads(raw)
        if not isinstance(data,dict) or data.get('schema')!=1 or not isinstance(data.get('devices'),list) or any(not isinstance(d,dict) for d in data['devices']):raise ValueError('Unknown SSD cache schema.')
        generated=data.get('generated_boottime_seconds')
        if type(generated) not in (int,float) or not math.isfinite(generated):raise ValueError('Invalid SSD cache time.')
        age=(boottime() if now is None else now)-generated
        if not 0<=age<=180:raise OSError(errno.ESTALE,'SSD metrics cache is stale.')
        data['age_seconds']=round(age,3);data['available']=any(d.get('available') for d in data['devices'])
        return data
    except (OSError,ValueError,TypeError,KeyError) as error:
        return {'schema':1,'available':False,'source':'NVMe SMART cache','errno':getattr(error,'errno',None) or errno.EPROTO,
                'error':str(error),'devices':[]}


def export(path=CACHE):
    if os.geteuid()!=0:raise PermissionError('SSD exporter requires privilege.')
    data=collect();path.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
    parent=path.parent.stat()
    if parent.st_uid!=0 or parent.st_mode&0o022:raise PermissionError('Untrusted metrics directory.')
    tmp=path.with_name('.ssd-'+str(os.getpid())+'.json')
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(data,stream,allow_nan=False);stream.write('\n');stream.flush();os.fchmod(stream.fileno(),0o644)
        os.replace(tmp,path)
    finally:
        if tmp.exists():tmp.unlink()
    return data
