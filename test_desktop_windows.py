# SPDX-License-Identifier: GPL-2.0-only
import copy
import errno
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import api_bridge
import desktop_windows as windows
from test_session_state import Boolean,RemoteError


def report(pids=(101,),titles=False):
    return {'schema':1,'source':'GNOME Shell','titles_included':titles,'complete':True,'enumeration_errors':0,
            'windows':[dict(id=i,pid=pid,app_id='app.desktop',application='Application',focused=i==0,
                            minimized=False,z_order=i,**({'title':'Synthetic title'} if titles else {})) for i,pid in enumerate(pids)]}


class DesktopWindowTests(unittest.TestCase):
    def dbus(self):
        return SimpleNamespace(DBusException=RemoteError,Boolean=Boolean)

    def test_strict_schema_privacy_and_top_first_stack(self):
        good=report((101,102))
        result=windows.decode(json.dumps(good),False,'4')
        self.assertTrue(result['complete']);self.assertEqual(result['windows'][1]['z_order'],1)
        cases=[]
        for key,value in [('schema',True),('complete',1),('enumeration_errors',True),('enumeration_errors',1)]:
            case=copy.deepcopy(good);case[key]=value;cases.append(case)
        for key,value in [('id',True),('pid',-1),('pid',2**31),('focused',1),('minimized',None),('z_order',2),('application',7),('title','unrequested')]:
            case=copy.deepcopy(good);case['windows'][0][key]=value;cases.append(case)
        case=copy.deepcopy(good);case['windows'][1]['id']=0;cases.append(case)
        for case in cases:
            with self.subTest(case=case),self.assertRaises(OSError):windows.decode(json.dumps(case),False,'4')
        self.assertEqual(windows.decode(json.dumps(report(titles=True)),True,'4')['windows'][0]['title'],'Synthetic title')

    def test_bridge3_is_partial_and_unknown_stack_is_not_list_order(self):
        result=windows.decode(json.dumps(report()),False,'3')
        self.assertFalse(result['complete']);self.assertIsNone(result['windows'][0]['z_order'])
        for raw in ['[]','invalid','x'*(1024*1024+1)]:
            with self.assertRaises(OSError):windows.decode(raw,False,'4')

    def bridge(self,version='4',uid=None,owners=(':1.42',':1.42'),exe='/usr/bin/gnome-shell',pids=(4242,4242),titles=False,remote=None):
        owner_iter=iter(owners);pid_iter=iter(pids);calls=[]
        def manager(*args,**kwargs):
            method=args[3];calls.append(method)
            if method=='GetConnectionUnixProcessID':return next(pid_iter)
            return next(owner_iter) if method=='GetNameOwner' else os.geteuid() if uid is None else uid
        windows_reply=mock.Mock(side_effect=remote) if remote else mock.Mock(return_value=json.dumps(report(titles=titles)))
        proxy=SimpleNamespace(GetVersion=mock.Mock(return_value=version),GetWindows=windows_reply)
        bus=SimpleNamespace(call_blocking=manager,get_object=mock.Mock(return_value=proxy))
        with tempfile.TemporaryDirectory() as temp,mock.patch.dict(sys.modules,{'dbus':self.dbus()}),mock.patch.object(windows,'PROC',Path(temp)):
            (Path(temp)/'4242').mkdir();(Path(temp)/'4242/exe').symlink_to(exe)
            (Path(temp)/'4242/stat').write_text('4242 (gnome-shell) S '+' '.join(['1']*19)+' 777 0\n')
            try:result=windows._bridge(bus,titles)
            except OSError as error:result=error
        return result,bus,proxy,calls

    def test_bridge_pins_same_user_owner_and_does_not_introspect_or_activate(self):
        result,bus,proxy,calls=self.bridge()
        self.assertTrue(result['available']);bus.get_object.assert_called_once_with(':1.42',windows.PATH,introspect=False)
        self.assertEqual(calls,['GetNameOwner','GetConnectionUnixUser','GetConnectionUnixProcessID','GetConnectionUnixProcessID','GetNameOwner'])
        proxy.GetWindows.assert_called_once_with(False,dbus_interface=windows.NAME,timeout=2)
        for options,code in [({'uid':os.geteuid()+1},errno.EACCES),({'uid':True},errno.EACCES),
                             ({'owners':('bad',)},errno.EPROTO),({'owners':(':1.42',':1.43')},errno.EAGAIN),
                             ({'version':'5'},errno.EOPNOTSUPP),
                             # A same-user impostor that claimed the name first is not trusted.
                             ({'exe':'/usr/bin/python3.14'},errno.EACCES),({'exe':'/tmp/gnome-shell'},errno.EACCES),
                             ({'pids':(4243,)},errno.EACCES),({'pids':(4242,4243)},errno.EAGAIN),({'pids':(True,)},errno.EPROTO)]:
            with self.subTest(options=options):
                result,_,proxy,calls=self.bridge(**options);self.assertEqual(result.errno,code)
                self.assertFalse(any('Start' in call for call in calls))

    def test_refused_titles_are_policy_and_never_rerouted_to_accessibility(self):
        refused=RemoteError('org.zenbook.HardwareBridge.Error.TitlesDisabled')
        result,*_=self.bridge(titles=True,remote=refused)
        self.assertIsInstance(result,windows.TitlesDisabled);self.assertEqual(result.errno,errno.EACCES)
        denied,*_=self.bridge(remote=RemoteError('org.zenbook.HardwareBridge.Error.AccessDenied'))
        self.assertEqual(denied.errno,errno.EACCES);self.assertNotIsInstance(denied,windows.TitlesDisabled)
        self.assertTrue(self.bridge(titles=True)[0]['titles_included'])
        accessibility=mock.Mock(side_effect=AssertionError('must not fall back'))
        with mock.patch.dict(os.environ,{'DBUS_SESSION_BUS_ADDRESS':'unix:path=/synthetic'}),\
             mock.patch.dict(sys.modules,{'dbus':SimpleNamespace(SessionBus=lambda:object(),DBusException=RemoteError)}),\
             mock.patch.object(windows,'_bridge',side_effect=windows.TitlesDisabled(errno.EACCES,'off')),\
             mock.patch.object(windows,'_accessibility',accessibility):
            result=windows.query(True)
        self.assertFalse(result['available']);self.assertEqual(result['errno'],errno.EACCES);accessibility.assert_not_called()

    def test_no_local_bus_or_bindings_is_typed_and_never_autolaunches(self):
        for address in ['','autolaunch:','tcp:host=localhost','unix:path=/missing;autolaunch:']:
            with mock.patch.dict(os.environ,{'DBUS_SESSION_BUS_ADDRESS':address}),mock.patch.dict(sys.modules,{'dbus':None}):
                self.assertEqual(windows.query(False)['errno'],errno.ENODEV)
        with mock.patch.dict(os.environ,{'DBUS_SESSION_BUS_ADDRESS':'unix:path=/synthetic'}),mock.patch.dict(sys.modules,{'dbus':None}):
            self.assertFalse(windows.query(False)['available'])

    def test_selected_pids_keep_idle_metrics_and_do_not_sum_shared_windows(self):
        before=windows.decode(json.dumps(report((101,101))),False,'4');after=copy.deepcopy(before)
        sample={'processes':[{'pid':101,'name':'idle','start_ticks':100,'cpu_percent':0.0,'cpu_available':True,
                              'rss_bytes':4096,'rss_available':True}],'sampling':{'requested_wait_seconds':.2}}
        with mock.patch.object(windows,'query',side_effect=[before,after]),mock.patch.object(windows.process_counters,'sample_pids',return_value=sample) as read,mock.patch.object(windows.process_counters,'verify_identity') as verify:
            result=windows.call({})
        read.assert_called_once_with([101]);verify.assert_called_once_with(101,100)
        self.assertTrue(result['process_metrics_complete']);self.assertTrue(all(r['cpu_percent']==0 and r['rss_bytes']==4096 for r in result['windows']))

    def test_reused_and_new_pids_withhold_old_process_counters(self):
        before=windows.decode(json.dumps(report((101,))),False,'4');after=windows.decode(json.dumps(report((101,102))),False,'4')
        sample={'processes':[{'pid':101,'start_ticks':100}],'sampling':{}}
        with mock.patch.object(windows,'query',side_effect=[before,after]),mock.patch.object(windows.process_counters,'sample_pids',return_value=sample),mock.patch.object(windows.process_counters,'verify_identity',side_effect=OSError(errno.EAGAIN,'Reused')):
            result=windows.call({})
        self.assertFalse(result['process_metrics_complete'])
        self.assertEqual([r['process_errno'] for r in result['windows']],[errno.EAGAIN,errno.ENODATA])
        self.assertTrue(all(r['cpu_percent'] is None and r['rss_bytes'] is None for r in result['windows']))

    def test_failed_sampling_preserves_window_and_explicit_error(self):
        value=windows.decode(json.dumps(report()),False,'4')
        with mock.patch.object(windows,'query',side_effect=[value,copy.deepcopy(value)]),mock.patch.object(windows.process_counters,'sample_pids',side_effect=OSError(errno.EACCES,'Denied')):
            result=windows.call({})
        self.assertTrue(result['available']);self.assertEqual(result['process_errno'],errno.EACCES)
        self.assertFalse(result['process_metrics_complete'])

    def test_unavailable_initial_or_final_provider_is_not_success(self):
        missing={'available':False,'errno':errno.ENODEV}
        with mock.patch.object(windows,'query',return_value=missing),mock.patch.object(windows.process_counters,'sample_pids') as read:
            self.assertEqual(windows.call({}),missing);read.assert_not_called()
        with mock.patch.object(windows,'query',side_effect=[windows.decode(json.dumps(report()),False,'4'),missing]),mock.patch.object(windows.process_counters,'sample_pids',return_value={'processes':[]}):
            self.assertEqual(windows.call({}),missing)

    def test_accessibility_uses_existing_unique_owners_and_never_reads_unrequested_titles(self):
        for titles in [False,True]:
            calls=[]
            def invoke(destination,path,interface,method,signature,args,timeout):
                calls.append((destination,path,method,args))
                self.assertLessEqual(timeout,2)
                if interface=='org.freedesktop.DBus':
                    if method=='GetNameOwner':return ':1.1' if args[0]=='org.a11y.Bus' else ':1.2' if args[0]=='org.a11y.atspi.Registry' else args[0]
                    if method=='GetConnectionUnixUser':return os.geteuid()
                    if method=='GetConnectionUnixProcessID':return 101
                self.assertTrue(destination.startswith(':'))
                if method=='GetChildren':return [(':1.3','/application')] if path.endswith('/root') else [(':1.3','/window'),(':1.3','/control')]
                if method=='GetRole':return 23 if path=='/window' else 42
                if method=='Get':return 'Synthetic application' if path=='/application' else 'Synthetic title'
                self.fail('Unexpected call')
            proxy=SimpleNamespace(GetAddress=mock.Mock(return_value='unix:path=/synthetic-accessibility'))
            registry=SimpleNamespace(call_blocking=invoke,close=mock.Mock())
            bus=SimpleNamespace(call_blocking=invoke,get_object=mock.Mock(return_value=proxy))
            dbus=self.dbus();dbus.bus=SimpleNamespace(BusConnection=mock.Mock(return_value=registry))
            with mock.patch.dict(sys.modules,{'dbus':dbus}):result=windows._accessibility(bus,titles)
            registry.close.assert_called_once();self.assertFalse(result['complete']);self.assertEqual(result['enumeration_errors'],0)
            self.assertEqual(result['windows'][0]['pid'],101);self.assertIsNone(result['windows'][0]['z_order'])
            self.assertEqual(any(path=='/window' and method=='Get' for _,path,method,_ in calls),titles)
            self.assertFalse(any('Start' in method for _,_,method,_ in calls))

    def test_missing_accessibility_registry_never_initializes_atspi(self):
        proxy=SimpleNamespace(GetAddress=mock.Mock(return_value='unix:path=/synthetic'))
        registry=SimpleNamespace(close=mock.Mock())
        dbus=self.dbus();dbus.bus=SimpleNamespace(BusConnection=mock.Mock(return_value=registry))
        with mock.patch.dict(sys.modules,{'dbus':dbus,'gi':None}),mock.patch.object(windows,'_owner',side_effect=[':1.1',OSError(errno.ENODEV,'No registry')]),self.assertRaises(OSError):
            windows._accessibility(SimpleNamespace(get_object=lambda *a,**k:proxy),False)
        registry.close.assert_called_once()

    def test_public_arguments_rejected_before_desktop_access(self):
        with mock.patch.object(windows,'query') as query:
            for args in [{'include_titles':1},{'all':True},[]]:
                with self.subTest(args=args),self.assertRaises(ValueError):api_bridge.call({'name':'AppList_OpenWindows','args':args})
        query.assert_not_called()


if __name__=='__main__':unittest.main()
