# SPDX-License-Identifier: GPL-2.0-only
"""Read-only USB display transport evidence from DRM and Type-C sysfs.

Product names, USB vendor branding and virtual DRM drivers do not prove a USB
display is in use. No EDID, serial, modeset, role swap or alt-mode write is used.
"""
import errno
import re
import time
from pathlib import Path


def read(path):
    value=path.read_text().strip()
    if len(value)>256:raise OSError(errno.EPROTO,'Oversized sysfs display attribute.')
    return value


def selected(value,allowed):
    words=value.split();active=[]
    for word in words:
        match=re.fullmatch(r'\[([^][]+)\]',word)
        plain=match[1] if match else word
        if plain not in allowed:raise OSError(errno.EPROTO,'Invalid Type-C selection value.')
        if match:active.append(plain)
    if len(active)!=1:raise OSError(errno.ENODATA,'No unique active Type-C selection.')
    return active[0]


def identity(path):
    info=path.stat();return (info.st_dev,info.st_ino,str(path.resolve(strict=True)))


def usb_ancestor(path):
    resolved=path.resolve(strict=True)
    for parent in (resolved,*resolved.parents):
        if not (parent/'idVendor').is_file():continue
        vendor=read(parent/'idVendor');product=read(parent/'idProduct')
        if not all(re.fullmatch(r'[0-9a-fA-F]{4}',v) for v in (vendor,product)):
            raise OSError(errno.EPROTO,'Invalid USB ancestry identifiers.')
        return {'device':parent.name,'vendor_id':vendor.lower(),'product_id':product.lower()}
    return None


def drm_connector(path):
    before=identity(path);state=read(path/'status')
    if state not in ('connected','disconnected'):raise OSError(errno.ENODATA,'DRM connector status is unknown.')
    internal=bool(re.fullmatch(r'card[0-9]+-(eDP|LVDS|DSI)-[0-9]+',path.name))
    usb=usb_ancestor(path) if state=='connected' else None
    if before!=identity(path) or state!=read(path/'status'):
        raise OSError(errno.EAGAIN,'DRM connector changed during sampling.')
    return {'connector':path.name,'available':True,'state':state,'internal':internal and usb is None,
            'transport':'USB' if usb else 'embedded' if internal else 'unmapped',
            'usb_device':usb,'usb_output_connected':bool(usb) and state=='connected'}


def dp_mode(path):
    before=identity(path);fields={'svid':read(path/'svid')}
    if not re.fullmatch(r'(?:0x)?[0-9a-fA-F]{1,4}',fields['svid']):raise OSError(errno.EPROTO,'Invalid Type-C SVID.')
    if int(fields['svid'],16)!=0xff01:
        if before!=identity(path) or read(path/'svid')!=fields['svid']:
            raise OSError(errno.EAGAIN,'Type-C identity changed during sampling.')
        return None
    fields['active']=read(path/'active')
    if fields['active'] not in ('0','1'):raise OSError(errno.EPROTO,'Invalid Type-C mode activity.')
    active=fields['active']=='1';configuration=None;pin=None;hpd=None
    if active:
        fields['displayport/configuration']=read(path/'displayport/configuration')
        configuration=selected(fields['displayport/configuration'],{'USB','source','sink'})
        # The driver exports the partner's role: a sink partner means this
        # machine is the DP source. See configuration_show in displayport.c.
        if configuration=='sink':
            fields['displayport/pin_assignment']=read(path/'displayport/pin_assignment')
            pin=selected(fields['displayport/pin_assignment'],set('ABCDEF'))
        if (path/'displayport/hpd').exists():
            fields['displayport/hpd']=read(path/'displayport/hpd')
            if fields['displayport/hpd'] not in ('0','1'):raise OSError(errno.EPROTO,'Invalid DisplayPort HPD value.')
            hpd=fields['displayport/hpd']=='1'
    if before!=identity(path) or any(read(path/key)!=value for key,value in fields.items()):
        raise OSError(errno.EAGAIN,'Type-C mode changed during sampling.')
    return {'mode':path.name,'port':path.name.split('-')[0],'available':True,'active':active,
            'configuration':configuration,'pin_assignment':pin,'hpd':hpd,
            'local_displayport_role':'source' if configuration=='sink' else 'sink' if configuration=='source' else None,
            'output_transport_active':active and configuration=='sink' and pin is not None}


def report(drm_root=Path('/sys/class/drm'),typec_root=Path('/sys/bus/typec/devices')):
    connectors=[];modes=[];errors=[]
    for kind,root,pattern,reader,rows in [('DRM',drm_root,r'card[0-9]+-.+',drm_connector,connectors),
                                      ('Type-C',typec_root,r'port[0-9]+-partner\.[0-9]+',dp_mode,modes)]:
        try:paths=sorted(p for p in root.iterdir() if re.fullmatch(pattern,p.name))
        except OSError as error:
            errors.append({'provider':kind,'errno':error.errno or errno.EIO,'error':'Display metadata provider is unavailable.'});continue
        if len(paths)>256:
            errors.append({'provider':kind,'errno':errno.EOVERFLOW,'error':'Too many display metadata objects.'});continue
        for path in paths:
            try:
                row=reader(path)
                if row is not None:rows.append(row)
            except OSError as error:
                errors.append({'provider':kind,'object':path.name,'errno':error.errno or errno.EIO,'error':str(error)})
    connected=[r for r in connectors if r['state']=='connected']
    unmapped=[r['connector'] for r in connected if not r['internal'] and r['transport']=='unmapped']
    positive=any(r['usb_output_connected'] for r in connected) or any(r['output_transport_active'] for r in modes)
    complete=bool(connectors) and not errors and not unmapped
    used=True if positive else False if complete else None
    return {'schema':1,'available':used is not None,'usb_display':used,'coverage_complete':complete,
            'connected_displays':connected,'typec_displayport':modes,'unmapped_external_displays':unmapped,'errors':errors,
            'source':'Linux DRM USB ancestry and partner DisplayPort alt-mode configuration',
            'captured_monotonic_seconds':time.monotonic(),
            'note':'A connected DRM output with USB ancestry or configured Type-C DisplayPort source transport is positive evidence. Local mode capability, product names and virtual-driver names are insufficient. Source transport does not prove a visible picture or an HDMI adapter identity. Observations are sampled sequentially, not atomically.'}
