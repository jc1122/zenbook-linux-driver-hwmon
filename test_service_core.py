# SPDX-License-Identifier: GPL-2.0-only
"""Unit tests for the privileged service: authorization mapping, request
validation, rate limiting, audit logging, fan leases and installation."""
from pathlib import Path
from unittest import mock
import errno
import importlib.util
import io
import json
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'service'))
import hwd_core as core  # noqa: E402

SPEC=importlib.util.spec_from_file_location('asus_ht_installer_service',ROOT/'tools/install.py')
installer=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(installer)


def exports():return set(json.loads((ROOT/'capabilities.json').read_text())['exports'])


class AuthorizationMappingTests(unittest.TestCase):
    def setUp(self):self.table=core.load_authorization(exports())

    def test_every_capabilities_export_has_exactly_one_known_action(self):
        self.assertEqual(set(self.table),exports())
        for name,action in self.table.items():self.assertIn(action,core.ACTIONS,name)

    def test_gaps_extras_and_unknown_actions_are_refused(self):
        data=json.loads((ROOT/'service/authorization.json').read_text())
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'a.json'
            for change in ('missing','extra','unknown'):
                broken=json.loads(json.dumps(data))
                if change=='missing':broken['exports'].pop('GetIoDllVersion')
                if change=='extra':broken['exports']['NotAnExport']=core.READ
                if change=='unknown':broken['exports']['GetIoDllVersion']='org.zenbook.hardware.everything'
                path.write_text(json.dumps(broken))
                with self.assertRaises(ValueError,msg=change):core.load_authorization(exports(),path)
            with self.assertRaises(ValueError):core.load_authorization(exports()|{'NewExport'})

    def test_dangerous_exports_map_to_admin_actions(self):
        import efi_oem,native_oem
        for name in efi_oem.WRITES:self.assertEqual(self.table[name],core.FIRMWARE,name)
        for name in native_oem.MUTATIONS:self.assertEqual(self.table[name],core.EC_OEM,name)
        self.assertEqual(self.table['WOA_EC_write'],core.EC_OEM);self.assertEqual(self.table['WOA_EC_read'],core.EC_OEM)
        for name in ('InitializeWinIo','StopWinIoDriver'):self.assertEqual(self.table[name],core.DRIVER)
        for name in ('WMISetBatteryHealth','WMISetBatteryHealthToUser','WMISetQuietFan'):self.assertEqual(self.table[name],core.SETTINGS)
        for name in core.FAN_EXPORTS:self.assertEqual(self.table[name],core.FAN_LEASE)
        for name in ('WMIGetSN','WMIGetType2SN','WMIGetBoardUUID','WMIGetMacAddress','RF_AP_MAC','BatteryHealthyTable_SerialNumber','GPNV_Get_RandomUUID','WMIGet90Number'):
            self.assertEqual(self.table[name],core.READ_IDENTIFIERS,name)
        for name in core.HARDWARE_ONLY:self.assertTrue(core.is_mutating(self.table[name]))

    def test_policy_file_matches_action_table(self):
        tree=ET.parse(ROOT/'service/org.zenbook.hardware.policy')  # noqa: S314 - repository file
        found={}
        for action in tree.getroot().iter('action'):
            d=action.find('defaults')
            found[action.get('id')]=(d.findtext('allow_any'),d.findtext('allow_inactive'),d.findtext('allow_active'))
        self.assertEqual(found,{k:v[0] for k,v in core.ACTIONS.items()})
        for action in core.NEVER_GROUP_GRANTED:self.assertEqual(found[action],('no','no','auth_admin'))

    def test_group_rule_grants_only_the_owner_approved_actions(self):
        text=(ROOT/'service/49-zenbook-hardware.rules').read_text()
        code=re.sub(r'//.*','',text)
        granted=set(re.findall(r'"(org\.zenbook\.hardware\.[a-z-]+)"',code))
        self.assertEqual(granted,set(core.GROUP_GRANTED))
        self.assertFalse(granted&core.NEVER_GROUP_GRANTED)
        self.assertIn('isInGroup("zenbook-hw")',code);self.assertEqual(code.count('polkit.Result.YES'),1)

    def test_bus_policy_restricts_ownership_to_root(self):
        root=ET.parse(ROOT/'service/org.zenbook.Hardware1.conf').getroot()  # noqa: S314 - repository file
        owners=[(p.attrib,a.get('own')) for p in root.iter('policy') for a in p.iter('allow') if a.get('own')]
        self.assertEqual(owners,[({'user':'root'},core.BUS_NAME)])
        senders={tuple(p.attrib.items()) for p in root.iter('policy') for a in p.iter('allow') if a.get('send_destination')}
        self.assertEqual(senders,{(('user','root'),),(('group','zenbook-hw'),)})
        default=[p for p in root.iter('policy') if p.get('context')=='default'][0]
        self.assertFalse(list(default.iter('allow')))
        self.assertEqual([d.attrib for d in default.iter('deny')],[{'send_destination':core.BUS_NAME}])
        activation=(ROOT/'service/org.zenbook.Hardware1.service').read_text()
        self.assertIn('Name=org.zenbook.Hardware1\n',activation);self.assertIn('SystemdService=zenbook-hardwared.service\n',activation)

    def test_controls_use_known_actions(self):
        for command,action in core.CONTROLS.items():self.assertIn(action,core.ACTIONS,command)
        self.assertEqual({c for c,a in core.CONTROLS.items() if a==core.SETTINGS},{'profile','charge-limit','keyboard','reprobe','battery-history-refresh'})
        self.assertLessEqual(core.SLOW_CONTROLS,set(core.CONTROLS))

    def test_mutation_export_sets_match_providers(self):
        import efi_oem,native_oem
        self.assertEqual(set(core.MUTATION_EXPORTS),set(native_oem.MUTATIONS)|set(efi_oem.WRITES)|{'StopWinIoDriver'})
        self.assertEqual(set(core.SERVICE_APPLY),set(native_oem.MUTATIONS))
        self.assertLessEqual(core.SLOW_CALLS|core.CACHE_EXEMPT,exports())
        for name in core.MUTATION_EXPORTS:self.assertIn(self.table[name],core.NEVER_GROUP_GRANTED,name)


