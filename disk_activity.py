# SPDX-License-Identifier: GPL-2.0-only
"""Native counterpart of the original non-system disk activity predicate.

The original misleadingly named RF_USBIsTranster uses PhysicalDisk disk-time
percent, not USB bus bytes. Linux queue-weighted I/O time is explicit here;
root backing disks are excluded and no synthetic Windows _Total is invented.
"""
from pathlib import Path
import errno
import os
import re
import time
import storage_inventory as inventory

ROOT=Path('/sys/class/block')


def identity(path):
    info=path.stat();device=inventory.text(path/'dev')
    if not re.fullmatch(r'[0-9]{1,10}:[0-9]{1,10}',device):raise OSError(errno.EPROTO,'Invalid block identity.')
    return info.st_dev,info.st_ino,str(path.resolve(strict=True)),device


def system_disks(root,root_dev=None):
    if root_dev is None:
        value=os.stat('/').st_dev;root_dev=(os.major(value),os.minor(value))
    wanted='%d:%d'%root_dev
    paths=list(root.iterdir())
    if len(paths)>8192:raise OSError(errno.EOVERFLOW,'Block topology exceeds its bound.')
    matches=[p for p in paths if inventory.text(p/'dev')==wanted]
    if len(matches)!=1:raise OSError(errno.ENODATA,'Root filesystem has no unique visible block provider.')
    active=set();cache={};guards=[]
    def walk(path,depth=0):
        before=identity(path)
        key=before[-1]
        if depth>16 or key in active:raise OSError(errno.ELOOP,'Root block topology is cyclic or too deep.')
        if key in cache:return cache[key]
        active.add(key);guards.append((path,before))
        if (path/'partition').exists():values=walk(root/path.resolve(strict=True).parent.name,depth+1)
        else:
            slaves=sorted((path/'slaves').iterdir()) if (path/'slaves').is_dir() else []
            if slaves:
                values=set()
                for child in slaves:values.update(walk(root/child.name,depth+1))
                if [p.name for p in slaves]!=[p.name for p in sorted((path/'slaves').iterdir())]:raise OSError(errno.EAGAIN,'Root backing-device links changed.')
            else:
                if not (path/'device').exists():raise OSError(errno.ENODATA,'Root block backing device is unavailable.')
                values={key}
        active.remove(key);cache[key]=values
        return values
    result=walk(matches[0])
    for path,before in guards:
        if identity(path)!=before:raise OSError(errno.EAGAIN,'Root block topology changed.')
    return result


def counters(path):
    raw=inventory.text(path/'stat');fields=raw.split()
    if not 11<=len(fields)<=32 or any(not re.fullmatch(r'[0-9]{1,20}',x) or int(x)>2**64-1 for x in fields):
        raise OSError(errno.EPROTO,'Invalid kernel disk I/O counters.')
    return {'busy_ms':int(fields[9]),'weighted_ms':int(fields[10])}


def snapshot(root,root_dev,clock,boot_clock):
    start=clock();boot_start=boot_clock();system=system_disks(root,root_dev);paths=inventory.paths(root);rows={}
    for path in paths:
        before=None
        try:
            before=identity(path);meta=inventory.sample(path)
            if meta['subsystem'] is None or meta['subsystem']=='scsi' and meta['scsi_type'] is None or meta['subsystem']=='mmc' and meta['card_type'] is None:
                raise OSError(errno.ENODATA,'Physical block-device classification is unavailable.')
            if meta['subsystem']=='scsi' and meta['scsi_type'] not in (0,14,20) or meta['card_type']=='SDIO':continue
            value=counters(path)
            if identity(path)!=before:raise OSError(errno.EAGAIN,'Disk identity changed during counter sampling.')
            rows[path.name]={'identity':before,'dev':before[-1],**value,'system_disk':before[-1] in system}
        except OSError as error:rows[path.name]={'errno':error.errno or errno.EIO,'error':str(error),'system_disk':None if before is None else before[-1] in system}
    if paths!=inventory.paths(root) or system!=system_disks(root,root_dev):raise OSError(errno.EAGAIN,'Disk inventory or root topology changed.')
    boot_end=boot_clock();end=clock()
    return {'time_ns':(start+end)//2,'boot_ns':(boot_start+boot_end)//2,'read_ns':end-start,'system':sorted(system),'rows':rows}


def report(root=None,root_dev=None,clock=None,boot_clock=None,sleep=None):
    root=ROOT if root is None else root;clock=clock or time.monotonic_ns
    boot_clock=boot_clock or (lambda:time.clock_gettime_ns(time.CLOCK_BOOTTIME));sleep=sleep or time.sleep
    a=snapshot(root,root_dev,clock,boot_clock);sleep(.25);b=snapshot(root,root_dev,clock,boot_clock)
    elapsed=b['time_ns']-a['time_ns'];boot_elapsed=b['boot_ns']-a['boot_ns']
    if not 100_000_000<=elapsed<=5_000_000_000 or abs(boot_elapsed-elapsed)>50_000_000 or any(not 0<=s['read_ns']<=100_000_000 for s in (a,b)):
        raise OSError(errno.ESTALE,'Invalid disk sampling interval, delayed snapshot or suspend gap.')
    if a['system']!=b['system']:raise OSError(errno.EAGAIN,'Root backing disks changed during sampling.')
    rows=[]
    for name in sorted(set(a['rows'])|set(b['rows'])):
        before=a['rows'].get(name);after=b['rows'].get(name);row={'device':name,'available':False}
        if before is None or after is None:row.update(errno=errno.EAGAIN,error='Disk was not present in both snapshots.')
        elif 'errno' in before or 'errno' in after:
            error=before if 'errno' in before else after;row.update(errno=error['errno'],error=error['error'],system_disk=error.get('system_disk'))
        elif before['identity']!=after['identity'] or before['system_disk']!=after['system_disk']:
            row.update(errno=errno.EAGAIN,error='Disk identity changed between snapshots.')
        elif any(after[k]<before[k] for k in ('busy_ms','weighted_ms')):
            row.update(errno=errno.ENODATA,error='Disk counters reset or wrapped.')
        else:
            weighted=after['weighted_ms']-before['weighted_ms'];busy=after['busy_ms']-before['busy_ms']
            percent=weighted*100_000_000//elapsed
            row.update(available=True,system_disk=after['system_disk'],eligible=not after['system_disk'],
                       activity_percent_integer=percent,busy_percent=busy*100_000_000/elapsed,
                       over_threshold=percent>20 and not after['system_disk'],
                       counter_before={k:before[k] for k in ('busy_ms','weighted_ms')},
                       counter_after={k:after[k] for k in ('busy_ms','weighted_ms')})
        rows.append(row)
    positive=sum(r.get('over_threshold',False) for r in rows);complete=all(r['available'] or r.get('system_disk') is True for r in rows)
    return {'schema':1,'available':complete,'active':True if positive else False if complete else None,
            'disks_over_threshold':positive,'threshold_percent':20,'sample_seconds':elapsed/1_000_000_000,
            'system_devices_excluded':a['system'],'disks':rows,'source':'Linux queue-weighted disk I/O milliseconds / measured elapsed time',
            'scope':'Physical non-root disks; integer percent strictly greater than20. Synthetic Windows _Total omitted.',
            'note':'Queue-weighted time can exceed100%; busy time is separate. This predicate does not measure USB bus traffic or filesystem capacity. Cross-OS counter calibration and non-block/multi-device root filesystems are unqualified.'}
