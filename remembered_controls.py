# SPDX-License-Identifier: GPL-2.0-only
"""Successful hardware selection plus a private user-choice record.

No boot policy, daemon activation, profile hold, action or PL1 ownership change.
"""
from pathlib import Path
import errno
from types import SimpleNamespace
import user_preferences

PATHS={'charge-limit':Path('/sys/class/power_supply/BAT0/charge_control_end_threshold'),
       'profile':Path('/sys/firmware/acpi/platform_profile')}
FIELDS={'charge-limit':'battery_charge_limit_percent','profile':'platform_profile'}

class ControlError(OSError):
    def __init__(self,code,message,result):super().__init__(code,message);self.control_result=result


def identity(path):
    info=path.stat();return info.st_dev,info.st_ino


def set_and_remember(front,command,value):
    field=FIELDS[command];path=PATHS[command];user_preferences.validate_value(field,value)
    preferences=user_preferences.read(prepare=True) # Fail invalid ownership/configuration before hardware.
    before_identity=identity(path)
    result=front.control(SimpleNamespace(command=command,value=value))
    if result.get('after')!=str(value) or before_identity!=identity(path):
        raise ControlError(errno.EAGAIN,'Hardware identity/readback changed; user choice was not stored.',{'hardware':result,'remembered':False})
    try:after=user_preferences.remember(field,value,preferences['revision'])
    except OSError as error:
        # A late/missing response can still have committed. Independently read
        # back the desired value before reporting a failed remember operation.
        try:current=user_preferences.read()
        except OSError:current=None
        if current is not None and current['values'].get(field)==value:
            return {**result,'remembered':True,'preferences':current,'persistence_readback_recovered':True}
        detail={'hardware':result,'remembered':False,'hardware_restored':False,'persistence_errno':error.errno}
        unchanged=current is not None and current['revision']==preferences['revision']
        if getattr(error,'committed',None) is False and unchanged and error.errno!=errno.EAGAIN:
            try:
                if identity(path)==before_identity and path.read_text().strip()==str(value):
                    if result['before']!=str(value):front.control(SimpleNamespace(command=command,value=result['before']))
                    detail['hardware_restored']=path.read_text().strip()==result['before']
            except (OSError,RuntimeError,ValueError):pass
        raise ControlError(error.errno or errno.EIO,'User choice could not be saved; inspect the control result and current setting.',detail) from None
    return {**result,'remembered':True,'preferences':after}
