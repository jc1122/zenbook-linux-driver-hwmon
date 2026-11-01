# SPDX-License-Identifier: GPL-2.0-only
"""Cached kernel disk metadata for original storage inventory/size queries.

Uses sysfs only; no block-device opens, SMART, filesystem probes or serial reads.
Kernel rotational/removable flags are Linux classifications, not physical media
measurements. Size is in 512-byte sectors regardless of logical sector size:
https://github.com/torvalds/linux/blob/master/Documentation/ABI/stable/sysfs-block
MMC type: https://github.com/torvalds/linux/blob/master/drivers/mmc/core/bus.c
"""
from pathlib import Path
import errno
import re

NAMES={'WMIGetHDDCaption','WMIGetHDDInfo','WMIGetHDDList','WMIGetHDDModel','WMIGetHDDSize','WMIGetSSDList',
       'WMIGetSSDModel','WMIGetPhysicalDiskInfo','WMIGetSDCardCaption','WMIGetSDCardSize'}
SOURCE='Linux cached sysfs block metadata; kernel rotational/removable classification and 512-byte sector capacity'


def validate(name,args):
    if name not in NAMES:raise KeyError(name)
    if name=='WMIGetSDCardSize' and isinstance(args,dict) and not set(args)-{'detailed'} and type(args.get('detailed',False)) is bool:return
    if not isinstance(args,dict) or args:raise ValueError('This storage inventory query takes no arguments.')


def exists(path):
    try:path.lstat();return True
    except FileNotFoundError:return False


def paths(root):
    out=[]
    for path in sorted(root.iterdir()):
        # Ignore virtual disks, normal partitions and MMC hardware subareas.
        if exists(path/'partition') or re.fullmatch(r'mmcblk[0-9]+(?:boot[0-9]+|rpmb)',path.name):continue
        if exists(path/'device'):out.append(path)
    if len(out)>4096:raise OSError(errno.EOVERFLOW,'Block-device census exceeds the supported bound.')
    return out


def text(path):
    try:
        with path.open('r',encoding='utf-8',errors='strict') as stream:value=stream.read(4097)
    except UnicodeDecodeError:raise OSError(errno.EPROTO,'Invalid UTF-8 in kernel storage metadata.') from None
    if len(value)>4096:raise OSError(errno.EOVERFLOW,'Kernel storage metadata exceeds the supported bound.')
    value=value.strip()
    if any(ord(c)<32 or ord(c)==127 for c in value):raise OSError(errno.EPROTO,'Invalid kernel storage metadata control character.')
    return value


def number(path,maximum):
    raw=text(path)
    if not re.fullmatch(r'[0-9]{1,20}',raw) or int(raw)>maximum:raise OSError(errno.EPROTO,'Invalid kernel storage numeric metadata.')
    return int(raw)


def identity(path):
    st=path.stat();dev=text(path/'dev')
    if not re.fullmatch(r'[0-9]{1,10}:[0-9]{1,10}',dev):raise OSError(errno.EPROTO,'Invalid kernel block-device identity.')
    return st.st_dev,st.st_ino,str(path.resolve(strict=True)),str((path/'device').resolve(strict=True)),dev


