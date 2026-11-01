# SPDX-License-Identifier: GPL-2.0-only
import copy
import errno
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock
import compat
import wireless
import wireless_capabilities as caps
import wireless_inventory as inventory
import wireless_native as native


def ie(kind,data):return bytes([kind,len(data)])+data

def ht(width=40):
    capability=bytearray(26);capability[0]=0x62;capability[3:7]=b'\xff'*4
    operation=bytearray(22);operation[0]=36;operation[1]=5 if width==40 else 0
    return ie(45,capability)+ie(61,operation)

def he(width=80,rx=0xfffe,tx=0xfffe,six=False):
    # Synthetic one-stream MCS11, separate <=80/160/80+80 maps.
    payload=bytearray(22);payload[0]=35;payload[7]=4|(8 if width==160 else 0)
    payload[18:20]=rx.to_bytes(2,'little');payload[20:22]=tx.to_bytes(2,'little')
    if width==160:payload+=rx.to_bytes(2,'little')+tx.to_bytes(2,'little')
    if six:
        op=bytes([36,0,0,2,0,0,0,1,{20:0,40:1,80:2,160:3}[width],7,15,0])
        return ie(255,payload)+ie(255,op)
    return ht()+ie(192,bytes([1,42,50 if width==160 else 0,0,0]))+ie(255,payload)


def current():
    return {'owner':':1.42','interfaces':[{'interface':'wlan0','identity':(1,2,3),'phy':'phy0','phy_identity':(1,4),
            'active_connection':'/org/freedesktop/NetworkManager/ActiveConnection/1','ap_object':'/org/freedesktop/NetworkManager/AccessPoint/1',
            'peer':'02:00:00:00:00:01','frequency_mhz':5180}]}


def observation(key='a',signal=-50,age=2,band='5G'):
    return {'ap_key':key*64,'frequency_mhz':5180 if band=='5G' else 2412 if band=='2_4G' else 5955,'band':band,'signal_dbm':signal,'age_seconds':age}


def envelope():
    return {'schema':1,'boot_id':'test-boot','maximum_cache_seconds':45,'generated_boottime_seconds':100,
            'context_id':native.fingerprint(current()),'interfaces':[{'interface':'wlan0','ifindex':3,'connected':True,
            'capability':caps.decode(he(),5180),'association_phy':{'available':True,'family':'802.11ax'},
            'observations_available':True,'observations':[observation()]}]}


