# SPDX-License-Identifier: GPL-2.0-only
import errno
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import battery_diagnostics as b
import compat
import thermistors


def envelope(seconds):
 return {'schema':1,'device_type_hex':'5645','firmware_hex':'45560234004002000000000000','age_milliseconds':0,'maximum_cache_seconds':seconds}
def lifetime():
 raw=bytearray(31)
 for o,n in [(0,4300),(2,4250),(8,3000),(10,3100),(12,32767),(14,32767),(16,250),(18,6500),(20,-9000),(22,-5000),(24,-4000)]:raw[o:o+2]=n.to_bytes(2,'little',signed=n<0)
 for o,n in [(26,50),(27,10),(28,2),(29,55),(30,12)]:raw[o]=n
 return {**envelope(60),'block1_prefix_hex':raw.hex(),'block3_prefix_hex':bytes(4).hex(),'block4_prefix_hex':bytes(31).hex(),'block5_prefix_hex':bytes(31).hex()}
def metrics():
 raw=bytearray(20)
 for o,n in [(0,4100),(2,4200),(8,8300),(10,8400),(12,-1234),(14,-1235)]:raw[o:o+2]=n.to_bytes(2,'little',signed=n<0)
 temps=[3100,3050,3060,4700,4700,3050,3060]
 return {**envelope(5),'da1_hex':raw.hex(),'da2_hex':b''.join(n.to_bytes(2,'little') for n in temps).hex()}
def full_lifetime():
 d=lifetime();d['block2_prefix_hex']='04000400';d['complete_blocks']=True
 for i,size in enumerate((32,8,26,32,32),1):
  raw=bytearray.fromhex(d[f'block{i}_prefix_hex']);raw.extend(bytes(size-len(raw)))
  if i==1:raw[31]=48
  if i==3:raw[:4]=(123).to_bytes(4,'little');d['block3_prefix_hex']=raw[:4].hex();raw[4:8]=b'\x01\x02\x03\x04'
  if i==5:
   raw[28:30]=(4).to_bytes(2,'little');raw[30:32]=(244).to_bytes(2,'little');d['block5_prefix_hex']=raw[:31].hex()
  d[f'block{i}_hex']=raw.hex()
 return d


