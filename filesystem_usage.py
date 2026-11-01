# SPDX-License-Identifier: GPL-2.0-only
"""Mounted capacity with pinned directory/mount and block-generation identity.

Only existing directory descriptors and cached kernel metadata are read; no
block device is opened. mountinfo dev_t and fdinfo mnt_id are documented at:
https://docs.kernel.org/filesystems/proc.html
Unsupported filesystem/device mappings stay unavailable, never a parent total.
"""
from pathlib import Path
import contextlib
import errno
import math
import os
import re
import subprocess
import time
import storage_inventory as storage

SOURCE='Linux pinned-directory fstatvfs; mounted filesystem capacity, not device I/O utilization'
DEV=re.compile(r'(0|[1-9][0-9]{0,9}):(0|[1-9][0-9]{0,9})')


def number(value):
    if not re.fullmatch(r'[0-9]{1,20}',value) or int(value)>2**64-1:
        raise OSError(errno.EPROTO,'Invalid mount identity number.')
    return int(value)


def device(value):
    if not isinstance(value,str) or not DEV.fullmatch(value) or any(int(x)>2**32-1 for x in value.split(':')):
        raise OSError(errno.EPROTO,'Invalid filesystem block-device number.')
    return value


def unescape(value):
    if re.search(r'\\(?!040|011|012|134)',value):raise OSError(errno.EPROTO,'Invalid mountinfo path escape.')
    return re.sub(r'\\(040|011|012|134)',lambda m:chr(int(m[1],8)),value)


def mount_table(raw):
    result={}
    for line in raw.splitlines():
        fields=line.split(' ')
        try:separator=fields.index('-')
        except ValueError:raise OSError(errno.EPROTO,'Mountinfo separator is unavailable.') from None
        if separator<6 or len(fields)!=separator+4 or any(not x for x in fields):
            raise OSError(errno.EPROTO,'Invalid mountinfo record.')
        ident=number(fields[0]);number(fields[1]);dev=device(fields[2])
        root=unescape(fields[3]);mount=unescape(fields[4])
        # nsfs records can use an opaque root such as mnt:[123]. It is never
        # opened or interpreted as a disk path; retain it for equality checks.
        if (not ident or ident in result or not root or '\x00' in root or
                not mount.startswith('/') or '\x00' in mount or os.path.normpath(mount)!=mount):
            raise OSError(errno.EPROTO,'Invalid or duplicate mount identity/path.')
        # Preserve the whole record: root, options and filesystem type changes
        # are relevant even when mount ID and dev_t remain the same.
        result[ident]={'device':dev,'mount':mount,'record':tuple(fields)}
        if len(result)>4096:raise OSError(errno.EOVERFLOW,'Too many mounted filesystems.')
    return result


def capacity(sample):
    values=[getattr(sample,k,None) for k in ('f_frsize','f_blocks','f_bfree','f_bavail')]
    if any(type(x) is not int or not 0<=x<=2**64-1 for x in values):
        raise OSError(errno.EPROTO,'Invalid filesystem capacity counters.')
    unit,blocks,free,available=values
    if not unit or not available<=free<=blocks:raise OSError(errno.EPROTO,'Inconsistent filesystem capacity counters.')
    total=blocks*unit;used=(blocks-free)*unit;free=available*unit
    percent=round(100*used/(used+free),1) if used+free else 0.0
    if not math.isfinite(percent):raise OSError(errno.EPROTO,'Non-finite filesystem capacity.')
    return dict(total=total,used=used,free=free,percent=percent)


