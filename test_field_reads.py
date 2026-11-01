# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import errno
import json
import tempfile
import unittest
from unittest import mock
import api_bridge
import field_reads as f


class FieldReadTests(unittest.TestCase):
    def ec(self,raw):return mock.patch.object(f.qualified_ec,'snapshot',return_value=(raw,[]))

    def test_all60_routes_validate_arguments_before_reading(self):
        self.assertEqual(len(f.NAMES),60)
        for name in f.NAMES:
            with self.assertRaises(ValueError):api_bridge.call({'name':name,'args':{'unknown':1}})
        for index in [True,-1,256,'0',None,0.0]:
            with self.assertRaises(ValueError):f.validate('ProArt_Read_Fan',{'index':index})

    def test_fan_getters_work_in_manual_without_ec_telemetry(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)
            for name,value in [('name','zenbook_ec'),('fan1_input','6120'),('pwm1_enable','0'),('pwm1','255')]:
                (p/name).write_text(value)
            with mock.patch.object(f.native_oem,'device',return_value=p),mock.patch.object(f.qualified_ec,'snapshot',side_effect=AssertionError('Unrelated EC dependency')):
                self.assertEqual(f.call('HealthyTable_FanCounts',{}),1)
                self.assertEqual(f.call('HealthyTable_FanRPM',{}),6120)
                self.assertIs(f.call('HealthyTable_GetFanTestMode',{}),True)
                self.assertEqual(f.call('ProArt_Read_Fan',{'index':0}),6120)
                self.assertEqual(f.call('HealthyTable_Read_Fan',{})['rpm'],6120)
                self.assertEqual(f.call('HealthyTable_Read_Fan',{})['manual_pwm_minimum'],0)
                with self.assertRaises(OSError) as e:f.call('ProArt_Read_Fan',{'index':1})
                self.assertEqual(e.exception.errno,errno.ENODEV)
                for invalid in ['3','-1','', 'true']:
                    (p/'pwm1_enable').write_text(invalid)
                    with self.assertRaises(OSError):f.call('HealthyTable_GetFanTestMode',{})

    def test_unknown_fan_mode_does_not_hide_independent_rpm(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);(p/'name').write_text('zenbook_ec');(p/'fan1_input').write_text('0')
            with mock.patch.object(f.native_oem,'device',return_value=p):self.assertEqual(f.fan('fan.rpm'),0)

    def test_signed_charging_current_and_current_preserve_minus_one(self):
        for raw,wanted in [(0,0),(32767,32767),(32768,-32768),(65535,-1)]:
            with self.ec({'battery_charge_current_mA':raw,'battery_current_mA_raw':raw}):
                self.assertEqual(f.call('BatteryHealthyTable_ChargingCurrent',{}),wanted)
                self.assertEqual(f.call('Battery_Read_Current',{}),wanted)
        for raw in [None,True,-1,65536,'0']:
            with self.ec({'battery_charge_current_mA':raw}):
                with self.assertRaises(OSError):f.call('BatteryHealthyTable_ChargingCurrent',{})

    def test_battery_error_is_the_separate_status_bit7(self):
        for raw,wanted in [(0,False),(16,False),(128,True),(255,True)]:
            with self.ec({'battery_status_flags':raw}):self.assertIs(f.call('BatteryHealthyTable_BatteryError',{}),wanted)

    def test_full_charged_uses_bit4_not_other_flags_or_os_status(self):
        for raw,wanted in [(0,False),(16,True),(128,False),(255,True)]:
            with self.ec({'battery_status_flags':raw}):self.assertIs(f.call('BatteryHealthyTable_FullCharged',{}),wanted)

    def test_family_selector_is_not_ascii_firmware_version(self):
        for vendor,raw,wanted in [(2,b'01',65535),(128,b'01',32767),(128,b'FF',32767),(128,b'AB',0x4142),(128,b'AC',0x4143),(128,b'CF',0x4346),(128,b'G1',0x4731),(128,b'ab',0x6162)]:
            with self.ec({'vendor':vendor,'firmware_raw':list(raw)}):self.assertEqual(f.call('EC_ReadEcFwRev',{}),wanted)

    def test_numeric_chip_name_has_big_endian_source_packing(self):
        with self.ec({'chip_name_raw':list(b'1234')}):self.assertEqual(f.call('EC_ReadEcChipName',{}),0x31323334)

    def test_extended_chip_name_keeps_all14_bytes(self):
        raw=b'ABCD\0'+bytes(range(9))
        with mock.patch.object(f,'metadata',return_value={'schema':1,'data_hex':raw.hex()}):
            result=f.call('BatteryHealthyTable_ECChipName',{})
            self.assertEqual(result['data_hex'],raw.hex());self.assertEqual(result['text'],'ABCD')
        with mock.patch.object(f,'metadata',return_value={'schema':1,'data_hex':'31323334'}):
            with self.assertRaises(OSError):f.call('BatteryHealthyTable_ECChipName',{})

    def test_packed_manufacture_date_is_validated(self):
        with self.ec({'battery_manufacture_date_raw':(2024-1980)*512+2*32+29}):self.assertEqual(f.call('Battery_Read_ManufactureDate',{}),'2024-02-29')
        for raw in [0,(2023-1980)*512+2*32+29,65535,None]:
            with self.ec({'battery_manufacture_date_raw':raw}):
                with self.assertRaises(OSError):f.call('Battery_Read_ManufactureDate',{})

    def fixture_battery(self,p):
        for name,value in [('type','Battery'),('present','1'),('charge_now','850000'),('charge_full','1000000'),('charge_full_design','2000000'),('voltage_now','8123000'),('charge_control_end_threshold','100')]:
            (p/name).write_text(value)

    def test_battery_quantities_have_own_linux_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);self.fixture_battery(p)
            with mock.patch.object(f,'BATTERY',p),mock.patch.object(f.qualified_ec,'snapshot',side_effect=AssertionError('Unrelated EC dependency')):
                self.assertEqual(f.call('Battery_Read_DesignVoltage',{}),8123)
                self.assertEqual(f.call('Battery_Read_DesignedCapacity',{}),2000)
                self.assertEqual(f.call('Battery_Read_FullChargedCapcity',{}),1000)
                result=f.call('Battery_Read_CapacityPercentage',{})
                self.assertEqual(result['percent'],85);self.assertEqual(result['legacy_bucket_percent'],90)
                self.assertEqual(f.call('WMIGetBatteryHealth',{}),100);self.assertIs(f.call('WMICheckBatteryHealthSupport',{}),True)
                (p/'charge_control_end_threshold').unlink();self.assertIs(f.call('WMICheckBatteryHealthSupport',{}),False)

    def test_percentage_bucket_boundaries_and_above_full(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);self.fixture_battery(p)
            for current,bucket in [(0,0),(49999,0),(50000,10),(849999,80),(850000,90),(1050000,110)]:
                (p/'charge_now').write_text(str(current))
                result=f.battery_counter('Battery_Read_CapacityPercentage',p)
                self.assertEqual(result['legacy_bucket_percent'],bucket)
            (p/'charge_full').write_text('0')
            with self.assertRaises(OSError):f.battery_counter('Battery_Read_CapacityPercentage',p)

    def test_battery_counter_change_or_denial_preserves_error(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);self.fixture_battery(p)
            with mock.patch.object(f,'unsigned',side_effect=[100,1000,101,1000]):
                with self.assertRaises(OSError) as e:f.battery_counter('Battery_Read_CapacityPercentage',p)
                self.assertEqual(e.exception.errno,errno.EAGAIN)
            with mock.patch.object(f,'BATTERY',p),mock.patch.object(f,'unsigned',side_effect=PermissionError(errno.EACCES,'Denied')):
                with self.assertRaises(PermissionError):f.charge_limit(True)

    def test_quiet_support_distinguishes_supported_and_current_state(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);(p/'platform_profile_choices').write_text('low-power balanced performance');(p/'platform_profile').write_text('balanced')
            with mock.patch.object(f,'PROFILE',p),mock.patch.object(f.qualified_ec,'snapshot',side_effect=AssertionError('Unrelated EC dependency')):
                result=f.call('WMICheckQuietFanSupport',{})
                self.assertTrue(result['supported']);self.assertFalse(result['quiet_enabled'])
                self.assertEqual(f.call('WMIGetQuietFan',{}),'balanced')
                (p/'platform_profile').write_text('low-power');self.assertTrue(f.call('WMICheckQuietFanSupport',{})['quiet_enabled'])
                (p/'platform_profile').write_text('bogus')
                with self.assertRaises(OSError):f.call('WMIGetQuietFan',{})

    def test_rapl_resolves_constraint_names_without_ec(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'intel-rapl:7';p.mkdir();(p/'name').write_text('package-0')
            for index,name,watts in [(9,'long_term',28),(3,'short_term',0)]:
                (p/f'constraint_{index}_name').write_text(name);(p/f'constraint_{index}_power_limit_uw').write_text(str(watts*1000000))
            with mock.patch.object(f,'POWERCAP',root),mock.patch.object(f.qualified_ec,'snapshot',side_effect=AssertionError('Unrelated EC dependency')):
                self.assertEqual(f.call('Thermal_Read_CpuDptf_PowerLimit1',{}),28)
                self.assertEqual(f.call('Thermal_Read_CpuDptf_PowerLimit2',{}),0)

    def zone(self,root,name,enabled,limits):
        p=root/name;p.mkdir();(p/'name').write_text('package-0');(p/'enabled').write_text(enabled)
        for index,(constraint,watts) in enumerate(limits):
            (p/f'constraint_{index}_name').write_text(constraint);(p/f'constraint_{index}_power_limit_uw').write_text(str(watts*1000000))
            (p/f'constraint_{index}_time_window_us').write_text('2440')
        return p

    def test_power_limits_report_both_interfaces_and_lowest_enabled(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            self.zone(root,'intel-rapl:0','1',[('long_term',200),('short_term',45)])
            self.zone(root,'intel-rapl-mmio:0','1',[('long_term',35),('short_term',25)])
            (root/'intel-rapl:0:0').mkdir();(root/'intel-rapl:0:0/name').write_text('core')
            r=f.power_limits(root)
            self.assertEqual([z['interface'] for z in r['zones']],['msr','mmio'])
            self.assertEqual((r['lowest_enabled_long_term_watts'],r['lowest_enabled_short_term_watts']),(35,25))
            with mock.patch.object(f,'POWERCAP',root):self.assertEqual(f.call('Thermal_Read_CpuDptf_PowerLimit1',{}),200)
            (root/'intel-rapl-mmio:0/enabled').write_text('0')
            self.assertEqual(f.power_limits(root)['lowest_enabled_long_term_watts'],200)

    def test_power_limit_zone_error_withholds_lowest_but_keeps_other_zone(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.zone(root,'intel-rapl:0','1',[('long_term',200)])
            bad=self.zone(root,'intel-rapl-mmio:0','1',[('long_term',35)]);(bad/'constraint_0_power_limit_uw').write_text('bogus')
            r=f.power_limits(root)
            self.assertEqual(len(r['zones']),1);self.assertEqual(r['zone_errors'][0]['errno'],errno.EPROTO)
            self.assertIsNone(r['lowest_enabled_long_term_watts'])
            empty=Path(temp)/'empty';empty.mkdir()
            with self.assertRaises(OSError) as e:f.power_limits(empty)
            self.assertEqual(e.exception.errno,errno.ENODEV)

    def test_cache_queries_preserve_access_and_firmware_errors(self):
        for name in f.ROOT_READS:
            with mock.patch.object(f.os,'geteuid',return_value=1000):
                with self.assertRaises(PermissionError):api_bridge.call({'name':name})
        with mock.patch.object(f.os,'geteuid',return_value=0),mock.patch.object(f,'metadata',side_effect=OSError(errno.EIO,'Firmware cache error')):
            with self.assertRaises(OSError) as e:f.call('BatteryHealthyTable_BatteryInformation',{})
            self.assertEqual(e.exception.errno,errno.EIO)

    def test_cache_payload_requires_complete_ready_stable_kernel_frame(self):
        data={'schema':1,'status':0x10,'timeout_flags':0,'ready_bit':0x10,'refresh_requested':True,'data_hex':bytes(range(32)).hex()}
        with mock.patch.object(f.os,'geteuid',return_value=0):
            with mock.patch.object(f,'metadata',return_value=data):self.assertTrue(f.call('BatteryHealthyTable_BatteryInformation',{})['opaque'])
            for key,bad in [('data_hex','00'*31),('status',0x50),('status',0x90),('status',0),('schema',True),('refresh_requested',1),('ready_bit',0x20)]:
                with mock.patch.object(f,'metadata',return_value={**data,key:bad}):
                    with self.assertRaises(OSError):f.call('BatteryHealthyTable_BatteryInformation',{})

    def test_pf_alarm_uses_only_same_cache_status_bits(self):
        for status,wanted in [(0,False),(0x80,True),(0xc0,False),(0x40,False)]:
            with mock.patch.object(f,'metadata',return_value={'schema':1,'status':status,'timeout_flags':0}),mock.patch.object(f.qualified_ec,'snapshot',side_effect=AssertionError('BatteryError is unrelated')):
                self.assertIs(f.call('BatteryHealthy_Check_PFalarm',{}),wanted)

    def test_pf_cache_value_preserves_all_four_source_bytes(self):
        data={'schema':1,'status':0x20,'timeout_flags':0,'ready_bit':0x20,'refresh_requested':False,'data_hex':'12345678'}
        with mock.patch.object(f.os,'geteuid',return_value=0),mock.patch.object(f,'metadata',return_value=data):self.assertEqual(f.call('BatteryHealthy_Read_PFStatus',{}),0x78563412)


if __name__=='__main__':unittest.main()