def sample(path):
    row={'device':path.name,'path':'/dev/'+path.name,'available':True,'field_errors':{},'source':SOURCE}
    errors=row['field_errors']
    def field(key,reader):
        try:row[key]=reader()
        except OSError as error:row[key]=None;errors[key]={'errno':error.errno or errno.EIO,'error':str(error)}
    field('size',lambda:number(path/'size',(2**64-1)//512)*512)
    field('removable',lambda:bool(number(path/'removable',1)))
    field('rotational',lambda:bool(number(path/'queue/rotational',1)))
    def model():
        try:value=text(path/'device/model')
        except FileNotFoundError:value=text(path/'device/name')
        if not value:raise OSError(errno.ENODATA,'Kernel disk model is not supplied.')
        return value
    field('model',model)
    def subsystem():return (path/'device/subsystem').resolve(strict=True).name
    field('subsystem',subsystem)
    row['scsi_type']=None
    if row['subsystem']=='scsi':field('scsi_type',lambda:number(path/'device/type',31))
    row['card_type']=None
    if row['subsystem']=='mmc':
        def card_type():
            value=text(path/'device/type')
            if value not in ('SD','SDcombo','MMC','SDIO'):raise OSError(errno.EPROTO,'Invalid kernel MMC card type.')
            return value
        field('card_type',card_type)
    return row


def unknown(path,error):
    return {'device':path.name,'path':'/dev/'+path.name,'available':False,'size':None,
            'removable':None,'rotational':None,'model':None,'subsystem':None,'card_type':None,'scsi_type':None,
            'field_errors':{},'errno':error.errno or errno.EIO,'error':str(error),'source':SOURCE}


def report(root=Path('/sys/class/block')):
    objects=paths(root);rows=[];guards=[]
    for path in objects:
        try:
            before=identity(path);row=sample(path);guards.append((path,before,row,len(rows)))
        except OSError as error:row=unknown(path,error)
        rows.append(row)
    for path,before,old,index in guards:
        try:
            if identity(path)!=before or sample(path)!=old:raise OSError(errno.EAGAIN,'Kernel disk identity or metadata changed during sampling.')
        except OSError as error:rows[index]=unknown(path,error)
    if objects!=paths(root):raise OSError(errno.EAGAIN,'Kernel physical-disk census changed during sampling.')
    # Multiple names for one dev_t must not silently double-count capacity.
    seen={}
    for path,before,old,index in guards:
        if rows[index]['available']:seen.setdefault(before[-1],[]).append(index)
    for indices in seen.values():
        if len(indices)>1:
            for index in indices:rows[index]=unknown(objects[index],OSError(errno.EPROTO,'Duplicate kernel block-device identity.'))
    return rows


def matches(row,kind):
    if not row['available']:return None
    if row['subsystem'] is None:return None
    if row['subsystem']=='scsi':
        if row['scsi_type'] is None:return None
        if row['scsi_type'] not in (0,14,20):return False
    removable=row['removable'];rotational=row['rotational'];card=row['card_type']
    if card=='SDIO':return False
    if row['subsystem']=='mmc' and card is None and kind in ('sd','hdd','ssd','physical'):return None
    if kind=='fixed':return None if removable is None else not removable
    if kind=='removable':return removable
    if kind=='sd':
        # Exact MMC type is stronger native evidence than a model substring.
        if card in ('SD','SDcombo'):return True
        if card in ('MMC','SDIO') or removable is False:return False
        caption=row['model']
        if caption is not None and any(x in caption.upper() for x in ('SD CARD','SDHC CARD','SDXC CARD')):
            return True if removable is True else None
        if removable is None or caption is None or row['subsystem'] is None or row['subsystem']=='mmc' and card is None:return None
        return False
    if kind=='hdd':return False if card in ('SD','SDcombo','SDIO') else rotational
    if kind=='ssd':
        if removable is True or rotational is True or card in ('SD','SDcombo','SDIO'):return False
        if removable is None or rotational is None:return None
        return True
    if kind=='physical':
        hdd=matches(row,'hdd');ssd=matches(row,'ssd')
        return True if hdd is True or ssd is True else False if hdd is False and ssd is False else None
    raise KeyError(kind)


def selected(rows,kind):
    result=[]
    for row in rows:
        match=matches(row,kind)
        if match is None:raise OSError(errno.ENODATA,'Complete storage selection is unavailable; inspect WMIGetPhysicalDiskInfo for per-device errors.')
        if match:result.append(row)
    return result


def call(name,args):
    validate(name,args);rows=report()
    if name=='WMIGetPhysicalDiskInfo':
        return [{**r,'matches_physical_media':matches(r,'physical')} for r in rows if matches(r,'physical') is not False]
    # Caption uses Win32_DiskDrive fixed-media selection (including SSDs).
    # Info instead uses MSFT_PhysicalDisk MediaType3, as HDDList/Model do.
    kind={'WMIGetHDDCaption':'fixed','WMIGetHDDInfo':'hdd','WMIGetHDDList':'hdd','WMIGetHDDModel':'hdd','WMIGetHDDSize':'fixed',
          'WMIGetSSDList':'ssd','WMIGetSSDModel':'ssd','WMIGetSDCardCaption':'removable','WMIGetSDCardSize':'sd'}[name]
    chosen=selected(rows,kind)
    if name.endswith('Size'):
        if any(r['size'] is None for r in chosen):raise OSError(errno.ENODATA,'Complete selected disk capacity is unavailable.')
        total=sum(r['size'] for r in chosen)
        if name=='WMIGetSDCardSize' and args.get('detailed'):
            return {'total_bytes':total,'cards':[{'device':r['device'],'bytes':r['size'],'model':r['model'],'card_type':r['card_type'],'source':r['source']} for r in chosen],
                    'source':SOURCE,'note':'Complete per-card capacity and sum; original Windows wrapper retained only the last matching card size.'}
        return total
    if name.endswith(('Model','Caption')):
        if any(r['model'] is None for r in chosen):raise OSError(errno.ENODATA,'Complete selected disk model/caption list is unavailable.')
        return [r['model'] for r in chosen]
    return chosen
