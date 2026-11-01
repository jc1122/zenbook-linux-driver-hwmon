# SPDX-License-Identifier: GPL-2.0-only
"""Client migration to org.zenbook.Hardware1: service-routed results must equal
the direct in-process results (fake system bus that wraps the direct path with
the service's own envelope functions). No real bus, polkit, root or hardware."""
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import errno
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import api_bridge
import auth
import compat
import remembered_controls
import user_preferences

ROOT=Path(__file__).resolve().parent
_SPEC=importlib.util.spec_from_file_location('client_test_service_core',ROOT/'service/hwd_core.py')
core=importlib.util.module_from_spec(_SPEC);_SPEC.loader.exec_module(core)
RealClient=auth.ServiceClient
try:Gio,GLib=auth._gi()
except (ImportError,ValueError):Gio=GLib=None


def direct(request):
    """The in-process path a root caller runs (privilege check bypassed)."""
    with mock.patch.object(compat,'needs_root',return_value=False):return api_bridge.call(request)


class FakeService:
    """Gio-connection stand-in for zenbook_hardwared: hwd_core envelopes,
    CLIENT_ONLY/firmware refusals, HARDWARE_ONLY client_persistence, leases."""

    def __init__(self,deny=(),fail=None):
        self.deny=set(deny);self.fail=fail;self.calls=[];self.subscriptions={};self.lease_end=None;self.release_error=None

    def call_sync(self,bus,path,iface,method,params,reply,flags,timeout,cancellable):
        args=params.unpack() if params is not None else ()
        self.calls.append({'target':(bus,path,iface),'method':method,'args':args,'flags':int(flags),'timeout':timeout})
        if self.fail:raise Gio.DBusError.new_for_dbus_error(self.fail,'fake failure')
        result=getattr(self,'do_'+method)(*args)
        return GLib.Variant('(s)',(result,))

    def signal_subscribe(self,sender,iface,member,path,arg0,flags,callback):
        key=len(self.subscriptions)+1;self.subscriptions[key]=(sender,iface,member,path,callback);return key
    def signal_unsubscribe(self,key):del self.subscriptions[key]

    @staticmethod
    def envelope(function):
        try:return core.success(function())
        except Exception as error:return core.failure(error)

    def do_Call(self,name,args_json,apply,digest):
        if name in self.deny:return core.failure(core.ServiceError(errno.EACCES,'Not authorized by polkit for fake.'))
        if name in core.CLIENT_ONLY:return core.failure(core.ServiceError(errno.EOPNOTSUPP,'client only'))
        args=json.loads(args_json)
        def run():
            if name in core.HARDWARE_ONLY:  # as service RuntimeBackend.call
                command,key,field=core.HARDWARE_ONLY[name]
                result=compat.frontend().control(SimpleNamespace(command=command,value=args[key]))
                return {**result,'remembered':False,'client_persistence':{'field':field,'value':args[key]}}
            return direct({'name':name,'args':args,'apply':apply,'expected_sha256':digest or None})
        return self.envelope(run)

    def do_Control(self,command,args_json):
        args=json.loads(args_json)
        return self.envelope(lambda:{'control':command,'args':args,'before':'balanced','after':str(args.get('value'))})

    def do_SetFanAuto(self):return core.success({'lease':None,'reason':'set_auto','automatic_restored':True,'mode':2})

    def do_AcquireFanLease(self,seconds,request):
        lease='a'*32
        if self.lease_end:
            def end():
                for sender,iface,member,path,callback in list(self.subscriptions.values()):
                    callback(None,auth.BUS_NAME,path,iface,member,GLib.Variant('(ss)',(lease,self.lease_end)))
                return False
            GLib.idle_add(end)
        return lease

    def do_ReleaseFanLease(self,lease_id):
        if self.release_error:raise Gio.DBusError.new_for_dbus_error(auth.ERROR_PREFIX+self.release_error,'gone')
        return core.success({'lease':lease_id,'reason':'released','automatic_restored':True,'mode':2})


def stable(value):
    """Drop per-run preference metadata (time, content revision, temp path)."""
    if isinstance(value,dict):
        return {k:stable(v) for k,v in value.items() if k not in ('updated_utc','revision','path')}
    if isinstance(value,(list,tuple)):return type(value)(stable(v) for v in value)
    return value


