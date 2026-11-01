# SPDX-License-Identifier: GPL-2.0-only
import errno
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock
import api_bridge
import battery_diagnostics as battery
import linux_services as services


class BusError(Exception):
    def __init__(self,name):self.name=name
    def get_dbus_name(self):return 'org.freedesktop.DBus.Error.'+self.name


class BusBoolean(int):pass


class AvailabilityTests(unittest.TestCase):
    def bluez(self,objects=None,error=None):
        remote=mock.Mock()
        remote.GetManagedObjects.return_value={} if objects is None else objects
        if error:remote.GetManagedObjects.side_effect=BusError(error)
        bus=mock.Mock();bus.get_object.return_value=remote;bus.call_blocking.return_value=':1.42'
        module=types.SimpleNamespace(SystemBus=mock.Mock(return_value=bus),DBusException=BusError,Boolean=BusBoolean)
        return mock.patch.dict(sys.modules,{'dbus':module}),module,bus,remote

    def test_known_bluetooth_empty_and_zero_are_valid_with_fixed_read_transport(self):
        context,module,bus,remote=self.bluez({'/device':{'org.bluez.Device1':{'Connected':False}}})
        with context:
            self.assertEqual(api_bridge.call({'name':'RF_BTConnectedNum'}),0)
            self.assertIs(api_bridge.call({'name':'RF_BTIsUsed'}),False)
            self.assertEqual(api_bridge.call({'name':'RF_BTConnectedType'}),[])
        self.assertEqual(bus.get_object.call_args,mock.call(':1.42','/',introspect=False))
        self.assertEqual(bus.call_blocking.call_args,mock.call('org.freedesktop.DBus','/org/freedesktop/DBus',
                         'org.freedesktop.DBus','GetNameOwner','s',('org.bluez',),timeout=5))
        self.assertEqual(remote.GetManagedObjects.call_args,mock.call(dbus_interface='org.freedesktop.DBus.ObjectManager',timeout=5))

    def test_bluetooth_provider_failures_are_errors_instead_of_disconnected(self):
        for name,code in [('ServiceUnknown',errno.ENODEV),('AccessDenied',errno.EACCES),('NoReply',errno.ETIMEDOUT),('Failed',errno.EIO)]:
            context,*_=self.bluez(error=name)
            with self.subTest(error=name),context:
                for query in ['RF_BTConnectedNum','RF_BTIsUsed','RF_BTConnectedType']:
                    with self.assertRaises(OSError) as error:api_bridge.call({'name':query})
                    self.assertEqual(error.exception.errno,code)

    def test_absent_bluetooth_daemon_is_not_activated(self):
        context,module,bus,remote=self.bluez()
        bus.call_blocking.side_effect=BusError('NameHasNoOwner')
        with context,self.assertRaises(OSError) as error:services.bluetooth()
        self.assertEqual(error.exception.errno,errno.ENODEV)
        bus.get_object.assert_not_called();remote.GetManagedObjects.assert_not_called()

    def test_unknown_connection_status_cannot_be_counted_as_disconnected(self):
        for connected in [None,0,'false',BusBoolean(2)]:
            context,*_=self.bluez({'/device':{'org.bluez.Device1':{'Connected':connected}}})
            with self.subTest(connected=connected),context,self.assertRaises(OSError) as error:services.bluetooth()
            self.assertEqual(error.exception.errno,errno.EPROTO)
        context,*_=self.bluez([])
        with context,self.assertRaises(OSError):services.bluetooth()

    def test_optional_bad_metadata_does_not_erase_known_connections(self):
        good={'Connected':BusBoolean(1),'Address':'00:11:22:33:44:55','Alias':'Test keyboard','Icon':'input-keyboard','UUIDs':['00001812-0000-1000-8000-00805f9b34fb']}
        bad={'Connected':True,'Address':'bad','Alias':'\x00','UUIDs':['bad']}
        context,*_=self.bluez({'/a':{'org.bluez.Device1':good},'/b':{'org.bluez.Device1':bad}})
        with context:
            self.assertEqual(api_bridge.call({'name':'RF_BTConnectedNum'}),2)
            rows=services.bluetooth()
        self.assertEqual(rows[0]['name'],'Test keyboard');self.assertEqual(rows[0]['uuids'],good['UUIDs'])
        self.assertIsNone(rows[1]['address']);self.assertIsNone(rows[1]['name']);self.assertIsNone(rows[1]['uuids'])
        self.assertEqual(set(rows[1]['unavailable_metadata_fields']),{'address','name','uuids'})

    def test_brightness_failures_preserve_good_and_true_zero_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name,actual,maximum in [('a-zero','0','100'),('b-good','50','100'),('c-missing',None,'100'),('d-range','101','100'),('e-invalid','NaN','100'),('f-denominator','0','0')]:
                p=root/name;p.mkdir();(p/'max_brightness').write_text(maximum)
                if actual is not None:(p/'actual_brightness').write_text(actual)
            rows=services.monitor_brightness(root)
            self.assertEqual([r.get('percent') for r in rows],[0,50,None,None,None,None])
            self.assertEqual([r['available'] for r in rows],[True,True,False,False,False,False])
            with self.assertRaises(OSError):services.monitor_brightness(root/'absent')

    def test_changed_brightness_range_is_not_a_false_percentage(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'panel';p.mkdir();(p/'max_brightness').write_text('100');(p/'actual_brightness').write_text('50')
            original=Path.read_text;calls=0
            def changing(path,*args,**kwargs):
                nonlocal calls
                if path==p/'max_brightness':
                    calls+=1;return '100' if calls==1 else '200'
                return original(path,*args,**kwargs)
            with mock.patch.object(Path,'read_text',changing):rows=services.monitor_brightness(root)
            self.assertEqual(rows[0]['errno'],errno.EAGAIN);self.assertNotIn('percent',rows[0])

    def test_ac_absence_or_invalid_status_is_not_offline_and_arguments_are_strict(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'online'
            for raw,wanted in [('0',False),('1',True)]:
                p.write_text(raw);self.assertIs(services.ac_online(p),wanted)
            for raw in ['', '2', '-1', 'yes']:
                p.write_text(raw)
                with self.assertRaises(OSError):services.ac_online(p)
            p.unlink()
            with self.assertRaises(OSError):services.ac_online(p)
        with mock.patch.object(services,'ac_online',side_effect=OSError(errno.EACCES,'Denied')):
            for name in ['BatteryHealthyTable_ACStatus','Power_Read_ACDCMode']:
                with self.assertRaises(OSError) as error:api_bridge.call({'name':name})
                self.assertEqual(error.exception.errno,errno.EACCES)
        for name in services.EMPTY_HW_READS:
            with self.assertRaises(ValueError):api_bridge.call({'name':name,'args':{'value':0}})

    def test_missing_battery_status_and_independent_cache_gate(self):
        self.assertIs(battery.battery_error(0),False);self.assertIs(battery.battery_error(128),True)
        for raw in [None,-1,256,True,'0']:
            self.assertIsNone(battery.battery_error(raw));self.assertIsNone(battery.legacy_pf_gate(raw))
        for raw,wanted in [(0,False),(64,False),(128,True),(192,False),(255,False)]:
            self.assertIs(battery.legacy_pf_gate(raw),wanted)

    def test_unknown_battery_full_status_is_unavailable_instead_of_not_full(self):
        self.assertIs(battery.is_full('Full'),True)
        for value in ['Charging','Discharging','Not charging']:self.assertIs(battery.is_full(value),False)
        for value in [None,'Unknown','',False]:self.assertIsNone(battery.is_full(value))

    def test_missing_or_invalid_fan_mode_is_not_reported_as_manual(self):
        spec=importlib.util.spec_from_file_location('fan_availability_frontend',Path(__file__).with_name('zenbook-hardware.py'))
        front=importlib.util.module_from_spec(spec);spec.loader.exec_module(front)
        for value in (0,1):self.assertIs(front.manual_fan_mode(value),True)
        self.assertIs(front.manual_fan_mode(2),False)
        for value in [None,-1,3,False,'2']:self.assertIsNone(front.manual_fan_mode(value))
        import field_reads
        with mock.patch.object(field_reads,'fan',side_effect=OSError(errno.ENODATA,'Unknown mode')):
            with self.assertRaises(OSError):front.api_field({'field':'fan.manual'})


if __name__=='__main__':unittest.main()
