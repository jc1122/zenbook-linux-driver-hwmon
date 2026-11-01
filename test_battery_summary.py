# SPDX-License-Identifier: GPL-2.0-only
import errno
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import api_bridge
import battery_summary as summary


class BatterySummaryTests(unittest.TestCase):
    def fixture(self,root,full=7500,design=10000,remaining=2000):
        for key,value in [('type','Battery'),('present','1'),('charge_full',full),
                          ('charge_full_design',design),('charge_now',remaining)]:
            (root/key).write_text(str(value)+'\n')

    def test_asoc_is_unrounded_full_design_fraction_including_zero_and_above_one(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for full,expected in [(7500,.75),(0,0),(12500,1.25)]:
                self.fixture(root,full=full)
                self.assertEqual(summary.charge_summary('Battery_Read_ASOC',root),expected)
            self.fixture(root,design=0)
            with self.assertRaises(OSError) as error:summary.charge_summary('Battery_Read_ASOC',root)
            self.assertEqual(error.exception.errno,errno.ENODATA)

    def test_capacity_is_remaining_charge_with_units_and_preserves_real_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for remaining in [2000,0,1234]:
                self.fixture(root,remaining=remaining)
                result=summary.charge_summary('Battery_Read_Capacity',root)
                self.assertEqual(result['value'],remaining/1000);self.assertEqual(result['units'],'mAh')
                self.assertEqual(result['quantity'],'remaining_charge')

    def test_missing_absent_invalid_and_denied_charge_data_are_typed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.fixture(root)
            for field,value in [('present','0'),('type','Mains'),('charge_now','-1'),('charge_now',str(2**64))]:
                self.fixture(root);(root/field).write_text(value)
                with self.subTest(field=field,value=value),self.assertRaises(OSError):summary.charge_summary('Battery_Read_Capacity',root)
            self.fixture(root);(root/'charge_now').unlink()
            with self.assertRaises(FileNotFoundError):summary.charge_summary('Battery_Read_Capacity',root)
            with mock.patch.object(summary,'text',side_effect=PermissionError(errno.EACCES,'Denied')),self.assertRaises(PermissionError):summary.charge_summary('Battery_Read_ASOC',root)

    def test_changed_full_capacity_does_not_become_a_precise_ratio(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.fixture(root);original=summary.unsigned;count=[0]
            def changed(path):
                if path.name=='charge_full':count[0]+=1;return 7000+count[0]
                return original(path)
            with mock.patch.object(summary,'unsigned',side_effect=changed),self.assertRaises(OSError) as error:summary.charge_summary('Battery_Read_ASOC',root)
            self.assertEqual(error.exception.errno,errno.EAGAIN)

    def test_all_four_cell_channels_are_preserved_with_independent_availability(self):
        result=summary.cell_voltages(dict(zip([f'battery_cell{i}_mV' for i in range(1,5)],[4100,4110,0,65535])))
        self.assertEqual([row['channel'] for row in result['cells']],[1,2,3,4]);self.assertTrue(result['frame_complete'])
        self.assertEqual(result['measured_channels'],2);self.assertEqual([r['millivolts'] for r in result['cells']],[4100,4110,None,None])
        self.assertEqual([r['raw_millivolts'] for r in result['cells']],[4100,4110,0,65535])

    def test_missing_or_malformed_channels_do_not_erase_a_good_cell(self):
        result=summary.cell_voltages({'battery_cell1_mV':4200,'battery_cell2_mV':True,'battery_cell3_mV':-1})
        self.assertTrue(result['available']);self.assertFalse(result['frame_complete'])
        self.assertEqual(result['cells'][1]['errno'],errno.EPROTO);self.assertEqual(result['cells'][2]['errno'],errno.ENODATA)
        self.assertFalse(summary.cell_voltages({})['available'])

    def test_numeric_chip_id_zero_is_not_ascii_chip_name_and_transport_errors_survive(self):
        with mock.patch.object(summary.qualified_ec,'snapshot',return_value=({'chip_id':0,'chip_name_raw':[53,53,55,49]},[])):
            result=api_bridge.call({'name':'BatteryHealthyTable_ECChipID'})
        self.assertIs(type(result),int);self.assertEqual(result,0)
        with mock.patch.object(summary.qualified_ec,'snapshot',side_effect=OSError(errno.EBUSY,'Manual owner')),self.assertRaises(OSError) as error:
            api_bridge.call({'name':'Battery_Read_CellVoltage'})
        self.assertEqual(error.exception.errno,errno.EBUSY)

    def test_all_public_arguments_reject_before_battery_access(self):
        with mock.patch.object(summary,'charge_summary') as charge,mock.patch.object(summary.qualified_ec,'snapshot') as snapshot:
            for name in summary.NAMES:
                with self.subTest(name=name),self.assertRaises(ValueError):api_bridge.call({'name':name,'args':{'unexpected':True}})
        charge.assert_not_called();snapshot.assert_not_called()


if __name__=='__main__':unittest.main()
