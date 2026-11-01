/* SPDX-License-Identifier: MIT
 * Parsed cached metadata; capability rates are not live throughput. */
const row=(label,value) => ({label,value,type:'network',format:'string'});
const count=x => Number.isInteger(x) && x>=0;
const finite=x => typeof x==='number' && Number.isFinite(x) && x>=0;
export function wirelessRows(data=null,known=[]) {
    const current=Array.isArray(data?.interfaces) ? data.interfaces : [];
    const cards=Array.isArray(data?.cards) ? data.cards : [];
    const names=[...new Set([...known,...current.map(x=>x?.interface),...cards.map(x=>x?.interface)])]
        .filter(x=>typeof x==='string' && /^[^/\s\x00]{1,15}$/.test(x));
    const fresh=data?.available===true && data.schema===1 && finite(data.age_seconds) && data.age_seconds<=45;
    const rows=[row('Wi-Fi Metadata Cache Age',fresh ? `${data.age_seconds} s`:'Unavailable')];
    for(const name of names) {
        const d=current.find(x=>x?.interface===name),c=cards.find(x=>x?.interface===name);
        const cap=fresh && d?.connected===true && d.capability?.available===true ? d.capability:null;
        const phy=fresh && d?.connected===true && d.association_phy?.available===true ? d.association_phy:null;
        const add=(label,value) => rows.push(row(`${name} ${label}`,value ?? 'Unavailable'));
        add('Wi-Fi Card',c?.name_available===true && typeof c.name==='string' ? c.name:null);
        add('Association PHY',/^802\.11(n|ac|ax|be)$/.test(phy?.family) ? phy.family:null);
        add('AP Capability Ceiling (HT/VHT/HE)',finite(cap?.maximum_mbit_s) && cap.maximum_mbit_s>0 ? `${cap.maximum_mbit_s} Mbit/s (derived)`:null);
        add('AP Operation Width',[20,40,80,160].includes(cap?.operation_width_mhz) ? `${cap.operation_width_mhz} MHz`:null);
        const streams=cap?.best_profile?.spatial_streams;
        add('AP Capability Spatial Streams',count(streams) && streams>=1 && streams<=8 ? String(streams):null);
    }
    for(const [band,label] of [['2_4G','2.4 GHz'],['5G','5 GHz'],['6G','6 GHz']]) {
        const h=fresh ? data.histograms?.[band]:null;
        const valid=h?.available===true && h.complete===true && Array.isArray(h.bins) && h.bins.length===9;
        for(let i=0;i<9;i++) {
            const lo=-20-10*i,hi=-10-10*i,b=h?.bins?.[i];
            rows.push(row(`Wi-Fi ${label} APs [${lo}, ${hi}) dBm`,valid && b?.lower_dbm===lo && b?.upper_dbm===hi && count(b.count) ? String(b.count):'Unavailable'));
        }
        rows.push(row(`Wi-Fi ${label} Cached APs`,valid && count(h.total_aps) ? String(h.total_aps):'Unavailable'));
        rows.push(row(`Wi-Fi ${label} APs Without dBm`,h?.available===true && count(h.unknown_signal_count) ? String(h.unknown_signal_count):'Unavailable'));
        rows.push(row(`Wi-Fi ${label} APs Outside Bins`,valid && count(h.outside_bins_count) ? String(h.outside_bins_count):'Unavailable'));
        rows.push(row(`Wi-Fi ${label} Oldest Observation`,h?.available===true && finite(h.maximum_observation_age_seconds) ? `${h.maximum_observation_age_seconds} s`:'Unavailable'));
    }
    return rows;
}
