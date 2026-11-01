# SPDX-License-Identifier: GPL-2.0-only
import errno
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import api_bridge
import linux_services
import storage_inventory as p


def disk(root,name,rotational=0,removable=0,sectors=2048,model='Example disk',bus='scsi',card=None):
    path=root/name;(path/'queue').mkdir(parents=True);(path/'device').mkdir()
    fields={'dev':str(8+len(list(root.iterdir())))+':0','size':str(sectors),
            'removable':str(removable),'queue/rotational':str(rotational),'device/model':model}
    if bus=='scsi':fields['device/type']='0'
    if bus=='mmc':fields['device/type']=card or 'SD'
    for name,value in fields.items():(path/name).write_text(value+'\n')
    target=root.parent/'bus'/bus;target.mkdir(parents=True,exist_ok=True);(path/'device/subsystem').symlink_to(target)
    return path


def call(name,rows,args=None):
    with mock.patch.object(p,'report',return_value=rows):return api_bridge.call({'name':name,'args':args or {}})


class StorageInventoryTests(unittest.TestCase):
    def test_SD_details_preserve_each_matching_card_without_losing_scalar_total(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'block';root.mkdir()
            disk(root,'mmcblk0',0,1,100,'Example SD','mmc','SD');disk(root,'sda',0,1,200,'Example SDHC CARD')
            rows=p.report(root)
        detail=call('WMIGetSDCardSize',rows,{'detailed':True})
        self.assertEqual(detail['total_bytes'],300*512);self.assertEqual([r['bytes'] for r in detail['cards']],[100*512,200*512])
        self.assertEqual(call('WMIGetSDCardSize',rows),300*512)
        for args in [{'detailed':1},{'detailed':None},{'detailed':'true'},{'index':0}]:
            with self.assertRaises(ValueError):call('WMIGetSDCardSize',rows,args)

    def test_original_caption_and_info_routes_have_different_media_selections(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'block';root.mkdir()
            disk(root,'sda',1,0,100,'HDD caption');disk(root,'nvme0n1',0,0,200,'SSD caption','nvme')
            disk(root,'sdb',0,1,300,'Removable reader');rows=p.report(root)
        self.assertEqual(call('WMIGetHDDCaption',rows),['SSD caption','HDD caption'])
        info=call('WMIGetHDDInfo',rows)
        self.assertEqual([(r['model'],r['size']) for r in info],[('HDD caption',100*512)])
        self.assertTrue(info[0]['rotational'])

    def test_caption_and_info_failures_remain_typed_instead_of_dispatch_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'block';root.mkdir();d=disk(root,'sda',1,0,100)
            (d/'device/model').unlink();rows=p.report(root)
        with self.assertRaises(OSError) as caught:call('WMIGetHDDCaption',rows)
        self.assertEqual(caught.exception.errno,errno.ENODATA)
        info=call('WMIGetHDDInfo',rows)
        self.assertIsNone(info[0]['model']);self.assertIn('model',info[0]['field_errors'])
        for name in ['WMIGetHDDCaption','WMIGetHDDInfo']:
            with mock.patch.object(p,'report',side_effect=AssertionError('Unexpected read')),self.assertRaises(ValueError):
                api_bridge.call({'name':name,'args':{'index':0}})

    def test_original_distinct_fixed_rotating_nonrotating_and_removable_selections(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'block';root.mkdir()
            disk(root,'sda',1,0,100,'Example HDD');disk(root,'nvme0n1',0,0,200,'Example SSD','nvme')
            disk(root,'sdb',0,1,300,'Example USB flash');rows=p.report(root)
        self.assertEqual([x['device'] for x in call('WMIGetHDDList',rows)],['sda'])
        self.assertEqual(call('WMIGetHDDModel',rows),['Example HDD'])
        self.assertEqual([x['device'] for x in call('WMIGetSSDList',rows)],['nvme0n1'])
        self.assertEqual(call('WMIGetSSDModel',rows),['Example SSD'])
        self.assertEqual(call('WMIGetHDDSize',rows),300*512)
        self.assertEqual(call('WMIGetSDCardCaption',rows),['Example USB flash'])
        self.assertEqual(call('WMIGetSDCardSize',rows),0)
        self.assertEqual([x['device'] for x in call('WMIGetPhysicalDiskInfo',rows)],['nvme0n1','sda'])

    def test_explicit_sd_type_excludes_emmc_and_preserves_nonremovable_sd(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'block';root.mkdir()
            disk(root,'mmcblk0',0,0,100,'eMMC part','mmc','MMC')
            disk(root,'mmcblk1',0,1,200,'Native SD part','mmc','SD')
            disk(root,'mmcblk2',0,0,300,'Embedded SD part','mmc','SDcombo')
            rows=p.report(root)
        self.assertEqual(call('WMIGetSDCardCaption',rows),['Native SD part'])
        self.assertEqual(call('WMIGetSDCardSize',rows),500*512)
        self.assertEqual([x['device'] for x in call('WMIGetSSDList',rows)],['mmcblk0'])

    def test_original_sd_caption_substrings_are_case_insensitive_and_removable_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'block';root.mkdir()
            for i,model in enumerate(['Reader SD Card','reader sdhc CARD','READER SDXC CARD','Generic reader']):disk(root,'sd'+chr(97+i),0,1,100,model)
            disk(root,'sde',0,0,100,'Fixed SD CARD named disk');rows=p.report(root)
        self.assertEqual(call('WMIGetSDCardSize',rows),300*512)
        self.assertEqual(len(call('WMIGetSDCardCaption',rows)),4)

    def test_zero_sectors_remain_kernel_zero_not_an_unknown_measurement(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'block';root.mkdir();disk(root,'sda',0,1,0,'SD CARD reader');rows=p.report(root)
        self.assertEqual(rows[0]['size'],0);self.assertEqual(call('WMIGetSDCardSize',rows),0)
        self.assertIn('512-byte sector',rows[0]['source'])

    def test_logical_sector_size_does_not_change_kernel_capacity_units(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'block';root.mkdir();d=disk(root,'sda',1,0,123)
            (d/'queue/logical_block_size').write_text('4096\n');rows=p.report(root)
        self.assertEqual(call('WMIGetHDDSize',rows),123*512)

    def test_virtual_partition_and_mmc_subarea_nodes_do_not_double_count(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'block';root.mkdir();disk(root,'mmcblk0',0,0,100,bus='mmc',card='MMC')
            disk(root,'mmcblk0boot0',0,0,50,bus='mmc',card='MMC');disk(root,'mmcblk0rpmb',0,0,50,bus='mmc',card='MMC')
            partition=disk(root,'mmcblk0p1',0,0,50,bus='mmc',card='MMC');(partition/'partition').write_text('1\n')
            (root/'zram0').mkdir();(root/'loop0').mkdir();rows=p.report(root)
        self.assertEqual([r['device'] for r in rows],['mmcblk0']);self.assertEqual(call('WMIGetHDDSize',rows),100*512)

    def test_optical_and_other_scsi_types_are_not_disk_inventory(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'block';root.mkdir();d=disk(root,'sr0',1,1);(d/'device/type').write_text('5\n');rows=p.report(root)
        for name in ['WMIGetHDDList','WMIGetSSDList','WMIGetPhysicalDiskInfo','WMIGetSDCardCaption']:self.assertEqual(call(name,rows),[])
        self.assertEqual(call('WMIGetSDCardSize',rows),0)

    def test_bad_size_withholds_total_without_erasing_known_model_or_membership(self):
        for value in ['-1','invalid',str(2**64),'1.5']:
            with self.subTest(value=value),tempfile.TemporaryDirectory() as temp:
                root=Path(temp)/'block';root.mkdir();bad=disk(root,'sda',1);disk(root,'sdb',1)
                (bad/'size').write_text(value);rows=p.report(root)
            self.assertIsNone(rows[0]['size']);self.assertEqual(len(call('WMIGetHDDList',rows)),2)
            self.assertEqual(len(call('WMIGetHDDModel',rows)),2)
            with self.assertRaises(OSError) as caught:call('WMIGetHDDSize',rows)
            self.assertEqual(caught.exception.errno,errno.ENODATA)

    def test_bad_classification_never_silently_omits_a_possible_target(self):
        for field,value,name in [('queue/rotational','2','WMIGetHDDList'),('removable','?','WMIGetHDDSize'),
                                 ('queue/rotational','?','WMIGetSSDList'),('device/type','?','WMIGetSDCardCaption')]:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as temp:
                root=Path(temp)/'block';root.mkdir();d=disk(root,'sda');(d/field).write_text(value);rows=p.report(root)
            with self.assertRaises(OSError):call(name,rows)
            info=call('WMIGetPhysicalDiskInfo',rows);self.assertIsNone(info[0]['matches_physical_media'])
            self.assertTrue(info[0]['field_errors'])

    def test_model_or_caption_failure_is_not_a_null_success_list(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'block';root.mkdir();d=disk(root,'sda',1,1);(d/'device/model').write_bytes(b'bad\xffmodel');rows=p.report(root)
        self.assertIsNone(rows[0]['model']);self.assertEqual(rows[0]['field_errors']['model']['errno'],errno.EPROTO)
        for name in ['WMIGetHDDModel','WMIGetSDCardCaption','WMIGetSDCardSize']:
            with self.assertRaises(OSError):call(name,rows)

    def test_missing_identity_is_retained_and_prevents_empty_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'block';root.mkdir();d=disk(root,'sda');(d/'dev').unlink();rows=p.report(root)
        self.assertFalse(rows[0]['available']);self.assertIsNone(call('WMIGetPhysicalDiskInfo',rows)[0]['matches_physical_media'])
        for name in p.NAMES-{'WMIGetPhysicalDiskInfo'}:
            with self.assertRaises(OSError):call(name,rows)

    def test_unreadable_mmc_type_or_bus_does_not_become_false_sd_or_ssd(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'block';root.mkdir();d=disk(root,'mmcblk0',0,0,bus='mmc',card='SD')
            (d/'device/type').unlink();rows=p.report(root)
            for name in ['WMIGetSDCardSize','WMIGetHDDList','WMIGetSSDList']:
                with self.assertRaises(OSError):call(name,rows)
            (d/'device/subsystem').unlink();rows=p.report(root)
        for name in p.NAMES-{'WMIGetPhysicalDiskInfo'}:
            with self.assertRaises(OSError):call(name,rows)

    def test_duplicate_dev_t_is_not_double_counted(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'block';root.mkdir();a=disk(root,'sda',1);b=disk(root,'sdb',1)
            (b/'dev').write_bytes((a/'dev').read_bytes());rows=p.report(root)
        self.assertTrue(all(not r['available'] for r in rows))
        with self.assertRaises(OSError):call('WMIGetHDDSize',rows)

    def test_reused_node_or_metadata_change_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'block';root.mkdir();d=disk(root,'sda');first=p.sample(d);second={**first,'size':4096}
            with mock.patch.object(p,'sample',side_effect=[first,second]):rows=p.report(root)
        self.assertFalse(rows[0]['available']);self.assertEqual(rows[0]['errno'],errno.EAGAIN)

    def test_hotplug_census_change_is_not_partial_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'block';root.mkdir();d=disk(root,'sda')
            with mock.patch.object(p,'paths',side_effect=[[d],[]]),self.assertRaises(OSError) as caught:p.report(root)
        self.assertEqual(caught.exception.errno,errno.EAGAIN)

    def test_empty_known_census_is_distinct_from_failed_census(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'block';root.mkdir();rows=p.report(root)
            with self.assertRaises(OSError):p.report(root/'missing')
        self.assertEqual(call('WMIGetHDDSize',rows),0);self.assertEqual(call('WMIGetHDDList',rows),[])

    def test_all_eight_original_queries_reject_arguments_before_io(self):
        with mock.patch.object(p,'report',side_effect=AssertionError('unexpected I/O')):
            for name in p.NAMES:
                with self.assertRaises(ValueError):api_bridge.call({'name':name,'args':{'invented':True}})
                with self.assertRaises(ValueError):linux_services.call(name,{'invented':True})

    def test_filesystem_mount_trees_use_verified_classification(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'block';root.mkdir();disk(root,'sda',1);disk(root,'sdb',0);rows=p.report(root)
        trees=[{'name':r['device'],'path':r['path'],'type':'disk','rota':r['rotational'],'rm':r['removable'],
                'size':r['size'],'children':[{'path':r['path']+'1','mountpoints':['/example']}]} for r in rows]
        with mock.patch.object(p,'report',return_value=rows),mock.patch.object(linux_services,'storage',return_value=trees):
            self.assertEqual(linux_services.drives('hdd'),trees[:1]);self.assertEqual(linux_services.drives('ssd'),trees[1:])

    def test_stale_or_missing_mount_tree_cannot_drop_selected_disk(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'block';root.mkdir();disk(root,'sda',1);rows=p.report(root)
        original={'name':'sda','path':'/dev/sda','type':'disk','rota':True,'rm':False,'size':rows[0]['size']}
        bad=[[],[original,original],*[ [{**original,key:value}] for key,value in
              [('path','/dev/reused'),('rota',False),('rm',1),('size',None),('size',1)] ]]
        for tree in bad:
            with self.subTest(tree=tree),mock.patch.object(p,'report',return_value=rows),mock.patch.object(linux_services,'storage',return_value=tree),self.assertRaises(OSError) as caught:
                linux_services.drives('hdd')
            self.assertEqual(caught.exception.errno,errno.EAGAIN)

    def test_failed_classification_prevents_mount_query_and_partial_success(self):
        with mock.patch.object(p,'report',side_effect=OSError(errno.EACCES,'Kernel census denied')),mock.patch.object(linux_services,'storage') as tree:
            with self.assertRaises(OSError):linux_services.drives('hdd')
        tree.assert_not_called()


if __name__=='__main__':unittest.main()