class RequestValidationTests(unittest.TestCase):
    table={'GetIoDllVersion':core.READ,'WOA_EC_write':core.EC_OEM}

    def parse(self,*args):return core.parse_call(*args,self.table)

    def test_valid_request(self):
        self.assertEqual(self.parse('GetIoDllVersion','{}',False,''),('GetIoDllVersion',{},False,None,core.READ))
        self.assertEqual(self.parse('WOA_EC_write','{"index":1}',True,'a'*64)[1:4],({'index':1},True,'a'*64))
        self.assertEqual(self.parse('GetIoDllVersion','',False,'')[1],{})

    def test_rejections_use_stable_errno(self):
        cases=[('Nope','{}',False,''),('Get IoDll','{}',False,''),('x'*200,'{}',False,''),
               ('GetIoDllVersion','[]',False,''),('GetIoDllVersion','{"a":1,"a":2}',False,''),('GetIoDllVersion','{"a":NaN}',False,''),
               ('GetIoDllVersion','{',False,''),('GetIoDllVersion','{}',False,'A'*64),('GetIoDllVersion','{}',False,'abc'),
               ('GetIoDllVersion','{}','yes',''),('GetIoDllVersion','['*100000,False,'')]
        for case in cases:
            with self.assertRaises(core.ServiceError,msg=case[0][:20]) as caught:self.parse(*case)
            self.assertIn(caught.exception.errno,(errno.EINVAL,errno.E2BIG))
        for raw in ('{"a":1e999}','{"a":-1e999}','{"a":[1E400]}','{"a":{"b":Infinity}}','{"a":-Infinity}'):
            with self.assertRaises(core.ServiceError,msg=raw) as caught:core.parse_args(raw)
            self.assertEqual(caught.exception.errno,errno.EINVAL);self.assertIn('Non-finite JSON value',str(caught.exception))
        self.assertEqual(core.parse_args('{"a":1.5,"b":-0.0,"c":1e308,"d":10}'),{'a':1.5,'b':-0.0,'c':1e308,'d':10})
        with self.assertRaises(core.ServiceError) as caught:self.parse('GetIoDllVersion','{"a":"'+'x'*70000+'"}',False,'')
        self.assertEqual(caught.exception.errno,errno.E2BIG)

    def test_error_envelope_matches_api_bridge(self):
        import api_bridge
        class Control(OSError):
            def __init__(self):super().__init__(errno.EAGAIN,'changed');self.control_result={'x':1};self.committed=False
        for error in (PermissionError('denied'),ValueError('bad'),KeyError('k'),OSError(errno.ENODEV,'absent'),RuntimeError('boom'),Control()):
            with mock.patch.object(api_bridge,'call',side_effect=error),mock.patch.object(sys,'stdin',io.TextIOWrapper(io.BytesIO(b'{}'))), \
                 mock.patch('sys.stdout',new_callable=io.StringIO) as out:
                api_bridge.main()
            self.assertEqual(json.loads(out.getvalue()),json.loads(core.failure(error)),type(error).__name__)
        self.assertEqual(json.loads(core.success({'a':1})),{'ok':True,'result':{'a':1}})
        self.assertEqual(core.dbus_error_name(errno.EBUSY),'org.zenbook.Hardware1.Error.EBUSY')


class RateLimitTests(unittest.TestCase):
    def test_token_bucket_per_uid_and_class(self):
        now=[0.0];limiter=core.RateLimiter(clock=lambda:now[0],limits={'read':(2.0,3.0),'mutating':(1.0,1.0)})
        self.assertEqual([limiter.allow(1000,'read') for _ in range(4)],[True,True,True,False])
        self.assertTrue(limiter.allow(1001,'read'))  # independent caller
        self.assertTrue(limiter.allow(1000,'mutating'));self.assertFalse(limiter.allow(1000,'mutating'))
        now[0]=0.5;self.assertTrue(limiter.allow(1000,'read'));self.assertFalse(limiter.allow(1000,'read'))
        now[0]=1.5;self.assertTrue(limiter.allow(1000,'mutating'))
        now[0]=100;self.assertEqual(sum(limiter.allow(1000,'read') for _ in range(10)),3)

    def test_key_table_is_bounded(self):
        limiter=core.RateLimiter(max_keys=10)
        for uid in range(100):limiter.allow(uid,'read')
        self.assertLessEqual(len(limiter.buckets),10)


class SlowClassAndCacheTests(unittest.TestCase):
    def test_slow_class_is_per_uid_and_global(self):
        now=[0.0];limiter=core.RateLimiter(clock=lambda:now[0],limits={'read':(1,1),'mutating':(1,1),'slow':(0.1,1.0)})
        self.assertEqual(core.RateLimiter.LIMITS['slow'],(0.1,3.0))
        self.assertTrue(limiter.allow_slow(1000));self.assertFalse(limiter.allow_slow(1000))
        self.assertFalse(limiter.allow_slow(1001))  # global bucket is empty too
        now[0]=9.9;self.assertFalse(limiter.allow_slow(1001))
        now[0]=10.1;self.assertTrue(limiter.allow_slow(1001))
        # A refusal does not consume the caller's own token.
        now[0]=25;self.assertTrue(limiter.allow_slow(1000))

    def test_cache_expires_and_is_bounded(self):
        now=[0.0];cache=core.ResultCache(clock=lambda:now[0],max_entries=3)
        key=core.ResultCache.key('X',{'b':1,'a':2})
        self.assertEqual(key,core.ResultCache.key('X',{'a':2,'b':1}))
        cache.put(key,'v');now[0]=1.9;self.assertEqual(cache.get(key),'v')
        now[0]=2.0;self.assertIsNone(cache.get(key))
        for i in range(10):cache.put(('k',str(i)),i)
        self.assertLessEqual(len(cache.entries),3)

    def test_cacheable_policy(self):
        self.assertTrue(core.cacheable('WMIGetBiosVersion',core.READ,False))
        self.assertTrue(core.cacheable('WMIGetSN',core.READ_IDENTIFIERS,False))
        for name,action,apply in (('HealthyTable_FanRPM',core.READ,False),('WMISetQuietFan',core.SETTINGS,False),
                                  ('WOA_EC_read',core.EC_OEM,False),('WMIGetBiosVersion',core.READ,True)):
            self.assertFalse(core.cacheable(name,action,apply),name)


