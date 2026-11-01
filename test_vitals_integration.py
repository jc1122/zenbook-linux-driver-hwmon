# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import importlib.util
import tempfile
import unittest
import hashlib
from unittest import mock

SPEC=importlib.util.spec_from_file_location('vitals_install',Path(__file__).parent/'tools/install-vitals.py')
installer=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(installer)


class VitalsIntegrationTests(unittest.TestCase):
    def test_reviewed_gauge_power_upgrade_changes_only_the_battery_helper(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);(path/'helpers').mkdir()
            original="// owner code\nimport * as FileModule from './helpers/file.js';\n    _queryProcessor(callback, dwell) {\n    _queryStorage(callback, dwell) {\n    _queryBattery(callback) {\n    destroy() {\n"
            (path/'sensors.js').write_text(original);(path/'values.js').write_text("            case 'hertz':\n")
            for name,data in installer.plan(path).items():(path/name).write_bytes(data)
            sensors=(path/'sensors.js').read_bytes();helper=path/'helpers/zenbook-battery.js';previous=b'reviewed previous gauge-power helper';helper.write_bytes(previous)
            with mock.patch.object(installer,'PREVIOUS_GAUGE_POWER_HELPER_SHA256',hashlib.sha256(previous).hexdigest()):
                changes=installer.plan(path);self.assertEqual(set(changes),{'helpers/zenbook-battery.js'})
                self.assertEqual((path/'sensors.js').read_bytes(),sensors)
                helper.write_bytes(previous+b' owner edit')
                with self.assertRaises(RuntimeError):installer.plan(path)
                for name,data in changes.items():(path/name).write_bytes(data)
                self.assertEqual(installer.plan(path),{})

    def test_previous_frequency_upgrade_keeps_owner_code_and_rejects_unreviewed_helper(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);(path/'helpers').mkdir()
            original="// owner code\nimport * as FileModule from './helpers/file.js';\n    _queryProcessor(callback, dwell) {\n    _queryStorage(callback, dwell) {\n    _queryBattery(callback) {\n    destroy() {\n"
            (path/'sensors.js').write_text(original);(path/'values.js').write_text("            case 'hertz':\n")
            for name,data in installer.plan(path).items():(path/name).write_bytes(data)
            p=path/'sensors.js';p.write_text(p.read_text().replace(installer.FREQUENCY_IMPORT,installer.PREVIOUS_FREQUENCY_IMPORT).replace(installer.FREQUENCY_METHOD,installer.PREVIOUS_FREQUENCY_METHOD))
            helper=path/'helpers/zenbook-frequency.js';old=b'reviewed previous frequency helper';helper.write_bytes(old)
            with mock.patch.object(installer,'PREVIOUS_FREQUENCY_HELPER_SHA256',hashlib.sha256(old).hexdigest()):
                changes=installer.plan(path);self.assertEqual(set(changes),{'sensors.js','helpers/zenbook-frequency.js'})
                self.assertIn('// owner code',changes['sensors.js'].decode());self.assertIn('serviceInputs(report).packagePower',changes['sensors.js'].decode())
                self.assertNotIn('/cpu_package_power',changes['sensors.js'].decode())
                helper.write_bytes(old+b' owner edit')
                with self.assertRaises(RuntimeError):installer.plan(path)
                for name,data in changes.items():(path/name).write_bytes(data)
                self.assertEqual(installer.plan(path),{})

    def test_reviewed_metrics_upgrade_preserves_sources_and_rejects_owner_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);(path/'helpers').mkdir()
            original="import * as FileModule from './helpers/file.js';\n    _queryProcessor(callback, dwell) {\n    _queryStorage(callback, dwell) {\n    _queryBattery(callback) {\n    destroy() {\n"
            (path/'sensors.js').write_text(original);(path/'values.js').write_text("            case 'hertz':\n")
            for name,data in installer.plan(path).items():(path/name).write_bytes(data)
            sensors=(path/'sensors.js').read_bytes();helper=path/'helpers/zenbook-metrics.js';old=b'reviewed previous metrics fixture';helper.write_bytes(old)
            with mock.patch.object(installer,'PREVIOUS_FIXED_ACTIVE_METRICS_SHA256',hashlib.sha256(old).hexdigest()):
                changes=installer.plan(path);self.assertEqual(set(changes),{'helpers/zenbook-metrics.js'})
                self.assertEqual((path/'sensors.js').read_bytes(),sensors)
                helper.write_bytes(old+b' owner edit')
                with self.assertRaises(RuntimeError):installer.plan(path)

    def test_frequency_refresh_uses_processor_path_and_preserves_existing_helpers(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);(path/'helpers').mkdir()
            original="import * as FileModule from './helpers/file.js';\n    _queryProcessor(callback, dwell) {\n    _queryStorage(callback, dwell) {\n    _queryBattery(callback) {\n    destroy() {\n"
            (path/'sensors.js').write_text(original);(path/'values.js').write_text("            case 'hertz':\n")
            changes=installer.plan(path);sensors=changes['sensors.js'].decode()
            self.assertIn('    _queryZenbookCPU(callback) {\n'+installer.FREQUENCY_CALL,sensors)
            self.assertIn('/cpu_reported_frequency',sensors)
            self.assertNotIn('sudo',installer.FREQUENCY_METHOD)
            for name,data in changes.items():(path/name).write_bytes(data)
            self.assertEqual(installer.plan(path),{})
            helper=path/'helpers/zenbook-frequency.js';helper.write_bytes(helper.read_bytes()+b' owner edit')
            with self.assertRaises(RuntimeError):installer.plan(path)

    def test_fan_hook_uses_fan_group_and_retains_wireless_source(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);(path/'helpers').mkdir()
            original="import * as FileModule from './helpers/file.js';\n    _queryTempVoltFan(callback, type, wantedKeys) {\n    _queryNetwork(callback, dwell) {\n    _queryProcessor(callback, dwell) {\n    _queryStorage(callback, dwell) {\n    _queryBattery(callback) {\n    destroy() {\n"
            (path/'sensors.js').write_text(original);(path/'values.js').write_text("            case 'hertz':\n")
            changes=installer.plan(path);sensors=changes['sensors.js'].decode()
            self.assertIn('    _queryTempVoltFan(callback, type, wantedKeys) {\n'+installer.FAN_CALL,sensors)
            self.assertIn(installer.WIRELESS_METHOD,sensors)
            for name,data in changes.items():(path/name).write_bytes(data)
            self.assertEqual(installer.plan(path),{})
            p=path/'helpers/zenbook-fan.js';p.write_bytes(p.read_bytes()+b' owner edit')
            with self.assertRaises(RuntimeError):installer.plan(path)
    def test_wireless_refresh_uses_network_and_destroys_only_owned_process(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);(path/'helpers').mkdir()
            original="import * as FileModule from './helpers/file.js';\n    _queryNetwork(callback, dwell) {\n    _queryProcessor(callback, dwell) {\n    _queryStorage(callback, dwell) {\n    _queryBattery(callback) {\n    destroy() {\n"
            (path/'sensors.js').write_text(original);(path/'values.js').write_text("            case 'hertz':\n")
            changes=installer.plan(path);sensors=changes['sensors.js'].decode()
            self.assertIn('    _queryNetwork(callback, dwell) {\n'+installer.WIRELESS_CALL,sensors)
            self.assertIn(installer.WIRELESS_DESTROY,sensors)
            self.assertNotIn("'sudo'",installer.WIRELESS_METHOD)
            self.assertIn("['/usr/local/bin/zenbook-hardware', 'wireless']",installer.WIRELESS_METHOD)
            for name,data in changes.items():(path/name).write_bytes(data)
            self.assertEqual(installer.plan(path),{})
            helper=path/'helpers/zenbook-wireless.js';helper.write_bytes(helper.read_bytes()+b' owner edit')
            with self.assertRaises(RuntimeError):installer.plan(path)
    def test_complete_block_hooks_gain_live_measurements_without_owner_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);(path/'helpers').mkdir()
            sensors='// owner code\n'+installer.IMPORT+installer.EXTRA_IMPORT+installer.PREVIOUS_COMPLETE_IMPORT+installer.PREVIOUS_COMPLETE_METHOD
            (path/'sensors.js').write_text(sensors);(path/'values.js').write_text('// owner formats')
            for dest,source in [('zenbook-charger.js','charger.js'),('zenbook-metrics.js','metrics.js')]:
                (path/'helpers'/dest).write_bytes((installer.ROOT/'integrations/vitals'/source).read_bytes())
            old=b'reviewed complete block helper';(path/'helpers/zenbook-battery.js').write_bytes(old)
            with mock.patch.object(installer,'PREVIOUS_COMPLETE_HELPER_SHA256',hashlib.sha256(old).hexdigest()):
                changes=installer.plan(path)
                self.assertEqual(set(changes),{'sensors.js','helpers/zenbook-battery.js','helpers/zenbook-wireless.js','helpers/zenbook-fan.js','helpers/zenbook-frequency.js','helpers/zenbook-service.js'})
                self.assertIn('// owner code',changes['sensors.js'].decode())
                self.assertIn('gaugeExtraRows(input.gaugeExtra)',changes['sensors.js'].decode())
                self.assertNotIn('/battery_gauge_extra',changes['sensors.js'].decode())
                for name,data in changes.items():(path/name).write_bytes(data)
                self.assertEqual(installer.plan(path),{})
                self.assertEqual((path/'values.js').read_text(),'// owner formats')
    def test_gauge_extra_upgrade_adds_sbs_and_preserves_owner_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);(path/'helpers').mkdir()
            sensors='// owner code\n'+installer.IMPORT+installer.EXTRA_IMPORT+installer.PREVIOUS_EXTRA_IMPORT+installer.PREVIOUS_EXTRA_METHOD
            (path/'sensors.js').write_text(sensors);(path/'values.js').write_text('// owner formats')
            for dest,source in [('zenbook-charger.js','charger.js'),('zenbook-metrics.js','metrics.js')]:
                (path/'helpers'/dest).write_bytes((installer.ROOT/'integrations/vitals'/source).read_bytes())
            old=b'reviewed extra helper';(path/'helpers/zenbook-battery.js').write_bytes(old)
            with mock.patch.object(installer,'PREVIOUS_EXTRA_HELPER_SHA256',hashlib.sha256(old).hexdigest()):
                changes=installer.plan(path)
                self.assertEqual(set(changes),{'sensors.js','helpers/zenbook-battery.js','helpers/zenbook-wireless.js','helpers/zenbook-fan.js','helpers/zenbook-frequency.js','helpers/zenbook-service.js'})
                self.assertIn('// owner code',changes['sensors.js'].decode())
                self.assertIn('sbsRows(input.sbs)',changes['sensors.js'].decode())
                self.assertNotIn('/battery_sbs',changes['sensors.js'].decode())
                for name,data in changes.items():(path/name).write_bytes(data)
                self.assertEqual(installer.plan(path),{})
                self.assertEqual((path/'values.js').read_text(),'// owner formats')

    def test_previous_gauge_hooks_upgrade_without_overwriting_owner_code(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);(path/'helpers').mkdir()
            previous=installer.PREVIOUS_BMS_IMPORT+installer.PREVIOUS_BMS_METHOD
            sensors='// owner code\n'+installer.IMPORT+installer.EXTRA_IMPORT+previous
            (path/'sensors.js').write_text(sensors);(path/'values.js').write_text('// owner formats')
            for dest,source in [('zenbook-charger.js','charger.js'),('zenbook-metrics.js','metrics.js')]:
                (path/'helpers'/dest).write_bytes((installer.ROOT/'integrations/vitals'/source).read_bytes())
            old=b'previous gauge helper fixture';(path/'helpers/zenbook-battery.js').write_bytes(old)
            with mock.patch.object(installer,'PREVIOUS_BMS_HELPER_SHA256',hashlib.sha256(old).hexdigest()):
                changes=installer.plan(path)
                self.assertEqual(set(changes),{'sensors.js','helpers/zenbook-battery.js','helpers/zenbook-wireless.js','helpers/zenbook-fan.js','helpers/zenbook-frequency.js','helpers/zenbook-service.js'})
                self.assertIn('// owner code',changes['sensors.js'].decode())
                self.assertIn('pdAlertRows(input.pdIdentity, chargerRows)',changes['sensors.js'].decode())
                for name,data in changes.items():(path/name).write_bytes(data)
                self.assertEqual(installer.plan(path),{})
    def test_reviewed_battery_upgrade_preserves_shell_and_rejects_local_helper_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);(path/'helpers').mkdir()
            sensors='// preserve owner code\n'+installer.IMPORT+installer.EXTRA_IMPORT+installer.BMS_IMPORT+installer.FILE_METHOD
            (path/'sensors.js').write_text(sensors);(path/'values.js').write_text('// owner formatters\n')
            for dest,source in [('zenbook-charger.js','charger.js'),('zenbook-metrics.js','metrics.js')]:
                (path/'helpers'/dest).write_bytes((installer.ROOT/'integrations/vitals'/source).read_bytes())
            old=b'reviewed battery fixture';(path/'helpers/zenbook-battery.js').write_bytes(old)
            with mock.patch.object(installer,'PREVIOUS_BATTERY_SHA256',hashlib.sha256(old).hexdigest()):
                changes=installer.plan(path)
                self.assertEqual(set(changes),{'sensors.js','helpers/zenbook-battery.js','helpers/zenbook-wireless.js','helpers/zenbook-fan.js','helpers/zenbook-frequency.js','helpers/zenbook-service.js'})
                self.assertEqual((path/'sensors.js').read_text(),sensors)
                self.assertIn(installer.WIRELESS_CALL,changes['sensors.js'].decode())
                (path/'helpers/zenbook-battery.js').write_bytes(old+b' owner edit')
                with self.assertRaises(RuntimeError):installer.plan(path)

    def test_unsupported_extension_fails_before_any_file_change(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);(path/'sensors.js').write_text('unknown version');(path/'values.js').write_text('unknown version')
            with self.assertRaises(RuntimeError):installer.plan(path)
            self.assertEqual((path/'sensors.js').read_text(),'unknown version')
            self.assertFalse((path/'helpers/zenbook-charger.js').exists())

    def test_integration_preserves_unrelated_extension_customizations(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);(path/'helpers').mkdir()
            original="    _queryProcessor(callback, dwell) {\n    _queryStorage(callback, dwell) {\n// existing customization\nimport * as FileModule from './helpers/file.js';\n    _queryBattery(callback) {\n// keep battery logic\n    destroy() {\n"
            (path/'sensors.js').write_text(original);(path/'values.js').write_text("            case 'hertz':\n// keep formatter logic\n")
            changes=installer.plan(path)
            for name,data in changes.items():(path/name).write_bytes(data)
            self.assertIn('// existing customization',changes['sensors.js'].decode())
            self.assertIn('// keep formatter logic',changes['values.js'].decode())
            self.assertEqual(installer.plan(path),{})

    def test_known_previous_integration_upgrades_without_losing_customizations(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);(path/'helpers').mkdir()
            old=b'previous reviewed helper fixture'
            (path/'helpers/zenbook-charger.js').write_bytes(old)
            (path/'sensors.js').write_text('// preserve customization\n'+installer.IMPORT+installer.OLD_METHOD+'    _queryProcessor(callback, dwell) {\n    _queryStorage(callback, dwell) {\n// preserve battery logic\n')
            (path/'values.js').write_text('// preserve formatters\n')
            with mock.patch.object(installer,'OLD_HELPER_SHA256',hashlib.sha256(old).hexdigest()):changes=installer.plan(path)
            self.assertEqual(set(changes),{'sensors.js','helpers/zenbook-charger.js','helpers/zenbook-metrics.js','helpers/zenbook-battery.js','helpers/zenbook-wireless.js','helpers/zenbook-fan.js','helpers/zenbook-frequency.js','helpers/zenbook-service.js'})
            self.assertIn(installer.METHOD,changes['sensors.js'].decode().replace(installer.WIRELESS_CALL,'').replace(installer.FAN_FALLBACK,'').replace(installer.FREQUENCY_CALL,''))
            self.assertIn('// preserve customization',changes['sensors.js'].decode())
            for name,data in changes.items():(path/name).write_bytes(data)
            self.assertEqual(installer.plan(path),{})

    RESTRICTED=('power1_input','power3_input','/charger_adc','/charger_metrics','/battery_gauge_metrics','/battery_lifetime',
                '/pd_identity','/battery_gauge_extra','/battery_sbs','/cpu_package_power','/battery_identity')

    @staticmethod
    def as_installed(method):
        anchor='    _queryZenbookCPU(callback) {\n'  # the frequency layer hooks the CPU method
        return method.replace(anchor,anchor+installer.FREQUENCY_CALL,1)

    def to_078(self,sensors):
        return sensors.replace(self.as_installed(installer.METHOD),self.as_installed(installer.FILE_METHOD)).replace(
            installer.SERVICE_IMPORT,'').replace(installer.FREQUENCY_METHOD,installer.PREVIOUS_FILE_FREQUENCY_METHOD)

    def installed_078(self,path,owner='// owner code\n'):
        """Reviewed 0.78 layout: managed blocks read the hwmon attributes directly."""
        original="import * as FileModule from './helpers/file.js';\n    _queryTempVoltFan(callback, type, wantedKeys) {\n    _queryNetwork(callback, dwell) {\n    _queryProcessor(callback, dwell) {\n    _queryStorage(callback, dwell) {\n    _queryBattery(callback) {\n    destroy() {\n"
        (path/'helpers').mkdir();(path/'sensors.js').write_text(owner+original);(path/'values.js').write_text("            case 'hertz':\n")
        for name,data in installer.plan(path).items():(path/name).write_bytes(data)
        sensors=(path/'sensors.js').read_text()
        sensors=self.to_078(sensors)
        (path/'sensors.js').write_text(sensors);(path/installer.SERVICE_HELPER).unlink()
        for name in self.RESTRICTED:
            if name not in ('power3_input','/battery_identity'):self.assertIn(name,sensors)  # 0.78 never read these two
        return sensors

    def test_reviewed_078_integration_moves_restricted_reads_to_the_service(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);before=self.installed_078(path)
            helpers={p.name:p.read_bytes() for p in (path/'helpers').iterdir()}
            changes=installer.plan(path)
            self.assertEqual(set(changes),{'sensors.js',installer.SERVICE_HELPER})
            sensors=changes['sensors.js'].decode()
            self.assertIn('// owner code',sensors);self.assertIn(installer.SERVICE_IMPORT,sensors)
            for name in self.RESTRICTED:self.assertNotIn(name,sensors)
            for name in ('/pd_contract','/pd_source_caps','/cpu_reported_frequency','/fan_diagnostics'):self.assertIn(name,sensors)
            self.assertNotIn('DBusCallFlags.ALLOW_INTERACTIVE',changes[installer.SERVICE_HELPER].decode());self.assertIn('Gio.DBusCallFlags.NONE',changes[installer.SERVICE_HELPER].decode())
            self.assertEqual(sensors.count('this._zenbookServiceMetrics()'),2)
            # Only managed text changed: undoing the managed replacement restores the 0.78 file exactly.
            self.assertEqual(self.to_078(sensors),before)
            for name,data in changes.items():(path/name).write_bytes(data)
            self.assertEqual(installer.plan(path),{})
            self.assertEqual({p.name:p.read_bytes() for p in (path/'helpers').iterdir() if p.name!='zenbook-service.js'},helpers)
            service=path/installer.SERVICE_HELPER;service.write_bytes(service.read_bytes()+b' owner edit')
            with self.assertRaises(RuntimeError):installer.plan(path)

    def test_078_upgrade_refuses_unreviewed_helpers_and_foreign_service_code(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);self.installed_078(path)
            frequency=path/'helpers/zenbook-frequency.js';original=frequency.read_bytes()
            frequency.write_bytes(original+b' owner edit')
            with self.assertRaises(RuntimeError):installer.plan(path)
            frequency.write_bytes(original)
            (path/installer.SERVICE_HELPER).write_bytes(b'foreign helper')
            with self.assertRaises(RuntimeError):installer.plan(path)
            (path/installer.SERVICE_HELPER).unlink()
            charger=path/'helpers/zenbook-charger.js';charger.write_bytes(b'unreviewed charger')
            with self.assertRaises(RuntimeError):installer.plan(path)
            with mock.patch.object(installer,'PREVIOUS_FILE_CHARGER_SHA256',hashlib.sha256(b'unreviewed charger').hexdigest()):
                changes=installer.plan(path)
            self.assertEqual(set(changes),{'sensors.js',installer.SERVICE_HELPER,'helpers/zenbook-charger.js'})
            self.assertEqual(changes['helpers/zenbook-charger.js'],(installer.ROOT/'integrations/vitals/charger.js').read_bytes())

    def test_installed_078_helper_hashes_are_accepted_previous_versions(self):
        for name,digest in (('charger.js',installer.PREVIOUS_FILE_CHARGER_SHA256),('metrics.js',installer.PREVIOUS_FILE_METRICS_SHA256),
                            ('battery.js',installer.PREVIOUS_FILE_BATTERY_SHA256),('frequency.js',installer.PREVIOUS_FILE_FREQUENCY_HELPER_SHA256)):
            # 0.79 keeps these row builders byte-identical; the hashes guard later edits.
            self.assertEqual(hashlib.sha256((installer.ROOT/'integrations/vitals'/name).read_bytes()).hexdigest(),digest,name)


if __name__=='__main__':unittest.main()
