# SPDX-License-Identifier: GPL-2.0-only
import errno
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import api_bridge
import platform_metadata as platform


def oem(strings,count=None):
    encoded=[s if isinstance(s,bytes) else s.encode() for s in strings]
    return bytes([11,5,1,0,len(strings) if count is None else count])+b'\0'.join(encoded)+b'\0\0'


class PlatformMetadataTests(unittest.TestCase):
    def test_oem_is_exact_fifth_string_not_sku_or_other_90_match(self):
        self.assertEqual(platform.decode_fifth_oem(oem(['90-first','second','third','fourth','fifth','90-sixth'])),'fifth')
        for raw,code in [(oem(['only']),errno.ENODATA),(oem(['a']*5,count=6),errno.EPROTO),
                         (oem(['a']*4+[b'\xff']),errno.EPROTO),(oem(['a']*5)+b'extra',errno.EPROTO)]:
            with self.subTest(code=code),self.assertRaises(OSError) as error:platform.decode_fifth_oem(raw)
            self.assertEqual(error.exception.errno,code)

    def test_cached_oem_record_count_and_revision_guards(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);entry=root/'11-0';entry.mkdir();raw=entry/'raw';raw.write_bytes(oem(['a','b','c','d','fifth']))
            self.assertEqual(platform.fifth_oem(root),'fifth')
            decode=platform.decode_fifth_oem
            def changed(data):
                value=decode(data);raw.write_bytes(oem(['a','b','c','d','later']));return value
            with mock.patch.object(platform,'decode_fifth_oem',side_effect=changed),self.assertRaises(OSError) as error:platform.fifth_oem(root)
            self.assertEqual(error.exception.errno,errno.EAGAIN)
            (root/'11-1').mkdir()
            with self.assertRaises(OSError) as error:platform.fifth_oem(root)
            self.assertEqual(error.exception.errno,errno.EOPNOTSUPP)

    def test_uuid_placeholders_serial_placeholders_and_permissions_are_typed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'product_uuid';p.write_text('AABBCCDD-1234-5678-9ABC-123456789ABC\n')
            self.assertEqual(platform.identifier('WMIGetBoardUUID',root),'aabbccdd-1234-5678-9abc-123456789abc')
            for value in ['00000000-0000-0000-0000-000000000000','ffffffff-ffff-ffff-ffff-ffffffffffff','bad']:
                p.write_text(value)
                with self.assertRaises(OSError):platform.identifier('WMIGetBoardUUID',root)
            (root/'product_serial').write_text('To Be Filled By O.E.M.')
            with self.assertRaises(OSError) as error:platform.identifier('WMIGetSN',root)
            self.assertEqual(error.exception.errno,errno.ENODATA)
            with mock.patch.object(platform,'text',side_effect=PermissionError(errno.EACCES,'Denied')),self.assertRaises(OSError) as error:platform.identifier('WMIGetSN',root)
            self.assertEqual(error.exception.errno,errno.EACCES)

    def test_chassis_preserves_code_and_original_categories(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'chassis_type'
            for code,expected in [(3,'Desktop'),(13,'Desktop'),(35,'Desktop'),(10,'Notebook'),(30,'Notebook'),(31,'Notebook'),(32,'Notebook'),(4,'unknown')]:
                p.write_text(str(code));result=platform.chassis(root)
                self.assertEqual((result['code'],result['classification']),(code,expected))

    def test_card_reader_uses_exact_cached_usb_identity_and_partial_caption(self):
        records=[{'device':'1-1','available':True,'vendor_id':'0bda','product_id':'0129','product':'Reader'},
                 {'device':'1-2','available':True,'vendor_id':'0bda','product_id':'9999','product':'Other reader'}]
        with mock.patch.object(platform.usb_inventory,'report',return_value={'all_devices':records,'enumeration_complete':True}):
            result=platform.card_reader()
        self.assertEqual([r['caption'] for r in result['readers']],['Reader'])
        records[0].update(product=None,metadata_errors={'product':{'errno':errno.EACCES,'error':'Denied'}})
        with mock.patch.object(platform.usb_inventory,'report',return_value={'all_devices':records,'enumeration_complete':True}):result=platform.card_reader()
        self.assertTrue(result['present']);self.assertFalse(result['complete'])
        self.assertEqual(result['readers'][0]['errno'],errno.EACCES)

    def test_unknown_usb_census_cannot_claim_reader_absent(self):
        with mock.patch.object(platform.usb_inventory,'report',return_value={'all_devices':[],'enumeration_complete':False}):result=platform.card_reader()
        self.assertIsNone(result['present']);self.assertFalse(result['complete'])

    def net_fixture(self,root,name,address,index,device=None):
        p=root/name;p.mkdir();(p/'address').write_text(address);(p/'ifindex').write_text(str(index))
        if device is not None:(p/'device').symlink_to(device)
        return p

    def test_mac_excludes_software_only_and_preserves_current_device_addresses(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);root=base/'net';root.mkdir();device=base/'hardware';device.mkdir()
            self.net_fixture(root,'physical','02:11:22:33:44:55',3,device)
            self.net_fixture(root,'bridge','02:aa:bb:cc:dd:ee',4)
            result=platform.physical_macs(root)
        self.assertTrue(result['complete']);self.assertEqual(result['software_interfaces_excluded'],1)
        self.assertEqual([r['interface'] for r in result['adapters']],['physical'])
        self.assertEqual(result['adapters'][0]['address'],'02:11:22:33:44:55')

    def test_mac_invalid_or_dangling_device_does_not_become_empty_success(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);root=base/'net';root.mkdir();device=base/'hardware';device.mkdir()
            self.net_fixture(root,'bad','00:00:00:00:00:00',3,device)
            self.net_fixture(root,'gone','02:11:22:33:44:55',4,base/'missing')
            result=platform.physical_macs(root)
        self.assertFalse(result['complete']);self.assertEqual(len(result['adapters']),2)
        self.assertTrue(all(not r['available'] and r['address'] is None for r in result['adapters']))

    def test_mac_interface_identity_change_withholds_value(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);root=base/'net';root.mkdir();device=base/'hardware';device.mkdir()
            p=self.net_fixture(root,'physical','02:11:22:33:44:55',3,device)
            original=platform.text;count=[0]
            def changed(path,*args):
                if path==p/'ifindex':count[0]+=1;return str(count[0]+2)
                return original(path,*args)
            with mock.patch.object(platform,'text',side_effect=changed):result=platform.physical_macs(root)
        self.assertFalse(result['complete']);self.assertEqual(result['adapters'][0]['errno'],errno.EAGAIN)

    def test_arguments_rejected_before_platform_reads(self):
        with mock.patch.object(platform,'text') as read,mock.patch.object(platform,'fifth_oem') as oem_read:
            for name in platform.NAMES:
                with self.subTest(name=name),self.assertRaises(ValueError):api_bridge.call({'name':name,'args':{'unexpected':True}})
        read.assert_not_called();oem_read.assert_not_called()


if __name__=='__main__':unittest.main()
