# SPDX-License-Identifier: GPL-2.0-only
import errno
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import compat
import linux_services as services


class WifiRateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.device('wlan0',4,1000,2000)

    def device(self,name,index,rx,tx):
        p=self.root/name;(p/'wireless').mkdir(parents=True,exist_ok=True)
        (p/'statistics').mkdir(exist_ok=True)
        for key,value in [('ifindex',index),('statistics/rx_bytes',rx),('statistics/tx_bytes',tx)]:
            (p/key).write_text(str(value))

    def sample(self,change,elapsed=.5,boot_elapsed=None,detailed=True):
        def pause(seconds):
            self.assertEqual(seconds,.25);change()
        times=iter([10,10,10+elapsed,10+elapsed]);boots=iter([100,100,100+(elapsed if boot_elapsed is None else boot_elapsed),100+(elapsed if boot_elapsed is None else boot_elapsed)])
        return services.wifi_byte_rates({'detailed':detailed},self.root,lambda:next(times),lambda:next(boots),pause)

    def test_uses_actual_elapsed_and_preserves_legacy_numeric_map(self):
        result=self.sample(lambda:self.device('wlan0',4,1200,2100))
        self.assertEqual(result['sample_seconds'],.5)
        row=result['interfaces'][0];self.assertTrue(row['available'])
        self.assertEqual((row['rx_bytes_per_second'],row['tx_bytes_per_second'],row['bytes_per_second']),(400,200,600))
        self.assertEqual(self.sample(lambda:self.device('wlan0',4,1400,2200),detailed=False),{'wlan0':600})

    def test_reset_or_invalid_counter_preserves_another_interface(self):
        self.device('wlan1',5,50,50)
        def change():
            self.device('wlan0',4,0,2100);self.device('wlan1',5,100,150)
        result=self.sample(change)
        self.assertEqual(result['rates_bytes_per_second'],{'wlan0':None,'wlan1':300})
        (self.root/'wlan0/statistics/rx_bytes').write_text('NaN')
        result=self.sample(lambda:None)
        self.assertEqual(result['interfaces'][0]['errno'],errno.EPROTO)
        self.assertEqual(result['rates_bytes_per_second']['wlan1'],0)

    def test_hotplug_and_reused_name_do_not_produce_rates(self):
        result=self.sample(lambda:self.device('wlan0',9,2000,3000))
        self.assertIsNone(result['rates_bytes_per_second']['wlan0'])
        result=self.sample(lambda:(self.root/'wlan0/wireless').rmdir())
        self.assertEqual(result['interfaces'][0]['errno'],errno.ENODEV)

    def test_suspend_long_gap_and_delayed_snapshot_are_unavailable(self):
        for elapsed,boot_elapsed in [(.5,10),(.01,.01),(31,31)]:
            with self.subTest(elapsed=elapsed,boot_elapsed=boot_elapsed):
                self.assertIsNone(self.sample(lambda:None,elapsed,boot_elapsed)['rates_bytes_per_second']['wlan0'])
        fake={'time':1,'boot_time':1,'read_seconds':.2,'interfaces':{'wlan0':{'rx':0,'tx':0,'identity':1}}}
        with patch.object(services,'wifi_counter_snapshot',side_effect=[fake,{**fake,'time':1.5,'boot_time':1.5}]):
            self.assertIsNone(services.wifi_byte_rates({},sleep=lambda _:None)['wlan0'])

    def test_absent_missing_and_out_of_range_counters_are_not_zero(self):
        (self.root/'wlan0/statistics/tx_bytes').unlink()
        self.assertIsNone(self.sample(lambda:None)['rates_bytes_per_second']['wlan0'])
        self.device('wlan0',4,2**64,0)
        self.assertIsNone(self.sample(lambda:None)['rates_bytes_per_second']['wlan0'])
        (self.root/'wlan0/wireless').rmdir()
        with self.assertRaises(OSError) as error:self.sample(lambda:None)
        self.assertEqual(error.exception.errno,errno.ENODEV)

    def test_strict_arguments_and_no_networkmanager_dependency(self):
        for args in [{'detailed':1},{'detailed':'yes'},{'interface':'wlan0'}]:
            with self.assertRaises(ValueError):compat.validate('WMIGetWiFiBytesPersec',args)
            with self.assertRaises(ValueError):services.wifi_byte_rates(args)
        with patch.object(services,'wifi',side_effect=AssertionError('No NetworkManager query')),patch.object(services,'wifi_byte_rates',return_value={'wlan0':0}) as read:
            self.assertEqual(services.call('WMIGetWiFiBytesPersec',{}),{'wlan0':0});read.assert_called_once_with({})


if __name__=='__main__':unittest.main()
