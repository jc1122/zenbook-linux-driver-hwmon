# SPDX-License-Identifier: GPL-2.0-only
"""End-to-end client routing on a private bus: the real zenbook_hardwared (fake
providers, mock polkit) reached by the real CLI, api_bridge.py and C library
through DBUS_SYSTEM_BUS_ADDRESS. No real polkit, root, sudo or hardware writes."""
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

# Own fakes (independent of test_service_integration.py, which the service
# review may change): provider runtime and a polkit mock with an allow list.
FAKE_BRIDGE='''
def call(request):
    return {'name':request['name'],'args':request['args'],'apply':request['apply'],'expected_sha256':request['expected_sha256']}
'''
FAKE_COMPAT='''
class Front:
    def control(self,request):return {'before':'balanced','after':str(request.value)}
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
POLKIT_MOCK='''
import json,os
import gi
gi.require_version('Gio','2.0')
from gi.repository import Gio,GLib
XML="""<node><interface name="org.freedesktop.PolicyKit1.Authority"><method name="CheckAuthorization">
<arg type="(sa{sv})" direction="in"/><arg type="s" direction="in"/><arg type="a{ss}" direction="in"/><arg type="u" direction="in"/>
<arg type="s" direction="in"/><arg type="(bba{ss})" direction="out"/></method></interface></node>"""
allowed=set(os.environ['CLIENT_MOCK_ALLOW'].split(','));log=open(os.environ['CLIENT_MOCK_LOG'],'a')
def method(conn,sender,path,iface,name,params,inv):
    subject,action,details,flags,cancel=params.unpack()
    log.write(json.dumps({'kind':subject[0],'subject':subject[1].get('name'),'action':action,'flags':flags})+'\\n');log.flush()
    inv.return_value(GLib.Variant('((bba{ss}))',((action in allowed,False,{}),)))
def acquired(conn,name):
    conn.register_object('/org/freedesktop/PolicyKit1/Authority',Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0],method,None,None)
Gio.bus_own_name(Gio.BusType.SESSION,'org.freedesktop.PolicyKit1',Gio.BusNameOwnerFlags.NONE,acquired,None,None)
GLib.MainLoop().run()
'''

DRIVER='''
import ctypes,json,os,signal,subprocess,sys,time
import gi
gi.require_version('Gio','2.0')
from gi.repository import Gio,GLib
base,root,library=sys.argv[1],sys.argv[2],sys.argv[3];fan=os.environ['FAKE_FAN_DIR'];out={}
mock=subprocess.Popen([sys.executable,'-I',base+'/polkit_mock.py'])
daemon=subprocess.Popen([sys.executable,'-I','-B',base+'/runtime/service/zenbook_hardwared.py','--bus','session',
    '--runtime',base+'/runtime','--marker',base+'/marker.json','--idle-timeout','0'],stdout=open(base+'/daemon.log','w'),stderr=subprocess.STDOUT)
bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
def has(name):
    return bus.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','NameHasOwner',
        GLib.Variant('(s)',(name,)),None,Gio.DBusCallFlags.NONE,1000,None).unpack()[0]
deadline=time.time()+20
while time.time()<deadline and not (has('org.zenbook.Hardware1') and has('org.freedesktop.PolicyKit1')):time.sleep(.1)
env={k:v for k,v in os.environ.items() if k not in ('DISPLAY','WAYLAND_DISPLAY')}
env.update(DBUS_SYSTEM_BUS_ADDRESS=os.environ['DBUS_SESSION_BUS_ADDRESS'],XDG_CONFIG_HOME=base+'/config')
def polkit_rows():
    return [json.loads(line) for line in open(base+'/polkit.log')] if os.path.exists(base+'/polkit.log') else []
def bridge(request):
    result=subprocess.run(['/usr/bin/python3','-I','-B',root+'/api_bridge.py'],input=json.dumps(request),capture_output=True,text=True,env=env,timeout=90)
    return {'status':result.returncode,'envelope':json.loads(result.stdout)}
