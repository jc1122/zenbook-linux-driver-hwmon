// SPDX-License-Identifier: GPL-2.0-only
import assert from 'node:assert/strict';
import {gaugeRows,gaugeExtraRows,sbsRows,lifetimeRows,pdAlertRows} from './battery.js';
import {chargerRows} from './charger.js';
const env=seconds => ({schema:1,device_type_hex:'5645',firmware_hex:'45560234004002000000000000',age_milliseconds:0,maximum_cache_seconds:seconds});
const value=(r,l) => r.find(x => x.label===l)?.value;
const a=Buffer.alloc(20),t=Buffer.alloc(14),l=Buffer.alloc(31);
[[0,4100],[2,4200],[8,8300],[10,8400]].forEach(([o,v]) => a.writeUInt16LE(v,o));a.writeInt16LE(-1200,12);
[3100,3050,3060,4700,4700,3050,3060].forEach((v,i) => t.writeUInt16LE(v,2*i));
const gauge={...env(5),da1_hex:a.toString('hex'),da2_hex:t.toString('hex')};
assert.equal(value(gaugeRows(gauge),'Battery Internal Temperature'),36850);
assert.equal(value(gaugeRows(gauge),'Battery TS3 Temperature'),'Unavailable');
assert.equal(value(gaugeRows(gauge),'Battery Cell 1 Sample Current'),-1200);
assert.equal(value(gaugeRows({...gauge,age_milliseconds:5001}),'Battery Internal Temperature'),'Unavailable');
[[0,4300],[2,4250],[8,3000],[10,3100],[12,32767],[14,32767],[16,250],[18,6500]].forEach(([o,v]) => l.writeUInt16LE(v,o));
[[20,-9000],[22,-5000],[24,-4000]].forEach(([o,v]) => l.writeInt16LE(v,o));
[[26,50],[27,10],[28,2],[29,55],[30,12]].forEach(([o,v]) => l[o]=v);
const life={...env(60),block1_prefix_hex:l.toString('hex')};
assert.equal(value(lifetimeRows(life),'Battery Recorded Highest Discharge Current'),9000);
assert.equal(value(lifetimeRows(life),'Battery Recorded Highest Average Discharge Power'),40000000);
assert.equal(value(lifetimeRows({...life,age_milliseconds:60001}),'Battery Recorded Highest Discharge Current'),'Unavailable');
assert.equal(value(lifetimeRows({...life,block1_prefix_hex:Buffer.alloc(31).toString('hex')}),'Battery Recorded Highest Charge Current'),'Unavailable');
const e=Buffer.alloc(31);e.writeUInt16LE(210,16);e.writeUInt16LE(292,18);e.writeUInt16LE(4,28);e[30]=244;
const events={...life,block2_prefix_hex:'04000400',block4_prefix_hex:Buffer.alloc(31).toString('hex'),block5_prefix_hex:e.toString('hex')};
assert.equal(value(lifetimeRows(events),'Battery Recorded Shutdowns'),'4');
assert.equal(value(lifetimeRows(events),'Battery Recorded Valid Charge Termination Events'),'210');
assert.equal(value(lifetimeRows(events),'Battery Recorded Valid Charge Termination Last Cycle'),'292');
assert.equal(value(lifetimeRows(events),'Battery Recorded Cell Overvoltage Last Cycle'),'Never');
assert.equal(value(lifetimeRows(events),'Battery Recorded Resistance Update Disable Last Cycle'),'Unavailable (partial field)');
assert.equal(value(lifetimeRows(life),'Battery Recorded Shutdowns'),'Unavailable');
assert.equal(value(lifetimeRows({...events,age_milliseconds:60001}),'Battery Recorded Valid Charge Termination Events'),'Unavailable');
assert.equal(gaugeRows(gauge).length,11);assert.equal(lifetimeRows(life).length,61);
const aFull=Buffer.alloc(32),tFull=Buffer.alloc(24);a.copy(aFull);t.copy(tFull);
aFull.writeInt16LE(-492,20);aFull.writeInt16LE(-492,28);aFull.writeInt16LE(-700,30);tFull.writeUInt16LE(3000,14);
const extra={...env(15),da1_hex:aFull.toString('hex'),da2_hex:tFull.toString('hex')};
assert.equal(value(gaugeExtraRows(extra),'Battery Gauge Cell 1 Power'),-4920000);
assert.equal(value(gaugeExtraRows(extra),'Battery Gauge Power'),-4920000);
assert.equal(value(gaugeExtraRows(extra),'Battery Gauge Average Power'),-7000000);
assert.equal(value(gaugeExtraRows(extra),'Battery Gauge Algorithm Temperature'),26850);
assert.equal(value(gaugeExtraRows({...extra,age_milliseconds:15001}),'Battery Gauge Power'),'Unavailable');
aFull.writeInt16LE(-984,20);
const wrongPower={...extra,da1_hex:aFull.toString('hex')};
assert.equal(value(gaugeExtraRows(wrongPower),'Battery Gauge Cell 1 Power'),'Unavailable');
assert.equal(value(gaugeExtraRows(wrongPower),'Battery Gauge Power'),-4920000);
assert.equal(value(gaugeExtraRows(wrongPower),'Battery Gauge Algorithm Temperature'),26850);
const separatePack=Buffer.from(aFull);separatePack.writeInt16LE(-492,20);separatePack.writeInt16LE(-1570,28);
assert.equal(value(gaugeExtraRows({...extra,da1_hex:separatePack.toString('hex')}),'Battery Gauge Power'),-15700000);
for(const [offset,label,other,expected] of [[28,'Battery Gauge Power','Battery Gauge Average Power',-7000000],[30,'Battery Gauge Average Power','Battery Gauge Power',-4920000]]){
    for(const raw of [-32768,32767,-20001,20001]){
        const frame=Buffer.from(aFull);frame.writeInt16LE(raw,offset);
        const rows=gaugeExtraRows({...extra,da1_hex:frame.toString('hex')});
        assert.equal(value(rows,label),'Unavailable');assert.equal(value(rows,other),expected);
    }
}
assert.equal(gaugeExtraRows().length,5);
assert.equal(value(lifetimeRows(life),'Battery Recorded FET Highest Temperature'),'Unavailable');
const full={...events,block3_prefix_hex:'00000000',complete_blocks:true};
[32,8,26,32,32].forEach((size,i) => {
    const data=Buffer.alloc(size);Buffer.from(full[`block${i+1}_prefix_hex`],'hex').copy(data);
    if(i===0)data[31]=48;
    full[`block${i+1}_hex`]=data.toString('hex');
});
assert.equal(value(lifetimeRows(full),'Battery Recorded FET Highest Temperature'),48000);
assert.equal(value(lifetimeRows(full),'Battery Recorded Resistance Update Disable Last Cycle'),'244');
assert.equal(value(lifetimeRows(full),'Battery Recorded Discharge Short Circuit Last Cycle'),'Never');
for(const update of [{complete_blocks:1},{block3_hex:'00'.repeat(4)},{block2_hex:'00'.repeat(8)},
    {block1_hex:full.block1_hex.slice(0,-2)+'7f'},{block5_hex:full.block5_hex.slice(0,-2)}])
    assert.equal(value(lifetimeRows({...full,...update}),'Battery Recorded FET Highest Temperature'),'Unavailable');
