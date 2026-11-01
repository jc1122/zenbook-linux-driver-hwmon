# SPDX-License-Identifier: GPL-2.0-only
"""Privileged routing for unprivileged callers.

A non-root caller reaches privileged operations through the system service
`org.zenbook.Hardware1` (zenbook-hardwared, polkit-authorised). Root callers
(`sudo zenbook-hardware ...`) never come here: they keep the direct in-process
path as the recovery route. Plain interactive `sudo` remains only an explicit
opt-in fallback when the service is unavailable. This module never reads a
keyring, a password or auth.json contents; the former Secret Service sudo route
was removed by owner decision.
"""
from pathlib import Path
import errno
import json
import os
import subprocess
import sys

BUS_NAME='org.zenbook.Hardware1'
OBJECT_PATH='/org/zenbook/Hardware1'
INTERFACE='org.zenbook.Hardware1'
ERROR_PREFIX='org.zenbook.Hardware1.Error.'
DEFAULT_SYSTEM_BUS='unix:path=/run/dbus/system_bus_socket'
UNAVAILABLE='privileged service unavailable; run with sudo'
LEASE_MIN_SECONDS=1
LEASE_MAX_SECONDS=300
# Client-side reply bounds. The service bounds polkit at 25 s (180 s when
# interactive) and provider work at 45 s. The C ABI kills its bridge at 60 s,
# so the non-interactive bridge bound stays below that.
BRIDGE_TIMEOUT_MS=55000
NONINTERACTIVE_TIMEOUT_MS=75000
INTERACTIVE_TIMEOUT_MS=240000
UNAVAILABLE_ERRORS={'org.freedesktop.DBus.Error.ServiceUnknown','org.freedesktop.DBus.Error.NameHasNoOwner',
    'org.freedesktop.DBus.Error.NoServer','org.freedesktop.DBus.Error.Disconnected','org.freedesktop.DBus.Error.UnknownObject',
    'org.freedesktop.DBus.Error.UnknownInterface','org.freedesktop.DBus.Error.UnknownMethod','org.freedesktop.DBus.Error.FileNotFound',
    'org.freedesktop.systemd1.NoSuchUnit','org.freedesktop.systemd1.UnitMasked'}
DENIED_ERRORS={'org.freedesktop.PolicyKit1.Error.NotAuthorized','org.freedesktop.DBus.Error.AccessDenied',
    'org.freedesktop.DBus.Error.AuthFailed','org.freedesktop.DBus.Error.InteractiveAuthorizationRequired'}
TIMEOUT_ERRORS={'org.freedesktop.DBus.Error.NoReply','org.freedesktop.DBus.Error.Timeout','org.freedesktop.DBus.Error.TimedOut'}
_MISSING=object()


class ServiceUnavailable(PermissionError):
    """The privileged service cannot be reached; EACCES like an unprivileged caller."""
    def __init__(self,detail=''):
        super().__init__(errno.EACCES,UNAVAILABLE+('' if not detail else ' ('+detail+')'))
    def __str__(self):return self.strerror


class RemoteError(OSError):
    """A provider/service error carried over the bus with its exact envelope fields."""
    def __init__(self,code,message,control=_MISSING,committed=_MISSING):
        super().__init__(code,message);self.message=message
        if control is not _MISSING:self.control_result=control
        if committed is not _MISSING:self.committed=committed
    def __str__(self):return self.message


def deprecated_auth_notice(stream=None):
    """One line if the retired auth.json exists. The file is never read or removed."""
    base=os.environ.get('XDG_CONFIG_HOME') or str(Path.home()/'.config')
    path=Path(base)/'zenbook-hardware/auth.json'
    try:present=os.path.lexists(path)
    except (OSError,ValueError):present=False
    if present:
        print('zenbook-hardware: '+str(path)+' is ignored; the Secret Service sudo route was removed (privileged service or sudo only).',
              file=stream or sys.stderr)
    return present


