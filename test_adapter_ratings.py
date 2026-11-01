# SPDX-License-Identifier: GPL-2.0-only
import errno
import unittest
from unittest import mock
import adapter_ratings as p
import api_bridge
import compat
import native_oem


def raw(config=-1,mask=1<<23):
    return {'protocol':15,'adapter_config':config,'unavailable_mask':mask,'adapter_watts':65,'measured_input_watts':31}


class AdapterRatingTests(unittest.TestCase):
    def test_qualified_x86_never_uses_ARM_WMI_or_fabricates_ratings_from_limits(self):
        with mock.patch.object(p.qualified_ec,'snapshot',return_value=(raw(),[])),mock.patch.object(native_oem,'rpc',side_effect=AssertionError('Unexpected WMI/EC request')):
            report=p.report()
            for name in p.NAMES:
                self.assertFalse(compat.needs_root(name,{}))
                with mock.patch('os.geteuid',return_value=1000),self.assertRaises(OSError) as caught:api_bridge.call({'name':name})
                self.assertEqual(caught.exception.errno,errno.EOPNOTSUPP)
        self.assertTrue(report['provider_available']);self.assertEqual(report['current_protocol'],15)
        self.assertEqual(report['minimum_rating_protocol'],28)
        self.assertTrue(all(r['watts'] is None and not r['request_sent'] and not r['available'] for r in report['ratings']))
        self.assertTrue(all(r['status']=='requires_newer_protocol' for r in report['ratings']))

    def test_legacy_interface_is_a_distinct_original_gate(self):
        with mock.patch.object(p.qualified_ec,'snapshot',return_value=(raw(),['ASUS1000:00'])):report=p.report()
        self.assertTrue(report['legacy_ASUS1000_present'])
        self.assertTrue(all(r['status']=='legacy_interface_blocks_original_path' for r in report['ratings']))

    def test_provider_failures_do_not_become_protocol_or_wattage_claims(self):
        for code in [errno.EIO,errno.EBUSY,errno.EAGAIN,errno.EACCES]:
            with self.subTest(code=code),mock.patch.object(p.qualified_ec,'snapshot',side_effect=OSError(code,'Read failed')):
                report=p.report()
                with self.assertRaises(OSError) as caught:p.call('Adapter_Read_Standard_Watt',{})
            self.assertEqual(caught.exception.errno,code);self.assertFalse(report['provider_available'])
            self.assertNotIn('current_protocol',report)
            self.assertTrue(all(r['status']=='provider_unavailable' and r['errno']==code for r in report['ratings']))

    def test_unknown_or_newer_protocol_does_not_bypass_device_qualification(self):
        for version in [None,True,14,28,255]:
            with self.subTest(version=version),mock.patch.object(p.qualified_ec,'snapshot',return_value=({**raw(),'protocol':version},[])):
                report=p.report()
            self.assertFalse(report['provider_available'])
            self.assertTrue(all(r['errno']==errno.EOPNOTSUPP and not r['request_sent'] for r in report['ratings']))

    def test_configuration_timeout_is_latched_observation_not_proven_firmware_absence(self):
        value=p.diagnostic_config(raw())
        self.assertFalse(value['available']);self.assertIsNone(value['raw_config'])
        self.assertTrue(value['read_failure_latched']);self.assertEqual(value['errno'],errno.ENODATA)
        self.assertFalse(value['new_request_sent']);self.assertFalse(value['static_firmware_absence_proven'])

    def test_valid_zero_and_nonzero_configuration_are_raw_not_measurements(self):
        for config in [0,42,255]:
            with self.subTest(config=config):
                value=p.diagnostic_config(raw(config,0))
                self.assertTrue(value['available']);self.assertEqual(value['raw_config'],config)
                self.assertFalse(value['read_failure_latched']);self.assertNotIn('watts',value)
                self.assertFalse(value['static_firmware_absence_proven'])

    def test_conflicting_or_malformed_configuration_is_not_published(self):
        invalid=[raw(0,1<<23),raw(True,0),raw(256,0),raw(-2,0),raw(0,True),raw(0,-1),raw(0,2**64),{}]
        for data in invalid:
            with self.subTest(data=data):
                value=p.diagnostic_config(data)
                self.assertFalse(value['available']);self.assertIsNone(value['raw_config'])
                self.assertEqual(value['errno'],errno.EPROTO)

    def test_all_arguments_are_rejected_before_authentication_or_hardware_access(self):
        with mock.patch.object(p,'report',side_effect=AssertionError('Unexpected read')):
            for name in p.NAMES:
                with self.assertRaises(ValueError):api_bridge.call({'name':name,'args':{'connector':1}})
                with self.assertRaises(ValueError):p.call(name,[])


if __name__=='__main__':unittest.main()
