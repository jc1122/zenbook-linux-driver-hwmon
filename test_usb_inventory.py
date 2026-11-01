# SPDX-License-Identifier: GPL-2.0-only
import errno
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import api_bridge
import usb_inventory as p


def port(root,bus,number,kind=9):
    path=root/f'usb{bus}'/f'{bus}-0:1.0'/f'usb{bus}-port{number}'
    (path/'firmware_node').mkdir(parents=True);acpi=f'ROOT.B{bus}.P{number}'
    (path.parent/'bInterfaceClass').write_text('09')
    (path/'connect_type').write_text('hotplug')
    (path/'firmware_node/path').write_text('\\'+acpi)
    return path,{'path':acpi,'type':kind,'connectable':1}


def device(root,name,hub=False):
    bus,chain=name.split('-');parts=chain.split('.')
    parent=root/('usb'+bus if len(parts)==1 else bus+'-'+'.'.join(parts[:-1]))
    parent.mkdir(exist_ok=True)
    actual=parent/name;actual.mkdir();path=root/name;path.symlink_to(actual)
    values={'idVendor':'1234','idProduct':'abcd','bDeviceClass':'09' if hub else '00',
            'busnum':name.split('-')[0],'devnum':'2','product':'Example USB device','manufacturer':'Example',
            'speed':'5000','removable':'removable','bcdDevice':'0100','version':'3.10','bConfigurationValue':'1'}
    for k,v in values.items():(path/k).write_text(v)
    iface=path/(name+':1.0');iface.mkdir();(iface/'bInterfaceClass').write_text('09' if hub else '03')
    port=parent/(bus+'-0:1.0' if len(parts)==1 else parent.name+':1.0')/(parent.name+'-port'+parts[-1])
    if port.exists():(path/'port').symlink_to(port)
    return path


def downstream(root,parent,number,kind=None,connect_type='hotplug'):
    path=(root/parent)/(parent+':1.0')/(parent+'-port'+str(number))
    path.mkdir(parents=True);(path.parent/'bInterfaceClass').write_text('09');(path/'connect_type').write_text(connect_type)
    row=None
    if kind is not None:
        (path/'firmware_node').mkdir();acpi=parent+'.PORT'+str(number);(path/'firmware_node/path').write_text('\\'+acpi)
        row={'path':acpi,'type':kind,'connectable':1}
    return path,row


def caps(*rows):return {'ports':list(rows),'complete':True}


def call(name,report,args=None):
    with mock.patch.object(p,'report',return_value=report):return api_bridge.call({'name':name,'args':args or {}})