def bus_address():
    """System bus address. An unprivileged caller may select another unix: bus
    (private test buses); anything else uses the standard system socket."""
    value=os.environ.get('DBUS_SYSTEM_BUS_ADDRESS','')
    if os.geteuid()!=0 and value.startswith('unix:') and '\n' not in value and len(value)<=4096:return value
    return DEFAULT_SYSTEM_BUS


def interactive_default():
    """Allow polkit interaction with a terminal or a graphical session (CLI only)."""
    try:tty=sys.stdin.isatty()
    except (AttributeError,ValueError):tty=False
    return bool(tty or os.environ.get('WAYLAND_DISPLAY') or os.environ.get('DISPLAY'))


def _gi():
    import gi
    gi.require_version('Gio','2.0');gi.require_version('GLib','2.0')
    from gi.repository import Gio,GLib
    return Gio,GLib


def unix_signal_add(GLib):
    try:
        import gi
        gi.require_version('GLibUnix','2.0')
        from gi.repository import GLibUnix
        return GLibUnix.signal_add
    except (ImportError,ValueError,AttributeError):return GLib.unix_signal_add


def decode_envelope(text):
    """Return the result of a C-bridge envelope or raise its error unchanged."""
    try:envelope=json.loads(text)
    except (TypeError,ValueError) as error:raise OSError(errno.EPROTO,'Invalid privileged service reply.') from error
    if not isinstance(envelope,dict) or not isinstance(envelope.get('ok'),bool):raise OSError(errno.EPROTO,'Invalid privileged service reply.')
    if envelope['ok']:return envelope.get('result')
    detail=envelope.get('error')
    if not isinstance(detail,dict) or type(detail.get('errno')) is not int or not isinstance(detail.get('message'),str):
        raise OSError(errno.EPROTO,'Invalid privileged service error reply.')
    raise RemoteError(detail['errno'],detail['message'],detail.get('control',_MISSING),detail.get('configuration_committed',_MISSING))


def inside_service():
    """True inside zenbook-hardwared (which imports api_bridge in-process); a
    non-root test daemon must never route back to itself."""
    main=sys.modules.get('__main__')
    return Path(getattr(main,'__file__','') or '').name=='zenbook_hardwared.py'


