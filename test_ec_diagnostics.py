# SPDX-License-Identifier: GPL-2.0-only
import copy
import errno
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
import compat
import ec_diagnostics as diag

LAYOUT=json.loads(diag.LAYOUT.read_text())

def packet():
    return {'schema':2,'protocol':15,'started_boottime_us':99_000_000,'duration_us':5000,
        'values':[[0,15 if i==0 else 33] for i in range(40)],'chip':{'status':0,'raw':list(b'ABCD')},
        'project':{'status':0,'raw':list(b'EXAMPLE-BIOS\0'.ljust(32,b'\0'))},
        'manufacturer':{'status':0,'raw':list(b'Example'.ljust(11,b'\0'))},
        'board':{'status':0,'raw':[31,32,33,0,255]},'board_selector_restored':True,
        'vr':{'status':0,'count':0},'fan':{'status':0,'count':1,'index':0,'selection_raw':1,'mode_raw':0,'rpm':3000,'duty_status':-95,'duty_code':None,'duty_code_maximum':254}}

def entries(result):return {row['name']:row for group in result['groups'] for row in group['entries']}

class DiagnosticTests(unittest.TestCase):
    def test_full_original_shape_strings_raw_codes_and_version_gates(self):
        result=diag.decode(packet(),LAYOUT,100);rows=entries(result)
        self.assertEqual(result['table_entry_count'],69);self.assertEqual(len(rows),69)
        self.assertEqual(rows['ProjectFWRevision']['byte_count'],32)
        self.assertEqual(rows['ProjectFWRevision']['text'],'EXAMPLE-BIOS')
        self.assertEqual(rows['ChipName']['text'],'ABCD')
        self.assertEqual(rows['Manuf_name']['text'],'Example')
        self.assertEqual(rows['Current']['raw_unsigned'],33);self.assertNotIn('amperes',rows['Current'])
        self.assertEqual(rows['Project Year']['errno'],errno.EOPNOTSUPP)
        self.assertEqual(rows['Power Limit Value']['effective_minimum_version'],24)
        self.assertEqual(rows['VRSensorInfo']['count'],0)
        board=rows['BoardSensorInfo'];self.assertTrue(board['selector_restored'])
        self.assertEqual(board['items'][0]['index'],1)
        self.assertEqual(board['items'][-1]['fields']['Temperature']['raw_unsigned'],255)
        self.assertEqual(board['items'][0]['fields']['Status']['errno'],errno.EOPNOTSUPP)
        self.assertIsNone(rows['FanInfo']['duty_code']);self.assertEqual(rows['FanInfo']['duty_errno'],95)
    def test_c_and_python_fixed_recipe_order_is_exact_and_no_higher_protocol_request(self):
        expected=[(r['command'],r['bank_or_special'],r['register_or_count'],r['length']) for g in LAYOUT['main'] for r in g['rows'] if r['command']!=255 and r['minimum_version']<=15]
        text=Path('source/healthytable_diagnostics.h').read_text().split('ht_diag_fields[]={',1)[1].split('};',1)[0]
        actual=[tuple(int(x,0) for x in match) for match in re.findall(r'\{(0x[0-9a-f]+),([0-9]+),(0x[0-9a-f]+),([0-9]+)\}',text)]
        self.assertEqual(actual,expected);self.assertEqual(len(expected),40)
        self.assertEqual(sum(len(g['rows']) for g in LAYOUT['nested']),23)
    def test_partial_string_and_scalar_errors_remain_typed_not_zero_or_partial_text(self):
        p=packet();p['project']={'status':-errno.EAGAIN,'raw':[]};p['values'][6]=[-errno.EAGAIN,None]
        rows=entries(diag.decode(p,LAYOUT,100));self.assertEqual(rows['ProjectFWRevision']['errno'],errno.EAGAIN)
        self.assertNotIn('raw_hex',rows['ProjectFWRevision']);self.assertEqual(rows['ECBatteryStatus']['errno'],errno.EAGAIN)
        self.assertEqual(rows['FanInfo']['rpm'],3000)
    def test_strict_schema_timing_sizes_and_statuses(self):
        changes=[('schema',True),('protocol',True),('started_boottime_us',101_000_000),('duration_us',31_000_000),('values',[]),('board_selector_restored',False)]
        for key,value in changes:
            p=packet();p[key]=value
            with self.assertRaises(OSError):diag.decode(p,LAYOUT,100)
        for value in [[0,True],[0,-1],[-errno.EIO,0],[True,5]]:
            p=packet();p['values'][1]=value
            with self.assertRaises(OSError):diag.decode(p,LAYOUT,100)
        for key,count in [('chip',3),('project',31),('manufacturer',10)]:
            p=packet();p[key]['raw']=[1]*count
            with self.assertRaises(OSError):diag.decode(p,LAYOUT,100)
    def test_duty_is_even_raw_code_separate_from_request_and_mode(self):
        p=packet()['fan'];self.assertEqual(diag.fan_value(p)['mode'],'automatic')
        for value in (1,195,255,True):
            with self.assertRaises(OSError):diag.fan_value({**p,'duty_code':value,'mode_raw':1,'duty_status':0})
        self.assertEqual(diag.fan_value({**p,'duty_code':0,'mode_raw':1,'duty_status':0})['mode'],'manual')
    def test_unprintable_revision_keeps_bytes_without_invented_text(self):
        p=packet();p['project']['raw'][0]=255
        r=entries(diag.decode(p,LAYOUT,100))['ProjectFWRevision']
        self.assertIsNone(r['text']);self.assertTrue(r['raw_hex'].startswith('ff'))
    def test_background_report_never_collects_eeprom(self):
        with mock.patch.object(diag.native_oem,'device',side_effect=RuntimeError('missing')),mock.patch.object(diag.firmware_queries,'call',side_effect=AssertionError('No hidden EEPROM')):
            self.assertFalse(diag.report()['available'])
    def test_explicit_log_preserves_fields_and_unavailable_raw_data(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'log.jsonl';result=diag.decode(packet(),LAYOUT,100)
            with mock.patch.object(diag,'report',return_value={**result,'raw_data':diag.unavailable('FE unsupported')}),mock.patch.object(diag.time,'sleep') as sleep:
                out=diag.write_log(str(p),2,.5,lambda:{'owner_field':'retained'})
            values=[json.loads(line) for line in p.read_text().splitlines()]
            self.assertEqual(len(values),2);self.assertEqual(out['source_table_entries_per_successful_sample'],69)
            self.assertTrue(all(v['owner_field']=='retained' and v['ec_diagnostics']['table_entry_count']==69 for v in values))
            self.assertEqual(p.stat().st_mode&0o777,0o600);sleep.assert_called_once_with(.5)
            with self.assertRaises(FileExistsError):diag.write_log(str(p))
            link=p.with_name('link');link.symlink_to(p)
            with self.assertRaises(OSError):diag.write_log(str(link))
    def test_log_refuses_symlinked_directory_components_after_swap(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);logs=base/'logs';logs.mkdir();victim=base/'victim';victim.mkdir()
            with mock.patch.object(diag,'report',return_value={}):
                diag.write_log(str(logs/'first'))
                self.assertTrue((logs/'first').is_file())
                # A same-UID process swaps an intermediate directory for a symlink.
                logs.rename(base/'moved');logs.symlink_to(victim)
                with self.assertRaises(OSError) as caught:diag.write_log(str(logs/'x'))
                self.assertIn(caught.exception.errno,(errno.ELOOP,errno.ENOTDIR));self.assertIn("symlinks",str(caught.exception))
                nested=base/'a';nested.mkdir();(nested/'b').symlink_to(victim)
                with self.assertRaises(OSError):diag.write_log(str(nested/'b'/'y'))
                with self.assertRaises(OSError):diag.write_log(str(base/'moved'/'first'/'z'))  # file as directory
                for bad in (str(base)+'/',str(base)+'/.',str(base)+'/..','.'):
                    with self.assertRaises(ValueError):diag.write_log(bad)
            self.assertEqual(list(victim.iterdir()),[])
    def test_log_relative_path_resolves_against_cwd(self):
        with tempfile.TemporaryDirectory() as temp:
            old=os.getcwd()
            try:
                os.chdir(temp)
                with mock.patch.object(diag,'report',return_value={}):diag.write_log('rel.jsonl')
            finally:os.chdir(old)
            self.assertTrue((Path(temp)/'rel.jsonl').is_file())
    def test_root_log_is_chowned_to_invoking_user_and_requires_their_directory(self):
        uid,gid=os.getuid(),os.getgid()
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'log'
            with mock.patch.object(diag,'report',return_value={}),mock.patch.object(diag.os,'geteuid',return_value=0),\
                 mock.patch.dict(os.environ,{'SUDO_UID':str(uid),'SUDO_GID':str(gid)}),mock.patch.object(diag.os,'fchown') as chown:
                diag.write_log(str(p))
                self.assertEqual(chown.call_args.args[1:],(uid,gid))
                with mock.patch.dict(os.environ,{'SUDO_UID':str(uid+1)}),mock.patch.object(diag.pwd,'getpwuid',return_value=SimpleNamespace(pw_gid=4321)):
                    with self.assertRaises(PermissionError):diag.write_log(str(Path(temp)/'other'))
                self.assertFalse((Path(temp)/'other').exists())
                with mock.patch.dict(os.environ,{'SUDO_UID':'-1'}):
                    with self.assertRaises(PermissionError):diag.write_log(str(Path(temp)/'bad'))
            env={k:v for k,v in os.environ.items() if k not in ('SUDO_UID','SUDO_GID')}
            with mock.patch.object(diag,'report',return_value={}),mock.patch.object(diag.os,'geteuid',return_value=0),\
                 mock.patch.dict(os.environ,{**env,'PKEXEC_UID':str(uid)},clear=True),mock.patch.object(diag.os,'fchown') as chown,\
                 mock.patch.object(diag.pwd,'getpwuid',return_value=SimpleNamespace(pw_gid=gid)):
                diag.write_log(str(Path(temp)/'pk'))
                self.assertEqual(chown.call_args.args[1:],(uid,gid))
    def test_invalid_arguments_rejected_before_creating_file_or_elevation(self):
        with tempfile.TemporaryDirectory() as temp:
            p=str(Path(temp)/'log')
            for args in [{'path':p,'interval':float('nan')},{'path':p,'interval':'1'},{'path':p,'samples':True},{'path':p,'unknown':1}]:
                with self.assertRaises(ValueError):compat.validate('SaveEcLog',args)
            self.assertFalse(Path(p).exists())
        with mock.patch.object(diag.firmware_queries,'report',return_value={'eeprom_table':{'available':False}}):self.assertFalse(compat.needs_root('SaveEcLog',{'path':'new-log'}))
        with mock.patch.object(diag.firmware_queries,'report',return_value={'eeprom_table':{'available':True}}):self.assertTrue(compat.needs_root('SaveEcLog',{'path':'new-log'}))
    def test_fan_report_is_independent_of_blocked_full_ec_report(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);(p/'fan_diagnostics').write_text(json.dumps({'schema':2,**packet()['fan']}))
            with mock.patch.object(diag.native_oem,'device',return_value=p),mock.patch.object(diag.qualified_ec,'identity',return_value=(1,2)),mock.patch.object(diag.qualified_ec,'snapshot',side_effect=AssertionError('No whole EC snapshot')):
                self.assertTrue(diag.fan_report()['available'])

if __name__=='__main__':unittest.main()