class Reader:
    def text(self,path,limit):
        with Path(path).open('r',encoding='utf-8',errors='strict') as stream:
            try:raw=stream.read(limit+1)
            except UnicodeError:raise OSError(errno.EPROTO,'Invalid kernel mount metadata encoding.') from None
        if len(raw)>limit:raise OSError(errno.EOVERFLOW,'Kernel mount metadata exceeds its bound.')
        return raw

    def mounts(self):return mount_table(self.text('/proc/self/mountinfo',2*1024*1024))

    def block(self,node):
        if not re.fullmatch(r'[a-zA-Z0-9_.!+-]{1,128}',node['name']):raise OSError(errno.EPROTO,'Invalid selected kernel disk name.')
        path=Path('/sys/class/block')/node['name'];before=storage.identity(path)
        try:sequence=storage.number(path/'diskseq',2**64-1)
        except FileNotFoundError:raise OSError(errno.EOPNOTSUPP,'Kernel disk-generation metadata is unavailable.') from None
        metadata=storage.sample(path)
        if (not metadata['available'] or any(metadata[k] is None or metadata[k]!=node[lk]
                for k,lk in [('size','size'),('rotational','rota'),('removable','rm')])):
            raise OSError(errno.EAGAIN,'Selected disk classification changed after mount discovery.')
        if device(node['maj:min'])!=before[-1] or storage.identity(path)!=before:
            raise OSError(errno.EAGAIN,'Selected block identity changed during sampling.')
        return before,sequence

    def open(self,mount):return os.open(mount,os.O_PATH|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
    def close(self,fd):os.close(fd)

    def identity(self,fd):
        values=[line.split(':',1)[1].strip() for line in self.text(f'/proc/self/fdinfo/{fd}',4096).splitlines() if line.startswith('mnt_id:')]
        if len(values)!=1:raise OSError(errno.EPROTO,'Opened directory mount identity is unavailable.')
        info=os.fstat(fd)
        return number(values[0]),f'{os.major(info.st_dev)}:{os.minor(info.st_dev)}',info.st_ino

    def capacity(self,fd):return capacity(os.fstatvfs(fd))


def nodes(roots):
    if not isinstance(roots,list) or len(roots)>64:raise OSError(errno.EOVERFLOW,'Invalid selected disk census.')
    pending=[(n,0) for n in reversed(roots)];result=[]
    while pending:
        node,depth=pending.pop()
        if not isinstance(node,dict) or depth>64 or len(result)>=1024:
            raise OSError(errno.EOVERFLOW,'Invalid or oversized mount inventory.')
        name=node.get('name');path=node.get('path');mounts=node.get('mountpoints');children=node.get('children',[])
        if (not isinstance(name,str) or not 1<=len(name)<=255 or '\x00' in name or
                not isinstance(path,str) or not path.startswith('/dev/') or '\x00' in path or os.path.normpath(path)!=path or
                not isinstance(children,list) or mounts is not None and not isinstance(mounts,list)):
            raise OSError(errno.EPROTO,'Invalid mount inventory node.')
        device(node.get('maj:min'))
        if any(m is not None and (not isinstance(m,str) or not m.startswith('/') or '\x00' in m or os.path.normpath(m)!=m) for m in mounts or []):
            raise OSError(errno.EPROTO,'Invalid mount inventory path.')
        result.append(node);pending.extend((c,depth+1) for c in reversed(children))
    return result


def report(kind,inventory,reader=None,clock=time.monotonic):
    reader=reader or Reader();deadline=clock()+8
    def remaining():
        value=deadline-clock()
        if value<=0:raise OSError(errno.ETIMEDOUT,'Filesystem capacity sampling budget expired.')
        return min(4,value)
    def discover():
        try:return inventory(kind,timeout=remaining())
        except subprocess.TimeoutExpired:raise OSError(errno.ETIMEDOUT,'Block mount inventory timed out.') from None
    roots=discover();nodes(roots)
    guards=[reader.block(n) for n in roots]
    before=reader.mounts();out=[];seen=set();verified=[]
    def unavailable(result,error):
        return {k:v for k,v in result.items() if k in ('path','mount','source')}|{'available':False,'errno':error.errno or errno.EIO,'error':str(error)}
    with contextlib.ExitStack() as opened:
        for root in roots:
            mounted=False
            for node in nodes([root]):
                for mount in node.get('mountpoints') or []:
                    if mount is None:continue
                    mounted=True;key=(node['path'],mount)
                    if key in seen:continue
                    if len(seen)>=256:raise OSError(errno.EOVERFLOW,'Too many mounted filesystem observations.')
                    seen.add(key);result={'path':node['path'],'mount':mount,'available':False,'source':SOURCE}
                    try:
                        remaining()
                        fd=reader.open(mount);opened.callback(reader.close,fd)
                        identity=reader.identity(fd);entry=before.get(identity[0])
                        if not entry or entry['mount']!=mount or entry['device']!=node['maj:min'] or identity[1]!=node['maj:min']:
                            raise OSError(errno.EAGAIN,'Mount path no longer identifies the selected filesystem; unsupported mappings are not guessed.')
                        values=reader.capacity(fd)
                        if reader.identity(fd)!=identity:raise OSError(errno.EAGAIN,'Opened filesystem identity changed during sampling.')
                        result.update(available=True,**values,mount_id=identity[0],filesystem_device=identity[1],identity_verified=True)
                        verified.append((len(out),fd,identity,entry))
                    except OSError as error:result=unavailable(result,error)
                    out.append(result)
            if not mounted:out.append({'path':root['path'],'mount':None,'available':False,'source':SOURCE,
                                       'errno':errno.ENODATA,'error':'No mounted filesystem for this disk in the current namespace.'})
        if discover()!=roots or [reader.block(n) for n in roots]!=guards:
            raise OSError(errno.EAGAIN,'Selected disk generation or mount inventory changed during sampling.')
        after=reader.mounts()
        for index,fd,identity,entry in verified:
            try:
                remaining()
                if after.get(identity[0])!=entry or reader.identity(fd)!=identity:
                    raise OSError(errno.EAGAIN,'Filesystem mount changed before publication.')
                check=reader.open(out[index]['mount'])
                try:
                    if reader.identity(check)!=identity:raise OSError(errno.EAGAIN,'Mount path was replaced or overmounted before publication.')
                finally:reader.close(check)
            except OSError as error:out[index]=unavailable(out[index],error)
        remaining()
        return out