class ServiceClient:
    """Minimal GDBus client. `connection` may be any object with Gio's
    call_sync() signature (tests inject a fake bus)."""

    def __init__(self,interactive=False,connection=None,timeout_ms=None):
        if inside_service():raise PermissionError(errno.EACCES,'Recursive privileged-service call refused.')
        self.interactive=bool(interactive);self._conn=connection
        self.timeout_ms=timeout_ms or (INTERACTIVE_TIMEOUT_MS if self.interactive else NONINTERACTIVE_TIMEOUT_MS)
        try:self.Gio,self.GLib=_gi()
        except (ImportError,ValueError) as error:raise ServiceUnavailable('python3-gi: '+type(error).__name__) from None

    @property
    def connection(self):
        if self._conn is None:
            Gio=self.Gio
            try:
                self._conn=Gio.DBusConnection.new_for_address_sync(bus_address(),
                    Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT|Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,None,None)
            except self.GLib.Error as error:raise ServiceUnavailable('system bus: '+error.message) from None
        return self._conn

    def map_error(self,error):
        Gio=self.Gio
        name=Gio.DBusError.get_remote_error(error) if Gio.DBusError.is_remote_error(error) else None
        message=error.message or ''
        prefix='GDBus.Error:'+(name or '')+': '
        if name and message.startswith(prefix):message=message[len(prefix):]
        if name and name.startswith(ERROR_PREFIX):
            code=getattr(errno,name[len(ERROR_PREFIX):],None)
            return RemoteError(code if type(code) is int else errno.EIO,message)
        if name in DENIED_ERRORS:return PermissionError(errno.EACCES,'Not authorized: '+message)
        if name in TIMEOUT_ERRORS:return OSError(errno.ETIMEDOUT,'Privileged service did not reply in time.')
        if name in UNAVAILABLE_ERRORS or (name or '').startswith('org.freedesktop.DBus.Error.Spawn'):return ServiceUnavailable(name)
        if name is None:
            if error.matches(Gio.io_error_quark(),Gio.IOErrorEnum.TIMED_OUT):return OSError(errno.ETIMEDOUT,'Privileged service did not reply in time.')
            if error.matches(Gio.io_error_quark(),Gio.IOErrorEnum.CLOSED):return ServiceUnavailable('bus connection closed')
        return OSError(errno.EIO,'Privileged service error: '+(name or message))

    def invoke(self,method,signature=None,args=None,reply='(s)'):
        Gio,GLib=self.Gio,self.GLib
        flags=Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION if self.interactive else Gio.DBusCallFlags.NONE
        try:
            value=self.connection.call_sync(BUS_NAME,OBJECT_PATH,INTERFACE,method,GLib.Variant(signature,args) if signature else None,
                                            GLib.VariantType(reply),flags,self.timeout_ms,None)
        except GLib.Error as error:raise self.map_error(error) from None
        return value.unpack()[0]

    # Envelope methods: identical results/errno to the in-process bridge.
    def call(self,name,args,apply=False,expected_sha256=None):
        text=json.dumps(args,allow_nan=False)
        return decode_envelope(self.invoke('Call','(ssbs)',(name,text,bool(apply),expected_sha256 or '')))
    def control(self,command,args=None):
        return decode_envelope(self.invoke('Control','(ss)',(command,json.dumps(args or {},allow_nan=False))))
    def metrics(self):return decode_envelope(self.invoke('Metrics'))
    def set_fan_auto(self):return decode_envelope(self.invoke('SetFanAuto'))
    # Lease methods report failures as org.zenbook.Hardware1.Error.<ERRNO>.
    def acquire_fan_lease(self,seconds,request):
        if type(seconds) is not int or not LEASE_MIN_SECONDS<=seconds<=LEASE_MAX_SECONDS:raise ValueError('Lease duration must be 1..300 seconds.')
        return self.invoke('AcquireFanLease','(us)',(seconds,str(request)))
    def release_fan_lease(self,lease_id):return decode_envelope(self.invoke('ReleaseFanLease','(s)',(lease_id,)))

    def hold_fan_lease(self,seconds,request,on_acquired=None):
        """Acquire a lease, keep this bus connection for `seconds` (or until
        SIGINT/SIGTERM/SIGHUP or the service ends the lease), then release it.
        Returns the service's end report {lease, reason, automatic_restored, mode}."""
        import signal
        GLib=self.GLib;loop=GLib.MainLoop();state={'reason':None,'lease':None}
        def ended(_conn,_sender,_path,_iface,_signal,params):
            lease_id,reason=params.unpack()
            if lease_id==state['lease'] or state['lease'] is None:
                state.setdefault('pending',{})[lease_id]=reason
                if lease_id==state['lease']:state['reason']=reason;loop.quit()
        # Subscribe first so an immediate end (low RPM, 1 s lease) is not missed.
        subscription=self.connection.signal_subscribe(BUS_NAME,INTERFACE,'FanLeaseEnded',OBJECT_PATH,None,self.Gio.DBusSignalFlags.NONE,ended)
        sources=[]
        try:
            # The service's expiry (1 s later) is the backstop; normally this
            # client releases first and receives the restoration readback.
            if type(seconds) is not int or not LEASE_MIN_SECONDS<=seconds<=LEASE_MAX_SECONDS:raise ValueError('Lease duration must be 1..300 seconds.')
            state['lease']=lease_id=self.acquire_fan_lease(min(seconds+1,LEASE_MAX_SECONDS),request)
            if state.get('pending',{}).get(lease_id):state['reason']=state['pending'][lease_id]
            if on_acquired:on_acquired(lease_id)
            if state['reason'] is None:
                def stop(*_args):
                    loop.quit();return False
                sources.append(GLib.timeout_add(seconds*1000 if seconds<LEASE_MAX_SECONDS else seconds*1000-500,stop))
                add=unix_signal_add(GLib)
                for signum in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):sources.append(add(GLib.PRIORITY_HIGH,signum,stop))
                loop.run()
            if state['reason'] is not None:
                return {'lease':lease_id,'reason':state['reason'],'automatic_restored':None,'mode':None}
            try:return self.release_fan_lease(lease_id)
            except RemoteError as error:
                if error.errno!=errno.ENOENT:raise
                # The service's own expiry won the race; it restored automatic.
                return {'lease':lease_id,'reason':state['reason'] or 'expired','automatic_restored':None,'mode':None}
        finally:
            for source in sources:
                context_source=GLib.main_context_default().find_source_by_id(source)
                if context_source is not None and not context_source.is_destroyed():GLib.source_remove(source)
            self.connection.signal_unsubscribe(subscription)


