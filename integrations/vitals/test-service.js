// SPDX-License-Identifier: GPL-2.0-only
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {SERVICE, parseMetrics, metricsSource, dbusMetricsCall, serviceInputs} from './service.js';
import {chargerRows} from './charger.js';
import {chargerExtraRows, pdSourceRows} from './metrics.js';
import {gaugeRows, gaugeExtraRows, sbsRows, lifetimeRows, pdAlertRows} from './battery.js';
import {frequencyRows, packagePowerRows} from './frequency.js';

const ROOT = fileURLToPath(new URL('../..', import.meta.url));
const value = (rows, label) => rows.find(r => r.label === label)?.value;
const tick = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

// Envelope parsing: only an ok service reply with a schema-1 report is used.
assert.deepEqual(parseMetrics('{"ok":true,"result":{"schema":1}}'), {schema: 1});
for (const bad of [null, 5, '', '{', '{"ok":false,"error":{"errno":13}}', '{"ok":true,"result":[]}',
    '{"ok":true,"result":{"schema":2}}', '{"ok":"true","result":{"schema":1}}', ' '.repeat(4 * 1024 * 1024 + 1)])
    assert.equal(parseMetrics(bad), null);

// One request per refresh: overlapping and immediately repeated queries share it.
{
    let calls = 0, clock = 0, release;
    const source = metricsSource(() => { calls++; return new Promise(r => { release = r; }); }, {now: () => clock});
    const a = source.get(), b = source.get();
    assert.equal(a, b); await tick(); assert.equal(calls, 1);
    release('{"ok":true,"result":{"schema":1,"n":1}}');
    assert.equal((await a).n, 1); assert.equal((await source.get()).n, 1); assert.equal(calls, 1);
    clock = 999; await source.get(); assert.equal(calls, 1);
    clock = 1000; const c = source.get(); await tick(); assert.equal(calls, 2);
    release('{"ok":false,"error":{"errno":13,"message":"denied"}}'); assert.equal(await c, null);
    clock = 1500; assert.equal(await source.get(), null); assert.equal(calls, 2);  // failures are not retried early
    clock = 400; const d = source.get(); await tick(); assert.equal(calls, 3);    // clock moved back: refresh
    release('{"ok":true,"result":{"schema":1}}'); await d;
    const failing = metricsSource(() => { throw new Error('no bus'); });
    assert.equal(await failing.get(), null);
    const rejecting = metricsSource(() => Promise.reject(new Error('ServiceUnknown')));
    assert.equal(await rejecting.get(), null);
}

// Fake system bus: exact destination, no interactive authorization, reply unpacking.
{
    const seen = [];
    const fake = reply => ({
        Gio: {DBusCallFlags: {NONE: 0, ALLOW_INTERACTIVE_AUTHORIZATION: 2}, DBus: {get system() {
            return {call: (...args) => { seen.push(args); const done = args[9]; done(fakeConnection, 'token'); }};
        }}},
        GLib: {VariantType: class { constructor(signature) { this.signature = signature; } }}
    });
    let reply = () => ({deepUnpack: () => ['{"ok":true,"result":{"schema":1}}']});
    const fakeConnection = {call_finish: token => { assert.equal(token, 'token'); return reply(); }};
    const {Gio, GLib} = fake();
    assert.equal(await dbusMetricsCall(Gio, GLib)(), '{"ok":true,"result":{"schema":1}}');
    const [name, path, iface, method, params, type, flags, timeout, cancellable] = seen[0];
    assert.deepEqual([name, path, iface, method, params, type.signature, flags, timeout, cancellable],
        [SERVICE.name, SERVICE.path, SERVICE.interface, 'VitalsMetrics', null, '(s)', 0, SERVICE.timeoutMs, null]);
    reply = () => { throw new Error('org.freedesktop.DBus.Error.AccessDenied'); };
    await assert.rejects(dbusMetricsCall(Gio, GLib)());
    assert.equal(await metricsSource(dbusMetricsCall(Gio, GLib)).get(), null);
}

