# SPDX-License-Identifier: GPL-2.0-only
import errno
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import auth


def gi_or_skip():
    try:return auth._gi()
    except (ImportError,ValueError):raise unittest.SkipTest('python3-gi unavailable') from None


class RetiredSecretServiceRouteTests(unittest.TestCase):
    def test_module_has_no_keyring_or_password_route(self):
        source=Path(auth.__file__).read_text()
        for word in ('secretstorage','get_secret','sudo\',\'-S','-S\''):self.assertNotIn(word,source)
        self.assertFalse(hasattr(auth,'elevate'));self.assertFalse(hasattr(auth,'configuration'))

    def test_fallback_is_plain_interactive_sudo_without_input(self):
        poisoned=mock.MagicMock(side_effect=AssertionError('keyring must never be used'))
        with mock.patch.dict(sys.modules,{'secretstorage':poisoned}),mock.patch.object(auth.subprocess,'run') as run,\
             mock.patch.object(auth,'sudo_path',return_value='/usr/bin/sudo'):
            run.return_value.returncode=0
            self.assertEqual(auth.sudo_fallback(['/usr/bin/python3','tool.py']),0)
        self.assertEqual(run.call_args.args[0],['/usr/bin/sudo','--','/usr/bin/python3','tool.py'])
        self.assertNotIn('input',run.call_args.kwargs);self.assertNotIn('stdin',run.call_args.kwargs)
        poisoned.assert_not_called()

    def test_existing_auth_json_gets_one_line_notice_and_is_never_read_or_removed(self):
        with tempfile.TemporaryDirectory() as temp,mock.patch.dict(os.environ,{'XDG_CONFIG_HOME':temp}):
            stream=io.StringIO();self.assertFalse(auth.deprecated_auth_notice(stream));self.assertEqual(stream.getvalue(),'')
            p=Path(temp)/'zenbook-hardware/auth.json';p.parent.mkdir();p.write_text('{"secret_service_attributes":{}}');p.chmod(0)
            with mock.patch.object(Path,'read_text',side_effect=AssertionError('auth.json must not be read')),\
                 mock.patch('builtins.open',side_effect=AssertionError('auth.json must not be opened')):
                self.assertTrue(auth.deprecated_auth_notice(stream))
            self.assertEqual(len(stream.getvalue().splitlines()),1);self.assertIn('ignored',stream.getvalue())
            self.assertTrue(p.exists());p.chmod(0o600);self.assertEqual(p.read_text(),'{"secret_service_attributes":{}}')


