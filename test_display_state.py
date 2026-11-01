# SPDX-License-Identifier: GPL-2.0-only
import errno
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import api_bridge
import display_state as p


def edid():
    data=bytearray(128);data[:8]=b'\0\xff\xff\xff\xff\xff\xff\0'
    data[8:10]=((1<<10)|(2<<5)|3).to_bytes(2,'big');data[10:12]=b'\x34\x12';data[18]=1
    data[54:59]=b'\0\0\0\xfc\0';data[59:72]=b'Test Panel\n  '
    data[127]=(-sum(data))%256;return bytes(data)


def connector(root,name,state='connected',data=None):
    path=root/name;path.mkdir();(path/'status').write_text(state);(path/'modes').write_text('1920x1080\n1280x720\n')
    (path/'edid').write_bytes(edid() if data is None else data);return path


class DisplayMetadataTests(unittest.TestCase):
    def test_valid_base_identity_and_complete_internal_only_external_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);connector(root,'card0-eDP-1');connector(root,'card0-HDMI-A-1','disconnected')
            rows=p.report(root)
            self.assertEqual(rows[0]['state'],'disconnected')
            panel=next(r for r in rows if r['internal'])
            self.assertEqual(panel['manufacturer'],'ABC');self.assertEqual(panel['product_id'],0x1234)
            self.assertEqual(panel['model'],'Test Panel');self.assertTrue(panel['edid_base_available'])
            with mock.patch.object(p,'report',return_value=rows):
                self.assertEqual(api_bridge.call({'name':'WMIGetExternMonitorNum'}),0)
                self.assertEqual(len(api_bridge.call({'name':'WMIGetLCDModel'})),1)
                self.assertEqual(api_bridge.call({'name':'WMIGetExternMonitorPropList'}),[])

    def test_unreadable_external_is_not_disconnected_or_exact_count(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);connector(root,'card0-eDP-1');bad=connector(root,'card0-HDMI-A-1');(bad/'status').unlink()
            rows=p.report(root)
        with mock.patch.object(p,'report',return_value=rows):
            with self.assertRaises(OSError) as error:api_bridge.call({'name':'WMIGetExternMonitorNum'})
            self.assertEqual(error.exception.errno,errno.ENOENT)
            external=api_bridge.call({'name':'WMIGetExternMonitorPropList'})[0]
            self.assertFalse(external['available']);self.assertIsNone(external['state'])
            self.assertNotIn('manufacturer',external)
            self.assertTrue(api_bridge.call({'name':'WMIGetLCDModel','args':{'internal_only':True}})[0]['model_available'])

    def test_unknown_and_malformed_status_never_becomes_absence(self):
        for state,code in [('unknown',errno.ENODATA),('invalid',errno.EPROTO)]:
            with self.subTest(state=state),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);connector(root,'card0-DP-1',state);rows=p.report(root)
            self.assertFalse(rows[0]['available']);self.assertEqual(rows[0]['errno'],code)

    def test_bad_edid_does_not_invent_identity_or_erase_known_connection(self):
        valid=bytearray(edid());bad_checksum=bytes(valid[:-1])+bytes([(valid[-1]+1)%256])
        bad_version=bytearray(valid);bad_version[18]=2;bad_version[127]=0;bad_version[127]=(-sum(bad_version))%256
        for data in [b'',edid()[:80],b'x'*128,bad_checksum,bytes(bad_version)]:
            with self.subTest(length=len(data)),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);connector(root,'card0-DP-1',data=data);rows=p.report(root)
            row=rows[0];self.assertTrue(row['available']);self.assertFalse(row['edid_base_available'])
            self.assertNotIn('manufacturer',row);self.assertNotIn('model',row)
            with mock.patch.object(p,'report',return_value=rows):self.assertEqual(p.call('WMIGetExternMonitorNum',{}),1)

    def test_valid_base_is_not_blocked_by_unparsed_extension(self):
        raw=bytearray(edid());raw[126]=1;raw[127]=0;raw[127]=(-sum(raw))%256
        result=p.edid_identity(bytes(raw)+b'x'*128)
        self.assertEqual(result['model'],'Test Panel');self.assertTrue(result['edid_base_available'])

    def test_invalid_manufacturer_or_model_text_is_not_published(self):
        raw=bytearray(edid());raw[8]=0;raw[9]=0;raw[127]=0;raw[127]=(-sum(raw))%256
        with self.assertRaises(OSError):p.edid_identity(bytes(raw))
        raw=bytearray(edid());raw[59]=0xff;raw[127]=0;raw[127]=(-sum(raw))%256
        result=p.edid_identity(bytes(raw));self.assertFalse(result['model_available'])
        self.assertNotIn('model',result);self.assertEqual(result['manufacturer'],'ABC')

    def test_optional_mode_error_retains_presence_and_valid_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=connector(root,'card0-DSI-1');(path/'modes').unlink();row=p.report(root)[0]
        self.assertTrue(row['internal']);self.assertTrue(row['available']);self.assertTrue(row['model_available'])
        self.assertFalse(row['modes_available']);self.assertIsNone(row['modes'])

    def test_missing_or_empty_provider_is_not_zero_monitors(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for folder in [root,root/'missing']:
                with self.assertRaises(OSError):p.report(folder)

    def test_connection_change_discards_prior_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);connector(root,'card0-DP-1')
            with mock.patch.object(p,'state',side_effect=['connected','disconnected']):rows=p.report(root)
        self.assertFalse(rows[0]['available']);self.assertNotIn('model',rows[0])
        self.assertEqual(rows[0]['errno'],errno.EAGAIN)

    def test_final_identity_and_inventory_checks_reject_changed_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);a=connector(root,'card0-DP-1')
            with mock.patch.object(p,'identity',side_effect=[(1,1,'a'),(1,1,'a'),(1,2,'a')]):rows=p.report(root)
            self.assertFalse(rows[0]['available']);self.assertNotIn('model',rows[0])
            with mock.patch.object(p,'paths',side_effect=[[a],[a,root/'card0-DP-2']]):
                with self.assertRaises(OSError) as error:p.report(root)
            self.assertEqual(error.exception.errno,errno.EAGAIN)

    def test_unknown_arguments_are_rejected_before_query(self):
        for name in ['WMIGetExternMonitorNum','WMIGetExternMonitorPropList','WMIGetLCDModel']:
            with mock.patch.object(p,'report') as read:
                with self.assertRaises(ValueError):api_bridge.call({'name':name,'args':{'invented':True}})
                read.assert_not_called()

    def test_original_model_query_retains_external_as_well_as_internal_names(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);connector(root,'card0-eDP-1');connector(root,'card0-HDMI-A-1');connector(root,'card0-DP-1','disconnected');rows=p.report(root)
        with mock.patch.object(p,'report',return_value=rows):
            all_models=api_bridge.call({'name':'WMIGetLCDModel'})
            self.assertEqual({r['connector'] for r in all_models},{'card0-eDP-1','card0-HDMI-A-1'})
            self.assertTrue(all(r['model_available'] for r in all_models))
            internal=api_bridge.call({'name':'WMIGetLCDModel','args':{'internal_only':True}})
            self.assertEqual([r['connector'] for r in internal],['card0-eDP-1'])
            self.assertEqual(api_bridge.call({'name':'WMIGetLCDModel','args':{'internal_only':False}}),all_models)

    def test_model_scope_rejects_wrong_types_before_reading_metadata(self):
        for args in [{'internal_only':1},{'internal_only':'true'},{'internal_only':None}]:
            with self.subTest(args=args),mock.patch.object(p,'report') as read:
                with self.assertRaises(ValueError):api_bridge.call({'name':'WMIGetLCDModel','args':args})
                read.assert_not_called()
        for name in ('WMIGetExternMonitorNum','WMIGetExternMonitorPropList'):
            with mock.patch.object(p,'report') as read:
                with self.assertRaises(ValueError):api_bridge.call({'name':name,'args':{'internal_only':True}})
                read.assert_not_called()


    def test_default_model_query_keeps_unknown_external_and_compat_validates_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);connector(root,'card0-eDP-1');connector(root,'card0-HDMI-A-1','unknown');rows=p.report(root)
        with mock.patch.object(p,'report',return_value=rows):
            self.assertEqual({r['connector'] for r in api_bridge.call({'name':'WMIGetLCDModel'})},{'card0-eDP-1','card0-HDMI-A-1'})
        import compat
        compat.validate('WMIGetLCDModel',{'internal_only':True})
        for args in ({'internal_only':'yes'},{'other':True}):
            with self.assertRaises(ValueError):compat.validate('WMIGetLCDModel',args)


if __name__=='__main__':unittest.main()
