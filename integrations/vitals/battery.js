/* SPDX-License-Identifier: MIT */
const row=(label,value,format='string') => ({label,value,format,type:'battery'});
const bytes=(d,key,n) => typeof d?.[key]==='string' && new RegExp(`^[0-9a-f]{${2*n}}$`,'i').test(d[key]) ? d[key].match(/../g).map(x => parseInt(x,16)):null;
const word=(a,o,signed=false) => {let n=a[o]+256*a[o+1];return signed && n>=32768 ? n-65536:n;};
const valid=(d,seconds) => d?.schema===1 && d.device_type_hex==='5645' && /^45560234004002[0-9a-f]{12}$/i.test(d.firmware_hex || '') &&
    d.maximum_cache_seconds===seconds && Number.isInteger(d.age_milliseconds) && d.age_milliseconds>=0 && d.age_milliseconds<=1000*seconds;

export function sbsRows(d=null) {
    const w=d?.words,signed=n => n>=32768 ? n-65536:n;
    const good=valid(d,30) && (d.transport===undefined || ['legacy_i2c_combined_read_word','native_smbus_read_word'].includes(d.transport)) &&
        Array.isArray(w) && w.length===16 && w.every(n => Number.isInteger(n) && n>=0 && n<=65535) &&
        w[0]===0x31 && w[2]>=2000 && w[2]<=4000 && w[3]>=4000 && w[3]<=11000 &&
        [4,5].every(i => Math.abs(signed(w[i]))<=20000) && [8,9,10].every(i => w[i]<=100) && w[15]>=4000 && w[15]<=11000;
    const add=(name,value,format='string') => row('Battery SBS '+name,good ? value:'Unavailable',good ? format:'string');
    const rows=[add('Pack Voltage',good ? w[3]:null,'in'),add('Current',good ? signed(w[4]):null,'amp'),
        add('Average Current',good ? signed(w[5]):null,'amp'),add('Selected Temperature',good ? w[2]*100-273150:null,'temp')];
    for(const [name,i,format] of [['Requested Charging Current',6,'amp'],['Requested Charging Voltage',7,'in']]){
        const maximum=good && w[i]===65535;
        rows.push(row('Battery SBS '+name,good ? maximum ? 'Maximum requested':w[i]:'Unavailable',good && !maximum ? format:'string'));
    }
    for(const [name,i] of [['Relative State of Charge',9],['Absolute State of Charge',10],['SOC Maximum Error',8]])
        rows.push(add(name,good ? `${w[i]} %`:null));
    for(const [name,i] of [['Remaining Capacity',11],['Full Capacity',12],['Design Capacity',14]]){
        const ok=good && w[i]!==65535;
        rows.push(row('Battery SBS '+name,ok ? (w[1]&0x8000 ? `${w[i]/100} Wh`:`${w[i]} mAh`):'Unavailable'));
    }
    return rows;
}

// Reuse the installed charger's contract decoder through the caller so helper
// filenames can differ between the repository and Vitals without duplicate logic.
export function pdAlertRows(d=null, contractDecoder=null) {
    const good=d?.schema===1 && d.maximum_cache_seconds===5 && Number.isInteger(d.age_milliseconds) &&
        d.age_milliseconds>=0 && d.age_milliseconds<=5000 && Array.isArray(d.ports) && d.ports.length===2;
    const contracts=good && typeof contractDecoder==='function' ? contractDecoder({schema:1,data_hex:d.contract_hex}):[];
    return [1,2].map(connector => {
        const state=contracts.find(r => r.label===`USB-C ${connector} State`)?.value;
        const port=good && d.ports[connector-1]?.connector===connector ? d.ports[connector-1]:null;
        const raw=bytes(port,'alert_hex',4);
        let text='Unavailable';
        if(raw && state==='Connected' && raw[0]===0 && raw[1]===0){
            const ado=(raw[2]*65536+raw[3]*16777216)>>>0;
            text=ado===0 ? 'No alert recorded':`0x${ado.toString(16).padStart(8,'0')}`;
        }else if(raw && state==='No active contract' && raw.every(x => x===0))text='No active contract';
        return row(`USB-C ${connector} Last Received PD Alert`,text);
    });
}