class BatteryDiagnosticsTests(unittest.TestCase):
 def test_gauge_temperatures_current_sign_and_inactive_channels(self):
  r=b.decode_metrics(metrics());self.assertAlmostEqual(r['temperatures_celsius']['internal'],36.85)
  self.assertIsNone(r['temperatures_celsius']['ts3']);self.assertEqual(r['cells'][0]['current_amperes'],-1.234)
  self.assertEqual(r['bat_pin_voltage_volts'],8.3);self.assertEqual(r['pack_pin_voltage_volts'],8.4)
 def test_fresh_extrema_and_discharge_sign(self):
  r=b.decode_lifetime(lifetime());self.assertEqual(r['maximum_discharge_current_amperes'],9)
  self.assertEqual(r['maximum_average_discharge_power_watts'],40);self.assertEqual(r['max_charge_current_milliamps'],6500)
  self.assertEqual(r['temperatures_celsius']['cell_minimum'],10);self.assertEqual(len(r['cells']),2)
  self.assertFalse(r['runtime_unit_verified']);self.assertNotIn('fet_maximum',r['temperatures_celsius'])
 def test_recorded_events_last_cycle_and_partial_fields(self):
  d=lifetime();raw=bytearray.fromhex(d['block5_prefix_hex'])
  for offset,value in [(16,210),(18,292),(20,18),(22,179),(24,3267),(26,292),(28,4)]:
   raw[offset:offset+2]=value.to_bytes(2,'little')
  raw[30]=244;d['block5_prefix_hex']=raw.hex();d['block2_prefix_hex']='04000400'
  r=b.decode_lifetime(d);events={e['name']:e for e in r['lifetime_events']}
  self.assertEqual(r['power_event_counts'],{'shutdowns':4,'partial_resets':0,'full_resets':4,'watchdog_resets':0})
  self.assertEqual(events['Valid Charge Termination']['count'],210)
  self.assertEqual(events['Resistance Update']['last_event_cycle_count'],292)
  self.assertIsNone(events['Cell Overvoltage']['last_event_cycle_count'])
  self.assertIsNone(events['Resistance Update Disable']['last_event_cycle_count'])
  self.assertFalse(events['Resistance Update Disable']['last_cycle_field_complete'])
  self.assertFalse(events['Discharge Short Circuit']['last_cycle_field_complete'])
 def test_old_driver_has_no_fabricated_reset_counts_or_runtime_unit(self):
  r=b.decode_lifetime(lifetime());self.assertIsNone(r['power_event_counts'])
  self.assertFalse(r['runtime_unit_verified'])
  with self.assertRaises(ValueError):b.decode_lifetime({**lifetime(),'block2_prefix_hex':'0400'})
 def test_complete_blocks_recover_fet_and_cycle_tail_without_interpreting_unknown_bytes(self):
  r=b.decode_lifetime(full_lifetime());self.assertTrue(r['complete_blocks'])
  self.assertEqual(r['temperatures_celsius']['fet_maximum'],48)
  self.assertEqual(r['runtime_counter_raw'],123);self.assertFalse(r['runtime_unit_verified'])
  self.assertEqual(len(bytes.fromhex(r['raw_blocks']['3'])),26)
  self.assertEqual(r['unmapped_block_bytes']['3']['offset'],16);self.assertEqual(len(r['unmapped_block_bytes']['3']['data_hex']),20)
  self.assertEqual(r['lifetime_events'][-1]['last_event_cycle_count'],244)
  self.assertTrue(all(e['last_cycle_field_complete'] for e in r['lifetime_events']))
  with mock.patch.object(b,'lifetime_report',return_value=r):
   self.assertTrue(b.call('BatteryHealthy_Read_LifetimeBlock3',{})['complete'])
   self.assertEqual(len(b.call('BatteryHealthy_Read_LifetimeBlock3',{})['data_hex']),52)
 def test_complete_block_mismatch_missing_data_and_invalid_fet_are_rejected(self):
  d=full_lifetime()
  for update in [{'complete_blocks':1},{'block2_hex':'00'*20},{'block3_hex':'00'*4},{'block4_hex':'00'*31},
                 {'block1_hex':d['block1_hex'][:-2]+'7f'},{'block5_prefix_hex':'00'*31}]:
   with self.subTest(update=update),self.assertRaises((ValueError,OSError)):b.decode_lifetime({**d,**update})
  del d['block5_hex']
  with self.assertRaises(ValueError):b.decode_lifetime(d)
 def test_bad_identity_freshness_and_payloads_rejected(self):
  for update in [{'device_type_hex':'0045'},{'firmware_hex':'00560234004002000000000000'},{'age_milliseconds':60001},{'schema':2},{'block1_prefix_hex':bytes(32).hex()},{'block1_prefix_hex':bytes(31).hex()}]:
   with self.subTest(update=update),self.assertRaises((OSError,ValueError)):b.decode_lifetime({**lifetime(),**update})
  with self.assertRaises(OSError):b.decode_metrics({**metrics(),'age_milliseconds':5001})
 def test_original_apis_use_fresh_guarded_provider_without_privilege(self):
  r=b.decode_lifetime(lifetime())
  with mock.patch.object(b,'lifetime_report',return_value=r):
   self.assertEqual(compat.dispatch('BatteryHealthy_Read_MaxChargeCurrent',{}),6500)
   v=compat.dispatch('BatteryHealthy_Read_LifetimeBlock1',{});self.assertFalse(v['complete']);self.assertEqual(len(v['data_hex']),62)
  for name in b.NAMES:
   self.assertTrue(compat.needs_root(name,{}))  # 0.79: root-only lifetime attribute; service route
   with self.assertRaises(ValueError):compat.validate(name,{'selector':0x28})
 def test_provider_failure_does_not_reuse_old_ec_history(self):
  with tempfile.TemporaryDirectory() as tmp,mock.patch('native_oem.device',return_value=Path(tmp)):
   (Path(tmp)/'battery_history').write_text(json.dumps({'max_charge_current_mA':9999}))
   self.assertFalse(b.lifetime_report()['available'])
 def test_thermistor_label_mapping_and_old_driver_rejection(self):
  with tempfile.TemporaryDirectory() as tmp,mock.patch('native_oem.device',return_value=Path(tmp)):
   p=Path(tmp)
   for i,label,*_ in thermistors.MAPPING:
    (p/f'temp{i+1}_label').write_text(label);(p/f'temp{i+1}_input').write_text(str((30+i)*1000))
   r=thermistors.report();self.assertTrue(r['available']);self.assertEqual(r['sensors'][4]['label'],'DDR NTC')
   (p/'temp2_label').write_text('Mainboard');self.assertIsNone(thermistors.report()['sensors'][0]['temperature_celsius'])

if __name__=='__main__':unittest.main()
