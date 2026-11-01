# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import errno
import os
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock
import compat
import driver_package as package


class InstalledDriverTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);root=Path(self.temp.name)
        self.device=root/'devices/asus-nb-wmi';self.driver=root/'drivers/asus-nb-wmi';self.modules=root/'sys-module'
        self.module=self.modules/'asus_wmi';self.tree=root/'kernel-tree';self.kernel='6.8-test'
        for path in (self.device,self.driver,self.module):path.mkdir(parents=True)
        (self.device/'driver').symlink_to(self.driver);(self.driver/'module').symlink_to(self.module)
        self.file=self.tree/self.kernel/'kernel/asus-wmi.ko.zst';self.file.parent.mkdir(parents=True);self.file.write_bytes(b'module-fixture')
        self.fields={'name':'asus_wmi','version':'','intree':'Y','vermagic':self.kernel+' SMP preempt mod_unload'}
        for name,value in (('DEVICE',self.device),('MODULES',self.modules),('MODULE_TREE',self.tree)):
            patch=mock.patch.object(package,name,value);patch.start();self.addCleanup(patch.stop)
        patch=mock.patch.object(package.os,'uname',return_value=SimpleNamespace(release=self.kernel));patch.start();self.addCleanup(patch.stop)
    def run_info(self,args,**kwargs):
        self.assertEqual(args[:3],[package.MODINFO,'-k',self.kernel]);self.assertEqual(set(kwargs['env']),{'PATH','LC_ALL'})
        field=args[4]
        if field=='filename':self.assertEqual(args[5],'asus_wmi');value=str(self.file)
        else:self.assertEqual(args[5],str(self.file));value=self.fields[field]
        return SimpleNamespace(returncode=0,stdout=value+'\n')
    def report(self):
        with mock.patch.object(package.subprocess,'run',side_effect=self.run_info):return package.report()
    def test_actual_bound_module_and_intree_kernel_version_replace_frontend_constant(self):
        result=self.report();self.assertEqual(result['module'],'asus_wmi');self.assertEqual(result['driver'],'asus-nb-wmi')
        self.assertEqual(result['version'],self.kernel);self.assertEqual(result['version_kind'],'kernel_release')
        self.assertIsNone(result['declared_module_version']);self.assertNotEqual(result['version'],compat.VERSION)
        with mock.patch.object(package.subprocess,'run',side_effect=self.run_info):self.assertEqual(compat.lifecycle('GetInfVersion',{}),result)
    def test_declared_module_version_is_separate_from_kernel_and_frontend(self):
        self.fields.update(version='4.5.6',intree='');result=self.report()
        self.assertEqual(result['version'],'4.5.6');self.assertEqual(result['version_kind'],'declared_module_version')
        self.assertEqual(result['kernel_release'],self.kernel);self.assertFalse(result['in_tree'])
    def test_missing_out_of_tree_version_is_not_filled_with_frontend_or_kernel(self):
        self.fields['intree']=''
        with self.assertRaises(OSError) as caught:self.report()
        self.assertEqual(caught.exception.errno,errno.ENODATA)
    def test_module_identity_kernel_and_version_errors_are_retained(self):
        for field,value in (('name','asus_nb_wmi'),('vermagic','other-kernel SMP'),('version','bad version'),('intree','N')):
            previous=self.fields[field];self.fields[field]=value
            with self.subTest(field=field),self.assertRaises(OSError) as caught:self.report()
            self.assertEqual(caught.exception.errno,errno.EPROTO);self.fields[field]=previous
    def test_missing_binding_never_returns_a_version_constant(self):
        (self.device/'driver').unlink()
        with mock.patch.object(package.subprocess,'run') as run,self.assertRaises(FileNotFoundError):package.report()
        run.assert_not_called()
    def test_module_replacement_during_query_invalidates_all_fields(self):
        def replace(args,**kwargs):
            result=self.run_info(args,**kwargs)
            if args[4]=='version':self.file.write_bytes(b'replaced-module')
            return result
        with mock.patch.object(package.subprocess,'run',side_effect=replace),self.assertRaises(OSError) as caught:package.report()
        self.assertEqual(caught.exception.errno,errno.EAGAIN)
    def test_binding_replacement_during_query_is_not_mixed_with_old_metadata(self):
        other=self.modules/'other_asus';other.mkdir()
        def replace(args,**kwargs):
            result=self.run_info(args,**kwargs)
            if args[4]=='version':(self.driver/'module').unlink();(self.driver/'module').symlink_to(other)
            return result
        with mock.patch.object(package.subprocess,'run',side_effect=replace),self.assertRaises(OSError) as caught:package.report()
        self.assertEqual(caught.exception.errno,errno.EAGAIN)
    def test_current_kernel_tree_and_regular_file_are_required(self):
        other=self.tree.parent/'outside.ko';other.write_bytes(b'other')
        self.file=other
        with self.assertRaises(OSError) as caught:self.report()
        self.assertEqual(caught.exception.errno,errno.EPROTO)
    def test_metadata_failure_timeout_and_builtin_are_explicit(self):
        for response,code in ((SimpleNamespace(returncode=1,stdout=''),errno.ENODATA),
                              (SimpleNamespace(returncode=0,stdout='(builtin)\n'),errno.ENODATA),
                              (SimpleNamespace(returncode=0,stdout='x'*4097),errno.EPROTO)):
            with mock.patch.object(package.subprocess,'run',return_value=response),self.assertRaises(OSError) as caught:package.report()
            self.assertEqual(caught.exception.errno,code)
        with mock.patch.object(package.subprocess,'run',side_effect=subprocess.TimeoutExpired('modinfo',3)),self.assertRaises(OSError) as caught:package.report()
        self.assertEqual(caught.exception.errno,errno.ETIMEDOUT)

if __name__=='__main__':unittest.main()
