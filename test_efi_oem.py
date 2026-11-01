# SPDX-License-Identifier: GPL-2.0-only
import errno
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import efi_oem

class FirmwareTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.fw=efi_oem.Firmware(self.root/'vars',self.root/'backups');self.fw.root.mkdir()
        self.before={}
        for name,(guid,size) in efi_oem.VARIABLES.items():
            raw=struct.pack('<I',7)+bytes((i*7+3)&255 for i in range(size))
            self.before[name]=raw;(self.fw.root/(name+'-'+guid)).write_bytes(raw)
    def tearDown(self):self.tmp.cleanup()
    def test_timestamp_patch_preserves_attributes_and_every_unrelated_byte(self):
        plan,old,new=self.fw.plan('activated_time','2026-10-30 20:00:00')
        self.assertEqual(new[:36],old[:36]);self.assertEqual(new[55:],old[55:])
        self.assertEqual(new[36:55],b'2026-10-30 20:00:00');self.assertFalse(plan['applied'])
    def test_manufacturing_field_exact_recovered_offset(self):
        _,old,new=self.fw.plan('manufactured_time','2026-10-30 20:00:00.123')
        self.assertEqual(old[:152],new[:152]);self.assertEqual(old[175:],new[175:])
    def test_uuid_patch_is_raw_and_preserves_other_config_fields(self):
        _,old,new=self.fw.plan('random_uuid','0123456789abcdef0123456789abcdef')
        self.assertEqual(new[4:20],bytes.fromhex('0123456789abcdef0123456789abcdef'))
        self.assertEqual(new[20:],old[20:])
    def test_plan_length_guard_is_an_explicit_error_not_an_assert(self):
        guid,_=efi_oem.VARIABLES['CNFG'];short=self.before['CNFG'][:40]
        with mock.patch.object(self.fw,'read',return_value=(self.fw.root/('CNFG-'+guid),short)):
            with self.assertRaises(ValueError) as caught:self.fw.plan('activated_time','2026-10-30 20:00:00')
        self.assertIn('record length',str(caught.exception))
    def test_stale_revision_rejected_without_backup_or_write(self):
        old=self.fw.read('CNFG')[1]
        with self.assertRaises(RuntimeError):self.fw.apply('activated_time','2026-10-30 20:00:00','0'*64)
        self.assertEqual(self.fw.read('CNFG')[1],old);self.assertFalse(self.fw.backup_root.exists())
    def test_success_retains_verified_private_original(self):
        raw=self.fw.read('CNFG')[1]
        r=self.fw.apply('os_language','pl-PL',efi_oem.digest(raw))
        backup=Path(r['backup']);self.assertEqual(backup.read_bytes(),raw)
        self.assertEqual(backup.stat().st_mode&0o777,0o600)
        self.assertEqual(self.fw.read('CNFG')[1][116:124],b'pl-PL\0\0\0')
    def test_failed_backup_prevents_firmware_write(self):
        raw=self.fw.read('CNFG')[1]
        with mock.patch.object(self.fw,'backup',side_effect=OSError('backup failed')):
            with self.assertRaises(OSError):self.fw.apply('os_language','pl-PL',efi_oem.digest(raw))
        self.assertEqual(self.fw.read('CNFG')[1],raw)
    def test_missing_variable_is_not_created(self):
        p,_=self.fw.variable('MFG0');p.unlink()
        with self.assertRaises(FileNotFoundError):self.fw.plan('manufactured_time','2026-10-30 20:00:00.000')
        self.assertFalse(p.exists())
    def test_variable_symlink_is_rejected(self):
        p,_=self.fw.variable('CNFG');p.unlink();p.symlink_to(self.fw.variable('MFG0')[0])
        with self.assertRaises(RuntimeError):self.fw.read('CNFG')
    def test_unexpected_layout_is_rejected(self):
        p,_=self.fw.variable('CNFG');p.write_bytes(b'wrong')
        with self.assertRaises(RuntimeError):self.fw.plan('os_language','pl-PL')
    def test_unknown_variable_and_path_are_rejected(self):
        for name in ('BootOrder','../CNFG','SecureBoot'):
            with self.assertRaises(ValueError):self.fw.read(name)
    def test_validation_rejects_invalid_dates_and_oversized_values(self):
        for key,value in [('activated_time','2026-02-30 20:00:00'),('manufactured_time','short'),('random_uuid','../bad'),('os_language','pl-PL\nX')]:
            with self.assertRaises(ValueError):self.fw.plan(key,value)
    def test_clear_uses_windows_command_byte_and_does_not_modify_heal(self):
        heal=self.fw.read('HEAL')[1];_,old,new=self.fw.plan('clear_csc_repair_flag',None)
        self.assertEqual(new,struct.pack('<I',7)+b'\x77');self.assertEqual(self.fw.read('HEAL')[1],heal)
    def test_same_field_is_a_noop(self):
        p,raw=self.fw.read('CNFG');raw=raw[:116]+b'pl-PL\0\0\0'+raw[124:];p.write_bytes(raw)
        r=self.fw.apply('os_language','pl-PL',efi_oem.digest(raw))
        self.assertFalse(r['applied']);self.assertTrue(r['unchanged']);self.assertFalse(self.fw.backup_root.exists())
    def test_immutable_is_not_removed_without_explicit_request(self):
        raw=self.fw.read('CNFG')[1]
        with mock.patch.object(self.fw,'get_flags',return_value=0x10),mock.patch.object(self.fw,'set_flags') as setter:
            with self.assertRaises(PermissionError):self.fw.apply('os_language','pl-PL',efi_oem.digest(raw))
        setter.assert_not_called();self.assertEqual(self.fw.read('CNFG')[1],raw)
    def test_explicit_immutable_write_restores_original_flags(self):
        raw=self.fw.read('CNFG')[1]
        with mock.patch.object(self.fw,'get_flags',return_value=0x10),mock.patch.object(self.fw,'set_flags') as setter:
            self.fw.apply('os_language','pl-PL',efi_oem.digest(raw),True)
        self.assertEqual([call.args[1] for call in setter.call_args_list],[0,0x10])
    def test_failed_firmware_write_still_restores_original_immutable_flag(self):
        raw=self.fw.read('CNFG')[1]
        with mock.patch.object(self.fw,'get_flags',return_value=0x10),mock.patch.object(self.fw,'set_flags') as setter,\
             mock.patch.object(self.fw,'backup',return_value=self.root/'backup'),mock.patch.object(efi_oem.os,'write',side_effect=OSError(errno.EIO,'firmware rejected write')):
            with self.assertRaises(OSError):self.fw.apply('os_language','pl-PL',efi_oem.digest(raw),True)
        self.assertEqual([call.args[1] for call in setter.call_args_list],[0,0x10])

if __name__=='__main__':unittest.main()
