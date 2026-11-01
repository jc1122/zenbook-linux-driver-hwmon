# SPDX-License-Identifier: GPL-2.0-only
import copy
import errno
import unittest
from unittest import mock
from pathlib import Path
import charger_adc


def packet():
    return {'schema':1,'words':[73,14,16387,45100,19524,13056,40,13056,19524,16387],
            'input_millivolts':19584,'input_microamps':1776000,'input_microwatts':34781184,
            'current_resolution_microamps':44400,'voltage_resolution_millivolts':96,
            'input_shunt_milliohms':10,'maximum_cache_seconds':2,'age_milliseconds':0}


class ChargerADCTests(unittest.TestCase):
    def test_hardware_adc_conversion_is_separate_from_pd_limit(self):
        row=charger_adc.decode(packet())
        self.assertEqual((row['voltage_volts'],row['current_amperes'],row['power_watts']),(19.584,1.776,34.781184))
        self.assertTrue(row['measurement'])
        self.assertNotIn('current_limit_amperes',row)

    def test_faults_identity_disabled_unplug_calibration_and_freshness(self):
        for key,value in [('schema',2),('input_shunt_milliohms',20),('age_milliseconds',2001),
                          ('input_microamps',888000),('input_microwatts',65000000),('age_milliseconds',True)]:
            bad=packet();bad[key]=value
            with self.subTest(key=key),self.assertRaises(OSError):charger_adc.decode(bad)
        for index,value in [(0,0),(1,15),(2,0),(3,45100|0x800),(4,0),(6,256),(7,13056+128)]:
            bad=copy.deepcopy(packet());bad['words'][index]=value
            with self.subTest(index=index),self.assertRaises(OSError):charger_adc.decode(bad)

    def test_non_object_json_is_an_unavailable_protocol_error(self):
        for raw in (b'[]',b'7',b'"x"',b'null'):
            with self.subTest(raw=raw),mock.patch.object(charger_adc.native_oem,'device',return_value=Path('/test')), \
                 mock.patch.object(charger_adc.os,'open',return_value=7),mock.patch.object(charger_adc.os,'close'), \
                 mock.patch.object(charger_adc.os,'read',return_value=raw):
                row=charger_adc.report()
            self.assertFalse(row['available']);self.assertEqual(row['errno'],errno.EPROTO)

    def test_sysfs_eagain_is_preserved_in_the_public_report(self):
        with mock.patch.object(charger_adc.native_oem,'device',return_value=Path('/test')), \
             mock.patch.object(charger_adc.os,'open',return_value=7), \
             mock.patch.object(charger_adc.os,'close') as close, \
             mock.patch.object(charger_adc.os,'read',side_effect=BlockingIOError(errno.EAGAIN,'Changing ADC')):
            row=charger_adc.report()
        self.assertFalse(row['available'])
        self.assertEqual(row['errno'],errno.EAGAIN)
        close.assert_called_once_with(7)

    def test_adc_zero_is_quantized_current_while_valid_voltage_is_required(self):
        data=packet();data['words'][6]=0;data['input_microamps']=0;data['input_microwatts']=0
        self.assertEqual(charger_adc.decode(data)['current_amperes'],0)
        data['words'][5]=data['words'][7]=0;data['input_millivolts']=0
        with self.assertRaises(OSError) as error:charger_adc.decode(data)
        self.assertEqual(error.exception.errno,errno.EPROTO)


if __name__=='__main__':unittest.main()
