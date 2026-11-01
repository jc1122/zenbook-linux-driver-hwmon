// SPDX-License-Identifier: GPL-2.0-only
import assert from 'node:assert/strict';
import {wirelessRows} from './wireless.js';
const bins=Array.from({length:9},(_,i)=>({lower_dbm:-20-10*i,upper_dbm:-10-10*i,count:i}));
const h={available:true,complete:true,bins,total_aps:36,unknown_signal_count:0,outside_bins_count:0,maximum_observation_age_seconds:12};
const data={schema:1,available:true,age_seconds:2,interfaces:[{interface:'wlan0',connected:true,capability:{available:true,maximum_mbit_s:1200.9,operation_width_mhz:160,best_profile:{spatial_streams:2}},association_phy:{available:true,family:'802.11ax'}}],cards:[{interface:'wlan0',name_available:true,name:'Example Wireless'}],histograms:{'2_4G':h,'5G':h,'6G':h}};
const get=(d,label)=>wirelessRows(d,['wlan0']).find(r=>r.label===label)?.value;
assert.equal(get(data,'wlan0 AP Capability Ceiling (HT/VHT/HE)'),'1200.9 Mbit/s (derived)');
assert.equal(get(data,'wlan0 Association PHY'),'802.11ax');
assert.equal(get(data,'Wi-Fi 5 GHz APs [-20, -10) dBm'),'0');
assert.equal(get(data,'wlan0 Wi-Fi Card'),'Example Wireless');
assert.equal(get({...data,age_seconds:46},'wlan0 Association PHY'),'Unavailable');
assert.equal(get(null,'wlan0 AP Operation Width'),'Unavailable');
assert.equal(get({...data,histograms:{'5G':{...h,complete:false}}},'Wi-Fi 5 GHz APs [-20, -10) dBm'),'Unavailable');
assert.equal(get({...data,histograms:{'5G':{...h,unknown_signal_count:3,complete:false}}},'Wi-Fi 5 GHz APs Without dBm'),'3');
assert.equal(wirelessRows(data).length,45);
assert.ok(wirelessRows(data).every(r=>r.type==='network' && r.format==='string'));
console.log('Wireless Vitals capability, histogram, unavailable and freshness checks passed');
