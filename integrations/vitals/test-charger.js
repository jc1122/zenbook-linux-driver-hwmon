// SPDX-License-Identifier: GPL-2.0-only
import assert from 'node:assert/strict';
import {chargerRows} from './charger.js';
const active = [69, 65, 32, 78, 178, 12, 69, 65, 6, 0];
const packet = [1, 3, 65, ...active, ...Array(10).fill(0)];
const wrap = bytes => ({schema: 1, data_hex: bytes.map(x => x.toString(16).padStart(2, '0')).join('')});
const value = (rows, name) => rows.find(x => x.label === name)?.value;
let rows = chargerRows(wrap(packet), 28500000);
assert.equal(value(rows, 'USB-C 1 Contract Voltage'), 20000);
assert.equal(value(rows, 'USB-C 1 Current Limit'), 3250);
assert.equal(value(rows, 'USB-C 1 Power Limit'), 65000000);
assert.equal(value(rows, 'Platform Power'), 28500000);
assert.equal(value(rows, 'USB-C 1 Input Current'), 'Unavailable (no ADC)');
assert.equal(value(rows, 'USB-C 1 Input Power'), 'Unavailable (no ADC)');
assert.equal(value(rows, 'USB-C 2 Power Limit'), 'Unavailable');
let unplugged = [...packet]; unplugged[1] = 2;
rows = chargerRows(wrap(unplugged), null);
assert.equal(value(rows, 'USB-C 1 Power Limit'), 'Unavailable');
assert.equal(value(rows, 'Platform Power'), 'Unavailable');
rows = chargerRows(wrap([1, 3, 65, ...Array(10).fill(0), ...active]), 20000000);
assert.equal(value(rows, 'USB-C 1 Power Limit'), 'Unavailable');
assert.equal(value(rows, 'USB-C 2 Power Limit'), 65000000);
for (const bad of [null, {schema: 2, data_hex: wrap(packet).data_hex}, {schema: 1, data_hex: '00'}, wrap([...packet.slice(0, 3), 255, ...packet.slice(4)])]) {
    assert.equal(value(chargerRows(bad, -1), 'USB-C 1 Power Limit'), 'Unavailable');
}
for (const bad of [NaN, Infinity, '1000000', 0, -1, 1000000001])
    assert.equal(value(chargerRows(null, bad), 'Platform Power'), 'Unavailable');
let inconsistent = [...packet]; inconsistent[5] ^= 16;
assert.equal(value(chargerRows(wrap(inconsistent)), 'USB-C 1 Power Limit'), 'Unavailable');
console.log('Vitals charger decoding: limits, measured power, unavailable states and unplug transitions passed.');
const adc = {schema: 1, words: [73,14,16387,45100,19524,13056,40,13056,19524,16387],
    input_millivolts: 19584, input_microamps: 1776000, input_microwatts: 34781184,
    current_resolution_microamps: 44400, voltage_resolution_millivolts: 96,
    input_shunt_milliohms: 10, maximum_cache_seconds: 2, age_milliseconds: 0};
rows = chargerRows(wrap(packet), 28500000, adc);
assert.equal(value(rows, 'USB-C 1 Input Voltage'), 19584);
assert.equal(value(rows, 'USB-C 1 Input Current'), 1776);
assert.equal(value(rows, 'USB-C 1 Input Power'), 34781184);
for (const bad of [{...adc, age_milliseconds: 2001}, {...adc, input_shunt_milliohms: 20},
    {...adc, input_microwatts: 65000000}, {...adc, words: [0,...adc.words.slice(1)]}])
    assert.equal(value(chargerRows(wrap(packet), null, bad), 'USB-C 1 Input Power'), 'Unavailable (no ADC)');
assert.equal(value(chargerRows(wrap(unplugged), null, adc), 'USB-C 1 Input Power'), 'Unavailable (no ADC)');
assert.equal(value(chargerRows(wrap([1,3,65,...active,...active]), null, adc), 'USB-C 1 Input Power'), 'Unavailable (no ADC)');
rows=chargerRows(wrap([1,3,65,...Array(10).fill(0),...active]), null, adc);
assert.equal(value(rows,'USB-C 2 Input Power'),34781184);
console.log('Vitals direct ADC: units, freshness, unplug and single-port attribution passed.');