const packet=Buffer.from([1,3,65,69,65,32,78,178,12,69,65,6,0,...Array(10).fill(0)]);
const pd={schema:1,maximum_cache_seconds:5,age_milliseconds:0,contract_hex:packet.toString('hex'),
    ports:[{connector:1,alert_hex:'00000000'},{connector:2,alert_hex:'00000000'}]};
assert.equal(value(pdAlertRows(pd,chargerRows),'USB-C 1 Last Received PD Alert'),'No alert recorded');
assert.equal(value(pdAlertRows(pd,chargerRows),'USB-C 2 Last Received PD Alert'),'No active contract');
pd.ports[0].alert_hex='00002102';
assert.equal(value(pdAlertRows(pd,chargerRows),'USB-C 1 Last Received PD Alert'),'0x02210000');
assert.equal(value(pdAlertRows({...pd,age_milliseconds:5001},chargerRows),'USB-C 1 Last Received PD Alert'),'Unavailable');
pd.ports[1].alert_hex='00000002';
assert.equal(value(pdAlertRows(pd,chargerRows),'USB-C 2 Last Received PD Alert'),'Unavailable');
pd.ports[0].alert_hex='01000000';
assert.equal(value(pdAlertRows(pd,chargerRows),'USB-C 1 Last Received PD Alert'),'Unavailable');
delete pd.ports[0].alert_hex;
assert.equal(value(pdAlertRows(pd,chargerRows),'USB-C 1 Last Received PD Alert'),'Unavailable');
assert.equal(pdAlertRows().length,2);
console.log('Battery Vitals: live pin units, current sign, inactive sensors, history extrema and stale/invalid data suppression passed.');

