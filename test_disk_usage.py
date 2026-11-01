# SPDX-License-Identifier: GPL-2.0-only
import copy
import errno
import os
import subprocess
from types import SimpleNamespace
import unittest
from unittest import mock
import api_bridge
import filesystem_usage as fs
import linux_services as services


def node(name,mounts=None,children=None,dev='8:1'):
    return {'name':name,'path':'/dev/'+name,'maj:min':dev,'type':'disk','rota':False,'rm':False,
            'size':1000,'mountpoints':mounts,'children':children or []}


def sample(blocks=100,free=60,available=50,unit=1):
    return SimpleNamespace(f_frsize=unit,f_blocks=blocks,f_bfree=free,f_bavail=available)


class FakeReader:
    def __init__(self,roots):
        self.table={};self.paths={};self.values={};self.fds={};self.closed=[];self.capacity_calls=[];self.sequence=1
        for root in roots:
            for n in fs.nodes([root]):
                for mount in n.get('mountpoints') or []:
                    if not mount or mount in self.paths:continue
                    ident=len(self.table)+10;self.paths[mount]=(ident,n['maj:min'],100+ident)
                    self.table[ident]={'device':n['maj:min'],'mount':mount,'record':('fixture',str(ident),mount)}
                    self.values[mount]=sample()
    def block(self,node):return node['name'],self.sequence
    def mounts(self):return copy.deepcopy(self.table)
    def open(self,mount):
        identity=self.paths[mount]
        if isinstance(identity,OSError):raise identity
        fd=len(self.fds)+100;self.fds[fd]=(mount,identity);return fd
    def close(self,fd):self.closed.append(fd)
    def identity(self,fd):return self.fds[fd][1]
    def capacity(self,fd):
        mount=self.fds[fd][0];self.capacity_calls.append(mount);value=self.values[mount]
        if isinstance(value,OSError):raise value
        return fs.capacity(value)


