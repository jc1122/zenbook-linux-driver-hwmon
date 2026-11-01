# SPDX-License-Identifier: GPL-2.0-only
import errno
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import api_bridge
import linux_services
import usb_display as display


class UsbDisplayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.drm=self.root/'drm';self.typec=self.root/'typec'
        self.drm.mkdir();self.typec.mkdir();self.connector('card0-eDP-1')

    def connector(self,name,parent=None,state='connected'):
        if parent is None:parent=self.root/'pci-gpu'
        target=parent/'drm'/name;target.mkdir(parents=True,exist_ok=True)
        (target/'status').write_text(state);(self.drm/name).symlink_to(target)
        return target

    def mode(self,name='port0-partner.0',active='1',configuration='USB source [sink]',pin='C [D]'):
        p=self.typec/name;(p/'displayport').mkdir(parents=True,exist_ok=True)
        for key,value in [('svid','ff01'),('active',active),('displayport/configuration',configuration),('displayport/pin_assignment',pin)]:
            (p/key).write_text(value)
        return p

    def result(self):return display.report(self.drm,self.typec)

    def test_internal_display_only_is_negative_without_brand_name_queries(self):
        r=self.result();self.assertIs(r['usb_display'],False);self.assertTrue(r['coverage_complete'])
        with mock.patch.object(linux_services,'usb',side_effect=AssertionError('No product-name heuristic')),mock.patch.object(display,'report',return_value=r):
            self.assertEqual(api_bridge.call({'name':'RF_USBHDMIIsUsed','args':{'metric':'usb_display'}}),r)
            with self.assertRaises(ValueError):api_bridge.call({'name':'RF_USBHDMIIsUsed','args':{'device':'x'}})

    def test_real_usb_ancestry_is_positive_without_displaylink_branding(self):
        parent=self.root/'usb1'/'1-2';parent.mkdir(parents=True)
        (parent/'idVendor').write_text('1234');(parent/'idProduct').write_text('abcd')
        p=self.connector('card2-HDMI-A-1',parent)
        r=self.result();self.assertIs(r['usb_display'],True)
        self.assertEqual(r['connected_displays'][-1]['usb_device']['device'],'1-2')
        (p/'status').write_text('disconnected');self.assertIs(self.result()['usb_display'],False)

    def test_unmapped_external_and_virtual_displays_are_unknown(self):
        self.connector('card0-HDMI-A-1');r=self.result()
        self.assertIsNone(r['usb_display']);self.assertEqual(r['unmapped_external_displays'],['card0-HDMI-A-1'])
        self.connector('card3-DVI-I-1',self.root/'platform'/'evdi.0')
        self.assertIsNone(self.result()['usb_display'])

    def test_partner_sink_means_local_output_local_capability_does_not(self):
        self.mode('port0.0');self.assertIs(self.result()['usb_display'],False)
        p=self.mode();r=self.result();self.assertIs(r['usb_display'],True)
        self.assertEqual(r['typec_displayport'][0]['pin_assignment'],'D')
        self.assertEqual(r['typec_displayport'][0]['local_displayport_role'],'source')
        for active,configuration in [('0','USB source [sink]'),('1','[USB] source sink'),('1','USB [source] sink')]:
            (p/'active').write_text(active);(p/'displayport/configuration').write_text(configuration)
            self.assertIs(self.result()['usb_display'],False)

    def test_partial_errors_preserve_positive_usb_but_never_fake_negative(self):
        p=self.mode();(p/'displayport/pin_assignment').write_text('C D')
        r=self.result();self.assertIsNone(r['usb_display']);self.assertEqual(r['errors'][0]['errno'],errno.ENODATA)
        parent=self.root/'1-3';parent.mkdir();(parent/'idVendor').write_text('1234');(parent/'idProduct').write_text('abcd')
        self.connector('card2-DP-1',parent)
        r=self.result();self.assertIs(r['usb_display'],True);self.assertFalse(r['coverage_complete'])
        self.assertIsNone(display.report(self.root/'missing',self.root/'also-missing')['usb_display'])

    def test_connector_and_mode_changes_are_rejected(self):
        p=self.mode();original=display.read;calls=0
        def changing(path):
            nonlocal calls
            if path==p/'active':
                calls+=1
                return '1' if calls==1 else '0'
            return original(path)
        with mock.patch.object(display,'read',side_effect=changing):
            r=self.result();self.assertIsNone(r['usb_display']);self.assertEqual(r['errors'][0]['errno'],errno.EAGAIN)
        (p/'svid').write_text('0000');path=self.drm/'card0-eDP-1';calls=0
        def disconnecting(node):
            nonlocal calls
            if node==path/'status':
                calls+=1
                return 'connected' if calls==1 else 'disconnected'
            return original(node)
        with mock.patch.object(display,'read',side_effect=disconnecting):
            r=self.result();self.assertIsNone(r['usb_display']);self.assertEqual(r['errors'][0]['errno'],errno.EAGAIN)
        calls=0
        def changing_svid(node):
            nonlocal calls
            if node==p/'svid':
                calls+=1
                return '0000' if calls==1 else 'ff01'
            return original(node)
        with mock.patch.object(display,'read',side_effect=changing_svid):
            r=self.result();self.assertIsNone(r['usb_display']);self.assertEqual(r['errors'][0]['errno'],errno.EAGAIN)

    def test_unknown_status_or_malformed_attributes_are_unavailable(self):
        p=self.mode();(p/'active').write_text('2')
        self.assertIsNone(self.result()['usb_display'])
        (p/'active').write_text('1');(p/'displayport/configuration').write_text('[source] [USB]')
        self.assertIsNone(self.result()['usb_display'])
        (p/'svid').write_text('xxxx');(self.drm/'card0-eDP-1'/'status').write_text('unknown')
        self.assertIsNone(self.result()['usb_display'])


if __name__=='__main__':unittest.main()