const sbs={schema:1,device_type_hex:'5645',firmware_hex:'45560234004002000000000000',maximum_cache_seconds:30,age_milliseconds:0,
    words:[0x31,0x6001,3000,8300,64536,65535,3000,8700,1,80,60,6000,7500,200,9000,7700]};
assert.equal(sbsRows(sbs).length,12);
assert.equal(value(sbsRows(sbs),'Battery SBS Pack Voltage'),8300);
assert.equal(value(sbsRows({...sbs,transport:'native_smbus_read_word'}),'Battery SBS Pack Voltage'),8300);
assert.equal(value(sbsRows({...sbs,transport:'unknown'}),'Battery SBS Pack Voltage'),'Unavailable');
assert.equal(value(sbsRows(sbs),'Battery SBS Current'),-1000);
assert.equal(value(sbsRows(sbs),'Battery SBS Average Current'),-1);
assert.equal(value(sbsRows(sbs),'Battery SBS Requested Charging Current'),3000);
assert.equal(value(sbsRows(sbs),'Battery SBS Remaining Capacity'),'6000 mAh');
assert.equal(value(sbsRows({...sbs,words:sbs.words.map((v,i) => i===1 ? v|0x8000:v)}),'Battery SBS Remaining Capacity'),'60 Wh');
assert.equal(value(sbsRows({...sbs,words:sbs.words.map((v,i) => i===6 ? 65535:v)}),'Battery SBS Requested Charging Current'),'Maximum requested');
for(const change of [{age_milliseconds:30001},{schema:true},{words:[]},{words:sbs.words.map((v,i) => i===0 ? 0x131:v)}])
    assert.equal(value(sbsRows({...sbs,...change}),'Battery SBS Pack Voltage'),'Unavailable');
assert.equal(sbsRows().length,12);

const timed={...full};
const timeBlock=Buffer.alloc(26);
[100,2,3,90,0,0,0,4].forEach((n,i) => timeBlock.writeUInt16LE(n,2*i));
timeBlock.fill(0xa5,16);
timed.block3_hex=timeBlock.toString('hex');timed.block3_prefix_hex=timeBlock.subarray(0,4).toString('hex');
assert.equal(value(lifetimeRows(timed),'Battery Recorded Firmware Runtime'),'200 h (2 h steps)');
assert.equal(value(lifetimeRows(life),'Battery Recorded Firmware Runtime'),'Unavailable');
assert.equal(value(lifetimeRows({...timed,age_milliseconds:60001}),'Battery Recorded Firmware Runtime'),'Unavailable');
for(const words of [[65535,2,3,90,0,0,0,4],[100,2,3,110,0,0,0,4],[100,0,0,0,0,0,0,0]]){
    const block=Buffer.alloc(26);words.forEach((n,i) => block.writeUInt16LE(n,2*i));
    const data={...full,block3_hex:block.toString('hex'),block3_prefix_hex:block.subarray(0,4).toString('hex')};
    assert.equal(value(lifetimeRows(data),'Battery Recorded Firmware Runtime'),'Unavailable');
    assert.equal(value(lifetimeRows(data),'Battery Recorded FET Highest Temperature'),48000);
}

assert.equal(value(lifetimeRows(timed),'Battery Recorded Region UT Time'),'4 h (2 h steps)');
assert.equal(value(lifetimeRows(timed),'Battery Recorded Region STL Time'),'180 h (2 h steps)');
assert.equal(value(lifetimeRows(timed),'Battery Recorded Region RT Time'),'0 h (2 h steps)');
assert.equal(value(lifetimeRows(life),'Battery Recorded Region UT Time'),'Unavailable');
const balanced={...timed,block2_hex:'0400040003050000'};
assert.equal(value(lifetimeRows(balanced),'Battery Recorded Cell 1 Balancing Time'),'6 h (2 h steps)');
assert.equal(value(lifetimeRows(balanced),'Battery Recorded Cell 2 Balancing Time'),'10 h (2 h steps)');
assert.equal(value(lifetimeRows({...balanced,block2_hex:'04000400ff050000'}),'Battery Recorded Cell 1 Balancing Time'),'≥ 510 h (saturated)');
assert.equal(value(lifetimeRows({...balanced,block2_hex:'04000400ff050000'}),'Battery Recorded Cell 2 Balancing Time'),'10 h (2 h steps)');
assert.equal(value(lifetimeRows({...balanced,block2_hex:'0400040003050100'}),'Battery Recorded Cell 2 Balancing Time'),'Unavailable');
