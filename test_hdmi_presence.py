# SPDX-License-Identifier: GPL-2.0-only
import errno
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import api_bridge
import hdmi_presence as hdmi


class HdmiPresenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.connector('card0-eDP-1','connected')

    def connector(self,name,state):
        p=self.root/name;p.mkdir();(p/'status').write_text(state);return p

    def result(self):return hdmi.report(self.root)

    def test_pci_hdmi_connected_needs_no_usb_edid_mode_or_enabled_picture(self):
        self.connector('card0-HDMI-A-1','connected')
        self.connector('card1-HDMI-B-2','disconnected')
        r=self.result();self.assertIs(r['hdmi_connected'],True);self.assertEqual(r['count'],1)
        self.assertTrue(r['coverage_complete'])
        with mock.patch.object(hdmi,'report',return_value=r):
            self.assertEqual(api_bridge.call({'name':'RF_USBHDMIIsUsed','args':{}}),r)
            self.assertEqual(api_bridge.call({'name':'RF_USBHDMIIsUsed','args':{'metric':'hdmi_presence'}}),r)
        for value in ['usb','',False,1]:
            with self.subTest(value=value),self.assertRaises(ValueError):
                api_bridge.call({'name':'RF_USBHDMIIsUsed','args':{'metric':value}})

    def test_only_other_transports_is_known_negative_without_inference(self):
        self.connector('card0-DP-1','unknown')
        r=self.result();self.assertIs(r['hdmi_connected'],False);self.assertEqual(r['count'],0)
        self.assertEqual(r['connectors'],[])

    def test_unknown_and_missing_hdmi_state_never_become_false(self):
        p=self.connector('card0-HDMI-A-1','unknown')
        r=self.result();self.assertIsNone(r['hdmi_connected']);self.assertFalse(r['available'])
        (p/'status').unlink();r=self.result();self.assertIsNone(r['hdmi_connected'])
        self.assertEqual(r['connectors'][0]['errno'],errno.ENOENT)

    def test_partial_positive_is_true_with_count_only_a_lower_bound(self):
        self.connector('card0-HDMI-A-1','connected');self.connector('card0-HDMI-A-2','unknown')
        r=self.result();self.assertTrue(r['hdmi_connected']);self.assertEqual(r['minimum_count'],1)
        self.assertIsNone(r['count']);self.assertFalse(r['coverage_complete'])

    def test_transition_discards_positive_and_inventory_change_fails(self):
        self.connector('card0-HDMI-A-1','connected')
        with mock.patch.object(hdmi.display_state,'state',side_effect=['connected','disconnected']):
            r=self.result();self.assertIsNone(r['hdmi_connected'])
            self.assertEqual(r['connectors'][0]['errno'],errno.EAGAIN)
        paths=hdmi.display_state.paths(self.root)
        with mock.patch.object(hdmi.display_state,'paths',side_effect=[paths,paths[:-1]]):
            with self.assertRaises(OSError) as error:self.result()
            self.assertEqual(error.exception.errno,errno.EAGAIN)

    def test_no_drm_and_duplicate_alias_are_unavailable(self):
        (self.root/'card0-eDP-1'/'status').unlink();(self.root/'card0-eDP-1').rmdir()
        with self.assertRaises(OSError) as error:self.result()
        self.assertEqual(error.exception.errno,errno.ENODEV)
        p=self.connector('card0-HDMI-A-1','disconnected')
        (self.root/'card1-HDMI-A-1').symlink_to(p)
        r=self.result();self.assertIsNone(r['hdmi_connected']);self.assertIsNone(r['count'])
        self.assertEqual(r['connectors'][1]['errno'],errno.EPROTO)


if __name__=='__main__':unittest.main()
