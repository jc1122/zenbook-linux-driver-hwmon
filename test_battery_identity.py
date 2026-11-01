# SPDX-License-Identifier: GPL-2.0-only
import errno
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import api_bridge
import battery_identity as identity
import compat


def sample(manufacturer=b'TSTQ-PACK-Z',model=b'PACK123'):
    return {'schema':1,'device_type_hex':'5645','firmware_hex':'45560234004002000000000000',
            'maximum_cache_seconds':300,'age_milliseconds':0,
            'manufacturer_hex':manufacturer.hex(),'model_hex':model.hex()}


class BatteryIdentityTests(unittest.TestCase):
    def test_full_reported_strings_and_original_raw_byte_convention(self):
        r=identity.decode(sample())
        self.assertEqual(r['manufacturer'],'TSTQ-PACK-Z');self.assertEqual(r['model'],'PACK123')
        self.assertEqual(r['gauge_identifier_raw'],ord('Q'))
        self.assertEqual(r['device_type_hex'],'4556');self.assertFalse(r['physical_gauge_vendor_verified'])
        self.assertEqual(identity.decode(sample(b'Z'*32,b'Z'*32))['model'],'Z'*32)

    def test_nontext_or_short_manufacturer_preserves_raw_and_good_model(self):
        r=identity.decode(sample(b'AB\x00\x00',b'PACK123'))
        self.assertIsNone(r['manufacturer']);self.assertEqual(r['manufacturer_raw_hex'],'41420000')
        self.assertEqual(r['gauge_identifier_raw'],0);self.assertEqual(r['model'],'PACK123')
        r=identity.decode(sample(b'AB'));self.assertIsNone(r['gauge_identifier_raw'])
        self.assertIsNone(identity.decode(sample(b'   '))['manufacturer'])

    def test_malformed_stale_and_wrong_identity_data_are_rejected(self):
        for change in [{'schema':True},{'device_type_hex':'0000'},{'firmware_hex':'00'*13},
                       {'age_milliseconds':300001},{'maximum_cache_seconds':60},
                       {'manufacturer_hex':''},{'model_hex':'00'*33},{'model_hex':'0'},{'model_hex':'zz'}]:
            with self.subTest(change=change),self.assertRaises((OSError,ValueError)):
                identity.decode({**sample(),**change})

    def test_missing_driver_and_unavailable_fields_do_not_fake_empty_or_zero(self):
        with tempfile.TemporaryDirectory() as temp,mock.patch('native_oem.device',return_value=Path(temp)):
            self.assertFalse(identity.report()['available'])
            with self.assertRaises(OSError):identity.call('BatteryHealthyTable_DeviceName',{})
        with mock.patch.object(identity,'report',return_value=identity.decode(sample(b'AB'))):
            with self.assertRaises(OSError) as error:identity.call('BatteryHealthyTable_GaugeIC',{})
            self.assertEqual(error.exception.errno,errno.ENODATA)

    def test_every_identity_export_routes_without_full_sensor_snapshot(self):
        expected={'model':'PACK123','manufacturer':'TSTQ-PACK-Z','gauge_identifier_raw':ord('Q')}
        # 0.79: root-only driver attributes; non-root callers use the service.
        with mock.patch.object(identity,'report',return_value=identity.decode(sample())),mock.patch.object(compat.os,'geteuid',return_value=0):
            for name,field in identity.NAMES.items():
                self.assertTrue(compat.needs_root(name,{}))
                self.assertEqual(api_bridge.call({'name':name}),expected[field])
                with self.assertRaises(ValueError):api_bridge.call({'name':name,'args':{'value':0}})


if __name__=='__main__':unittest.main()
