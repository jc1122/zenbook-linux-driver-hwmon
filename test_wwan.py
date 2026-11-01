# SPDX-License-Identifier: GPL-2.0-only
import errno,json,unittest
from unittest import mock
import compat,wwan

M='/org/freedesktop/ModemManager1/Modem/0'
S='/org/freedesktop/ModemManager1/SIM/0'


def properties():
    return {(M,wwan.MODEM,'State'):11,(M,wwan.MODEM,'AccessTechnologies'):(1<<14)|(1<<15),
            (M,wwan.MODEM,'Sim'):S,(S,wwan.SIM,'OperatorIdentifier'):'00101',
            (S,wwan.SIM,'OperatorName'):'Home Example',(M,wwan.GPP,'OperatorCode'):'00202',
            (M,wwan.GPP,'OperatorName'):'Visited Example',(M,wwan.MODEM,'SignalQuality'):[73,True],
            (M,wwan.SIGNAL,'Rate'):10,(M,wwan.SIGNAL,'RssiThreshold'):0,(M,wwan.SIGNAL,'ErrorRateThreshold'):False,
            (M,wwan.SIGNAL,'Lte'):{'rssi':-72.5,'rsrp':-95.0,'rsrq':-12.5,'snr':18.5,'ignored-identifier':'DO-NOT-EXPORT'},
            (M,wwan.SIGNAL,'Nr5g'):{'rsrp':-89.0,'rsrq':-11.0,'snr':25.0,'rssi':-89.0}}


def getter(data,seen=None):
    def get(path,interface,prop):
        if seen is not None:seen.append((path,interface,prop))
        if prop not in wwan.PROPERTIES.get(interface,set()):raise AssertionError('Non-whitelisted property')
        value=data.get((path,interface,prop),OSError(errno.EOPNOTSUPP,'Optional property absent'))
        if isinstance(value,Exception):raise value
        return value
    return get