def client_factory(service):
    return lambda interactive=False,timeout_ms=None,connection=None:RealClient(interactive=interactive,connection=service,timeout_ms=timeout_ms)


def bridge(request,service=None,euid=1000):
    source=SimpleNamespace(buffer=io.BytesIO(json.dumps(request).encode()));output=io.StringIO()
    with mock.patch.object(api_bridge.sys,'stdin',source),mock.patch.object(api_bridge.sys,'stdout',output),\
         mock.patch.object(os,'geteuid',return_value=euid),mock.patch.object(auth,'ServiceClient',client_factory(service)):
        status=api_bridge.main()
    return status,json.loads(output.getvalue())


@unittest.skipIf(Gio is None,'python3-gi unavailable')
@unittest.skipIf(os.geteuid()==0,'client routing tests run as an unprivileged user')
class BridgeRoutingTests(unittest.TestCase):
    def outcomes(self):
        yield 'value',lambda *a:{'firmware':'1.0','raw':[1,2]}
        yield 'provider_errno',mock.Mock(side_effect=OSError(errno.ENODEV,'absent'))
        yield 'control_result',mock.Mock(side_effect=remembered_controls.ControlError(errno.EAGAIN,'changed',{'hardware':{'after':'x'},'remembered':False}))
        yield 'commit_unknown',mock.Mock(side_effect=user_preferences.PreferenceError(errno.EIO,'Verify current settings.',None))
        yield 'value_error',mock.Mock(side_effect=ValueError('bad argument'))
        yield 'plain_error',mock.Mock(side_effect=RuntimeError('no errno'))

    def test_routed_envelopes_and_status_equal_direct(self):
        for label,behaviour in self.outcomes():
            with self.subTest(label),mock.patch.object(compat,'dispatch',side_effect=behaviour):
                service=FakeService()
                routed=bridge({'name':'GetXgmFw'},service)
                with mock.patch.object(compat,'needs_root',return_value=False):reference=bridge({'name':'GetXgmFw'},None)
                self.assertEqual(routed,reference)
                self.assertEqual([c['method'] for c in service.calls],['Call'])
                self.assertEqual(service.calls[0]['target'],(auth.BUS_NAME,auth.OBJECT_PATH,auth.INTERFACE))
                self.assertEqual(service.calls[0]['flags'],0)  # the C ABI path never allows interaction
                self.assertLess(service.calls[0]['timeout'],60000)  # below the C library's kill deadline

    def test_root_keeps_direct_path_without_bus(self):
        service=FakeService()
        with mock.patch.object(compat,'dispatch',return_value={'firmware':'1.0'}):
            self.assertEqual(bridge({'name':'GetXgmFw'},service,euid=0),(0,{'ok':True,'result':{'firmware':'1.0'}}))
        self.assertEqual(service.calls,[])

    def test_polkit_denial_and_unavailable_service_are_eacces(self):
        status,out=bridge({'name':'GetXgmFw'},FakeService(deny={'GetXgmFw'}))
        self.assertEqual((status,out['error']['errno']),(1,errno.EACCES))
        for name in ('org.freedesktop.DBus.Error.ServiceUnknown','org.freedesktop.DBus.Error.AccessDenied'):
            status,out=bridge({'name':'GetXgmFw'},FakeService(fail=name))
            self.assertEqual((status,out['error']['errno']),(1,errno.EACCES))
        self.assertIn('privileged service unavailable; run with sudo',bridge({'name':'GetXgmFw'},FakeService(fail='org.freedesktop.DBus.Error.ServiceUnknown'))[1]['error']['message'])

    def test_client_only_exports_run_unprivileged_in_the_client(self):
        service=FakeService()
        with mock.patch.object(compat,'needs_root',return_value=True),mock.patch.object(compat,'dispatch',return_value={'path':'/tmp/x'}) as dispatch:
            self.assertEqual(bridge({'name':'SaveEcLog','args':{'path':'/tmp/x'}},service),(0,{'ok':True,'result':{'path':'/tmp/x'}}))
        dispatch.assert_called_once();self.assertEqual(service.calls,[])

    def test_firmware_apply_and_driver_unload_are_not_sent_and_point_to_sudo(self):
        service=FakeService()
        with mock.patch.object(compat,'validate'),mock.patch.object(compat,'dispatch',side_effect=AssertionError('no direct run')):
            for request in ({'name':'GPNV_Set_ActivatedTime','args':{},'apply':True,'expected_sha256':'0'*64},
                            {'name':'StopWinIoDriver','args':{},'apply':True,'expected_sha256':'0'*64}):
                status,out=bridge(request,service)
                self.assertEqual((status,out['error']['errno']),(1,errno.EACCES));self.assertIn('sudo zenbook-hardware',out['error']['message'])
        self.assertEqual(service.calls,[])
        self.assertEqual(compat.privilege_route('GPNV_Set_ActivatedTime',{},False),'service')  # plans still use the service

    def test_route_table_matches_service_refusals(self):
        self.assertEqual(compat.CLIENT_ONLY,set(core.CLIENT_ONLY))
        authorization=json.loads((ROOT/'service/authorization.json').read_text())['exports']
        firmware={name for name,action in authorization.items() if action==core.FIRMWARE}
        for name in firmware:self.assertEqual(compat.privilege_route(name,{},True),'root-cli',name)

    def test_hardware_only_setting_is_saved_as_the_user_with_direct_result_shape(self):
        front=SimpleNamespace(control=lambda request:{'before':'balanced','after':str(request.value)})
        results=[]
        for routed in (False,True):
            with tempfile.TemporaryDirectory() as temp,mock.patch.object(compat,'frontend',return_value=front),\
                 mock.patch.object(remembered_controls,'identity',return_value=(1,1)):
                user_preferences.configure(temp);self.addCleanup(user_preferences.configure,None)
                service=FakeService()
                if routed:results.append(bridge({'name':'WMISetQuietFan','args':{'profile':'quiet'}},service))
                else:
                    with mock.patch.object(compat,'needs_root',return_value=False):results.append(bridge({'name':'WMISetQuietFan','args':{'profile':'quiet'}},None))
                self.assertEqual(user_preferences.read()['values'],{'platform_profile':'quiet'})
                self.assertEqual(len(service.calls),1 if routed else 0)
        self.assertEqual(stable(results[0]),stable(results[1]));self.assertTrue(results[1][1]['result']['remembered'])
        self.assertNotIn('client_persistence',results[1][1]['result'])

    def test_unexpected_persistence_request_is_refused(self):
        client=RealClient(connection=FakeService())
        with mock.patch.object(client,'call',return_value={'before':'a','after':'quiet','client_persistence':{'field':'other','value':1}}),\
             mock.patch.object(user_preferences,'remember') as remember,mock.patch.object(user_preferences,'read',return_value={'revision':'r','values':{}}),\
             mock.patch.object(remembered_controls,'identity',return_value=(1,1)),self.assertRaises(OSError) as caught:
            auth.service_call('WMISetQuietFan',{'profile':'quiet'},client=client)
        self.assertEqual(caught.exception.errno,errno.EPROTO);remember.assert_not_called()


