# SPDX-License-Identifier: GPL-2.0-only
import ctypes
import errno
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import api_bridge
import cpu_metadata as cpu


class CpuMetadataTests(unittest.TestCase):
    def fraction(self,before,after,elapsed=.1):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'stat';path.write_bytes(before);clock=[0.0]
            def wait(value):self.assertEqual(value,.1);path.write_bytes(after);clock[0]=elapsed
            return cpu.usage_fraction(path,clock=lambda:clock[0],wait=wait)

    def test_original_fraction_and_wmi_percentage_are_different_units(self):
        before=b'cpu 100 10 50 200 20 5 10 0 10 5\n'
        after=b'cpu 120 10 80 230 40 5 10 0 30 5\n'
        self.assertEqual(self.fraction(before,after),.5)
        with mock.patch.object(cpu,'usage_fraction',return_value=.5):
            self.assertEqual(api_bridge.call({'name':'CPU_ReadCPUUsage'}),.5)
            self.assertEqual(api_bridge.call({'name':'WMIGetCPUUsg'}),50)

    def test_known_idle_busy_and_older_kernel_fields_are_valid(self):
        self.assertEqual(self.fraction(b'cpu 0 0 0 0\n',b'cpu 0 0 0 10\n'),0)
        self.assertEqual(self.fraction(b'cpu 0 0 0 0\n',b'cpu 10 0 0 0\n'),1)

    def test_failed_regressed_zero_or_short_samples_are_not_fake_load(self):
        for before,after,elapsed,code in [(b'cpu 1 0 0 1\n',b'cpu 1 0 0 1\n',.1,errno.ENODATA),
                                          (b'cpu 1 0 0 1\n',b'cpu 0 0 0 2\n',.1,errno.EAGAIN),
                                          (b'cpu 1 0 0 1\n',b'cpu 2 0 0 2\n',.01,errno.EAGAIN),
                                          (b'cpu 1 0 0 1\n',b'bad\n',.1,errno.EPROTO)]:
            with self.subTest(code=code),self.assertRaises(OSError) as error:self.fraction(before,after,elapsed)
            self.assertEqual(error.exception.errno,code)

    def test_model_name_is_first_processor_property_and_missing_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'cpuinfo';path.write_text('processor: 0\nmodel name: First CPU\n\nprocessor: 1\nmodel name: Second CPU\n')
            self.assertEqual(cpu.model_name(path),'First CPU')
            path.write_text('processor: 0\n\nprocessor: 1\nmodel name: Second CPU\n')
            with self.assertRaises(OSError) as error:cpu.model_name(path)
            self.assertEqual(error.exception.errno,errno.ENODATA)

    def test_architecture_uses_original_numeric_enum(self):
        for machine,value in [('x86_64',9),('aarch64',12),('i686',0),('armv7l',5),('ppc64le',3),('ia64',6)]:
            with self.subTest(machine=machine):self.assertEqual(cpu.architecture(machine),value)
        with self.assertRaises(OSError):cpu.architecture('future-unknown')

    def test_cpuid_arguments_reject_before_library_loading(self):
        with mock.patch.object(cpu.ctypes,'CDLL') as load:
            for args in [{'leaf':-1},{'leaf':True},{'leaf':2**32},{'subleaf':1.5},{'unknown':0}]:
                with self.subTest(args=args),self.assertRaises(ValueError):api_bridge.call({'name':'CPU_ReadCpuId','args':args})
        load.assert_not_called()

    def test_native_c_cpuid_registers_match_cpu_vendor_without_driver(self):
        library=Path(__file__).parent/'build/test-libasus-healthytable.so'
        if not library.exists():self.skipTest('Run make check.')
        if platform.machine().casefold() not in ('x86_64','amd64','i386','i686'):self.skipTest('CPUID is x86 only.')
        result=cpu.cpuid(library=library.resolve())
        vendor=b''.join(result[k].to_bytes(4,'little') for k in ('ebx','edx','ecx')).decode('ascii')
        declared=next(line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('vendor_id'))
        self.assertEqual(vendor,declared)
        lib=ctypes.CDLL(str(library.resolve()));read=lib.asus_ht_cpuid
        read.argtypes=[ctypes.c_uint32,ctypes.c_uint32,ctypes.POINTER(ctypes.c_uint32)];read.restype=ctypes.c_int
        self.assertEqual(read(0,0,None),-errno.EINVAL)

    def test_missing_native_helper_does_not_substitute_cpu_description(self):
        with mock.patch.object(cpu.ctypes,'CDLL',side_effect=OSError('Absent')):
            with self.assertRaises(OSError) as error:cpu.cpuid()
        self.assertEqual(error.exception.errno,errno.EOPNOTSUPP)

    def test_disabled_child_thread_cpuid_returns_unavailable_without_a_fault(self):
        library=Path(__file__).parent/'build/test-libasus-healthytable.so'
        if not library.exists() or platform.machine().casefold() not in ('x86_64','amd64'):
            self.skipTest('Built helper and Linux x86_64 required.')
        # Only this disposable child thread changes its own CPUID permission.
        # The production helper only uses ARCH_GET_CPUID and never enables it.
        code='''import ctypes,errno,sys
lib=ctypes.CDLL(sys.argv[1]);read=lib.asus_ht_cpuid
read.argtypes=[ctypes.c_uint32,ctypes.c_uint32,ctypes.POINTER(ctypes.c_uint32)];read.restype=ctypes.c_int
libc=ctypes.CDLL(None,use_errno=True);control=libc.arch_prctl
control.argtypes=[ctypes.c_int,ctypes.c_ulong];control.restype=ctypes.c_int
words=(ctypes.c_uint32*4)(1,2,3,4)
if control(0x1012,0):raise SystemExit(77 if ctypes.get_errno() in (errno.ENODEV,errno.EINVAL) else 1)
try:result=read(0,0,words)
finally:control(0x1012,1)
assert result==-errno.EOPNOTSUPP and list(words)==[0,0,0,0]
'''
        result=subprocess.run([sys.executable,'-c',code,str(library.resolve())],capture_output=True,text=True,timeout=5)
        if result.returncode==77:self.skipTest('Kernel cannot disable CPUID for a thread.')
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
