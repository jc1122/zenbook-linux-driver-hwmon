# SPDX-License-Identifier: GPL-2.0-only
"""Runs zenbook_hardwared on a private bus (dbus-run-session) with a mock polkit
and fake providers: no real polkit, no root, no hardware."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT=Path(__file__).resolve().parent

FAKE_BRIDGE='''
import errno,hashlib,json,os
MUTATIONS={'WOA_EC_write','Adapter_Set_Notify_Control','GPNV_Set_ActivatedTime','StopWinIoDriver'}
def call(request):
    name=request['name']
    with open(os.environ['FAKE_FAN_DIR']+'/calls','a') as log:log.write(name+'\\n')
    if name in MUTATIONS:
        state=open(os.environ['FAKE_FAN_DIR']+'/state').read()
        digest=hashlib.sha256(json.dumps([name,request['args'],state],sort_keys=True).encode()).hexdigest()
        if not request['apply']:return {'function':name,'applied':False,'expected_sha256':digest}
        if request['expected_sha256']!=digest:raise RuntimeError('digest mismatch')
        return {'function':name,'applied':True}
    if name=='CPU_ReadCpuFrequency':raise OSError(errno.ENODEV,'fake sensor absent')
    if name=='WMIGetGPUUsg':return {'engines':[{'available':False,'errno':1,'error':'Cannot open PMU'},{'available':False,'errno':13,'error':'denied'}]}
    if name=='System_Read_TabletMode':raise PermissionError(errno.EPERM,'Operation not permitted')
    if name=='GetIoDllVersion':return 'fake-0'
    return {'name':name,'args':request['args'],'apply':request['apply'],'expected_sha256':request['expected_sha256']}
'''
FAKE_COMPAT='''
class Front:
    def control(self,request):return {'before':'balanced','after':str(getattr(request,'value',request.command))}
def validate(name,args,apply=False,expected_sha256=None):
    if not isinstance(args,dict):raise ValueError('API arguments must be a JSON object.')
def frontend():return Front()
'''
FAKE_METRICS='''
def report():return {'fake_metrics':True}
'''
FAKE_NATIVE='''
import os
from pathlib import Path
def device():return Path(os.environ['FAKE_FAN_DIR'])
'''
FAKE_VITALS_MODULE='''
import errno,os
def _count(name):
    with open(os.environ['FAKE_FAN_DIR']+'/calls','a') as log:log.write(name+'\\n')
def report():
    _count(__name__+'.report')
    if __name__=='pd_identity':raise OSError(errno.EIO,'fake identity failure')
    return {'available':True,'source':__name__}
def lifetime_report():_count(__name__+'.lifetime_report');return {'available':True,'source':'lifetime'}
def platform_power():_count(__name__+'.platform_power');return {'available':True,'watts':1.5}
'''
POLKIT_MOCK='''
import json,os,sys
import gi
gi.require_version('Gio','2.0')
from gi.repository import Gio,GLib
XML="""<node><interface name="org.freedesktop.PolicyKit1.Authority"><method name="CheckAuthorization">
<arg type="(sa{sv})" direction="in"/><arg type="s" direction="in"/><arg type="a{ss}" direction="in"/><arg type="u" direction="in"/>
<arg type="s" direction="in"/><arg type="(bba{ss})" direction="out"/></method></interface></node>"""
denied=set(os.environ['MOCK_DENY'].split(','));log=open(os.environ['MOCK_LOG'],'a')
def method(conn,sender,path,iface,name,params,inv):
    subject,action,details,flags,cancel=params.unpack()
    log.write(json.dumps({'kind':subject[0],'subject':subject[1].get('name'),'action':action,'flags':flags})+'\\n');log.flush()
    inv.return_value(GLib.Variant('((bba{ss}))',((action not in denied,False,{}),)))
def acquired(conn,name):
    conn.register_object('/org/freedesktop/PolicyKit1/Authority',Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0],method,None,None)
Gio.bus_own_name(Gio.BusType.SESSION,'org.freedesktop.PolicyKit1',Gio.BusNameOwnerFlags.NONE,acquired,None,None)
GLib.MainLoop().run()
'''
DRIVER='''
import json,os,signal,subprocess,sys,time
import gi
gi.require_version('Gio','2.0')
from gi.repository import Gio,GLib
base=sys.argv[1];fan=os.environ['FAKE_FAN_DIR'];out={}
mock=subprocess.Popen([sys.executable,'-I',base+'/polkit_mock.py'])
daemon_log=open(base+'/daemon.log','w')
daemon=subprocess.Popen([sys.executable,'-I','-B',base+'/runtime/service/zenbook_hardwared.py','--bus','session',
    '--runtime',base+'/runtime','--marker',base+'/marker.json','--idle-timeout','0','--slow-limit','0.5,1'],stdout=daemon_log,stderr=subprocess.STDOUT)
def connect():
    return Gio.DBusConnection.new_for_address_sync(Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION,None),
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT|Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,None,None)
bus=connect()
def has(name):
    return bus.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','NameHasOwner',
        GLib.Variant('(s)',(name,)),None,Gio.DBusCallFlags.NONE,1000,None).unpack()[0]
deadline=time.time()+20
while time.time()<deadline and not (has('org.zenbook.Hardware1') and has('org.freedesktop.PolicyKit1')):time.sleep(.1)
def call(method,signature,args,conn=None,reply='(s)'):
    try:
        value=(conn or bus).call_sync('org.zenbook.Hardware1','/org/zenbook/Hardware1','org.zenbook.Hardware1',method,
            GLib.Variant(signature,args) if signature else None,GLib.VariantType(reply),Gio.DBusCallFlags.NONE,10000,None)
        return {'value':value.unpack()[0]}
    except GLib.Error as error:
        return {'dbus_error':Gio.DBusError.get_remote_error(error),'message':Gio.DBusError.strip_remote_error(error) or error.message}
def api(name,args='{}',apply=False,digest=''):
    reply=call('Call','(ssbs)',(name,args,apply,digest))
    return json.loads(reply['value']) if 'value' in reply else reply
def mode():return open(fan+'/pwm1_enable').read().strip()
def wait_mode(value,seconds=6):
    end=time.time()+seconds
    while time.time()<end and mode()!=value:time.sleep(.1)
    return mode()
out['read']=api('GetIoDllVersion')
out['provider_error']=api('CPU_ReadCpuFrequency')
out['unknown']=api('NoSuchExport')
out['bad_json']=api('GetIoDllVersion','[1]')
out['bad_digest']=api('GetIoDllVersion','{}',False,'XYZ')
out['identifier_denied']=api('WMIGetSN')
out['settings']=api('WMISetQuietFan','{"profile":"quiet"}')
out['client_only']=api('SaveEcLog','{"path":"/nonexistent/ec.log"}')
out['firmware_apply']=api('GPNV_Set_ActivatedTime','{}',True,'0'*64)
out['firmware_plan_denied']=json.loads(call('PlanMutation','(ss)',('GPNV_Set_ActivatedTime','{}'))['value'])
def calls(name):return open(fan+'/calls').read().split().count(name)
before=calls('WMIGetBiosVersion');api('WMIGetBiosVersion');api('WMIGetBiosVersion')
out['cached_provider_calls']=calls('WMIGetBiosVersion')-before
api('HealthyTable_FanRPM');api('HealthyTable_FanRPM')
out['fan_read_provider_calls']=calls('HealthyTable_FanRPM')
out['gpu']=api('WMIGetGPUUsg');out['tablet']=api('System_Read_TabletMode')
slow=['BatteryHealthyTable_PFStatus','BatteryHealthyTable_SafetyStatus','BatteryHealthy_Read_PFStatus','BatteryHealthyTable_BatteryInformation']
started=time.time()
out['slow_reads']=[api(name) for name in slow]  # 3 groups, budget 1 token/2 s: queued, not refused
out['slow_seconds']=time.time()-started
out['slow_repeat']=api('BatteryHealthyTable_PFStatus')
out['slow_provider_calls']={name:calls(name) for name in slow}
out['reprobe']=json.loads(call('Control','(ss)',('reprobe','{}'))['value'])  # controls do not queue
out['profile_control']=json.loads(call('Control','(ss)',('profile','{"value":"balanced"}'))['value'])
call('Metrics',None,None);call('Metrics',None,None)
time.sleep(4)
out['direct_apply']=api('WOA_EC_write','{"index":1}',True,'0'*64)
plan=json.loads(call('PlanMutation','(ss)',('WOA_EC_write','{"index":1}'))['value'])
out['plan']=plan;token=plan['result']['service_token']
out['foreign_apply']=json.loads(call('ApplyMutation','(s)',(token,),conn=connect())['value'])
out['apply']=json.loads(call('ApplyMutation','(s)',(token,))['value'])
out['reuse']=json.loads(call('ApplyMutation','(s)',(token,))['value'])
plan=json.loads(call('PlanMutation','(ss)',('WOA_EC_write','{"index":2}'))['value'])
open(fan+'/state','w').write('changed')
out['stale_apply']=json.loads(call('ApplyMutation','(s)',(plan['result']['service_token'],))['value'])
out['driver_plan']=json.loads(call('PlanMutation','(ss)',('StopWinIoDriver','{}'))['value'])
time.sleep(4)
out['fan_without_lease']=api('HealthyTable_SetFanPwmDuty','{"duty":10}')
out['metrics']=json.loads(call('Metrics',None,None)['value'])
replies=[];loop=GLib.MainLoop()
def got(conn,result):
    replies.append(json.loads(conn.call_finish(result).unpack()[0]))
    if len(replies)==3:loop.quit()
for _ in range(3):
    bus.call('org.zenbook.Hardware1','/org/zenbook/Hardware1','org.zenbook.Hardware1','VitalsMetrics',None,GLib.VariantType('(s)'),
             Gio.DBusCallFlags.NONE,10000,None,got)
GLib.timeout_add_seconds(10,loop.quit);loop.run()
replies.append(json.loads(call('VitalsMetrics',None,None)['value']))
out['vitals']=replies;out['vitals_provider_calls']=open(fan+'/calls').read().split().count('battery_extra.report')
out['version']=bus.call_sync('org.zenbook.Hardware1','/org/zenbook/Hardware1','org.freedesktop.DBus.Properties','Get',
    GLib.Variant('(ss)',('org.zenbook.Hardware1','Version')),None,Gio.DBusCallFlags.NONE,5000,None).unpack()[0]
time.sleep(4)  # refill the per-uid mutating rate-limit bucket
lease=call('AcquireFanLease','(us)',(30,'50'),reply='(s)')
out['lease']=lease;out['lease_mode']=mode();out['lease_duty']=open(fan+'/pwm1').read().strip()
out['marker_during_lease']=os.path.exists(base+'/marker.json')
out['second_lease']=call('AcquireFanLease','(us)',(30,'40'))
out['fan_with_lease']=api('HealthyTable_SetFanPwmDuty','{"duty":10}')
other=connect()
out['foreign_release']=call('ReleaseFanLease','(s)',(lease['value'],),conn=other)
out['release']=json.loads(call('ReleaseFanLease','(s)',(lease['value'],))['value'])
out['after_release']=mode();out['marker_after_release']=os.path.exists(base+'/marker.json')
out['bad_seconds']=call('AcquireFanLease','(us)',(301,'50'))
time.sleep(3)
holder=connect()
out['disconnect_lease']=call('AcquireFanLease','(us)',(60,'full'),conn=holder)
out['disconnect_mode_before']=mode()
holder.close_sync(None)
out['after_disconnect']=wait_mode('2')
out['expiry_lease']=call('AcquireFanLease','(us)',(1,'30'))
out['after_expiry']=wait_mode('2')
out['low_rpm_lease']=call('AcquireFanLease','(us)',(60,'30'))
open(fan+'/fan1_input','w').write('100\\n')
out['after_low_rpm']=wait_mode('2')
open(fan+'/fan1_input','w').write('3000\\n')
out['stop_lease']=call('AcquireFanLease','(us)',(60,'30'))
daemon.send_signal(signal.SIGTERM)
try:daemon.wait(10)
except subprocess.TimeoutExpired:daemon.kill()
out['after_stop']=mode();out['marker_after_stop']=os.path.exists(base+'/marker.json');out['exit']=daemon.returncode
mock.terminate();mock.wait(5)
print(json.dumps(out))
'''


@unittest.skipUnless(shutil.which('dbus-run-session') and shutil.which('dbus-daemon'),'dbus-run-session unavailable')
class PrivateBusIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:import gi  # noqa: F401
        except ImportError:raise unittest.SkipTest('python3-gi unavailable') from None
        cls.temp=tempfile.TemporaryDirectory();base=Path(cls.temp.name)
        runtime=base/'runtime';(runtime/'service').mkdir(parents=True)
        for name in ('zenbook_hardwared.py','hwd_core.py','authorization.json'):shutil.copyfile(ROOT/'service'/name,runtime/'service'/name)
        shutil.copyfile(ROOT/'capabilities.json',runtime/'capabilities.json')
        for name in ('battery_diagnostics','battery_extra','battery_sbs','pd_identity','charger_adc','charger_metrics','pd_contract','package_power'):
            (runtime/(name+'.py')).write_text(textwrap.dedent(FAKE_VITALS_MODULE))
        for name,text in (('api_bridge.py',FAKE_BRIDGE),('compat.py',FAKE_COMPAT),('metrics.py',FAKE_METRICS),('native_oem.py',FAKE_NATIVE)):
            (runtime/name).write_text(textwrap.dedent(text))
        (base/'polkit_mock.py').write_text(POLKIT_MOCK);(base/'driver.py').write_text(DRIVER)
        fan=base/'fan';fan.mkdir()
        for name,value in (('pwm1_enable','2'),('pwm1','0'),('fan1_input','3000')):(fan/name).write_text(value+'\n')
        (fan/'state').write_text('initial');(fan/'calls').write_text('')
        env={k:v for k,v in os.environ.items() if not k.startswith(('DBUS_','PYTHON'))}
        env.update(FAKE_FAN_DIR=str(fan),MOCK_LOG=str(base/'polkit.log'),
                   MOCK_DENY='org.zenbook.hardware.read-identifiers,org.zenbook.hardware.firmware')
        result=subprocess.run([shutil.which('dbus-run-session'),'--',sys.executable,'-I',str(base/'driver.py'),str(base)],
                              capture_output=True,text=True,timeout=120,env=env,cwd=str(base))
        cls.log=(base/'daemon.log').read_text() if (base/'daemon.log').exists() else ''
        if result.returncode or not result.stdout.strip():
            raise AssertionError('driver failed: '+result.stderr[-4000:]+'\n'+cls.log[-4000:])
        cls.out=json.loads(result.stdout.strip().splitlines()[-1])
        cls.polkit=[json.loads(line) for line in (base/'polkit.log').read_text().splitlines()]
        cls.audit=[json.loads(line.split(' ',1)[1]) for line in cls.log.splitlines() if line.startswith('AUDIT ')]

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_call_round_trip_matches_bridge_envelope(self):
        self.assertEqual(self.out['read'],{'ok':True,'result':'fake-0'})
        self.assertEqual(self.out['provider_error'],{'ok':False,'error':{'errno':19,'message':'[Errno 19] fake sensor absent'}})
        self.assertEqual(self.out['metrics'],{'ok':True,'result':{'fake_metrics':True}})
        self.assertEqual(self.out['version'],json.loads((ROOT/'capabilities.json').read_text())['module_version'])

    def test_vitals_metrics_subset_shared_cache_and_coalescing(self):
        replies=self.out['vitals'];self.assertEqual(len(replies),4)
        self.assertTrue(all(r==replies[0] for r in replies))
        result=replies[0]['result']
        self.assertEqual(set(result),{'schema','battery_gauge','battery_lifetime','battery_gauge_extra','battery_sbs','usb_pd_identity',
                                      'charger_input','charger','platform_power','cpu_package_power'})
        self.assertEqual(result['usb_pd_identity'],{'available':False,'errno':5,'error':'[Errno 5] fake identity failure'})
        self.assertEqual(result['platform_power'],{'available':True,'watts':1.5})
        self.assertEqual(self.out['vitals_provider_calls'],1)  # 3 concurrent + 1 cached call, one provider run

    def test_request_validation(self):
        self.assertEqual(self.out['unknown']['error']['errno'],22)
        self.assertEqual(self.out['bad_json']['error']['errno'],22)
        self.assertEqual(self.out['bad_digest']['error']['errno'],22)

    def test_polkit_denial_and_refusals(self):
        self.assertEqual(self.out['identifier_denied']['error']['errno'],13)
        self.assertEqual(self.out['firmware_plan_denied']['error']['errno'],13)
        self.assertEqual(self.out['client_only']['error']['errno'],95)
        self.assertEqual(self.out['firmware_apply']['error']['errno'],1)  # apply needs a service token
        self.assertEqual(self.out['fan_without_lease']['error']['errno'],1)

    def test_read_cache_and_slow_class(self):
        self.assertEqual(self.out['cached_provider_calls'],1)  # second read within 2 s is a cache hit
        self.assertEqual(self.out['fan_read_provider_calls'],2)  # fan reads are never cached
        self.assertTrue(all(r['ok'] for r in self.out['slow_reads']),self.out['slow_reads'])
        self.assertTrue(self.out['slow_repeat']['ok'])
        self.assertEqual(self.out['slow_provider_calls'],{n:1 for n in self.out['slow_provider_calls']})
        # Gauge-status pair is one refresh; the PF-cache and information groups
        # each waited about one 2 s refill instead of failing with EAGAIN.
        self.assertGreater(self.out['slow_seconds'],2.5);self.assertLess(self.out['slow_seconds'],9)
        self.assertEqual(self.out['reprobe']['error']['errno'],11)
        self.assertTrue(self.out['profile_control']['ok'])

    def test_sandbox_denials_are_marked(self):
        self.assertTrue(self.out['gpu']['ok'])  # envelope ok, every inner row denied
        rows=self.out['gpu']['result']['engines']
        self.assertTrue(rows and all(not r['available'] and r['errno'] in (1,13) for r in rows))
        self.assertEqual(self.out['tablet']['error']['errno'],1)
        marks={row['name']:row for row in self.audit if row['event']=='sandbox_denied'}
        self.assertEqual(marks['WMIGetGPUUsg']['count'],2);self.assertEqual(marks['System_Read_TabletMode']['errno'],1)
        self.assertNotIn('GetIoDllVersion',marks);self.assertNotIn('BatteryHealthyTable_PFStatus',marks)
        self.assertNotIn('Cannot open PMU',self.log)

    def test_mutation_tokens(self):
        self.assertEqual(self.out['direct_apply']['error']['errno'],1)
        result=self.out['plan']['result']
        self.assertRegex(result['service_token'],'^[0-9a-f]{32}$');self.assertTrue(result['service_apply_supported'])
        self.assertEqual(self.out['foreign_apply']['error']['errno'],13)
        self.assertEqual(self.out['apply'],{'ok':True,'result':{'function':'WOA_EC_write','applied':True}})
        self.assertEqual(self.out['reuse']['error']['errno'],2)
        self.assertEqual(self.out['stale_apply']['error']['errno'],11)
        self.assertNotIn('service_token',self.out['driver_plan']['result'])
        self.assertFalse(self.out['driver_plan']['result']['service_apply_supported'])

    def test_polkit_subject_is_the_callers_bus_name(self):
        self.assertTrue(self.polkit)
        for row in self.polkit:
            self.assertEqual(row['kind'],'system-bus-name');self.assertTrue(row['subject'].startswith(':'))
            self.assertEqual(row['flags'],0)
        self.assertIn('org.zenbook.hardware.read-identifiers',{r['action'] for r in self.polkit})

    def test_hardware_only_settings_leave_persistence_to_client(self):
        result=self.out['settings']['result']
        self.assertFalse(result['remembered']);self.assertEqual(result['after'],'quiet')
        self.assertEqual(result['client_persistence'],{'field':'platform_profile','value':'quiet'})

    def test_lease_lifecycle_restores_automatic(self):
        self.assertRegex(self.out['lease']['value'],'^[0-9a-f]{32}$')
        self.assertEqual(self.out['lease_mode'],'1');self.assertEqual(self.out['lease_duty'],'128')
        self.assertTrue(self.out['marker_during_lease'])
        self.assertEqual(self.out['second_lease']['dbus_error'],'org.zenbook.Hardware1.Error.EBUSY')
        self.assertTrue(self.out['fan_with_lease']['ok'])
        self.assertEqual(self.out['foreign_release']['dbus_error'],'org.zenbook.Hardware1.Error.EPERM')
        self.assertEqual(self.out['release']['result']['reason'],'released');self.assertTrue(self.out['release']['result']['automatic_restored'])
        self.assertEqual(self.out['after_release'],'2');self.assertFalse(self.out['marker_after_release'])
        self.assertEqual(self.out['bad_seconds']['dbus_error'],'org.zenbook.Hardware1.Error.EINVAL')

    def test_disconnect_expiry_low_rpm_and_stop_restore(self):
        self.assertEqual(self.out['disconnect_mode_before'],'0')
        for key in ('disconnect_lease','expiry_lease','low_rpm_lease','stop_lease'):self.assertIn('value',self.out[key],key)
        for key in ('after_disconnect','after_expiry','after_low_rpm','after_stop'):self.assertEqual(self.out[key],'2',key)
        self.assertFalse(self.out['marker_after_stop']);self.assertEqual(self.out['exit'],0)
        reasons=[row.get('reason') for row in self.audit if row['event']=='fan_lease_ended']
        self.assertEqual(reasons,['released','holder_disconnected','expired','low_rpm_abort','service_stopping'])

    def test_audit_lines_for_mutations_carry_no_values(self):
        calls=[row for row in self.audit if row['event']=='call']
        names={row['name'] for row in calls}
        self.assertIn('WMISetQuietFan',names);self.assertIn('WOA_EC_write',names);self.assertNotIn('GetIoDllVersion',names)
        events={(row['event'],row.get('name'),row.get('result')) for row in self.audit}
        self.assertIn(('plan','GPNV_Set_ActivatedTime','denied'),events);self.assertIn(('apply','WOA_EC_write','ok'),events)
        self.assertIn(('control',None,'ok'),events)
        self.assertFalse(any(len(row.get('token',''))>8 for row in self.audit))
        settings=[row for row in calls if row['name']=='WMISetQuietFan'][0]
        self.assertEqual(settings['arg_keys'],['profile']);self.assertEqual(settings['result'],'ok')
        self.assertIsInstance(settings['uid'],int)
        refused=[row for row in calls if row['name']=='WOA_EC_write'][0]
        self.assertEqual((refused['result'],refused['errno']),('refused',1))
        self.assertNotIn('quiet',self.log);self.assertNotIn('/nonexistent/ec.log',self.log)


if __name__=='__main__':unittest.main()
