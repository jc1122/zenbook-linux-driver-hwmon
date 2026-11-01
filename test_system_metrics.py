# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import copy,json,os,tempfile,unittest
from unittest import mock
import cpu_throttling,ssd_health,charger_metrics,metrics,native_oem


def extra():
    return {'schema':1,'words':[73,14,16387,45100,19524,220,8320,10,20,6016,0x8069,0,19524,16387],
            'valid_mask':31,'die_millicelsius':51511,'vbat_pin_millivolts':8320,'system_millivolts':9024,
            'discharge_microamps':888000,'charge_microamps':888000,'battery_shunt_milliohms':5,
            'maximum_cache_seconds':2,'age_milliseconds':0}


class MetricsTests(unittest.TestCase):
    def test_ec_cpu_reports_temperature_voltage_and_typed_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);(p/'temp1_input').write_text('61000\n');(p/'in6_input').write_text('1147\n')
            with mock.patch.object(native_oem,'device',return_value=p):r=metrics._ec_cpu()
            self.assertEqual((r['temperature']['celsius'],r['voltage']['volts']),(61.0,1.147))
            (p/'in6_input').unlink();(p/'temp1_input').write_text('bad')
            with mock.patch.object(native_oem,'device',return_value=p):r=metrics._ec_cpu()
            self.assertFalse(r['temperature']['available']);self.assertFalse(r['voltage']['available'])
            self.assertEqual(r['voltage']['errno'],2)

    def test_charger_units_flags_and_opaque_pin_label(self):
        row=charger_metrics.decode(extra())
        self.assertEqual(row['die_temperature_celsius'],51.511)
        self.assertEqual(row['battery_discharge_current_amperes'],.888)
        self.assertEqual(row['system_voltage_volts'],9.024)
        self.assertEqual(row['status']['active_control_loop'],'system_voltage')
        self.assertFalse(row['status']['live_protection']['thermal_warning'])
        self.assertNotIn('0x90',row['raw_registers'])
        data=extra();data['words'][11]=1<<6|1<<2
        flags=charger_metrics.decode(data)['status']['live_protection']
        self.assertTrue(flags['thermal_warning'] and flags['fet_fault'])

    def test_disabled_adc_retains_status_without_fabricating_sensor_values(self):
        data=extra();data['words'][2]=0;data['valid_mask']=0
        result=charger_metrics.decode(data)
        self.assertTrue(result['available'])
        self.assertFalse(result['adc_available'])
        self.assertIsNone(result['die_temperature_celsius'])
        self.assertIsNone(result['battery_charge_current_amperes'])
        for mutate in [lambda d:d.update(age_milliseconds=2001),lambda d:d['words'].__setitem__(0,0),
                       lambda d:d.update(discharge_microamps=444000),lambda d:d['words'].__setitem__(11,0xffff)]:
            data=extra();mutate(data)
            with self.assertRaises(OSError):charger_metrics.decode(data)

    def test_charger_metrics_non_object_json_is_an_unavailable_protocol_error(self):
        import errno
        for raw in (b'[]',b'7',b'"x"',b'null'):
            with self.subTest(raw=raw),mock.patch.object(charger_metrics.native_oem,'device',return_value=Path('/test')), \
                 mock.patch.object(charger_metrics.os,'open',return_value=7),mock.patch.object(charger_metrics.os,'close'), \
                 mock.patch.object(charger_metrics.os,'read',return_value=raw):
                row=charger_metrics.report()
            self.assertFalse(row['available']);self.assertEqual(row['errno'],errno.EPROTO)

    def test_cpu_counts_are_per_cpu_not_summed_and_missing_is_not_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for cpu,count in [(0,'100'),(1,'101')]:
                p=root/f'cpu{cpu}'/'thermal_throttle';p.mkdir(parents=True)
                (p/'package_throttle_count').write_text(count)
                (p/'core_throttle_count').write_text('invalid')
            row=cpu_throttling.report(root)
            self.assertEqual(row['summary']['package_throttle_count']['value'],'101')
            self.assertEqual(len(row['cpus']),2)
            self.assertNotIn('core_throttle_count',row['summary'])

    def test_smart_sanitizes_identifiers_and_preserves_warning_health_and_128bit_counters(self):
        data={'serial_number':'DO-NOT-EXPORT','model_name':'private-model','smart_status':{'passed':False},
              'nvme_smart_health_information_log':{'critical_warning':4,'available_spare':99,'percentage_used':130,
                   'media_errors':5,'data_units_written':2**80,'temperature':50}}
        row=ssd_health.decode_smart(data,'nvme0n1',8)
        self.assertTrue(row['available']);self.assertFalse(row['smart_passed'])
        self.assertEqual(row['wear_used_percent'],130)
        self.assertEqual(row['counters']['data_units_written'],str(2**80))
        self.assertEqual(row['counters']['data_written_bytes_rounded'],str(2**80*512000))
        self.assertNotIn('private-model',json.dumps(row));self.assertNotIn('DO-NOT-EXPORT',json.dumps(row))
        self.assertFalse(ssd_health.decode_smart(data,'nvme0n1',2)['available'])
        with self.assertRaises(ValueError):ssd_health.decode_smart(data,'../../sda',0)

    def test_cache_rejects_stale_permissions_symlinks_and_future_samples(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'ssd.json'
            d={'schema':1,'generated_boottime_seconds':100,'devices':[{'available':True}]}
            p.write_text(json.dumps(d));p.chmod(0o644)
            self.assertTrue(ssd_health.read_cached(p,101,os.getuid())['available'])
            for now in [99,281]:self.assertFalse(ssd_health.read_cached(p,now,os.getuid())['available'])
            p.chmod(0o666);self.assertFalse(ssd_health.read_cached(p,101,os.getuid())['available'])
            p.chmod(0o644);link=p.with_name('link');link.symlink_to(p)
            self.assertFalse(ssd_health.read_cached(link,101,os.getuid())['available'])


if __name__=='__main__':unittest.main()
