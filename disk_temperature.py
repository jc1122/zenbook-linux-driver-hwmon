# SPDX-License-Identifier: GPL-2.0-only
"""Identity-bracketed cached hwmon / standby-aware SMART disk temperatures.

Kernel diskseq distinguishes a replacement even if its name/dev_t is reused:
https://www.kernel.org/doc/Documentation/ABI/stable/sysfs-block
This module only stats device nodes. Its optional smartctl subprocess opens the
disk and retains autodetection's bridge-specific wake limitations despite -n.
"""
from pathlib import Path
import errno
import json
import math
import os
import re
import stat
import subprocess
import time
import storage_inventory as storage


def valid(value):return type(value) in (int,float) and -80<=value<=150 and math.isfinite(value)


def block_identity(path):
    before=storage.identity(path)
    try:sequence=storage.number(path/'diskseq',2**64-1)
    except FileNotFoundError:raise OSError(errno.EOPNOTSUPP,'Kernel disk-generation metadata is unavailable.') from None
    if storage.identity(path)!=before:raise OSError(errno.EAGAIN,'Disk identity changed while sampling its generation.')
    return before,sequence


def node_identity(path,identity,stat_node):
    info=stat_node(path);major,minor=map(int,identity[0][-1].split(':'))
    if not stat.S_ISBLK(info.st_mode) or (os.major(info.st_rdev),os.minor(info.st_rdev))!=(major,minor):
        raise OSError(errno.ENODEV,'Disk device node does not match the kernel block identity.')
    return info.st_dev,info.st_ino,info.st_rdev


def hwmon_candidates(block,root):
    objects=sorted(root.glob('hwmon*'))
    if len(objects)>256:raise OSError(errno.EOVERFLOW,'Too many hwmon providers.')
    rows=[]
    for path in objects:
        try:
            name=storage.text(path/'name')
            if name not in ('nvme','drivetemp'):continue
            parent=(path/'device').resolve(strict=True)
            if parent!=block and parent not in block.parents:continue
            info=path.stat();pinfo=parent.stat()
            rows.append((path,(info.st_dev,info.st_ino,str(path.resolve(strict=True)),name,str(parent),pinfo.st_dev,pinfo.st_ino)))
        except FileNotFoundError:continue
    return rows


def temperature(path):
    raw=storage.text(path/'temp1_input')
    if not re.fullmatch(r'-?[0-9]{1,7}',raw):raise OSError(errno.EPROTO,'Invalid disk hwmon temperature.')
    value=int(raw)/1000
    if not valid(value):raise OSError(errno.ENODATA,'No valid disk hwmon temperature is available.')
    return value


def hwmon_temperature(block,root):
    before=hwmon_candidates(block,root)
    if not before:return None,None
    if len(before)!=1:raise OSError(errno.EBUSY,'Multiple disk temperature providers match one disk.')
    value=temperature(before[0][0])
    if hwmon_candidates(block,root)!=before:raise OSError(errno.EAGAIN,'Disk hwmon provider changed during sampling.')
    return value,before


def smart_temperature(node,runner,timeout):
    proc=runner(['/usr/sbin/smartctl','-A','-j','-n','standby,3,5',str(node)],capture_output=True,text=True,timeout=timeout)
    if type(proc.returncode) is not int or not 0<=proc.returncode<=255:
        raise OSError(errno.EIO,'Disk SMART reader failed.')
    if proc.returncode in (3,5):
        reason='Device is in standby; no wake requested.' if proc.returncode==3 else 'Power-mode check is unsupported; no further SMART read requested.'
        raise OSError(errno.ENODATA,reason)
    if proc.returncode&7:raise OSError(errno.ENODATA,'Disk SMART temperature query failed.')
    if not isinstance(proc.stdout,str) or len(proc.stdout)>1024*1024:raise OSError(errno.EPROTO,'Invalid disk SMART reply length.')
    try:raw=json.loads(proc.stdout)
    except (ValueError,RecursionError):raise OSError(errno.EPROTO,'Invalid disk SMART JSON.') from None
    if not isinstance(raw,dict):raise OSError(errno.EPROTO,'Invalid disk SMART object.')
    temp=raw.get('temperature');nvme=raw.get('nvme_smart_health_information_log')
    value=temp.get('current') if isinstance(temp,dict) else None
    if value is None and isinstance(nvme,dict):value=nvme.get('temperature')
    if not valid(value):raise OSError(errno.ENODATA,'No valid disk SMART temperature is available.')
    return value


