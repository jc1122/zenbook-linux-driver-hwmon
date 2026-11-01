# SPDX-License-Identifier: GPL-2.0-only
import errno
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import api_bridge
import specialty_thermal as p
import qualified_ec as q


def telemetry(gpu=64):
    return {'protocol':15,'vendor':2,'chip_id':0,'chip_name_raw':[53,53,55,49],
            'firmware_raw':[48,49],'gpu_celsius':gpu,'cpu_celsius':99}


def fixture(base):
    dmi=base/'dmi';dmi.mkdir();acpi=base/'acpi';acpi.mkdir();hw=base/'hwmon';hw.mkdir()
    for name,value in [('product_name','Zenbook Flip UP3404VA_UP3404VA'),('bios_version','UP3404VA.301')]:
        (dmi/name).write_text(value+'\n')
    for name,value in [('name','zenbook_ec'),('pwm1_enable','2'),('ec_telemetry',json.dumps(telemetry()))]:(hw/name).write_text(value+'\n')
    return dmi,acpi,hw


def snapshot(dmi,acpi,hw):
    with mock.patch.object(q.native_oem,'device',return_value=hw),mock.patch.object(q.platform,'machine',return_value='x86_64'):
        return q.snapshot(dmi,acpi)


class SpecialtyThermalTests(unittest.TestCase):
    def test_original_gpu_fallback_uses_its_channel_not_cpu_or_nearby_ntc(self):
        with mock.patch.object(p,'snapshot',return_value=(telemetry(64),[])):
            report=p.report();result=api_bridge.call({'name':p.GPU})
        row=next(r for r in report['sensors'] if r['api']==p.GPU)
        self.assertEqual(row['raw_celsius'],64);self.assertEqual(row['celsius'],64)
        self.assertEqual(result[0]['celsius'],64);self.assertIn('bank2 selector3',result[0]['source'])
        self.assertTrue(report['provider_available']);self.assertTrue(report['any_sensor_available'])

    def test_eight_unsupported_original_zero_sentinels_are_not_temperatures(self):
        with mock.patch.object(p,'snapshot',return_value=(telemetry(),[])):
            report=p.report()
            for name in p.NAMES-{p.GPU}:
                with self.assertRaises(OSError) as error:api_bridge.call({'name':name})
                self.assertEqual(error.exception.errno,errno.EOPNOTSUPP)
        rows=[r for r in report['sensors'] if r['api']!=p.GPU]
        self.assertEqual(len(rows),8);self.assertTrue(all(r['celsius'] is None and not r['available'] for r in rows))
        self.assertTrue(all(r['status']=='unsupported_original_platform_dispatch' for r in rows))

    def test_no_substring_search_can_substitute_an_unrelated_sensor(self):
        with mock.patch.object(p,'snapshot',return_value=(telemetry(),[])),mock.patch.object(Path,'glob',side_effect=AssertionError('Unexpected hwmon label search')):
            with self.assertRaises(OSError) as error:api_bridge.call({'name':'Thermal_Read_GpuVrm_Temperature'})
        self.assertEqual(error.exception.errno,errno.EOPNOTSUPP)

    def test_inactive_and_out_of_range_values_are_explicitly_unavailable(self):
        for value in [0,126,255]:
            with self.subTest(value=value),mock.patch.object(p,'snapshot',return_value=(telemetry(value),[])):
                report=p.report();row=next(r for r in report['sensors'] if r['api']==p.GPU)
                self.assertEqual(row['raw_celsius'],value);self.assertIsNone(row['celsius'])
                self.assertFalse(report['any_sensor_available'])
                with self.assertRaises(OSError) as error:p.call(p.GPU,{})
                self.assertEqual(error.exception.errno,errno.ENODATA)

    def test_malformed_channel_is_not_a_zero_or_a_cpu_fallback(self):
        for value in [None,True,-1,256,64.0,float('nan'),'64']:
            with self.subTest(value=str(value)),mock.patch.object(p,'snapshot',return_value=(telemetry(value),[])):
                row=next(r for r in p.report()['sensors'] if r['api']==p.GPU)
                self.assertEqual(row['errno'],errno.EPROTO);self.assertIsNone(row['raw_celsius']);self.assertIsNone(row['celsius'])

    def test_legacy_interface_presence_withholds_the_unqualified_fallback(self):
        with mock.patch.object(p,'snapshot',return_value=(telemetry(64),['ASUS1000:00'])):
            row=next(r for r in p.report()['sensors'] if r['api']==p.GPU)
        self.assertFalse(row['available']);self.assertEqual(row['status'],'unqualified_legacy_interface')
        self.assertEqual(row['errno'],errno.EOPNOTSUPP)

    def test_provider_errors_do_not_claim_firmware_support_or_unsupported_roles(self):
        for code in [errno.EIO,errno.EBUSY,errno.EAGAIN,errno.EACCES]:
            with mock.patch.object(p,'snapshot',side_effect=OSError(code,'Provider failure')):
                report=p.report()
                with self.assertRaises(OSError) as error:p.call(p.GPU,{})
            self.assertEqual(error.exception.errno,code);self.assertFalse(report['provider_available'])
            self.assertTrue(all(r['status']=='provider_unavailable' and r['errno']==code for r in report['sensors']))

    def test_all_argument_checks_precede_io(self):
        with mock.patch.object(p,'report',side_effect=AssertionError('Unexpected read')):
            for name in p.NAMES:
                with self.assertRaises(ValueError):api_bridge.call({'name':name,'args':{'invented':True}})
                with self.assertRaises(ValueError):p.call(name,[])

    def test_actual_adapter_inputs_and_legacy_census(self):
        with tempfile.TemporaryDirectory() as temp:
            dmi,acpi,hw=fixture(Path(temp));(acpi/'ASUS1000:00').mkdir();(acpi/'PNP0C14:00').mkdir()
            raw,devices=snapshot(dmi,acpi,hw)
        self.assertEqual(raw,telemetry());self.assertEqual(devices,['ASUS1000:00'])

    def test_unqualified_model_bios_arch_or_ec_identity_is_not_decoded(self):
        for target,value in [('product_name','Other'),('bios_version','UP3404VA.302'),('protocol',True),('protocol',14),
                             ('vendor',130),('chip_id',1),('firmware_raw',[48,50]),('chip_name_raw',[True,53,55,49])]:
            with self.subTest(target=target),tempfile.TemporaryDirectory() as temp:
                dmi,acpi,hw=fixture(Path(temp));raw=telemetry()
                if target in ['product_name','bios_version']:(dmi/target).write_text(value)
                else:raw[target]=value;(hw/'ec_telemetry').write_text(json.dumps(raw))
                with self.assertRaises(OSError) as error:snapshot(dmi,acpi,hw)
                self.assertEqual(error.exception.errno,errno.EOPNOTSUPP)
        with tempfile.TemporaryDirectory() as temp:
            dmi,acpi,hw=fixture(Path(temp))
            with mock.patch.object(q.platform,'machine',return_value='aarch64'),self.assertRaises(OSError):q.snapshot(dmi,acpi)

    def test_missing_malformed_and_oversized_telemetry_is_not_accepted(self):
        for value in [None,'invalid','[]','x'*16385]:
            with self.subTest(value=str(value)[:15]),tempfile.TemporaryDirectory() as temp:
                dmi,acpi,hw=fixture(Path(temp))
                if value is None:(hw/'ec_telemetry').unlink()
                else:(hw/'ec_telemetry').write_text(value)
                with self.assertRaises(OSError):snapshot(dmi,acpi,hw)

    def test_manual_mode_and_mode_transition_are_not_hidden_by_cached_data(self):
        with tempfile.TemporaryDirectory() as temp:
            dmi,acpi,hw=fixture(Path(temp))
            for mode in ['0','1','invalid']:
                (hw/'pwm1_enable').write_text(mode)
                with self.assertRaises(OSError) as error:snapshot(dmi,acpi,hw)
                self.assertEqual(error.exception.errno,errno.EBUSY)
            read=q.text
            def flip(path,limit=16384):
                if path.name=='ec_telemetry':(hw/'pwm1_enable').write_text('1')
                return read(path,limit)
            (hw/'pwm1_enable').write_text('2')
            with mock.patch.object(q,'text',side_effect=flip),self.assertRaises(OSError) as error:snapshot(dmi,acpi,hw)
            self.assertEqual(error.exception.errno,errno.EBUSY)

    def test_changed_device_or_legacy_census_is_not_a_verified_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            dmi,acpi,hw=fixture(Path(temp))
            with mock.patch.object(q,'identity',side_effect=[(1,2),(1,3)]),self.assertRaises(OSError) as error:snapshot(dmi,acpi,hw)
            self.assertEqual(error.exception.errno,errno.EAGAIN)
            with mock.patch.object(q,'legacy_devices',side_effect=[[],['ASUS1000:00']]),self.assertRaises(OSError) as error:snapshot(dmi,acpi,hw)
            self.assertEqual(error.exception.errno,errno.EAGAIN)


if __name__=='__main__':unittest.main()
