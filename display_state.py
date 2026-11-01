# SPDX-License-Identifier: GPL-2.0-only
"""Cached DRM connection and base-EDID identity; no modeset or DDC request."""
from pathlib import Path
import errno
import re

NAMES={'WMIGetExternMonitorNum','WMIGetExternMonitorPropList','WMIGetLCDModel'}


def identity(path):
    info=path.stat();return info.st_dev,info.st_ino,str(path.resolve(strict=True))


def paths(root):
    result=sorted(p for p in root.iterdir() if re.fullmatch(r'card[0-9]+-.+',p.name))
    if not result:raise OSError(errno.ENODEV,'No DRM connector metadata provider is present.')
    if len(result)>256:raise OSError(errno.EOVERFLOW,'Too many DRM connectors.')
    return result


def text(path,limit=65536):
    try:
        with path.open('r',encoding='ascii') as stream:raw=stream.read(limit+1)
    except UnicodeError:raise OSError(errno.EPROTO,'Invalid DRM metadata encoding.') from None
    if len(raw)>limit or '\x00' in raw:raise OSError(errno.EPROTO,'Invalid DRM metadata length or contents.')
    return raw.strip()


def state(path):
    value=text(path/'status',32)
    if value=='unknown':raise OSError(errno.ENODATA,'DRM connector state is unknown.')
    if value not in ('connected','disconnected'):raise OSError(errno.EPROTO,'Invalid DRM connector state.')
    return value


def base_row(path):
    return {'connector':path.name,'internal':bool(re.fullmatch(r'card[0-9]+-(eDP|LVDS|DSI)-[0-9]+',path.name)),
            'available':False,'state':None,'source':'Linux cached DRM connector state; optional cached base-EDID identity'}


def edid_identity(data):
    if len(data)<128:raise OSError(errno.ENODATA,'No complete base EDID is cached.')
    block=data[:128]
    if block[:8]!=b'\0\xff\xff\xff\xff\xff\xff\0' or sum(block)%256 or block[18]!=1:
        raise OSError(errno.EPROTO,'Cached base EDID header, checksum or version is invalid.')
    vendor=int.from_bytes(block[8:10],'big');codes=[(vendor>>s)&31 for s in (10,5,0)]
    if vendor&0x8000 or any(not 1<=code<=26 for code in codes):
        raise OSError(errno.EPROTO,'Invalid base EDID manufacturer code.')
    result={'manufacturer':''.join(chr(64+x) for x in codes),'product_id':int.from_bytes(block[10:12],'little'),
            'edid_base_available':True,'model_available':False}
    for off in (54,72,90,108):
        if block[off:off+5]!=b'\0\0\0\xfc\0':continue
        label=block[off+5:off+18].split(b'\n')[0].rstrip(b' \0')
        if label and all(32<=byte<=126 for byte in label):
            result.update(model=label.decode('ascii'),model_available=True)
        else:result.update(model_errno=errno.EPROTO,model_error='Cached EDID model text is empty or invalid.')
        break
    return result


def connector(path):
    row=base_row(path)
    before=identity(path);connection=state(path)
    row.update(available=True,state=connection)
    if connection=='connected':
        try:
            modes=text(path/'modes').splitlines()
            if len(modes)>1024 or any(len(m)>64 or any(not 32<=ord(c)<=126 for c in m) for m in modes):
                raise OSError(errno.EPROTO,'Invalid cached DRM mode names.')
            row.update(modes=modes,modes_available=True)
        except OSError as error:row.update(modes=None,modes_available=False,modes_errno=error.errno or errno.EIO,modes_error=str(error))
        try:
            with (path/'edid').open('rb') as stream:data=stream.read(32769)
            if len(data)>32768:raise OSError(errno.EOVERFLOW,'Oversized cached EDID.')
            row.update(edid_identity(data))
        except OSError as error:row.update(edid_base_available=False,model_available=False,edid_errno=error.errno or errno.EIO,edid_error=str(error))
    if before!=identity(path) or connection!=state(path):
        raise OSError(errno.EAGAIN,'DRM connection changed during metadata sampling.')
    return row,before,connection


def report(root=Path('/sys/class/drm')):
    objects=paths(root);rows=[];guards=[]
    for path in objects:
        try:
            row,before,connection=connector(path);guards.append((path,before,connection,len(rows)))
        except OSError as error:
            row=base_row(path);row.update(errno=error.errno or errno.EIO,error=str(error))
        rows.append(row)
    if objects!=paths(root):raise OSError(errno.EAGAIN,'DRM connector inventory changed during sampling.')
    for path,before,connection,index in guards:
        try:
            if before!=identity(path) or connection!=state(path):raise OSError(errno.EAGAIN,'DRM identity or connection changed during sampling.')
        except OSError as error:
            row=base_row(path);row.update(errno=error.errno or errno.EIO,error=str(error));rows[index]=row
    return rows


def validate(name,args):
    if name not in NAMES:raise KeyError(name)
    if not isinstance(args,dict) or set(args)-({'internal_only'} if name=='WMIGetLCDModel' else set()):
        raise ValueError('Only LCD model queries accept the optional internal_only selector.')
    if 'internal_only' in args and type(args['internal_only']) is not bool:raise ValueError('internal_only must be boolean.')


def call(name,args):
    validate(name,args)
    rows=report()
    if name=='WMIGetLCDModel':return [r for r in rows if r['state']!='disconnected' and (not args.get('internal_only',False) or r['internal'])]
    rows=[r for r in rows if not r['internal']]
    if name=='WMIGetExternMonitorPropList':return [r for r in rows if r['state']!='disconnected']
    if name=='WMIGetExternMonitorNum':
        for row in rows:
            if not row['available']:raise OSError(row['errno'],row['error'])
        return sum(r['state']=='connected' for r in rows)
    raise KeyError(name)
