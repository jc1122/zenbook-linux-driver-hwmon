# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import errno
import importlib.util
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock
import compat
import remembered_controls as controls
import user_preferences as prefs


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name);prefs.configure(str(self.home));self.addCleanup(prefs.configure,None)
    def test_reads_do_not_create_files_and_choices_survive_new_workers(self):
        before=prefs.read();self.assertFalse(before['exists']);self.assertFalse((self.home/'zenbook-hardware').exists())
        one=prefs.remember('battery_charge_limit_percent',100,before['revision'])
        two=prefs.remember('platform_profile','performance',one['revision'])
        self.assertEqual(prefs.read(),two);self.assertEqual(two['values'],{'battery_charge_limit_percent':100,'platform_profile':'performance'})
        for name in ('preferences.json','preferences.lock'):
            info=(self.home/'zenbook-hardware'/name).stat()
            self.assertEqual(info.st_uid,os.getuid());self.assertEqual(info.st_mode&0o777,0o600)
        self.assertEqual((self.home/'zenbook-hardware').stat().st_mode&0o777,0o700)
    def test_oversized_settings_are_refused_with_explicit_error_before_replacement(self):
        env={**os.environ,'XDG_CONFIG_HOME':str(self.home)}
        with mock.patch.dict(os.environ,env),mock.patch.object(prefs,'LIMIT',16):
            before=prefs._local({'op':'read'})
            with self.assertRaises(OSError) as caught:
                prefs._local({'op':'update','field':'platform_profile','value':'balanced','expected_revision':before['revision']})
        self.assertEqual(caught.exception.errno,errno.EOVERFLOW)
        self.assertFalse((self.home/'zenbook-hardware/preferences.json').exists())
        self.assertEqual([p.name for p in (self.home/'zenbook-hardware').iterdir() if p.name.startswith('.preferences-')],[])
    def test_stale_revision_never_overwrites_another_choice(self):
        old=prefs.read();current=prefs.remember('platform_profile','balanced',old['revision'])
        with self.assertRaises(OSError) as caught:prefs.remember('battery_charge_limit_percent',80,old['revision'])
        self.assertEqual(caught.exception.errno,errno.EAGAIN);self.assertEqual(prefs.read(),current)
    def test_idempotent_update_keeps_revision(self):
        one=prefs.remember('platform_profile','quiet',prefs.read()['revision'])
        self.assertEqual(prefs.remember('platform_profile','quiet',one['revision']),one)
    def test_unrelated_app_configuration_is_preserved(self):
        base=self.home/'zenbook-hardware';base.mkdir(mode=0o700)
        app=base/'compat.json';app.write_bytes(b'{"app_path":"/usr/bin/true","unrelated":17}\n')
        original=app.read_bytes();prefs.remember('platform_profile','quiet',prefs.read()['revision'])
        self.assertEqual(app.read_bytes(),original)
    def test_untrusted_settings_fail_before_replacement(self):
        base=self.home/'zenbook-hardware';base.mkdir(mode=0o700);path=base/'preferences.json'
        invalid=[b'{"schema":1,"schema":1,"values":{}}',b'{"schema":1,"values":{"foreign":1}}',
                 b'{"schema":true,"values":{}}',b'{"schema":1,"values":{"battery_charge_limit_percent":true}}',
                 b'{"schema":1,"values":{},"foreign":1}',b'x'*8193,b'\xff']
        for raw in invalid:
            with self.subTest(raw=raw[:70]):
                path.write_bytes(raw);path.chmod(0o600)
                with self.assertRaises(OSError):prefs.read()
                self.assertEqual(path.read_bytes(),raw)
    def test_symlink_hardlink_and_shared_modes_rejected(self):
        base=self.home/'zenbook-hardware';base.mkdir(mode=0o700);path=base/'preferences.json'
        target=self.home/'target';target.write_text('{"schema":1,"values":{}}');target.chmod(0o600)
        path.symlink_to(target)
        with self.assertRaises(OSError):prefs.read()
        path.unlink();os.link(target,path)
        with self.assertRaises(OSError):prefs.read()
        path.unlink();path.write_bytes(target.read_bytes());path.chmod(0o644)
        with self.assertRaises(OSError):prefs.read()
        path.chmod(0o600);base.chmod(0o755)
        with self.assertRaises(OSError):prefs.read()
    def test_foreign_owned_file_rejected(self):
        with tempfile.TemporaryFile() as stream:
            info=SimpleNamespace(st_mode=0o100600,st_uid=os.getuid()+1,st_nlink=1)
            with mock.patch.object(prefs.os,'fstat',return_value=info),self.assertRaises(PermissionError):prefs._trusted_fd(stream.fileno())
    def test_lock_contention_is_bounded(self):
        import fcntl
        base=self.home/'zenbook-hardware';base.mkdir(mode=0o700);lock=base/'preferences.lock'
        with lock.open('w') as stream:
            lock.chmod(0o600);fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(OSError) as caught:prefs.read(prepare=True)
        self.assertEqual(caught.exception.errno,errno.ETIMEDOUT)
    def test_sudo_worker_drops_to_caller_and_sanitizes_environment(self):
        account=SimpleNamespace(pw_uid=1000,pw_gid=1001,pw_dir='/home/test-owner',pw_name='test-owner')
        response=SimpleNamespace(returncode=0,stdout=json.dumps({'ok':True,'result':{'owner_uid':1000}}))
        with mock.patch.object(prefs.os,'getuid',return_value=0),mock.patch.object(prefs.os,'geteuid',return_value=0),mock.patch.object(prefs.os,'getgrouplist',return_value=[1001,1002]),mock.patch.dict(os.environ,{'SUDO_UID':'1000','UNRELATED_SECRET':'do-not-pass'}),mock.patch.object(prefs.pwd,'getpwuid',return_value=account),mock.patch.object(prefs.subprocess,'run',return_value=response) as run:
            prefs.read()
        call=run.call_args
        self.assertEqual((call.kwargs['user'],call.kwargs['group'],call.kwargs['extra_groups']),(1000,1001,[1002]))
        self.assertEqual(set(call.kwargs['env']),{'PATH','LANG','XDG_CONFIG_HOME'})
        self.assertEqual(call.kwargs['env']['XDG_CONFIG_HOME'],str(self.home));self.assertNotIn('do-not-pass',str(call))
    def test_invalid_caller_and_config_fail_without_spawn(self):
        with mock.patch.object(prefs.os,'getuid',return_value=0),mock.patch.dict(os.environ,{'SUDO_UID':'-1'}),mock.patch.object(prefs.subprocess,'run') as run:
            with self.assertRaises(PermissionError):prefs.read()
        run.assert_not_called()
        for value in ('relative','/tmp/\0bad',17):
            with self.assertRaises(ValueError):prefs.configure(value)
    def test_unknown_worker_response_does_not_claim_no_commit(self):
        with mock.patch.object(prefs.subprocess,'run',return_value=SimpleNamespace(stdout='broken',returncode=1)):
            with self.assertRaises(prefs.PreferenceError) as caught:prefs.read()
        self.assertIsNone(caught.exception.committed)
    def test_application_plans_do_not_create_files_and_updates_preserve_preferences(self):
        before=prefs.read();saved=prefs.remember('platform_profile','balanced',before['revision'])
        original=(self.home/'zenbook-hardware/preferences.json').read_bytes()
        plan=prefs.set_application_path('/usr/bin/python3');self.assertFalse(plan['applied']);self.assertFalse(prefs.application_config()['exists'])
        result=prefs.set_application_path('/usr/bin/python3',True,plan['expected_sha256']);self.assertTrue(result['readback_verified'])
        self.assertEqual(prefs.application_config()['values'],{'app_path':'/usr/bin/python3'})
        self.assertEqual((self.home/'zenbook-hardware/preferences.json').read_bytes(),original);self.assertEqual(prefs.read(),saved)
        self.assertEqual((self.home/'zenbook-hardware/compat.json').stat().st_mode&0o777,0o600)
    def test_application_read_and_plan_are_noncreating_and_content_revisions_distinguish_absent(self):
        first=prefs.set_application_path('/usr/bin/python3');self.assertFalse((self.home/'zenbook-hardware').exists())
        base=self.home/'zenbook-hardware';base.mkdir(mode=0o700);p=base/'compat.json';p.write_text('{}');p.chmod(0o600)
        with self.assertRaises(OSError) as caught:prefs.set_application_path('/usr/bin/python3',True,first['expected_sha256'])
        self.assertEqual(caught.exception.errno,errno.EAGAIN);self.assertEqual(p.read_text(),'{}')
    def test_application_untrusted_files_are_not_modified(self):
        base=self.home/'zenbook-hardware';base.mkdir(mode=0o700);p=base/'compat.json'
        for raw in (b'{"x":1,"x":2}',b'{"x":NaN}',b'[]',b'x'*8193,b'\xff'):
            p.write_bytes(raw);p.chmod(0o600)
            with self.assertRaises(OSError):prefs.set_application_path('/usr/bin/python3')
            self.assertEqual(p.read_bytes(),raw)
        p.unlink();target=self.home/'target';target.write_text('{}');target.chmod(0o600);p.symlink_to(target)
        with self.assertRaises(OSError):prefs.application_config()
        self.assertEqual(target.read_text(),'{}')
        p.unlink();os.link(target,p)
        with self.assertRaises(OSError):prefs.application_config()
    def test_application_invalid_path_fails_before_directory_creation(self):
        for value in ('relative','/missing-app',17,'/bad\0path'):
            with self.assertRaises(OSError):prefs.set_application_path(value)
            self.assertFalse((self.home/'zenbook-hardware').exists())
    def test_root_application_worker_uses_actual_sudo_identity_and_config_context(self):
        account=SimpleNamespace(pw_uid=1000,pw_gid=1001,pw_dir='/home/test-owner',pw_name='test-owner')
        response=SimpleNamespace(returncode=0,stdout=json.dumps({'ok':True,'result':{'owner_uid':1000}}))
        with mock.patch.object(prefs.os,'getuid',return_value=0),mock.patch.object(prefs.os,'geteuid',return_value=0),mock.patch.object(prefs.os,'getgrouplist',return_value=[1001]),mock.patch.dict(os.environ,{'SUDO_UID':'1000'}),mock.patch.object(prefs.pwd,'getpwuid',return_value=account),mock.patch.object(prefs.subprocess,'run',return_value=response) as run:
            prefs.set_application_path('/usr/bin/python3')
        self.assertEqual(run.call_args.kwargs['user'],1000);self.assertEqual(run.call_args.kwargs['extra_groups'],[])
        self.assertEqual(run.call_args.kwargs['env']['XDG_CONFIG_HOME'],str(self.home))
        self.assertEqual(json.loads(run.call_args.kwargs['input'])['op'],'application_set')
    def test_setuid_caller_drops_effective_root_before_user_file_access(self):
        account=SimpleNamespace(pw_uid=1000,pw_gid=1001,pw_dir='/home/test-owner',pw_name='test-owner')
        response=SimpleNamespace(returncode=0,stdout=json.dumps({'ok':True,'result':{'owner_uid':1000}}))
        with mock.patch.object(prefs.os,'getuid',return_value=1000),mock.patch.object(prefs.os,'geteuid',return_value=0),mock.patch.object(prefs.os,'getgrouplist',return_value=[1001,1002]) as groups,mock.patch.object(prefs.os,'getgroups',side_effect=AssertionError('Inherited privileged groups must not be used')),mock.patch.dict(os.environ,{'SUDO_UID':'0'}),mock.patch.object(prefs.pwd,'getpwuid',return_value=account) as lookup,mock.patch.object(prefs.subprocess,'run',return_value=response) as run:
            prefs.application_config()
        lookup.assert_called_with(1000);self.assertEqual(run.call_args.kwargs['user'],1000)
        groups.assert_called_once_with('test-owner',1001)
        self.assertEqual(run.call_args.kwargs['group'],1001);self.assertEqual(run.call_args.kwargs['extra_groups'],[1002])
    def test_application_external_change_before_replace_is_preserved(self):
        import errno
        base=self.home/'zenbook-hardware';base.mkdir(mode=0o700);p=base/'compat.json';p.write_text('{}');p.chmod(0o600)
        digest=prefs.application_config()['revision'];real_fsync=os.fsync
        def change(fd):
            real_fsync(fd);p.write_text('{"external":true}')
        with mock.patch.dict(os.environ,{'XDG_CONFIG_HOME':str(self.home)}),mock.patch.object(prefs.os,'fsync',side_effect=change),self.assertRaises(OSError) as caught:
            prefs._local({'op':'application_set','path':'/usr/bin/python3','apply':True,'expected_sha256':digest})
        self.assertEqual(caught.exception.errno,errno.EAGAIN);self.assertEqual(p.read_text(),'{"external":true}')
        self.assertFalse(list(base.glob('.compat-*')))


class RememberedControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'profile';self.path.write_text('balanced\n')
        patch=mock.patch.dict(controls.PATHS,{'profile':self.path});patch.start();self.addCleanup(patch.stop)
        self.front=SimpleNamespace(control=self.control);self.writes=[]
        self.before={'values':{},'revision':'before'}
    def control(self,args):
        before=self.path.read_text().strip();self.writes.append(args.value);self.path.write_text(str(args.value)+'\n')
        return {'before':before,'after':str(args.value)}
    def test_preflight_failure_never_changes_hardware(self):
        with mock.patch.object(prefs,'read',side_effect=PermissionError(errno.EACCES,'private')):
            with self.assertRaises(PermissionError):controls.set_and_remember(self.front,'profile','performance')
        self.assertEqual(self.writes,[])
    def test_success_remembers_only_verified_hardware(self):
        after={'values':{'platform_profile':'performance'},'revision':'after'}
        with mock.patch.object(prefs,'read',return_value=self.before),mock.patch.object(prefs,'remember',return_value=after) as remember:
            out=controls.set_and_remember(self.front,'profile','performance')
        self.assertTrue(out['remembered']);remember.assert_called_once_with('platform_profile','performance','before')
    def test_known_uncommitted_failure_conditionally_restores(self):
        error=prefs.PreferenceError(errno.ENOSPC,'disk full',False)
        with mock.patch.object(prefs,'read',return_value=self.before),mock.patch.object(prefs,'remember',side_effect=error):
            with self.assertRaises(controls.ControlError) as caught:controls.set_and_remember(self.front,'profile','performance')
        self.assertTrue(caught.exception.control_result['hardware_restored']);self.assertEqual(self.path.read_text(),'balanced\n')
    def test_external_hardware_selection_is_never_undone(self):
        def fail(*args):self.path.write_text('quiet\n');raise prefs.PreferenceError(errno.ENOSPC,'full',False)
        with mock.patch.object(prefs,'read',return_value=self.before),mock.patch.object(prefs,'remember',side_effect=fail):
            with self.assertRaises(controls.ControlError):controls.set_and_remember(self.front,'profile','performance')
        self.assertEqual(self.writes,['performance']);self.assertEqual(self.path.read_text(),'quiet\n')
    def test_unknown_commit_or_concurrent_preferences_are_not_compensated(self):
        for committed,code,current in ((None,errno.EIO,self.before),(False,errno.EAGAIN,self.before),(False,errno.ENOSPC,{'values':{},'revision':'external'})):
            self.writes=[]
            with mock.patch.object(prefs,'read',side_effect=[self.before,current]),mock.patch.object(prefs,'remember',side_effect=prefs.PreferenceError(code,'failed',committed)):
                with self.assertRaises(controls.ControlError):controls.set_and_remember(self.front,'profile','performance')
            self.assertEqual(self.writes,['performance'])
    def test_lost_commit_reply_recovers_by_independent_readback(self):
        after={'values':{'platform_profile':'performance'},'revision':'new'}
        with mock.patch.object(prefs,'read',side_effect=[self.before,after]),mock.patch.object(prefs,'remember',side_effect=prefs.PreferenceError(errno.EIO,'lost',None)):
            out=controls.set_and_remember(self.front,'profile','performance')
        self.assertTrue(out['persistence_readback_recovered']);self.assertEqual(self.writes,['performance'])
    def test_immediate_and_remembered_api_setters_are_distinct(self):
        front=SimpleNamespace(control=mock.Mock(return_value={'after':'100'}))
        with mock.patch.object(compat,'frontend',return_value=front),mock.patch.object(controls,'set_and_remember',return_value={'remembered':True}) as remember:
            compat.normal_control('WMISetBatteryHealth',{'percent':100});remember.assert_not_called();front.control.assert_called_once()
            compat.normal_control('WMISetBatteryHealthToUser',{'percent':100});remember.assert_called_with(front,'charge-limit',100)
            compat.normal_control('WMISetQuietFan',{'profile':'performance'});remember.assert_called_with(front,'profile','performance')
    def test_readback_mismatch_never_saves(self):
        self.front.control=lambda args:{'before':'balanced','after':'quiet'}
        with mock.patch.object(prefs,'read',return_value=self.before),mock.patch.object(prefs,'remember') as remember:
            with self.assertRaises(controls.ControlError):controls.set_and_remember(self.front,'profile','performance')
        remember.assert_not_called()


class FrontendControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.front=compat.frontend()
    def test_sudo_fallback_preserves_explicit_config_context(self):
        prefs.configure('/tmp/unit-config');self.addCleanup(prefs.configure,None)
        with mock.patch('auth.sudo_fallback',return_value=0) as sudo,mock.patch('sys.stderr'):self.front.elevated(['profile','performance'])
        self.assertEqual(sudo.call_args.args[0][-4:],['--caller-config-home','/tmp/unit-config','profile','performance'])
    def test_bad_control_and_lifecycle_args_rejected_before_auth(self):
        samples={'WMISetBatteryHealth':{'percent':100,'foreign':1},'WMISetBatteryHealthToUser':{'percent':True},
                 'WMISetQuietFan':{'profile':'performance','foreign':1},'HealthyTable_SetFanIndex':{'index':0,'foreign':1},
                 'Thermal_Read_CpuPackagePower':{'foreign':1},'InitializeWinIo':{'foreign':1},'ShutdownWinIo':{'foreign':1},
                 'StopWinIoDriver':{'foreign':1},'GetIoDllVersion':{'foreign':1},'wmiadd':{'value':True},
                 'TraceOutput':{'text':'x','foreign':1},'TraceOutputCritical':{'text':''},'WMISetAppPath':{'path':'relative'}}
        for name,args in samples.items():
            with self.subTest(name=name),mock.patch.object(self.front,'elevated') as elevate,mock.patch.object(self.front,'routed') as routed:
                with self.assertRaises(ValueError):self.front.main(['api',name,'--args',json.dumps(args)])
                elevate.assert_not_called();routed.assert_not_called()
    def test_primitive_does_not_undo_external_readback_change(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'setting';path.write_text('balanced\n');actual=Path.write_text;writes=[]
            def changed(p,value,*args,**kwargs):
                writes.append(value);return actual(p,'quiet\n',*args,**kwargs)
            with mock.patch.object(Path,'write_text',changed),self.assertRaises(controls.ControlError):self.front.write_verified(path,'performance')
            self.assertEqual(writes,['performance\n']);self.assertEqual(path.read_text(),'quiet\n')

if __name__=='__main__':unittest.main()
