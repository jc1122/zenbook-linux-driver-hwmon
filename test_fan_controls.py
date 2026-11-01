# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
from types import SimpleNamespace
import errno
import tempfile
import unittest
from unittest import mock
import compat
import user_preferences

class FanControlsTests(unittest.TestCase):
    def test_complete_charge_percentage_range_and_immediate_vs_remembered_contract(self):
        front=SimpleNamespace(control=mock.Mock(return_value={'after':'100'}))
        with mock.patch.object(compat,'frontend',return_value=front),mock.patch.object(compat.remembered_controls,'set_and_remember') as remember:
            for percent in range(101):
                user_preferences.validate_value('battery_charge_limit_percent',percent)
                for name in ('WMISetBatteryHealth','WMISetBatteryHealthToUser'):
                    compat.validate(name,{'percent':percent});compat.normal_control(name,{'percent':percent})
                    if name=='WMISetBatteryHealth':
                        self.assertEqual(front.control.call_args.args[0].value,percent)
                    else:remember.assert_called_with(front,'charge-limit',percent)
            self.assertEqual(front.control.call_count,101);self.assertEqual(remember.call_count,101)
        for percent in (-1,101,True,1.5,None,'invalid'):
            for name in ('WMISetBatteryHealth','WMISetBatteryHealthToUser'):
                with self.assertRaises(ValueError):compat.validate(name,{'percent':percent})
            with self.assertRaises(ValueError):user_preferences.validate_value('battery_charge_limit_percent',percent)

    def test_every_byte_is_valid_and_stored_request_is_not_claimed_as_physical_application(self):
        with tempfile.TemporaryDirectory() as temp,mock.patch.object(compat.native_oem,'device',return_value=Path(temp)):
            path=Path(temp);(path/'pwm1_enable').write_text('2')
            for value in range(256):
                args={'duty':value};compat.validate('HealthyTable_SetFanPwmDuty',args)
                result=compat.normal_control('HealthyTable_SetFanPwmDuty',args)
                self.assertEqual(result['requested_pwm'],value);self.assertEqual(result['stored_pwm'],value)
                self.assertTrue(result['request_readback_verified']);self.assertTrue(result['deferred_while_automatic'])
                self.assertEqual((path/'pwm1_enable').read_text(),'2')
        for value in ('0','127','255','0x7f'):compat.validate('HealthyTable_SetFanPwmDuty',{'duty':value})
        for value in (-1,256,True,1.5,None,'invalid','0x100'):
            with self.assertRaises(ValueError):compat.validate('HealthyTable_SetFanPwmDuty',{'duty':value})

    def test_concurrent_request_readback_is_reported_separately(self):
        with tempfile.TemporaryDirectory() as temp,mock.patch.object(compat.native_oem,'device',return_value=Path(temp)), \
             mock.patch.object(Path,'read_text',side_effect=['64','2']):
            result=compat.normal_control('HealthyTable_SetFanPwmDuty',{'duty':0})
            self.assertEqual(result['requested_pwm'],0);self.assertEqual(result['stored_pwm'],64)
            self.assertFalse(result['request_readback_verified'])

    def test_test_mode_preserves_full_as_manual_and_auto_as_mode2(self):
        with tempfile.TemporaryDirectory() as temp,mock.patch.object(compat.native_oem,'device',return_value=Path(temp)):
            (Path(temp)/'pwm1').write_text('0')
            for requested in (True,False):
                result=compat.normal_control('HealthyTable_SetFanTestMode',{'manual':requested})
                self.assertTrue(result['mode_readback_verified']);self.assertEqual(result['requested_manual'],requested)
                self.assertEqual(result['requested_pwm'],0)
        for requested,mode in [(True,0),(True,2),(False,3)]:
            with tempfile.TemporaryDirectory() as temp,mock.patch.object(compat.native_oem,'device',return_value=Path(temp)), \
                 mock.patch.object(Path,'read_text',side_effect=[str(mode),'255']):
                result=compat.normal_control('HealthyTable_SetFanTestMode',{'manual':requested})
                self.assertEqual(result['mode_readback_verified'],requested and mode in (0,1))

    def test_CLI_percent_mapping_includes_zero_and_lower_half_and_restores_after_failure(self):
        front=compat.frontend();read=front.read
        def product(path,default=None):
            return 'Zenbook Flip UP3404VA_UP3404VA' if str(path)=='/sys/class/dmi/id/product_name' else read(path,default)
        with tempfile.TemporaryDirectory() as temp,mock.patch.object(front,'device',return_value=Path(temp)),mock.patch.object(front,'read',side_effect=product):
            path=Path(temp);(path/'fan1_input').write_text('3000')
            for percent in (0,1,49,50,99,100):
                result=front.control(SimpleNamespace(command='fan',value=str(percent)))
                self.assertEqual(result['requested_pwm'],(percent*255+50)//100);self.assertEqual(result['mode'],1)
            write=Path.write_text
            def failure(target,*args,**kwargs):
                if target.name=='pwm1':raise OSError(errno.EIO,'Injected duty write failure')
                return write(target,*args,**kwargs)
            with mock.patch.object(Path,'write_text',new=failure),self.assertRaises(OSError):
                front.control(SimpleNamespace(command='fan',value='1'))
            self.assertEqual((path/'pwm1_enable').read_text(),'2\n')

if __name__=='__main__':unittest.main()