class SlowCoalescingAndDenialTests(unittest.TestCase):
    def test_slow_groups_cover_slow_calls(self):
        self.assertEqual(set(core.SLOW_GROUPS),set(core.SLOW_CALLS))
        self.assertEqual(core.SLOW_GROUPS['BatteryHealthyTable_PFStatus'],core.SLOW_GROUPS['BatteryHealthyTable_SafetyStatus'])
        for name in core.SLOW_CALLS:self.assertFalse(core.cacheable(name,core.READ,False))

    def test_slow_wait(self):
        now=[0.0];limiter=core.RateLimiter(clock=lambda:now[0],limits={'read':(1,1),'mutating':(1,1),'slow':(0.1,3.0)})
        self.assertEqual(core.slow_wait(limiter,1000),0.0)
        for _ in range(3):self.assertTrue(limiter.allow_slow(1000))
        self.assertAlmostEqual(core.slow_wait(limiter,1000),10.0)
        now[0]=6;self.assertAlmostEqual(core.slow_wait(limiter,1001),4.0)  # global bucket governs
        now[0]=10;self.assertEqual(core.slow_wait(limiter,1001),0.0)

    def test_sandbox_denials_count_rows_without_reading_values(self):
        self.assertEqual(core.sandbox_denials({'rows':[{'errno':1},{'errno':13,'x':{'errno':1}},{'errno':19},{'errno':True}]}),3)
        self.assertEqual(core.sandbox_denials({'available':True,'value':1}),0)
        self.assertEqual(core.sandbox_denials('text'),0)
        deep=cur=[]
        for _ in range(20000):cur.append([]);cur=cur[0]
        core.sandbox_denials(deep)  # bounded walk


class SyscallFilterTests(unittest.TestCase):
    STATIC_DEBUG={'lookup_dcookie','perf_event_open','pidfd_getfd','ptrace','rtas','s390_runtime_instr','sys_debug_setcontext'}

    def filters(self):
        unit=(ROOT/'service/zenbook-hardwared.service.in').read_text()
        allow=set();deny=set()
        for line in unit.splitlines():
            if not line.startswith('SystemCallFilter='):continue
            value=line.split('=',1)[1]
            (deny if value.startswith('~') else allow).update(value.lstrip('~').split())
        return allow,deny

    def debug_group(self):
        import shutil,subprocess
        tool=shutil.which('systemd-analyze')
        if tool:
            out=subprocess.run([tool,'syscall-filter','@debug'],capture_output=True,text=True,timeout=10).stdout
            names={line.strip() for line in out.splitlines()[1:] if line.strip() and not line.strip().startswith('#')}
            if names:return names
        return self.STATIC_DEBUG

    def test_perf_event_open_allowed_and_other_debug_calls_denied(self):
        allow,deny=self.filters()
        self.assertIn('perf_event_open',allow);self.assertNotIn('perf_event_open',deny)
        self.assertNotIn('@debug',deny)  # a group deny would override the allow
        self.assertLessEqual(self.debug_group()-{'perf_event_open'},deny)
        self.assertLessEqual(self.STATIC_DEBUG-{'perf_event_open'},deny)
        self.assertNotIn('ptrace',allow)


class VitalsSectionTests(unittest.TestCase):
    def test_sections_are_exactly_what_vitals_consumes(self):
        source=ROOT/'integrations/vitals/service.js'
        if not source.exists():self.skipTest('Vitals service helper not present.')
        consumed=set(re.findall(r'report\?\.([a-z_]+)',source.read_text()))
        self.assertEqual(set(core.VITALS_SECTIONS),consumed)

    def test_sections_use_the_same_providers_as_metrics(self):
        text=(ROOT/'metrics.py').read_text()
        for section,(module,function) in core.VITALS_SECTIONS.items():
            self.assertIn("'%s':%s.%s()"%(section,module,function),text,section)
        self.assertNotIn('ec_diagnostics',core.VITALS_SECTIONS)


class MutationTokenTests(unittest.TestCase):
    def setUp(self):
        self.now=[0.0];counter=iter(range(1000))
        self.tokens=core.MutationTokens(clock=lambda:self.now[0],max_tokens=3,token=lambda:'%032x'%next(counter))
        self.digest='a'*64

    def test_single_use_and_binding(self):
        token=self.tokens.issue(':1.1',1000,core.EC_OEM,'WOA_EC_write',{'b':1,'a':2},self.digest)
        for value,sender,uid,code in ((token,':1.2',1000,errno.EACCES),(token,':1.1',1001,errno.EACCES),('zz',':1.1',1000,errno.EINVAL)):
            with self.assertRaises(core.ServiceError) as caught:self.tokens.consume(value,sender,uid)
            self.assertEqual(caught.exception.errno,code)
        entry=self.tokens.consume(token,':1.1',1000)  # foreign attempts did not consume it
        self.assertEqual((entry['name'],entry['action'],entry['args'],entry['digest']),('WOA_EC_write',core.EC_OEM,{'a':2,'b':1},self.digest))
        with self.assertRaises(core.ServiceError) as caught:self.tokens.consume(token,':1.1',1000)
        self.assertEqual(caught.exception.errno,errno.ENOENT)

    def test_expiry_replacement_bound_and_digest(self):
        token=self.tokens.issue(':1.1',1000,core.EC_OEM,'WOA_EC_write',{},self.digest)
        self.now[0]=60
        with self.assertRaises(core.ServiceError):self.tokens.consume(token,':1.1',1000)
        first=self.tokens.issue(':1.1',1000,core.EC_OEM,'WOA_EC_write',{},self.digest)
        second=self.tokens.issue(':1.1',1000,core.EC_OEM,'WOA_EC_write',{},self.digest)
        with self.assertRaises(core.ServiceError):self.tokens.consume(first,':1.1',1000)  # replaced
        self.tokens.issue(':1.2',1000,core.EC_OEM,'WOA_EC_write',{},self.digest)
        self.tokens.issue(':1.3',1000,core.EC_OEM,'WOA_EC_write',{},self.digest)
        with self.assertRaises(core.ServiceError) as caught:self.tokens.issue(':1.4',1000,core.EC_OEM,'WOA_EC_write',{},self.digest)
        self.assertEqual(caught.exception.errno,errno.EBUSY)
        self.assertEqual(self.tokens.consume(second,':1.1',1000)['digest'],self.digest)
        with self.assertRaises(core.ServiceError):self.tokens.issue(':1.1',1000,core.EC_OEM,'WOA_EC_write',{},None)


