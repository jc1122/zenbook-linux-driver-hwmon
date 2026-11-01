# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import errno
import json
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
import compat
import native_oem

class CompatibilityTests(unittest.TestCase):
    def test_ec_mutations_only_plan_without_explicit_apply(self):
        for name in native_oem.MUTATIONS:
            args={'address_space':'healthytable','bank':6,'register':0x36,'value':1}
            with mock.patch.object(native_oem.Path,'read_text',return_value='test-device'),mock.patch.object(native_oem,'rpc') as rpc,\
                 mock.patch.object(native_oem,'raw_ec_write_enabled',return_value=True):
                result=native_oem.call(name,args)
            self.assertFalse(result['applied']);self.assertEqual(len(result['expected_sha256']),64);rpc.assert_not_called()
    def test_unreviewed_ec_apply_never_reaches_hardware(self):
        with mock.patch.object(native_oem.Path,'read_text',return_value='test-device'),mock.patch.object(native_oem,'rpc') as rpc:
            with self.assertRaises(RuntimeError):native_oem.call('Adapter_Clear_Charger_Data',{},True,'bad')
        rpc.assert_not_called()
    def test_oem_plans_show_actual_monitor_encoding_and_flag_clear_variants(self):
        with mock.patch.object(native_oem.Path,'read_text',return_value='test-device'):
            for value,encoded in ((0,5),(1,0x85)):
                plan=native_oem.mutation_plan('Power_Set_Monitor_PowerDropped',{'value':value})
                self.assertEqual(plan['recipe_revision'],2);self.assertEqual(plan['protocol_recipe']['encoded_value'],encoded)
                self.assertEqual(plan['protocol_recipe']['minimum_version'],19)
            flag=native_oem.mutation_plan('Adapter_Read_Power_Data_Flag',{})['protocol_recipe']
            self.assertEqual(flag['clear_versions14_to23'],{'register':1,'value':0})
            self.assertEqual(flag['clear_version24_or_newer']['register'],0x35)
    def test_previous_recipe_digest_cannot_authorize_corrected_operation(self):
        import hashlib
        with mock.patch.object(native_oem.Path,'read_text',return_value='test-device'),mock.patch.object(native_oem,'rpc') as rpc:
            plan=native_oem.mutation_plan('Power_Set_Monitor_PowerDropped',{'value':1})
            legacy={k:v for k,v in plan.items() if k not in ('expected_sha256','recipe_revision','protocol_recipe')}
            old_digest=hashlib.sha256(json.dumps(legacy,sort_keys=True).encode()).hexdigest()
            with self.assertRaises(RuntimeError):native_oem.call('Power_Set_Monitor_PowerDropped',{'value':1},True,old_digest)
            rpc.assert_not_called()
    def test_raw_reads_and_writes_require_their_exact_native_parameters(self):
        base={'address_space':'healthytable','bank':2,'register':0x30}
        self.assertEqual(native_oem.raw_index(base),0x230)
        self.assertEqual(native_oem.raw_index({**base,'value':1},write=True),0x230)
        for name,args in [('WOA_EC_read',{**base,'value':1}),('WOA_EC_read',{**base,'unknown':1}),
                          ('WOA_EC_write',base),('CPU_ReadCpuVoltage',{'value':1}),('Adapter_Read_PD_IC_PN',{'index':1})]:
            with self.subTest(name=name),mock.patch.object(native_oem,'rpc') as rpc,mock.patch.object(native_oem,'raw_ec_write_enabled',return_value=True):
                with self.assertRaises(ValueError):compat.validate(name,args)
                rpc.assert_not_called()
    def test_raw_write_plan_revision_exposes_packet_and_rejects_old_digest(self):
        import hashlib
        args={'address_space':'healthytable','bank':6,'register':0x36,'value':1}
        with mock.patch.object(native_oem,'raw_ec_write_enabled',return_value=True),mock.patch.object(native_oem.Path,'read_text',return_value='test-device'),mock.patch.object(native_oem,'rpc') as rpc:
            plan=native_oem.mutation_plan('WOA_EC_write',args)
            self.assertEqual(plan['recipe_revision'],3)
            self.assertEqual(plan['protocol_recipe'],{'address_space':'healthytable','bank':6,'register':0x36,'wire_bank':0x86,'wire_value':1})
            old={k:v for k,v in plan.items() if k not in ('expected_sha256','protocol_recipe')};old['recipe_revision']=2
            digest=hashlib.sha256(json.dumps(old,sort_keys=True).encode()).hexdigest()
            with self.assertRaises(RuntimeError):native_oem.call('WOA_EC_write',args,True,digest)
            rpc.assert_not_called()
    def test_completed_write_transport_is_not_firmware_acknowledgment(self):
        args={'address_space':'healthytable','bank':6,'register':0x36,'value':1}
        with mock.patch.object(native_oem,'raw_ec_write_enabled',return_value=True),mock.patch.object(native_oem.Path,'read_text',return_value='test-device'),mock.patch.object(native_oem,'rpc',return_value={'status':0,'value':0}) as rpc:
            plan=native_oem.mutation_plan('WOA_EC_write',args)
            result=native_oem.call('WOA_EC_write',args,True,plan['expected_sha256'])
        self.assertTrue(result['applied']);self.assertTrue(result['transport_completed'])
        self.assertIsNone(result['firmware_acknowledged']);self.assertFalse(result['readback_verified'])
        rpc.assert_called_once_with(2,0x0636,1,True)
    def test_raw_ec_write_is_refused_by_default_before_planning_or_elevation(self):
        args={'address_space':'healthytable','bank':6,'register':0x36,'value':1}
        with tempfile.TemporaryDirectory() as temp,mock.patch.object(native_oem,'RAW_EC_WRITE_POLICY',Path(temp)/'absent'),\
             mock.patch.object(native_oem,'rpc') as rpc:
            import api_bridge
            with mock.patch.object(api_bridge.sys,'stdin',SimpleNamespace(buffer=__import__('io').BytesIO(json.dumps({'name':'WOA_EC_write','args':args}).encode()))),\
                 mock.patch('builtins.print') as out:
                self.assertEqual(api_bridge.main(),1)
            self.assertEqual(json.loads(out.call_args[0][0])['error']['errno'],errno.EPERM)
            with mock.patch.object(native_oem.Path,'read_text',return_value='test-device'):
                for call in (lambda:compat.validate('WOA_EC_write',args),lambda:native_oem.call('WOA_EC_write',args),
                             lambda:native_oem.call('WOA_EC_write',args,True,'0'*64),lambda:compat.dispatch('WOA_EC_write',args,True,'0'*64)):
                    with self.assertRaises(PermissionError) as caught:call()
                    self.assertEqual(caught.exception.errno,errno.EPERM)
                    self.assertIn('owner policy forbids arbitrary EC writes',str(caught.exception))
                # Other OEM mutations keep their reviewed plan path.
                self.assertFalse(native_oem.call('Adapter_Clear_Charger_Data',{})['applied'])
            rpc.assert_not_called()
    def test_raw_ec_write_policy_requires_trusted_regular_file_and_directory(self):
        import os
        uid=os.getuid()
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp)/'policy';d.mkdir(mode=0o755);d.chmod(0o755);f=d/'allow-raw-ec-write'
            self.assertFalse(native_oem.raw_ec_write_enabled(f,uid))
            f.write_text('');f.chmod(0o644)
            self.assertTrue(native_oem.raw_ec_write_enabled(f,uid))
            self.assertFalse(native_oem.raw_ec_write_enabled(f,uid+1))  # not owned by the trusted (root) user
            self.assertFalse(native_oem.raw_ec_write_enabled(f))  # default trusted owner is root
            for mode in (0o664,0o646):
                f.chmod(mode);self.assertFalse(native_oem.raw_ec_write_enabled(f,uid))
            f.chmod(0o644);d.chmod(0o775);self.assertFalse(native_oem.raw_ec_write_enabled(f,uid));d.chmod(0o755)
            f.unlink();target=Path(temp)/'target';target.write_text('');target.chmod(0o644);f.symlink_to(target)
            self.assertFalse(native_oem.raw_ec_write_enabled(f,uid))
            f.unlink();f.mkdir();self.assertFalse(native_oem.raw_ec_write_enabled(f,uid));f.rmdir()
            link=Path(temp)/'linkdir';link.symlink_to(d);target.rename(d/'allow-raw-ec-write')
            self.assertTrue(native_oem.raw_ec_write_enabled(d/'allow-raw-ec-write',uid))
            self.assertFalse(native_oem.raw_ec_write_enabled(link/'allow-raw-ec-write',uid))
    def test_wrong_address_space_and_high_bit_alias_are_rejected(self):
        for args in ({'bank':2,'register':0x31},{'address_space':'arm','bank':2,'register':0x31},
                     {'address_space':'healthytable','bank':130,'register':0x31}):
            with self.assertRaises(ValueError):native_oem.raw_index(args)
    def test_invalid_fan_requests_are_rejected_before_elevation(self):
        for name,args in [('HealthyTable_SetFanPwmDuty',{'duty':-1}),('HealthyTable_SetFanPwmDuty',{'duty':256}),('HealthyTable_SetFanIndex',{'index':1}),
                          ('HealthyTable_SetFanTestMode',{'manual':'false'}),('WMISetQuietFan',{'profile':'bogus'})]:
            with self.assertRaises(ValueError):compat.validate(name,args)
    def test_application_configuration_preserves_unrelated_keys(self):
        import user_preferences
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'zenbook-hardware/compat.json';p.parent.mkdir(mode=0o700);p.write_text(json.dumps({'unrelated':{'theme':'dark'}}));p.chmod(0o600)
            with mock.patch.object(user_preferences,'_CONTEXT',temp):
                plan=compat.set_app_path({'path':'/usr/bin/python3'},False,None)
                self.assertFalse(plan['applied']);self.assertNotIn('app_path',json.loads(p.read_text()))
                out=compat.set_app_path({'path':'/usr/bin/python3'},True,plan['expected_sha256'])
            self.assertTrue(out['readback_verified']);self.assertEqual(json.loads(p.read_text())['unrelated'],{'theme':'dark'})
            self.assertEqual(p.stat().st_mode&0o777,0o600)
    def test_application_stale_plan_is_rejected(self):
        import user_preferences
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'zenbook-hardware/compat.json';p.parent.mkdir(mode=0o700);p.write_text('{}');p.chmod(0o600)
            with mock.patch.object(user_preferences,'_CONTEXT',temp):
                plan=compat.set_app_path({'path':'/usr/bin/python3'},False,None);p.write_text('{"new":true}')
                with self.assertRaises(OSError) as caught:compat.set_app_path({'path':'/usr/bin/python3'},True,plan['expected_sha256'])
                self.assertEqual(caught.exception.errno,errno.EAGAIN)
            self.assertEqual(json.loads(p.read_text()),{'new':True})
    def test_logging_uses_stdin_and_correct_priority(self):
        for name,level in [('TraceOutput','info'),('TraceOutputCritical','crit')]:
            with mock.patch.object(compat.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run,\
                 mock.patch.object(compat.linux_services,'system_tool',return_value='/usr/bin/systemd-cat') as tool:
                result=compat.lifecycle(name,{'text':'unit-test metadata'})
            tool.assert_called_once_with('systemd-cat');self.assertEqual(run.call_args.args[0][0],'/usr/bin/systemd-cat')
            self.assertTrue(result['recorded']);self.assertEqual(run.call_args.kwargs['input'],'unit-test metadata')
            self.assertEqual(run.call_args.args[0][-1],level);self.assertNotIn('unit-test metadata',run.call_args.args[0])
    def test_shutdown_does_not_unload_shared_driver(self):
        with mock.patch.object(compat.linux_services,'run') as run:out=compat.lifecycle('ShutdownWinIo',{})
        self.assertTrue(out['client_released']);run.assert_not_called()
    def test_driver_stop_is_a_plan_without_apply(self):
        with mock.patch.object(compat.linux_services,'run') as run:out=compat.lifecycle('StopWinIoDriver',{})
        self.assertFalse(out['applied']);run.assert_not_called()
    def test_log_does_not_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'existing.jsonl';p.write_text('retain')
            with self.assertRaises(FileExistsError):compat.normal_control('SaveEcLog',{'path':str(p)})
            self.assertEqual(p.read_text(),'retain')
    def test_wmiadd_wraps_like_the_original_32_bit_export(self):
        self.assertEqual(compat.lifecycle('wmiadd',{'value':0xffffffff}),0)
        self.assertEqual(compat.lifecycle('wmiadd',{'value':41}),42)

if __name__=='__main__':unittest.main()


class HddTemperaturePrivilegeTests(unittest.TestCase):
    def test_root_only_when_smart_fallback_would_be_needed(self):
        import compat,disk_temperature,errno
        from unittest import mock
        cases=[([{'device':'/dev/nvme0n1','available':True,'celsius':40.0,'source':'Linux hwmon'}],False),
               ([],False),
               ([{'device':'/dev/sda','available':False,'errno':errno.EACCES,'error':'SMART fallback requires privilege.'}],True)]
        for rows,expected in cases:
            with self.subTest(rows=rows),mock.patch.object(disk_temperature,'report',return_value=rows) as r,mock.patch('os.geteuid',return_value=1000):
                self.assertIs(compat.needs_root('WMIGetHDDTemp',{}),expected)
                self.assertEqual(r.call_args.args,('all',))
                with self.assertRaises(PermissionError):r.call_args.kwargs['runner']()
        with mock.patch.object(disk_temperature,'report',side_effect=OSError(errno.EAGAIN,'changed')),mock.patch('os.geteuid',return_value=1000):
            self.assertTrue(compat.needs_root('WMIGetHDDTemp',{}))
        self.assertFalse(compat.needs_root('RF_WiFi_Main_Aux_Rssi',{}))
