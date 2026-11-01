# SPDX-License-Identifier: GPL-2.0-only
"""Cached HDMI connector presence, independent of USB ancestry and modesetting."""
from pathlib import Path
import errno
import re
import display_state


def report(root=Path('/sys/class/drm')):
    objects=display_state.paths(root);rows=[];guards=[];seen=set()
    for path in objects:
        if not re.fullmatch(r'card[0-9]+-HDMI-[AB]-[0-9]+',path.name):continue
        row={'connector':path.name,'available':False,'connected':None}
        try:
            identity=display_state.identity(path)
            if identity in seen:raise OSError(errno.EPROTO,'Duplicate HDMI connector identity.')
            seen.add(identity);state=display_state.state(path)
            row.update(available=True,connected=state=='connected');guards.append((path,identity,state,len(rows)))
        except OSError as error:row.update(errno=error.errno or errno.EIO,error=str(error))
        rows.append(row)
    if objects!=display_state.paths(root):raise OSError(errno.EAGAIN,'DRM connector inventory changed during HDMI sampling.')
    for path,identity,state,index in guards:
        try:
            if display_state.identity(path)!=identity or display_state.state(path)!=state:
                raise OSError(errno.EAGAIN,'HDMI connector identity or state changed during sampling.')
        except OSError as error:rows[index].update(available=False,connected=None,errno=error.errno or errno.EIO,error=str(error))
    complete=all(r['available'] for r in rows);positive=sum(r['connected'] is True for r in rows)
    return {'schema':1,'available':bool(positive) or complete,'hdmi_connected':True if positive else False if complete else None,
            'count':positive if complete else None,'minimum_count':positive,'coverage_complete':complete,'connectors':rows,
            'source':'Linux cached DRM HDMI-A/HDMI-B connector status',
            'note':'HDMI presence does not require USB ancestry, an enabled modeset or visible picture. DP/Type-C transport does not establish downstream HDMI identity. No EDID, DDC, scan or display setting is requested.'}
