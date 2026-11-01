# SPDX-License-Identifier: GPL-2.0-only
"""Read only advertised EV_SW tablet state; never read an input event stream."""
from pathlib import Path
import errno
import fcntl
import os
import re
import stat


def identity(path):
    info=path.stat()
    return info.st_dev,info.st_ino


def event_paths(root):
    return sorted(p for p in root.iterdir() if re.fullmatch(r'event[0-9]+',p.name))


def switches(path):
    raw=(path/'device/capabilities/sw').read_text().strip()
    if not re.fullmatch(r'[0-9a-fA-F]{1,16}(?: [0-9a-fA-F]{1,16}){0,3}',raw):
        raise OSError(errno.EPROTO,'Invalid input switch capability bitmap.')
    # SW_TABLET_MODE is bit1 in the least significant native bitmap word.
    return int(raw.split()[-1],16)&2!=0


def read_switch(path,dev_root):
    major_minor=(path/'dev').read_text().strip()
    if not re.fullmatch(r'[0-9]+:[0-9]+',major_minor):raise OSError(errno.EPROTO,'Invalid evdev device number.')
    expected=os.makedev(*(int(x) for x in major_minor.split(':')))
    fd=os.open(dev_root/path.name,os.O_RDONLY|os.O_NONBLOCK|os.O_CLOEXEC|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if not stat.S_ISCHR(info.st_mode) or info.st_rdev!=expected:
            raise OSError(errno.EAGAIN,'Input device identity changed during sampling.')
        caps=bytearray(8);fcntl.ioctl(fd,0x80084525,caps,True)  # EVIOCGBIT(EV_SW,8)
        if not int.from_bytes(caps,'little')&2:raise OSError(errno.EAGAIN,'Tablet switch capability changed during sampling.')
        state=bytearray(8);fcntl.ioctl(fd,0x8008451b,state,True)  # EVIOCGSW(8)
        return bool(int.from_bytes(state,'little')&2)
    finally:os.close(fd)


def report(root=Path('/sys/class/input'),dev_root=Path('/dev/input')):
    paths=event_paths(root);rows=[];guards=[]
    for path in paths:
        row={'device':path.name,'available':False,'tablet_mode':None}
        try:
            before=identity(path)
            supported=switches(path)
            if not supported:
                guards.append((path,before,False));continue
            row.update(available=True,tablet_mode=read_switch(path,dev_root))
            if before!=identity(path) or not switches(path):
                raise OSError(errno.EAGAIN,'Input switch changed during sampling.')
            guards.append((path,before,True))
        except OSError as error:row.update(available=False,tablet_mode=None,errno=error.errno or errno.EIO,error=str(error))
        rows.append(row)
    if paths!=event_paths(root):raise OSError(errno.EAGAIN,'Input inventory changed during sampling.')
    for path,before,supported in guards:
        if before!=identity(path) or supported!=switches(path):
            raise OSError(errno.EAGAIN,'Input identity or switch capabilities changed during sampling.')
    positive=any(row['tablet_mode'] is True for row in rows)
    complete=bool(rows) and all(row['available'] for row in rows)
    return {'available':positive or complete,'tablet_mode':True if positive else False if complete else None,
            'complete':complete,'switches':rows,'source':'Linux EV_SW / SW_TABLET_MODE capability and EVIOCGSW current state',
            'note':'A positive switch is sufficient for tablet mode. Off requires a complete readable switch census. No keys, touches, motion or input event stream is recorded.'}


def value():
    result=report()
    if not result['available']:
        error=next((r for r in result['switches'] if not r['available']),{})
        raise OSError(error.get('errno',errno.ENODEV),error.get('error','No advertised tablet-mode switch is available.'))
    return result['tablet_mode']
