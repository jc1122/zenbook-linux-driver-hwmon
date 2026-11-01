/* SPDX-License-Identifier: MIT
 * Fixed read-only metrics. Preserve large counters as decimal strings; never
 * sum per-CPU package copies or substitute stale cached SMART information. */
const fields = ['core_throttle_count','core_throttle_total_time_ms','core_throttle_max_time_ms',
    'package_throttle_count','package_throttle_total_time_ms','package_throttle_max_time_ms'];
const counter = x => typeof x === 'string' && /^[0-9]{1,39}$/.test(x);
const row = (label,value,type,format='string') => ({label,value,type,format});

export function cpuRows(cpus=[], previous=[]) {
    const labels = ['Core Throttle Events (max CPU)','Core Throttle Total (max CPU)','Core Longest Throttle (max CPU)',
        'Package Throttle Events (max CPU)','Package Throttle Total (max CPU)','Package Longest Throttle (max CPU)'];
    const rows=fields.map((key,i) => {
        const values=cpus.map(c => c.counters?.[key]).filter(counter).map(BigInt);
        let value='Unavailable';
        if(values.length){
            const n=values.reduce((a,b) => a>b ? a:b);
            value=key.endsWith('_ms') ? `${n/1000n}.${String(n%1000n).padStart(3,'0')} s` : String(n);
        }
        return row(labels[i],value,'processor');
    });
    let increased=false, baseline=false;
    for(const c of cpus){
        const old=previous.find(x => x.cpu===c.cpu);
        if(!old)continue;
        for(const key of fields){
            const a=c.counters?.[key],b=old.counters?.[key];
            if(!counter(a) || !counter(b) || BigInt(a)<BigInt(b))continue;
            baseline=true;if(BigInt(a)>BigInt(b))increased=true;
        }
    }
    rows.push(row('Throttling Activity Since Update',baseline ? increased ? 'Observed' : 'None observed' : 'Unavailable (new baseline)','processor'));
    return rows;
}

export function ssdRows(data=null,uptime=NaN,known=[]) {
    const current=Array.isArray(data?.devices) ? data.devices.filter(x => x && /^nvme[0-9]+n[0-9]+$/.test(x.device)) : [];
    const names=[...new Set([...known,...current.map(x => x.device)])].filter(x => /^nvme[0-9]+n[0-9]+$/.test(x));
    const age=uptime-data?.generated_boottime_seconds;
    const fresh=data?.schema===1 && Number.isFinite(age) && age>=0 && age<=180;
    if(!names.length)return [row('SSD Health','Unavailable','storage')];
    return names.flatMap(name => {
        const d=current.find(x => x.device===name);
        const valid=fresh && d?.available===true;
        const add=(label,value) => row(`${name} ${label}`,valid && value!==undefined && value!==null ? value:'Unavailable','storage');
        const percent=(v,max) => Number.isInteger(v) && v>=0 && v<=max ? `${v}%`:null;
        const c=d?.counters || {};
        const count=key => counter(c[key]) ? c[key]:null;
        return [add('SMART Health',d?.smart_passed===true ? 'Passed' : d?.smart_passed===false ? 'Failed':null),
            add('Wear Used',percent(d?.wear_used_percent,255)),add('Available Spare',percent(d?.available_spare_percent,100)),
            add('Critical Warning',Number.isInteger(d?.critical_warning_mask) ? `0x${d.critical_warning_mask.toString(16)}`:null),
            ...[['Media Errors','media_errors'],['Error Log Entries','error_log_entries'],['Unsafe Shutdowns','unsafe_shutdowns'],
                ['Power Cycles','power_cycles'],['Power-on Hours','power_on_hours'],['Read Units (512 kB)','data_units_read'],
                ['Written Units (512 kB)','data_units_written'],['Warning Temperature Minutes','warning_temperature_minutes'],
                ['Critical Temperature Minutes','critical_temperature_minutes']].map(([label,key]) => add(label,count(key)))];
    });
}

