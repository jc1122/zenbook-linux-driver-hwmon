# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import errno
import json
import tempfile
import unittest
from unittest import mock
import api_bridge
import hardware_status as status
import battery_diagnostics as battery
import compat


def policy(root,name='policy0',current='2000000',maximum='4600000'):
    p=root/name;p.mkdir();(p/'scaling_cur_freq').write_text(current);(p/'cpuinfo_max_freq').write_text(maximum)
    return p


class NativeStatusTests(unittest.TestCase):
    def test_frequency_aggregation_preserves_per_policy_units_and_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);policy(root);policy(root,'policy1','3000000','3400000')
            r=status.frequencies(root);self.assertTrue(r['available'])
            self.assertEqual(r['maximum_observed_policy_mhz'],3000)
            self.assertEqual(r['maximum_possible_policy_mhz'],4600)
            self.assertEqual(r['policies'][0]['current_mhz'],2000)

    def test_partial_policy_failure_never_pretends_to_be_a_global_maximum(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);policy(root);p=policy(root,'policy1');(p/'scaling_cur_freq').unlink()
            r=status.frequencies(root);self.assertIsNone(r['maximum_observed_policy_mhz'])
            self.assertEqual(r['maximum_possible_policy_mhz'],4600)
            self.assertEqual(r['policies'][0]['current_mhz'],2000)

    def test_missing_zero_bad_or_negative_frequencies_do_not_become_zero_mhz(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.assertIsNone(status.frequencies(root)['maximum_observed_policy_mhz'])
            p=policy(root)
            for raw in ('0','-1','nan','1.5','9999999999999999999',''):
                (p/'scaling_cur_freq').write_text(raw)
                self.assertIsNone(status.frequencies(root)['maximum_observed_policy_mhz'])
            self.assertEqual(status.frequencies(root/'missing')['errno'],errno.ENOENT)

    def test_changing_policy_identity_or_inventory_does_not_publish_aggregate(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=policy(root)
            with mock.patch.object(status,'identity',side_effect=[(1,1),(1,2)]):
                r=status.frequencies(root);self.assertIsNone(r['maximum_observed_policy_mhz'])
            with mock.patch.object(status,'policies',side_effect=[[p],[]]):
                r=status.frequencies(root);self.assertEqual(r['errno'],errno.EAGAIN)
                self.assertIsNone(r['maximum_possible_policy_mhz'])

    def test_driver_metadata_retains_real_zero_refcount_and_missing_is_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'version').write_text('1.2.3');(root/'refcnt').write_text('0')
            with mock.patch.object(status,'MODULE',root):
                self.assertEqual(api_bridge.call({'name':'GetDriverVersion'}),'1.2.3')
                self.assertEqual(api_bridge.call({'name':'GetRefCount'}),0)
                (root/'version').unlink()
                with self.assertRaises(FileNotFoundError):api_bridge.call({'name':'GetDriverVersion'})
            with mock.patch.object(status,'MODULE',root/'absent'),self.assertRaises(FileNotFoundError):status.driver_value('refcnt')

    def test_malformed_driver_values_and_replaced_module_are_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name,values in [('version',['','a b','\x00']),('refcnt',['','-1','0x10','false'])]:
                for raw in values:
                    (root/name).write_text(raw)
                    with mock.patch.object(status,'MODULE',root),self.assertRaises(OSError):status.driver_value(name)
            (root/'version').write_text('1.0.0')
            with mock.patch.object(status,'MODULE',root),mock.patch.object(status,'identity',side_effect=[(1,1),(1,2)]),self.assertRaises(OSError):status.driver_value('version')
        with self.assertRaises(ValueError):status.driver_value('parameters')

    def test_status_queries_reject_arguments_before_reading_hardware(self):
        for name in ('GetDriverVersion','GetRefCount','CPU_ReadCpuFrequency','CPU_ReadCpuMaxFrequency'):
            with self.assertRaises(ValueError):api_bridge.call({'name':name,'args':{'path':'/arbitrary'}})

    def test_signed_battery_current_distinguishes_minus_one_from_missing(self):
        for raw,wanted in [(0,0),(1,1),(32767,32767),(32768,-32768),(65535,-1)]:
            self.assertEqual(battery.signed_current(raw),wanted)
        for raw in (None,-1,65536,True,'65535'):self.assertIsNone(battery.signed_current(raw))
        front=compat.frontend()
        with mock.patch('field_reads.qualified_ec.snapshot',return_value=({'battery_current_mA_raw':65535},[])):
            self.assertEqual(front.api_field({'field':'ec.battery_current_mA'}),-1)
        with mock.patch('field_reads.qualified_ec.snapshot',return_value=({'battery_current_mA_raw':None},[])),self.assertRaises(OSError):
            front.api_field({'field':'ec.battery_current_mA'})


def reported():
    return {'schema':1,'cpu':0,'reference_mhz':100,
            'current':{'errno':0,'ratio':31,'mhz':3100,'raw_msr_hex':'0x0000242d00001f00'},
            'maximum':{'errno':0,'ratio':46,'mhz':4600,'raw_msr_hex':'0x2c2c2c2c2c2c2e2e'}}


class ReportedFrequencyTests(unittest.TestCase):
    def snapshot(self,data):
        with mock.patch.object(status.os,'open',return_value=11),mock.patch.object(status.os,'close') as close, \
             mock.patch.object(status.os,'read',return_value=data),mock.patch.object(status.native_oem,'device',return_value=Path('/qualified')):
            result=status.reported_snapshot()
        close.assert_called_once_with(11)
        return result

    def test_source_packet_and_export_values_are_independent_from_policy_maxima(self):
        result=self.snapshot(json.dumps(reported()).encode());self.assertTrue(result['available'])
        self.assertEqual(result['cpu'],0);self.assertIn('no mailbox or MSR writes',result['note'])
        with mock.patch.object(status,'reported_snapshot',return_value=result), \
             mock.patch.object(status,'frequencies',side_effect=AssertionError('No CPUFreq substitution')):
            self.assertEqual(api_bridge.call({'name':'CPU_ReadCpuFrequency'}),3100)
            self.assertEqual(api_bridge.call({'name':'CPU_ReadCpuMaxFrequency'}),4600)

    def test_independent_register_fault_does_not_hide_the_other_frequency(self):
        for field,name,other in [('current','CPU_ReadCpuFrequency','CPU_ReadCpuMaxFrequency'),('maximum','CPU_ReadCpuMaxFrequency','CPU_ReadCpuFrequency')]:
            data=reported();data[field].update(errno=errno.EIO,ratio=0,mhz=0)
            result=self.snapshot(json.dumps(data).encode());self.assertFalse(result['available']);self.assertIsNone(result[field]['mhz'])
            with mock.patch.object(status,'reported_snapshot',return_value=result):
                with self.assertRaises(OSError) as error:status.call(name,{})
                self.assertEqual(error.exception.errno,errno.EIO)
                self.assertGreater(status.call(other,{}),0)

    def test_unknown_bad_or_inconsistent_kernel_payloads_are_not_readings(self):
        changes=[('schema',True),('schema',2),('cpu',1),('reference_mhz',0),('reference_mhz',1001),('reference_mhz',True),('extra',1)]
        for key,value in changes:
            data=reported();data[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(OSError) as error:self.snapshot(json.dumps(data).encode())
            self.assertEqual(error.exception.errno,errno.EPROTO)
        for key,value in [('errno',-1),('errno',4096),('errno',True),('errno',5),('ratio',30),('mhz',3101),('mhz',True),('raw_msr_hex','0x0'),('raw_msr_hex','0x0000242d00000000')]:
            data=reported();data['current'][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(OSError):self.snapshot(json.dumps(data).encode())
        for raw in [b'{"schema":1,"schema":1}',b'[]',b'null',b'\xff',b'x'*4097]:
            with self.assertRaises(OSError):self.snapshot(raw)

    def test_missing_driver_attribute_retains_error_without_policy_fallback(self):
        with mock.patch.object(status.native_oem,'device',return_value=Path('/absent')), \
             mock.patch.object(status,'frequencies',side_effect=AssertionError('No fallback')):
            with self.assertRaises(FileNotFoundError):status.call('CPU_ReadCpuFrequency',{})
            result=status.reported_frequencies();self.assertFalse(result['available']);self.assertEqual(result['errno'],errno.ENOENT)


if __name__=='__main__':unittest.main()