class UsbInventoryTests(unittest.TestCase):
    def test_unknown_connection_is_not_false_or_an_exact_zero_count(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);port(root,1,1);device(root,'1-1');r=p.report(root,caps())
        self.assertIsNone(call('RF_USBISTYPEC',r)['type_c'])
        for name in ['RF_USB_A_Num','RF_USB_C_Num']:
            out=call(name,r);self.assertIsNone(out['count']);self.assertEqual(out['observed_count'],0);self.assertFalse(out['available'])
        self.assertEqual(call('RF_USBNum',r),1)

    def test_positive_c_survives_unclassified_other_connection(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);a,row=port(root,1,1);port(root,1,2);device(root,'1-1');device(root,'1-2')
            r=p.report(root,caps(row))
        self.assertTrue(call('RF_USBISTYPEC',r)['type_c']);self.assertIsNone(call('RF_USB_C_Num',r)['count'])
        self.assertTrue(call('RF_USBISTYPEC',r,{'device':'1-1'})['type_c'])
        self.assertIsNone(call('RF_USBISTYPEC',r,{'device':'1-2'})['type_c'])

    def test_empty_hub_is_a_connection_while_legacy_device_count_excludes_hubs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);a,row=port(root,1,1);device(root,'1-1',True);r=p.report(root,caps(row))
        self.assertEqual(call('RF_USBNum',r),0);self.assertEqual(call('RF_USBPort',r),[])
        self.assertTrue(call('RF_USBISTYPEC',r)['type_c']);self.assertEqual(call('RF_USB_C_Num',r)['count'],1)
        self.assertTrue(call('RF_USBISTYPEC',r,{'device':'1-1'})['type_c'])

    def test_usb2_and_usb3_peer_halves_count_once_with_devices_on_both(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);a,ar=port(root,1,1);b,br=port(root,2,1)
            (a/'peer').symlink_to(b);(b/'peer').symlink_to(a)
            for name,hub in [('1-1',True),('2-1',True),('1-1.1',False),('2-1.1',False)]:device(root,name,hub)
            r=p.report(root,caps(ar,br))
        self.assertEqual(call('RF_USBNum',r),2);self.assertIsNone(call('RF_USB_C_Num',r)['count'])
        self.assertEqual(call('RF_USB_C_Num',r,{'scope':'host'})['socket_count'],1)
        self.assertEqual(call('RF_USB_C_Num',r,{'scope':'host'})['count'],4)
        self.assertEqual(len({row['host_connection']['port_group'] for row in r['all_devices']}),1)

    def test_same_numbers_and_descriptors_without_links_are_distinct_ports(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);a,ar=port(root,1,1);b,br=port(root,2,1)
            device(root,'1-1');device(root,'2-1');r=p.report(root,caps(ar,br))
        self.assertEqual(call('RF_USBNum',r),2);self.assertEqual(call('RF_USB_C_Num',r)['count'],2)

    def test_registered_typec_association_supplies_type_and_merges_aliases(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);a,ar=port(root,1,1);b,br=port(root,2,1)
            physical=root/'typec/port0';physical.mkdir(parents=True);classroot=root/'class-typec';classroot.mkdir();(classroot/'port0').symlink_to(physical)
            (a/'connector').symlink_to(physical);(b/'connector').symlink_to(physical)
            device(root,'1-1');device(root,'2-1');r=p.report(root,caps(),classroot)
        self.assertEqual(call('RF_USB_C_Num',r)['count'],2)
        self.assertEqual(call('RF_USB_C_Num',r)['socket_count'],1)
        self.assertTrue(call('RF_USBISTYPEC',r)['type_c'])

    def test_conflicting_peer_classifications_are_unknown_not_two_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);a,ar=port(root,1,1,0);b,br=port(root,2,1,9)
            (a/'peer').symlink_to(b);(b/'peer').symlink_to(a);device(root,'1-1');device(root,'2-1')
            r=p.report(root,caps(ar,br))
        self.assertIsNone(call('RF_USB_C_Num',r)['count']);self.assertIsNone(call('RF_USBISTYPEC',r)['type_c'])
        self.assertTrue(all(row['host_connection']['group_errno']==errno.EPROTO for row in r['devices']))

    def test_nonreciprocal_or_unregistered_association_does_not_guess(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);a,ar=port(root,1,1);b,br=port(root,2,1);(a/'peer').symlink_to(b);device(root,'1-1')
            r=p.report(root,caps(ar,br));self.assertIsNone(call('RF_USB_C_Num',r)['count'])
            self.assertEqual(r['devices'][0]['host_connection']['errno'],errno.EPROTO)
            (a/'peer').unlink();unregistered=root/'fake/port0';unregistered.mkdir(parents=True);(a/'connector').symlink_to(unregistered)
            r=p.report(root,caps(ar));self.assertIsNone(call('RF_USBISTYPEC',r)['type_c'])

    def test_reciprocal_links_across_different_controllers_do_not_merge(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);other=root/'other-controller';other.mkdir()
            a,ar=port(root,1,1);b,br=port(other,2,1)
            (a/'peer').symlink_to(b);(b/'peer').symlink_to(a);device(root,'1-1')
            r=p.report(root,caps(ar,br))
        self.assertEqual(call('RF_USBNum',r),1)
        self.assertIsNone(call('RF_USB_C_Num',r)['count'])
        self.assertEqual(r['devices'][0]['host_connection']['errno'],errno.EPROTO)

    def test_missing_or_bad_essential_fields_preserve_rows_and_withhold_count(self):
        for field,value in [('idVendor',None),('idProduct','bad'),('bDeviceClass','?'),('busnum','2'),('devnum','0')]:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);a,ar=port(root,1,1);b,br=port(root,1,2);bad=device(root,'1-1');device(root,'1-2')
                if value is None:(bad/field).unlink()
                else:(bad/field).write_text(value)
                r=p.report(root,caps(ar,br))
            self.assertEqual([row['available'] for row in r['devices']],[False,True])
            self.assertNotIn('vendor_id',r['devices'][0])
            with self.assertRaises(OSError):call('RF_USBNum',r)
            self.assertEqual(len(call('RF_USBPort',r)),2)

    def test_optional_fields_can_fail_without_erasing_presence(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);a,ar=port(root,1,1);d=device(root,'1-1');(d/'manufacturer').unlink();(d/'speed').write_text('nan');(d/'bcdDevice').write_text('wrong')
            r=p.report(root,caps(ar))
        self.assertEqual(call('RF_USBNum',r),1);self.assertTrue(call('RF_USBISTYPEC',r)['type_c'])
        self.assertIsNone(r['devices'][0]['speed_mbit']);self.assertIn('manufacturer',r['devices'][0]['metadata_errors'])

    def test_changed_device_identity_or_topology_never_commits_old_identifiers(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);a,ar=port(root,1,1);d=device(root,'1-1');original=p.essential;calls=0
            def fields(path):
                nonlocal calls
                result=original(path);calls+=1
                if calls==3:result['devnum']+=1
                return result
            with mock.patch.object(p,'essential',side_effect=fields):r=p.report(root,caps(ar))
            self.assertFalse(r['devices'][0]['available']);self.assertNotIn('vendor_id',r['devices'][0])
            with mock.patch.object(p,'inventory_paths',side_effect=[[d],[]]):
                with self.assertRaises(OSError) as error:p.report(root,caps(ar))
            self.assertEqual(error.exception.errno,errno.EAGAIN)

    def test_empty_readable_tree_and_failed_root_are_distinct(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);r=p.report(root,caps())
            self.assertEqual(call('RF_USBNum',r),0);self.assertFalse(call('RF_USBISTYPEC',r)['type_c'])
            self.assertEqual(call('RF_USB_C_Num',r)['count'],0)
            with self.assertRaises(OSError):p.report(root/'missing',caps())

    def test_arguments_are_validated_before_inventory(self):
        for name in p.NAMES:
            with self.subTest(name=name),mock.patch.object(p,'report') as read:
                with self.assertRaises(ValueError):api_bridge.call({'name':name,'args':{'invented':True}})
                if name=='RF_USBISTYPEC':
                    for device in [True,'usb1','1-1:1.0','../1-1']:
                        with self.assertRaises(ValueError):api_bridge.call({'name':name,'args':{'device':device}})
                read.assert_not_called()

    def test_dock_child_uses_immediate_A_socket_instead_of_laptop_C_socket(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);_,host=port(root,1,1,9);device(root,'1-1',True)
            _,leaf=downstream(root,'1-1',2,0);device(root,'1-1.2');r=p.report(root,caps(host,leaf))
        child=next(x for x in r['devices'] if x['device']=='1-1.2')
        self.assertEqual(child['connector'],'A');self.assertEqual(child['host_connection']['connector'],'C')
        self.assertFalse(call('RF_USBISTYPEC',r,{'device':'1-1.2'})['type_c'])
        self.assertTrue(call('RF_USBISTYPEC',r,{'device':'1-1.2','scope':'host'})['type_c'])
        self.assertEqual(call('RF_USB_A_Num',r)['count'],1);self.assertEqual(call('RF_USB_C_Num',r)['count'],1)
        self.assertEqual(call('RF_USB_A_Num',r,{'scope':'host'})['count'],0)

    def test_unknown_dock_socket_never_inherits_known_root_type(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);_,host=port(root,1,1,9);device(root,'1-1',True)
            downstream(root,'1-1',2);device(root,'1-1.2');r=p.report(root,caps(host))
        self.assertIsNone(call('RF_USBISTYPEC',r,{'device':'1-1.2'})['type_c'])
        count=call('RF_USB_C_Num',r);self.assertIsNone(count['count']);self.assertEqual(count['observed_count'],1)
        self.assertTrue(call('RF_USBISTYPEC',r,{'device':'1-1.2','scope':'host'})['type_c'])

    def test_unknown_connect_type_does_not_treat_UPC_connectivity_as_user_visibility(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,row=port(root,1,1,9);(path/'connect_type').write_text('unknown');device(root,'1-1')
            r=p.report(root,caps(row))
        self.assertTrue(call('RF_USBISTYPEC',r)['type_c']);self.assertIsNone(call('RF_USB_C_Num',r)['count'])

    def test_hardwired_internal_connections_are_excluded_from_user_socket_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,row=port(root,1,1,255);(path/'connect_type').write_text('hardwired');device(root,'1-1')
            r=p.report(root,caps(row))
        self.assertEqual(call('RF_USBNum',r),1)
        self.assertEqual(call('RF_USB_C_Num',r)['count'],0);self.assertEqual(call('RF_USB_A_Num',r)['count'],0)

    def test_nested_hub_port_and_USB2_USB3_peer_socket_count_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);_,a=port(root,1,1,9);_,b=port(root,2,1,9)
            device(root,'1-1',True);device(root,'2-1',True)
            pa,aa=downstream(root,'1-1',2,0);pb,bb=downstream(root,'2-1',2,0)
            (pa/'peer').symlink_to(pb);(pb/'peer').symlink_to(pa)
            device(root,'1-1.2');device(root,'2-1.2');r=p.report(root,caps(a,b,aa,bb))
        self.assertEqual(call('RF_USB_A_Num',r)['count'],2)
        self.assertEqual(call('RF_USB_A_Num',r)['socket_count'],1)
        self.assertTrue(all(x['connector']=='A' for x in r['devices']))

    def test_missing_misassociated_or_nonlink_attachment_metadata_stays_unknown(self):
        for mode in ['missing','wrong','notlink']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);_,a=port(root,1,1,9);other,_=port(root,1,2,0);d=device(root,'1-1');(d/'port').unlink()
                if mode=='wrong':(d/'port').symlink_to(other)
                if mode=='notlink':(d/'port').write_text('not a link')
                r=p.report(root,caps(a))
            self.assertIsNone(call('RF_USBISTYPEC',r)['type_c']);self.assertIsNone(call('RF_USB_C_Num',r)['count'])
            self.assertEqual(call('RF_USBNum',r),1)

    def test_typec_link_on_downstream_socket_is_not_a_host_classification(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);_,host=port(root,1,1,0);device(root,'1-1',True);leaf,_=downstream(root,'1-1',2)
            physical=root/'typec/port0';physical.mkdir(parents=True);classroot=root/'class-typec';classroot.mkdir();(classroot/'port0').symlink_to(physical)
            (leaf/'connector').symlink_to(physical);device(root,'1-1.2');r=p.report(root,caps(host),classroot)
        self.assertTrue(call('RF_USBISTYPEC',r,{'device':'1-1.2'})['type_c'])
        self.assertFalse(call('RF_USBISTYPEC',r,{'device':'1-1.2','scope':'host'})['type_c'])
        self.assertEqual(call('RF_USB_C_Num',r)['count'],1);self.assertEqual(call('RF_USB_A_Num',r)['count'],1)

    def test_detailed_versions_preserve_specification_firmware_and_link_speed_quantities(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);_,a=port(root,1,1,0);_,b=port(root,1,2,0);x=device(root,'1-1');y=device(root,'1-2')
            (x/'version').write_text(' 2.01\n');(y/'version').write_text('3.20');r=p.report(root,caps(a,b))
        self.assertEqual(call('RF_USBNum',r),2);report=call('RF_USBNum',r,{'detailed':True})
        self.assertEqual(report['usb_specification_bcd_counts']['0320'],1);self.assertEqual(report['other_usb_specification_bcd_counts'],{'0201':1})
        self.assertTrue(report['version_coverage_complete'])
        self.assertEqual(r['devices'][0]['firmware_bcd'],'0100');self.assertEqual(r['devices'][0]['speed_mbit'],'5000')

    def test_bad_optional_USB_specification_keeps_device_and_partial_distribution(self):
        for bad in ['3.2','not a version','999.00']:
            with self.subTest(bad=bad),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);_,row=port(root,1,1,0);d=device(root,'1-1');(d/'version').write_text(bad);r=p.report(root,caps(row))
            self.assertEqual(call('RF_USBNum',r),1);self.assertIsNone(r['devices'][0]['usb_specification_bcd'])
            report=call('RF_USBNum',r,{'detailed':True});self.assertEqual(report['unknown_usb_specification_count'],1);self.assertFalse(report['version_coverage_complete'])

    def test_new_selectors_reject_wrong_types_before_inventory(self):
        bad=[('RF_USBISTYPEC',{'scope':True}),('RF_USB_A_Num',{'scope':'root'}),('RF_USB_C_Num',{'scope':None}),
             ('RF_USBNum',{'detailed':1}),('RF_USBPort',{'scope':'host'})]
        for name,args in bad:
            with self.subTest(name=name,args=args),mock.patch.object(p,'report') as read:
                with self.assertRaises(ValueError):api_bridge.call({'name':name,'args':args})
                read.assert_not_called()

    def test_mass_storage_subset_retains_USB_specification_distribution(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);_,a=port(root,1,1,0);_,b=port(root,1,2,0);x=device(root,'1-1');device(root,'1-2')
            (x/'1-1:1.0/bInterfaceClass').write_text('08');(x/'version').write_text('2.10');r=p.report(root,caps(a,b))
        report=call('RF_USBNum',r,{'detailed':True});self.assertEqual(report['count'],2)
        self.assertEqual(report['mass_storage']['count'],1);self.assertEqual(report['mass_storage']['usb_specification_bcd_counts']['0210'],1)
        self.assertEqual(report['usb_specification_bcd_counts']['0310'],1)

    def test_failed_or_changed_interface_classification_is_not_zero_storage(self):
        for mode in ['unreadable','changed']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);_,row=port(root,1,1,0);d=device(root,'1-1');original=p.interfaces;calls=0
                if mode=='unreadable':(d/'1-1:1.0/bInterfaceClass').unlink()
                def read(path):
                    nonlocal calls
                    value=original(path);calls+=1
                    return value if calls<2 else {'configuration':1,'classes':['08']}
                with mock.patch.object(p,'interfaces',side_effect=read):r=p.report(root,caps(row))
            self.assertEqual(call('RF_USBNum',r),1);storage=call('RF_USBNum',r,{'detailed':True})['mass_storage']
            self.assertIsNone(storage['count']);self.assertEqual(storage['observed_count'],0);self.assertEqual(storage['classification_unknown_count'],1)

    def test_original_A_counter_is_non_TypeC_without_relabelling_B_socket_as_A(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);_,row=port(root,1,1,1);device(root,'1-1');r=p.report(root,caps(row))
        result=call('RF_USB_A_Num',r);self.assertEqual(result['count'],1);self.assertIn('non-Type-C',result['quantity'])
        self.assertEqual(r['devices'][0]['connector'],'other');self.assertFalse(call('RF_USBISTYPEC',r)['type_c'])


if __name__=='__main__':unittest.main()
