// SPDX-License-Identifier: GPL-2.0-only
import assert from 'node:assert/strict';
import {cpuRows,ssdRows,chargerExtraRows} from './metrics.js';
const value=(rows,name) => rows.find(r => r.label===name)?.value;
const cpu=[{cpu:0,counters:{package_throttle_count:'100',package_throttle_total_time_ms:'2500'}},
    {cpu:1,counters:{package_throttle_count:'101',package_throttle_total_time_ms:'2501'}}];
assert.equal(value(cpuRows(cpu),'Package Throttle Events (max CPU)'),'101');
assert.equal(value(cpuRows(cpu),'Package Throttle Total (max CPU)'),'2.501 s');
assert.equal(value(cpuRows(cpu,cpu),'Throttling Activity Since Update'),'None observed');
assert.equal(value(cpuRows([{cpu:0,counters:{core_throttle_count:'10000000000000000000'}}]),'Core Throttle Events (max CPU)'),'10000000000000000000');
assert.equal(value(cpuRows(),'Core Throttle Events (max CPU)'),'Unavailable');
const smart={schema:1,generated_boottime_seconds:100,devices:[{device:'nvme0n1',available:true,smart_passed:true,
    wear_used_percent:130,available_spare_percent:99,critical_warning_mask:0,counters:{media_errors:'0',data_units_written:'1208925819614629174706176'}}]};
assert.equal(value(ssdRows(smart,101),'nvme0n1 Wear Used'),'130%');
assert.equal(value(ssdRows(smart,101),'nvme0n1 Written Units (512 kB)'),'1208925819614629174706176');
for(const now of [99,281,NaN])assert.equal(value(ssdRows(smart,now),'nvme0n1 Wear Used'),'Unavailable');
assert.equal(value(ssdRows(null,200,['nvme0n1']),'nvme0n1 Media Errors'),'Unavailable');
const d={schema:1,words:[73,14,16387,45100,19524,220,8320,10,20,6016,0x8069,0,19524,16387],
    valid_mask:31,die_millicelsius:51511,vbat_pin_millivolts:8320,system_millivolts:9024,
    discharge_microamps:888000,charge_microamps:888000,battery_shunt_milliohms:5,maximum_cache_seconds:2,age_milliseconds:0};
assert.equal(value(chargerExtraRows(d),'Charger Die Temperature'),51511);
assert.equal(value(chargerExtraRows(d),'Charger Battery Discharge Current'),888);
assert.equal(value(chargerExtraRows(d),'Charger Thermal Warning'),'Clear');
assert.equal(value(chargerExtraRows({...d,age_milliseconds:2001}),'Charger Die Temperature'),'Unavailable');
assert.equal(value(chargerExtraRows({...d,discharge_microamps:444000}),'Charger Battery Discharge Current'),'Unavailable');
const off={...d,words:[...d.words],valid_mask:0};off.words[2]=0;
assert.equal(value(chargerExtraRows(off),'Charger Die Temperature'),'Unavailable');
assert.equal(value(chargerExtraRows(off),'Charger State'),'System regulation');
console.log('Vitals metrics: exact counters, no double-counting, stale-cache invalidation, ADC units and non-clearing status passed.');
const {pdSourceRows}=await import('./metrics.js');
const b=new Uint8Array(81);b[0]=1;b[1]=1;b[2]=65;b[3]=64;b[4]=65;
b[5]=32;b[6]=78;b[7]=178;b[8]=12;
new DataView(b.buffer).setUint32(9,0x64145,true);b[23]=4;
[0x0a01912c,0x2d12c,0x4b12c,0x64145].forEach((p,i) => new DataView(b.buffer).setUint32(24+4*i,p,true));
const env=() => ({schema:1,maximum_cache_seconds:2,data_hex:Buffer.from(b).toString('hex')});
assert.equal(value(pdSourceRows(env()),'USB-C 1 Source Profiles'),'5 V / 3 A; 9 V / 3 A; 15 V / 3 A; 20 V / 3.25 A');
b[36]=0;assert.equal(value(pdSourceRows(env()),'USB-C 1 Source Profiles'),'Unavailable');
b[1]=0;assert.equal(value(pdSourceRows(env()),'USB-C 1 Source Profiles'),'No active contract');
const all=[0x1912c,0x2d12c,0x4b12c,0x64145,0x40019234,0x800abcde,0xc0dc213c];
for(const port of [0,1]) for(const active of [0,4,5,6]) {
    b.fill(0);b[0]=1;b[1]=1;const o=3+10*port,s=23+29*port;
    b[o]=64;b[s]=7;new DataView(b.buffer).setUint32(o+6,all[active],true);
    if(active===0){b[o+1]=15;new DataView(b.buffer).setUint16(o+2,5000,true);new DataView(b.buffer).setUint16(o+4,3000,true);}
    all.forEach((p,i)=>new DataView(b.buffer).setUint32(s+1+4*i,p,true));
    const text=value(pdSourceRows(env()),`USB-C ${port+1} Source Profiles`);
    assert(text.includes('5 V / 3 A'));assert(text.endsWith('0xc0dc213c (raw)'));
    assert.equal(text.split('; ').length,7);
    new DataView(b.buffer).setUint32(o+6,0xc1234567,true);
    assert.equal(value(pdSourceRows(env()),`USB-C ${port+1} Source Profiles`),'Unavailable');
}
console.log('Seven source slots, both ports and raw nonfixed active contracts passed without unit conversion.');