class AuditTests(unittest.TestCase):
    def test_only_whitelisted_fields_reach_the_journal(self):
        stream=io.StringIO();audit=core.AuditLog(stream)
        audit.write(event='call',uid=1000,sender=':1.5',action=core.SETTINGS,name='WMISetQuietFan',apply=False,
                    arg_keys=core.arg_keys({'profile':'quiet'}),result='ok',args={'profile':'quiet'},credential_value='hunter2',message='serial XYZ')
        line=stream.getvalue()
        self.assertTrue(line.startswith('AUDIT ') and line.endswith('\n'))
        record=json.loads(line[6:])
        self.assertEqual(record,{'event':'call','uid':1000,'sender':':1.5','action':core.SETTINGS,'name':'WMISetQuietFan',
                                 'apply':False,'arg_keys':['profile'],'result':'ok'})
        for value in ('quiet','hunter2','XYZ'):self.assertNotIn(value,line)

    def test_arg_keys_are_bounded(self):
        keys=core.arg_keys({str(i)*100:i for i in range(40)})
        self.assertEqual(len(keys),16);self.assertTrue(all(len(k)<=64 for k in keys))
        self.assertIsNone(core.arg_keys([1]))


class FakeFan:
    def __init__(self,rpm=3000):self.mode_value=2;self.duty=0;self.rpm_value=rpm;self.fail_restore=0;self.fail_read=False;self.writes=[]
    def mode(self):
        if self.fail_read:raise OSError(errno.EIO,'read')
        return self.mode_value
    def rpm(self):
        if self.fail_read:raise OSError(errno.EIO,'read')
        return self.rpm_value
    def write_mode(self,mode):
        self.writes.append(('mode',mode))
        if mode==2 and self.fail_restore:self.fail_restore-=1;raise OSError(errno.EIO,'write')
        self.mode_value=mode
    def write_duty(self,duty):self.writes.append(('duty',duty));self.duty=duty


class FanLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.marker=Path(self.temp.name)/'lease.json'
        self.now=[100.0];self.fan=FakeFan();self.stream=io.StringIO();self.ended=[]
        self.leases=core.FanLeases(self.fan,core.AuditLog(self.stream),clock=lambda:self.now[0],marker=self.marker,
                                   token=lambda:'0'*32,on_end=lambda lease,reason:self.ended.append(reason))

    def tearDown(self):self.temp.cleanup()

    def audit(self):return [json.loads(line[6:]) for line in self.stream.getvalue().splitlines()]

    def test_acquire_sets_duty_then_manual_and_writes_marker(self):
        self.assertEqual(self.leases.acquire(':1.1',1000,10,'50'),'0'*32)
        self.assertEqual(self.fan.writes,[('duty',128),('mode',1)]);self.assertTrue(self.marker.exists())
        self.assertEqual(json.loads(self.marker.read_text()),{'lease':'0'*32,'uid':1000})
        self.assertEqual(self.marker.stat().st_mode&0o777,0o600)
        self.assertTrue(self.leases.held_by(':1.1'));self.assertFalse(self.leases.held_by(':1.2'))
        self.assertEqual(self.leases.active()['minimum_rpm'],1500)

    def test_full_and_percent_mapping_and_bounds(self):
        self.assertEqual(core.parse_fan_request('full'),(0,None))
        self.assertEqual([core.parse_fan_request(str(p))[1] for p in (0,1,50,100)],[0,3,128,255])
        for bad in ('auto','101','-1','1.5','0x10','',' 5','٥',None,'0100'):
            with self.assertRaises(core.ServiceError):core.parse_fan_request(bad)
        for seconds in (0,301,True,1.5):
            with self.assertRaises(core.ServiceError):self.leases.acquire(':1.1',1000,seconds,'50')
        self.assertEqual(self.fan.writes,[])

    def test_single_lease_and_firmware_automatic_precondition(self):
        self.leases.acquire(':1.1',1000,10,'50')
        with self.assertRaises(core.ServiceError) as caught:self.leases.acquire(':1.2',1000,10,'50')
        self.assertEqual(caught.exception.errno,errno.EBUSY)
        self.leases.release('0'*32,':1.1')
        self.fan.mode_value=1
        with self.assertRaises(core.ServiceError) as caught:self.leases.acquire(':1.1',1000,10,'50')
        self.assertEqual(caught.exception.errno,errno.EBUSY)

    def test_expiry_restores_automatic(self):
        self.leases.acquire(':1.1',1000,10,'50')
        self.now[0]=109;self.assertIsNone(self.leases.tick());self.assertEqual(self.fan.mode_value,1)
        self.now[0]=110;result=self.leases.tick()
        self.assertEqual((result['reason'],result['automatic_restored'],result['mode']),('expired',True,2))
        self.assertFalse(self.marker.exists());self.assertIsNone(self.leases.active());self.assertEqual(self.ended,['expired'])

    def test_disconnect_restores_only_for_the_holder(self):
        self.leases.acquire(':1.1',1000,60,'50')
        self.assertIsNone(self.leases.owner_vanished(':1.9'));self.assertEqual(self.fan.mode_value,1)
        self.assertEqual(self.leases.owner_vanished(':1.1')['reason'],'holder_disconnected');self.assertEqual(self.fan.mode_value,2)

    def test_low_rpm_and_read_failure_abort(self):
        self.leases.acquire(':1.1',1000,60,'10');self.fan.rpm_value=1499
        self.assertEqual(self.leases.tick()['reason'],'low_rpm_abort');self.assertEqual(self.fan.mode_value,2)
        self.leases.acquire(':1.1',1000,60,'10');self.fan.fail_read=True
        self.assertEqual(self.leases.tick()['reason'],'fan_read_failed');self.assertEqual(self.fan.mode_value,2)

    def test_minimum_rpm_matches_kernel_formula(self):
        self.assertEqual([core.minimum_rpm(b) for b in (0,800,1000,1002,3000)],[500,500,500,501,1500])

    def test_external_automatic_restoration_ends_lease_without_extra_write(self):
        self.leases.acquire(':1.1',1000,60,'50');self.fan.mode_value=2;self.fan.writes.clear()
        self.assertEqual(self.leases.tick()['reason'],'restored_externally');self.assertEqual(self.fan.writes,[])

    def test_release_rules(self):
        self.leases.acquire(':1.1',1000,60,'50')
        for lease_id,owner,code in (('bad',':1.1',errno.EINVAL),('1'*32,':1.1',errno.ENOENT),('0'*32,':1.2',errno.EPERM)):
            with self.assertRaises(core.ServiceError) as caught:self.leases.release(lease_id,owner)
            self.assertEqual(caught.exception.errno,code)
        self.assertEqual(self.leases.release('0'*32,':1.2',privileged=True)['reason'],'released')

    def test_stop_and_set_auto(self):
        self.assertIsNone(self.leases.stop())
        self.leases.acquire(':1.1',1000,60,'50')
        self.assertEqual(self.leases.stop()['reason'],'service_stopping');self.assertEqual(self.fan.mode_value,2)
        self.fan.mode_value=1
        self.assertTrue(self.leases.set_auto()['automatic_restored']);self.assertEqual(self.fan.mode_value,2)

    def test_failed_restoration_keeps_marker_and_retries(self):
        self.leases.acquire(':1.1',1000,1,'50');self.fan.fail_restore=3;self.now[0]=200
        result=self.leases.tick()
        self.assertFalse(result['automatic_restored']);self.assertTrue(self.marker.exists());self.assertTrue(self.leases.needs_ticks())
        with self.assertRaises(core.ServiceError):self.leases.acquire(':1.1',1000,10,'50')
        self.leases.tick();self.assertEqual(self.fan.mode_value,2);self.assertFalse(self.marker.exists());self.assertFalse(self.leases.needs_ticks())
        events=[r['event'] for r in self.audit()]
        self.assertEqual(events[-2:],['fan_lease_ended','fan_restore_retry'])
        self.assertEqual(self.audit()[-2]['result'],'error')

    def test_failed_acquire_restores(self):
        def broken(duty):raise OSError(errno.EIO,'duty')
        self.fan.write_duty=broken
        with self.assertRaises(OSError):self.leases.acquire(':1.1',1000,10,'50')
        self.assertEqual(self.fan.mode_value,2);self.assertFalse(self.marker.exists());self.assertIsNone(self.leases.active())

    def test_stale_marker_recovery(self):
        self.assertFalse(self.leases.recover())
        self.marker.write_text('{}');self.fan.mode_value=1
        self.assertTrue(self.leases.recover());self.assertEqual(self.fan.mode_value,2);self.assertFalse(self.marker.exists())

    def test_sysfs_fan_and_restore_readback(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)
            for name,value in (('pwm1_enable','1'),('pwm1','0'),('fan1_input','2900')):(path/name).write_text(value+'\n')
            fan=core.SysfsFan(lambda:path)
            fan.write_duty(77);self.assertEqual((path/'pwm1').read_text(),'77\n')
            self.assertEqual((fan.mode(),fan.rpm()),(1,2900))
            self.assertTrue(core.restore_auto(fan));self.assertEqual((path/'pwm1_enable').read_text(),'2\n')
        stuck=FakeFan();stuck.write_mode=lambda mode:None;stuck.mode_value=1
        with self.assertRaises(core.ServiceError):core.restore_auto(stuck)


