# SPDX-License-Identifier: GPL-2.0-only
import errno
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import api_bridge
import compat
import hardware_memory as p
import linux_services


def frame(size=2048,length=0x5c,handle=1):
    data=bytearray(length);data[:2]=bytes([17,length]);struct.pack_into('<H',data,2,handle)
    struct.pack_into('<H',data,0xc,size);data[0x10]=1;data[0x11]=2
    if length>=0x17:struct.pack_into('<H',data,0x15,6400)
    if length>=0x18:data[0x17]=3
    if length>=0x1b:data[0x1a]=4
    if length>=0x22:struct.pack_into('<H',data,0x20,4800)
    return bytes(data)+b'DIMM0\0BANK0\0Example maker\0Example part\0PRIVATE SERIAL NOT EXPORTED\0\0'


def modify(raw,offset,value,width=2):
    data=bytearray(raw);data[offset:offset+width]=value.to_bytes(width,'little');return bytes(data)


def put(root,index,raw):
    path=root/f'17-{index}';path.mkdir();(path/'raw').write_bytes(raw);return path


class MemoryTests(unittest.TestCase):
    def test_original_module_fields_and_no_serial_or_os_usage(self):
        row=p.decode(frame())
        self.assertEqual(row['capacity_bytes'],2*1024**3)
        self.assertEqual((row['manufacturer'],row['part_number'],row['locator']),('Example maker','Example part','DIMM0'))
        self.assertEqual((row['speed_mt_s'],row['configured_speed_mt_s'],row['speed_units']),(6400,4800,'MT/s'))
        self.assertNotIn('PRIVATE',str(row));self.assertNotIn('serial',row)

    def test_capacity_kib_mib_extended_empty_and_unknown(self):
        for size,value in [(1,1024**2),(0x8001,1024),(0,0),(32766,32766*1024**2)]:
            self.assertEqual(p.decode(frame(size))['capacity_bytes'],value)
        row=p.decode(modify(frame(0x7fff),0x1c,32768,4));self.assertEqual(row['capacity_bytes'],32*1024**3)
        self.assertFalse(p.decode(frame(0))['populated'])
        row=p.decode(frame(0xffff));self.assertTrue(row['populated']);self.assertIsNone(row['capacity_bytes'])
        self.assertEqual(row['field_errors']['capacity_bytes']['errno'],errno.ENODATA)

    def test_invalid_extended_size_is_not_fabricated_capacity(self):
        for raw in [frame(0x8000),modify(frame(0x7fff),0x1c,0x80008000,4),
                    modify(frame(0x7fff),0x1c,100,4),frame(0x7fff,length=0x1b)]:
            self.assertIsNone(p.decode(raw)['capacity_bytes'])

    def test_extended_rates_sentinels_and_no_maximum_rate_fallback(self):
        raw=modify(modify(frame(),0x15,0xffff),0x54,70000,4)
        raw=modify(modify(raw,0x20,0xffff),0x58,68000,4)
        row=p.decode(raw);self.assertEqual((row['speed_mt_s'],row['configured_speed_mt_s']),(70000,68000))
        for raw in [modify(frame(),0x20,0),modify(frame(length=0x22),0x20,0xffff),
                    modify(modify(frame(),0x20,0xffff),0x58,4000,4),
                    modify(modify(frame(),0x20,0xffff),0x58,0x80000001,4)]:
            self.assertIsNone(p.decode(raw)['configured_speed_mt_s'])
            self.assertEqual(p.decode(raw)['speed_mt_s'],6400)

    def test_malformed_framing_is_rejected(self):
        for raw in [b'',frame()[:-1],frame()+b'extra',modify(frame(),0,16,1),
                    modify(frame(),1,0x14,1),b'\x11\xff'+bytes(30),bytes(65537)]:
            with self.subTest(length=len(raw)),self.assertRaises(OSError):p.decode(raw)

    def test_optional_string_errors_do_not_erase_capacity(self):
        for raw,code in [(modify(frame(),0x17,9,1),errno.EPROTO),(modify(frame(),0x17,0,1),errno.ENODATA),
                         (frame().replace(b'Example maker',b'Unknown'),errno.ENODATA),
                         (frame().replace(b'Example maker',b'bad\x01maker'),errno.EPROTO),
                         (frame().replace(b'Example maker',b'bad\xffmaker'),errno.EPROTO)]:
            row=p.decode(raw);self.assertIsNone(row['manufacturer']);self.assertEqual(row['capacity_bytes'],2*1024**3)
            self.assertEqual(row['field_errors']['manufacturer']['errno'],code)
        old=p.decode(frame(length=0x15));self.assertIsNone(old['manufacturer']);self.assertEqual(old['locator'],'DIMM0')

    def test_installed_total_and_independent_field_exports(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);put(root,0,frame());put(root,1,frame(0,handle=2));put(root,2,frame(4096,handle=3))
            report=p.report(root)
        self.assertEqual(report['installed_capacity_bytes'],6*1024**3);self.assertEqual(report['populated_devices'],2)
        with mock.patch.object(p,'report',return_value=report),mock.patch('os.geteuid',return_value=0):
            self.assertEqual(api_bridge.call({'name':'WMIGetMemInfo'}),report)
            self.assertEqual(api_bridge.call({'name':'WMIGetMemSize'}),6*1024**3)
            self.assertEqual([x['value'] for x in api_bridge.call({'name':'WMIGetMemFrequency'})],[4800,4800])
            self.assertEqual(len(api_bridge.call({'name':'WMIGetMemModel'})),2)
            self.assertEqual(len(api_bridge.call({'name':'WMIGetMemManufacture'})),2)

    def test_unknown_or_unreadable_record_withholds_total_preserves_known_data(self):
        for broken in ['unknown','missing','bad']:
            with self.subTest(broken=broken),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);put(root,0,frame());bad=put(root,1,frame(0xffff,handle=2))
                if broken=='missing':(bad/'raw').unlink()
                if broken=='bad':(bad/'raw').write_bytes(b'bad')
                report=p.report(root)
            self.assertIsNone(report['installed_capacity_bytes']);self.assertFalse(report['capacity_available'])
            self.assertEqual(report['known_capacity_bytes'],2*1024**3);self.assertEqual(len(report['devices']),2)
            with mock.patch.object(p,'report',return_value=report):
                with self.assertRaises(OSError) as caught:p.call('WMIGetMemSize',{})
                self.assertEqual(caught.exception.errno,errno.ENODATA)
                if broken!='unknown':self.assertFalse(p.call('WMIGetMemModel',{})[1]['available'])

    def test_duplicate_handles_are_not_double_counted(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);put(root,0,frame());put(root,1,frame());report=p.report(root)
        self.assertIsNone(report['installed_capacity_bytes']);self.assertEqual(report['known_capacity_bytes'],0)
        self.assertTrue(all(r['errno']==errno.EPROTO for r in report['devices']))

    def test_record_change_or_read_failure_on_recheck_withholds_total(self):
        for failure in [False,True]:
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);put(root,0,frame())
                second=OSError(errno.EACCES,'denied') if failure else frame(4096)
                with mock.patch.object(p,'read',side_effect=[frame(),second]):report=p.report(root)
            self.assertIsNone(report['installed_capacity_bytes']);self.assertFalse(report['devices'][0]['available'])

    def test_census_change_is_not_partial_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=put(root,0,frame())
            with mock.patch.object(p,'paths',side_effect=[[path],[]]),self.assertRaises(OSError) as caught:p.report(root)
        self.assertEqual(caught.exception.errno,errno.EAGAIN)

    def test_empty_census_or_only_empty_slots_is_not_installed_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with self.assertRaises(OSError):p.report(root)
            put(root,0,frame(0));report=p.report(root)
        self.assertIsNone(report['installed_capacity_bytes']);self.assertEqual(report['populated_devices'],0)

    def test_argument_and_privilege_checks_precede_memory_io(self):
        with mock.patch.object(p,'report',side_effect=AssertionError('unexpected I/O')):
            for name in p.NAMES:
                self.assertTrue(compat.needs_root(name,{}))
                with self.assertRaises(ValueError):api_bridge.call({'name':name,'args':{'unused':True}})
                with mock.patch('os.geteuid',return_value=1000),self.assertRaises(PermissionError) as caught:api_bridge.call({'name':name})
                self.assertEqual(caught.exception.errno,errno.EACCES)
                with self.assertRaises(ValueError):linux_services.call(name,{'unused':True})


if __name__=='__main__':unittest.main()
