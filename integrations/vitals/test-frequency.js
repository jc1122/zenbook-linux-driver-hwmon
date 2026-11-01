// SPDX-License-Identifier: GPL-2.0-only
import assert from 'node:assert/strict';
import {frequencyRows,packagePowerRows} from './frequency.js';
import {readFileSync} from 'node:fs';
const sample=() => ({schema:1,cpu:0,reference_mhz:100,
    current:{errno:0,ratio:31,mhz:3100,raw_msr_hex:'0x0000242d00001f00'},
    maximum:{errno:0,ratio:46,mhz:4600,raw_msr_hex:'0x2c2c2c2c2c2c2e2e'}});
let rows=frequencyRows(sample());
assert.equal(rows[0].value,3100000000);assert.equal(rows[0].format,'hertz');
assert.equal(rows[1].value,4600000000);assert.equal(rows[0].type,'processor');
for(const [key,value] of [['schema',2],['cpu',1],['reference_mhz',0],['reference_mhz',1001],['reference_mhz',true]]) {
    const data=sample();data[key]=value;assert(frequencyRows(data).every(r => r.value==='Unavailable'));
}
for(const [key,value] of [['errno',5],['ratio',30],['mhz',3101],['mhz',true],['raw_msr_hex','0x0'],['raw_msr_hex','0x0000242d00000000']]) {
    const data=sample();data.current[key]=value;rows=frequencyRows(data);
    assert.equal(rows[0].value,'Unavailable');assert.equal(rows[1].value,4600000000);
}
assert(frequencyRows().every(r => r.value==='Unavailable'));
console.log('CPU-reported frequency quantities, independent fields and malformed/error states passed.');
const packageSample=()=>({schema:1,cpu:0,energy_before:1000,energy_after:17384,energy_exponent:14,
    elapsed_microseconds:1000000,power_microwatts:1000000,maximum_cache_seconds:1,age_microseconds:0});
assert.equal(packagePowerRows(packageSample())[0].value,1000000);
assert.equal(packagePowerRows({...packageSample(),energy_before:4294967280,energy_after:240,
    elapsed_microseconds:200000,power_microwatts:78125})[0].value,78125);
for(const [key,value] of [['schema',2],['cpu',1],['energy_before',-1],['energy_after',4294967296],['energy_exponent',0],
    ['elapsed_microseconds',99999],['age_microseconds',1000000],['power_microwatts',1],['energy_after',1000]]) {
    const data=packageSample();data[key]=value;assert.equal(packagePowerRows(data)[0].value,'Unavailable');
}
assert.equal(packagePowerRows()[0].format,'string');

const method=readFileSync(new URL('./frequency-method.txt',import.meta.url),'utf8');
assert(!method.includes('cpu_package_power'));  // root-only since 0.79; RAPL comes from the service reply
async function wire(mode) {
    const emitted=[];let metricsReads=0,nameReads=0,serviceCalls=0;
    class File {
        constructor(path){this.path=path;}
        async list(){return ['hwmon4'];}
        async read(){
            if(this.path.endsWith('/name'))return ++nameReads===3 && mode==='replaced' ? 'other_device':'zenbook_ec';
            assert(this.path.endsWith('/cpu_reported_frequency'));metricsReads++;
            if(mode==='fault')throw new Error('EIO');
            return JSON.stringify(sample());
        }
    }
    const serviceInputs=report => ({packagePower:report?.cpu_package_power?.available ? report.cpu_package_power.energy_sample:null});
    const Handler=Function('FileModule','frequencyRows','packagePowerRows','serviceInputs',`return class {${method}}`)({File},frequencyRows,packagePowerRows,serviceInputs);
    const handler=new Handler();handler._returnValue=(_,label,value) => emitted.push({label,value});
    handler._zenbookServiceMetrics=async () => { serviceCalls++;
        return mode==='power-fault' || mode==='fault' ? null:{schema:1,cpu_package_power:{available:true,energy_sample:packageSample()}}; };
    handler._queryZenbookFrequency(()=>{});handler._queryZenbookFrequency(()=>{});
    if(mode==='destroyed')handler._zenbookChargerDestroyed=true;
    for(let i=0;i<50 && handler._zenbookFrequencyPending;i++)await Promise.resolve();
    assert.equal(handler._zenbookFrequencyPending,false);assert.equal(metricsReads,1);assert.equal(serviceCalls,1);
    if(mode==='destroyed')assert.equal(emitted.length,0);
    else {
        assert.equal(emitted.length,3);
        assert.equal(emitted[0].value,mode==='normal' || mode==='power-fault' ? 3100000000:'Unavailable');
        assert.equal(emitted[2].value,mode==='normal' ? 1000000:'Unavailable');
    }
}
for(const mode of ['normal','replaced','fault','power-fault','destroyed'])await wire(mode);
console.log('Vitals frequency discovery, overlapping refresh, service package power, provider replacement, read failure and destruction passed.');
