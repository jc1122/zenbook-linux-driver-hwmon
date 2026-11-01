# SPDX-License-Identifier: GPL-2.0-only
import ctypes
import struct
import stat
from types import SimpleNamespace
import unittest
from unittest import mock
import usb_activity


class Poll:
    def register(self,*args):pass
    def poll(self,*args):return [(9,1)]


class UsbActivityTests(unittest.TestCase):
    def capture(self,kind=3,dropped=0,pending=0,iso_errors=0,limit=20000,ready=True,mode=stat.S_IFCHR,boot_elapsed=.3):
        calls=0
        def ioctl(fd,operation,arg,*args):
            nonlocal calls
            if operation==usb_activity.GET_STATS:
                calls+=1;arg[:]=struct.pack('=II',0,0) if calls==1 else struct.pack('=II',pending,dropped);return
            self.assertIsNone(arg.data);self.assertEqual(arg.alloc,0)
            raw=bytearray(64);raw[8]=ord('C');raw[9]=kind
            struct.pack_into('=I',raw,32,1024);struct.pack_into('=i',raw,40,iso_errors)
            ctypes.memmove(arg.header,bytes(raw),64)
        poll=Poll()
        with mock.patch.object(usb_activity.Path,'exists',return_value=True),mock.patch.object(usb_activity.os,'open',return_value=9), \
             mock.patch.object(usb_activity.os,'close') as close,mock.patch.object(usb_activity.os,'fstat',return_value=SimpleNamespace(st_mode=mode)), \
             mock.patch.object(usb_activity.select,'poll',return_value=poll),mock.patch.object(poll,'poll',return_value=[(9,1)] if ready else []), \
             mock.patch.object(usb_activity.fcntl,'ioctl',side_effect=ioctl),mock.patch.object(usb_activity,'MAX_EVENTS',limit), \
             mock.patch.object(usb_activity.time,'monotonic',side_effect=[0,0,.01,.3,.3]), \
             mock.patch.object(usb_activity.time,'clock_gettime',side_effect=[100,100+boot_elapsed]):
            try:return usb_activity.sample()
            finally:close.assert_called_once_with(9)
    def test_real_elapsed_interval_and_known_empty_capture(self):
        r=self.capture(ready=False);self.assertFalse(r['active']);self.assertTrue(r['capture_complete']);self.assertEqual(r['bytes'],0)
        self.assertEqual(r['sample_seconds'],.3);self.assertEqual(r['requested_seconds'],.2)
    def test_drops_backlog_and_event_cap_cannot_be_false_inactivity_or_exact_bytes(self):
        for args in [{'dropped':1},{'pending':1},{'limit':1}]:
            for kind in [1,3]:
                r=self.capture(kind=kind,**args);self.assertFalse(r['capture_complete']);self.assertIsNone(r['bytes'])
                self.assertEqual(r['observed_successful_bytes'],1024 if kind==3 else 0)
                if kind==3:self.assertTrue(r['active'])
                else:self.assertIsNone(r['active'])
    def test_partial_iso_errors_remain_unknown_and_invalid_headers_raise(self):
        r=self.capture(kind=0,iso_errors=1);self.assertIsNone(r['active']);self.assertIsNone(r['bytes']);self.assertEqual(r['iso_error_completions'],1)
        with self.assertRaises(OSError) as caught:self.capture(kind=4)
        self.assertEqual(caught.exception.errno,usb_activity.errno.EPROTO)
    def test_opened_wrong_device_and_suspend_gap_fail_closed_and_close_descriptor(self):
        for args,wanted in [({'mode':stat.S_IFREG},usb_activity.errno.ENODEV),({'boot_elapsed':2},usb_activity.errno.ESTALE)]:
            with self.assertRaises(OSError) as caught:self.capture(**args)
            self.assertEqual(caught.exception.errno,wanted)

    def test_only_metadata_is_requested_and_bulk_is_counted(self):
        def ioctl(fd,operation,arg,*args):
            if operation==usb_activity.GET_STATS:
                arg[:]=struct.pack("=II",0,0);return
            self.assertIsNone(arg.data);self.assertEqual(arg.alloc,0)
            raw=bytearray(64);raw[8]=ord('C');raw[9]=3
            struct.pack_into('=I',raw,32,1024)
            ctypes.memmove(arg.header,bytes(raw),64)
        with mock.patch.object(usb_activity.Path,'exists',return_value=True), \
             mock.patch.object(usb_activity.os,'open',return_value=9), \
             mock.patch.object(usb_activity.os,'fstat',return_value=SimpleNamespace(st_mode=stat.S_IFCHR)), \
             mock.patch.object(usb_activity.time,'clock_gettime',side_effect=[100,100.3]), \
             mock.patch.object(usb_activity.os,'close') as close, \
             mock.patch.object(usb_activity.select,'poll',return_value=Poll()), \
             mock.patch.object(usb_activity.fcntl,'ioctl',side_effect=ioctl), \
             mock.patch.object(usb_activity.time,'monotonic',side_effect=[0,0,.01,.3,.3]):
            result=usb_activity.sample()
        self.assertEqual(result['bytes'],1024)
        self.assertEqual(result['payload_bytes_requested'],0)
        self.assertTrue(result['active']);close.assert_called_once_with(9)

    def test_input_interrupt_completions_are_not_counted(self):
        def ioctl(fd,operation,arg,*args):
            if operation==usb_activity.GET_STATS:
                arg[:]=struct.pack("=II",0,0);return
            raw=bytearray(64);raw[8]=ord('C');raw[9]=1
            struct.pack_into('=I',raw,32,8);ctypes.memmove(arg.header,bytes(raw),64)
        with mock.patch.object(usb_activity.Path,'exists',return_value=True), \
             mock.patch.object(usb_activity.os,'open',return_value=9), \
             mock.patch.object(usb_activity.os,'fstat',return_value=SimpleNamespace(st_mode=stat.S_IFCHR)), \
             mock.patch.object(usb_activity.time,'clock_gettime',side_effect=[100,100.3]), \
             mock.patch.object(usb_activity.os,'close'), \
             mock.patch.object(usb_activity.select,'poll',return_value=Poll()), \
             mock.patch.object(usb_activity.fcntl,'ioctl',side_effect=ioctl), \
             mock.patch.object(usb_activity.time,'monotonic',side_effect=[0,0,.01,.3,.3]):
            self.assertFalse(usb_activity.sample()['active'])

    def test_bounded_sample_duration(self):
        for seconds in (0,2,True,float("nan"),float("inf"),"0.2",None):
            with self.assertRaises(ValueError):usb_activity.sample(seconds)


    def test_root_loads_usbmon_with_absolute_modprobe_from_fixed_directories(self):
        import errno,linux_services,os,tempfile
        from pathlib import Path
        with mock.patch.object(usb_activity.Path,'exists',side_effect=[False,False]),mock.patch.object(usb_activity.os,'geteuid',return_value=0),\
             mock.patch.object(linux_services,'system_tool',return_value='/usr/sbin/modprobe') as tool,mock.patch.object(usb_activity.subprocess,'run') as run:
            with self.assertRaises(OSError):usb_activity.sample(.1)
        tool.assert_called_once_with('modprobe');self.assertEqual(run.call_args.args[0],['/usr/sbin/modprobe','usbmon'])
        with tempfile.TemporaryDirectory() as temp:
            tool_path=Path(temp)/'fake-tool';tool_path.write_text('');os.chmod(tool_path,0o755)
            with mock.patch.dict(os.environ,{'PATH':temp}):
                with self.assertRaises(FileNotFoundError) as caught:linux_services.system_tool('fake-tool')
            self.assertEqual(caught.exception.errno,errno.ENOENT)
            with mock.patch.object(linux_services,'SYSTEM_TOOL_DIRS',(temp,)):
                self.assertEqual(linux_services.system_tool('fake-tool'),str(tool_path))
                with mock.patch.object(linux_services.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='ok',stderr='')) as run:
                    linux_services.run(['fake-tool','x'])
                self.assertEqual(run.call_args.args[0],[str(tool_path),'x'])
        for bad in ('../sbin/modprobe','/usr/sbin/modprobe','',None,'-x'):
            with self.assertRaises(ValueError):linux_services.system_tool(bad)

if __name__=='__main__':unittest.main()