class InstallerServiceTests(unittest.TestCase):
    def install(self,root,target):
        with mock.patch.object(installer,'run') as run,mock.patch.object(installer,'ensure_group') as group:
            result=installer.install_service(target,root,read_write='ReadWritePaths=-/sys/devices/platform/zenbook_healthytable',
                                             tablet_devices=['/dev/input/by-path/platform-INTC1078:00-event'])
        return result,run,group

    def runtime(self,base):
        target=base/'runtime';(target/'service').mkdir(parents=True)
        for name in installer.SERVICE_RUNTIME:(target/name).write_bytes((ROOT/name).read_bytes())
        return target

    def test_installs_integration_files_without_enabling(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'root';target=self.runtime(Path(temp))
            result,run,group=self.install(root,target)
            self.assertFalse(result['enabled']);group.assert_called_once()
            for path in [*installer.SERVICE_FILES.values(),installer.SERVICE_UNIT]:
                self.assertEqual((root/path).stat().st_mode&0o777,0o644,path)
            unit=(root/installer.SERVICE_UNIT).read_text()
            self.assertIn('ExecStart=/usr/bin/python3 -I -B '+str(target)+'/service/zenbook_hardwared.py',unit)
            self.assertIn('ReadWritePaths=-/sys/devices/platform/zenbook_healthytable',unit)
            self.assertNotIn('char-input',unit);self.assertIn('PrivatePIDs=yes',unit);self.assertIn('StartLimitBurst=10',unit)
            settings=[line for line in unit.splitlines() if line and not line.startswith('#')]
            self.assertEqual([l for l in settings if l.startswith(('CapabilityBoundingSet=','AmbientCapabilities='))],
                             ['CapabilityBoundingSet=CAP_PERFMON','AmbientCapabilities=CAP_PERFMON'])
            self.assertIn('SystemCallFilter=perf_event_open',settings)
            self.assertEqual([l for l in settings if l.startswith('DeviceAllow=')],
                             ['DeviceAllow=/dev/usbmon0 r','DeviceAllow=/dev/input/by-path/platform-INTC1078:00-event r'])
            self.assertNotIn('@RUNTIME@',unit);self.assertNotIn('\n[Install]',unit);self.assertIn('CapabilityBoundingSet=CAP_PERFMON\n',unit)
            commands=[c.args[0] for c in run.call_args_list]
            self.assertTrue(all(c[0].startswith('/usr/') for c in commands))
            self.assertFalse(any('enable' in c or 'start' in c or 'usermod' in ' '.join(c) for c in commands))
            # Idempotent reinstall over our own files.
            self.install(root,target)

    def test_install_is_transactional(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'root';target=self.runtime(Path(temp))
            self.install(root,target)
            unit=root/installer.SERVICE_UNIT;before=unit.read_text()
            calls=[]
            def failing(command):
                calls.append(command)
                if command[-1]=='ReloadConfig' and len(calls)==2:raise installer.subprocess.CalledProcessError(1,command)
            with mock.patch.object(installer,'run',side_effect=failing),mock.patch.object(installer,'ensure_group',return_value={'created':False,'members':[]}), \
                 self.assertRaises(installer.subprocess.CalledProcessError):
                installer.install_service(target,root,read_write='ReadWritePaths=-/sys/changed',hwmon_path='/sys/h',tablet_devices=[])
            self.assertEqual(unit.read_text(),before)  # previous content restored
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'root';target=self.runtime(Path(temp))
            with mock.patch.object(installer,'run',side_effect=OSError(5,'boom')),mock.patch.object(installer,'ensure_group',return_value={'created':True,'members':[]}), \
                 self.assertRaises(OSError):
                installer.install_service(target,root,read_write='ReadWritePaths=-/sys/x',hwmon_path='/sys/h',tablet_devices=[])
            for path in [*installer.SERVICE_FILES.values(),installer.SERVICE_UNIT]:self.assertFalse((root/path).exists(),path)

    def test_refuses_foreign_files_and_rolls_back_only_managed_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'root';target=self.runtime(Path(temp))
            foreign=root/installer.SERVICE_FILES['service/49-zenbook-hardware.rules']
            foreign.parent.mkdir(parents=True);foreign.write_text('polkit.addRule(function(){});\n')
            with self.assertRaises(RuntimeError):self.install(root,target)
            foreign.unlink();self.install(root,target)
            with mock.patch.object(installer,'run') as run:removed=installer.remove_service(root)
            self.assertEqual(len(removed),5);self.assertTrue(target.exists())
            self.assertIn(['/usr/bin/systemctl','stop','zenbook-hardwared.service'],[c.args[0] for c in run.call_args_list])

    def test_group_creation_is_idempotent_and_adds_no_members(self):
        with mock.patch.object(installer,'run') as run,mock.patch('grp.getgrnam',side_effect=KeyError):
            installer.ensure_group()
        run.assert_called_once_with(['/usr/sbin/groupadd','--system','zenbook-hw'])
        group=mock.Mock(gr_mem=['alice'],gr_gid=990)
        with mock.patch.object(installer,'run') as run,mock.patch('grp.getgrnam',return_value=group), \
             mock.patch('pwd.getpwall',return_value=[mock.Mock(pw_name='agent',pw_gid=990),mock.Mock(pw_name='other',pw_gid=1)]), \
             mock.patch('sys.stderr',new_callable=io.StringIO) as err:
            result=installer.ensure_group()
        run.assert_not_called()
        self.assertEqual(result,{'created':False,'members':['agent','alice']})
        self.assertIn('already exists',err.getvalue());self.assertIn('agent, alice',err.getvalue())

    @staticmethod
    def fake_sysfs(root,index,keyboard=True):
        """Minimal Zenbook-shaped sysfs tree with relative class symlinks, as on a real host."""
        platform=root/'sys/devices/platform/zenbook_healthytable'
        device=platform/'hwmon'/('hwmon%d'%index);device.mkdir(parents=True)
        (device/'name').write_text('zenbook_ec\n')
        for name in installer.HWMON_WRITES:(device/name).write_text('')
        hwmon=root/'sys/class/hwmon';hwmon.mkdir(parents=True,exist_ok=True)
        for old in hwmon.iterdir():old.unlink()
        (hwmon/('hwmon%d'%index)).symlink_to('../../devices/platform/zenbook_healthytable/hwmon/hwmon%d'%index)
        acpi=root/'sys/firmware/acpi';acpi.mkdir(parents=True,exist_ok=True);(acpi/'platform_profile').write_text('balanced\n')
        battery=root/'sys/devices/LNXSYSTM:00/PNP0C0A:00/power_supply/BAT0';battery.mkdir(parents=True,exist_ok=True)
        (battery/'charge_control_end_threshold').write_text('100\n')
        supply=root/'sys/class/power_supply';supply.mkdir(parents=True,exist_ok=True)
        if not (supply/'BAT0').is_symlink():(supply/'BAT0').symlink_to('../../devices/LNXSYSTM:00/PNP0C0A:00/power_supply/BAT0')
        if keyboard:
            led=root/'sys/devices/platform/asus-nb-wmi/leds/asus::kbd_backlight';led.mkdir(parents=True,exist_ok=True)
            (led/'brightness').write_text('0\n')
            leds=root/'sys/class/leds';leds.mkdir(parents=True,exist_ok=True)
            if not (leds/'asus::kbd_backlight').is_symlink():(leds/'asus::kbd_backlight').symlink_to('../../devices/platform/asus-nb-wmi/leds/asus::kbd_backlight')
        return device

    def test_writable_paths_do_not_depend_on_the_hwmon_index(self):
        """Fixture-based: runs on any host, no Zenbook needed."""
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);lines=set()
            for index in (1,7):
                device=self.fake_sysfs(root,index)
                line,container=installer.service_read_write_paths(root)
                lines.add(line);self.assertEqual(container,'/sys/devices/platform/zenbook_healthytable/hwmon')
                self.assertNotIn('hwmon%d'%index,line);self.assertNotIn(temp,line)
                (device/'oem_request').unlink()
                with self.assertRaises(RuntimeError):installer.service_read_write_paths(root)
                (device/'oem_request').write_text('')
            self.assertEqual(len(lines),1)
            self.assertEqual(lines.pop().split('=',1)[1].split(),[
                '-/sys/devices/platform/zenbook_healthytable/hwmon','/sys/firmware/acpi/platform_profile',
                '/sys/devices/LNXSYSTM:00/PNP0C0A:00/power_supply/BAT0/charge_control_end_threshold',
                '-/sys/devices/platform/asus-nb-wmi/leds/asus::kbd_backlight/brightness','-/sys/kernel/debug/usb/ucsi/USBC000:00/command'])
            (root/'sys/firmware/acpi/platform_profile').unlink()
            with self.assertRaises(RuntimeError):installer.service_read_write_paths(root)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.fake_sysfs(root,2,keyboard=False)
            self.assertNotIn('kbd_backlight',installer.service_read_write_paths(root)[0])
            stray=root/'sys/devices/elsewhere/hwmon/hwmon9';stray.mkdir(parents=True);(stray/'name').write_text('zenbook_ec\n')
            for old in (root/'sys/class/hwmon').iterdir():old.unlink()
            (root/'sys/class/hwmon/hwmon9').symlink_to('../../devices/elsewhere/hwmon/hwmon9')
            with self.assertRaises(RuntimeError):installer.service_read_write_paths(root)
        self.assertEqual(installer.HWMON_CONTAINER,Path('/sys/devices/platform/zenbook_healthytable/hwmon'))

    def test_writable_paths_on_a_real_zenbook(self):
        """Optional real-host check; skipped without the qualified hardware."""
        if not Path('/sys/devices/platform/zenbook_healthytable/hwmon').is_dir() or not Path('/sys/firmware/acpi/platform_profile').is_file():
            self.skipTest('Zenbook driver/platform_profile absent on this host.')
        line,container=installer.service_read_write_paths()
        self.assertTrue(line.startswith('ReadWritePaths=-/sys/devices/platform/zenbook_healthytable/hwmon '))
        self.assertNotRegex(line,r'hwmon[0-9]')

    def test_tablet_switch_device_uses_stable_by_path_link(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);inputs=base/'class/input';dev=base/'dev/input';by_path=dev/'by-path'
            by_path.mkdir(parents=True)
            for event,caps in (('event0','1'),('event17','2'),('event18','10'),('event30','2')):
                (inputs/event/'device/capabilities').mkdir(parents=True);(inputs/event/'device/capabilities/sw').write_text(caps+'\n')
                (dev/event).write_text('')
            (by_path/'platform-INTC1078:00-event').symlink_to('../event17')
            (by_path/'platform-PNP0C0D:00-event').symlink_to('../event0')
            self.assertEqual(installer.tablet_switch_devices(inputs,by_path),[str(by_path/'platform-INTC1078:00-event')])
            (by_path/'odd name-event').symlink_to('../event30')
            self.assertEqual(installer.tablet_switch_devices(inputs,by_path),[str(by_path/'platform-INTC1078:00-event')])  # unsafe link name ignored
            (by_path/'platform-INTC1078:00-event').unlink()
            self.assertEqual(installer.tablet_switch_devices(inputs,by_path),[])  # event30 has no by-path link: skipped

    def test_sysfs_path_validation(self):
        self.assertEqual(installer.safe_sysfs('/sys/devices/platform/asus-nb-wmi/leds/asus::kbd_backlight/brightness'),
                         '/sys/devices/platform/asus-nb-wmi/leds/asus::kbd_backlight/brightness')
        for bad in ('/etc/passwd','/sys/../etc','/sys/a b','/sys/a\nb'):
            with self.assertRaises(RuntimeError):installer.safe_sysfs(bad)

    def test_runtime_contains_service(self):
        if not (installer.ROOT/'build/libasus-healthytable.so').exists():self.skipTest('Run make check.')
        with tempfile.TemporaryDirectory() as temp,mock.patch.object(installer,'run'):
            target=installer.install_runtime(Path(temp))
            for name in installer.SERVICE_RUNTIME:self.assertEqual((target/name).stat().st_mode&0o777,0o644)
            self.assertEqual((target/'service').stat().st_mode&0o777,0o755)


class DaemonModuleTests(unittest.TestCase):
    def test_test_options_refused_for_root_and_runtime_trust(self):
        spec=importlib.util.spec_from_file_location('zenbook_hardwared_test',ROOT/'service/zenbook_hardwared.py')
        daemon=importlib.util.module_from_spec(spec);spec.loader.exec_module(daemon)
        with mock.patch('os.geteuid',return_value=0),mock.patch('sys.stderr',new_callable=io.StringIO),self.assertRaises(SystemExit):daemon.main(['--bus','session'])
        with tempfile.TemporaryDirectory() as temp,self.assertRaises(PermissionError):
            (Path(temp)/'service').mkdir();daemon.check_trusted(Path(temp))
        self.assertIn('<method name="Call">',daemon.XML);self.assertIn('<method name="ApplyMutation">',daemon.XML)

    def daemon_module(self):
        spec=importlib.util.spec_from_file_location('zenbook_hardwared_test2',ROOT/'service/zenbook_hardwared.py')
        daemon=importlib.util.module_from_spec(spec);spec.loader.exec_module(daemon);return daemon

    def test_check_trusted_walks_pycache(self):
        daemon=self.daemon_module()
        with tempfile.TemporaryDirectory() as temp:
            runtime=Path(temp)/'rt';(runtime/'service/__pycache__').mkdir(parents=True)
            (runtime/'service/__pycache__/hwd_core.cpython-314.pyc').write_bytes(b'x')
            seen=[]
            def fake_lstat(path):
                seen.append(str(path));return mock.Mock(st_uid=0,st_mode=0o40755)
            with mock.patch.object(Path,'lstat',fake_lstat):daemon.check_trusted(runtime)
            self.assertIn(str(runtime/'service/__pycache__/hwd_core.cpython-314.pyc'),seen)
            def bad(path):
                return mock.Mock(st_uid=1000 if path.name.endswith('.pyc') else 0,st_mode=0o100644)
            with mock.patch.object(Path,'lstat',bad),self.assertRaises(PermissionError):daemon.check_trusted(runtime)
        source=(ROOT/'service/zenbook_hardwared.py').read_text()
        self.assertIn("sys.pycache_prefix='/nonexistent/zenbook-hardwared-no-bytecode'",source)
        self.assertLess(source.index('sys.pycache_prefix'),source.index('import hwd_core'))

    def test_every_job_is_subject_to_the_hard_timeout(self):
        daemon=self.daemon_module()
        d=daemon.Daemon.__new__(daemon.Daemon)
        now=[1000.0];d.clock=lambda:now[0];d.inflight=0;d.pending=2;d.last_activity=now[0];d.idle_seconds=60
        d.leases=mock.Mock(needs_ticks=lambda:False);d.audit=mock.Mock();d.loop=mock.Mock()
        d.running={'old':now[0]-121,'new':now[0]-1}
        with mock.patch.object(daemon.os,'_exit',side_effect=SystemExit(70)),self.assertRaises(SystemExit):d.check_idle()
        d.leases.stop.assert_called_once()
        d.running={'a':now[0]-10,'b':now[0]-5};self.assertTrue(d.check_idle())

    def test_apply_timeout_reports_outcome_unknown_and_audits_late_result(self):
        import concurrent.futures
        daemon=self.daemon_module()
        d=daemon.Daemon.__new__(daemon.Daemon)
        timers=[];idles=[];futures=[]
        d.GLib=mock.Mock(timeout_add_seconds=lambda s,f:timers.append((s,f)),idle_add=lambda f:idles.append(f))
        d.clock=lambda:0.0;d.pending=0;d.running={};d.last_activity=0.0
        class Worker:
            def submit(self,function):
                future=concurrent.futures.Future();future.function=function;futures.append(future);return future
        d.worker=Worker()
        stream=io.StringIO();d.audit=core.AuditLog(stream)
        d.tokens=mock.Mock(consume=lambda token,sender,uid:{'name':'X','args':{'a':1},'action':'org.zenbook.hardware.ec-oem','digest':'d'*64})
        d.limited=lambda uid,action:False
        d.authorize=lambda invocation,sender,action,done:done(None)
        replies=[];d.reply_json=lambda invocation,result,error:replies.append((result,error))
        d.do_apply(object(),':1.5',1000,('t'*32,))
        self.assertEqual([s for s,_ in timers],[daemon.CALL_TIMEOUT])
        timers[0][1]()  # timeout fires while the worker is still running
        self.assertEqual(len(replies),1);self.assertIsNone(replies[0][0])
        self.assertEqual(replies[0][1].errno,errno.EINPROGRESS)
        self.assertEqual(json.loads(core.failure(replies[0][1]))['error']['errno'],errno.EINPROGRESS)
        records=[json.loads(line[6:]) for line in stream.getvalue().splitlines()]
        self.assertEqual(records[-1]['result'],'outcome_unknown');self.assertEqual(records[-1]['event'],'apply')
        futures[0].set_result({'applied':True});idles[0]()  # worker commits later
        records=[json.loads(line[6:]) for line in stream.getvalue().splitlines()]
        self.assertEqual(records[-1]['event'],'apply_late_outcome');self.assertEqual(records[-1]['result'],'ok')
        self.assertEqual(len(replies),1);self.assertEqual(d.pending,0)
        # A late failure is recorded as such; a normal timeout elsewhere stays ETIMEDOUT.
        timers.clear();idles.clear();futures.clear();d.do_apply(object(),':1.5',1000,('t'*32,));timers[0][1]()
        futures[0].set_exception(core.ServiceError(errno.EIO,'x'));idles[0]()
        records=[json.loads(line[6:]) for line in stream.getvalue().splitlines()]
        self.assertEqual((records[-1]['event'],records[-1]['result'],records[-1]['errno']),('apply_late_outcome','error',errno.EIO))
        timers.clear();out=[];d.run_in_worker(lambda:None,lambda r,e:out.append(e));timers[0][1]()
        self.assertEqual(out[0].errno,errno.ETIMEDOUT)

    def test_signal_shim_prefers_glibunix_and_falls_back(self):
        daemon=self.daemon_module()
        new=lambda *a:'glibunix';old=lambda *a:'glib'  # noqa: E731
        glib=mock.Mock(unix_signal_add=old)
        gi=mock.Mock()
        with mock.patch.object(daemon.importlib,'import_module',return_value=mock.Mock(signal_add=new)):
            self.assertIs(daemon.signal_adder(gi,glib),new)
        older=type('GLibUnix',(),{})()  # older PyGObject: namespace without signal_add
        with mock.patch.object(daemon.importlib,'import_module',return_value=older):
            self.assertIs(daemon.signal_adder(gi,glib),old)
        with mock.patch.object(daemon.importlib,'import_module',side_effect=ImportError):
            self.assertIs(daemon.signal_adder(gi,glib),old)
        gi.require_version.side_effect=ValueError('Namespace GLibUnix not available')
        self.assertIs(daemon.signal_adder(gi,glib),old)
        gi.require_version.assert_called_with('GLibUnix','2.0')
        full=lambda *a:'full'  # noqa: E731
        self.assertIs(daemon.signal_adder(gi,mock.Mock(spec=['unix_signal_add_full'],unix_signal_add_full=full)),full)
        with self.assertRaises(RuntimeError):daemon.signal_adder(gi,mock.Mock(spec=[]))

    def test_self_test_runs_a_glib_callback(self):
        try:
            import gi
            gi.require_version('GLib','2.0')
            from gi.repository import GLib
        except (ImportError,ValueError):self.skipTest('python3-gi unavailable')
        self.assertTrue(self.daemon_module().self_test(GLib))


if __name__=='__main__':unittest.main()
