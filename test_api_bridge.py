# SPDX-License-Identifier: GPL-2.0-only
import ctypes
import errno
import json
from pathlib import Path
import unittest
from unittest import mock
from types import SimpleNamespace
import api_bridge
import compat
import linux_services
import native_oem


class ApiTests(unittest.TestCase):
    def test_configuration_error_reports_actual_or_unknown_commit_state(self):
        import io
        import user_preferences
        for committed in (False,True,None):
            source=SimpleNamespace(buffer=io.BytesIO(b'{}'));output=io.StringIO()
            error=user_preferences.PreferenceError(errno.EIO,'Verify current settings.',committed)
            with mock.patch.object(api_bridge.sys,'stdin',source),mock.patch.object(api_bridge.sys,'stdout',output),mock.patch.object(api_bridge,'call',side_effect=error):
                status=api_bridge.main()
            result=json.loads(output.getvalue());self.assertEqual(status,1)
            self.assertIs(result['error']['configuration_committed'],committed)

    def test_generic_sensor_uses_actual_recovered_device_id(self):
        with mock.patch('firmware_queries.call',return_value={'p_sensor':'0x1234','raw':0x1234}) as query:
            out=native_oem.call('GetSENSOR_WMI_Data',{})
        query.assert_called_once_with('GetSENSOR_WMI_Data',{})
        self.assertEqual(out['p_sensor'],'0x1234')

    def test_sensor_does_not_accept_unrelated_queries(self):
        with mock.patch.object(native_oem,'rpc') as rpc:
            with self.assertRaises(ValueError):compat.validate('GetSENSOR_WMI_Data',{'device_id':0x120079})
        rpc.assert_not_called()

    def test_num_key_uses_keyboard_state(self):
        with mock.patch.object(linux_services,'keyboard_state',return_value={'num_lock':False,'keyboard_num':1}) as read:
            self.assertEqual(compat.lifecycle('GetNum_Key',{})['keyboard_num'],1)
        read.assert_called_once()

    def test_bridge_unknown_name_and_unknown_fields_are_rejected(self):
        for request in [{'name':'unknown'},{'name':'wmiadd','unexpected':True}]:
            with self.assertRaises(ValueError):api_bridge.call(request)

    def test_bridge_result_is_not_implicitly_elevated(self):
        # Non-root privileged names go to the service (never sudo); without it: EACCES.
        import auth
        with mock.patch.object(compat.os,'geteuid',return_value=1000),mock.patch.object(auth,'ServiceClient',side_effect=auth.ServiceUnavailable('test')),\
             mock.patch.object(compat,'dispatch',side_effect=AssertionError('no in-process privileged run')),mock.patch.object(auth.subprocess,'run') as run:
            with self.assertRaises(PermissionError) as caught:api_bridge.call({'name':'GetXgmFw'})
        self.assertEqual(caught.exception.errno,errno.EACCES);run.assert_not_called()

    def test_bridge_calls_native_utility(self):
        self.assertEqual(api_bridge.call({'name':'wmiadd','args':{'value':41}}),42)

    def test_acpi_connector_types_and_internal_ports(self):
        for kind in (0,3):self.assertEqual(linux_services.upc_connector(kind,255),'A')
        for kind in (8,9,10):self.assertEqual(linux_services.upc_connector(kind,255),'C')
        self.assertEqual(linux_services.upc_connector(0,0),'internal')
        self.assertEqual(linux_services.upc_connector(254,255),'unknown')

    def test_c_library_success_and_error_across_subprocess(self):
        library=Path(__file__).parent/'build/test-libasus-healthytable.so'
        if not library.exists():self.skipTest('Run make check to build the native ABI test library.')
        lib=ctypes.CDLL(str(library))
        lib.asus_ht_call.argtypes=[ctypes.c_char_p,ctypes.POINTER(ctypes.c_void_p)]
        lib.asus_ht_call.restype=ctypes.c_int
        lib.asus_ht_free.argtypes=[ctypes.c_void_p]
        for request,code in [({'name':'wmiadd','args':{'value':41}},0),({'name':'unknown'},1)]:
            ptr=ctypes.c_void_p()
            result=lib.asus_ht_call(json.dumps(request).encode(),ctypes.byref(ptr))
            try:
                self.assertEqual(result,code)
                data=json.loads(ctypes.string_at(ptr))
                self.assertEqual(data['ok'],code==0)
                if code==0:self.assertEqual(data['result'],42)
            finally:lib.asus_ht_free(ptr)
        ptr=ctypes.c_void_p()
        self.assertEqual(lib.asus_ht_call(b'x'*65537,ctypes.byref(ptr)),-errno.E2BIG)
        self.assertIsNone(ptr.value)


    def _probe_library(self,temp,timeout_ms=60000):
        import shutil,subprocess
        source=Path(__file__).parent/'lib/asus_healthytable.c'
        compiler=shutil.which('cc') or shutil.which('gcc')
        if not compiler or not Path('/usr/bin/python3').exists():self.skipTest('A C compiler and /usr/bin/python3 are required.')
        bridge=Path(temp)/'probe_bridge.py'
        bridge.write_text("""import json,os,sys,time
request=json.loads(sys.stdin.read())
if request.get('sleep'):time.sleep(request['sleep'])
print(json.dumps({'ok':True,'result':{'env':dict(os.environ),'isolated':sys.flags.isolated,
    'dont_write_bytecode':sys.flags.dont_write_bytecode,'path0':sys.path[0] if sys.path else None,
    'fds':sorted(int(n) for n in os.listdir('/proc/self/fd'))}}))
""")
        library=Path(temp)/'probe.so'
        subprocess.run([compiler,'-O2','-Wall','-Wextra','-Werror','-std=c11','-fPIC','-shared','-I'+str(source.parent.parent/'include'),
                        '-DASUS_HT_BRIDGE="'+str(bridge)+'"','-DASUS_HT_TIMEOUT_MS='+str(timeout_ms),str(source),'-o',str(library)],check=True,timeout=60)
        return library

    def _probe_code(self):
        return """import ctypes,json,sys
lib=ctypes.CDLL(sys.argv[1])
lib.asus_ht_call.argtypes=[ctypes.c_char_p,ctypes.POINTER(ctypes.c_void_p)];lib.asus_ht_call.restype=ctypes.c_int
ptr=ctypes.c_void_p();code=lib.asus_ht_call(sys.argv[2].encode(),ctypes.byref(ptr))
out={'code':code,'response':json.loads(ctypes.string_at(ptr)) if ptr.value else None}
"""

    def test_c_library_runs_isolated_bridge_with_minimal_environment(self):
        import os,subprocess,sys,tempfile
        with tempfile.TemporaryDirectory() as temp:
            library=self._probe_library(temp)
            evil=Path(temp)/'evil';evil.mkdir();(evil/'json.py').write_text('raise SystemExit(99)\n')
            env={**os.environ,'PYTHONPATH':str(evil),'PYTHONHOME':str(evil),'PYTHONSTARTUP':str(evil/'json.py'),
                 'LD_PRELOAD':'','LD_LIBRARY_PATH':str(evil),'PATH':str(evil),'LANG':'xx_YY.bogus','UNRELATED_SECRET':'do-not-pass'}
            code=self._probe_code()+"open(sys.argv[3],'w').write(json.dumps(out))\n"
            result_file=Path(temp)/'out.json'
            subprocess.run([sys.executable,'-I','-c',code,str(library),'{}',str(result_file)],env=env,cwd=evil,check=True,timeout=30)
            out=json.loads(result_file.read_text())
        self.assertEqual(out['code'],0,out)
        child=out['response']['result']
        self.assertEqual(child['isolated'],1);self.assertEqual(child['dont_write_bytecode'],1)
        self.assertEqual(child['env']['PATH'],'/usr/sbin:/usr/bin:/sbin:/bin');self.assertEqual(child['env']['LANG'],'C.UTF-8')
        for name in ('PYTHONPATH','PYTHONHOME','PYTHONSTARTUP','LD_PRELOAD','LD_LIBRARY_PATH','UNRELATED_SECRET'):
            self.assertNotIn(name,child['env'])
        self.assertLessEqual(set(child['env']),{'PATH','LANG','HOME','XDG_RUNTIME_DIR','XDG_CONFIG_HOME','DBUS_SESSION_BUS_ADDRESS','DBUS_SYSTEM_BUS_ADDRESS'})

    def test_c_library_with_closed_standard_fds_keeps_request_and_response(self):
        import subprocess,sys,tempfile
        with tempfile.TemporaryDirectory() as temp:
            library=self._probe_library(temp)
            result_file=Path(temp)/'out.json'
            code="import os,sys\nfd=os.open(sys.argv[3],os.O_WRONLY|os.O_CREAT|os.O_CLOEXEC,0o600)\nos.dup2(fd,9,inheritable=True);os.close(fd)\nfor n in (0,1,2):os.close(n)\n"+self._probe_code()+"os.write(9,json.dumps(out).encode())\n"
            subprocess.run([sys.executable,'-c',code,str(library),'{"probe":1}',str(result_file)],check=True,timeout=30,
                           stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            out=json.loads(result_file.read_text())
        self.assertEqual(out['code'],0,out)
        self.assertEqual(out['response']['result']['fds'][:3],[0,1,2])
        self.assertNotIn(9,out['response']['result']['fds'])  # caller fds do not leak into the bridge

    def test_c_library_kills_stalled_bridge_and_reports_timeout(self):
        import subprocess,sys,tempfile,time
        with tempfile.TemporaryDirectory() as temp:
            library=self._probe_library(temp,timeout_ms=700)
            result_file=Path(temp)/'out.json'
            code=self._probe_code()+"open(sys.argv[3],'w').write(json.dumps(out))\n"
            start=time.monotonic()
            subprocess.run([sys.executable,'-c',code,str(library),'{"sleep":30}',str(result_file)],check=True,timeout=20)
            elapsed=time.monotonic()-start
            out=json.loads(result_file.read_text())
        self.assertEqual(out['code'],-errno.ETIMEDOUT);self.assertIsNone(out['response'])
        self.assertLess(elapsed,10)

if __name__=='__main__':unittest.main()
