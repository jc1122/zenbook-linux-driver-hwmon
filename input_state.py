# SPDX-License-Identifier: GPL-2.0-only
"""Input capabilities and LED metadata only; no input events or state writes."""
from pathlib import Path
import errno
import re


def identity(path):
    info=path.stat();return info.st_dev,info.st_ino,str(path.resolve(strict=True))


def paths(root,pattern):
    result=sorted(p for p in root.iterdir() if re.fullmatch(pattern,p.name))
    if len(result)>4096:raise OSError(errno.EOVERFLOW,'Too many input metadata objects.')
    return result


def bitmap(path):
    try:raw=path.read_text(encoding='ascii').strip()
    except UnicodeError:raise OSError(errno.EPROTO,'Invalid input metadata encoding.') from None
    if not re.fullmatch(r'[0-9a-fA-F]{1,16}(?: [0-9a-fA-F]{1,16}){0,63}',raw):
        raise OSError(errno.EPROTO,'Invalid native64 input key bitmap.')
    return int(''.join(word.zfill(16) for word in raw.split()),16)


def keyboard(path):
    bits=bitmap(path/'device/capabilities/key')
    return bool(bits&(1<<30)) and bool(bits&(1<<44))


def led(path):
    try:
        maximum=(path/'max_brightness').read_text(encoding='ascii').strip()
        raw=(path/'brightness').read_text(encoding='ascii').strip()
    except UnicodeError:raise OSError(errno.EPROTO,'Invalid input LED metadata encoding.') from None
    if maximum!='1' or raw not in ('0','1'):
        raise OSError(errno.EPROTO,'Num Lock LED is not a valid binary input LED.')
    return raw=='1'


def report(input_root=Path('/sys/class/input'),led_root=Path('/sys/class/leds')):
    rows=[];leds=[];errors=[]
    complete={'input':True,'LED':True}
    for kind,root,pattern,read,target,field in [
        ('input',input_root,r'event[0-9]+',keyboard,rows,'keyboard'),
        ('LED',led_root,r'.*::numlock',led,leds,'num_lock')]:
        try:objects=paths(root,pattern)
        except OSError as error:
            complete[kind]=False;errors.append({'provider':kind,'errno':error.errno or errno.EIO,'error':str(error)});continue
        guards=[]
        for path in objects:
            row={'device':path.name,'available':False,field:None};target.append(row)
            try:
                before=identity(path);value=read(path)
                if before!=identity(path) or value!=read(path):
                    raise OSError(errno.EAGAIN,'Input metadata changed during sampling.')
                row.update(available=True,**{field:value});guards.append((path,before,value,row))
            except OSError as error:
                complete[kind]=False;row.update(errno=error.errno or errno.EIO,error=str(error))
        try:
            if objects!=paths(root,pattern):raise OSError(errno.EAGAIN,'Input metadata inventory changed during sampling.')
            for path,before,value,row in guards:
                try:
                    if before!=identity(path) or value!=read(path):raise OSError(errno.EAGAIN,'Input metadata identity or state changed during sampling.')
                except OSError as error:
                    complete[kind]=False;row.update(available=False,**{field:None},errno=error.errno or errno.EIO,error=str(error))
        except OSError as error:
            complete[kind]=False;errors.append({'provider':kind,'errno':error.errno or errno.EIO,'error':str(error)})
    states=[r['num_lock'] for r in leds if r['available']]
    num_lock=states[0] if complete['LED'] and states and len(set(states))==1 else None
    observed=sum(r['keyboard'] is True for r in rows)
    return {'num_lock':num_lock,'num_lock_available':num_lock is not None,'num_lock_complete':complete['LED'],
            'keyboard_num':observed if complete['input'] else None,'keyboard_inventory_complete':complete['input'],
            'observed_keyboard_num':observed,'per_keyboard_num_lock':states,'keyboards':rows,'num_lock_leds':leds,'errors':errors,
            'source':'Linux native64 key capabilities (KEY_A and KEY_Z) and binary Num Lock LED state',
            'note':'Keyboard count is input event devices advertising both keys, not unique physical peripherals. Num Lock is a complete LED consensus, not a key press or desktop-session query. Missing, conflicting or unreadable LED state is null. Samples are sequential; no event stream, input contents or write is used.'}
