# SPDX-License-Identifier: GPL-2.0-only
import errno
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import api_bridge
import input_state as p
import session_state


KEYS=(1<<30)|(1<<44)


def event(root,name,mask=KEYS):
    folder=root/name/'device/capabilities';folder.mkdir(parents=True)
    (folder/'key').write_text(format(mask,'x'));return root/name


def led(root,name,value='0',maximum='1'):
    folder=root/name;folder.mkdir();(folder/'brightness').write_text(value)
    (folder/'max_brightness').write_text(maximum);return folder


class InputMetadataTests(unittest.TestCase):
    def roots(self,temp):
        root=Path(temp);a=root/'input';b=root/'leds';a.mkdir();b.mkdir();return a,b

    def test_binary_led_consensus_and_native_key_word_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root,leds=self.roots(temp);a=event(root,'event0');event(root,'event1',1);event(root,'event2',0)
            (a/'device/capabilities/key').write_text('1 '+format(KEYS,'x'))
            led(leds,'input0::numlock','1');led(leds,'input1::numlock','1')
            r=p.report(root,leds)
        self.assertEqual(r['keyboard_num'],1);self.assertTrue(r['num_lock'])
        self.assertTrue(r['num_lock_available']);self.assertTrue(r['keyboard_inventory_complete'])

    def test_unreadable_event_withholds_exact_count_but_preserves_observed_keyboard(self):
        with tempfile.TemporaryDirectory() as temp:
            root,leds=self.roots(temp);event(root,'event0');bad=event(root,'event1');(bad/'device/capabilities/key').unlink()
            r=p.report(root,leds)
        self.assertIsNone(r['keyboard_num']);self.assertEqual(r['observed_keyboard_num'],1)
        self.assertEqual(r['keyboards'][1]['errno'],errno.ENOENT)

    def test_invalid_or_missing_led_never_becomes_partial_consensus(self):
        for value,maximum in [('bad','1'),('2','1'),('1','255'),('','1')]:
            with self.subTest(value=value,maximum=maximum),tempfile.TemporaryDirectory() as temp:
                root,leds=self.roots(temp);event(root,'event0');led(leds,'input0::numlock','1');led(leds,'input1::numlock',value,maximum)
                r=p.report(root,leds)
            self.assertIsNone(r['num_lock']);self.assertFalse(r['num_lock_complete'])
            self.assertEqual(r['per_keyboard_num_lock'],[True])

    def test_missing_census_does_not_become_zero_and_absent_led_is_not_off(self):
        with tempfile.TemporaryDirectory() as temp:
            root,leds=self.roots(temp)
            r=p.report(root/'missing',leds/'missing')
            self.assertIsNone(r['keyboard_num']);self.assertIsNone(r['num_lock']);self.assertEqual(len(r['errors']),2)
            r=p.report(root,leds)
            self.assertEqual(r['keyboard_num'],0);self.assertIsNone(r['num_lock']);self.assertFalse(r['num_lock_available'])

    def test_disagreeing_leds_preserve_states_without_global_boolean(self):
        with tempfile.TemporaryDirectory() as temp:
            root,leds=self.roots(temp);led(leds,'input0::numlock','0');led(leds,'input1::numlock','1')
            r=p.report(root,leds)
        self.assertTrue(r['num_lock_complete']);self.assertIsNone(r['num_lock'])
        self.assertEqual(r['per_keyboard_num_lock'],[False,True])

    def test_malformed_capability_does_not_count_as_non_keyboard(self):
        for raw in ['bad-bitmap','-1','1'*17,'','0x10','1 '*65,'\xff']:
            with self.subTest(raw=raw),tempfile.TemporaryDirectory() as temp:
                root,leds=self.roots(temp);a=event(root,'event0');(a/'device/capabilities/key').write_bytes(raw.encode('latin1'))
                r=p.report(root,leds)
            self.assertIsNone(r['keyboard_num']);self.assertFalse(r['keyboards'][0]['available'])

    def test_changed_state_identity_or_inventory_withholds_aggregate(self):
        with tempfile.TemporaryDirectory() as temp:
            root,leds=self.roots(temp);a=event(root,'event0');led(leds,'input0::numlock')
            original=p.identity
            calls=0
            def changed(path):
                nonlocal calls
                if path==a:
                    calls+=1;return (1,1 if calls==1 else 2,'event0')
                return original(path)
            with mock.patch.object(p,'identity',side_effect=changed):r=p.report(root,leds)
            self.assertIsNone(r['keyboard_num'])
            with mock.patch.object(p,'led',side_effect=[False,True]):r=p.report(root,leds)
            self.assertIsNone(r['num_lock'])
            original_paths=p.paths;count=0
            def paths(folder,pattern):
                nonlocal count
                if folder==root:
                    count+=1
                    if count==2:return []
                return original_paths(folder,pattern)
            with mock.patch.object(p,'paths',side_effect=paths):r=p.report(root,leds)
            self.assertIsNone(r['keyboard_num']);self.assertEqual(r['errors'][0]['errno'],errno.EAGAIN)

    def test_original_api_routes_report_and_rejects_unused_arguments(self):
        with mock.patch.object(p,'report',return_value={'num_lock':True,'num_lock_available':True,'num_lock_complete':True,'keyboard_num':None,'note':'LED metadata'}) as read,mock.patch.object(session_state,'report',return_value={'available':False,'num_lock':None}):
            result=api_bridge.call({'name':'GetNum_Key'})
            self.assertIsNone(result['keyboard_num']);self.assertIsNone(result['num_lock'])
            self.assertTrue(result['num_lock_led_consensus']);self.assertFalse(result['num_lock_available'])
            with self.assertRaises(ValueError):api_bridge.call({'name':'GetNum_Key','args':{'ignored':True}})
            read.assert_called_once_with()


if __name__=='__main__':unittest.main()
