# SPDX-License-Identifier: GPL-2.0-only
import errno
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

import api_bridge
import application_inventory as inventory


class InventoryTests(unittest.TestCase):
    def dpkg(self,output,widths):
        def command(args):
            if args[0]=='dpkg-query':
                self.assertIn('${db:Status-Status}',args[2])
                self.assertNotIn('Status-Abbrev',args[2]);return output
            self.assertEqual(args[0],'dpkg-architecture')
            arch=args[1].removeprefix('--host-arch=');value=widths[arch]
            if isinstance(value,Exception):raise value
            return str(value)+'\n'
        return mock.patch.object(inventory,'_command',side_effect=command)

    def test_held_installed_abi_widths_and_independent_architecture(self):
        output='held-package\t1:2.0\tamd64\tinstalled\nx32-package\t2\tx32\tinstalled\nmainframe\t3\ts390x\tinstalled\ndata-files\t4\tall\tinstalled\nremoved\t1\tamd64\tconfig-files\n'
        with self.dpkg(output,{'amd64':64,'x32':32,'s390x':64}):
            wide=inventory.native(64);narrow=inventory.native(32)
        self.assertEqual([r['name'] for r in wide['packages']],['held-package','mainframe'])
        self.assertEqual([r['name'] for r in narrow['packages']],['x32-package'])
        self.assertEqual(wide['architecture_independent'],narrow['architecture_independent'])
        self.assertIsNone(wide['architecture_independent'][0]['architecture_bits'])
        self.assertTrue(wide['complete']);self.assertEqual(wide['providers'][0]['removed_records_excluded'],1)

    def test_unconfigured_registered_packages_keep_their_state(self):
        with self.dpkg('partial\t2\tamd64\tunpacked\n',{'amd64':64}):result=inventory.native(64)
        self.assertFalse(result['packages'][0]['fully_installed'])
        self.assertEqual(result['packages'][0]['state'],'unpacked')

    def test_unknown_architecture_is_retained_without_host_guess(self):
        with self.dpkg('test-package\t1\tnewarch\tinstalled\n',{'newarch':OSError(errno.ENODATA,'Unknown ABI')}):
            result=inventory.native(64)
        self.assertTrue(result['available']);self.assertFalse(result['complete'])
        self.assertEqual(result['packages'],[]);self.assertEqual(len(result['unclassified_packages']),1)
        self.assertIsNone(result['unclassified_packages'][0]['architecture_bits'])

    def test_invalid_partial_dpkg_rows_have_bounded_errors(self):
        output='good\t1\tamd64\tinstalled\n'+'bad\n'*100
        with self.dpkg(output,{'amd64':64}):result=inventory.native(64)
        self.assertEqual(result['packages'][0]['name'],'good')
        self.assertFalse(result['complete']);self.assertEqual(result['providers'][0]['parse_error_count'],100)
        self.assertEqual(len(result['providers'][0]['parse_errors']),64)

    def test_absent_or_failed_dpkg_is_not_empty_success(self):
        for code in [errno.ENODEV,errno.EACCES,errno.ETIMEDOUT]:
            with self.subTest(code=code),mock.patch.object(inventory,'_command',side_effect=OSError(code,'Unavailable')):
                result=inventory.native(64)
            self.assertFalse(result['available']);self.assertFalse(result['complete'])
            self.assertEqual(result['providers'][0]['errno'],code)

    def test_command_errors_timeout_invalid_encoding_and_bound(self):
        import linux_services
        with mock.patch.object(linux_services,'system_tool',side_effect=FileNotFoundError(errno.ENOENT,'absent')),\
             mock.patch.object(inventory.subprocess,'run') as run,self.assertRaises(OSError) as error:
            inventory._command(['fixed-tool'])
        self.assertEqual(error.exception.errno,errno.ENODEV);run.assert_not_called()
        tool=mock.patch.object(linux_services,'system_tool',return_value='/usr/bin/fixed-tool');tool.start();self.addCleanup(tool.stop)
        for failure,code in [(FileNotFoundError(),errno.ENODEV),
                             (subprocess.TimeoutExpired('tool',5),errno.ETIMEDOUT)]:
            with mock.patch.object(inventory.subprocess,'run',side_effect=failure),self.assertRaises(OSError) as error:
                inventory._command(['fixed-tool'])
            self.assertEqual(error.exception.errno,code)
        for stdout,rc,code in [(b'\xff',0,errno.EPROTO),(b'',1,errno.EIO),(b'x'*17,0,errno.E2BIG)]:
            with mock.patch.object(inventory,'MAX_BYTES',16),mock.patch.object(inventory.subprocess,'run',return_value=SimpleNamespace(stdout=stdout,returncode=rc)),self.assertRaises(OSError) as error:
                inventory._command(['fixed-tool'])
            self.assertEqual(error.exception.errno,code)

    def test_flatpak_includes_apps_runtimes_extensions_and_scopes(self):
        output='org.Test.App\t\tx86_64\tstable\tremote\tuser\norg.Test.App\t1\tx86_64\tstable\tremote\tsystem\n'
        with mock.patch.object(inventory,'_command',return_value=output) as command:
            rows,status=inventory.flatpak('runtime')
        self.assertIn('--all',command.call_args.args[0]);self.assertIn('--runtime',command.call_args.args[0])
        self.assertTrue(status['complete']);self.assertEqual([r['scope'] for r in rows],['user','system'])
        self.assertIsNone(rows[0]['version']);self.assertFalse(rows[0]['version_available'])

    def test_flatpak_duplicate_and_malformed_rows_do_not_erase_good(self):
        good='org.Test.App\t1\tx86_64\tstable\tremote\tsystem\n'
        with mock.patch.object(inventory,'_command',return_value=good+good+'bad\n'):
            rows,status=inventory.flatpak('app')
        self.assertEqual(len(rows),1);self.assertFalse(status['complete'])
        self.assertEqual(status['parse_error_count'],2)

    def test_packaged_inventory_keeps_good_provider_and_failed_provider(self):
        def command(args):
            if '--runtime' in args:raise OSError(errno.ETIMEDOUT,'Runtime query timed out')
            return 'org.Test.App\t1\tx86_64\tstable\tremote\tuser\n'
        with mock.patch.object(inventory,'_command',side_effect=command),mock.patch.object(inventory,'_snapd',side_effect=OSError(errno.ENODEV,'Absent')):
            result=inventory.call('GetApplist_UWP',{})
        self.assertTrue(result['available']);self.assertFalse(result['complete'])
        self.assertEqual(len(result['packages']),1)
        self.assertEqual([p['available'] for p in result['providers']],[True,False,False])

    def test_genuine_empty_success_and_all_providers_unavailable_are_distinct(self):
        with mock.patch.object(inventory,'_command',return_value=''),mock.patch.object(inventory,'_snapd',return_value=[]):
            good=inventory.call('App_Get_UWPApp',{})
        self.assertTrue(good['available']);self.assertTrue(good['complete']);self.assertEqual(good['packages'],[])
        with mock.patch.object(inventory,'_command',side_effect=OSError(errno.ENODEV,'Absent')),mock.patch.object(inventory,'_snapd',side_effect=OSError(errno.ENODEV,'Absent')):
            bad=inventory.call('App_Get_UWPApp',{})
        self.assertFalse(bad['available']);self.assertFalse(bad['complete'])

    def test_snap_manifest_explicit_multiarch_and_format_default(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'sample'/'1'/'meta';p.mkdir(parents=True);manifest=p/'snap.yaml'
            for declaration,expected,defaulted in [('architectures: [amd64, arm64]\n',['amd64','arm64'],False),
                                                   ('',['all'],True),('architectures: []\n',['all'],True)]:
                manifest.write_text('name: sample\n'+declaration)
                architectures,used_default=inventory._snap_architecture('sample','1',root)
                self.assertEqual(architectures,expected);self.assertEqual(used_default,defaulted)

    def test_snap_manifest_identity_invalid_arch_and_unsafe_yaml_are_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'sample'/'1'/'meta';p.mkdir(parents=True);manifest=p/'snap.yaml'
            for text in ['name: other\n','name: sample\narchitectures: [../bad]\n',
                         'name: sample\narchitectures: amd64\n',
                         '!!python/object/apply:os.system [private-marker]\n']:
                manifest.write_text(text)
                with self.assertRaises(OSError) as error:inventory._snap_architecture('sample','1',root)
                self.assertNotIn('private-marker',str(error.exception))

    def test_changed_or_missing_manifest_never_uses_host_architecture(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'sample'/'1'/'meta';p.mkdir(parents=True);manifest=p/'snap.yaml';manifest.write_text('name: sample\n')
            st=manifest.stat();changed=SimpleNamespace(st_dev=st.st_dev,st_ino=st.st_ino,st_size=st.st_size,st_mtime_ns=st.st_mtime_ns+1)
            with mock.patch.object(Path,'stat',return_value=changed),self.assertRaises(OSError) as error:
                inventory._snap_architecture('sample','1',root)
            self.assertEqual(error.exception.errno,errno.EAGAIN)
            with mock.patch.dict(sys.modules,{'yaml':None}),self.assertRaises(OSError) as error:
                inventory._snap_architecture('sample','1',root)
            self.assertEqual(error.exception.errno,errno.ENODEV)

    def test_snap_revisions_types_and_version_spaces_are_preserved(self):
        records=[{'name':'sample','revision':'1','version':'1 custom','status':'installed','type':'base'},
                 {'name':'sample','revision':'2','version':'2','status':'active','type':'app'}]
        with mock.patch.object(inventory,'_snapd',return_value=records),mock.patch.object(inventory,'_snap_architecture',return_value=(['amd64'],False)):
            rows,status=inventory.snaps()
        self.assertTrue(status['complete']);self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['version'],'1 custom');self.assertFalse(rows[0]['active']);self.assertTrue(rows[1]['active'])

    def test_snap_bad_rows_are_reported_and_manifest_failure_preserves_version(self):
        records=[{'name':'sample','revision':'1','version':'v1','status':'active'},
                 {'name':'../bad','revision':'2','version':'x','status':'active'}]
        with mock.patch.object(inventory,'_snapd',return_value=records),mock.patch.object(inventory,'_snap_architecture',side_effect=OSError(errno.EACCES,'Denied')) as read:
            rows,status=inventory.snaps()
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['version'],'v1')
        self.assertFalse(rows[0]['architecture_available']);self.assertIsNone(rows[0]['architectures'])
        self.assertEqual(rows[0]['architecture_errno'],errno.EACCES);self.assertFalse(status['complete'])
        read.assert_called_once_with('sample','1')

    def test_actual_unix_http_transport_uses_fixed_read_only_installed_endpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            path=str(Path(temp)/'snapd.socket');server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
            server.bind(path);server.listen(1);server.settimeout(3);requests=[];failures=[]
            def serve():
                try:
                    conn,_=server.accept()
                    with conn:
                        conn.settimeout(3);request=b''
                        while b'\r\n\r\n' not in request:request+=conn.recv(4096)
                        requests.append(request)
                        body=json.dumps({'type':'sync','status-code':200,'result':[]}).encode()
                        conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body)).encode()+b'\r\nConnection: close\r\n\r\n'+body)
                except Exception as error:failures.append(error)
            thread=threading.Thread(target=serve,daemon=True);thread.start()
            try:self.assertEqual(inventory._snapd(path),[])
            finally:server.close();thread.join(4)
            self.assertFalse(thread.is_alive());self.assertEqual(failures,[])
            self.assertTrue(requests[0].startswith(b'GET /v2/snaps?select=all HTTP/1.1\r\n'))
            self.assertNotIn(b'Authorization:',requests[0]);self.assertNotIn(b'/v2/find',requests[0])

    def test_snapd_http_invalid_envelope_and_timeout_are_typed(self):
        for body in [b'invalid',b'{}',b'{"type":"async","status-code":200,"result":[]}',b'{"type":"sync","status-code":200,"result":{}}']:
            connection=mock.Mock();connection.getresponse.return_value=SimpleNamespace(status=200,read=lambda n:body)
            with mock.patch.object(inventory,'_UnixHTTP',return_value=connection),self.assertRaises(OSError) as error:inventory._snapd()
            self.assertEqual(error.exception.errno,errno.EPROTO);connection.close.assert_called_once()
        connection=mock.Mock();connection.request.side_effect=TimeoutError()
        with mock.patch.object(inventory,'_UnixHTTP',return_value=connection),self.assertRaises(OSError) as error:inventory._snapd()
        self.assertEqual(error.exception.errno,errno.ETIMEDOUT)

    def test_all_six_routes_reject_arguments_before_tools_or_socket_access(self):
        with mock.patch.object(inventory,'_command') as command,mock.patch.object(inventory,'_snapd') as snap:
            for name in inventory.NAMES:
                with self.subTest(name=name),self.assertRaises(ValueError):api_bridge.call({'name':name,'args':{'refresh':True}})
        command.assert_not_called();snap.assert_not_called()


if __name__=='__main__':unittest.main()
