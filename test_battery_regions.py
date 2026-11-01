# SPDX-License-Identifier: GPL-2.0-only
import unittest
from unittest import mock
import battery_diagnostics as battery
from test_battery_runtime import frame
from test_battery_diagnostics import lifetime


class RecordedRegionTests(unittest.TestCase):
    def test_region_order_units_and_rounding_gap_are_separate_from_thresholds(self):
        r=battery.decode_lifetime(frame());t=r['recorded_temperature_region_time']
        self.assertTrue(t['available']);self.assertTrue(t['unit_verified'])
        self.assertEqual([x['code'] for x in t['regions']],['UT','LT','STL','RT','STH','HT','OT'])
        self.assertEqual([x['hours'] for x in t['regions']],[4,6,180,0,0,0,8])
        self.assertEqual((t['sum_recorded_hours'],t['rounding_gap_hours']),(198,2))
        self.assertFalse(t['configured_thresholds_available']);d=t['reference_default_thresholds_celsius'];self.assertFalse(d['read_from_pack']);self.assertEqual((d['T1'],d['T4'],d['regions']['RT']),(0,55,'T5..T6'))
        self.assertTrue(all(x['thresholds_celsius'] is None for x in t['regions']))
        self.assertEqual(r['unmapped_block_bytes']['3']['offset'],16)
        self.assertEqual(r['unmapped_block_bytes']['3']['data_hex'],'a5'*10)
        with mock.patch.object(battery,'lifetime_report',return_value=r):v=battery.call('BatteryHealthy_Read_LifetimeBlock3',{})
        self.assertEqual(v['recorded_temperature_region_time'],t)

    def test_independent_bucket_step_does_not_invent_runtime_or_interpolate(self):
        before=battery.decode_lifetime(frame((101,2,3,90,0,0,0,4)))
        after=battery.decode_lifetime(frame((101,2,3,90,1,0,0,4)))
        a=before['recorded_temperature_region_time'];b=after['recorded_temperature_region_time']
        self.assertEqual(b['regions'][3]['hours']-a['regions'][3]['hours'],2)
        self.assertEqual(b['rounding_gap_hours'],a['rounding_gap_hours']-2)
        self.assertEqual(before['recorded_firmware_runtime']['hours'],after['recorded_firmware_runtime']['hours'])

    def test_partial_max_and_inconsistent_frames_keep_regions_unavailable(self):
        r=battery.decode_lifetime(lifetime());self.assertFalse(r['recorded_temperature_region_time']['available'])
        for values in [(100,0,0,0,0,0,0,0),(100,101,0,0,0,0,0,0),(65535,0,0,0,0,0,0,0)]:
            r=battery.decode_lifetime(frame(values));self.assertFalse(r['recorded_temperature_region_time']['available'])
            self.assertTrue(r['available']);self.assertEqual(r['temperatures_celsius']['fet_maximum'],48)

    def test_recorded_zero_regions_are_valid_without_degree_or_state_claim(self):
        r=battery.decode_lifetime(frame((0,0,0,0,0,0,0,0)))['recorded_temperature_region_time']
        self.assertTrue(r['available']);self.assertTrue(all(x['hours']==0 for x in r['regions']))
        self.assertNotIn('current_region',r);self.assertNotIn('temperature_celsius',r)


class RecordedBalancingTests(unittest.TestCase):
    def report(self,data=b'\x04\x00\x04\x00\x03\x05\x00\x00'):
        d=frame();d['block2_hex']=data.hex();d['block2_prefix_hex']=data[:4].hex()
        return battery.decode_lifetime(d)
    def test_two_applicable_u8_counters_no_phantom_cells_or_current_status(self):
        r=self.report();t=r['recorded_cell_balancing_time']
        self.assertTrue(t['available']);self.assertEqual([x['cell'] for x in t['cells']],[1,2])
        self.assertEqual([x['hours'] for x in t['cells']],[6,10]);self.assertEqual(t['resolution_hours'],2)
        self.assertTrue(t['unit_from_compatible_reference']);self.assertFalse(t['physical_nonzero_scaling_verified'])
        self.assertEqual(r['unmapped_block_bytes']['2'],{'offset':6,'data_hex':'0000'})
        self.assertNotIn('currently_balancing',t)
    def test_zero_is_quantized_recorded_value_not_never_or_disabled_claim(self):
        t=self.report(b'\x04\x00\x04\x00'+bytes(4))['recorded_cell_balancing_time']
        self.assertTrue(t['available']);self.assertEqual([x['hours'] for x in t['cells']],[0,0])
        self.assertNotIn('never_balanced',t);self.assertFalse(t['reset_behavior_verified'])
    def test_one_maximum_counter_preserves_other_cell_and_other_history(self):
        r=self.report(b'\x04\x00\x04\x00\xff\x05\x00\x00');t=r['recorded_cell_balancing_time']
        self.assertTrue(t['available']);self.assertIsNone(t['cells'][0]['hours'])
        self.assertTrue(t['cells'][0]['saturated']);self.assertEqual(t['cells'][0]['hours_at_least'],510)
        self.assertEqual(t['cells'][0]['counter_raw'],255);self.assertEqual(t['cells'][1]['hours'],10)
        self.assertFalse(t['cells'][1]['saturated']);self.assertIsNone(t['cells'][1]['hours_at_least'])
        self.assertTrue(t['cells'][1]['available']);self.assertTrue(r['recorded_firmware_runtime']['available'])
        self.assertEqual(r['power_event_counts']['shutdowns'],4)
    def test_partial_or_nonzero_inactive_storage_cannot_qualify_cell_time(self):
        r=battery.decode_lifetime(lifetime());self.assertFalse(r['recorded_cell_balancing_time']['available'])
        r=self.report(b'\x04\x00\x04\x00\x03\x05\x01\x00')
        self.assertFalse(r['recorded_cell_balancing_time']['available']);self.assertTrue(r['available'])
        self.assertEqual(r['temperatures_celsius']['fet_maximum'],48)
        self.assertEqual(len(bytes.fromhex(r['raw_blocks']['2'])),8)


if __name__=='__main__':unittest.main()
