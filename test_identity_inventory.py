# SPDX-License-Identifier: GPL-2.0-only
import errno
from pathlib import Path
from types import SimpleNamespace
import subprocess
import tempfile
import unittest
from unittest import mock
import api_bridge
import identity_inventory as identity


PCI='0000:00:02.0 "VGA compatible controller [0300]" "Example Vendor [1234]" "Graphics [Model] [abcd]" -r04 -p00 "" ""\n'


class IdentityInventoryTests(unittest.TestCase):
    def pci(self,root,address='0000:00:02.0',kind='0x030000',vendor='0x1234',device='0xabcd'):
        path=root/address;path.mkdir()
        for name,value in [('class',kind),('vendor',vendor),('device',device)]:
            (path/name).write_text(value+'\n')
        return path

    def test_exact_firmware_source_selections_do_not_alias_model_or_vendor(self):
        values={'board_vendor':'Board maker','sys_vendor':'System maker','board_name':'Baseboard',
                'product_name':'System product','product_family':'System family',
                'bios_version':'Firmware1','bios_date':'02/29/2024'}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name,value in values.items():(root/name).write_text(value+'\n')
            expected={'WMIGetBiosManufacture':'Board maker','WMIGetModelName':'Baseboard',
                      'WMIGetProductName':'System product','WMIGetComputerFamilyName':'System family',
                      'WMIGetBiosVersion':'Firmware1','WMIGetBiosReleaseDate':'2024-02-29'}
            for name,value in expected.items():
                with self.subTest(name=name):self.assertEqual(identity.firmware(name,root),value)
            (root/'board_name').unlink()
            with self.assertRaises(FileNotFoundError):identity.firmware('WMIGetModelName',root)

    def test_invalid_missing_denied_and_placeholder_fields_are_not_substituted(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'product_family'
            for value in ['','Unknown','To be filled by O.E.M.','System Product Name','Bad\x00field']:
                path.write_text(value)
                with self.subTest(value=value),self.assertRaises(OSError):identity.firmware('WMIGetComputerFamilyName',root)
            with mock.patch.object(identity,'text',side_effect=PermissionError(errno.EACCES,'Denied')),self.assertRaises(OSError) as error:
                identity.firmware('WMIGetComputerFamilyName',root)
            self.assertEqual(error.exception.errno,errno.EACCES)

    def test_bios_calendar_date_requires_real_complete_date(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for value in ['02/29/2023','05/11/23','2023-05-11','13/01/2023','05/00/2023']:
                (root/'bios_date').write_text(value)
                with self.subTest(value=value),self.assertRaises(OSError) as error:identity.firmware('WMIGetBiosReleaseDate',root)
                self.assertEqual(error.exception.errno,errno.EPROTO)

    def test_os_assignments_are_decoded_without_expansion_or_execution(self):
        raw=b'''NAME=Example
PRETTY_NAME="Example \\"Quoted\\" \\$literal \\`literal\\`"
VERSION_ID='1.2'
ID=example-os
BUILD_ID=123
IGNORED=$(never-execute)
'''
        values,errors=identity.decode_os_release(raw)
        self.assertEqual(errors,0);self.assertEqual(values['PRETTY_NAME'],'Example "Quoted" $literal `literal`')
        self.assertEqual(values['VERSION_ID'],'1.2');self.assertNotIn('IGNORED',values)
        for invalid in ['"unterminated','"a""b"','"$expand"','"`command`"','$(command)','bad value','"bad\\"']:
            with self.subTest(invalid=invalid):
                fields,errors=identity.decode_os_release(('NAME='+invalid+'\nVERSION_ID=1\n').encode())
                self.assertIsNone(fields['NAME']);self.assertEqual(fields['VERSION_ID'],'1');self.assertGreater(errors,0)

    def test_os_duplicates_use_last_value_and_malformed_selected_fields_stay_unknown(self):
        values,errors=identity.decode_os_release(b'NAME=Old\nNAME="New OS"\nVERSION_ID=1\nVERSION_ID="bad\nID="Bad ID"\nnot an assignment\n')
        self.assertEqual(values['NAME'],'New OS');self.assertIsNone(values['VERSION_ID']);self.assertIsNone(values['ID']);self.assertEqual(errors,3)
        for raw in [b'\xff',b'x'*65537]:
            with self.assertRaises(OSError):identity.decode_os_release(raw)
        values,errors=identity.decode_os_release(b'VERSION_ID=""\nBUILD_ID=\n')
        self.assertEqual(errors,0);self.assertIsNone(values['VERSION_ID']);self.assertIsNone(values['BUILD_ID'])

    def test_os_release_precedence_fallback_and_missing_caption_are_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);etc=root/'etc';vendor=root/'vendor';vendor.write_text('NAME=Vendor\nVERSION_ID=2\n')
            self.assertEqual(identity.distribution((etc,vendor))['caption'],'Vendor')
            etc.write_text('NAME=Admin\n')
            result=identity.distribution((etc,vendor));self.assertEqual(result['caption'],'Admin');self.assertIsNone(result['fields']['VERSION_ID'])
            etc.write_text('VERSION_ID=1\n')
            result=identity.distribution((etc,vendor));self.assertFalse(result['available']);self.assertEqual(result['errno'],errno.ENODATA)
            def opened(path,*args,**kwargs):
                if path==etc:raise PermissionError(errno.EACCES,'Denied')
                self.fail('Denied higher-priority OS file must not fall back')
            with mock.patch.object(Path,'open',opened),self.assertRaises(PermissionError):identity.distribution((etc,vendor))

    def test_os_release_race_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'os-release';path.write_text('NAME=Example\n');stat=path.stat()
            changed=SimpleNamespace(**{key:getattr(stat,key) for key in ['st_dev','st_ino','st_size','st_ctime_ns']},st_mtime_ns=stat.st_mtime_ns+1)
            with mock.patch.object(identity.os,'fstat',side_effect=[stat,changed]),self.assertRaises(OSError) as error:
                identity.distribution((path,))
            self.assertEqual(error.exception.errno,errno.EAGAIN)

    def test_os_kernel_distribution_and_architecture_are_independently_available(self):
        uname=SimpleNamespace(sysname='Linux',release='6.8-test',version='#1 Example',machine='x86_64')
        distro={'available':True,'caption':'Example OS1','complete':True}
        with mock.patch.object(identity,'distribution',return_value=distro),mock.patch.object(identity.os,'uname',return_value=uname),mock.patch.object(identity.subprocess,'run') as execute:
            result=identity.os_info()
        self.assertTrue(result['complete']);self.assertEqual(result['caption'],'Example OS1');self.assertEqual(result['architecture']['bits'],64)
        self.assertNotIn('node',result['kernel']);execute.assert_not_called()
        with mock.patch.object(identity,'distribution',side_effect=OSError(errno.EACCES,'Denied')),mock.patch.object(identity.os,'uname',return_value=uname):result=identity.os_info()
        self.assertTrue(result['available']);self.assertFalse(result['complete']);self.assertIsNone(result['caption']);self.assertTrue(result['kernel']['available'])
        uname.machine='future-unknown'
        with mock.patch.object(identity,'distribution',return_value=distro),mock.patch.object(identity.os,'uname',return_value=uname):result=identity.os_info()
        self.assertFalse(result['architecture']['available']);self.assertIsNone(result['architecture']['bits'])

    def test_local_pci_parser_handles_names_flags_duplicates_and_large_domains(self):
        rows,errors=identity.decode_pci_names(PCI+PCI.replace('0000:00:02.0','10000:e1:00.0'))
        self.assertEqual(errors,0);self.assertEqual(rows['10000:e1:00.0']['device_name'],'Graphics [Model]')
        reordered='-new42 0000:00:02.0 -r04 "VGA compatible controller [0300]" -p00 "Example Vendor [1234]" "Graphics [Model] [abcd]" "" ""'
        self.assertEqual(identity.decode_pci_names(reordered),identity.decode_pci_names(PCI))
        rows,errors=identity.decode_pci_names(PCI+PCI+'bad\n');self.assertEqual(rows,{});self.assertEqual(errors,2)
        with self.assertRaises(OSError):identity.decode_pci_names('x'*(4*1024*1024+1))

    def test_local_pci_transport_is_fixed_sysfs_only_and_typed(self):
        with mock.patch.object(identity.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=PCI)) as run:
            self.assertEqual(identity.pci_names()[1],0)
        run.assert_called_once_with(['/usr/bin/lspci','-A','linux-sysfs','-D','-mm','-nn'],capture_output=True,text=True,encoding='utf-8',errors='strict',timeout=5,env={'LC_ALL':'C'})
        for failure,code in [(FileNotFoundError(),errno.ENODEV),(subprocess.TimeoutExpired('lspci',5),errno.ETIMEDOUT),
                             (UnicodeDecodeError('utf-8',b'\xff',0,1,'bad'),errno.EPROTO)]:
            with mock.patch.object(identity.subprocess,'run',side_effect=failure),self.assertRaises(OSError) as error:identity.pci_names()
            self.assertEqual(error.exception.errno,code)

    def test_gpu_names_are_numeric_identity_matched_without_drm_or_driver_requirement(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.pci(root);self.pci(root,'10000:e1:00.0',kind='0x010800')
            with mock.patch.object(identity,'pci_names',return_value=identity.decode_pci_names(PCI)):result=identity.gpu_info(root)
        self.assertTrue(result['complete']);self.assertTrue(result['present']);self.assertEqual(len(result['adapters']),1)
        self.assertEqual(result['adapters'][0]['caption'],'Example Vendor Graphics [Model]')

    def test_missing_or_unknown_gpu_caption_retains_identity_without_fabricated_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.pci(root)
            for parsed in [({},0),identity.decode_pci_names(PCI.replace('Graphics [Model]','Device')),
                           identity.decode_pci_names(PCI.replace('[abcd]','[1234]'))]:
                with mock.patch.object(identity,'pci_names',return_value=parsed):result=identity.gpu_info(root)
                self.assertFalse(result['complete']);self.assertTrue(result['present']);self.assertTrue(result['adapters'][0]['available'])
                self.assertFalse(result['adapters'][0]['caption_available']);self.assertIsNone(result['adapters'][0]['caption'])
            with mock.patch.object(identity,'pci_names',side_effect=OSError(errno.ENODEV,'Missing')):result=identity.gpu_info(root)
            self.assertEqual(result['adapters'][0]['caption_error']['errno'],errno.ENODEV)

    def test_unknown_pci_class_cannot_claim_no_graphics_but_empty_census_can(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with mock.patch.object(identity,'pci_names',return_value=({},0)):
                self.assertIs(identity.gpu_info(root)['present'],False)
                self.pci(root,kind='bad');result=identity.gpu_info(root)
            self.assertIsNone(result['present']);self.assertFalse(result['selection_complete']);self.assertEqual(result['selection_error_count'],1)

    def test_classification_changes_withhold_a_stale_complete_graphics_census(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=self.pci(root,kind='0x010800');original=identity.text;count=[0]
            def changed(value,*args):
                if value==path/'class':count[0]+=1;return '0x010800' if count[0]==1 else '0x030000'
                return original(value,*args)
            with mock.patch.object(identity,'text',side_effect=changed),mock.patch.object(identity,'pci_names',return_value=({},0)),self.assertRaises(OSError) as error:identity.gpu_info(root)
            self.assertEqual(error.exception.errno,errno.EAGAIN)

    def test_public_routes_avoid_the_sensor_snapshot_and_reject_arguments_before_io(self):
        with mock.patch.object(identity,'firmware',return_value='Firmware field') as firmware,\
             mock.patch.object(identity.cpu_metadata,'model_name',return_value='CPU name'),\
             mock.patch.object(identity,'gpu_info',return_value={'adapters':[]}),\
             mock.patch.object(identity,'os_info',return_value={'caption':'Native OS'}),\
             mock.patch('compat.frontend',side_effect=AssertionError('Unrelated hardware snapshot')):
            for name in identity.NAMES:self.assertIsNotNone(api_bridge.call({'name':name}))
            self.assertEqual(firmware.call_count,6)
        with mock.patch.object(identity,'firmware') as firmware,mock.patch.object(identity,'gpu_info') as gpu:
            for name in identity.NAMES:
                with self.subTest(name=name),self.assertRaises(ValueError):api_bridge.call({'name':name,'args':{'unexpected':True}})
        firmware.assert_not_called();gpu.assert_not_called()


if __name__=='__main__':unittest.main()
