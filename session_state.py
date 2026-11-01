# SPDX-License-Identifier: GPL-2.0-only
"""Existing local GNOME session keymap queries; never read an event stream."""
import errno
import os
import desktop_windows


NAME='org.zenbook.HardwareBridge'
PATH='/org/zenbook/HardwareBridge'


def report():
    result={'available':False,'num_lock':None,'source':'GNOME Shell default-seat keymap Num Lock toggle',
            'read_only':True,'existing_provider_only':True}
    try:
        address=os.environ.get('DBUS_SESSION_BUS_ADDRESS','')
        if not address.startswith('unix:') or ';' in address or len(address)>1024:
            raise OSError(errno.ENODEV,'No existing desktop session bus is selected.')
        try:import dbus
        except ImportError:raise OSError(errno.ENODEV,'Desktop D-Bus bindings are unavailable.') from None
        try:
            bus=dbus.SessionBus()
            def manager(method,value):
                return bus.call_blocking('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus',method,'s',(value,),timeout=2)
            # Same pinned, same-user, /usr/bin/gnome-shell owner check as the window provider.
            owner=desktop_windows._shell_owner(bus,NAME)
            obj=bus.get_object(owner,PATH,introspect=False)
            version=obj.GetVersion(dbus_interface=NAME,timeout=2)
            if not isinstance(version,str):raise OSError(errno.EPROTO,'Invalid session bridge version.')
            if version not in ('3','4'):raise OSError(errno.EOPNOTSUPP,'Session bridge does not provide the qualified Num Lock interface.')
            value=obj.GetNumLock(dbus_interface=NAME,timeout=2)
            if not isinstance(value,(bool,dbus.Boolean)):raise OSError(errno.EPROTO,'Session Num Lock is not a D-Bus Boolean.')
            if manager('GetNameOwner',NAME)!=owner:raise OSError(errno.EAGAIN,'Session bridge owner changed during sampling.')
            result.update(available=True,num_lock=bool(value),bridge_version=version)
        except dbus.DBusException as error:
            name=error.get_dbus_name()
            code=errno.ENODEV if name.endswith(('ServiceUnknown','NameHasNoOwner')) else errno.EACCES if name.endswith(('AccessDenied','AuthFailed','NotAuthorized')) else errno.ETIMEDOUT if name.endswith(('NoReply','TimedOut','Timeout')) else errno.EOPNOTSUPP if name.endswith(('UnknownMethod','UnknownInterface')) else errno.EIO
            raise OSError(code,'Read-only desktop keymap query is unavailable.') from None
    except OSError as error:result.update(errno=error.errno or errno.EIO,error=str(error))
    result['note']='Logical desktop-session toggle, separate from hardware LED consensus. No activation, input events, key contents, toggle or Xwayland/LED substitute. The enabled bridge may require a normal new login before Shell discovers it.'
    return result