export function chargerExtraRows(d=null) {
    const w=d?.words;
    const valid=d?.schema===1 && Array.isArray(w) && w.length===14 && w.every(x => Number.isInteger(x) && x>=0 && x<=65535) &&
        w[0]===73 && w[1]===14 && !(w[11]&~8191) && !(w[12]&32768) &&
        d.maximum_cache_seconds===2 && Number.isInteger(d.age_milliseconds) && d.age_milliseconds>=0 && d.age_milliseconds<=2000;
    let mask=0;
    const values={};
    if(valid && (w[2]&1) && (w[13]&1) && !((w[4]^w[12])&3840) && [2,6,9,10,12].includes((w[12]>>8)&15)){
        const temp=Math.trunc((2517-10*w[5])*1000000/6154);
        if(w[5]>0 && w[5]<255 && temp>=-10000 && temp<=170000){mask|=1;values.die_millicelsius=temp;}
        const v=(w[6]>>6)*64,s=(w[9]>>6)*96;
        if(!(w[6]&~16320) && v>=2500 && v<=17000){mask|=2;values.vbat_pin_millivolts=v;}
        if(!(w[9]&~16320) && s>=2500 && s<=24500){mask|=4;values.system_millivolts=s;}
        if(!(w[3]&2048)){
            if(w[7]<255){mask|=8;values.discharge_microamps=w[7]*88800;}
            if(w[8]<255){mask|=16;values.charge_microamps=w[8]*44400;}
        }
    }
    const converted=valid && d.battery_shunt_milliohms===5 && d.valid_mask===mask &&
        Object.entries(values).every(([k,v]) => d[k]===v);
    const add=(label,bit,key,format,scale=1) => row(label,converted && (mask&bit) ? d[key]/scale:'Unavailable','battery',converted && (mask&bit) ? format:'string');
    const rows=[add('Charger Die Temperature',1,'die_millicelsius','temp'),add('Charger VBAT Pin Voltage',2,'vbat_pin_millivolts','in'),
        add('Charger System Voltage',4,'system_millivolts','in'),add('Charger Battery Discharge Current',8,'discharge_microamps','amp',1000),
        add('Charger Battery Charge Current',16,'charge_microamps','amp',1000)];
    const state=valid ? ({0:'Reset',2:'Autonomous charging',4:'Battery low power',6:'Charging',7:'Fault',9:'OTG/supplemental',10:'Ready',12:'System regulation'}[(w[12]>>8)&15] || 'Startup/unknown'):'Unavailable';
    rows.push(row('Charger State',state,'battery'));
    rows.push(row('Charger Regulation Loop',valid ? ['System voltage','Charge current','Input current','Input voltage'][(w[10]>>13)&3]:'Unavailable','battery'));
    for(const [label,index,bit] of [['Charger Thermal Warning',11,6],['Charger FET Fault',11,2],['Charger Input Overvoltage',11,9],
        ['Charger System Overvoltage',11,10],['Charger SMBus Timeout',11,12],['Charger Low System PROCHOT',10,10],
        ['Charger Battery Overcurrent PROCHOT',10,11],['Charger Adapter Overcurrent PROCHOT',10,12]])
        rows.push(row(label,valid ? w[index]&(1<<bit) ? 'Active':'Clear':'Unavailable','battery'));
    return rows;
}

export const CPU_FIELDS=fields;

export function pdSourceRows(envelope=null) {
    const b=envelope?.schema===1 && envelope.maximum_cache_seconds===2 && /^[0-9a-f]{162}$/i.test(envelope.data_hex || '') ?
        envelope.data_hex.match(/../g).map(x => parseInt(x,16)):null;
    const word=(offset) => (b[offset]+256*b[offset+1]+65536*b[offset+2]+16777216*b[offset+3])>>>0;
    return [0,1].map(i => {
        let value='Unavailable';
        if(b && b[0]===1 && b[1]!==255 && b[3]!==255 && b[13]!==255){
            const o=3+10*i,s=23+29*i,n=b[s];
            if(!(b[1]&1) || !(b[o]&64))value='No active contract';
            else if(n>=1 && n<=7 && b.slice(s+1+4*n,s+29).every(x => x===0)){
                const words=Array.from({length:n},(_,j) => word(s+1+4*j));
                const active=word(o+6),mv=b[o+2]+256*b[o+3],ma=b[o+4]+256*b[o+5];
                const activeValid=active>>>30!==0 || mv===((active>>>10)&1023)*50 &&
                    ma===(active&1023)*10 && b[o+1]>0 && b[o+1]<255 && Math.abs(b[o+1]-mv*ma/1000000)<=1;
                if(words.every(w => w!==0) && words.includes(active) && activeValid &&
                    words[0]>>>30===0 && ((words[0]>>>10)&1023)===100 && words.every(w => w>>>30 ||
                        ((w>>>10)&1023)*50>=4500 && ((w>>>10)&1023)*50<=50000 && (w&1023)*10>=50 && (w&1023)*10<=5000))
                    value=words.map(w => w>>>30 ? `0x${w.toString(16).padStart(8,'0')} (raw)`:
                        `${((w>>>10)&1023)/20} V / ${(w&1023)/100} A`).join('; ');
            }
        }
        return row(`USB-C ${i+1} Source Profiles`,value,'battery');
    });
}