def report(kind='all',block_root=Path('/sys/class/block'),hwmon_root=Path('/sys/class/hwmon'),
           dev_root=Path('/dev'),runner=None,stat_node=os.stat):
    if kind not in ('all','hdd','ssd'):raise ValueError('Unknown physical disk temperature selection.')
    runner=runner or subprocess.run;deadline=time.monotonic()+10
    objects=storage.paths(block_root)
    if len(objects)>64:raise OSError(errno.EOVERFLOW,'Too many physical disks for one temperature sample.')
    initial={}
    for path in objects:
        try:initial[path.name]=block_identity(path)
        except OSError as error:initial[path.name]=error
    rows=storage.report(block_root)
    if [r['device'] for r in rows]!=[p.name for p in objects]:
        raise OSError(errno.EAGAIN,'Disk inventory changed during temperature discovery.')
    output=[];guards=[]
    for row in rows:
        match=storage.matches(row,'physical' if kind=='all' else kind)
        if match is False:continue
        result={'device':str(dev_root/row['device']),'available':False}
        try:
            if match is None:raise OSError(errno.ENODATA,'Disk media selection is unavailable.')
            before=initial[row['device']]
            if isinstance(before,OSError):raise before
            path=block_root/row['device'];node=dev_root/row['device']
            if block_identity(path)!=before:raise OSError(errno.EAGAIN,'Disk changed after its metadata was sampled.')
            node_before=node_identity(node,before,stat_node)
            if time.monotonic()>=deadline:raise OSError(errno.ETIMEDOUT,'Disk temperature read budget expired.')
            block=Path(before[0][3]);value,hwguard=hwmon_temperature(block,hwmon_root)
            source='Linux hwmon'
            if value is None:
                if block_identity(path)!=before or node_identity(node,before,stat_node)!=node_before:
                    raise OSError(errno.EAGAIN,'Disk changed before its SMART read; no query was issued.')
                remaining=deadline-time.monotonic()
                if remaining<=0:raise OSError(errno.ETIMEDOUT,'Disk temperature read budget expired.')
                source='SMART';value=smart_temperature(node,runner,min(8,remaining))
            if time.monotonic()>=deadline:raise OSError(errno.ETIMEDOUT,'Disk temperature read budget expired.')
            if block_identity(path)!=before or node_identity(node,before,stat_node)!=node_before:
                raise OSError(errno.EAGAIN,'Disk identity or device node changed during temperature sampling.')
            result.update(available=True,celsius=value,source=source,identity_verified=True)
            guards.append((path,node,before,node_before,block,hwguard,len(output)))
        except (OSError,subprocess.TimeoutExpired) as error:
            result.update(errno=getattr(error,'errno',None) or errno.ETIMEDOUT,error='Disk temperature read timed out.' if isinstance(error,subprocess.TimeoutExpired) else str(error))
        output.append(result)
    if storage.paths(block_root)!=objects:raise OSError(errno.EAGAIN,'Disk inventory changed during temperature sampling.')
    for path,node,before,node_before,block,hwguard,index in guards:
        try:
            if block_identity(path)!=before or node_identity(node,before,stat_node)!=node_before or (hwguard is not None and hwmon_candidates(block,hwmon_root)!=hwguard):
                raise OSError(errno.EAGAIN,'Disk or hwmon provider changed before the temperature result was published.')
        except OSError as error:
            output[index]={'device':str(node),'available':False,'errno':error.errno or errno.EIO,'error':str(error)}
    if storage.paths(block_root)!=objects:raise OSError(errno.EAGAIN,'Disk inventory changed during final temperature checks.')
    return output