// Equivalence: frames decoded by the service's own Python decoders must give
// the same rows as the direct sysfs frames gave before 0.79.
const env = seconds => ({schema: 1, device_type_hex: '5645', firmware_hex: '45560234004002000000000000', age_milliseconds: 0, maximum_cache_seconds: seconds});
const hex = b => Buffer.from(b).toString('hex');
function frames(variant) {
    const a = Buffer.alloc(20), t = Buffer.alloc(14), l = Buffer.alloc(31);
    [[0, 4100], [2, 4200], [8, 8300], [10, variant.pack ?? 8400]].forEach(([o, v]) => a.writeUInt16LE(v, o));
    a.writeInt16LE(-1200, 12); a.writeInt16LE(variant.cell2 ?? 350, 14);
    [3100, 3050, 3060, 4700, 4700, 3050, 3060].forEach((v, i) => t.writeUInt16LE(v, 2 * i));
    [[0, 4300], [2, 4250], [8, 3000], [10, 3100], [12, 32767], [14, 32767], [16, 250], [18, 6500]].forEach(([o, v]) => l.writeUInt16LE(v, o));
    [[20, -9000], [22, -5000], [24, -4000]].forEach(([o, v]) => l.writeInt16LE(v, o));
    [[26, 50], [27, 10], [28, 2], [29, 55], [30, 12]].forEach(([o, v]) => { l[o] = v; });
    const e = Buffer.alloc(31); e.writeUInt16LE(210, 16); e.writeUInt16LE(292, 18); e.writeUInt16LE(4, 28); e[30] = 244;
    const life = {...env(60), age_milliseconds: 1234, block1_prefix_hex: hex(l), block2_prefix_hex: '04000400', block3_prefix_hex: '64000200',
        block4_prefix_hex: hex(Buffer.alloc(31)), block5_prefix_hex: hex(e)};
    if (variant.complete) {
        const block3 = Buffer.alloc(26); [100, 2, 3, 90, 0, 0, 0, 4].forEach((n, i) => block3.writeUInt16LE(n, 2 * i));
        life.complete_blocks = true;
        [32, 8, 26, 32, 32].forEach((size, i) => {
            const data = i === 2 ? block3 : Buffer.alloc(size); Buffer.from(life[`block${i + 1}_prefix_hex`], 'hex').copy(data);
            if (i === 0) data[31] = 48;
            if (i === 1) { data[4] = 3; data[5] = 255; }
            life[`block${i + 1}_hex`] = hex(data);
        });
    }
    const aFull = Buffer.alloc(32), tFull = Buffer.alloc(24); a.copy(aFull); t.copy(tFull);
    aFull.writeInt16LE(-492, 20); aFull.writeInt16LE(variant.cellPower ?? 147, 22); aFull.writeInt16LE(variant.total ?? -345, 28); aFull.writeInt16LE(-700, 30);
    tFull.writeUInt16LE(3000, 14); [4110, 4190, 0, 0].forEach((v, i) => tFull.writeUInt16LE(v, 16 + 2 * i));
    const sbsWords = [0x31, variant.energy ? 0xe001 : 0x6001, 3000, 8300, 64536, 65535, variant.maxRequest ? 65535 : 3000, 8700, 1, 80, 60, 6000, 65535, 200, 9000, 7700];
    const contract = [1, 3, 65, 69, 65, 32, 78, 178, 12, 69, 65, 6, 0, ...Array(10).fill(0)];
    const identity = {schema: 1, maximum_cache_seconds: 5, age_milliseconds: 10, contract_hex: hex(contract), ports: [
        {connector: 1, sop_hex: hex(Buffer.alloc(25)), cable_hex: hex(Buffer.alloc(25)), alert_hex: variant.alert ?? '00000000'},
        {connector: 2, sop_hex: hex(Buffer.alloc(25)), cable_hex: hex(Buffer.alloc(25)), alert_hex: '00000000'}]};
    const adcWords = variant.adcOff ? [73, 14, 16386, 45100, 19524, 13056, 40, 13056, 19524, 16387] : [73, 14, 16387, 45100, 19524, 13056, 40, 13056, 19524, 16387];
    const adc = {schema: 1, words: adcWords, input_millivolts: 19584, input_microamps: 1776000, input_microwatts: 34781184,
        current_resolution_microamps: 44400, voltage_resolution_millivolts: 96, input_shunt_milliohms: 10, maximum_cache_seconds: 2, age_milliseconds: 7};
    const metricsWords = [73, 14, 16387, 45100, 19524, 220, 8320, 10, 20, 6016, 0x8069, variant.thermal ? 64 : 0, 19524, 16387];
    const metrics = {schema: 1, words: metricsWords, die_millicelsius: 51511, vbat_pin_millivolts: 8320, system_millivolts: 9024,
        discharge_microamps: 888000, charge_microamps: 888000, valid_mask: 31, battery_shunt_milliohms: 5, maximum_cache_seconds: 2, age_milliseconds: 3};
    if (variant.chargerOff) { metrics.words = [...metricsWords]; metrics.words[2] = 0; metrics.words[13] = 0;
        for (const k of ['die_millicelsius', 'vbat_pin_millivolts', 'system_millivolts', 'discharge_microamps', 'charge_microamps']) delete metrics[k];
        metrics.valid_mask = 0; }
    const pkg = {schema: 1, cpu: 0, energy_before: 4294967280, energy_after: 240, energy_exponent: 14, elapsed_microseconds: 200000,
        power_microwatts: 78125, maximum_cache_seconds: 1, age_microseconds: 5};
    return {contract: {schema: 1, data_hex: hex(contract)}, power: variant.power ?? 28512345, adc, metrics, pkg, identity,
        gauge: {...env(5), age_milliseconds: 4999, da1_hex: hex(a), da2_hex: hex(t)},
        extra: {...env(15), age_milliseconds: 15, da1_hex: hex(aFull), da2_hex: hex(tFull)},
        sbs: {...env(30), transport: 'native_smbus_read_word', age_milliseconds: 29, words: sbsWords}, life};
}
const DECODE = `
import json,sys
sys.path.insert(0,sys.argv[1])
import battery_diagnostics,battery_extra,battery_sbs,charger_adc,charger_metrics,pd_identity,package_power
f=json.load(sys.stdin)
def guard(fn,*a):
    try:return fn(*a)
    except Exception as e:return {'available':False,'error':str(e)}
print(json.dumps({'schema':1,'cpu_package_power':guard(package_power.decode,f['pkg']),
 'platform_power':{'available':True,'watts':f['power']/1000000,'measurement':True},
 'charger_input':guard(charger_adc.decode,f['adc']),'charger':guard(charger_metrics.decode,f['metrics']),
 'battery_gauge':guard(battery_diagnostics.decode_metrics,f['gauge']),'battery_lifetime':guard(battery_diagnostics.decode_lifetime,f['life']),
 'battery_gauge_extra':guard(battery_extra.decode,f['extra']),'battery_sbs':guard(battery_sbs.decode,f['sbs']),
 'usb_pd_identity':guard(pd_identity.decode,f['identity'])}))`;