export function gaugeRows(d=null) {
    const a=bytes(d,'da1_hex',20),t=bytes(d,'da2_hex',14);
    const good=valid(d,5) && a && t && [0,2].every(o => word(a,o)>=2000 && word(a,o)<=5000) && [4,6].every(o => [0,65535].includes(word(a,o)));
    const rows=['Internal','TS1','TS2','TS3','TS4','Cell','FET'].map((name,i) => {
        const value=good ? word(t,2*i)*100-273150:NaN;
        const ok=value>=-40000 && value<=125000;
        return row(`Battery ${name} Temperature`,ok ? value:'Unavailable',ok ? 'temp':'string');
    });
    for(const [name,o] of [['BAT Pin',8],['PACK Pin',10]]){
        const value=good ? word(a,o):NaN,ok=value>=4000 && value<=17000;
        rows.push(row(`Battery Gauge ${name} Voltage`,ok ? value:'Unavailable',ok ? 'in':'string'));
    }
    for(let i=0;i<2;i++)rows.push(row(`Battery Cell ${i+1} Sample Current`,good ? word(a,12+2*i,true):'Unavailable',good ? 'amp':'string'));
    return rows;
}

export function gaugeExtraRows(d=null) {
    const a=bytes(d,'da1_hex',32),t=bytes(d,'da2_hex',24);
    const good=valid(d,15) && a && t && [0,2].every(o => word(a,o)>=2000 && word(a,o)<=5000) &&
        [4,6].every(o => [0,65535].includes(word(a,o)));
    const rows=[];
    for(let i=0;i<2;i++){
        const current=good ? word(a,12+2*i,true):NaN;
        const power=good ? word(a,20+2*i,true)/100:NaN;
        const ok=good && Math.abs(current)<=20000 && Math.abs(power-word(a,2*i)*current/1000000)<=.03;
        rows.push(row(`Battery Gauge Cell ${i+1} Power`,ok ? power*1000000:'Unavailable',ok ? 'watt':'string'));
    }
    const total=good ? word(a,28,true)/100:NaN,average=good ? word(a,30,true)/100:NaN;
    // Pack SBS V/I and per-cell sample pairs do not establish a common time.
    const totalOk=good && Math.abs(total)<=200;
    rows.push(row('Battery Gauge Power',totalOk ? total*1000000:'Unavailable',totalOk ? 'watt':'string'));
    const avgOk=good && Math.abs(average)<=200;
    rows.push(row('Battery Gauge Average Power',avgOk ? average*1000000:'Unavailable',avgOk ? 'watt':'string'));
    const mc=good ? word(t,14)*100-273150:NaN,ok=mc>=-40000 && mc<=125000;
    rows.push(row('Battery Gauge Algorithm Temperature',ok ? mc:'Unavailable',ok ? 'temp':'string'));
    return rows;
}

