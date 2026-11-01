# SPDX-License-Identifier: GPL-2.0-only
import errno
import subprocess
import unittest
from unittest import mock

import api_bridge
import linux_services as services


class HardwareConfigTests(unittest.TestCase):
    def test_zero_level_is_available_and_mute_is_independent(self):
        for reply,percent,muted,effective in [('Volume: 0.00\n',0,False,0),
                                             ('Volume: 0.94 [MUTED]\n',94,True,0),
                                             ('Volume: 1.25\n',125,False,125)]:
            with self.subTest(reply=reply),mock.patch.object(services,'run',return_value=reply) as run:
                result=api_bridge.call({'name':'System_Read_VolumeLevel'})
            self.assertIs(result['available'],True)
            self.assertEqual((result['percent'],result['muted'],result['effective_percent']),
                             (percent,muted,effective))
            run.assert_called_once_with(['wpctl','get-volume','@DEFAULT_AUDIO_SINK@'],timeout=5)

    def test_malformed_or_nonfinite_audio_is_an_error(self):
        for reply in ['','Volume: NaN','Volume: inf','Volume: -0.01','Volume: 0.4garbage',
                      'Volume: 0.4 [NOT_MUTED]','Volume: 0.4\nVolume: 0.5',
                      'Volume: 1e300','Volume: 0..4','Volume: '+'9'*100]:
            with self.subTest(reply=reply),mock.patch.object(services,'run',return_value=reply):
                with self.assertRaises(OSError) as error:services.default_volume()
                self.assertEqual(error.exception.errno,errno.EPROTO)

    def test_audio_missing_timeout_and_provider_errors_are_typed(self):
        for failure,code in [(FileNotFoundError(),errno.ENODEV),
                             (subprocess.TimeoutExpired('wpctl',5),errno.ETIMEDOUT),
                             (OSError(errno.EACCES,'Denied'),errno.EACCES),
                             (OSError(errno.ENODATA,'No sink'),errno.ENODATA)]:
            with self.subTest(code=code),mock.patch.object(services,'run',side_effect=failure):
                with self.assertRaises(OSError) as error:services.default_volume()
                self.assertEqual(error.exception.errno,code)

    def test_config_keeps_multiple_backlights_and_partial_errors(self):
        rows=[{'device':'a','available':True,'percent':0},
              {'device':'b','available':False,'errno':errno.EIO,'error':'Read failed'}]
        with mock.patch.object(services,'monitor_brightness',return_value=rows),\
             mock.patch.object(services,'run',return_value='Volume: 0.94 [MUTED]'),\
             mock.patch.object(services.process_counters,'call',side_effect=AssertionError('Unrelated process read')),\
             mock.patch.object(services,'cpu',side_effect=AssertionError('Unrelated CPU read')):
            result=api_bridge.call({'name':'AppList_HardwareConfig'})
        self.assertIs(result['brightness']['available'],True)
        self.assertEqual(result['brightness']['devices'],rows)
        self.assertIs(result['volume']['muted'],True)
        self.assertNotIn('processes',result);self.assertNotIn('cpu',result);self.assertNotIn('memory_bytes',result)

    def test_display_error_does_not_erase_audio(self):
        with mock.patch.object(services,'monitor_brightness',side_effect=PermissionError(errno.EACCES,'Denied')),\
             mock.patch.object(services,'run',return_value='Volume: 0.00'):
            result=services.hardware_config()
        self.assertIs(result['brightness']['available'],False)
        self.assertEqual(result['brightness']['errno'],errno.EACCES)
        self.assertIs(result['volume']['available'],True)
        self.assertEqual(result['volume']['percent'],0)

    def test_audio_error_does_not_erase_display(self):
        rows=[{'device':'a','available':True,'percent':50}]
        with mock.patch.object(services,'monitor_brightness',return_value=rows),\
             mock.patch.object(services,'run',side_effect=OSError(errno.ENODEV,'No sink')):
            result=services.hardware_config()
        self.assertEqual(result['brightness']['devices'],rows)
        self.assertIs(result['volume']['available'],False)
        self.assertEqual(result['volume']['errno'],errno.ENODEV)
        self.assertNotIn('percent',result['volume'])

    def test_absent_and_failed_backlights_are_not_zero_brightness(self):
        for rows in [[],[{'device':'a','available':False,'errno':errno.EIO,'error':'Read failed'}]]:
            with self.subTest(rows=rows),mock.patch.object(services,'monitor_brightness',return_value=rows),\
                 mock.patch.object(services,'run',return_value='Volume: 0.94'):
                result=services.hardware_config()
            self.assertIs(result['brightness']['available'],False)
            self.assertNotIn('percent',result['brightness'])
            self.assertEqual(result['brightness']['devices'],rows)

    def test_unknown_arguments_rejected_before_any_read(self):
        with mock.patch.object(services,'monitor_brightness') as brightness,\
             mock.patch.object(services,'run') as run:
            for name in ['AppList_HardwareConfig','System_Read_VolumeLevel']:
                with self.subTest(name=name),self.assertRaises(ValueError):
                    api_bridge.call({'name':name,'args':{'device':'other'}})
                with self.assertRaises(ValueError):services.call(name,{'device':'other'})
        brightness.assert_not_called();run.assert_not_called()


if __name__=='__main__':unittest.main()