function decode(f) {
    const run = spawnSync('python3', ['-I', '-B', '-c', DECODE, ROOT], {input: JSON.stringify(f), encoding: 'utf8'});
    assert.equal(run.status, 0, run.stderr);
    return JSON.parse(run.stdout);
}
const direct = f => [...chargerRows(f.contract, f.power, f.adc), ...chargerExtraRows(f.metrics), ...gaugeRows(f.gauge),
    ...gaugeExtraRows(f.extra), ...sbsRows(f.sbs), ...lifetimeRows(f.life), ...pdAlertRows(f.identity, chargerRows), ...packagePowerRows(f.pkg)];
const viaService = (report, contract) => {
    const i = serviceInputs(report, contract, chargerRows);
    return [...chargerRows(contract, i.platformPower, i.chargerAdc), ...chargerExtraRows(i.chargerMetrics), ...gaugeRows(i.gauge),
        ...gaugeExtraRows(i.gaugeExtra), ...sbsRows(i.sbs), ...lifetimeRows(i.lifetime), ...pdAlertRows(i.pdIdentity, chargerRows), ...packagePowerRows(i.packagePower)];
};
const variants = [{}, {complete: true}, {energy: true, maxRequest: true}, {alert: '00002102'}, {thermal: true, chargerOff: true},
    {cell2: -20, total: 32767, cellPower: -100}, {pack: 3000}, {power: 1}];