class CapabilityTests(unittest.TestCase):
    def test_standard_rate_arithmetic_includes_guard_intervals(self):
        self.assertEqual(float(caps.rate('HT',40,4,7,.4)),600)
        self.assertAlmostEqual(float(caps.rate('VHT',80,2,9,.4)),866.6666667)
        self.assertAlmostEqual(float(caps.rate('HE',160,4,11,.8)),4803.9215686)
        self.assertAlmostEqual(float(caps.rate('HE',160,4,11,1.6)),4537.0370370)
        self.assertAlmostEqual(float(caps.rate('HE',160,4,11,3.2)),4083.3333333)
        for args in [('HT',80,1,7,.4),('HE',80,1,11,.4),('VHT',80,0,9,.4)]:
            with self.assertRaises(ValueError):caps.rate(*args)
    def test_tlv_bounds_duplicates_and_no_identity_vendor_data(self):
        raw=ht()+ie(0,b'private-network')+ie(221,b'private-vendor')
        self.assertEqual(caps.elements(raw),caps.elements(ht()))
        for raw in [b'',b'\xff\x00',b'\x01',b'\x01\x05\x01',ie(1,b'\x0c')+ie(1,b'\x18'),b'x'*8193]:
            with self.assertRaises(OSError):caps.elements(raw)
        self.assertEqual(caps.elements(ht()+ht()),caps.elements(ht()))
    def test_ht_ceiling_is_capability_not_observed_link_rate(self):
        result=caps.decode(ht(),5180)
        self.assertEqual(result['maximum_mbit_s'],600)
        self.assertEqual(result['best_profile']['spatial_streams'],4)
        self.assertEqual(caps.decode(ht(20),5180)['maximum_mbit_s'],288.889)
    def test_vht_rx_tx_maps_and_20mhz_mcs9_constraint(self):
        vht=(0x20).to_bytes(4,'little')+bytes.fromhex('feff0000faff0000')
        result=caps.decode(ht()+ie(191,vht)+ie(192,bytes([1,42,0,0,0])),5180)
        self.assertEqual(result['best_profile']['family'],'VHT')
        self.assertEqual(result['best_profile']['spatial_streams'],2)
        result=caps.decode(ht(20)+ie(191,vht)+ie(192,bytes(5)),5180)
        self.assertTrue(all(p['mcs']<=8 for p in result['profiles'] if p['family']=='VHT'))
    def test_he_width_specific_maps_do_not_borrow_80mhz_streams(self):
        raw=bytearray(he(160));payload=bytearray(caps.elements(bytes(raw))[(255,35)])
        payload[18:22]=b'\xaa\xaa\xaa\xaa' # eight streams only <=80
        payload[22:26]=b'\xfe\xff\xfe\xff' # one stream at160
        raw=ht()+ie(192,bytes([1,42,50,0,0]))+ie(255,payload)
        result=caps.decode(raw,5180)
        self.assertEqual(result['best_profile']['width_mhz'],80)
        self.assertEqual(result['best_profile']['spatial_streams'],8)
        self.assertEqual(max(p['spatial_streams'] for p in result['profiles'] if p['width_mhz']==160),1)
    def test_6ghz_width_and_eht_scope_are_explicit(self):
        result=caps.decode(he(160,six=True)+ie(255,bytes([108,0])),5955)
        self.assertEqual(result['operation_width_mhz'],160)
        self.assertTrue(result['complete_for_scope']);self.assertFalse(result['complete_overall'])
        with self.assertRaises(OSError):caps.decode(ie(255,caps.elements(he())[(255,35)]),5955)
    def test_80plus80_uses_its_own_he_maps_and_optional_vht_operation(self):
        payload=bytearray(caps.elements(he(160))[(255,35)])
        payload[7]|=16;payload+=bytes.fromhex('fafffaff') # two streams in80+80
        raw=ht()+ie(192,bytes([1,42,106,0,0]))+ie(255,payload)
        result=caps.decode(raw,5180)
        self.assertEqual(result['operation_channel_layout'],'80+80')
        self.assertEqual(result['best_profile']['spatial_streams'],2)
        payload[7]&=~16
        with self.assertRaises(OSError):caps.decode(ht()+ie(192,bytes([1,42,106,0,0]))+ie(255,payload),5180)
        op=bytes([36,0,0x40,0,0,0,0,1,42,50])
        result=caps.decode(ht()+ie(255,caps.elements(he(160))[(255,35)])+ie(255,op),5180)
        self.assertEqual(result['operation_width_mhz'],160)
        with self.assertRaises(OSError):caps.decode(he()+ie(255,op),5180)
    def test_truncated_he_maps_ppe_and_operation_fail(self):
        payload=bytearray(caps.elements(he(160))[(255,35)])
        for bad in [payload[:21],payload[:24]]:
            with self.assertRaises(OSError):caps.decode(ht()+ie(192,bytes([1,42,50,0,0]))+ie(255,bad),5180)
        payload=bytearray(caps.elements(he())[(255,35)]);payload[13]|=0x80
        for tail in [b'',bytes([0x7f])]:
            with self.assertRaises(OSError):caps.decode(ht()+ie(255,payload+tail),5180)
        with self.assertRaises(OSError):caps.decode(ht()+ie(255,bytes([36,0,0,2,0,0,0])),5955)
    def test_peer_family_independent_of_observed_frames_and_legacy_unknown(self):
        files={'ht_capa':'ht supported\n','vht_capa':'VHT supported\n','he_capa':'HE supported\n','eht_capa':'EHT not supported\n'}
        self.assertEqual(caps.peer_family(files)['family'],'802.11ax')
        files['he_capa']='HE not supported';self.assertEqual(caps.peer_family(files)['family'],'802.11ac')
        files['vht_capa']='VHT not supported';files['ht_capa']='ht not supported'
        with self.assertRaises(OSError):caps.peer_family(files)
        files['he_capa']='unknown'
        with self.assertRaises(OSError):caps.peer_family(files)
    def test_histogram_boundaries_unknown_zero_and_outside(self):
        signals=[-10,-20,-30,-90,-100,-101,0,None]
        rows=[observation(signal=v) for v in signals];result=caps.histograms(rows)['5G']
        self.assertEqual([b['count'] for b in result['bins']],[1,1,0,0,0,0,0,1,1])
        self.assertEqual(result['unknown_signal_count'],1);self.assertEqual(result['outside_bins_count'],3)
        self.assertFalse(result['complete']);self.assertEqual(result['total_aps'],8)
        self.assertEqual(caps.histograms([])['6G']['total_aps'],0)


