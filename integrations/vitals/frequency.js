/* SPDX-License-Identifier: MIT */
export function frequencyRows(data=null) {
    const reference=data?.reference_mhz;
    const valid=data?.schema===1 && data.cpu===0 && Number.isInteger(reference) && reference>0 && reference<=1000;
    return [['current','CPU0 Reported P-state Frequency'],['maximum','CPU0 Maximum Turbo Ratio Frequency']].map(([key,label]) => {
        const field=data?.[key];
        let mhz=null;
        if(valid && field?.errno===0 && Number.isInteger(field.ratio) && Number.isInteger(field.mhz) &&
                /^0x[0-9a-f]{16}$/.test(field.raw_msr_hex || '')) {
            const raw=BigInt(field.raw_msr_hex),ratio=Number(key==='current' ? (raw>>8n)&127n : raw&255n);
            if(ratio>0 && !(key==='maximum' && ratio===255) && field.ratio===ratio && field.mhz===ratio*reference)
                mhz=field.mhz;
        }
        return {label,value:mhz===null ? 'Unavailable':mhz*1000000,type:'processor',format:mhz===null ? 'string':'hertz'};
    });
}

export function packagePowerRows(data=null) {
    let value='Unavailable';
    if(data?.schema===1 && data.cpu===0 && data.maximum_cache_seconds===1 &&
            ['energy_before','energy_after','energy_exponent','elapsed_microseconds','power_microwatts','age_microseconds'].every(k=>Number.isSafeInteger(data[k])) &&
            data.energy_before>=0 && data.energy_before<=4294967295 && data.energy_after>=0 && data.energy_after<=4294967295 &&
            data.energy_exponent>=1 && data.energy_exponent<=31 && data.elapsed_microseconds>=100000 && data.elapsed_microseconds<=30000000 &&
            data.age_microseconds>=0 && data.age_microseconds<1000000 &&
            data.elapsed_microseconds<(2**(32-data.energy_exponent))*1000) {
        const delta=(BigInt(data.energy_after)-BigInt(data.energy_before))&4294967295n;
        const expected=((delta*1000000000n)>>BigInt(data.energy_exponent))*1000n/BigInt(data.elapsed_microseconds);
        if(delta>0n && expected>0n && expected<=1000000000n && BigInt(data.power_microwatts)===expected)value=data.power_microwatts;
    }
    return [{label:'CPU Package Power (RAPL)',value,type:'processor',format:typeof value==='number' ? 'watt':'string'}];
}