let compared = 0;
for (const variant of variants) {
    const f = frames(variant), report = decode(f), rows = viaService(report, f.contract);
    for (const key of ['cpu_package_power', 'charger_input', 'charger', 'battery_gauge', 'battery_lifetime', 'battery_gauge_extra', 'battery_sbs', 'usb_pd_identity'])
        assert.equal(report[key].available, true, `${key} ${JSON.stringify(variant)} ${report[key].error}`);
    assert.deepEqual(rows, direct(f), JSON.stringify(variant));
    assert(rows.filter(r => typeof r.value === 'number').length >= 30, String(rows.filter(r => typeof r.value === 'number').length));
    compared += rows.length;
}
// Python-rejected frames and a missing service give the same full set of rows, all Unavailable where restricted.
{
    const f = frames({adcOff: true}), report = decode(f);
    assert.equal(report.charger_input.available, false);
    assert.equal(value(viaService(report, f.contract), 'USB-C 1 Input Power'), 'Unavailable (no ADC)');
    const none = viaService(null, f.contract), restricted = none.filter(r => !/^USB-C [12] (State|Contract Voltage|Current Limit|Power Limit)$/.test(r.label));
    assert.equal(none.length, direct(f).length);
    assert(restricted.every(r => typeof r.value === 'string' && /^(Unavailable|No active contract)/.test(r.value)), JSON.stringify(restricted.filter(r => typeof r.value !== 'string')));
    assert.equal(value(none, 'USB-C 1 Power Limit'), 65000000);  // world-readable contract still shown
}
// A contract change between the pd_contract read and the service identity frame drops the alert rows.
{
    const f = frames({}), report = decode(f);
    const unplugged = {schema: 1, data_hex: hex([1, 2, 65, 69, 65, 32, 78, 178, 12, 69, 65, 6, 0, ...Array(10).fill(0)])};
    assert.equal(serviceInputs(report, unplugged, chargerRows).pdIdentity, null);
    assert.equal(serviceInputs(report, f.contract).pdIdentity, null);
}
// Malformed decoded sections never pass through as values.
{
    const f = frames({}), report = decode(f);
    const broken = structuredClone(report);
    broken.charger_input.raw_words[6] = 41; broken.charger.raw_registers['0x82'] = -1; broken.battery_sbs.voltage_volts = 'x';
    broken.battery_gauge.cells = [broken.battery_gauge.cells[0]]; broken.battery_gauge_extra.cells[1].power_raw_centiwatts = 70000;
    broken.battery_lifetime.complete_blocks = 'yes'; broken.cpu_package_power.available = false; broken.platform_power.watts = NaN;
    const i = serviceInputs(broken, f.contract, chargerRows);
    for (const key of ['chargerAdc', 'chargerMetrics', 'sbs', 'gauge', 'gaugeExtra', 'lifetime', 'packagePower', 'platformPower'])
        assert.equal(i[key], null, key);
}
console.log(`Vitals service adapter: ${compared} rows equal to direct frames through the service decoders; bus, cache and failure states passed.`);

// Managed sensors.js blocks: one shared service request per refresh, no restricted file reads.
const chargerMethod = readFileSync(new URL('./charger-method.txt', import.meta.url), 'utf8');
const frequencyMethod = readFileSync(new URL('./frequency-method.txt', import.meta.url), 'utf8');
for (const name of ['power1_input', 'power3_input', 'charger_adc', 'charger_metrics', 'battery_gauge_metrics', 'battery_lifetime',
    'pd_identity', 'battery_gauge_extra', 'battery_sbs', 'cpu_package_power', 'battery_identity', 'sudo'])
    assert(!chargerMethod.includes(name) && !frequencyMethod.includes(name), name);
