# SPDX-License-Identifier: GPL-2.0-only
"""Installed metadata for the actual bound ASUS system-control platform driver.

This is separate from the native frontend and loaded HealthyTable module.
Reading modinfo never loads, unloads or executes a kernel module.
"""
from pathlib import Path
import errno
import os
import re
import stat
import subprocess

DEVICE=Path('/sys/bus/platform/devices/asus-nb-wmi')
MODULES=Path('/sys/module')
MODULE_TREE=Path('/lib/modules')
MODINFO='/usr/sbin/modinfo'
TOKEN=r'[0-9A-Za-z][0-9A-Za-z.+_-]{0,127}'


def identity(path):
    info=path.stat()
    return info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns


def binding():
    device=DEVICE.resolve(strict=True);driver=(DEVICE/'driver').resolve(strict=True)
    module=(DEVICE/'driver/module').resolve(strict=True)
    if driver.name!='asus-nb-wmi' or module.parent!=MODULES.resolve(strict=True) or not re.fullmatch(r'[A-Za-z0-9_]{1,64}',module.name):
        raise OSError(errno.EPROTO,'Unexpected ASUS system-control driver binding.')
    return {'device':str(device),'driver':driver.name,'module':module.name},(identity(device),str(driver),identity(driver),str(module),identity(module))


def query(target,field,kernel):
    try:
        proc=subprocess.run([MODINFO,'-k',kernel,'-F',field,str(target)],capture_output=True,text=True,timeout=3,
                            env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C'})
    except subprocess.TimeoutExpired:raise OSError(errno.ETIMEDOUT,'Installed driver metadata timed out.') from None
    except UnicodeError:raise OSError(errno.EPROTO,'Invalid installed driver metadata encoding.') from None
    if proc.returncode:raise OSError(errno.ENODATA,'Installed driver metadata is unavailable.')
    value=proc.stdout.strip()
    if len(value)>4096 or '\n' in value or '\r' in value or any(ord(c)<32 or ord(c)>126 for c in value):
        raise OSError(errno.EPROTO,'Invalid installed driver metadata field.')
    return value


def selected_file(module,kernel):
    value=query(module,'filename',kernel)
    if not value or not Path(value).is_absolute():raise OSError(errno.ENODATA,'No installed loadable module file is available.')
    path=Path(value).resolve(strict=True);root=(MODULE_TREE/kernel).resolve(strict=True)
    if not path.is_relative_to(root) or not stat.S_ISREG(path.stat().st_mode):
        raise OSError(errno.EPROTO,'Installed module is outside the current kernel tree.')
    return path


def report():
    kernel=os.uname().release
    if not re.fullmatch(TOKEN,kernel):raise OSError(errno.EPROTO,'Invalid running kernel release.')
    selected,before=binding();path=selected_file(selected['module'],kernel);stamp=identity(path)
    name=query(path,'name',kernel);version=query(path,'version',kernel)
    intree=query(path,'intree',kernel);vermagic=query(path,'vermagic',kernel)
    if name!=selected['module'] or intree not in ('','Y') or not vermagic or vermagic.split()[0]!=kernel:
        raise OSError(errno.EPROTO,'Installed module identity or kernel metadata does not match.')
    if version:
        if not re.fullmatch(TOKEN,version):raise OSError(errno.EPROTO,'Invalid declared module version.')
        value=version;kind='declared_module_version'
    elif intree=='Y':value=kernel;kind='kernel_release'
    else:raise OSError(errno.ENODATA,'This out-of-tree module declares no version.')
    if identity(path)!=stamp or selected_file(selected['module'],kernel)!=path or binding()!=(selected,before):
        raise OSError(errno.EAGAIN,'System-control binding or installed module changed during the query.')
    return {'schema':1,'component':'installed ASUS system-control platform driver',**selected,
            'version':value,'version_kind':kind,'declared_module_version':version or None,
            'kernel_release':kernel,'in_tree':intree=='Y','module_file':str(path),
            'source':'actual platform binding and current-kernel modinfo metadata',
            'scope':'Installed module file; separate from frontend and loaded HealthyTable version.'}
