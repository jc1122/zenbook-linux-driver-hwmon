/* SPDX-License-Identifier: MIT
 * Read-only Zenbook monitoring adapter. Limits and measured platform power
 * remain separate. No charger-current estimate or privileged subprocess. */
export function chargerRows(envelope = null, powerMicrowatts = null, adc = null) {
    let bytes = null;
    if (envelope?.schema === 1 && /^[0-9a-f]{46}$/i.test(envelope.data_hex || ''))
        bytes = envelope.data_hex.match(/../g).map(x => parseInt(x, 16));
    if (bytes && (bytes[0] !== 1 || bytes[1] === 255 || bytes[3] === 255 || bytes[13] === 255))
        bytes = null;
    const rows = [], active = [];
    const add = (label, value, format = 'string') => rows.push({label, value, format, type: 'battery'});
    for (let i = 0; i < 2; i++) {
        const prefix = `USB-C ${i + 1}`;
        const o = 3 + 10 * i;
        let valid = false, mv = 0, ma = 0, watts = 0;
        if (bytes && (bytes[1] & 1) && (bytes[o] & 64)) {
            mv = bytes[o + 2] + 256 * bytes[o + 3];
            ma = bytes[o + 4] + 256 * bytes[o + 5];
            const pdo = (bytes[o + 6] + bytes[o + 7] * 256 + bytes[o + 8] * 65536 + bytes[o + 9] * 16777216) >>> 0;
            watts = mv * ma / 1000000;
            valid = (pdo >>> 30) === 0 && mv >= 4500 && mv <= 50000 && ma >= 50 && ma <= 5000 &&
                mv === ((pdo >>> 10) & 1023) * 50 && ma === (pdo & 1023) * 10 &&
                bytes[o + 1] > 0 && bytes[o + 1] < 255 && Math.abs(bytes[o + 1] - watts) <= 1;
        }
        const state = !bytes ? 'Unavailable' : valid ? 'Connected' :
            !(bytes[1] & 1) || !(bytes[o] & 64) ? 'No active contract' : 'Unavailable';
        if (valid) active.push(i + 1);
        add(`${prefix} State`, state);
        add(`${prefix} Contract Voltage`, valid ? mv : 'Unavailable', valid ? 'in' : 'string');
        add(`${prefix} Current Limit`, valid ? ma : 'Unavailable', valid ? 'amp' : 'string');
        add(`${prefix} Power Limit`, valid ? watts * 1000000 : 'Unavailable', valid ? 'watt' : 'string');
        add(`${prefix} Input Voltage`, 'Unavailable');
        add(`${prefix} Input Current`, 'Unavailable (no ADC)');
        add(`${prefix} Input Power`, 'Unavailable (no ADC)');
    }
    const w = adc?.words;
    const validADC = adc?.schema === 1 && Array.isArray(w) && w.length === 10 &&
        w.every(x => Number.isInteger(x) && x >= 0 && x <= 65535) && w[0] === 73 && w[1] === 14 &&
        (w[2] & 1) && (w[9] & 1) && !(w[3] & 2048) &&
        [w[4], w[8]].every(x => (x & 16384) && ((x >> 5) & 7) >= 1 && ((x >> 5) & 7) <= 3) &&
        w[6] <= 255 && !(w[5] & ~16320) && !(w[7] & ~16320) && Math.abs((w[5] >> 6) - (w[7] >> 6)) <= 1 &&
        adc.input_millivolts === (w[7] >> 6) * 96 && adc.input_millivolts >= 4000 && adc.input_millivolts <= 24000 &&
        adc.input_microamps === w[6] * 44400 &&
        adc.input_microwatts === Math.floor((adc.input_millivolts * adc.input_microamps + 500) / 1000) &&
        adc.input_shunt_milliohms === 10 && adc.current_resolution_microamps === 44400 &&
        adc.voltage_resolution_millivolts === 96 && adc.maximum_cache_seconds === 2 &&
        Number.isInteger(adc.age_milliseconds) && adc.age_milliseconds >= 0 && adc.age_milliseconds <= 2000;
    if (active.length === 1 && validADC) {
        const prefix = `USB-C ${active[0]}`;
        for (const [suffix, value, format] of [
            ['Input Voltage', adc.input_millivolts, 'in'],
            ['Input Current', adc.input_microamps / 1000, 'amp'],
            ['Input Power', adc.input_microwatts, 'watt']]) {
            const row = rows.find(x => x.label === `${prefix} ${suffix}`);
            Object.assign(row, {value, format});
        }
    }
    const validPower = typeof powerMicrowatts === 'number' && Number.isFinite(powerMicrowatts) &&
        powerMicrowatts > 0 && powerMicrowatts <= 1000000000;
    add('Platform Power', validPower ? powerMicrowatts : 'Unavailable', validPower ? 'watt' : 'string');
    return rows;
}
