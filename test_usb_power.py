# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import errno
import tempfile
import unittest
from unittest import mock
import api_bridge
import usb_power as usb


def supply(root,name='1',online='1',status='Charging',kind='C [PD] PD_PPS'):
    path=root/('ucsi-source-psy-'+name);path.mkdir()
    for key,value in {'online':online,'status':status,'usb_type':kind,'voltage_now':'20000000',
                      'current_now':'3000000','voltage_max':'20000000','current_max':'5000000'}.items():
        (path/key).write_text(value)
    return path


class USBPowerTests(unittest.TestCase):
    def test_pd_and_pps_sink_are_online_but_never_adcs(self):
        for kind in ('C [PD] PD_PPS','C PD [PD_PPS]'):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);supply(root,kind=kind)
                r=usb.result(root);p=r['ports'][0]
                self.assertTrue(r['available']);self.assertTrue(r['pd_input_online'])
                self.assertEqual(p['power_role'],'sink');self.assertFalse(p['electrical_measurements_available'])
                self.assertIsNone(p['voltage_volts']);self.assertIsNone(p['current_amperes'])
                self.assertEqual(p['ucsi_values']['selected_voltage_volts'],20)
                self.assertEqual(p['ucsi_values']['requested_or_advertised_current_amperes'],3)
                self.assertFalse(p['ucsi_values']['measurement'])

    def test_phone_source_advertisement_is_not_charging_input_or_measured_draw(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=supply(root,online='0',status='Discharging',kind='[C] PD PD_PPS')
            (p/'voltage_now').write_text('5000000')
            r=usb.result(root);p=r['ports'][0]
            self.assertFalse(r['pd_input_online']);self.assertEqual(p['power_role'],'source')
            self.assertEqual(p['ucsi_values']['selected_voltage_volts'],5)
            self.assertIsNone(p['current_amperes']);self.assertIn('advertisement',p['ucsi_values']['semantics'])

    def test_offline_defaults_are_suppressed_and_disabled_pd_path_is_not_input(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=supply(root,online='0',status='Not charging')
            r=usb.result(root);self.assertFalse(r['pd_input_online'])
            self.assertTrue(all(r['ports'][0]['ucsi_values'][key] is None for key in usb.FIELDS.values()))
            (p/'online').write_text('1');self.assertFalse(usb.result(root)['pd_input_online'])

    def test_non_pd_type_c_input_is_known_false_for_pd_query(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);supply(root,kind='[C] PD PD_PPS')
            with mock.patch.object(usb,'ROOT',root):self.assertIs(api_bridge.call({'name':'Power_PD_Charging'}),False)

    def test_optional_missing_zero_negative_or_bad_metadata_does_not_erase_pd_state(self):
        for value in (None,'0','-1','broken','9999999999'):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);p=supply(root)
                if value is None:(p/'current_now').unlink()
                else:(p/'current_now').write_text(value)
                r=usb.result(root);self.assertTrue(r['pd_input_online'])
                self.assertIsNone(r['ports'][0]['ucsi_values']['requested_or_advertised_current_amperes'])
                self.assertIn('current_now',r['ports'][0]['ucsi_values']['errors'])
                with mock.patch.object(usb,'ROOT',root):self.assertTrue(usb.pd_input_online())

    def test_unknown_mandatory_state_never_becomes_false(self):
        for field,value in (('online','-1'),('online','3'),('status','Unknown'),('status','Discharging'),
                            ('usb_type','C PD'),('usb_type','[C] [PD]'),('usb_type','C [UNKNOWN]')):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);p=supply(root);(p/field).write_text(value)
                self.assertIsNone(usb.result(root)['pd_input_online'])
                with mock.patch.object(usb,'ROOT',root),self.assertRaises(OSError):usb.pd_input_online()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=supply(root);(p/'status').unlink()
            with mock.patch.object(usb,'ROOT',root),self.assertRaises(FileNotFoundError):usb.pd_input_online()

    def test_known_positive_survives_bad_other_port_but_negative_requires_all_ports(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=supply(root);bad=supply(root,'2');(bad/'online').unlink()
            with mock.patch.object(usb,'ROOT',root):self.assertTrue(usb.pd_input_online())
            (p/'online').write_text('0');(p/'status').write_text('Not charging')
            with mock.patch.object(usb,'ROOT',root),self.assertRaises(OSError):usb.pd_input_online()

    def test_missing_or_empty_provider_returns_unknown_not_off(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for path in (root,root/'missing'):
                self.assertIsNone(usb.result(path)['pd_input_online'])
                with mock.patch.object(usb,'ROOT',path),self.assertRaises(OSError):usb.pd_input_online()

    def test_changed_state_identity_and_inventory_are_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=supply(root);first=usb.state(p)
            with mock.patch.object(usb,'state',side_effect=[first,(0,'Not charging',first[2],first[3])]):
                self.assertEqual(usb.result(root)['ports'][0]['errno'],errno.EAGAIN)
            with mock.patch.object(usb,'identity',side_effect=[(1,1),(1,2)]):
                self.assertIsNone(usb.result(root)['pd_input_online'])
            with mock.patch.object(usb,'supplies',side_effect=[[p],[]]):
                self.assertEqual(usb.result(root)['errno'],errno.EAGAIN)

    def test_permission_errors_and_arguments_are_preserved(self):
        with mock.patch.object(usb,'supplies',side_effect=PermissionError(errno.EACCES,'denied')):
            self.assertEqual(usb.result()['errno'],errno.EACCES)
            with self.assertRaises(PermissionError):usb.pd_input_online()
        with self.assertRaises(ValueError):api_bridge.call({'name':'Power_PD_Charging','args':{'scan':True}})


if __name__=='__main__':unittest.main()