class WwanTests(unittest.TestCase):
    def test_technology_flags_include_simultaneous_lte_nr_and_preserve_unknown_bits(self):
        d=properties();d[M,wwan.MODEM,'AccessTechnologies']|=1<<28
        r=wwan.collect('RF_WWAN_Access_Technology',[M],getter(d))[0]
        self.assertTrue(r['available']);self.assertEqual(r['technologies'],['LTE','5G NR'])
        self.assertEqual(r['unknown_mask'],1<<28)
        d[M,wwan.MODEM,'State']=7
        self.assertFalse(wwan.collect('RF_WWAN_Access_Technology',[M],getter(d))[0]['available'])
        d[M,wwan.MODEM,'State']=11;d[M,wwan.MODEM,'AccessTechnologies']=0xffffffff
        self.assertEqual(wwan.access_technology(getter(d),M)['technologies'],[])

    def test_home_provider_uses_sim_and_never_relabels_a_roaming_serving_network(self):
        seen=[];r=wwan.home_provider(getter(properties(),seen),M)
        self.assertEqual(r['home_provider'],{'code':'00101','name':'Home Example'})
        self.assertEqual(r['serving_provider']['code'],'00202')
        self.assertEqual({p for _,_,p in seen},{'Sim','OperatorIdentifier','OperatorName','OperatorCode'})
        d=properties();d[S,wwan.SIM,'OperatorIdentifier']='';d[S,wwan.SIM,'OperatorName']=''
        r=wwan.home_provider(getter(d),M);self.assertFalse(r['available']);self.assertIsNone(r['home_provider']['code'])
        self.assertEqual(r['serving_provider']['code'],'00202')

    def test_measured_signal_units_do_not_convert_quality_or_substitute_nr_rsrp(self):
        r=wwan.signal(getter(properties()),M)
        self.assertTrue(r['rssi_available']);self.assertEqual(r['measurements'][0]['rssi_dbm'],-72.5)
        self.assertEqual(r['measurements'][1]['rsrp_dbm'],-89)
        self.assertNotIn('rssi_dbm',r['measurements'][1]);self.assertEqual(r['signal_quality_percent'],73)
        self.assertFalse(r['freshness_verified']);self.assertIsNone(r['sample_age_seconds'])
        self.assertNotIn('DO-NOT-EXPORT',json.dumps(r))
        d=properties();d[M,wwan.MODEM,'AccessTechnologies']=1<<15
        r=wwan.signal(getter(d),M);self.assertFalse(r['available']);self.assertIn('rsrp_dbm',r['measurements'][0])

    def test_disabled_polling_suppresses_cached_values_but_unsolicited_updates_work(self):
        d=properties();d[M,wwan.SIGNAL,'Rate']=0;seen=[]
        r=wwan.signal(getter(d,seen),M);self.assertFalse(r['available']);self.assertEqual(r['measurements'],[])
        self.assertFalse(any(p in wwan.RADIOS for _,_,p in seen))
        d[M,wwan.SIGNAL,'RssiThreshold']=10
        self.assertTrue(wwan.signal(getter(d),M)['available'])
        d[M,wwan.MODEM,'SignalQuality']=[99,False]
        self.assertIsNone(wwan.signal(getter(d),M)['signal_quality_percent'])

    def test_unknown_or_invalid_values_are_not_signal_zero(self):
        d=properties();d[M,wwan.MODEM,'AccessTechnologies']=1<<14
        for bad in [True,float('nan'),float('inf'),1.7976931348623157e308,'-75',50,-999]:
            with self.subTest(bad=bad):
                d[M,wwan.SIGNAL,'Lte']={'rssi':bad}
                r=wwan.signal(getter(d),M);self.assertFalse(r['available']);self.assertEqual(r['measurements'],[])

    def test_per_modem_failures_do_not_hide_a_healthy_device(self):
        d=properties();other=M[:-1]+'1'
        d[other,wwan.MODEM,'AccessTechnologies']=OSError(errno.EACCES,'Denied')
        rows=wwan.collect('RF_WWAN_Access_Technology',[other,M],getter(d))
        self.assertEqual(rows[0]['errno'],errno.EACCES);self.assertTrue(rows[1]['available'])
        d[S,wwan.SIM,'OperatorIdentifier']=OSError(errno.EACCES,'Denied')
        row=wwan.collect('RF_WWAN_Home_Provider',[M],getter(d))[0]
        self.assertTrue(row['available']);self.assertIsNone(row['home_provider']['code'])
        self.assertEqual(row['home_provider_errors']['code']['errno'],errno.EACCES)
        d[S,wwan.SIM,'OperatorName']=OSError(errno.EACCES,'Denied')
        self.assertEqual(wwan.collect('RF_WWAN_Home_Provider',[M],getter(d))[0]['errno'],errno.EACCES)
        d=properties();d[M,wwan.GPP,'OperatorCode']=OSError(errno.EACCES,'Denied')
        self.assertTrue(wwan.home_provider(getter(d),M)['available'])
        d=properties();d[M,wwan.SIGNAL,'Lte']=OSError(errno.EIO,'Gone')
        row=wwan.signal(getter(d),M);self.assertFalse(row['rssi_available']);self.assertEqual(row['measurements'][0]['radio'],'Nr5g')

    def test_selectors_are_validated_and_absent_devices_do_not_initialize_dbus(self):
        for args in [{'modem':'/other/0'},{'modem':False},{'enable':True},{'modem':M+'/../1'}]:
            with self.subTest(args=args),mock.patch.object(wwan,'list_modems') as listing:
                with self.assertRaises(ValueError):compat.validate('RF_WWAN_RSSI',args)
                listing.assert_not_called()
        with mock.patch.object(wwan,'list_modems',return_value=[]),mock.patch.object(wwan,'dbus_getter') as bus:
            with self.assertRaises(OSError) as error:wwan.call('RF_WWAN_RSSI',{})
            self.assertEqual(error.exception.errno,errno.ENODEV);bus.assert_not_called()

    def test_enumeration_rejects_malformed_and_foreign_objects(self):
        for raw in ['[]','<other/>','<node><node name="/secret"/></node>',
                    '<node><node name="0"/><node name="0"/></node>',
                    '<!DOCTYPE node [<!ENTITY x "0">]><node><node name="&x;"/></node>',
                    '<node>'+''.join('<node name="%d"/>'%n for n in range(33))+'</node>', 'x'*65537]:
            with self.subTest(raw=raw[:100]),mock.patch.object(wwan,'Reader',return_value=transport(raw)):
                with self.assertRaises(OSError) as error:wwan.list_modems()
                self.assertEqual(error.exception.errno,errno.EPROTO)

    def test_real_dbus_type_unboxing_and_fixed_property_transport(self):
        import dbus
        calls=[]
        class Object:
            def Get(self,interface,prop,**kwargs):
                calls.append((interface,prop,kwargs))
                return dbus.Struct((dbus.UInt32(73),dbus.Boolean(True)))
        class Bus:
            def call_blocking(self,*args,**kwargs):return ':1.42'
            def get_object(self,service,path,**kwargs):
                self.args=(service,path,kwargs);return Object()
        bus=Bus()
        with mock.patch.object(dbus,'SystemBus',return_value=bus):get=wwan.dbus_getter()
        self.assertEqual(get(M,wwan.MODEM,'SignalQuality'),[73,True])
        self.assertEqual(bus.args,(':1.42',M,{'introspect':False}))
        self.assertEqual(calls[0][2]['dbus_interface'],'org.freedesktop.DBus.Properties')
        self.assertLessEqual(calls[0][2]['timeout'],2)
        for prop in ['Imsi','OwnNumbers','UnlockRetries','Enable','GetAll']:
            with self.subTest(prop=prop),self.assertRaises(OSError) as error:get(M,wwan.MODEM,prop)
            self.assertEqual(error.exception.errno,errno.EPERM)
        self.assertEqual(len(calls),1)

    def test_standard_introspection_and_complete_call_pin_unique_owner(self):
        import dbus
        bus=FakeBus()
        with mock.patch.object(dbus,'SystemBus',return_value=bus):
            rows=wwan.call('RF_WWAN_RSSI',{'modem':M})
        self.assertTrue(rows[0]['available'])
        self.assertEqual(bus.inventory_reads,2);self.assertEqual(bus.owner_reads,2)
        self.assertTrue(all(service==':1.42' for service,_,_ in bus.objects))
        self.assertTrue(all(prop in wwan.PROPERTIES[interface] for _,interface,prop in bus.reads))
        self.assertFalse(any(p in ('Imsi','Imei','OwnNumbers','Bearers') for _,_,p in bus.reads))

    def test_owner_and_inventory_changes_discard_results(self):
        import dbus
        for field in ['owner_change','inventory_change']:
            bus=FakeBus();setattr(bus,field,True)
            with self.subTest(field=field),mock.patch.object(dbus,'SystemBus',return_value=bus):
                with self.assertRaises(OSError) as error:wwan.call('RF_WWAN_Home_Provider',{})
                self.assertEqual(error.exception.errno,errno.EAGAIN)

    def test_empty_inventory_still_checks_owner_and_never_reads_properties(self):
        import dbus
        bus=FakeBus();bus.xml='<node/>'
        with mock.patch.object(dbus,'SystemBus',return_value=bus):
            with self.assertRaises(OSError) as error:wwan.call('RF_WWAN_RSSI',{})
        self.assertEqual(error.exception.errno,errno.ENODEV);self.assertFalse(bus.reads)
        self.assertEqual(bus.owner_reads,2);self.assertEqual(bus.inventory_reads,2)

    def test_context_transitions_discard_mixed_radio_or_sim_readings(self):
        for name,interface,prop,new in [
            ('RF_WWAN_Access_Technology',wwan.MODEM,'State',7),
            ('RF_WWAN_Access_Technology',wwan.MODEM,'AccessTechnologies',0),
            ('RF_WWAN_Home_Provider',wwan.MODEM,'Sim',S[:-1]+'1'),
            ('RF_WWAN_RSSI',wwan.MODEM,'SignalQuality',[74,True]),
            ('RF_WWAN_RSSI',wwan.SIGNAL,'Rate',0),
            ('RF_WWAN_RSSI',wwan.SIGNAL,'RssiThreshold',10),
            ('RF_WWAN_RSSI',wwan.SIGNAL,'ErrorRateThreshold',True)]:
            base=getter(properties());calls=0
            def changing(p,i,v):
                nonlocal calls
                if (p,i,v)==(M,interface,prop):
                    calls+=1
                    if calls>1:return new
                return base(p,i,v)
            with self.subTest(prop=prop):
                row=wwan.collect(name,[M],changing)[0]
                self.assertFalse(row['available']);self.assertEqual(row['errno'],errno.EAGAIN)
                self.assertNotIn('measurements',row);self.assertNotIn('home_provider',row)

    def test_deadline_invalid_owner_and_transport_error_mapping(self):
        import dbus
        bus=FakeBus()
        with mock.patch.object(dbus,'SystemBus',return_value=bus):reader=wwan.Reader()
        reader.deadline=0
        with self.assertRaises(OSError) as error:reader.paths()
        self.assertEqual(error.exception.errno,errno.ETIMEDOUT)
        bus.owner='org.freedesktop.ModemManager1'
        with mock.patch.object(dbus,'SystemBus',return_value=bus):
            with self.assertRaises(OSError) as error:wwan.Reader()
        self.assertEqual(error.exception.errno,errno.EPROTO)
        for suffix,code in [('AccessDenied',errno.EACCES),('NameHasNoOwner',errno.ENODEV),('NoReply',errno.ETIMEDOUT)]:
            bus.owner_error=dbus.DBusException('private diagnostic omitted',name='org.freedesktop.DBus.Error.'+suffix)
            with mock.patch.object(dbus,'SystemBus',return_value=bus):
                with self.assertRaises(OSError) as error:wwan.Reader()
            self.assertEqual(error.exception.errno,code);self.assertNotIn('private',str(error.exception))

    def test_technology_specific_units_and_bad_property_shapes(self):
        d=properties();d[M,wwan.MODEM,'AccessTechnologies']=(1<<10)|(1<<5)
        d[M,wwan.SIGNAL,'Cdma']={'rssi':-80.,'ecio':-12.}
        d[M,wwan.SIGNAL,'Umts']={'rssi':-81.,'ecio':-11.}
        rows=wwan.signal(getter(d),M)['measurements']
        self.assertEqual(rows[0]['ecio_db'],-11.);self.assertEqual(rows[1]['ecio_dbm'],-12.)
        for prop,value in [('SignalQuality',[73,1]),('AccessTechnologies',True),('State',99)]:
            bad=properties();bad[M,wwan.MODEM,prop]=value
            with self.subTest(prop=prop):
                row=wwan.collect('RF_WWAN_RSSI',[M],getter(bad))[0]
                self.assertFalse(row['available']);self.assertEqual(row['errno'],errno.EPROTO)


class FakeBus:
    def __init__(self):
        self.owner=':1.42';self.owner_reads=0;self.inventory_reads=0
        self.owner_change=False;self.inventory_change=False;self.owner_error=None
        self.xml='<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN" "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd"><node><node name="0"/></node>'
        self.objects=[];self.reads=[]
    def call_blocking(self,*args,**kwargs):
        if self.owner_error:raise self.owner_error
        self.owner_reads+=1
        return ':1.43' if self.owner_change and self.owner_reads>1 else self.owner
    def get_object(self,service,path,**kwargs):
        self.objects.append((service,path,kwargs));bus=self
        class Object:
            def Introspect(self,**kwargs):
                bus.inventory_reads+=1
                return '<node/>' if bus.inventory_change and bus.inventory_reads>1 else bus.xml
            def Get(self,interface,prop,**kwargs):
                bus.reads.append((path,interface,prop));return getter(properties())(path,interface,prop)
        return Object()


def transport(raw):
    import dbus
    bus=FakeBus();bus.xml=raw
    with mock.patch.object(dbus,'SystemBus',return_value=bus):return wwan.Reader()


if __name__=='__main__':unittest.main()