export function lifetimeRows(d=null) {
    const b=bytes(d,'block1_prefix_hex',31);
    let good=valid(d,60) && b;
    const full=d?.complete_blocks===true ? Object.fromEntries([32,8,26,32,32].map((n,i) => [i+1,bytes(d,`block${i+1}_hex`,n)])):null;
    const complete=full && [1,2,3,4,5].every(i => {
        const prefix=bytes(d,`block${i}_prefix_hex`,i===2 || i===3 ? 4:31);
        return full[i] && prefix && prefix.every((v,j) => v===full[i][j]);
    });
    if((d?.complete_blocks!==undefined && typeof d.complete_blocks!=='boolean') || (d?.complete_blocks===true && !complete))good=false;
    if(good){
        good=[0,1].every(i => word(b,8+2*i)>=1500 && word(b,8+2*i)<=word(b,2*i) && word(b,2*i)<=5000) &&
            [2,3].every(i => word(b,2*i)===0 && [0,32767].includes(word(b,8+2*i))) && word(b,16)<=3000 &&
            word(b,18,true)>=0 && word(b,18,true)<=20000 && [20,22,24].every(o => word(b,o,true)>=-20000 && word(b,o,true)<=0);
    }
    const signed=n => n>=128 ? n-256:n;
    if(good)good=[26,27,29,30].every(o => signed(b[o])>=-40 && signed(b[o])<=125) && signed(b[27])<=signed(b[26]) && signed(b[30])<=signed(b[29]);
    if(good && complete)good=signed(full[1][31])>=-40 && signed(full[1][31])<=125;
    const rows=[],add=(label,value,format) => rows.push(row('Battery Recorded '+label,good ? value:'Unavailable',good ? format:'string'));
    const times=good && complete ? Array.from({length:8},(_,i) => word(full[3],2*i)):null;
    const delta=times ? times[0]-times.slice(1).reduce((a,b) => a+b,0):NaN;
    const runtimeGood=times && times.every(v => v<65535) && delta>=0 && delta<=7;
    rows.push(row('Battery Recorded Firmware Runtime',runtimeGood ? `${times[0]*2} h (2 h steps)`:'Unavailable'));
    for(const [i,code] of ['UT','LT','STL','RT','STH','HT','OT'].entries())
        rows.push(row(`Battery Recorded Region ${code} Time`,runtimeGood ? `${times[i+1]*2} h (2 h steps)`:'Unavailable'));
    const balanceGood=good && complete && full[2][6]===0 && full[2][7]===0;
    for(let i=0;i<2;i++)rows.push(row(`Battery Recorded Cell ${i+1} Balancing Time`,
        !balanceGood ? 'Unavailable' : full[2][4+i]<255 ? `${full[2][4+i]*2} h (2 h steps)` : '≥ 510 h (saturated)'));
    for(let i=0;i<2;i++){
        add(`Cell ${i+1} Highest Voltage`,good ? word(b,2*i):null,'in');
        add(`Cell ${i+1} Lowest Voltage`,good ? word(b,8+2*i):null,'in');
    }
    for(const [name,o] of [['Cell Highest Temperature',26],['Cell Lowest Temperature',27],['Internal Highest Temperature',29],['Internal Lowest Temperature',30]])
        add(name,good ? signed(b[o])*1000:null,'temp');
    rows.push(row('Battery Recorded FET Highest Temperature',good && complete ? signed(full[1][31])*1000:'Unavailable',good && complete ? 'temp':'string'));
    add('Highest Cell Voltage Difference',good ? word(b,16):null,'in');
    add('Highest Charge Current',good ? word(b,18,true):null,'amp');
    add('Highest Discharge Current',good ? -word(b,20,true):null,'amp');
    add('Highest Average Discharge Current',good ? -word(b,22,true):null,'amp');
    add('Highest Average Discharge Power',good ? -word(b,24,true)*10000:null,'watt');
    add('Highest Cell Temperature Difference',good ? b[28]*1000:null,'temp');
    const reset=bytes(d,'block2_prefix_hex',4);
    for(const [i,name] of ['Shutdowns','Partial Resets','Full Resets','Watchdog Resets'].entries())
        rows.push(row('Battery Recorded '+name,good && reset ? String(reset[i]):'Unavailable'));
    const events=[
        [4,['Cell Overvoltage','Cell Undervoltage','Discharge Overcurrent 1','Discharge Overcurrent 2',
            'Charge Overcurrent 1','Charge Overcurrent 2','Discharge Overload','Discharge Short Circuit']],
        [5,['Charge Short Circuit','Charge Overtemperature','Discharge Overtemperature','FET Overtemperature',
            'Valid Charge Termination','Qmax Update','Resistance Update','Resistance Update Disable']]];
    for(const [block,names] of events){
        const raw=complete ? full[block]:bytes(d,`block${block}_prefix_hex`,31);
        for(const [i,name] of names.entries()){
            const count=good && raw ? word(raw,4*i):null;
            const fieldComplete=raw && 4*i+4<=raw.length;
            const last=count!==null && fieldComplete ? word(raw,4*i+2):null;
            rows.push(row(`Battery Recorded ${name} Events`,count===null ? 'Unavailable':String(count)));
            rows.push(row(`Battery Recorded ${name} Last Cycle`,count===null ? 'Unavailable':
                !fieldComplete ? 'Unavailable (partial field)':count===0 ? 'Never':last===65535 ? 'Unavailable':String(last)));
        }
    }
    return rows;
}
