# SPDX-License-Identifier: GPL-2.0-only
import errno
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock
import api_bridge
import compat
import linux_services as services
import wireless

PEER='02:00:00:00:00:01'
def link(iface='wlan0',peer=PEER,freq='5180.0',signal='-55.00 dBm',rate='HE-MCS 5'):
    return f'Connected to {peer} (on {iface})\n\tfreq: {freq}\n\tsignal: {signal}\n\ttx bitrate: 600.0 MBit/s {rate}\n\trx bitrate: 300.0 MBit/s {rate}\n'

def bss(peer=PEER,freq='5180.0',signal='-55.00 dBm'):
    return f'BSS {peer}(on wlan0)\n\tfreq: {freq}\n\tsignal: {signal}\n'

class BusError(Exception):
    def __init__(self,name):self.name=name
    def get_dbus_name(self):return 'org.freedesktop.DBus.Error.'+self.name
class BusBoolean(int):pass

class WirelessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.device('wlan0',3)
    def device(self,name,index):
        p=self.root/name;(p/'wireless').mkdir(parents=True,exist_ok=True);(p/'ifindex').write_text(str(index));return p
    def test_actual_link_fields_decimal_frequency_units_and_channel_are_parsed(self):
        r=wireless.parse_link(link(),'wlan0')
        self.assertEqual((r['peer'],r['frequency_mhz'],r['channel'],r['signal_dbm'],r['phy']),(PEER,5180,36,-55,'802.11ax'))
        self.assertEqual(r['maximum_reported_link_rate_mbit'],600)
        self.assertEqual(r['reported_rates_mbit'],{'tx':600,'rx':300})
        self.assertFalse(wireless.parse_link('Not connected.\n','wlan0')['connected'])
    def test_relative_quality_missing_or_invalid_fields_are_not_measurements(self):
        for signal in ['48/100','NaN dBm','-999 dBm','-55']:
            self.assertIsNone(wireless.parse_link(link(signal=signal),'wlan0')['signal_dbm'])
        r=wireless.parse_link(link(rate='')+'\tSSID: EHT-MCS 1\n','wlan0');self.assertIsNone(r['phy'])
        for text in ['', 'unknown',link(iface='wlan1')]:
            with self.assertRaises(OSError):wireless.parse_link(text,'wlan0')
    def test_channel_formulas_include_6ghz_special_49ghz_and_no_floor_guess(self):
        for frequency,wanted in [(2412,1),(2484,14),(4910,182),(5180,36),(5935,2),(5955,1),(7115,233),(58320,1)]:
            self.assertEqual(wireless.channel(frequency),wanted)
        for frequency in (2450,5180.5,5925,0,None):self.assertIsNone(wireless.channel(frequency))
    def test_link_queries_are_independent_of_nm_cache_and_zero_is_not_disconnect(self):
        with mock.patch.object(wireless,'NET_ROOT',self.root),mock.patch.object(wireless,'query',return_value=link(signal='0 dBm')),mock.patch.object(services,'wifi',side_effect=AssertionError('No NM dependency')):
            self.assertTrue(api_bridge.call({'name':'RF_WiFiIsConnected'}))
            self.assertEqual(api_bridge.call({'name':'RF_WiFiRssi'}),0)
            self.assertEqual(api_bridge.call({'name':'RF_WiFiChannel'}),36)
    def test_known_positive_survives_other_error_and_negative_requires_all_known(self):
        self.device('wlan1',4)
        def read(iface,operation):
            if iface=='wlan1':raise PermissionError(errno.EACCES,'denied')
            return link()
        with mock.patch.object(wireless,'NET_ROOT',self.root),mock.patch.object(wireless,'query',side_effect=read):
            self.assertTrue(wireless.call('RF_WiFiIsConnected',{}))
        def read(iface,operation):
            if iface=='wlan1':raise PermissionError(errno.EACCES,'denied')
            return 'Not connected.\n'
        with mock.patch.object(wireless,'NET_ROOT',self.root),mock.patch.object(wireless,'query',side_effect=read),self.assertRaises(PermissionError):
            wireless.call('RF_WiFiIsConnected',{})
    def test_roam_identity_and_inventory_changes_are_not_known_link_state(self):
        with mock.patch.object(wireless,'query',side_effect=[link(),link(peer='02:00:00:00:00:02')]):
            self.assertEqual(wireless.links(self.root)['interfaces'][0]['errno'],errno.EAGAIN)
        with mock.patch.object(wireless,'query',return_value=link()),mock.patch.object(wireless,'identity',side_effect=[(1,1,1),(1,1,2)]):
            self.assertIsNone(wireless.links(self.root)['connected'])
        p=self.root/'wlan0'
        with mock.patch.object(wireless,'query',return_value=link()),mock.patch.object(wireless,'interfaces',side_effect=[[p],[]]):
            self.assertIsNone(wireless.links(self.root)['connected'])
        with mock.patch.object(wireless,'links',return_value={'connected':None,'interfaces':[{'available':True,'connected':True}],'errno':errno.EAGAIN,'error':'changed'}),self.assertRaises(OSError):
            wireless.selected_link()
    def test_main_aux_reads_only_active_peer_and_keeps_physical_mapping_unknown(self):
        other='Station 02:00:00:00:00:02 (on wlan0)\n\tsignal: -10 [-10, -11] dBm\n'
        text=other+f'Station {PEER} (on wlan0)\n\tsignal: -55 [-57, -54] dBm\n'
        r=wireless.chains('wlan0',PEER,text)
        self.assertEqual(r['aggregate_dbm'],-55);self.assertEqual(r['chains_dbm'],[-57,-54])
        self.assertEqual(r['physical_main_aux_mapping'],'unverified')
        with self.assertRaises(OSError):wireless.chains('wlan0',PEER,other)
        with self.assertRaises(OSError):wireless.chains('wlan0',PEER,text.replace('[-57, -54]','[relative]'))
    def test_cached_bss_requires_dbm_and_complete_identity_frequency(self):
        self.assertEqual(wireless.parse_bss(bss())[0]['signal_dbm'],-55)
        self.assertIsNone(wireless.parse_bss(bss(signal='48/100'))[0]['signal_dbm'])
        self.assertEqual(wireless.parse_bss(''),[])
        for text in ['invalid',bss().replace('freq:', 'missing:'),bss(peer='bad')]:
            with self.assertRaises(OSError):wireless.parse_bss(text)
    def test_rssi_counts_do_not_turn_unknown_quality_into_zero_or_strong_dbm(self):
        name='RF_WiFi_5G_AP_RSSI_Num'
        with mock.patch.object(wireless,'NET_ROOT',self.root):
            with mock.patch.object(wireless,'query',return_value=bss(signal='48/100')),self.assertRaises(OSError):wireless.rssi_count(name,{})
            with mock.patch.object(wireless,'query',return_value=bss(signal='-70.0 dBm')):self.assertEqual(wireless.rssi_count(name,{}),0)
            with mock.patch.object(wireless,'query',return_value=bss(signal='-60.0 dBm')):self.assertEqual(wireless.rssi_count(name,{}),1)
            with mock.patch.object(wireless,'query',return_value=bss(freq='2412',signal='48/100')):self.assertEqual(wireless.rssi_count(name,{}),0)
    def test_same_bss_on_multiple_interfaces_counts_once_if_any_measured_strong(self):
        self.device('wlan1',4);name='RF_WiFi_5G_AP_RSSI_Num'
        with mock.patch.object(wireless,'NET_ROOT',self.root),mock.patch.object(wireless,'query',side_effect=[bss(),bss(signal='48/100')]):
            self.assertEqual(wireless.rssi_count(name,{}),1)
        with mock.patch.object(wireless,'NET_ROOT',self.root),mock.patch.object(wireless,'query',side_effect=[bss(signal='-80 dBm'),bss(signal='48/100')]),self.assertRaises(OSError):
            wireless.rssi_count(name,{})
    def test_cards_do_not_invent_missing_driver_name_or_require_networkmanager(self):
        driver=self.root/'drivers/iwlwifi';driver.mkdir(parents=True)
        p=self.root/'wlan0';(p/'device').mkdir();(p/'device/driver').symlink_to(driver)
        with mock.patch.object(wireless,'NET_ROOT',self.root),mock.patch.object(services,'wifi',side_effect=AssertionError('No NM dependency')):
            row=services.call('RF_WiFiCardName',{})[0]
            self.assertEqual(row['driver'],'iwlwifi');self.assertFalse(row['name_available'])
            (p/'device/driver').unlink();self.assertIsNone(wireless.cards()[0]['driver'])
    def test_fixed_query_directions_arguments_timeout_and_missing_device(self):
        for operation in [('scan',),('connect','ssid'),('set','power_save','off')]:
            with self.assertRaises(ValueError):wireless.query('wlan0',operation)
        import linux_services
        with mock.patch.object(linux_services,'system_tool',return_value='/usr/sbin/iw'),\
             mock.patch.object(wireless.subprocess,'run',side_effect=wireless.subprocess.TimeoutExpired('iw',5)) as run,self.assertRaises(OSError) as caught:wireless.query('wlan0',('link',))
        self.assertEqual(run.call_args.args[0][:2],['/usr/sbin/iw','dev'])
        self.assertEqual(caught.exception.errno,errno.ETIMEDOUT)
        for args in [{'threshold_dbm':True},{'threshold_dbm':float('nan')},{'threshold_dbm':'-65'},{'threshold_dbm':-121},{'scan':True}]:
            with self.assertRaises(ValueError):compat.validate('RF_WiFi_5G_AP_RSSI_Num',args)
        with mock.patch.object(wireless,'NET_ROOT',self.root/'missing'),self.assertRaises(OSError):wireless.call('RF_WiFiIsConnected',{})

class NMCacheTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        for index,name in enumerate(('wlan0','wlan1'),3):
            path=self.root/name;(path/'wireless').mkdir(parents=True);(path/'ifindex').write_text(str(index))
        patch=mock.patch.object(wireless,'NET_ROOT',self.root);patch.start();self.addCleanup(patch.stop)
    def context(self,aps=None,scan=1,error=None,two=False):
        aps=[] if aps is None else aps
        paths=['/org/freedesktop/NetworkManager/Devices/1']
        if two:paths.append('/org/freedesktop/NetworkManager/Devices/2')
        manager=mock.Mock();manager.GetDevices.return_value=paths
        device=mock.Mock();meta={'LastScan':scan}
        device.Get.side_effect=lambda interface,key,**kwargs:({'DeviceType':2,'Interface':'wlan0'} if interface.endswith('.Device') else meta).get(key)
        ap_paths=[f'/org/freedesktop/NetworkManager/AccessPoint/{i+1}' for i in range(len(aps))]
        device.GetAllAccessPoints.return_value=ap_paths
        entries={path:mock.Mock() for path in ap_paths}
        for path,value in zip(ap_paths,aps):entries[path].Get.side_effect=lambda interface,key,value=value,**kwargs:value.get(key)
        second=mock.Mock();second.Get.side_effect=lambda interface,key,**kwargs:({'DeviceType':2,'Interface':'wlan1'} if interface.endswith('.Device') else meta).get(key)
        second.GetAllAccessPoints.return_value=ap_paths
        bus=mock.Mock();bus.call_blocking.return_value=':1.42'
        if error:bus.call_blocking.side_effect=BusError(error)
        def obj(owner,path,**kwargs):
            if path=='/org/freedesktop/NetworkManager':return manager
            if path==paths[0]:return device
            if path in paths:return second
            return entries[path]
        bus.get_object.side_effect=obj
        module=types.SimpleNamespace(SystemBus=mock.Mock(return_value=bus),DBusException=BusError,Boolean=BusBoolean)
        return mock.patch.dict(sys.modules,{'dbus':module}),bus,manager,device,meta,entries
    def test_valid_known_empty_cache_zero_does_not_activate_scan_or_request_ssid(self):
        context,bus,manager,device,meta,entries=self.context()
        with context:self.assertEqual(services.call('RF_WiFi_5G_AP_Num',{}),0)
        self.assertEqual(bus.call_blocking.call_args.args[5],('org.freedesktop.NetworkManager',))
        self.assertEqual(bus.call_blocking.call_args.kwargs['timeout'],3)
        self.assertTrue(all(c.args[0]==':1.42' and c.kwargs['introspect'] is False for c in bus.get_object.call_args_list))
        device.RequestScan.assert_not_called()
        device.GetAll.assert_not_called()
        self.assertTrue(all(c.args[1] in ('DeviceType','Interface','LastScan') for c in device.Get.call_args_list))
    def test_never_scanned_missing_or_bad_frequency_is_unknown_not_zero(self):
        for aps,scan in [([], -1),([{'HwAddress':PEER}],1),([{'HwAddress':PEER,'Frequency':0}],1),([{'HwAddress':'bad','Frequency':5180}],1)]:
            context,*_=self.context(aps,scan)
            with context,self.assertRaises(OSError):services.call('RF_WiFi_5G_AP_Num',{})
    def test_percent_quality_is_retained_as_quality_only_and_duplicate_bss_deduplicated(self):
        context,*_=self.context([{'HwAddress':PEER,'Frequency':5180,'Strength':48}],two=True)
        with context:
            self.assertEqual(services.call('RF_WiFi_5G_AP_Num',{}),1)
            row=services.wifi()[0]['access_points'][0]
            self.assertEqual(row['strength_percent'],48);self.assertNotIn('signal_dbm',row)
    def test_nm_owner_permission_and_timeout_errors_are_not_false_empty_lists(self):
        for error,wanted in [('NameHasNoOwner',errno.ENODEV),('AccessDenied',errno.EACCES),('NoReply',errno.ETIMEDOUT)]:
            context,*_=self.context(error=error)
            with context,self.assertRaises(OSError) as caught:services.wifi()
            self.assertEqual(caught.exception.errno,wanted)
    def test_scan_changes_during_query_are_rejected(self):
        context,bus,manager,device,meta,entries=self.context([{'HwAddress':PEER,'Frequency':5180}])
        device.GetAllAccessPoints.side_effect=[list(entries),[]]
        with context,self.assertRaises(OSError) as caught:services.wifi()
        self.assertEqual(caught.exception.errno,errno.EAGAIN)
    def test_replaced_daemon_and_renamed_or_reused_interface_are_not_successful_censuses(self):
        context,bus,*_=self.context()
        bus.call_blocking.side_effect=[':1.42',':1.43']
        with context,self.assertRaises(OSError) as caught:services.wifi()
        self.assertEqual(caught.exception.errno,errno.EAGAIN)
        for changed in ('ifindex','Interface'):
            context,bus,manager,device,meta,entries=self.context([{'HwAddress':PEER,'Frequency':5180}])
            entry=next(iter(entries.values()))
            def read(interface,key,**kwargs):
                if key=='Strength':
                    if changed=='ifindex':(self.root/'wlan0/ifindex').write_text('42')
                    else:device.Get.side_effect=lambda interface,key,**kwargs:({'DeviceType':2,'Interface':'wlan1'} if interface.endswith('.Device') else meta).get(key)
                return {'HwAddress':PEER,'Frequency':5180,'Strength':50}.get(key)
            entry.Get.side_effect=read
            with context,self.assertRaises(OSError) as caught:services.wifi()
            self.assertEqual(caught.exception.errno,errno.EAGAIN)
            (self.root/'wlan0/ifindex').write_text('3')
    def test_changed_bss_identity_or_frequency_is_rejected_without_ssid_read(self):
        for field,value in [('HwAddress','02:00:00:00:00:02'),('Frequency',5200)]:
            context,bus,manager,device,meta,entries=self.context([{'HwAddress':PEER,'Frequency':5180}])
            calls=0;entry=next(iter(entries.values()))
            def read(interface,key,**kwargs):
                nonlocal calls
                self.assertIn(key,('HwAddress','Frequency','Strength'))
                if key==field:calls+=1
                return value if key==field and calls>1 else {'HwAddress':PEER,'Frequency':5180,'Strength':50}.get(key)
            entry.Get.side_effect=read
            with context,self.assertRaises(OSError) as caught:services.wifi()
            self.assertEqual(caught.exception.errno,errno.EAGAIN);entry.GetAll.assert_not_called()
    def test_deadline_duplicate_and_malformed_inventories_do_not_return_zero(self):
        context,bus,manager,device,*_=self.context()
        with context,mock.patch.object(services.time,'monotonic',side_effect=[0,0,9]),self.assertRaises(OSError) as caught:services.wifi()
        self.assertEqual(caught.exception.errno,errno.ETIMEDOUT);device.GetAllAccessPoints.assert_not_called()
        for paths in [['/org/freedesktop/NetworkManager/Devices/1']*2,['/org/freedesktop/NetworkManager/Devices/1/other']]:
            context,bus,manager,*_=self.context();manager.GetDevices.return_value=paths
            with context,self.assertRaises(OSError) as caught:services.wifi()
            self.assertEqual(caught.exception.errno,errno.EPROTO)
    def test_24ghz_channel_14_and_6ghz_special_frequency_are_classified(self):
        context,*_=self.context([{'HwAddress':PEER,'Frequency':2484},{'HwAddress':'02:00:00:00:00:02','Frequency':5935}])
        with context:
            self.assertEqual(services.call('RF_WiFi_2_4G_AP_Ch_Num',{}),{'channels':{'14':1},'channel_groups':{'1':0,'6':0,'11':0,'other':1},'total_aps':1})
            self.assertEqual(services.call('RF_WiFi_6G_AP_Num',{}),1)
    def test_all_original_count_and_group_quantities_with_full_native_channel_maps(self):
        frequencies=[2412,2437,2462,2484,2422,5180,5260,5500,5745,4910,5900,5935,6455,6535,6895]
        observations=[{'bssid':f'02:00:00:00:00:{i:02x}','frequency_mhz':freq} for i,freq in enumerate(frequencies,1)]
        rows=[{'access_points':observations},{'access_points':observations[:1]}]
        with mock.patch.object(services,'wifi',return_value=rows):
            self.assertEqual(services.call('RF_WiFi_2_4G_AP_Num',{}),5)
            self.assertEqual(services.call('RF_WiFi_5G_AP_Num',{}),6)
            self.assertEqual(services.call('RF_WiFi_6G_AP_Num',{}),4)
            channels=services.call('RF_WiFi_2_4G_AP_Ch_Num',{})
            self.assertEqual(channels['channel_groups'],{'1':1,'6':1,'11':1,'other':2})
            self.assertEqual(channels['channels'],{'1':1,'6':1,'11':1,'14':1,'3':1})
            self.assertEqual(services.call('RF_WiFi_5G_AP_Band_Num',{}),{'bands':{'U-NII-1':1,'U-NII-2A':1,'U-NII-2C':1,'U-NII-3':1},'total_aps':6,'unclassified':2})
            self.assertEqual(services.call('RF_WiFi_6G_AP_NUII_Num',{}),{'bands':{'U-NII-5':1,'U-NII-6':1,'U-NII-7':1,'U-NII-8':1},'total_aps':4,'unclassified':0})

if __name__=='__main__':unittest.main()
