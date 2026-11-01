# SPDX-License-Identifier: GPL-2.0-only
import errno
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import api_bridge
import disk_temperature as p
from test_storage_inventory import disk as make_disk


class StorageTemperatureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.blocks=self.root/'block';self.hw=self.root/'hwmon';self.dev=self.root/'dev'
        for path in [self.blocks,self.hw,self.dev]:path.mkdir()
        self.nodes={};self.sequence=1

    def disk(self,name,bus='scsi'):
        path=make_disk(self.blocks,name,rotational=int(bus=='scsi'),bus=bus)
        (path/'diskseq').write_text(str(self.sequence));self.sequence+=1
        major,minor=map(int,(path/'dev').read_text().split(':'))
        self.nodes[str(self.dev/name)]=SimpleNamespace(st_mode=stat.S_IFBLK|0o600,st_rdev=os.makedev(major,minor),st_dev=1,st_ino=self.sequence)
        return path

    def hwmon(self,block,value=41000,parent=None):
        path=self.hw/('hwmon'+str(len(list(self.hw.iterdir()))));path.mkdir()
        (path/'name').write_text('nvme' if block.name.startswith('nvme') else 'drivetemp')
        (path/'device').symlink_to(parent or (block/'device').resolve());(path/'temp1_input').write_text(str(value))
        return path

    def result(self,runner=None):
        if runner is None:runner=mock.Mock(side_effect=AssertionError('Unexpected SMART query'))
        return p.report(block_root=self.blocks,hwmon_root=self.hw,dev_root=self.dev,runner=runner,stat_node=lambda node:self.nodes[str(node)])

    def test_unsupported_disk_does_not_hide_working_hwmon_or_smart_disks(self):
        self.disk('sda');self.hwmon(self.disk('nvme0n1','nvme'),41500);self.disk('sdb')
        runner=mock.Mock(side_effect=[SimpleNamespace(returncode=2,stdout='{}'),SimpleNamespace(returncode=0,stdout=json.dumps({'temperature':{'current':34}}))])
        rows={Path(r['device']).name:r for r in self.result(runner)}
        self.assertFalse(rows['sda']['available']);self.assertEqual(rows['nvme0n1']['celsius'],41.5);self.assertEqual(rows['sdb']['celsius'],34)
        self.assertEqual(runner.call_count,2)
        for call in runner.call_args_list:
            self.assertEqual(call.args[0][-3:-1],['-n','standby,3,5']);self.assertLessEqual(call.kwargs['timeout'],8)

    def test_standby_and_unsupported_power_check_do_not_become_zero_temperature(self):
        self.disk('sda')
        for status in (3,5):
            with self.subTest(status=status):
                row=self.result(mock.Mock(return_value=SimpleNamespace(returncode=status,stdout='{}')))[0]
                self.assertFalse(row['available']);self.assertNotIn('celsius',row);self.assertEqual(row['errno'],errno.ENODATA)
                self.assertIn('no ',row['error'].lower())

    def test_malformed_and_timed_out_disk_reads_preserve_other_devices(self):
        self.disk('sda');self.hwmon(self.disk('nvme0n1','nvme'),40000)
        bad=[SimpleNamespace(returncode=0,stdout='broken'),SimpleNamespace(returncode=0,stdout='[]'),SimpleNamespace(returncode=0,stdout='{"temperature":{"current":true}}'),SimpleNamespace(returncode=0,stdout='{"temperature":{"current":32767}}'),SimpleNamespace(returncode=0,stdout='{"temperature":{"current":'+'9'*1000+'}}'),SimpleNamespace(returncode=0,stdout='['*100000),SimpleNamespace(returncode=0,stdout='{"a":'*100000),subprocess.TimeoutExpired('smartctl',8)]
        for failure in bad:
            with self.subTest(failure=failure):
                rows={Path(r['device']).name:r for r in self.result(mock.Mock(side_effect=[failure]))}
                self.assertFalse(rows['sda']['available']);self.assertTrue(rows['nvme0n1']['available'])

    def test_deeply_nested_smart_reply_is_a_protocol_error(self):
        for stdout in ('['*100000,'{"a":'*100000):
            with self.subTest(prefix=stdout[:2]),self.assertRaises(OSError) as caught:
                p.smart_temperature(Path('/nonexistent/sdx'),mock.Mock(return_value=SimpleNamespace(returncode=0,stdout=stdout)),1)
            self.assertEqual(caught.exception.errno,errno.EPROTO)

    def test_hwmon_matches_real_path_ancestry_instead_of_string_prefix(self):
        block=self.disk('nvme0n1','nvme');physical=self.root/'physical'
        wrong=physical/'nvme0';right=physical/'nvme01';wrong.mkdir(parents=True);right.mkdir()
        (block/'device').rename(right/'nvme0n1');(block/'device').symlink_to(right/'nvme0n1')
        self.hwmon(block,99000,wrong);self.hwmon(block,41000,right)
        self.assertEqual(self.result()[0]['celsius'],41)

    def test_disk_generation_change_during_smart_discards_value(self):
        block=self.disk('sda')
        def replace(*args,**kwargs):
            (block/'diskseq').write_text('99');return SimpleNamespace(returncode=0,stdout='{"temperature":{"current":34}}')
        row=self.result(replace)[0];self.assertFalse(row['available']);self.assertNotIn('celsius',row);self.assertEqual(row['errno'],errno.EAGAIN)

    def test_hwmon_reassociation_during_read_is_not_a_disk_temperature(self):
        block=self.disk('sda');hw=self.hwmon(block);other=self.root/'unrelated';other.mkdir();original=p.temperature
        def replace(path):
            value=original(path);(hw/'device').unlink();(hw/'device').symlink_to(other);return value
        with mock.patch.object(p,'temperature',side_effect=replace):row=self.result()[0]
        self.assertFalse(row['available']);self.assertEqual(row['errno'],errno.EAGAIN);self.assertNotIn('celsius',row)

    def test_device_node_replacement_with_same_rdev_is_rejected(self):
        self.disk('sda');node=self.nodes[str(self.dev/'sda')]
        def replace(*args,**kwargs):
            node.st_ino+=1;return SimpleNamespace(returncode=0,stdout='{"temperature":{"current":34}}')
        row=self.result(replace)[0];self.assertFalse(row['available']);self.assertEqual(row['errno'],errno.EAGAIN)

    def test_replacement_while_looking_for_hwmon_prevents_smart(self):
        block=self.disk('sda')
        def replace(*args):
            (block/'diskseq').write_text('99');return None,None
        with mock.patch.object(p,'hwmon_temperature',side_effect=replace):row=self.result()[0]
        self.assertFalse(row['available']);self.assertEqual(row['errno'],errno.EAGAIN)

    def test_nonblock_or_mismatched_node_never_reaches_smart(self):
        self.disk('sda');node=self.nodes[str(self.dev/'sda')]
        node.st_mode=stat.S_IFREG|0o600
        row=self.result()[0];self.assertFalse(row['available']);self.assertEqual(row['errno'],errno.ENODEV)
        node.st_mode=stat.S_IFBLK|0o600;node.st_rdev=os.makedev(99,0)
        self.assertEqual(self.result()[0]['errno'],errno.ENODEV)

    def test_inventory_addition_rejects_incomplete_census(self):
        self.disk('sda')
        def insert(*args,**kwargs):
            self.disk('sdb');return SimpleNamespace(returncode=0,stdout='{"temperature":{"current":34}}')
        with self.assertRaises(OSError) as error:self.result(insert)
        self.assertEqual(error.exception.errno,errno.EAGAIN)

    def test_missing_generation_and_ambiguous_hwmon_do_not_fabricate_values(self):
        block=self.disk('sda');(block/'diskseq').unlink()
        row=self.result()[0];self.assertFalse(row['available']);self.assertEqual(row['errno'],errno.EOPNOTSUPP)
        (block/'diskseq').write_text('1');self.hwmon(block);self.hwmon(block)
        row=self.result()[0];self.assertFalse(row['available']);self.assertEqual(row['errno'],errno.EBUSY)

    def test_shared_deadline_prevents_late_smart_requests(self):
        self.disk('sda')
        with mock.patch.object(p.time,'monotonic',side_effect=[0,11]):row=self.result()[0]
        self.assertFalse(row['available']);self.assertEqual(row['errno'],errno.ETIMEDOUT)

    def test_later_disk_read_cannot_publish_a_previous_replaced_disk(self):
        first=self.disk('sda');self.hwmon(first,40000);self.disk('sdb')
        def replace(*args,**kwargs):
            (first/'diskseq').write_text('99');return SimpleNamespace(returncode=0,stdout='{"temperature":{"current":34}}')
        rows=self.result(replace)
        self.assertFalse(rows[0]['available']);self.assertEqual(rows[0]['errno'],errno.EAGAIN);self.assertNotIn('celsius',rows[0])
        self.assertTrue(rows[1]['available']);self.assertEqual(rows[1]['celsius'],34)

    def test_native_route_and_argument_validation(self):
        with mock.patch.object(p,'report',return_value=[]) as reader,mock.patch('os.geteuid',return_value=0):
            self.assertEqual(api_bridge.call({'name':'WMIGetHDDTemp','args':{}}),[]);reader.assert_called_once_with('all')
        with mock.patch.object(p,'report',side_effect=AssertionError('No read')):
            with self.assertRaises(ValueError):api_bridge.call({'name':'WMIGetHDDTemp','args':{'device':'/tmp/other'}})


if __name__=='__main__':unittest.main()
