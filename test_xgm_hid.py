# SPDX-License-Identifier: GPL-2.0-only
import errno
import struct
import unittest
from unittest import mock
import xgm_hid


DESCRIPTOR=bytes.fromhex('0631ff0976a101c0')
def metadata(operation,data,descriptor=DESCRIPTOR):
    if operation==0x80084803:data[:]=struct.pack('=IHH',3,0x0b05,0x1970)
    elif operation==0x80044801:data[:]=struct.pack('=I',len(descriptor))
    elif operation==0x90044802:data[4:4+len(descriptor)]=descriptor
    else:return False
    return True


class XgmTests(unittest.TestCase):
    def test_only_recovered_vendor_application_collection_matches(self):
        self.assertTrue(xgm_hid.collection_matches(bytes.fromhex('0631ff0976a101c0')))
        self.assertFalse(xgm_hid.collection_matches(bytes.fromhex('05010906a101c0')))
        self.assertFalse(xgm_hid.collection_matches(bytes.fromhex('0631ff0975a101c0')))

    def test_global_push_pop_and_extended_usage(self):
        self.assertTrue(xgm_hid.collection_matches(bytes.fromhex('0501a40631ffb40b760031ffa101c0')))
        with self.assertRaises(ValueError):
            xgm_hid.collection_matches(b'\xb4')

    def test_truncated_descriptors_fail_closed(self):
        for raw in [b'\x06', b'\xfe\x08\x00\x01',DESCRIPTOR+b'\x06',b'\xc0',DESCRIPTOR[:-1]]:
            with self.assertRaises(ValueError):
                xgm_hid.collection_matches(raw)

    def test_exact_read_query_and_reply_decoding(self):
        def ioctl(fd, operation, data, mutate):
            self.assertEqual(fd,7)
            if metadata(operation,data):return 0
            self.assertEqual(len(data), 64)
            if operation == xgm_hid.feature_ioctl(True, 64):
                self.assertEqual(data[:2], b'\x5a\xa0')
                self.assertEqual(data[2:], bytes(62))
            else:
                data[:2] = b'\x5a\xa0'
                data[2:6] = b'0102'
            return 64
        with mock.patch.object(xgm_hid.os, 'open', return_value=7), mock.patch.object(xgm_hid.os, 'close') as close, \
             mock.patch.object(xgm_hid.fcntl, 'ioctl', side_effect=ioctl), mock.patch.object(xgm_hid.time, 'sleep'):
            self.assertEqual(xgm_hid.query('/dev/hidraw7')['firmware'], '0102')
        close.assert_called_once_with(7)

    def test_original_firmware_boundary_excludes_byte33_and_requires_complete_report(self):
        for size in (64,0,32,33,34,63,65):
            def ioctl(fd,operation,data,mutate):
                if metadata(operation,data):return 0
                if operation==xgm_hid.feature_ioctl(True,64):return 64
                data[:2]=b'\x5a\xa0';data[2:33]=b'A'*31;data[33]=ord('Z')
                return size
            with mock.patch.object(xgm_hid.os,'open',return_value=7),mock.patch.object(xgm_hid.os,'close'), \
                 mock.patch.object(xgm_hid.fcntl,'ioctl',side_effect=ioctl),mock.patch.object(xgm_hid.time,'sleep'):
                if size==64:
                    result=xgm_hid.query('/dev/hidraw7');self.assertEqual(result['firmware'],'A'*31)
                    self.assertEqual(result['firmware_payload_bytes'],31);self.assertEqual(bytes.fromhex(result['firmware_raw_hex']),b'A'*31)
                else:
                    with self.assertRaises(OSError):xgm_hid.query('/dev/hidraw7')

    def test_malformed_response_closes_handle(self):
        with mock.patch.object(xgm_hid.os, 'open', return_value=7), mock.patch.object(xgm_hid.os, 'close') as close, \
             mock.patch.object(xgm_hid.fcntl, 'ioctl', return_value=64), mock.patch.object(xgm_hid.time, 'sleep'):
            with self.assertRaises(OSError):
                xgm_hid.query('/dev/hidraw7')
        close.assert_called_once_with(7)

    def test_absent_hardware_is_not_a_fake_success(self):
        with mock.patch.object(xgm_hid, 'candidates', return_value=[]):
            with self.assertRaises(OSError) as error:
                xgm_hid.firmware()
        self.assertEqual(error.exception.errno, errno.ENODEV)

    def test_matching_vendor_with_wrong_open_collection_never_receives_feature_command(self):
        operations=[]
        def ioctl(fd,operation,data,mutate):
            operations.append(operation)
            self.assertTrue(metadata(operation,data,bytes.fromhex('05010906a101c0')),'No feature command may be sent')
            return 0
        with mock.patch.object(xgm_hid.os,'open',return_value=7),mock.patch.object(xgm_hid.os,'close'), \
             mock.patch.object(xgm_hid.fcntl,'ioctl',side_effect=ioctl):
            with self.assertRaises(OSError) as error:xgm_hid.query('/dev/hidraw7')
        self.assertEqual(error.exception.errno,errno.ENODEV)
        self.assertEqual(operations,[0x80084803,0x80044801,0x90044802])

    def test_descriptor_size_change_truncation_and_ioctl_fault_precede_feature(self):
        for kind in ('zero','oversize','changed','truncated','fault'):
            def ioctl(fd,operation,data,mutate):
                self.assertIn(operation,(0x80084803,0x80044801,0x90044802))
                if kind=='fault':raise OSError(errno.EIO,'HID read failed')
                metadata(operation,data)
                if operation==0x80044801 and kind in ('zero','oversize'):data[:]=struct.pack('=I',0 if kind=='zero' else 4097)
                if operation==0x90044802:
                    if kind=='changed':data[:4]=struct.pack('=I',len(DESCRIPTOR)+1)
                    elif kind=='truncated':data[4+len(DESCRIPTOR)-1]=6
                return 0
            with mock.patch.object(xgm_hid.os,'open',return_value=7),mock.patch.object(xgm_hid.os,'close') as close, \
                 mock.patch.object(xgm_hid.fcntl,'ioctl',side_effect=ioctl):
                with self.assertRaises(OSError):xgm_hid.query('/dev/hidraw7')
            close.assert_called_once_with(7)

    def test_reused_hidraw_number_never_receives_a_feature_command(self):
        def ioctl(fd,operation,data,mutate):
            self.assertEqual(operation,0x80084803)
            data[:]=struct.pack('=IHH',3,0x1234,0x5678)
        with mock.patch.object(xgm_hid.os,'open',return_value=7),mock.patch.object(xgm_hid.os,'close'), \
             mock.patch.object(xgm_hid.fcntl,'ioctl',side_effect=ioctl) as call:
            with self.assertRaises(OSError):xgm_hid.query('/dev/hidraw7')
        self.assertEqual(call.call_count,1)


if __name__ == '__main__':
    unittest.main()