class DiskUsageTests(unittest.TestCase):
    def run_report(self,roots,reader=None,inventory=None,**kwargs):
        return fs.report('ssd',inventory or mock.Mock(return_value=roots),reader=reader or FakeReader(roots),**kwargs)

    def test_unreadable_mount_survives_beside_readable_sibling(self):
        roots=[node('nvme0n1',children=[node('nvme0n1p1',['/boot']),node('nvme0n1p2',['/'])])];r=FakeReader(roots)
        r.values['/boot']=OSError(errno.EACCES,'Permission denied');rows=self.run_report(roots,r)
        self.assertEqual([x['available'] for x in rows],[False,True]);self.assertEqual(rows[0]['errno'],errno.EACCES)
        self.assertNotIn('total',rows[0]);self.assertEqual(rows[1]['total'],100);self.assertTrue(rows[1]['identity_verified'])
        self.assertEqual(set(r.fds),set(r.closed))

    def test_disappeared_mount_is_typed_failure(self):
        roots=[node('sda',['/gone'])];r=FakeReader(roots);r.paths['/gone']=FileNotFoundError(errno.ENOENT,'Mount disappeared')
        row=self.run_report(roots,r)[0];self.assertFalse(row['available']);self.assertEqual(row['errno'],errno.ENOENT);self.assertNotIn('total',row)

    def test_unmounted_disk_is_distinct_from_no_selected_disks(self):
        roots=[node('sda',children=[node('sda1',[])])];r=FakeReader(roots);rows=self.run_report(roots,r)
        self.assertEqual(rows[0]['errno'],errno.ENODATA);self.assertIsNone(rows[0]['mount']);self.assertFalse(r.fds)
        self.assertEqual(self.run_report([]),[])

    def test_reserved_blocks_and_zero_capacity(self):
        self.assertEqual(fs.capacity(sample()),dict(total=100,used=40,free=50,percent=44.4))
        self.assertEqual(fs.capacity(sample(0,0,0)),dict(total=0,used=0,free=0,percent=0.0))
        self.assertEqual(fs.capacity(sample(unit=4096))['free'],50*4096)

    def test_invalid_capacity_keeps_valid_sibling_and_never_becomes_zero(self):
        for bad in [sample(blocks=True),sample(-1),sample(100,101),sample(100,60,61),sample(unit=0),sample(unit=float('nan')),sample(blocks=2**65),SimpleNamespace()]:
            with self.subTest(bad=bad):
                roots=[node('sda',['/bad','/good'])];r=FakeReader(roots);r.values['/bad']=bad
                rows=self.run_report(roots,r);self.assertEqual([x['available'] for x in rows],[False,True])
                self.assertEqual(rows[0]['errno'],errno.EPROTO);self.assertNotIn('free',rows[0])

    def test_shared_children_and_duplicate_mounts_are_counted_once(self):
        child=node('dm-0',['/','/']);roots=[node('sda',children=[child]),node('sdb',children=[child])];r=FakeReader(roots)
        self.assertEqual(len(self.run_report(roots,r)),1);self.assertEqual(r.capacity_calls,['/'])

    def test_api_names_use_native_provider_and_reject_unknown_args_before_read(self):
        for name,kind in [('WMIGetHDDUsage','hdd'),('WMIGetSSDUsage','ssd')]:
            roots=[node('sda',['/gone'])];r=FakeReader(roots);r.values['/gone']=OSError(errno.ESTALE,'Stale mount')
            with self.subTest(name=name),mock.patch.object(services,'drives',return_value=roots) as inventory,mock.patch.object(fs,'Reader',return_value=r):
                row=api_bridge.call({'name':name})[0];self.assertEqual(row['errno'],errno.ESTALE)
                self.assertEqual(inventory.call_count,2);self.assertTrue(all(c.args==(kind,) for c in inventory.call_args_list))
                with self.assertRaises(ValueError):api_bridge.call({'name':name,'args':{'invented_filter':True}})
                self.assertEqual(inventory.call_count,2)

    def test_failed_census_is_not_an_empty_list(self):
        with mock.patch.object(services,'drives',side_effect=OSError(errno.EIO,'Inventory failed')):
            with self.assertRaises(OSError):services.disk_usage('ssd')

    def test_unmounted_path_falling_through_to_parent_never_reads_parent_capacity(self):
        roots=[node('sda',['/gone'])];r=FakeReader(roots);r.paths['/gone']=(42,'8:2',999)
        r.table[42]={'mount':'/','device':'8:2','record':('parent',)}
        row=self.run_report(roots,r)[0];self.assertEqual(row['errno'],errno.EAGAIN);self.assertNotIn('total',row);self.assertFalse(r.capacity_calls)

    def test_wrong_device_at_same_mount_path_is_rejected(self):
        roots=[node('sda',['/mounted'])];r=FakeReader(roots);r.paths['/mounted']=(10,'8:2',110)
        r.table[10]['device']='8:2';row=self.run_report(roots,r)[0]
        self.assertEqual(row['errno'],errno.EAGAIN);self.assertFalse(r.capacity_calls)

    def test_same_device_overmount_with_new_mount_id_invalidates_result(self):
        roots=[node('sda',['/mounted'])];r=FakeReader(roots);read=r.capacity
        def overmount(fd):value=read(fd);r.paths['/mounted']=(20,'8:1',110);return value
        r.capacity=overmount;row=self.run_report(roots,r)[0]
        self.assertEqual(row['errno'],errno.EAGAIN);self.assertNotIn('total',row);self.assertEqual(set(r.fds),set(r.closed))

    def test_detached_mount_kept_alive_by_fd_is_not_published(self):
        roots=[node('sda',['/mounted'])];r=FakeReader(roots);read=r.capacity
        def detach(fd):value=read(fd);r.table={};return value
        r.capacity=detach;row=self.run_report(roots,r)[0];self.assertEqual(row['errno'],errno.EAGAIN);self.assertNotIn('mount_id',row)

    def test_same_id_mount_option_or_root_change_invalidates_value(self):
        roots=[node('sda',['/mounted'])];r=FakeReader(roots);read=r.capacity
        def change(fd):value=read(fd);r.table[10]['record']=('changed-root-or-options',);return value
        r.capacity=change;self.assertEqual(self.run_report(roots,r)[0]['errno'],errno.EAGAIN)

    def test_mount_path_replacement_inode_is_rejected(self):
        roots=[node('sda',['/mounted'])];r=FakeReader(roots);read=r.capacity
        def replace(fd):value=read(fd);r.paths['/mounted']=(10,'8:1',111);return value
        r.capacity=replace;self.assertEqual(self.run_report(roots,r)[0]['errno'],errno.EAGAIN)

    def test_reused_block_device_number_with_new_generation_is_rejected(self):
        roots=[node('sda',['/mounted'])];r=FakeReader(roots);read=r.capacity
        def replace(fd):value=read(fd);r.sequence+=1;return value
        r.capacity=replace
        with self.assertRaises(OSError) as caught:self.run_report(roots,r)
        self.assertEqual(caught.exception.errno,errno.EAGAIN);self.assertEqual(set(r.fds),set(r.closed))

    def test_changed_inventory_is_not_published_and_fds_are_closed(self):
        roots=[node('sda',['/mounted'])];r=FakeReader(roots)
        with self.assertRaises(OSError) as caught:self.run_report(roots,r,mock.Mock(side_effect=[roots,[]]))
        self.assertEqual(caught.exception.errno,errno.EAGAIN);self.assertEqual(set(r.fds),set(r.closed))

    def test_deadline_during_capacity_read_never_publishes_late_value(self):
        roots=[node('sda',['/mounted'])];r=FakeReader(roots);read=r.capacity;now=[0]
        def late(fd):value=read(fd);now[0]=9;return value
        r.capacity=late
        with self.assertRaises(OSError) as caught:self.run_report(roots,r,clock=lambda:now[0])
        self.assertEqual(caught.exception.errno,errno.ETIMEDOUT);self.assertEqual(set(r.fds),set(r.closed))

    def test_mountinfo_escapes_bind_roots_and_unknown_optional_fields(self):
        raw=r'10 1 8:1 /sub\040dir /mount\134name rw future:yes - ext4 /dev/sda rw'+'\n'
        result=fs.mount_table(raw);self.assertEqual(result[10]['mount'],'/mount\\name');self.assertEqual(result[10]['device'],'8:1')

    def test_bad_mountinfo_is_not_a_known_empty_mount_table(self):
        valid='10 1 8:1 / / rw - ext4 /dev/sda rw\n'
        for raw in [valid*2,valid.replace('8:1','bad'),valid.replace('/ /','/ /bad\\001'),valid.replace(' - ',' '),valid.replace('10 1','0 1')]:
            with self.subTest(raw=raw),self.assertRaises(OSError):fs.mount_table(raw)

    def test_unrelated_namespace_file_mount_does_not_invalidate_disk_census(self):
        table=fs.mount_table('10 1 0:4 mnt:[12345] /run/example.mnt rw - nsfs nsfs rw\n')
        self.assertEqual(table[10]['mount'],'/run/example.mnt')

    def test_mapper_paths_are_supported_without_guessing_name_equals_path(self):
        roots=[node('sda',children=[node('crypt',['/'])])];roots[0]['children'][0]['path']='/dev/mapper/crypt'
        row=self.run_report(roots)[0];self.assertEqual(row['path'],'/dev/mapper/crypt');self.assertTrue(row['available'])

    def test_invalid_mount_inventory_is_rejected_before_filesystem_reads(self):
        for change in [('mountpoints',['relative']),('maj:min','invalid'),('path','/dev/../etc/passwd'),('children','bad')]:
            roots=[node('sda',['/mounted'])];roots[0][change[0]]=change[1]
            with self.subTest(change=change),self.assertRaises(OSError):fs.nodes(roots)

    def test_opened_descriptor_identity_uses_kernel_mount_id_and_device(self):
        r=fs.Reader();info=SimpleNamespace(st_dev=os.makedev(8,1),st_ino=100)
        with mock.patch.object(r,'text',return_value='pos:\t0\nmnt_id:\t21\nino:\t100\n'),mock.patch.object(fs.os,'fstat',return_value=info):
            self.assertEqual(r.identity(5),(21,'8:1',100))
        with mock.patch.object(r,'text',return_value='mnt_id: 1\nmnt_id: 2\n'),self.assertRaises(OSError):r.identity(5)

    def test_inventory_timeout_is_typed_and_cleans_up_pinned_descriptors(self):
        roots=[node('sda',['/mounted'])];r=FakeReader(roots)
        inventory=mock.Mock(side_effect=[roots,subprocess.TimeoutExpired('lsblk',1)])
        with self.assertRaises(OSError) as caught:self.run_report(roots,r,inventory)
        self.assertEqual(caught.exception.errno,errno.ETIMEDOUT);self.assertEqual(set(r.fds),set(r.closed))

    def test_kernel_block_guard_rejects_changed_metadata_and_identity(self):
        n=node('sda');ident=(1,2,'/sys/physical/sda','/sys/physical','8:1');r=fs.Reader()
        values={'available':True,'size':1000,'rotational':False,'removable':False}
        with mock.patch.object(fs.storage,'identity',return_value=ident),mock.patch.object(fs.storage,'number',return_value=123),mock.patch.object(fs.storage,'sample',return_value=values):
            self.assertEqual(r.block(n),(ident,123))
            for bad in [values|{'size':None},values|{'rotational':True}]:
                with mock.patch.object(fs.storage,'sample',return_value=bad),self.assertRaises(OSError):r.block(n)
            with mock.patch.object(fs.storage,'identity',side_effect=[ident,(1,3,*ident[2:])]),self.assertRaises(OSError):r.block(n)
            with mock.patch.object(fs.storage,'number',side_effect=FileNotFoundError()),self.assertRaises(OSError) as caught:r.block(n)
            self.assertEqual(caught.exception.errno,errno.EOPNOTSUPP)


if __name__=='__main__':unittest.main()
