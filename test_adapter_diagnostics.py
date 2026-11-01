# SPDX-License-Identifier: GPL-2.0-only
import errno
import unittest
from unittest import mock
import adapter_diagnostics as p
import adapter_ratings
import api_bridge
import compat
import native_oem


def metadata(**changes):
    return {'max_dd_bank':5,'unsupported_mask':1<<23,'unavailable_mask':0,'adapter_config':-1,**changes}


class AdapterDiagnosticsTests(unittest.TestCase):
    def test_public_calls_report_source_absence_without_root_or_rpc(self):
        with mock.patch.object(p.qualified_ec,'snapshot',return_value=(metadata(),[])),mock.patch.object(native_oem,'rpc',side_effect=AssertionError('Unexpected RPC')):
            report=p.report()
            for name in p.NAMES:
                self.assertFalse(compat.needs_root(name,{}))
                with mock.patch('os.geteuid',return_value=1000),self.assertRaises(OSError) as caught:api_bridge.call({'name':name})
                self.assertEqual(caught.exception.errno,errno.EOPNOTSUPP)
        self.assertTrue(report['provider_available'])
        self.assertEqual(report['implemented_dd_banks'],[1,2,3,4,5])
        self.assertTrue(all(r['value'] is None and not r['available'] and not r['request_sent'] for r in report['diagnostics']))

    def test_support_absence_is_distinct_from_failed_probe(self):
        current=p.configuration(metadata())
        self.assertTrue(current['static_firmware_absence_proven'])
        self.assertFalse(current['read_failure_latched'])
        old=adapter_ratings.diagnostic_config({'adapter_config':-1,'unavailable_mask':1<<23})
        self.assertFalse(old['static_firmware_absence_proven'])
        self.assertEqual(old['errno'],errno.ENODATA)

    def test_missing_or_bad_support_metadata_is_not_platform_absence(self):
        for data in [{},metadata(max_dd_bank=True),metadata(max_dd_bank=6),metadata(max_dd_bank=0),
                     metadata(unsupported_mask=0),metadata(unsupported_mask=True),metadata(unsupported_mask=-1),
                     metadata(unsupported_mask=2**64)]:
            with self.subTest(data=data),mock.patch.object(p.qualified_ec,'snapshot',return_value=(data,[])):
                report=p.report()
                self.assertFalse(report['provider_available'])
                self.assertTrue(all(r['errno']==errno.EPROTO and r['status']=='provider_unavailable' for r in report['diagnostics']))

    def test_conflicting_configuration_does_not_become_a_measurement(self):
        for data in [metadata(adapter_config=0),metadata(adapter_config=65),metadata(adapter_config=True),
                     metadata(unavailable_mask=1<<23),metadata(unavailable_mask=True),metadata(unavailable_mask=-1)]:
            with self.subTest(data=data),self.assertRaises(OSError) as caught:p.configuration(data)
            self.assertEqual(caught.exception.errno,errno.EPROTO)

    def test_transport_or_identity_error_keeps_its_errno(self):
        for code in [errno.EIO,errno.EBUSY,errno.EACCES,errno.EAGAIN,errno.ENODEV]:
            with self.subTest(code=code),mock.patch.object(p.qualified_ec,'snapshot',side_effect=OSError(code,'Provider error')):
                report=p.report()
                self.assertFalse(report['provider_available'])
                with self.assertRaises(OSError) as caught:p.call('Adapter_Read_Power_Big_Data_Config',{})
                self.assertEqual(caught.exception.errno,code)

    def test_legacy_device_presence_cannot_create_missing_firmware_bank(self):
        with mock.patch.object(p.qualified_ec,'snapshot',return_value=(metadata(),['ASUS1000:00'])):
            self.assertTrue(p.report()['provider_available'])

    def test_current_rating_report_uses_same_support_semantics(self):
        self.assertEqual(adapter_ratings.diagnostic_config(metadata()),p.configuration(metadata()))
        invalid=adapter_ratings.diagnostic_config(metadata(adapter_config=0))
        self.assertEqual(invalid['errno'],errno.EPROTO)
        self.assertFalse(invalid['static_firmware_absence_proven'])

    def test_arguments_rejected_before_read_or_authentication(self):
        with mock.patch.object(p,'report',side_effect=AssertionError('Unexpected access')):
            for name in p.NAMES:
                for args in [{'connector':1},{'index':0},[]]:
                    with self.subTest(name=name,args=args),self.assertRaises(ValueError):api_bridge.call({'name':name,'args':args})


if __name__=='__main__':unittest.main()
