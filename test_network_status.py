# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import errno
import sys
import tempfile
import types
import unittest
from unittest import mock
import api_bridge
import linux_services as services
import network_status as n

class BusError(Exception):
    def __init__(self,name):self.name=name
    def get_dbus_name(self):return 'org.freedesktop.DBus.Error.'+self.name
class BusBoolean(int):pass

class NetworkStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def device(self,name,index,wifi=False,flags='0x1',carrier='1'):
        p=self.root/name;p.mkdir();(p/'device').mkdir();(p/'ifindex').write_text(str(index));(p/'flags').write_text(flags);(p/'carrier').write_text(carrier);(p/'operstate').write_text('up')
        if wifi:(p/'wireless').mkdir()
        return p
    def nm(self,kinds,owner=':1.42'):
        return {'owner':owner,'interfaces':{name:{'device_type':kind,'kind':'wwan' if kind==8 else n.TYPES.get(kind),'control_interface':name} for name,kind in kinds.items()}}
    def report(self,mapping):
        with mock.patch.object(n,'manager_snapshot',return_value=self.nm(mapping)):return n.report(self.root)
    def test_physical_types_preserve_priority_and_exclude_virtual_tunnels(self):
        self.device('eth0',1);self.device('wwan0',2);self.device('wlan0',3,True)
        p=self.root/'tun0';p.mkdir();(p/'operstate').write_text('up')
        r=self.report({'eth0':1,'wwan0':8,'wlan0':2,'tun0':16})
        self.assertTrue(r['available']);self.assertTrue(r['complete']);self.assertEqual(r['primary_type'],'ethernet');self.assertEqual(r['connected_types'],['ethernet','wwan','wifi']);self.assertEqual(len(r['interfaces']),3)
    def test_cellular_ip_interface_is_not_ethernet(self):
        self.device('wwan0',9)
        r=self.report({'wwan0':8});self.assertEqual(r['primary_type'],'wwan');self.assertEqual(r['interfaces'][0]['type'],'wwan')
    def test_up_without_carrier_and_disabled_links_are_disconnected(self):
        self.device('eth0',1,carrier='0');p=self.device('wwan0',2,flags='0x0');(p/'carrier').unlink()
        r=self.report({'eth0':1,'wwan0':8});self.assertIs(r['connected'],False);self.assertIsNone(r['primary_type']);self.assertTrue(r['available'])
    def test_connected_unknown_hardware_is_not_guessed_ethernet(self):
        self.device('other0',1);self.device('wlan0',2,True)
        r=self.report({'other0':14,'wlan0':2});self.assertTrue(r['connected']);self.assertFalse(r['available']);self.assertFalse(r['complete']);self.assertIsNone(r['primary_type']);self.assertEqual(r['preferred_known_type'],'wifi')
    def test_unknown_lower_priority_does_not_erase_known_ethernet(self):
        self.device('eth0',1);self.device('other0',2)
        r=self.report({'eth0':1});self.assertTrue(r['available']);self.assertEqual(r['primary_type'],'ethernet');self.assertFalse(r['complete'])
    def test_manager_absence_does_not_guess_and_kernel_wifi_remains_known(self):
        self.device('wlan0',1,True)
        with mock.patch.object(n,'manager_snapshot',side_effect=OSError(errno.ENODEV,'Not running')):
            r=n.report(self.root)
        self.assertEqual(r['primary_type'],'wifi');self.assertEqual(r['errors'][0]['errno'],errno.ENODEV)
        self.device('eth0',2)
        with mock.patch.object(n,'manager_snapshot',side_effect=OSError(errno.EACCES,'Denied')):r=n.report(self.root)
        self.assertFalse(r['available']);self.assertIsNone(r['primary_type']);self.assertEqual(r['interfaces'][0]['type'],None)
    def test_census_or_manager_owner_change_invalidates_summary(self):
        self.device('eth0',1);original=n.physical(self.root)
        with mock.patch.object(n,'physical',side_effect=[original,{}]),mock.patch.object(n,'manager_snapshot',return_value=self.nm({'eth0':1})):
            r=n.report(self.root)
        self.assertFalse(r['available']);self.assertIsNone(r['connected']);self.assertIsNone(r['primary_type']);self.assertEqual(r['errors'][0]['errno'],errno.EAGAIN)
        with mock.patch.object(n,'manager_snapshot',side_effect=[self.nm({'eth0':1}),self.nm({'eth0':1},':1.43')]):r=n.report(self.root)
        self.assertFalse(r['available']);self.assertIsNone(r['primary_type'])
    def test_link_transition_invalid_flags_or_missing_carrier_is_unknown(self):
        p=self.device('eth0',1)
        with mock.patch.object(n,'link',side_effect=[{'connected':True},{'connected':False}]),mock.patch.object(n,'manager_snapshot',return_value=self.nm({'eth0':1})):r=n.report(self.root)
        self.assertFalse(r['available']);self.assertEqual(r['interfaces'][0]['errno'],errno.EAGAIN)
        for flags,carrier in [('1','1'),('0x1','2'),('0x1','')]:
            (p/'flags').write_text(flags);(p/'carrier').write_text(carrier);r=self.report({'eth0':1});self.assertIsNone(r['connected']);self.assertFalse(r['available'])
    def test_classification_conflicts_are_not_silently_accepted(self):
        self.device('wlan0',1,True);r=self.report({'wlan0':1});self.assertFalse(r['available']);self.assertEqual(r['interfaces'][0]['errno'],errno.EAGAIN)
    def bus(self,props=None,error=None):
        root=mock.Mock();root.GetDevices.return_value=[n.ROOT+'/Devices/1'];device=mock.Mock();device.Get.return_value=8;device.GetAll.return_value={'Interface':'cdc-wdm0','IpInterface':'wwan0','DeviceType':8} if props is None else props
        bus=mock.Mock();bus.call_blocking.return_value=':1.42';bus.get_object.side_effect=lambda owner,path,**kw:root if path==n.ROOT else device
        if error:bus.call_blocking.side_effect=BusError(error)
        module=types.SimpleNamespace(SystemBus=mock.Mock(return_value=bus),DBusException=BusError,Boolean=BusBoolean)
        return mock.patch.dict(sys.modules,{'dbus':module}),bus,root,device
    def test_nm_reads_existing_unique_owner_and_modem_data_interface(self):
        context,bus,root,device=self.bus()
        with context:r=n.manager_snapshot()
        self.assertEqual(r['interfaces']['wwan0']['kind'],'wwan');self.assertEqual(r['interfaces']['wwan0']['control_interface'],'cdc-wdm0')
        self.assertTrue(all(c.args[0]==':1.42' and c.kwargs=={'introspect':False} for c in bus.get_object.call_args_list))
        device.GetAll.assert_called_once();device.Get.assert_called_once();self.assertEqual(device.Get.call_args.args,(n.DEVICE+'.Modem','CurrentCapabilities'));self.assertEqual(device.GetAll.call_args.args,(n.DEVICE,));self.assertEqual(root.GetDevices.call_count,2)
    def test_absent_denied_and_expired_manager_does_not_activate_service(self):
        for error,wanted in [('NameHasNoOwner',errno.ENODEV),('AccessDenied',errno.EACCES),('NoReply',errno.ETIMEDOUT)]:
            context,bus,root,device=self.bus(error=error)
            with context,self.assertRaises(OSError) as e:n.manager_snapshot()
            self.assertEqual(e.exception.errno,wanted);bus.get_object.assert_not_called()
        context,bus,*_=self.bus()
        with context,mock.patch.object(n.time,'monotonic',side_effect=[0,6]),self.assertRaises(OSError) as e:n.manager_snapshot()
        self.assertEqual(e.exception.errno,errno.ETIMEDOUT);bus.call_blocking.assert_not_called()
    def test_manager_malformed_or_changing_device_inventory_is_rejected(self):
        for props in [{'Interface':'wwan0','IpInterface':'','DeviceType':True},{'Interface':'wwan0','IpInterface':'../bad','DeviceType':8},{'Interface':'wwan0','DeviceType':8}]:
            context,*_=self.bus(props)
            with context,self.assertRaises(OSError) as e:n.manager_snapshot()
            self.assertEqual(e.exception.errno,errno.EPROTO)
        context,bus,root,device=self.bus();root.GetDevices.side_effect=[[n.ROOT+'/Devices/1'],[]]
        with context,self.assertRaises(OSError) as e:n.manager_snapshot()
        self.assertEqual(e.exception.errno,errno.EAGAIN)
        context,bus,root,device=self.bus();bus.call_blocking.side_effect=[':1.42',':1.43']
        with context,self.assertRaises(OSError) as e:n.manager_snapshot()
        self.assertEqual(e.exception.errno,errno.EAGAIN)
    def test_modem_classification_requires_cellular_current_capabilities(self):
        for caps,wanted,excluded in [(1,None,True),(0,None,False),(2,'wwan',False),(4|8,'wwan',False),(64,'wwan',False),(16,None,False),(1|8,None,False)]:
            context,bus,root,device=self.bus();device.Get.return_value=caps
            with context:r=n.manager_snapshot()
            self.assertEqual(r['interfaces']['wwan0']['kind'],wanted);self.assertEqual(r['interfaces']['wwan0']['excluded'],excluded)
        context,bus,root,device=self.bus();device.Get.side_effect=BusError('UnknownInterface')
        with context:r=n.manager_snapshot()
        self.assertIsNone(r['interfaces']['wwan0']['kind']);self.assertEqual(r['interfaces']['wwan0']['classification_error']['errno'],errno.ENODATA)

    def test_pots_and_declared_virtual_devices_are_outside_preference_scope(self):
        self.device('wwan0',1);self.device('p2p0',2,True)
        nm=self.nm({});nm['interfaces']={'wwan0':{'device_type':8,'kind':None,'excluded':True},'p2p0':{'device_type':30,'kind':None,'excluded':True}}
        with mock.patch.object(n,'manager_snapshot',return_value=nm):r=n.report(self.root)
        self.assertFalse(r['connected']);self.assertTrue(r['available']);self.assertIsNone(r['primary_type']);self.assertTrue(all(x['scope_applicable'] is False for x in r['interfaces']))

    def test_zero_hardware_is_known_empty_and_arguments_are_strict(self):
        r=self.report({});self.assertFalse(r['connected']);self.assertTrue(r['available']);self.assertTrue(r['complete']);self.assertEqual(r['interfaces'],[])
        with self.assertRaises(ValueError):api_bridge.call({'name':'RF_Net_Connected_Type','args':{'scan':True}})