class EnvelopeAndErrorTests(unittest.TestCase):
    def test_envelope_round_trip_preserves_errno_message_and_detail_fields(self):
        self.assertEqual(auth.decode_envelope('{"ok":true,"result":{"a":1}}'),{'a':1})
        with self.assertRaises(auth.RemoteError) as caught:
            auth.decode_envelope('{"ok":false,"error":{"errno":11,"message":"m","control":{"x":1},"configuration_committed":null}}')
        error=caught.exception
        self.assertEqual((error.errno,str(error),error.control_result,error.committed),(11,'m',{'x':1},None))
        with self.assertRaises(auth.RemoteError) as caught:auth.decode_envelope('{"ok":false,"error":{"errno":19,"message":"[Errno 19] gone"}}')
        self.assertEqual(str(caught.exception),'[Errno 19] gone')
        self.assertFalse(hasattr(caught.exception,'control_result'));self.assertFalse(hasattr(caught.exception,'committed'))
        for bad in ('x','[]','{"ok":false,"error":{"errno":"1","message":"m"}}'):
            with self.assertRaises(OSError) as caught:auth.decode_envelope(bad)
            self.assertEqual(caught.exception.errno,errno.EPROTO)

    def test_dbus_error_mapping(self):
        Gio,GLib=gi_or_skip()
        client=auth.ServiceClient(connection=object())
        def mapped(name):return client.map_error(Gio.DBusError.new_for_dbus_error(name,'detail'))
        busy=mapped('org.zenbook.Hardware1.Error.EBUSY');self.assertEqual((busy.errno,str(busy)),(errno.EBUSY,'detail'))
        for name in ('org.freedesktop.PolicyKit1.Error.NotAuthorized','org.freedesktop.DBus.Error.AccessDenied'):
            error=mapped(name);self.assertIsInstance(error,PermissionError);self.assertNotIsInstance(error,auth.ServiceUnavailable)
            self.assertEqual(error.errno,errno.EACCES)
        for name in ('org.freedesktop.DBus.Error.ServiceUnknown','org.freedesktop.DBus.Error.NameHasNoOwner','org.freedesktop.DBus.Error.Spawn.ChildExited'):
            error=mapped(name);self.assertIsInstance(error,auth.ServiceUnavailable);self.assertEqual(error.errno,errno.EACCES)
            self.assertIn('privileged service unavailable; run with sudo',str(error))
        self.assertEqual(mapped('org.freedesktop.DBus.Error.NoReply').errno,errno.ETIMEDOUT)
        self.assertEqual(mapped('com.example.Other').errno,errno.EIO)
        self.assertEqual(client.map_error(GLib.Error.new_literal(Gio.io_error_quark(),'t',Gio.IOErrorEnum.TIMED_OUT)).errno,errno.ETIMEDOUT)

    def test_bus_address_only_accepts_unix_override_for_unprivileged_callers(self):
        with mock.patch.dict(os.environ,{'DBUS_SYSTEM_BUS_ADDRESS':'unix:path=/tmp/private'}):
            with mock.patch.object(auth.os,'geteuid',return_value=1000):self.assertEqual(auth.bus_address(),'unix:path=/tmp/private')
            with mock.patch.object(auth.os,'geteuid',return_value=0):self.assertEqual(auth.bus_address(),auth.DEFAULT_SYSTEM_BUS)
        with mock.patch.dict(os.environ,{'DBUS_SYSTEM_BUS_ADDRESS':'tcp:host=example,port=1'}),mock.patch.object(auth.os,'geteuid',return_value=1000):
            self.assertEqual(auth.bus_address(),auth.DEFAULT_SYSTEM_BUS)

    def test_client_refuses_to_route_from_inside_the_service(self):
        main=mock.Mock(__file__='/usr/local/lib/asus-healthytable/x/service/zenbook_hardwared.py')
        with mock.patch.dict(sys.modules,{'__main__':main}),self.assertRaises(PermissionError):auth.ServiceClient(connection=object())

    def test_missing_gi_is_reported_as_unavailable_service(self):
        with mock.patch.object(auth,'_gi',side_effect=ImportError('gi')),self.assertRaises(auth.ServiceUnavailable):
            auth.ServiceClient(connection=object())

    def test_interaction_flag_only_when_requested(self):
        Gio,GLib=gi_or_skip()
        calls=[]
        class Bus:
            def call_sync(self,*a):calls.append(a);return GLib.Variant('(s)',('{"ok":true,"result":1}',))
        auth.ServiceClient(interactive=False,connection=Bus()).call('GetXgmFw',{})
        auth.ServiceClient(interactive=True,connection=Bus()).call('GetXgmFw',{})
        self.assertEqual([int(c[6]) for c in calls],[0,int(Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION)])
        self.assertEqual(calls[0][:4],(auth.BUS_NAME,auth.OBJECT_PATH,auth.INTERFACE,'Call'))
        self.assertEqual(calls[0][4].unpack(),('GetXgmFw','{}',False,''))
        self.assertGreater(calls[1][7],calls[0][7])
        with mock.patch.dict(os.environ,{'DISPLAY':'','WAYLAND_DISPLAY':''}),mock.patch.object(sys,'stdin',io.StringIO()):
            self.assertFalse(auth.interactive_default())


if __name__=='__main__':unittest.main()
