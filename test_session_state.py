# SPDX-License-Identifier: GPL-2.0-only
import errno
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import desktop_windows
import session_state as p


class Boolean(int):pass


class RemoteError(Exception):
    def __init__(self,name):self.name=name
    def get_dbus_name(self):return self.name


class SessionTests(unittest.TestCase):
    def query(self,value=False,version='3',owners=(':1.42',':1.42'),uid=None,error=None,exe='/usr/bin/gnome-shell',pids=(4242,4242)):
        obj=SimpleNamespace(GetVersion=mock.Mock(return_value=version),GetNumLock=mock.Mock(return_value=value))
        bus=SimpleNamespace(get_object=mock.Mock(return_value=obj))
        calls=[];owner_iter=iter(owners);pid_iter=iter(pids)
        def manager(dest,path,interface,method,signature,args,timeout):
            calls.append((method,args,timeout))
            if error:raise RemoteError(error)
            if method=='GetConnectionUnixProcessID':return next(pid_iter)
            return next(owner_iter) if method=='GetNameOwner' else os.geteuid() if uid is None else uid
        bus.call_blocking=manager
        dbus=SimpleNamespace(SessionBus=mock.Mock(return_value=bus),DBusException=RemoteError,Boolean=Boolean)
        with tempfile.TemporaryDirectory() as temp,mock.patch.object(desktop_windows,'PROC',Path(temp)),mock.patch.dict(os.environ,{'DBUS_SESSION_BUS_ADDRESS':'unix:path=/synthetic'}),mock.patch.dict(sys.modules,{'dbus':dbus}):
            (Path(temp)/'4242').mkdir();(Path(temp)/'4242/exe').symlink_to(exe)
            (Path(temp)/'4242/stat').write_text('4242 (gnome-shell) S '+' '.join(['1']*19)+' 777 0\n')
            r=p.report()
        return r,obj,bus,calls

    def test_real_false_and_true_from_pinned_owner_are_preserved(self):
        for value in [False,True,Boolean(0),Boolean(1)]:
            with self.subTest(value=value):
                r,obj,bus,calls=self.query(value)
                self.assertTrue(r['available']);self.assertIs(r['num_lock'],bool(value))
                bus.get_object.assert_called_once_with(':1.42',p.PATH,introspect=False)
                obj.GetNumLock.assert_called_once_with(dbus_interface=p.NAME,timeout=2)
                self.assertEqual([c[0] for c in calls],['GetNameOwner','GetConnectionUnixUser','GetConnectionUnixProcessID','GetConnectionUnixProcessID','GetNameOwner'])
                self.assertTrue(all(c[2]==2 for c in calls))

    def test_window_bridge4_preserves_logical_num_lock_transport(self):
        for value in [False,True]:
            result,*_=self.query(value,version='4')
            self.assertTrue(result['available']);self.assertIs(result['num_lock'],value)

    def test_unknown_owner_and_unsupported_bridge_do_not_activate_or_query_toggle(self):
        for options,code in [({'owners':('wrong',)},errno.EPROTO),({'version':'1'},errno.EOPNOTSUPP),({'version':'2'},errno.EOPNOTSUPP),({'version':'5'},errno.EOPNOTSUPP),({'version':2},errno.EPROTO),({'uid':os.geteuid()+1},errno.EACCES),({'uid':True},errno.EACCES)]:
            with self.subTest(options=options):
                r,obj,bus,calls=self.query(**options)
                self.assertFalse(r['available']);self.assertIsNone(r['num_lock']);self.assertEqual(r['errno'],code)
                obj.GetNumLock.assert_not_called()
                self.assertFalse(any('Start' in c[0] for c in calls))

    def test_same_user_impostor_owner_is_not_trusted(self):
        for options,code in [({'exe':'/usr/bin/python3'},errno.EACCES),({'pids':(4243,)},errno.EACCES),
                             ({'pids':(4242,4243)},errno.EAGAIN),({'pids':(True,)},errno.EPROTO),({'pids':(0,)},errno.EPROTO)]:
            with self.subTest(options=options):
                r,obj,bus,calls=self.query(True,**options)
                self.assertFalse(r['available']);self.assertIsNone(r['num_lock']);self.assertEqual(r['errno'],code)
                obj.GetVersion.assert_not_called();obj.GetNumLock.assert_not_called();bus.get_object.assert_not_called()

    def test_missing_and_error_providers_remain_unavailable(self):
        for suffix,code in [('NameHasNoOwner',errno.ENODEV),('ServiceUnknown',errno.ENODEV),('AccessDenied',errno.EACCES),('NoReply',errno.ETIMEDOUT),('UnknownMethod',errno.EOPNOTSUPP),('Failed',errno.EIO)]:
            with self.subTest(suffix=suffix):
                r,obj,bus,calls=self.query(error='org.freedesktop.DBus.Error.'+suffix)
                self.assertFalse(r['available']);self.assertIsNone(r['num_lock']);self.assertEqual(r['errno'],code)
                obj.GetNumLock.assert_not_called()

    def test_integer_string_null_and_owner_change_are_not_successful_boolean(self):
        for value in [0,1,'false',None]:
            with self.subTest(value=value):
                r,*_=self.query(value=value);self.assertFalse(r['available']);self.assertEqual(r['errno'],errno.EPROTO)
        r,*_=self.query(owners=(':1.42',':1.43'));self.assertIsNone(r['num_lock']);self.assertEqual(r['errno'],errno.EAGAIN)

    def test_absent_or_autolaunch_bus_does_not_open_a_new_session(self):
        for address in ['', 'autolaunch:', 'tcp:host=localhost', 'unix:path=/missing;autolaunch:']:
            with self.subTest(address=address),mock.patch.dict(os.environ,{'DBUS_SESSION_BUS_ADDRESS':address}),mock.patch.dict(sys.modules,{'dbus':None}):
                r=p.report()
            self.assertFalse(r['available']);self.assertEqual(r['errno'],errno.ENODEV)

    def test_missing_bindings_preserve_unavailable_state(self):
        with mock.patch.dict(os.environ,{'DBUS_SESSION_BUS_ADDRESS':'unix:path=/synthetic'}),mock.patch.dict(sys.modules,{'dbus':None}):
            r=p.report()
        self.assertFalse(r['available']);self.assertIsNone(r['num_lock']);self.assertEqual(r['errno'],errno.ENODEV)


if __name__=='__main__':unittest.main()
