# SPDX-License-Identifier: GPL-2.0-only
import tempfile,unittest
from pathlib import Path
from unittest import mock
import battery_sbs as sbs


def sample():
    return {'schema':1,'device_type_hex':'5645','firmware_hex':'45560234004002000000000000',
            'maximum_cache_seconds':30,'age_milliseconds':0,
            'words':[0x31,0x6001,3000,8300,64536,65535,3000,8700,1,80,60,6000,7500,200,9000,7700]}


class BatterySBSTests(unittest.TestCase):
    def test_direct_signed_measurements_are_separate_from_charge_requests(self):
        r=sbs.decode(sample())
        self.assertEqual((r['current_amperes'],r['average_current_amperes']),(-1,-.001))
        self.assertEqual((r['voltage_volts'],r['requested_charging_voltage_volts']),(8.3,8.7))
        self.assertEqual(r['requested_charging_current_amperes'],3)
        self.assertAlmostEqual(r['temperature_celsius'],26.85)
        self.assertEqual(r['absolute_state_of_charge_percent'],60)
        self.assertEqual(r['state_of_charge_maximum_error_percent'],1)

    def test_capacity_modes_do_not_invent_energy_from_voltage(self):
        d=sample();r=sbs.decode(d)
        self.assertEqual(r['capacities']['remaining_milliamp_hours'],6000)
        self.assertIsNone(r['capacities']['remaining_watt_hours'])
        d['words'][1]|=0x8000;r=sbs.decode(d)
        self.assertIsNone(r['capacities']['remaining_milliamp_hours'])
        self.assertEqual(r['capacities']['remaining_watt_hours'],60)
        d['words'][11]=65535;self.assertIsNone(sbs.decode(d)['capacities']['remaining_watt_hours'])

    def test_maximum_request_sentinel_and_real_zero(self):
        d=sample()
        for i in (6,7):d['words'][i]=65535
        r=sbs.decode(d)
        for key in ('current','voltage'):
            self.assertTrue(r[f'requested_charging_{key}_is_maximum'])
        self.assertIsNone(r['requested_charging_current_amperes'])
        self.assertIsNone(r['requested_charging_voltage_volts'])
        for i in (4,5,6,7):d['words'][i]=0
        r=sbs.decode(d);self.assertEqual(r['current_amperes'],0)
        self.assertEqual(r['requested_charging_current_amperes'],0)

    def test_stale_wrong_identity_scaling_and_malformed_frames_rejected(self):
        for change in ({'age_milliseconds':30001},{'schema':True},{'device_type_hex':'0000'},
                       {'maximum_cache_seconds':5},{'words':None},{'words':[0]*15}):
            with self.subTest(change=change),self.assertRaises((ValueError,OSError)):sbs.decode({**sample(),**change})
        for i,value in ((0,0x131),(0,0x30),(2,0),(3,65535),(4,32768),(8,101),(15,0),(3,True),(1,-1)):
            d=sample();d['words'][i]=value
            with self.subTest(i=i,value=value),self.assertRaises((ValueError,OSError)):sbs.decode(d)

    def test_missing_driver_is_unavailable_not_a_zero_measurement(self):
        with tempfile.TemporaryDirectory() as temp,mock.patch('native_oem.device',return_value=Path(temp)):
            self.assertFalse(sbs.report()['available'])

    def test_cached_diagnostics_keep_failures_after_a_success_and_allow_no_attempts(self):
        empty={'schema':1,'cached_metadata_only':True,'attempts':0,'successes':0,'failures':0,'last_attempt':None,'last_failure':None}
        self.assertEqual(sbs.decode_diagnostics(empty)['attempts'],0)
        failure={'phase':'word-completion','result':-5,'operation_status':-5,'restoration_status':0,'age_milliseconds':1000,
                 'sentinel_attempt':0,'bracket':False,'command':0x1a,'completion_status':0,'bus_status':None}
        success={**failure,'phase':'complete','result':0,'operation_status':0,'age_milliseconds':0,'command':3,'completion_status':128,'bus_status':0,'bracket':True}
        d={**empty,'attempts':2,'successes':1,'failures':1,'last_attempt':success,'last_failure':failure}
        decoded=sbs.decode_diagnostics(d);self.assertEqual(decoded['last_failure']['completion_status'],0)
        with tempfile.TemporaryDirectory() as temp,mock.patch('native_oem.device',return_value=Path(temp)):
            p=Path(temp)/'battery_sbs_diagnostics';p.write_text(__import__('json').dumps(d))
            self.assertTrue(sbs.diagnostics()['available'])
            p.unlink();self.assertFalse(sbs.diagnostics()['available'])

    def test_diagnostic_corruption_is_never_a_clean_health_report(self):
        d={'schema':1,'cached_metadata_only':True,'attempts':0,'successes':0,'failures':0,'last_attempt':None,'last_failure':None}
        for change in ({'schema':True},{'cached_metadata_only':False},{'attempts':1},{'successes':True},{'last_failure':{}},{'failures':-1}):
            with self.subTest(change=change),self.assertRaises(ValueError):sbs.decode_diagnostics({**d,**change})
        trace={'phase':'word-completion','result':-5,'operation_status':-5,'restoration_status':0,'age_milliseconds':0,
               'sentinel_attempt':0,'bracket':False,'command':26,'completion_status':0,'bus_status':None}
        d.update(attempts=1,failures=1,last_attempt=trace,last_failure=trace)
        for change in ({'phase':'guessed'},{'result':0},{'operation_status':1},{'restoration_status':-5},
                       {'command':22},{'completion_status':True},{'sentinel_attempt':2},{'age_milliseconds':-1}):
            with self.subTest(change=change),self.assertRaises(ValueError):sbs.decode_diagnostics({**d,'last_attempt':{**trace,**change}})

    def test_retry_metadata_is_bounded_and_does_not_erase_initial_failure(self):
        failed={'phase':'word-completion','result':-5,'operation_status':-5,'restoration_status':0,'age_milliseconds':1000,
                'sentinel_attempt':0,'bracket':False,'command':26,'completion_status':64,'bus_status':None}
        success={**failed,'phase':'complete','result':0,'operation_status':0,'age_milliseconds':0,'bracket':True,'command':3,'completion_status':128,'bus_status':0}
        d={'schema':1,'cached_metadata_only':True,'attempts':2,'successes':1,'failures':1,'retries':1,'recovered_refreshes':1,
           'retry_limit':1,'retry_backoff_milliseconds':100,'last_attempt':success,'last_failure':failed}
        self.assertEqual(sbs.decode_diagnostics(d)['last_failure'],failed)
        for change in ({'retries':2},{'recovered_refreshes':2},{'retry_limit':2},{'retries':True},{'retry_backoff_milliseconds':-1}):
            with self.subTest(change=change),self.assertRaises(ValueError):sbs.decode_diagnostics({**d,**change})
        del d['retry_limit']
        with self.assertRaises(ValueError):sbs.decode_diagnostics(d)

    def test_software_observation_is_nonatomic_raw_metadata_and_cannot_hide_failure(self):
        failed={'phase':'word-completion','result':-5,'operation_status':-5,'restoration_status':0,'age_milliseconds':1000,
                'sentinel_attempt':0,'bracket':False,'command':26,'completion_status':64,'bus_status':None,
                'software_observation':{'result':0,'raw_hex':'82000100','atomic':False,'current_operation_proven':False}}
        d={'schema':1,'cached_metadata_only':True,'attempts':1,'successes':0,'failures':1,'last_attempt':failed,'last_failure':failed}
        self.assertEqual(sbs.decode_diagnostics(d)['last_failure']['result'],-5)
        for raw in ['00000101','ff000100']:
            failed['software_observation']['raw_hex']=raw;self.assertTrue(sbs.decode_diagnostics(d)['available'])
        for change in ({'result':True},{'raw_hex':'00'},{'raw_hex':'xy000100'},{'raw_hex':'00000200'},
                       {'atomic':True},{'current_operation_proven':True},{'result':-5}):
            s={**failed,'software_observation':{**failed['software_observation'],**change}}
            with self.subTest(change=change),self.assertRaises(ValueError):sbs.decode_diagnostics({**d,'last_attempt':s})
        failed['software_observation']={'result':-5,'raw_hex':None,'atomic':False,'current_operation_proven':False}
        self.assertTrue(sbs.decode_diagnostics(d)['available'])

    def test_native_word_values_keep_same_units_and_tag_the_actual_transport(self):
        r=sbs.decode({**sample(),'transport':'native_smbus_read_word'})
        old=sbs.decode(sample());self.assertEqual(r['transport'],'native_smbus_read_word')
        for name in ('voltage_volts','current_amperes','capacities','cycle_count','requested_charging_current_amperes'):
            self.assertEqual(r[name],old[name])
        with self.assertRaises(OSError):sbs.decode({**sample(),'transport':'guessed'})

    def test_native_status_is_distinct_from_old_combined_completion_and_software_copies(self):
        t={'phase':'complete','transport':'native_smbus_read_word','result':0,'operation_status':0,'restoration_status':0,'age_milliseconds':0,
           'sentinel_attempt':0,'bracket':True,'command':3,'completion_status':0,'bus_status':None,'worker_result':1,'software_observation':None}
        d={'schema':1,'transport':'native_smbus_read_word','cached_metadata_only':True,'attempts':1,'successes':1,'failures':0,'last_attempt':t,'last_failure':None}
        self.assertTrue(sbs.decode_diagnostics(d)['available'])
        for change in ({'completion_status':128},{'worker_result':None},{'worker_result':2},{'worker_result':True},
                       {'bus_status':0},{'transport':'legacy_i2c_combined_read_word'},{'software_observation':{}}):
            with self.subTest(change=change),self.assertRaises(ValueError):sbs.decode_diagnostics({**d,'last_attempt':{**t,**change}})
        failure={**t,'phase':'native-word-result','result':-5,'operation_status':-5,'worker_result':0}
        self.assertTrue(sbs.decode_diagnostics({**d,'attempts':2,'failures':1,'last_failure':failure})['available'])


if __name__=='__main__':unittest.main()
