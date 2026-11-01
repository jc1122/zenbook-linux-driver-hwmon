# SPDX-License-Identifier: GPL-2.0-only
import unittest
from unittest import mock
import battery_diagnostics as battery
from test_battery_diagnostics import full_lifetime


def frame(words=(100,2,3,90,0,0,0,4),tail=b'\xa5'*10):
    d=full_lifetime();raw=b''.join(value.to_bytes(2,'little') for value in words)+tail
    d['block3_hex']=raw.hex();d['block3_prefix_hex']=raw[:4].hex();return d


class BatteryRuntimeTests(unittest.TestCase):
    def test_known_u16_is_separate_from_opaque_legacy_u32(self):
        r=battery.decode_lifetime(frame());t=r['recorded_firmware_runtime']
        self.assertTrue(t['available']);self.assertTrue(t['unit_verified'])
        self.assertEqual((t['counter_raw'],t['hours'],t['resolution_hours']),(100,200,2))
        self.assertEqual(r['runtime_counter_raw'],100+(2<<16));self.assertFalse(r['runtime_unit_verified'])
        self.assertFalse(t['reset_behavior_verified']);self.assertNotIn('battery_age_hours',t)
        self.assertEqual(r['unmapped_block_bytes']['3']['offset'],16)
        self.assertTrue(r['unmapped_block_bytes']['3']['data_hex'].endswith('a5'*10))
        with mock.patch.object(battery,'lifetime_report',return_value=r):
            value=battery.call('BatteryHealthy_Read_LifetimeBlock3',{})
        self.assertEqual(value['recorded_firmware_runtime']['hours'],200)
        self.assertEqual(value['data_hex'],frame()['block3_hex']);self.assertTrue(value['complete'])

    def test_recorded_zero_and_quantized_steps_are_not_interpolated(self):
        t=battery.decode_lifetime(frame((0,0,0,0,0,0,0,0)))['recorded_firmware_runtime']
        self.assertTrue(t['available']);self.assertEqual(t['hours'],0)
        first=battery.decode_lifetime(frame())['recorded_firmware_runtime']
        later=frame();later['age_milliseconds']=59000
        self.assertEqual(battery.decode_lifetime(later)['recorded_firmware_runtime']['hours'],first['hours'])
        increment=battery.decode_lifetime(frame((101,2,3,91,0,0,0,4)))['recorded_firmware_runtime']
        self.assertEqual(increment['hours']-first['hours'],2)

    def test_partial_frames_do_not_gain_a_fabricated_runtime(self):
        from test_battery_diagnostics import lifetime
        r=battery.decode_lifetime(lifetime());self.assertFalse(r['recorded_firmware_runtime']['available'])
        self.assertIsNone(r['recorded_firmware_runtime']['hours'])
        for size in [0,4,8,16,24,32]:
            self.assertFalse(battery.recorded_runtime(bytes(size))['available'])

    def test_unknown_relationships_or_maximum_values_preserve_other_history(self):
        for words in [(100,2,3,110,0,0,0,4),(100,0,0,0,0,0,0,0),
                      (65535,0,0,0,0,0,0,0),(100,65535,0,0,0,0,0,0)]:
            r=battery.decode_lifetime(frame(words));t=r['recorded_firmware_runtime']
            self.assertFalse(t['available']);self.assertIsNone(t['hours']);self.assertFalse(t['unit_verified'])
            self.assertTrue(r['available']);self.assertEqual(r['temperatures_celsius']['fet_maximum'],48)
            self.assertEqual(t['counter_raw'],words[0]);self.assertIn('error',t)

    def test_existing_identity_freshness_and_prefix_checks_cover_runtime(self):
        d=frame()
        for update in [{'age_milliseconds':60001},{'device_type_hex':'0000'},
                       {'firmware_hex':'00000234004002000000000000'},{'block3_prefix_hex':'00'*4}]:
            with self.assertRaises((ValueError,OSError)):battery.decode_lifetime({**d,**update})


if __name__=='__main__':unittest.main()