class BluetoothClassTests(unittest.TestCase):
    def test_all_recovered_major_classes_and_other_are_decoded(self):
        for major,label in {**services.BLUETOOTH_MAJOR,0:'Other',10:'Other'}.items():
            r=services.bluetooth_class((major<<8)|0xA00005);self.assertTrue(r['available']);self.assertEqual(r['major'],label);self.assertEqual(r['major_code'],major)
    def test_absent_invalid_or_boolean_class_is_not_inferred(self):
        for raw in [None,True,False,-1,2**24,'0x500',BusBoolean(1)]:
            r=services.bluetooth_class(raw,BusBoolean);self.assertFalse(r['available']);self.assertIsNone(r['major']);self.assertIsNone(r['raw'])
        self.assertEqual(services.bluetooth_class(0)['major_code'],0)
    def test_major_class_is_added_without_changing_connection_count(self):
        from test_hardware_availability import AvailabilityTests
        context,*_=AvailabilityTests().bluez({'/d':{'org.bluez.Device1':{'Connected':True,'Class':0x2540}}})
        with context:
            self.assertEqual(api_bridge.call({'name':'RF_BTConnectedNum'}),1)
            r=api_bridge.call({'name':'RF_BTConnectedType'})[0];self.assertEqual(r['device_class']['major'],'Peripheral')
    def test_bluez_owner_change_does_not_produce_stale_known_connections(self):
        from test_hardware_availability import AvailabilityTests
        context,module,bus,remote=AvailabilityTests().bluez()
        bus.call_blocking.side_effect=[':1.42',':1.43']
        with context,self.assertRaises(OSError) as e:services.bluetooth()
        self.assertEqual(e.exception.errno,errno.EAGAIN)

if __name__=='__main__':unittest.main()