def hardware_only(client,name,args,apply=False,expected_sha256=None):
    """Service call for exports whose choice the client must record as the user
    (`client_persistence`); result shape matches remembered_controls."""
    import remembered_controls
    command={'WMISetQuietFan':'profile','WMISetBatteryHealthToUser':'charge-limit'}[name]
    value=args['profile'] if command=='profile' else args['percent']
    def apply_call():
        result=client.call(name,args,apply,expected_sha256)
        persistence=result.pop('client_persistence',None) if isinstance(result,dict) else None
        if isinstance(result,dict):result.pop('remembered',None)
        if persistence!={'field':remembered_controls.FIELDS[command],'value':value}:
            raise OSError(errno.EPROTO,'Privileged service did not return the expected client persistence request.')
        return result
    return remember_as_user(client,command,value,apply_call)


def remember_as_user(client,command,value,apply_call):
    """Apply a setting through the service, then record the choice as the user,
    with the same checks, recovery and result as remembered_controls."""
    import remembered_controls
    import user_preferences
    field=remembered_controls.FIELDS[command];path=remembered_controls.PATHS[command]
    user_preferences.validate_value(field,value)
    preferences=user_preferences.read(prepare=True)  # Fail invalid ownership/configuration before hardware.
    before_identity=remembered_controls.identity(path)
    result=apply_call()
    if result.get('after')!=str(value) or before_identity!=remembered_controls.identity(path):
        raise remembered_controls.ControlError(errno.EAGAIN,'Hardware identity/readback changed; user choice was not stored.',{'hardware':result,'remembered':False})
    try:after=user_preferences.remember(field,value,preferences['revision'])
    except OSError as error:
        try:current=user_preferences.read()
        except OSError:current=None
        if current is not None and current['values'].get(field)==value:
            return {**result,'remembered':True,'preferences':current,'persistence_readback_recovered':True}
        detail={'hardware':result,'remembered':False,'hardware_restored':False,'persistence_errno':error.errno}
        unchanged=current is not None and current['revision']==preferences['revision']
        if getattr(error,'committed',None) is False and unchanged and error.errno!=errno.EAGAIN:
            try:
                if remembered_controls.identity(path)==before_identity and path.read_text().strip()==str(value):
                    if result['before']!=str(value):
                        previous=result['before'] if command=='profile' else int(result['before'])
                        client.control(command,{'value':previous})
                    detail['hardware_restored']=path.read_text().strip()==result['before']
            except (OSError,RuntimeError,ValueError):pass
        raise remembered_controls.ControlError(error.errno or errno.EIO,'User choice could not be saved; inspect the control result and current setting.',detail) from None
    return {**result,'remembered':True,'preferences':after}


def service_call(name,args,apply=False,expected_sha256=None,interactive=False,client=None):
    """Route one export to the service; same value or error as the direct path."""
    client=client or ServiceClient(interactive=interactive,timeout_ms=None if interactive else BRIDGE_TIMEOUT_MS)
    if name in ('WMISetQuietFan','WMISetBatteryHealthToUser'):return hardware_only(client,name,args,apply,expected_sha256)
    return client.call(name,args,apply,expected_sha256)


def sudo_path():
    import linux_services
    return linux_services.system_tool('sudo')


def sudo_fallback(command):
    """Explicit opt-in only: plain interactive sudo, no stored credential."""
    return subprocess.run([sudo_path(),'--',*command],check=False).returncode