class NativeTests(unittest.TestCase):
    def test_cache_age_boot_and_same_peer_reassociation_rejected(self):
        data=envelope();self.assertEqual(native.validate_cache(data,105,current(),'test-boot')['age_seconds'],5)
        for now,boot in [(146,'test-boot'),(99,'test-boot'),(105,'other')]:
            with self.assertRaises(OSError):native.validate_cache(data,now,current(),boot)
        changed=current();changed['interfaces'][0]['active_connection']+='/different'
        with self.assertRaises(OSError) as caught:native.validate_cache(data,105,changed,'test-boot')
        self.assertEqual(caught.exception.errno,errno.EAGAIN)
    def test_cache_strict_nested_status_and_real_zero_signal(self):
        for key,value in [('ifindex',True),('connected',1),('observations_available',1)]:
            data=envelope();data['interfaces'][0][key]=value
            with self.assertRaises(OSError):native.validate_cache(data,105,current(),'test-boot')
        for value in [True,float('nan'),float('inf'),-1,'600']:
            data=envelope();data['interfaces'][0]['capability']['maximum_mbit_s']=value
            with self.assertRaises(OSError):native.validate_cache(data,105,current(),'test-boot')
        data=envelope();data['interfaces'][0]['observations'][0]['signal_dbm']=0
        native.validate_cache(data,105,current(),'test-boot')
        data['interfaces'][0]['association_phy']['family']='802.11unknown'
        with self.assertRaises(OSError):native.validate_cache(data,105,current(),'test-boot')
    def test_cache_retains_collector_error(self):
        data={**envelope(),'available':False,'errno':errno.EACCES,'error':'denied','context_id':''}
        with self.assertRaises(OSError) as caught:native.validate_cache(data,105,current(),'test-boot')
        self.assertEqual(caught.exception.errno,errno.EACCES)
    def test_cache_files_require_trusted_regular_owner_and_no_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'wireless.json';p.write_text(json.dumps(envelope()));p.chmod(0o644)
            with mock.patch.object(native,'Reader'),mock.patch.object(native,'context',return_value=current()),mock.patch.object(native,'boottime',return_value=105),mock.patch.object(native,'text',return_value='test-boot'):
                self.assertEqual(native.cached(p,os.getuid())['age_seconds'],5)
                p.chmod(0o666)
                with self.assertRaises(PermissionError):native.cached(p,os.getuid())
                p.chmod(0o644);q=p.with_name('link');q.symlink_to(p)
                with self.assertRaises(OSError):native.cached(q,os.getuid())
                p.write_text('invalid')
                with self.assertRaises(OSError):native.cached(p,os.getuid())
    def test_histograms_deduplicate_newest_measurement_and_add_cache_age(self):
        data=envelope();data['age_seconds']=5
        row=copy.deepcopy(data['interfaces'][0]);row['observations']=[observation(signal=-80,age=0),observation('b',None)]
        data['interfaces'].append(row);result=native.summarize(data)
        hist=result['histograms']['5G'];self.assertEqual(hist['total_aps'],2);self.assertFalse(hist['complete'])
        self.assertEqual(hist['maximum_observation_age_seconds'],7)
        self.assertEqual(hist['bins'][6]['count'],1)
    def test_partial_inventory_preserves_known_bins_without_definitive_count(self):
        data=envelope();data['interfaces'].append({**copy.deepcopy(data['interfaces'][0]),'observations_available':False,'observations':[]})
        result=native.summarize(data);self.assertEqual(result['histograms']['5G']['total_aps'],1)
        self.assertFalse(result['histograms']['5G']['complete'])
        with mock.patch.object(native,'report',return_value=result),self.assertRaises(OSError):native.require('RF_WiFi_5G_AP_RSSI_Num',{'threshold_dbm':-65})
    def test_native_default_histogram_explicit_threshold_and_no_root_when_cached(self):
        data=native.summarize(envelope())
        with mock.patch.object(native,'report',return_value=data):
            self.assertEqual(wireless.call('RF_WiFiMaxRate',{}),data['interfaces'][0]['capability']['maximum_mbit_s'])
            self.assertEqual(wireless.call('RF_PhyMode',{}),'802.11ax')
            self.assertEqual(wireless.call('RF_WiFi_5G_AP_RSSI_Num',{})['total_aps'],1)
            self.assertEqual(wireless.call('RF_WiFi_5G_AP_RSSI_Num',{'threshold_dbm':0}),0)
        with mock.patch.object(native.os,'geteuid',return_value=1000),mock.patch.object(native,'cached',return_value=envelope()):
            self.assertFalse(compat.needs_root('RF_WiFi_5G_AP_RSSI_Num',{}))
        with mock.patch.object(native.os,'geteuid',return_value=1000),mock.patch.object(native,'cached',side_effect=OSError(errno.ESTALE,'stale')):
            self.assertTrue(compat.needs_root('RF_WiFiMaxRate',{}))
    def test_report_missing_cache_does_not_authenticate_or_collect(self):
        with mock.patch.object(native,'cached',side_effect=OSError(errno.ENOENT,'missing')),mock.patch.object(native,'collect',side_effect=AssertionError('No root/refresh')):
            self.assertEqual(native.report()['errno'],errno.ENOENT)
    def test_fixed_reader_rejects_scan_configuration_and_expired_deadline(self):
        reader=object.__new__(native.Reader)
        for method in ['Scan','CreateInterface','Set','Disconnect']:
            with self.assertRaises(ValueError):reader.call(':1.42','/',native.WPA,method)
        reader.deadline=time.monotonic()-1
        with self.assertRaises(OSError) as caught:reader.remaining()
        self.assertEqual(caught.exception.errno,errno.ETIMEDOUT)
    def test_fixed_station_files_require_complete_current_peer(self):
        with tempfile.TemporaryDirectory() as temp:
            row=current()['interfaces'][0];p=Path(temp)/'phy0/netdev:wlan0/stations'/row['peer'];p.mkdir(parents=True)
            for name,value in [('ht_capa','ht'),('vht_capa','VHT'),('he_capa','HE'),('eht_capa','EHT not')]:
                (p/name).write_text(value+' supported\n')
            self.assertEqual(native.station(row,Path(temp))['family'],'802.11ax')
            (p/'he_capa').unlink()
            with self.assertRaises(OSError):native.station(row,Path(temp))
    def test_collection_bss_failure_does_not_erase_capability_or_association(self):
        reader=mock.Mock();reader.owner.return_value=':1.43';reader.call.return_value='/fi/w1/wpa_supplicant1/Interfaces/0'
        def get(owner,path,interface,key):
            if key=='CurrentBSS':return '/fi/w1/wpa_supplicant1/Interfaces/0/BSSs/1'
            if key=='BSSID':return bytes.fromhex('020000000001')
            if key=='Frequency':return 5180
            if key=='IEs':return he()
            if key=='BSSs':raise OSError(errno.ETIMEDOUT,'cache timeout')
            raise AssertionError(key)
        reader.get.side_effect=get
        with mock.patch.object(native.os,'geteuid',return_value=0),mock.patch.object(native,'Reader',return_value=reader),mock.patch.object(native,'context',return_value=current()),mock.patch.object(native,'station',return_value={'available':True,'family':'802.11ax'}):
            result=native.collect()['interfaces'][0]
        self.assertTrue(result['capability']['available']);self.assertTrue(result['association_phy']['available'])
        self.assertFalse(result['observations_available']);self.assertEqual(result['observations_error']['errno'],errno.ETIMEDOUT)
        self.assertFalse(any(c.args[3] in ('SSID','Privacy','WPS') for c in reader.get.call_args_list))
    def test_bss_keys_are_salted_per_boot_and_root_only(self):
        import hashlib,hmac
        secret=bytes(range(32));key=native.ap_key(secret,'02:00:00:00:00:01',5180)
        self.assertRegex(key,'^[0-9a-f]{64}$');self.assertEqual(key,native.ap_key(secret,'02:00:00:00:00:01',5180))
        self.assertNotEqual(key,native.fingerprint(['02:00:00:00:00:01',5180]))
        self.assertNotEqual(key,native.ap_key(bytes(32),'02:00:00:00:00:01',5180))
        self.assertEqual(key,hmac.new(secret,b'["02:00:00:00:00:01",5180]',hashlib.sha256).hexdigest())
        with self.assertRaises(ValueError):native.ap_key(b'short','02:00:00:00:00:01',5180)
        uid=os.getuid();boot='0123abcd-0000-4000-8000-000000000001'
        with tempfile.TemporaryDirectory() as temp:
            os.chmod(temp,0o755);path=Path(temp)/'.salt'
            first,persistent=native.boot_salt(path,boot,uid)
            self.assertTrue(persistent);self.assertEqual(len(first),32);self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertEqual(native.boot_salt(path,boot,uid),(first,True))
            self.assertFalse(list(Path(temp).glob('.salt-*')))
            other,persistent=native.boot_salt(path,'0123abcd-0000-4000-8000-000000000002',uid)
            self.assertTrue(persistent);self.assertNotEqual(other,first)  # a new boot gets a new secret
            os.chmod(path,0o644);value,persistent=native.boot_salt(path,'0123abcd-0000-4000-8000-000000000002',uid)
            self.assertFalse(persistent);self.assertNotEqual(value,other)  # readable secret is never trusted
            path.unlink();os.chmod(temp,0o775)
            self.assertFalse(native.boot_salt(path,boot,uid)[1]);self.assertFalse(path.exists())
            os.chmod(temp,0o755);self.assertFalse(native.boot_salt(path,boot,uid+1)[1])
            self.assertFalse(native.boot_salt(path,'not a boot id!',uid)[1])
    def test_collected_cache_carries_only_salted_bss_keys(self):
        reader=mock.Mock();reader.owner.return_value=':1.43';reader.call.return_value='/fi/w1/wpa_supplicant1/Interfaces/0'
        def get(owner,path,interface,key):
            if key=='CurrentBSS':return '/fi/w1/wpa_supplicant1/Interfaces/0/BSSs/1'
            if key=='BSSID':return bytes.fromhex('020000000001')
            if key=='Frequency':return 5180
            if key=='IEs':return he()
            if key=='BSSs':return ['/fi/w1/wpa_supplicant1/Interfaces/0/BSSs/1']
            if key=='Signal':return -50
            if key=='Age':return 3
            raise AssertionError(key)
        reader.get.side_effect=get;secret=b'k'*32
        with mock.patch.object(native.os,'geteuid',return_value=0),mock.patch.object(native,'Reader',return_value=reader),\
             mock.patch.object(native,'context',return_value=current()),mock.patch.object(native,'boot_salt',return_value=(secret,True)),\
             mock.patch.object(native,'station',return_value={'available':True,'family':'802.11ax'}):
            data=native.collect()
        item=data['interfaces'][0]['observations'][0]
        self.assertEqual(item['ap_key'],native.ap_key(secret,'02:00:00:00:00:01',5180))
        self.assertNotEqual(item['ap_key'],native.fingerprint(['02:00:00:00:00:01',5180]))
        self.assertNotIn('02:00:00:00:00:01',json.dumps(data['interfaces']))
    def test_context_owner_paths_and_current_interface_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'wlan0';(p/'wireless').mkdir(parents=True);(p/'ifindex').write_text('3')
            (root/'phy0').mkdir();(p/'phy80211').symlink_to(root/'phy0')
            reader=mock.Mock();reader.owner.return_value=':1.42';reader.call.return_value=['/org/freedesktop/NetworkManager/Devices/1']
            fields={'DeviceType':2,'Interface':'wlan0','ActiveConnection':'/org/freedesktop/NetworkManager/ActiveConnection/1','ActiveAccessPoint':'/org/freedesktop/NetworkManager/AccessPoint/1','HwAddress':'02:00:00:00:00:01','Frequency':5180,'LastScan':1000}
            reader.get.side_effect=lambda o,p,i,k:fields[k]
            result=native.context(reader,root);self.assertEqual(result['interfaces'][0]['identity'][2],3)
            reader.owner.side_effect=[':1.42',':1.43']
            with self.assertRaises(OSError):native.context(reader,root)
    def test_export_atomic_modes_and_sanitized_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'wireless.json'
            # Production ownership check remains exact root; fixtures model it.
            rootstat=mock.Mock(st_uid=0,st_mode=0o40755)
            actual=Path.stat
            def stat_path(p,*a,**k):return rootstat if p==path.parent else actual(p,*a,**k)
            with mock.patch.object(native.os,'geteuid',return_value=0),mock.patch.object(native,'collect',return_value=envelope()),mock.patch.object(Path,'stat',stat_path):
                native.export(path)
            self.assertEqual(path.stat().st_mode&0o777,0o644)
            self.assertEqual(json.loads(path.read_text())['schema'],1)
            self.assertFalse(list(path.parent.glob('.wireless-*')))
            with mock.patch.object(native.os,'geteuid',return_value=1000),self.assertRaises(PermissionError):native.export(path)


