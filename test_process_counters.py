# SPDX-License-Identifier: GPL-2.0-only
import errno
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import api_bridge
import process_counters as process


def stat(pid,name='worker',user=0,system=0,start=100,rss=10):
    fields=['S']+['0']*30
    for index,value in [(11,user),(12,system),(19,start),(21,rss)]:fields[index]=str(value)
    return str(pid).encode()+b' ('+name.encode()+b') '+' '.join(fields).encode()+b'\n'


class ProcessCounterTests(unittest.TestCase):
    def measure(self,first,last,name='AppList_CpuUsage',elapsed=.2,deny=(),deny_rss=(),rss_override=None,**options):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);clock=[0.0]
            def populate(rows):
                for p in root.iterdir():
                    if p.is_dir():
                        for f in p.iterdir():f.unlink()
                        p.rmdir()
                for pid,raw in rows.items():
                    p=root/str(pid);p.mkdir();(p/'stat').write_bytes(raw)
                    try:rss=process.decode(raw,pid)['rss_pages']
                    except OSError:rss=0
                    rss=(rss_override or {}).get(pid,rss)
                    (p/'statm').write_text(f'{rss+1024} {rss} 0 0 0 0 0\n')
                    (p/'cmdline').write_text('must never read');(p/'environ').write_text('must never read')
            populate(first)
            def wait(seconds):
                self.assertEqual(seconds,.2);populate(last);clock[0]=elapsed
            original=Path.open
            def opened(path,mode='r',*args,**kwargs):
                if 'r' in mode:
                    self.assertIn(path.name,('stat','statm'))
                    if int(path.parent.name) in deny:raise PermissionError(errno.EACCES,'Denied stat')
                    if path.name=='statm' and int(path.parent.name) in deny_rss:
                        raise PermissionError(errno.EACCES,'Denied statm')
                return original(path,mode,*args,**kwargs)
            with mock.patch.object(Path,'open',opened),mock.patch('os.getuid',side_effect=AssertionError('UID filtering')):
                return process.collect(name,root=root,clock=lambda:clock[0],wait=wait,
                                       sysconf=lambda n:100 if n=='SC_CLK_TCK' else 4096,**options)

    def test_window_selected_pids_preserve_idle_zero_rss_and_all_rows(self):
        rows={i:stat(i,rss=0) for i in range(1,21)}
        with mock.patch.object(process,'_census',side_effect=AssertionError('No global census')):
            result=self.measure(rows,rows,selected_pids=list(rows),all_rows=True)
        self.assertEqual(len(result['processes']),20);self.assertIsNone(result['limit'])
        self.assertTrue(all(r['cpu_percent']==0 and r['rss_bytes']==0 for r in result['processes']))
        self.assertEqual(self.measure(rows,rows,selected_pids=[3,3,1],all_rows=True)['initial_pid_count'],2)

    def test_invalid_window_pid_selection_is_rejected_before_reads(self):
        with mock.patch.object(process,'_sample') as read:
            for pids in [[0],[-1],[True],[2**31],list(range(1,4098)),'all']:
                with self.subTest(pids=str(pids)[:30]),self.assertRaises(ValueError):process.collect('AppList_MemUsage',selected_pids=pids)
        read.assert_not_called()

    def test_window_pid_identity_check_rejects_reuse(self):
        with mock.patch.object(process,'_stat',return_value={'start_ticks':101}),self.assertRaises(OSError) as error:
            process.verify_identity(1,100)
        self.assertEqual(error.exception.errno,errno.EAGAIN)

    def test_top_five_cpu_top_ten_memory_and_both_counters(self):
        first={i:stat(i,rss=20-i) for i in range(1,16)}
        last={i:stat(i,user=2*i,rss=20-i) for i in range(1,16)}
        first[0]=last[0]=stat(0,user=10000,rss=10000)
        cpu=self.measure(first,last);mem=self.measure(first,last,'AppList_MemUsage')
        self.assertEqual([r['pid'] for r in cpu['processes']],[15,14,13,12,11])
        self.assertEqual([r['pid'] for r in mem['processes']],list(range(1,11)))
        self.assertAlmostEqual(cpu['processes'][0]['cpu_percent'],150)
        self.assertEqual(mem['processes'][0]['rss_bytes'],19*4096)
        self.assertAlmostEqual(mem['processes'][0]['cpu_percent'],10)
        self.assertTrue(cpu['ranking_complete']);self.assertEqual(cpu['final_pid_count'],15)

    def test_kernel_name_framing_with_parentheses_newline_and_encoding(self):
        raw=stat(1,name='a) (b\nend')
        row=process.decode(raw,1);self.assertEqual(row['name'],'a) (b\nend')
        row=process.decode(raw.replace(b'a) (b\nend',b'bad\xff'),1)
        self.assertTrue(row['name_encoding_loss']);self.assertEqual(row['start_ticks'],100)

    def test_zero_and_fewer_than_five_processes_are_safe(self):
        rows={1:stat(1,rss=0)}
        for name in process.NAMES:
            out=self.measure(rows,rows,name)
            self.assertTrue(out['available']);self.assertTrue(out['ranking_complete'])
            self.assertEqual(out['processes'],[])
        out=self.measure({1:stat(1)},{1:stat(1,user=1)})
        self.assertEqual(len(out['processes']),1)
        self.assertEqual(self.measure({}, {})['processes'],[])

    def test_pid_reuse_never_mixes_cpu_with_replacement_memory(self):
        out=self.measure({1:stat(1,user=100,start=50)},
                         {1:stat(1,name='replacement',user=1,start=150,rss=20)},'AppList_MemUsage')
        row=out['processes'][0]
        self.assertEqual(row['name'],'replacement');self.assertEqual(row['rss_bytes'],81920)
        self.assertFalse(row['cpu_available']);self.assertIsNone(row['cpu_percent'])
        self.assertEqual(row['cpu_errno'],errno.EAGAIN);self.assertEqual(out['reused_pids'],1)
        self.assertTrue(out['ranking_complete'])

    def test_new_and_exited_processes_have_explicit_census_and_unknown_cpu(self):
        out=self.measure({1:stat(1)},{2:stat(2)},'AppList_MemUsage')
        self.assertEqual(out['exited_since_initial_census'],1)
        self.assertEqual(out['new_since_initial_census'],1)
        self.assertIsNone(out['processes'][0]['cpu_percent'])
        self.assertEqual(out['unknown_cpu_processes'],1)
        cpu=self.measure({1:stat(1)},{2:stat(2)})
        self.assertFalse(cpu['available']);self.assertFalse(cpu['ranking_complete'])
        self.assertEqual(cpu['errno'],errno.ENODATA)

    def test_counter_regression_is_unavailable_not_zero(self):
        out=self.measure({1:stat(1,user=2)},{1:stat(1,user=1)},'AppList_MemUsage')
        row=out['processes'][0]
        self.assertFalse(row['cpu_available']);self.assertIsNone(row['cpu_percent'])
        self.assertEqual(row['cpu_errno'],errno.EPROTO)

    def test_unknown_candidates_make_rank_incomplete_and_errors_bounded(self):
        first={i:stat(i) for i in range(1,101)}
        out=self.measure(first,first,deny=range(1,101))
        self.assertFalse(out['available']);self.assertFalse(out['ranking_complete'])
        self.assertEqual(out['unknown_cpu_processes'],100)
        self.assertEqual(out['unknown_rss_processes'],100)
        self.assertEqual(out['sample_error_count'],200)
        self.assertEqual(len(out['sample_errors']),64);self.assertTrue(out['sample_errors_truncated'])
        self.assertTrue(all(r['errno']==errno.EACCES for r in out['sample_errors']))

    def test_short_or_reversed_interval_is_not_reported_idle(self):
        for interval in [.01,-.1]:
            out=self.measure({1:stat(1)},{1:stat(1,user=1)},elapsed=interval)
            self.assertFalse(out['available']);self.assertEqual(out['processes'],[])
            self.assertEqual(out['sample_errors'][-1]['errno'],errno.EAGAIN)

    def test_read_uncertainty_spanning_interval_withholds_cpu(self):
        original=process._sample
        def slow(*args):
            row=original(*args);row['read_window_seconds']=1;return row
        with mock.patch.object(process,'_sample',slow):
            out=self.measure({1:stat(1)},{1:stat(1,user=1)},'AppList_MemUsage')
        self.assertIsNone(out['processes'][0]['cpu_percent'])
        self.assertEqual(out['processes'][0]['cpu_errno'],errno.EAGAIN)

    def test_partial_permission_failure_keeps_other_ranked_candidates(self):
        first={1:stat(1),2:stat(2)};last={1:stat(1,user=10),2:stat(2,user=20)}
        out=self.measure(first,last,deny=(2,))
        self.assertTrue(out['available']);self.assertFalse(out['ranking_complete'])
        self.assertEqual([r['pid'] for r in out['processes']],[1])
        self.assertEqual(out['unknown_cpu_processes'],1)

    def test_invalid_or_truncated_stat_fields_are_errors(self):
        valid=stat(1)
        for raw in [b'',b'1 x S 0',stat(2),stat(1,user=-1),stat(1,rss=-1),
                    stat(1,start=2**64),b'x'*65537]:
            with self.subTest(raw=raw[:50]),self.assertRaises(OSError):process.decode(raw,1)
        out=self.measure({1:valid},{1:b'invalid'})
        self.assertFalse(out['available']);self.assertEqual(out['unknown_rss_processes'],1)

    def test_large_rss_is_not_truncated_to_signed_32_bit(self):
        rows={1:stat(1,rss=2**24)}
        out=self.measure(rows,rows,'AppList_MemUsage')
        self.assertEqual(out['processes'][0]['rss_bytes'],2**36)

    def test_memory_uses_statm_and_keeps_cpu_when_memory_is_denied(self):
        first={1:stat(1,rss=1)};last={1:stat(1,user=1,rss=1)}
        out=self.measure(first,last,'AppList_MemUsage',rss_override={1:2})
        self.assertEqual(out['processes'][0]['rss_bytes'],8192)
        out=self.measure(first,last,deny_rss=(1,))
        self.assertTrue(out['processes'][0]['cpu_available'])
        self.assertFalse(out['processes'][0]['rss_available'])
        self.assertIsNone(out['processes'][0]['rss_bytes'])
        self.assertEqual(out['processes'][0]['rss_errno'],errno.EACCES)
        self.assertTrue(out['ranking_complete']);self.assertEqual(out['unknown_rss_processes'],1)
        mem=self.measure(first,last,'AppList_MemUsage',deny_rss=(1,))
        self.assertFalse(mem['available']);self.assertFalse(mem['ranking_complete'])

    def test_resident_memory_bounds_and_identity_bracket(self):
        for raw in [b'',b'1',b'1 2',b'1 -1',b'1 '*4097]:
            with self.subTest(raw=raw[:10]),self.assertRaises(OSError):process.decode_statm(raw)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'1';p.mkdir();(p/'stat').write_bytes(stat(1,start=100));(p/'statm').write_bytes(b'100 10')
            original=Path.open
            def opened(path,mode='r',*args,**kwargs):
                if path.name=='statm' and mode=='rb':(p/'stat').write_bytes(stat(1,start=101))
                return original(path,mode,*args,**kwargs)
            with mock.patch.object(Path,'open',opened),self.assertRaises(OSError) as error:
                process._sample(root,1,lambda:0)
            self.assertEqual(error.exception.errno,errno.EAGAIN)

    def test_ties_have_deterministic_pid_order_and_no_name_filter(self):
        first={2:stat(2,name='_Total'),1:stat(1,name='_Total')}
        last={2:stat(2,name='_Total',user=1),1:stat(1,name='_Total',user=1)}
        out=self.measure(first,last)
        self.assertEqual([r['pid'] for r in out['processes']],[1,2])

    def test_invalid_native_units_fail_before_process_access(self):
        with mock.patch.object(process,'_census') as census:
            for value in [0,-1,True,None]:
                with self.subTest(value=value),self.assertRaises(OSError):
                    process.collect('AppList_CpuUsage',sysconf=lambda n:value)
        census.assert_not_called()

    def test_public_dispatch_and_rejection_before_sampling(self):
        with mock.patch.object(process,'collect',return_value={'available':True}) as read:
            for name in process.NAMES:
                self.assertTrue(api_bridge.call({'name':name})['available'])
            self.assertEqual(read.call_count,2)
            for name in process.NAMES:
                with self.assertRaises(ValueError):api_bridge.call({'name':name,'args':{'all_users':True}})
                with self.assertRaises(ValueError):process.call(name,{'pid':1})
            self.assertEqual(read.call_count,2)


if __name__=='__main__':unittest.main()
