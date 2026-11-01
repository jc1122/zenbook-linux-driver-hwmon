# SPDX-License-Identifier: GPL-2.0-only
import errno
import json
import os
from pathlib import Path
import stat
import struct
import tempfile
import types
import unittest
from unittest import mock
import api_bridge
import gpu_usage as gpu
import linux_services
import tablet_mode as tablet


class GpuTests(unittest.TestCase):
    def test_actual_zero_fraction_and_full_are_not_clamped_or_summed(self):
        for busy,wanted in [(0,0),(125000000,50),(250000000,100)]:
            result=gpu.counter_result((100,10,10),(100+busy,250000010,250000010),.25,.25)
            self.assertEqual(result['percent'],wanted);self.assertTrue(result['available'])
            self.assertEqual(result['busy_nanoseconds'],busy);self.assertFalse(result['multiplexed'])

    def test_invalid_reset_zero_multiplexed_or_overshoot_is_not_idle_or_full(self):
        for before,after in [((1,0,0),(0,250000000,250000000)),((0,0,0),(0,0,0)),
                             ((0,0,0),(5,250000000,200000000)),((0,0,0),(0,1,2)),
                             ((0,0,0),(250000001,250000000,250000000)),((0,0,0),(0,100000000,100000000)),
                             ((0,0,1),(0,250000000,250000001))]:
            with self.subTest(before=before,after=after),self.assertRaises(OSError):gpu.counter_result(before,after,.25,.25)

    def test_delayed_suspended_nonfinite_intervals_are_unavailable(self):
        for elapsed,boot in [(0,0),(.01,.01),(6,6),(.25,.5),(float('nan'),.25),(.25,float('inf'))]:
            with self.subTest(elapsed=elapsed,boot=boot),self.assertRaises(OSError):
                gpu.counter_result((0,0,0),(0,250000000,250000000),elapsed,boot)

    def fixture(self,root,names=('rcs0-busy','vcs0-busy')):
        p=root/'i915';(p/'events').mkdir(parents=True);(p/'type').write_text('30');(p/'cpumask').write_text('0')
        for i,name in enumerate(names):
            (p/'events'/name).write_text(f'config=0x{i:x}');(p/'events'/(name+'.unit')).write_text('ns')
        return p

    def test_initial_packet_failure_closes_fd_and_preserves_other_engine(self):
        with tempfile.TemporaryDirectory() as temp:
            pmu=self.fixture(Path(temp))
            with mock.patch.object(gpu,'open_event',side_effect=[10,11]),mock.patch.object(gpu,'packet',side_effect=[OSError(errno.EPROTO,'short'),(0,0,0),(100000000,250000000,250000000)]),mock.patch.object(gpu.os,'close') as close:
                rows=gpu.pmu_usage(pmu,clock=iter([0,0,.25]).__next__,boot_clock=iter([0,0,.25]).__next__,sleep=lambda _:None)
            self.assertFalse(rows[0]['available']);self.assertIsNone(rows[0]['percent']);self.assertEqual(rows[1]['percent'],40)
            self.assertEqual(close.call_args_list,[mock.call(10),mock.call(11)])

    def test_fixed_pmu_metadata_no_unknown_unit_or_negative_config(self):
        for value,unit in [('config=0x0','cycles'),('config=-1','ns'),('config=0x10000000000000000','ns')]:
            with tempfile.TemporaryDirectory() as temp:
                pmu=self.fixture(Path(temp),('rcs0-busy',));(pmu/'events/rcs0-busy').write_text(value);(pmu/'events/rcs0-busy.unit').write_text(unit)
                with mock.patch.object(gpu,'open_event') as opened:rows=gpu.pmu_usage(pmu)
                opened.assert_not_called();self.assertIsNone(rows[0]['percent'])

    def test_short_counter_packet_is_explicit_and_drm_bad_value_not_zero(self):
        with mock.patch.object(gpu.os,'read',return_value=b'\0'*16),self.assertRaises(OSError) as err:gpu.packet(1)
        self.assertEqual(err.exception.errno,errno.EPROTO)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name,value in [('card0','0'),('card1','101'),('card2','broken')]:
                p=root/name/'device';p.mkdir(parents=True);(p/'gpu_busy_percent').write_text(value)
            result=gpu.report(root,root/'no-pmu')
            self.assertTrue(result['available']);self.assertEqual([r['percent'] for r in result['engines']],[0,None,None])

    def test_pmu_no_access_not_false_idle_and_native_empty_arguments(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'drm').mkdir();self.fixture(root)
            with mock.patch.object(gpu,'open_event',side_effect=PermissionError(errno.EACCES,'denied')):
                result=gpu.report(root/'drm',root)
            self.assertFalse(result['available']);self.assertTrue(all(r['errno']==errno.EACCES for r in result['engines']))
        for name in ('WMIGetGPUUsg','System_Read_TabletMode'):
            with self.assertRaises(ValueError):api_bridge.call({'name':name,'args':{'unexpected':1}})

    def drm_fixture(self,root,value='31'):
        card=root/'card0';(card/'device').mkdir(parents=True);(card/'device/gpu_busy_percent').write_text(value)
        return card

    def pmu_row(self):
        return {'engine':'rcs0-busy','pmu':'i915','available':True,'percent':42,
                'busy_nanoseconds':105000000,'sample_seconds':.25,'time_enabled_seconds':.25,'time_running_seconds':.25,'multiplexed':False}

    def test_DRM_and_i915_readings_are_both_preserved_with_separate_providers(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.drm_fixture(root/'drm');self.fixture(root/'pmu')
            with mock.patch.object(gpu,'pmu_usage',return_value=[self.pmu_row()]) as read:result=gpu.report(root/'drm',root/'pmu')
        read.assert_called_once();self.assertEqual([r['percent'] for r in result['engines']],[31,42])
        self.assertEqual([r['provider'] for r in result['engines']],['drm_busy','i915_pmu']);self.assertTrue(result['provider_coverage_complete'])
        self.assertNotIn('total_percent',result)

    def test_failed_DRM_counter_does_not_hide_working_i915_PMU(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.drm_fixture(root/'drm','101');self.fixture(root/'pmu')
            with mock.patch.object(gpu,'pmu_usage',return_value=[self.pmu_row()]):result=gpu.report(root/'drm',root/'pmu')
        self.assertTrue(result['available']);self.assertFalse(result['provider_coverage_complete'])
        self.assertIsNone(result['engines'][0]['percent']);self.assertEqual(result['engines'][1]['percent'],42)

    def test_working_DRM_counter_survives_i915_read_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.drm_fixture(root/'drm');self.fixture(root/'pmu')
            with mock.patch.object(gpu,'pmu_usage',side_effect=OSError(errno.EACCES,'PMU denied')):result=gpu.report(root/'drm',root/'pmu')
        self.assertTrue(result['available']);self.assertEqual(result['engines'][0]['percent'],31)
        self.assertEqual(result['engines'][1]['errno'],errno.EACCES);self.assertFalse(result['provider_coverage_complete'])

    def test_provider_discovery_error_preserves_other_available_measurements(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.drm_fixture(root/'drm');original=gpu.census
            def census(path,pattern):
                if path==root/'pmu':raise OSError(errno.EACCES,'Discovery denied')
                return original(path,pattern)
            with mock.patch.object(gpu,'census',side_effect=census):result=gpu.report(root/'drm',root/'pmu')
        self.assertTrue(result['available']);self.assertEqual(result['engines'][0]['percent'],31)
        self.assertEqual(result['provider_errors'][0]['errno'],errno.EACCES);self.assertFalse(result['provider_coverage_complete'])

    def test_replaced_DRM_identity_before_publication_invalidates_only_that_value(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);card=self.drm_fixture(root/'drm');self.fixture(root/'pmu')
            def replace(_):
                card.rename(root/'old-card');self.drm_fixture(root/'drm','90');return [self.pmu_row()]
            with mock.patch.object(gpu,'pmu_usage',side_effect=replace):result=gpu.report(root/'drm',root/'pmu')
        self.assertTrue(result['available']);self.assertEqual(result['engines'][0]['errno'],errno.EAGAIN)
        self.assertIsNone(result['engines'][0]['percent']);self.assertEqual(result['engines'][1]['percent'],42)

    def test_replaced_PMU_identity_drops_old_measurement_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.drm_fixture(root/'drm');pmu=self.fixture(root/'pmu')
            def replace(_):pmu.rename(root/'old-pmu');self.fixture(root/'pmu');return [self.pmu_row()]
            with mock.patch.object(gpu,'pmu_usage',side_effect=replace):result=gpu.report(root/'drm',root/'pmu')
        self.assertEqual(result['engines'][0]['percent'],31);self.assertEqual(result['engines'][1]['errno'],errno.EAGAIN)
        for key in ('busy_nanoseconds','sample_seconds','time_enabled_seconds','time_running_seconds','multiplexed'):
            self.assertNotIn(key,result['engines'][1])

    def test_changed_provider_census_keeps_readings_but_marks_coverage_partial(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'drm').mkdir();self.fixture(root/'pmu')
            def add(_):(root/'pmu/i915_0000_01_00_0').mkdir();return [self.pmu_row()]
            with mock.patch.object(gpu,'pmu_usage',side_effect=add):result=gpu.report(root/'drm',root/'pmu')
        self.assertTrue(result['available']);self.assertEqual(result['engines'][0]['percent'],42)
        self.assertFalse(result['provider_coverage_complete']);self.assertEqual(result['provider_errors'][0]['errno'],errno.EAGAIN)

    def test_known_empty_and_failed_provider_discovery_remain_distinct(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'drm').mkdir();(root/'pmu').mkdir()
            with self.assertRaises(OSError) as empty:gpu.report(root/'drm',root/'pmu')
            self.assertEqual(empty.exception.errno,errno.ENODEV)
            with mock.patch.object(gpu,'census',side_effect=OSError(errno.EACCES,'Denied')),self.assertRaises(OSError) as denied:gpu.report(root/'drm',root/'pmu')
            self.assertEqual(denied.exception.errno,errno.EACCES)


    def test_intel_card_without_busy_counter_adds_no_row_and_keeps_PMU_coverage(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'drm/card1/device').mkdir(parents=True);self.fixture(root/'pmu')
            with mock.patch.object(gpu,'pmu_usage',return_value=[self.pmu_row()]):result=gpu.report(root/'drm',root/'pmu')
        self.assertEqual([r['provider'] for r in result['engines']],['i915_pmu'])
        self.assertTrue(result['provider_coverage_complete']);self.assertTrue(result['all_readings_available'])
        self.assertEqual(result['source'],'i915 perf PMU');self.assertEqual(result['requested_sample_seconds'],.25)

    def test_DRM_read_error_is_explicit_row_and_missing_DRM_root_keeps_PMU(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.drm_fixture(root/'drm');self.fixture(root/'pmu')
            original=Path.read_text
            def denied(path,*a,**k):
                if path.name=='gpu_busy_percent':raise PermissionError(errno.EACCES,'denied')
                return original(path,*a,**k)
            with mock.patch.object(Path,'read_text',denied),mock.patch.object(gpu,'pmu_usage',return_value=[self.pmu_row()]):
                result=gpu.report(root/'drm',root/'pmu')
            self.assertEqual(result['engines'][0]['errno'],errno.EACCES);self.assertFalse(result['provider_coverage_complete'])
            with mock.patch.object(gpu,'pmu_usage',return_value=[self.pmu_row()]):missing=gpu.report(root/'absent',root/'pmu')
        self.assertEqual([r['percent'] for r in missing['engines']],[42]);self.assertTrue(missing['provider_coverage_complete'])

    def test_DRM_only_report_has_no_PMU_interval(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.drm_fixture(root/'drm');result=gpu.report(root/'drm',root/'no-pmu')
        self.assertNotIn('requested_sample_seconds',result);self.assertEqual(result['source'],'DRM driver busy percentage')

    def test_non_ASCII_metadata_is_local_protocol_error_not_lost_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);card=self.drm_fixture(root/'drm');(card/'device/gpu_busy_percent').write_bytes(b'\xff');pmu=self.fixture(root/'pmu')
            with mock.patch.object(gpu,'pmu_usage',return_value=[self.pmu_row()]):result=gpu.report(root/'drm',root/'pmu')
            self.assertEqual(result['engines'][0]['errno'],errno.EPROTO);self.assertEqual(result['engines'][1]['percent'],42)
            (pmu/'events/vcs0-busy').write_bytes(b'config=\xff')
            with mock.patch.object(gpu,'open_event',side_effect=PermissionError(errno.EACCES,'denied')):rows=gpu.pmu_usage(pmu)
            self.assertEqual([r['errno'] for r in rows],[errno.EACCES,errno.EPROTO])
            (pmu/'type').write_bytes(b'\xff');result=gpu.report(root/'drm',root/'pmu')
        self.assertEqual(result['engines'][1]['errno'],errno.EPROTO);self.assertNotIn('engine',result['engines'][1])
        self.assertFalse(result['provider_coverage_complete'])

    def test_one_unavailable_engine_keeps_provider_coverage_but_not_all_readings(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'drm').mkdir();self.fixture(root/'pmu')
            bad=gpu.failed({'engine':'vcs0-busy','pmu':'i915'},OSError(errno.ENODATA,'multiplexed'))
            with mock.patch.object(gpu,'pmu_usage',return_value=[self.pmu_row(),bad]):result=gpu.report(root/'drm',root/'pmu')
        self.assertTrue(result['provider_coverage_complete']);self.assertFalse(result['all_readings_available'])

    def test_publication_guard_keeps_original_error_of_failed_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'drm').mkdir();pmu=self.fixture(root/'pmu')
            bad=gpu.failed({'engine':'vcs0-busy','pmu':'i915'},OSError(errno.ENODATA,'multiplexed'))
            def replace(_):pmu.rename(root/'old-pmu');self.fixture(root/'pmu');return [self.pmu_row(),bad]
            with mock.patch.object(gpu,'pmu_usage',side_effect=replace):result=gpu.report(root/'drm',root/'pmu')
        self.assertEqual([r['errno'] for r in result['engines']],[errno.EAGAIN,errno.ENODATA])
        self.assertFalse(result['provider_coverage_complete']);self.assertEqual(result['provider_errors'][0]['errno'],errno.EAGAIN)

    def test_bridge_publishes_provider_fields(self):
        value={'available':True,'engines':[],'source':'i915 perf PMU','provider_coverage_complete':True,'all_readings_available':True,'provider_errors':[]}
        with mock.patch.object(gpu,'report',return_value=value),mock.patch('os.geteuid',return_value=0):result=api_bridge.call({'name':'WMIGetGPUUsg'})
        for key in ('provider_coverage_complete','all_readings_available','provider_errors'):self.assertIn(key,result)


class TabletTests(unittest.TestCase):
    def fixture(self,root,values):
        for i,value in enumerate(values):
            p=root/f'event{i}'/'device/capabilities';p.mkdir(parents=True);(p/'sw').write_text(value)

    def test_only_advertised_switch_is_opened_and_known_false_is_valid(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.fixture(root,['0','1','2','140'])
            with mock.patch.object(tablet,'read_switch',return_value=False) as read:
                result=tablet.report(root,root)
            self.assertIs(result['tablet_mode'],False);self.assertTrue(result['complete']);self.assertEqual(len(result['switches']),1)
            read.assert_called_once_with(root/'event2',root)

    def test_partial_negative_unknown_and_positive_survives_other_unreadable_switch(self):
        for state,expected in [(False,None),(True,True)]:
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);self.fixture(root,['2','2'])
                with mock.patch.object(tablet,'read_switch',side_effect=[state,PermissionError(errno.EACCES,'denied')]):
                    result=tablet.report(root,root)
                self.assertIs(result['tablet_mode'],expected);self.assertFalse(result['complete']);self.assertEqual(result['available'],state)

    def test_missing_malformed_caps_and_no_switch_are_not_off(self):
        for raw in ['bad!','', '0']:
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);self.fixture(root,[raw]);result=tablet.report(root,root)
                self.assertFalse(result['available']);self.assertIsNone(result['tablet_mode'])
        with mock.patch.object(tablet,'report',return_value={'available':False,'switches':[{'available':False,'errno':errno.EACCES,'error':'denied'}]}),self.assertRaises(OSError) as err:tablet.value()
        self.assertEqual(err.exception.errno,errno.EACCES)

    def test_fixed_ioctl_state_only_and_descriptor_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'event0';path.mkdir();(path/'dev').write_text('13:64')
            def ioctl(fd,request,buffer,mutable):
                self.assertEqual(fd,10);self.assertTrue(mutable);buffer[0]=2
            with mock.patch.object(tablet.os,'open',return_value=10) as opened,mock.patch.object(tablet.os,'fstat',return_value=types.SimpleNamespace(st_mode=stat.S_IFCHR,st_rdev=os.makedev(13,64))),mock.patch.object(tablet.fcntl,'ioctl',side_effect=ioctl) as query,mock.patch.object(tablet.os,'close') as close,mock.patch.object(tablet.os,'read') as read:
                self.assertIs(tablet.read_switch(path,Path(temp)),True)
            self.assertEqual([c.args[1] for c in query.call_args_list],[0x80084525,0x8008451b]);read.assert_not_called();close.assert_called_once_with(10)
            self.assertEqual(opened.call_args.args[1],os.O_RDONLY|os.O_NONBLOCK|os.O_CLOEXEC|os.O_NOFOLLOW)

    def test_device_number_or_capability_change_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.fixture(root,['2'])
            with mock.patch.object(tablet,'switches',side_effect=[True,False]),mock.patch.object(tablet,'read_switch',return_value=False):
                result=tablet.report(root,root)
            self.assertIsNone(result['tablet_mode']);self.assertEqual(result['switches'][0]['errno'],errno.EAGAIN)
            (root/'event0/dev').write_text('13:64')
            with mock.patch.object(tablet.os,'open',return_value=10),mock.patch.object(tablet.os,'fstat',return_value=types.SimpleNamespace(st_mode=stat.S_IFCHR,st_rdev=os.makedev(13,65))),mock.patch.object(tablet.os,'close') as close,self.assertRaises(OSError):tablet.read_switch(root/'event0',root)
            close.assert_called_once_with(10)

    def test_non_tablet_device_replaced_by_tablet_cannot_produce_false_off(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.fixture(root,['0','2'])
            with mock.patch.object(tablet,'switches',side_effect=[False,True,True,True]),mock.patch.object(tablet,'read_switch',return_value=False),self.assertRaises(OSError) as err:
                tablet.report(root,root)
            self.assertEqual(err.exception.errno,errno.EAGAIN)


if __name__=='__main__':unittest.main()
