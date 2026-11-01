# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import errno
import tempfile
import unittest
from unittest import mock
import compat
import disk_activity as activity
import linux_services


class DiskActivityTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.base=Path(temp.name)
        self.root=self.base/'block';self.root.mkdir();self.bus=self.base/'scsi';self.bus.mkdir()
        self.disk('sda','8:0');self.partition('sda','sda1','8:1');self.disk('sdb','8:16')
    def disk(self,name,device):
        p=self.base/'devices'/name;(p/'device').mkdir(parents=True);(p/'queue').mkdir()
        (p/'device/subsystem').symlink_to(self.bus,target_is_directory=True)
        for path,value in [('device/model','Test disk'),('device/type','0'),('queue/rotational','0'),('size','2048'),('removable','0'),('dev',device)]:
            (p/path).write_text(value)
        (self.root/name).symlink_to(p,target_is_directory=True);self.counts(name)
        return p
    def partition(self,parent,name,device):
        p=(self.root/parent).resolve()/name;p.mkdir();(p/'partition').write_text('1');(p/'dev').write_text(device)
        (self.root/name).symlink_to(p,target_is_directory=True)
    def counts(self,name,busy=0,weighted=0):
        values=[0]*17;values[9]=busy;values[10]=weighted
        (self.root/name/'stat').write_text(' '.join(map(str,values)))
    def sample(self,change,elapsed=500_000_000,boot_elapsed=None):
        def pause(seconds):self.assertEqual(seconds,.25);change()
        times=iter([10_000_000_000]*2+[10_000_000_000+elapsed]*2)
        boots=iter([100_000_000_000]*2+[100_000_000_000+(elapsed if boot_elapsed is None else boot_elapsed)]*2)
        return activity.report(self.root,(8,1),lambda:next(times),lambda:next(boots),pause)
    def test_original_threshold_is_truncated_weighted_time_and_root_is_excluded(self):
        for weighted,wanted in [(100,False),(102,False),(104,False),(105,True),(1000,True)]:
            self.counts('sda');self.counts('sdb')
            r=self.sample(lambda:(self.counts('sda',500,10000),self.counts('sdb',50,weighted)))
            self.assertEqual(r['active'],wanted);self.assertTrue(r['available'])
            root,other=r['disks'];self.assertFalse(root['eligible']);self.assertFalse(root['over_threshold'])
            self.assertEqual(other['activity_percent_integer'],weighted//5);self.assertEqual(other['busy_percent'],10)
            self.assertEqual(r['sample_seconds'],.5)
    def test_idle_is_real_zero_and_partial_or_reset_counter_is_not_false(self):
        self.assertFalse(self.sample(lambda:None)['active'])
        self.counts('sdb',20,100)
        r=self.sample(lambda:self.counts('sdb',0,0));self.assertIsNone(r['active']);self.assertFalse(r['available'])
        self.assertEqual(r['disks'][1]['errno'],errno.ENODATA)
        (self.root/'sdb/stat').write_text('bad')
        self.assertIsNone(self.sample(lambda:None)['active'])
        self.counts('sdb');(self.root/'sda/stat').write_text('bad')
        r=self.sample(lambda:None);self.assertFalse(r['active']);self.assertTrue(r['available']);self.assertFalse(r['disks'][0]['available'])
    def test_positive_disk_remains_true_with_another_unknown_disk(self):
        self.disk('sdc','8:32');(self.root/'sdc/stat').write_text('bad')
        r=self.sample(lambda:self.counts('sdb',250,500))
        self.assertTrue(r['active']);self.assertFalse(r['available']);self.assertEqual(r['disks_over_threshold'],1)
    def test_no_guess_for_nonblock_root_suspend_delayed_or_reset_samples(self):
        with self.assertRaises(OSError) as caught:activity.system_disks(self.root,(0,99))
        self.assertEqual(caught.exception.errno,errno.ENODATA)
        for elapsed,boot in [(1,1),(6_000_000_000,6_000_000_000),(500_000_000,1_500_000_000)]:
            with self.assertRaises(OSError) as caught:self.sample(lambda:None,elapsed,boot)
            self.assertEqual(caught.exception.errno,errno.ESTALE)
    def test_nested_device_mapper_and_shared_backing_disk_and_cycles(self):
        for name,dev in [('dm-0','253:0'),('dm-1','253:1'),('dm-2','253:2')]:
            p=self.base/'devices'/name;(p/'slaves').mkdir(parents=True);(p/'dev').write_text(dev)
            (self.root/name).symlink_to(p,target_is_directory=True)
        for parent,child in [('dm-0','dm-1'),('dm-0','dm-2'),('dm-1','sda1'),('dm-2','sda1')]:
            (self.root/parent/'slaves'/child).symlink_to(self.root/child,target_is_directory=True)
        self.assertEqual(activity.system_disks(self.root,(253,0)),{'8:0'})
        (self.root/'dm-1/slaves/sda1').unlink();(self.root/'dm-1/slaves/dm-0').symlink_to(self.root/'dm-0',target_is_directory=True)
        with self.assertRaises(OSError) as caught:activity.system_disks(self.root,(253,0))
        self.assertEqual(caught.exception.errno,errno.ELOOP)
    def test_reused_or_hotplugged_disk_never_contributes_false_activity(self):
        r=self.sample(lambda:(self.root/'sdb/dev').write_text('8:48'))
        self.assertIsNone(r['active']);self.assertEqual(r['disks'][1]['errno'],errno.EAGAIN)
        (self.root/'sdb/dev').write_text('8:16')
        r=self.sample(lambda:self.disk('sdc','8:32'))
        self.assertIsNone(r['active']);self.assertEqual(r['disks'][-1]['errno'],errno.EAGAIN)
    def test_metric_selection_keeps_real_USB_data_available_and_validates_before_elevation(self):
        with mock.patch.object(activity,'report',return_value={'active':False}) as report,mock.patch('usb_activity.sample',return_value={'bytes':42}) as usb:
            self.assertEqual(linux_services.call('RF_USBIsTranster',{}),{'active':False})
            self.assertEqual(linux_services.call('RF_USBIsTranster',{'metric':'usb_traffic'}),{'bytes':42})
            report.assert_called_once();usb.assert_called_once()
        for args in [{},{'metric':'disk_activity'}]:
            compat.validate('RF_USBIsTranster',args);self.assertFalse(compat.needs_root('RF_USBIsTranster',args))
        compat.validate('RF_USBIsTranster',{'metric':'usb_traffic'})
        self.assertTrue(compat.needs_root('RF_USBIsTranster',{'metric':'usb_traffic'}))
        for args in [{'metric':True},{'metric':'disk'}, {'metric':None},{'capture':True}]:
            with self.assertRaises(ValueError):compat.validate('RF_USBIsTranster',args)
            with self.assertRaises(ValueError):linux_services.call('RF_USBIsTranster',args)

if __name__=='__main__':unittest.main()
