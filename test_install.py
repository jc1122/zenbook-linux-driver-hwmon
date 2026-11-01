# SPDX-License-Identifier: GPL-2.0-only
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC=importlib.util.spec_from_file_location('asus_ht_installer',Path(__file__).parent/'tools/install.py')
installer=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(installer)


class RuntimeInstallationTests(unittest.TestCase):
    def test_library_replacement_preserves_existing_open_inode(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'new';target=root/'installed'
            source.write_bytes(b'new library');target.write_bytes(b'old library')
            with target.open('rb') as existing:
                installer.atomic_library(source,target)
                self.assertEqual(existing.read(),b'old library')
                self.assertEqual(target.read_bytes(),b'new library')
            self.assertEqual(target.stat().st_mode&0o777,0o644)

    def test_installed_runtime_is_traversable_and_files_readable(self):
        if not (installer.ROOT/'build/libasus-healthytable.so').exists():self.skipTest('Run make check.')
        with tempfile.TemporaryDirectory() as temp,mock.patch.object(installer,'run'):
            prefix=Path(temp)
            target=installer.install_runtime(prefix)
            self.assertEqual(target.stat().st_mode&0o777,0o755)
            self.assertEqual((target/'api_bridge.py').stat().st_mode&0o777,0o644)
            self.assertEqual((prefix/'bin/zenbook-hardware').stat().st_mode&0o777,0o755)
            # Idempotent reinstall also repairs an earlier staging-directory
            # permission mistake after verifying the exact runtime contents.
            target.chmod(0o700)
            self.assertEqual(installer.install_runtime(prefix),target)
            self.assertEqual(target.stat().st_mode&0o777,0o755)


if __name__=='__main__':unittest.main()