class CardTests(unittest.TestCase):
    def test_pci_human_caption_requires_exact_identity_and_driver_is_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'net/wlan0';(p/'wireless').mkdir(parents=True);(p/'ifindex').write_text('3')
            d=root/'0000:00:01.0';d.mkdir();(p/'device').symlink_to(d)
            for key,value in [('vendor','0x1234'),('device','0x5678'),('class','0x028000')]: (d/key).write_text(value)
            driver=root/'drivers/samplewifi';driver.mkdir(parents=True);(d/'driver').symlink_to(driver)
            named={'vendor_id':'1234','device_id':'5678','class_id':'0280','vendor_name':'Example','device_name':'Wireless Adapter'}
            with mock.patch.object(inventory.identity_inventory,'pci_names',return_value=({'0000:00:01.0':named},0)):
                result=inventory.cards(root/'net')[0]
                self.assertEqual(result['name'],'Example Wireless Adapter');self.assertEqual(result['driver'],'samplewifi')
                named['device_id']='ffff';result=inventory.cards(root/'net')[0]
                self.assertFalse(result['name_available']);self.assertEqual(result['driver'],'samplewifi')
                self.assertNotIn('name_parse_errors',result)
            with mock.patch.object(inventory.identity_inventory,'pci_names',return_value=({},2)):
                result=inventory.cards(root/'net')[0]
                self.assertFalse(result['name_available']);self.assertEqual(result['name_parse_errors'],2)
    def test_usb_device_product_name_does_not_require_pci_provider(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'net/wlan0';(p/'wireless').mkdir(parents=True);(p/'ifindex').write_text('3')
            d=root/'usb/1-1';d.mkdir(parents=True);(p/'device').symlink_to(d)
            for key,value in [('idVendor','1234'),('idProduct','5678'),('manufacturer','Example'),('product','USB Wireless')]: (d/key).write_text(value)
            with mock.patch.object(inventory.identity_inventory,'pci_names',side_effect=OSError(errno.ENOENT,'no lspci')):
                result=inventory.cards(root/'net')[0]
                self.assertEqual(result['name'],'Example USB Wireless');self.assertIsNone(result['driver'])

if __name__=='__main__':unittest.main()
