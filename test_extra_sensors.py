# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock
import charger
import extra_sensors
import native_oem
import compat


class AdditionalSensorTests(unittest.TestCase):
    def test_truncated_charger_response_never_invents_fourth_pdo(self):
        data=bytes.fromhex('042c91010a2cd102002cb10400454106')
        self.assertEqual(len(data),16)
        result=charger.decode_asus_source_pdos(data)
        self.assertEqual(result['reported_count'],4)
        self.assertEqual([r['voltage_volts'] for r in result['complete_pdos']],[5,9,15])
        self.assertEqual([r['max_current_amperes'] for r in result['complete_pdos']],[3,3,3])
        self.assertFalse(result['complete']);self.assertIsNone(result['maximum_profile_watts'])
        self.assertEqual(result['truncated_bytes_hex'],'454106')
        self.assertFalse(result['measurement'])
        self.assertFalse(result['target_verified'])

    def test_complete_response_has_a_valid_advertised_capacity(self):
        data=b'\x01'+(0x0001912c).to_bytes(4,'little')+bytes(11)
        result=charger.decode_asus_source_pdos(data)
        self.assertTrue(result['complete']);self.assertEqual(result['maximum_profile_watts'],15)
        self.assertFalse(result['target_verified'])

    def test_invalid_pdo_and_response_layouts_are_rejected(self):
        for data in [bytes(16),b'\x08'+bytes(15),b'\x01'+bytes(15),bytes(15)]:
            with self.assertRaises(OSError):charger.decode_asus_source_pdos(data)
        for raw in ['bad','0x00']:
            with self.assertRaises(OSError):charger.decode_response(raw)

    def test_query_accepts_only_fixed_get_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);(p/'response').write_text('0x'+'00'*16)
            with self.assertRaises(ValueError):charger.query(p,'set_power')
            self.assertFalse((p/'command').exists())
            with self.assertRaises(ValueError):charger.query(p,'capability',3)
            charger.query(p,'connector_status',2)
            self.assertEqual((p/'command').read_text(),'0x20012\n')

    def test_named_native_temperatures_are_read_without_relabelling(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'hwmon0';p.mkdir();(p/'name').write_text('coretemp')
            (p/'temp1_input').write_text('42500');(p/'temp1_label').write_text('Package id 0')
            (p/'temp2_input').write_text('not available')
            self.assertEqual(extra_sensors.temperatures(Path(temp)),{'coretemp/Package id 0':42.5})

    def test_firmware_inventory_does_not_read_storage_contents(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);p=base/'nvmem/mtd0';p.mkdir(parents=True)
            (p/'nvmem').write_bytes(bytes(512));m=base/'mtd/mtd0';m.mkdir(parents=True)
            (m/'name').write_text('BIOS');(m/'flags').write_text('0x800')
            with mock.patch.object(Path,'read_bytes',side_effect=AssertionError('contents must not be read')),mock.patch.object(extra_sensors.firmware_queries,'report',return_value={'eeprom_table':{'available':False,'status':'firmware_unsupported'}}):
                result=extra_sensors.firmware_storage(base/'nvmem',base/'mtd')
            self.assertEqual(result['storage'][0]['bytes'],512)
            self.assertFalse(result['storage'][0]['contents_read']);self.assertFalse(result['storage'][0]['writable'])
            self.assertFalse(result['asus_eeprom_table_available'])

    def test_voltage_reads_public_hwmon_without_oem_rpc(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);(p/'in6_input').write_text('1125\n')
            with mock.patch.object(native_oem,'device',return_value=p),mock.patch.object(native_oem,'rpc') as rpc:
                value=native_oem.call('CPU_ReadCpuVoltage',{})
                self.assertFalse(compat.needs_root('CPU_ReadCpuVoltage',{}))
            rpc.assert_not_called();self.assertEqual(value['millivolts'],1125)
            self.assertFalse(value['independent_rail_measurement'])


if __name__=='__main__':unittest.main()