def cli(argv,extra=None,timeout=90):
    result=subprocess.run([sys.executable,root+'/zenbook-hardware.py',*argv],capture_output=True,text=True,env={**env,**(extra or {})},
                          timeout=timeout,stdin=subprocess.DEVNULL)
    return {'status':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
mark=len(polkit_rows())
out['bridge_read']=bridge({'name':'GetXgmFw'})
out['bridge_denied']=bridge({'name':'WMIGetSN'})
out['bridge_quiet']=bridge({'name':'WMISetQuietFan','args':{'profile':'quiet'}})
out['bridge_flags']=[row['flags'] for row in polkit_rows()[mark:]]
code="""import ctypes,json,sys
lib=ctypes.CDLL(sys.argv[1]);lib.asus_ht_call.argtypes=[ctypes.c_char_p,ctypes.POINTER(ctypes.c_void_p)];lib.asus_ht_call.restype=ctypes.c_int
rows=[]
for request in sys.argv[2:]:
    ptr=ctypes.c_void_p();status=lib.asus_ht_call(request.encode(),ctypes.byref(ptr))
    rows.append({'status':status,'envelope':json.loads(ctypes.string_at(ptr)) if ptr.value else None})
print(json.dumps(rows))"""
mark=len(polkit_rows())
c=subprocess.run([sys.executable,'-I','-c',code,library,json.dumps({'name':'GetXgmFw'}),json.dumps({'name':'WMIGetSN'})],
                 capture_output=True,text=True,env=env,timeout=120)
out['c_library']=json.loads(c.stdout) if c.stdout else c.stderr
out['c_flags']=[row['flags'] for row in polkit_rows()[mark:]]
time.sleep(5)  # refill the per-uid mutating rate-limit bucket
mark=len(polkit_rows())
out['cli_charge_interactive']=cli(['charge-limit','80'],{'DISPLAY':':99'})
out['cli_charge_flags']=[row['flags'] for row in polkit_rows()[mark:]]
mark=len(polkit_rows())
out['cli_api_noninteractive']=cli(['--non-interactive','api','GetXgmFw'],{'DISPLAY':':99'})
out['cli_api_flags']=[row['flags'] for row in polkit_rows()[mark:]]
out['cli_fan']=cli(['--non-interactive','fan','50','--duration','2'])
out['after_cli_fan']=open(fan+'/pwm1_enable').read().strip()
proc=subprocess.Popen([sys.executable,root+'/zenbook-hardware.py','--non-interactive','fan','full','--duration','60'],env=env,
                      stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL)
end=time.time()+20
while time.time()<end and open(fan+'/pwm1_enable').read().strip()!='0':time.sleep(.1)
out['during_killed_lease']=open(fan+'/pwm1_enable').read().strip()
proc.kill();proc.wait(10)
end=time.time()+10
while time.time()<end and open(fan+'/pwm1_enable').read().strip()!='2':time.sleep(.1)
out['after_killed_client']=open(fan+'/pwm1_enable').read().strip()
time.sleep(3)
out['cli_fan_auto']=cli(['--non-interactive','fan','auto'])
daemon.send_signal(signal.SIGTERM)
try:daemon.wait(10)
except subprocess.TimeoutExpired:daemon.kill()
mock.terminate();mock.wait(5)
print(json.dumps(out))
'''


@unittest.skipUnless(shutil.which('dbus-run-session') and shutil.which('dbus-daemon'),'dbus-run-session unavailable')
@unittest.skipIf(os.geteuid()==0,'client routing tests run as an unprivileged user')
class ClientOverPrivateBusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:import gi  # noqa: F401
        except ImportError:raise unittest.SkipTest('python3-gi unavailable') from None
        compiler=shutil.which('cc') or shutil.which('gcc')
        if not compiler or not Path('/usr/bin/python3').exists():raise unittest.SkipTest('A C compiler and /usr/bin/python3 are required.')
        if not Path('/sys/firmware/acpi/platform_profile').exists():raise unittest.SkipTest('platform_profile identity unavailable')
        cls.temp=tempfile.TemporaryDirectory();base=Path(cls.temp.name)
        runtime=base/'runtime';(runtime/'service').mkdir(parents=True)
        for name in ('zenbook_hardwared.py','hwd_core.py','authorization.json'):shutil.copyfile(ROOT/'service'/name,runtime/'service'/name)
        shutil.copyfile(ROOT/'capabilities.json',runtime/'capabilities.json')
        for name,text in (('api_bridge.py',FAKE_BRIDGE),('compat.py',FAKE_COMPAT),('metrics.py',FAKE_METRICS),('native_oem.py',FAKE_NATIVE)):
            (runtime/name).write_text(textwrap.dedent(text))
        (base/'polkit_mock.py').write_text(POLKIT_MOCK);(base/'driver.py').write_text(DRIVER);(base/'config').mkdir(mode=0o700)
        fan=base/'fan';fan.mkdir()
        for name,value in (('pwm1_enable','2'),('pwm1','0'),('fan1_input','3000')):(fan/name).write_text(value+'\n')
        library=base/'client.so'
        subprocess.run([compiler,'-O2','-Wall','-Wextra','-Werror','-std=c11','-fPIC','-shared','-I'+str(ROOT/'include'),
                        '-DASUS_HT_BRIDGE="'+str(ROOT/'api_bridge.py')+'"',str(ROOT/'lib/asus_healthytable.c'),'-o',str(library)],check=True,timeout=60)
        env={k:v for k,v in os.environ.items() if not k.startswith(('DBUS_','PYTHON'))}
        env.update(FAKE_FAN_DIR=str(fan),CLIENT_MOCK_LOG=str(base/'polkit.log'),
                   CLIENT_MOCK_ALLOW='org.zenbook.hardware.read,org.zenbook.hardware.settings,org.zenbook.hardware.fan-lease')
        result=subprocess.run([shutil.which('dbus-run-session'),'--',sys.executable,'-I',str(base/'driver.py'),str(base),str(ROOT),str(library)],
                              capture_output=True,text=True,timeout=300,env=env,cwd=str(base))
        cls.log=(base/'daemon.log').read_text() if (base/'daemon.log').exists() else ''
        if result.returncode or not result.stdout.strip():raise AssertionError('driver failed: '+result.stderr[-4000:]+'\n'+cls.log[-4000:])
        cls.out=json.loads(result.stdout.strip().splitlines()[-1])
        prefs=base/'config/zenbook-hardware/preferences.json'
        cls.preferences=json.loads(prefs.read_text()) if prefs.exists() else None
        cls.preferences_mode=prefs.stat().st_mode&0o777 if prefs.exists() else None

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_bridge_routes_privileged_names_non_interactively(self):
        self.assertEqual(self.out['bridge_read'],{'status':0,'envelope':{'ok':True,'result':{'name':'GetXgmFw','args':{},'apply':False,'expected_sha256':None}}})
        self.assertEqual(self.out['bridge_denied']['status'],1);self.assertEqual(self.out['bridge_denied']['envelope']['error']['errno'],13)
        self.assertTrue(self.out['bridge_flags']);self.assertEqual(set(self.out['bridge_flags']),{0})

    def test_client_persistence_is_saved_by_the_client_as_the_user(self):
        result=self.out['bridge_quiet']['envelope']['result']
        self.assertEqual((result['after'],result['remembered']),('quiet',True));self.assertNotIn('client_persistence',result)
        self.assertEqual(self.preferences['values'],{'platform_profile':'quiet'});self.assertEqual(self.preferences_mode,0o600)

    def test_c_library_reaches_service_without_interaction_and_eacces_on_denial(self):
        read,denied=self.out['c_library']
        self.assertEqual(read['status'],0);self.assertEqual(read['envelope']['result']['name'],'GetXgmFw')
        self.assertEqual(denied['status'],1);self.assertEqual(denied['envelope']['error']['errno'],13)
        self.assertEqual(set(self.out['c_flags']),{0})

    def test_cli_allows_interactive_authorisation_unless_disabled(self):
        charge=self.out['cli_charge_interactive'];self.assertEqual(charge['status'],0,charge['stderr'])
        self.assertEqual(json.loads(charge['stdout']),{'before':'balanced','after':'80'})
        self.assertEqual(set(self.out['cli_charge_flags']),{1})
        api=self.out['cli_api_noninteractive'];self.assertEqual(api['status'],0,api['stderr'])
        self.assertEqual(json.loads(api['stdout'])['value']['name'],'GetXgmFw');self.assertEqual(set(self.out['cli_api_flags']),{0})

    def test_cli_fan_lease_is_bounded_and_restored_on_kill(self):
        fan=self.out['cli_fan'];self.assertEqual(fan['status'],0,fan['stderr'])
        lease=json.loads(fan['stdout'])['lease']
        self.assertRegex(lease['id'],'^[0-9a-f]{32}$');self.assertEqual((lease['seconds'],lease['request']),(2,'50'))
        self.assertEqual(lease['reason'],'released');self.assertTrue(lease['automatic_restored'])
        self.assertEqual(self.out['after_cli_fan'],'2')
        self.assertEqual(self.out['during_killed_lease'],'0');self.assertEqual(self.out['after_killed_client'],'2')
        auto=self.out['cli_fan_auto'];self.assertEqual(auto['status'],0,auto['stderr']);self.assertTrue(json.loads(auto['stdout'])['automatic_restored'])
        reasons=[json.loads(line.split(' ',1)[1]).get('reason') for line in self.log.splitlines() if line.startswith('AUDIT ') and '"fan_lease_ended"' in line]
        self.assertEqual(reasons,['released','holder_disconnected'])


if __name__=='__main__':unittest.main()