async function wire(mode) {
    const f = frames({}), reportText = JSON.stringify({ok: true, result: decode(f)});
    const reads = [], emitted = [];
    let calls = 0;
    class File {
        constructor(path) { this.path = path; }
        async list() { return this.path === '/sys/devices/system/cpu' ? [] : ['hwmon3']; }
        async read() {
            reads.push(this.path.replace(/^.*\//, ''));
            if (this.path.endsWith('/name')) return 'zenbook_ec\n';
            if (this.path.endsWith('/pd_contract')) return JSON.stringify(f.contract);
            if (this.path.endsWith('/pd_source_caps')) return '{}';
            if (this.path.endsWith('/cpu_reported_frequency')) return '{}';
            throw new Error('unexpected ' + this.path);
        }
    }
    const services = {metricsSource, dbusMetricsCall: () => () => {
        calls++;
        if (mode === 'unavailable') return Promise.reject(new Error('org.freedesktop.DBus.Error.ServiceUnknown'));
        return Promise.resolve(reportText);
    }, serviceInputs};
    const Handler = Function('FileModule', 'Gio', 'GLib', 'metricsSource', 'dbusMetricsCall', 'serviceInputs', 'chargerRows', 'chargerExtraRows', 'pdSourceRows',
        'gaugeRows', 'gaugeExtraRows', 'sbsRows', 'lifetimeRows', 'pdAlertRows', 'frequencyRows', 'packagePowerRows', 'CPU_FIELDS', 'cpuRows', 'ssdRows',
        `return class {${chargerMethod}${frequencyMethod}}`)({File}, {}, {}, services.metricsSource, services.dbusMetricsCall, services.serviceInputs,
        chargerRows, chargerExtraRows, pdSourceRows, gaugeRows, gaugeExtraRows, sbsRows, lifetimeRows, pdAlertRows, frequencyRows, packagePowerRows, [], () => [], () => []);
    const handler = new Handler();
    handler._returnValue = (_, label, value) => emitted.push({label, value});
    handler._queryZenbookCharger(() => {}); handler._queryZenbookFrequency(() => {}); handler._queryZenbookCharger(() => {});
    if (mode === 'destroyed') handler._zenbookChargerDestroyed = true;
    for (let i = 0; i < 200 && (handler._zenbookChargerPending || handler._zenbookFrequencyPending); i++) await Promise.resolve();
    assert.equal(handler._zenbookChargerPending, false); assert.equal(handler._zenbookFrequencyPending, false);
    assert.equal(calls, 1, 'one VitalsMetrics() request per refresh');
    assert(reads.every(name => ['name', 'pd_contract', 'pd_source_caps', 'cpu_reported_frequency'].includes(name)), reads.join());
    if (mode === 'destroyed') { assert.equal(emitted.length, 0); return; }
    const expected = mode === 'normal' ? direct(f).filter(r => r.label !== 'CPU Package Power (RAPL)') : null;
    const battery = emitted.filter(r => r.label !== 'CPU Package Power (RAPL)' && !/^CPU0 /.test(r.label) && !/PD Source|Source Profile|PDO/.test(r.label));
    if (expected) for (const row of expected) assert.equal(value(battery, row.label), row.value, row.label);
    else {
        assert.equal(value(emitted, 'Platform Power'), 'Unavailable');
        assert.equal(value(emitted, 'Battery SBS Pack Voltage'), 'Unavailable');
        assert.equal(value(emitted, 'Battery Recorded Shutdowns'), 'Unavailable');
        assert.equal(value(emitted, 'USB-C 1 Last Received PD Alert'), 'Unavailable');
        assert.equal(value(emitted, 'USB-C 1 Power Limit'), 65000000);
    }
    assert.equal(value(emitted, 'CPU Package Power (RAPL)'), mode === 'normal' ? 78125 : 'Unavailable');
}
for (const mode of ['normal', 'unavailable', 'destroyed']) await wire(mode);
console.log('Vitals service wiring: shared request, world-readable files only, unavailable service and destruction passed.');
