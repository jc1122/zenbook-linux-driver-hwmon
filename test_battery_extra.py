# SPDX-License-Identifier: GPL-2.0-only
import tempfile,unittest
from pathlib import Path
from unittest import mock
import battery_extra as extra


def sample(current=-1000):
    a=bytearray(32);t=bytearray(24)
    for o,n in [(0,4200),(2,4100),(8,8300),(10,8400),(12,current),(14,current),
                (20,int(4200*current/10000)),(22,int(4100*current/10000)),
                (28,int(8300*current/10000)),(30,-700)]:
        a[o:o+2]=n.to_bytes(2,'little',signed=n<0)
    t[14:16]=(3000).to_bytes(2,'little');t[16:]=b'\x01\x02\x03\x04\x05\x06\x07\x08'
    return {'schema':1,'device_type_hex':'5645','firmware_hex':'45560234004002000000000000',
            'age_milliseconds':0,'maximum_cache_seconds':15,'da1_hex':a.hex(),'da2_hex':t.hex()}


class BatteryExtraTests(unittest.TestCase):
    def test_signed_cell_pack_average_power_and_algorithm_temperature(self):
        for current in [-1000,0,1000]:
            r=extra.decode(sample(current));self.assertEqual(r['cells'][0]['power_watts'],4.2*current/1000)
            self.assertEqual(r['gauge_power_watts'],8.3*current/1000)
            self.assertEqual(r['gauge_average_power_watts'],-7)
            self.assertAlmostEqual(r['gauging_temperature_celsius'],26.85)
            self.assertFalse(r['independent_power_adc']);self.assertTrue(r['power_computed_by_gauge'])
            self.assertEqual(r['unmapped_da2_tail_hex'],'0102030405060708')
            self.assertFalse(r['uncompensated_cells']['available']);self.assertEqual(r['uncompensated_cells']['cells'],[])

    def test_da2_tail_decodes_uncompensated_cells_only_when_layout_checks_pass(self):
        d=sample();t=bytearray.fromhex(d['da2_hex'])
        t[16:24]=(4190).to_bytes(2,'little')+(4085).to_bytes(2,'little')+bytes(4);d['da2_hex']=t.hex()
        u=extra.decode(d)['uncompensated_cells'];self.assertTrue(u['available'])
        self.assertEqual([(c['voltage_volts'],c['minus_compensated_millivolts']) for c in u['cells']],[(4.19,-10),(4.085,-15)])
        for bad in [(4190,4085,1,0),(1500,4085,0,0),(4190,3000,0,0)]:
            t[16:24]=b''.join(v.to_bytes(2,'little') for v in bad);d['da2_hex']=t.hex()
            u=extra.decode(d)['uncompensated_cells'];self.assertFalse(u['available'],bad);self.assertEqual(u['errno'],61)

    def test_wrong_power_scale_is_unavailable_without_replacing_the_register(self):
        d=sample();a=bytearray.fromhex(d['da1_hex']);a[20:22]=(-840).to_bytes(2,'little',signed=True);d['da1_hex']=a.hex()
        r=extra.decode(d);self.assertIsNone(r['cells'][0]['power_watts']);self.assertEqual(r['gauge_power_watts'],-8.3)
        self.assertEqual(r['cells'][1]['power_watts'],-4.1);self.assertEqual(r['gauge_average_power_watts'],-7)
        self.assertIsNone(r['power_sum_comparison']['cell_sum_watts'])

    def test_pack_power_retains_its_own_reported_value_when_cell_sum_differs(self):
        d=sample();a=bytearray.fromhex(d['da1_hex']);a[28:30]=(-1570).to_bytes(2,'little',signed=True);d['da1_hex']=a.hex()
        r=extra.decode(d);self.assertEqual(r['gauge_power_watts'],-15.7)
        self.assertEqual(r['gauge_power_raw_centiwatts'],-1570);self.assertEqual(r['gauge_average_power_raw_centiwatts'],-700)
        self.assertAlmostEqual(r['power_sum_comparison']['cell_sum_watts'],-8.3)
        self.assertAlmostEqual(r['power_sum_comparison']['pack_minus_cell_sum_watts'],-7.4)
        self.assertFalse(r['power_sum_comparison']['time_alignment_verified']);self.assertFalse(r['power_sum_comparison']['used_as_validity_gate'])

    def test_out_of_range_pack_and_average_values_remain_independently_unavailable(self):
        for offset,field,other,expected in [(28,'gauge_power_watts','gauge_average_power_watts',-7),(30,'gauge_average_power_watts','gauge_power_watts',-8.3)]:
            for raw in [-32768,32767,-20001,20001]:
                d=sample();a=bytearray.fromhex(d['da1_hex']);a[offset:offset+2]=raw.to_bytes(2,'little',signed=True);d['da1_hex']=a.hex()
                with self.subTest(offset=offset,raw=raw):
                    r=extra.decode(d);self.assertIsNone(r[field]);self.assertEqual(r[other],expected)
                    self.assertEqual(r['cells'][0]['power_watts'],-4.2)

    def test_short_stale_wrong_identity_and_topology_are_not_accepted(self):
        d=sample()
        for change in [{'da1_hex':d['da1_hex'][:-2]},{'da2_hex':d['da2_hex'][:-2]},
                       {'age_milliseconds':15001},{'schema':True},{'device_type_hex':'0000'},{'da1_hex':'00'*32}]:
            with self.subTest(change=change),self.assertRaises((OSError,ValueError)):extra.decode({**d,**change})

    def test_off_scale_algorithm_input_and_old_driver_stay_unavailable(self):
        d=sample();t=bytearray.fromhex(d['da2_hex']);t[14:16]=(4700).to_bytes(2,'little');d['da2_hex']=t.hex()
        r=extra.decode(d);self.assertIsNone(r['gauging_temperature_celsius']);self.assertEqual(r['gauge_power_watts'],-8.3)
        with tempfile.TemporaryDirectory() as temp,mock.patch('native_oem.device',return_value=Path(temp)):
            self.assertFalse(extra.report()['available'])


if __name__=='__main__':unittest.main()