@unittest.skipIf(Gio is None,'python3-gi unavailable')
@unittest.skipIf(os.geteuid()==0,'client routing tests run as an unprivileged user')
class CliRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.front=compat.frontend()

    def run_cli(self,argv,service):
        output=io.StringIO()
        with mock.patch.object(self.front,'service_client',lambda args:RealClient(interactive=False,connection=service)),\
             mock.patch('sys.stdout',output),mock.patch('sys.stderr',io.StringIO()):
            status=self.front.main(argv)
        return status,(json.loads(output.getvalue()) if output.getvalue().strip() else None)

    def test_api_routed_output_equals_direct_output(self):
        with mock.patch.object(compat,'dispatch',return_value={'firmware':'1.0'}):
            routed=self.run_cli(['api','GetXgmFw'],FakeService())
            with mock.patch.object(compat,'needs_root',return_value=False):reference=self.run_cli(['api','GetXgmFw'],None)
        self.assertEqual(routed,reference)
        with mock.patch.object(compat,'dispatch',side_effect=OSError(errno.ENODEV,'absent')),self.assertRaises(OSError) as caught:
            self.run_cli(['api','GetXgmFw'],FakeService())
        self.assertEqual((caught.exception.errno,str(caught.exception)),(errno.ENODEV,'[Errno 19] absent'))

    def test_profile_is_applied_by_service_and_remembered_like_root(self):
        fake=lambda request:{'before':'balanced','after':str(request.value)}
        with tempfile.TemporaryDirectory() as temp,mock.patch.object(remembered_controls,'identity',return_value=(1,1)):
            user_preferences.configure(temp);self.addCleanup(user_preferences.configure,None)
            reference=remembered_controls.set_and_remember(SimpleNamespace(control=fake),'profile','quiet')  # root path
        with tempfile.TemporaryDirectory() as temp,mock.patch.object(remembered_controls,'identity',return_value=(1,1)):
            service=FakeService()
            with mock.patch.object(service,'do_Control',lambda command,args_json:core.success({'before':'balanced','after':json.loads(args_json)['value']})):
                status,out=self.run_cli(['--caller-config-home',temp,'profile','quiet'],service)
        self.assertEqual(status,0);self.assertEqual(stable(out),stable(reference))
        self.assertEqual(service.calls[0]['args'],('profile','{"value": "quiet"}'))

    def test_controls_map_to_service_controls(self):
        cases=[(['charge-limit','80'],('charge-limit',{'value':80})),(['keyboard','2'],('keyboard',{'value':2})),
               (['charger','--connector','2'],('charger',{'connector':2})),(['charger'],('charger',{})),
               (['battery-gauge'],('battery-gauge',{})),(['reprobe'],('reprobe',{})),(['usb-activity'],('usb-activity',{})),
               (['battery-history','--refresh'],('battery-history-refresh',{}))]
        for argv,(command,args) in cases:
            with self.subTest(argv=argv):
                service=FakeService();status,out=self.run_cli(argv,service)
                self.assertEqual(status,0);self.assertEqual((out['control'],out['args']),(command,args))
                self.assertEqual([c['method'] for c in service.calls],['Control'])

    def test_fan_uses_set_auto_and_bounded_lease_not_sysfs(self):
        write=mock.Mock(side_effect=AssertionError('no sysfs write'))
        with mock.patch.object(Path,'write_text',write),mock.patch.object(self.front,'fan_state',return_value={'mode':1,'requested_pwm':128,'rpm':3000}):
            service=FakeService();status,out=self.run_cli(['fan','auto'],service)
            self.assertEqual((status,out['automatic_restored']),(0,True));self.assertEqual([c['method'] for c in service.calls],['SetFanAuto'])
            service=FakeService();status,out=self.run_cli(['fan','50','--duration','1'],service)
        self.assertEqual(status,0)
        self.assertEqual([c['method'] for c in service.calls],['AcquireFanLease','ReleaseFanLease'])
        self.assertEqual(service.calls[0]['args'],(2,'50'))  # service expiry is a 1 s backstop
        self.assertEqual(out['lease']['reason'],'released');self.assertTrue(out['lease']['automatic_restored'])
        self.assertEqual(service.subscriptions,{})
        with self.assertRaises(SystemExit):self.run_cli(['fan','50','--duration','301'],FakeService())

    def test_lease_ended_by_service_and_expiry_race(self):
        service=FakeService();service.lease_end='low_rpm_abort'
        ended=RealClient(connection=service).hold_fan_lease(30,'full')
        self.assertEqual(ended['reason'],'low_rpm_abort');self.assertEqual([c['method'] for c in service.calls],['AcquireFanLease'])
        service=FakeService();service.release_error='ENOENT'
        self.assertEqual(RealClient(connection=service).hold_fan_lease(1,'30')['reason'],'expired')

    def test_unavailable_service_hint_and_explicit_sudo_fallback(self):
        down=FakeService(fail='org.freedesktop.DBus.Error.ServiceUnknown')
        with self.assertRaises(auth.ServiceUnavailable) as caught:self.run_cli(['charge-limit','80'],down)
        self.assertIn('privileged service unavailable; run with sudo',str(caught.exception))
        poisoned=mock.MagicMock(side_effect=AssertionError('keyring must never be used'))
        with tempfile.TemporaryDirectory() as temp,mock.patch.dict(sys.modules,{'secretstorage':poisoned}),\
             mock.patch.object(auth,'sudo_fallback',return_value=0) as sudo:
            self.assertEqual(self.run_cli(['--caller-config-home',temp,'--sudo-fallback','charge-limit','80'],down)[0],0)
        command=sudo.call_args.args[0]
        self.assertEqual(command[:3],['/usr/bin/python3','-I','-B'])
        self.assertTrue(Path(command[3]).is_absolute());self.assertEqual(Path(command[3]).name,'zenbook-hardware.py')
        self.assertEqual(command[4:6],['--caller-config-home',temp]);self.assertEqual(command[-2:],['charge-limit','80'])

    def test_root_only_operations_point_to_sudo_without_bus(self):
        service=FakeService()
        with mock.patch.object(compat,'validate'),self.assertRaises(PermissionError) as caught:
            self.run_cli(['api','GPNV_Set_ActivatedTime','--apply','--expect-sha256','0'*64],service)
        self.assertIn('sudo zenbook-hardware',str(caught.exception))
        with self.assertRaises(PermissionError):self.run_cli(['metrics','--refresh-ssd'],service)
        self.assertEqual(service.calls,[])

    def test_record_runs_unprivileged_in_the_client(self):
        import ec_diagnostics
        service=FakeService()
        with mock.patch.object(compat,'needs_root',return_value=True),mock.patch.object(ec_diagnostics,'write_log',return_value={'path':'/tmp/x'}) as log:
            self.assertEqual(self.run_cli(['record','/tmp/x','--samples','1'],service),(0,{'path':'/tmp/x'}))
        log.assert_called_once();self.assertEqual(service.calls,[])

    def test_cli_interaction_follows_terminal_and_opt_out(self):
        args=SimpleNamespace(non_interactive=False)
        with mock.patch.object(auth,'interactive_default',return_value=True),mock.patch.object(auth,'_gi',return_value=(Gio,GLib)):
            self.assertTrue(self.front.service_client(args).interactive)
            self.assertFalse(self.front.service_client(SimpleNamespace(non_interactive=True)).interactive)

    def test_restricted_exports_need_root_and_route_to_service(self):
        import battery_diagnostics,battery_identity,pd_identity,pd_sources
        names=['Thermal_Read_CpuPackagePower',*battery_diagnostics.NAMES,*battery_identity.NAMES,*(set(pd_identity.NAMES)-{'Adapter_Read_PD_ADO'})]
        self.assertEqual(len(battery_diagnostics.NAMES),7);self.assertEqual(len(battery_identity.NAMES),5)
        for name in names:self.assertTrue(compat.needs_root(name,{}),name);self.assertEqual(compat.privilege_route(name,{}),'service')
        self.assertTrue(compat.needs_root('Adapter_Read_PD_ADO',{'native_alert':True}))
        self.assertFalse(compat.needs_root('Adapter_Read_PD_ADO',{}))
        for name in pd_sources.NAMES:self.assertFalse(compat.needs_root(name,{}),name)
        with mock.patch.object(compat.native_oem,'device',return_value=Path('/nonexistent')),mock.patch.object(Path,'exists',return_value=True):
            self.assertFalse(compat.needs_root('Adapter_Read_Contract_PDO',{}));self.assertFalse(compat.needs_root('CPU_ReadCpuVoltage',{}))
        service=FakeService()
        with mock.patch.object(compat,'dispatch',return_value=6500):
            self.assertEqual(bridge({'name':'BatteryHealthy_Read_MaxChargeCurrent'},service),(0,{'ok':True,'result':6500}))
        self.assertEqual([c['method'] for c in service.calls],['Call'])

    def metrics_service(self,report):
        service=FakeService();service.do_Metrics=lambda:core.success(report);return service

    def test_metrics_overlays_root_only_sections_from_service(self):
        import metrics
        local={'schema':1,'cpu_package_power':{'available':False,'errno':13},'charger':{'available':False},'wireless_links':{'local':True},
               'usb_pd_identity':{'ports':[]},'unavailable':{'usb_pd_cable_identity':'x'}}
        remote={key:{'from_service':key} for key in self.front.RESTRICTED_METRICS}
        remote['usb_pd_identity']={'ports':[{'cable':{'available':True}}]};remote['wireless_links']={'sandboxed':True}
        with mock.patch.object(metrics,'report',return_value=local):status,out=self.run_cli(['metrics'],self.metrics_service(remote))
        self.assertEqual(status,0)
        for key in self.front.RESTRICTED_METRICS:self.assertEqual(out[key],remote[key])
        self.assertEqual(out['wireless_links'],{'local':True})  # unrestricted sections stay local
        self.assertNotIn('usb_pd_cable_identity',out['unavailable'])

    def test_show_power_and_unavailable_metrics_fallback(self):
        remote={'cpu_package_power':{'watts':5},'battery_gauge':{'g':1}}
        with mock.patch.object(self.front,'snapshot',return_value={'fan':{}}) as snap:
            status,out=self.run_cli(['show','--json'],self.metrics_service(remote))
        self.assertEqual(status,0);snap.assert_called_once_with(remote)
        service=FakeService();service.do_Control=lambda command,args_json:core.success({'watts':7,'command':command})
        self.assertEqual(self.run_cli(['power'],service),(0,{'watts':7,'command':'power'}))
        errors=io.StringIO()
        with mock.patch.object(self.front,'service_client',lambda args:RealClient(connection=FakeService(fail='org.freedesktop.DBus.Error.ServiceUnknown'))),\
             mock.patch('sys.stderr',errors):
            self.assertIsNone(self.front.restricted_metrics(None))
        self.assertIn('root-only sections remain unavailable',errors.getvalue())
        with mock.patch.object(os,'geteuid',return_value=0),mock.patch.object(self.front,'service_client',side_effect=AssertionError('root reads locally')):
            self.assertIsNone(self.front.restricted_metrics(None))

    def test_snapshot_uses_service_sections_instead_of_local_root_only_reads(self):
        try:self.front.device()
        except RuntimeError:self.skipTest('zenbook_ec hwmon device unavailable')
        import battery_diagnostics,battery_identity,charger_adc,charger_metrics,package_power
        identity={'available':True,'manufacturer':'SVC','model':'PACK','source':'service','gauge_identifier_raw':81}
        restricted={'cpu_package_power':{'svc':1},'charger':{'svc':2},'charger_input':{'svc':3},'battery_gauge':{'svc':4},'battery_identity':identity}
        refuse=mock.Mock(side_effect=AssertionError('root-only local read'))
        with mock.patch.object(package_power,'report',refuse),mock.patch.object(charger_metrics,'report',refuse),\
             mock.patch.object(charger_adc,'report',refuse),mock.patch.object(battery_diagnostics,'report',refuse),\
             mock.patch.object(battery_identity,'report',refuse):
            r=self.front.snapshot(restricted)
        self.assertEqual((r['cpu_package_power'],r['charger_metrics'],r['charger_input'],r['battery_gauge_metrics']),({'svc':1},{'svc':2},{'svc':3},{'svc':4}))
        self.assertEqual((r['battery']['manufacturer'],r['battery']['model'],r['ec']['gauge_identifier_raw']),('SVC','PACK',81))

    def test_deprecated_auth_json_notice_on_privileged_route(self):
        with tempfile.TemporaryDirectory() as temp,mock.patch.dict(os.environ,{'XDG_CONFIG_HOME':temp}):
            p=Path(temp)/'zenbook-hardware/auth.json';p.parent.mkdir();p.write_text('{}');p.chmod(0o600)
            errors=io.StringIO()
            with mock.patch.object(self.front,'service_client',lambda args:RealClient(connection=FakeService())),\
                 mock.patch('sys.stdout',io.StringIO()),mock.patch('sys.stderr',errors):
                self.assertEqual(self.front.main(['charge-limit','80']),0)
            self.assertIn('auth.json is ignored',errors.getvalue());self.assertEqual(p.read_text(),'{}')


if __name__=='__main__':unittest.main()
