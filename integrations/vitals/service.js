/* SPDX-License-Identifier: MIT
 * Restricted Zenbook readings come from the root service org.zenbook.Hardware1.
 * Since driver 0.79 the attributes that start EC broker/SMBus sessions or
 * sample RAPL/PSYS energy are root-only (0400); the service reads them, and
 * VitalsMetrics() returns the decoded Vitals sections (polkit `read`, active session).
 *
 * The service has already decoded and validated each sysfs frame. The adapters
 * below re-express those decoded fields in the frame shapes the existing row
 * builders accept, so the builders' own consistency checks still run. Any
 * missing, failed or inconsistent section becomes null, which every builder
 * shows as Unavailable. No subprocess, elevation or interactive prompt is used.
 */
export const SERVICE = {name: 'org.zenbook.Hardware1', path: '/org/zenbook/Hardware1',
    interface: 'org.zenbook.Hardware1', method: 'VitalsMetrics', timeoutMs: 20000};
const MAX_REPLY = 4 * 1024 * 1024;

export function parseMetrics(text) {
    if (typeof text !== 'string' || text.length > MAX_REPLY) return null;
    try {
        const envelope = JSON.parse(text);
        const result = envelope?.ok === true ? envelope.result : null;
        return result && typeof result === 'object' && !Array.isArray(result) && result.schema === 1 ? result : null;
    } catch (_) { return null; }
}

/* call() resolves to the VitalsMetrics() JSON string. Battery and Processor queries of
 * one Vitals refresh share a single request (in flight, or answered less than
 * maxAgeMs ago); failures are remembered for the same window. No own timer. */
export function metricsSource(call, {now = () => Date.now(), maxAgeMs = 1000} = {}) {
    let pending = null, last = null, at = null;
    return {
        get() {
            if (pending) return pending;
            if (at !== null && now() - at >= 0 && now() - at < maxAgeMs) return Promise.resolve(last);
            pending = Promise.resolve().then(call).then(parseMetrics, () => null).then(report => {
                last = report; at = now(); pending = null;
                return report;
            });
            return pending;
        }
    };
}

/* System-bus VitalsMetrics() call without ALLOW_INTERACTIVE_AUTHORIZATION: a polkit
 * denial or a missing service rejects, and the rows become Unavailable. */
export function dbusMetricsCall(Gio, GLib, service = SERVICE) {
    return () => new Promise((resolve, reject) => {
        Gio.DBus.system.call(service.name, service.path, service.interface, service.method, null,
            new GLib.VariantType('(s)'), Gio.DBusCallFlags.NONE, service.timeoutMs, null, (connection, result) => {
                try {
                    const [text] = connection.call_finish(result).deepUnpack();
                    resolve(text);
                } catch (error) { reject(error); }
            });
    });
}

const integer = (x, lo, hi) => Number.isSafeInteger(x) && x >= lo && x <= hi;
const scaled = (x, scale) => typeof x === 'number' && Number.isFinite(x) ? Math.round(x * scale) : null;
const ok = section => section && typeof section === 'object' && section.available === true ? section : null;
function frame(words, bytes) {
    const out = new Array(bytes).fill(0);
    for (const [offset, value] of words) {
        if (!integer(value, -32768, 65535)) return null;
        const u = value & 65535;
        out[offset] = u & 255; out[offset + 1] = u >> 8;
    }
    return out.map(b => b.toString(16).padStart(2, '0')).join('');
}
const cell = (section, n) => Array.isArray(section?.cells) ? section.cells.find(c => c?.cell === n) : undefined;
// The service decoder accepts only this gauge device type and firmware layout
// prefix (battery_diagnostics.validate); the builders check nothing beyond it.
const gaugeFrame = (section, seconds) => integer(section.age_milliseconds, 0, 1000 * seconds) ? {schema: 1,
    device_type_hex: '5645', firmware_hex: '45560234004002000000000000',
    maximum_cache_seconds: section.maximum_cache_seconds, age_milliseconds: section.age_milliseconds} : null;
const kelvinCode = celsius => celsius === null ? 0 : scaled(celsius * 10 + 2731.5, 1);

export function packagePower(report) {
    const sample = ok(report?.cpu_package_power)?.energy_sample;
    return sample && typeof sample === 'object' ? sample : null;
}

export function platformPower(report) {
    const value = scaled(ok(report?.platform_power)?.watts, 1000000);
    return value !== null && value > 0 ? value : null;
}

export function chargerAdc(report) {
    const s = ok(report?.charger_input), w = s?.raw_words;
    if (!Array.isArray(w) || w.length !== 10 || !w.every(x => integer(x, 0, 65535))) return null;
    const mv = (w[7] >> 6) * 96, ua = w[6] * 44400;
    if (scaled(s.voltage_volts, 1000) !== mv || scaled(s.current_amperes, 1000000) !== ua) return null;
    return {schema: 1, words: [...w], input_millivolts: mv, input_microamps: ua,
        input_microwatts: Math.floor((mv * ua + 500) / 1000), current_resolution_microamps: 44400,
        voltage_resolution_millivolts: 96, input_shunt_milliohms: s.input_shunt_milliohms,
        maximum_cache_seconds: s.maximum_cache_seconds, age_milliseconds: s.age_milliseconds};
}

// raw_registers is keyed by register, so the second 0x4d/0x4c reads (words 12
// and 13) also stand for words 4 and 2. The decoded valid fields still gate
// every converted value through valid_mask.
const CHARGER_REGISTERS = [0xfe, 0xff, 0x4c, 0x4e, 0x4d, 0x82, 0x81, 0x84, 0x85, 0x86, 0x3a, 0x91, 0x4d, 0x4c];
export function chargerMetrics(report) {
    const s = ok(report?.charger), registers = s?.raw_registers;
    if (!registers || typeof registers !== 'object') return null;
    const words = CHARGER_REGISTERS.map(r => registers['0x' + r.toString(16).padStart(2, '0')]);
    if (!words.every(x => integer(x, 0, 65535))) return null;
    const d = {schema: 1, words, battery_shunt_milliohms: s.battery_shunt_milliohms,
        maximum_cache_seconds: s.maximum_cache_seconds, age_milliseconds: s.age_milliseconds};
    let mask = 0;
    for (const [bit, key, field, scale] of [[1, 'die_millicelsius', 'die_temperature_celsius', 1000],
        [2, 'vbat_pin_millivolts', 'vbat_pin_voltage_volts', 1000], [4, 'system_millivolts', 'system_voltage_volts', 1000],
        [8, 'discharge_microamps', 'battery_discharge_current_amperes', 1000000],
        [16, 'charge_microamps', 'battery_charge_current_amperes', 1000000]]) {
        if (s[field] === null) continue;
        const value = scaled(s[field], scale);
        if (value === null) return null;
        mask |= bit; d[key] = value;
    }
    d.valid_mask = mask;
    return d;
}

export function gauge(report) {
    const s = ok(report?.battery_gauge), c1 = cell(s, 1), c2 = cell(s, 2);
    const base = s && gaugeFrame(s, 5), t = s?.temperatures_celsius;
    if (!base || !c1 || !c2 || !t || typeof t !== 'object') return null;
    const pin = v => v === null ? 0 : scaled(v, 1000);
    const da1 = frame([[0, scaled(c1.voltage_volts, 1000)], [2, scaled(c2.voltage_volts, 1000)],
        [8, pin(s.bat_pin_voltage_volts)], [10, pin(s.pack_pin_voltage_volts)],
        [12, scaled(c1.current_amperes, 1000)], [14, scaled(c2.current_amperes, 1000)]], 20);
    const da2 = frame(['internal', 'ts1', 'ts2', 'ts3', 'ts4', 'cell', 'fet'].map((k, i) => [2 * i, kelvinCode(t[k] ?? null)]), 14);
    return da1 && da2 ? {...base, da1_hex: da1, da2_hex: da2} : null;
}

export function gaugeExtra(report) {
    const s = ok(report?.battery_gauge_extra), c1 = cell(s, 1), c2 = cell(s, 2);
    const base = s && gaugeFrame(s, 15);
    if (!base || !c1 || !c2 || (s.gauging_temperature_celsius !== null && typeof s.gauging_temperature_celsius !== 'number')) return null;
    const da1 = frame([[0, scaled(c1.voltage_volts, 1000)], [2, scaled(c2.voltage_volts, 1000)],
        [12, scaled(c1.current_amperes, 1000)], [14, scaled(c2.current_amperes, 1000)],
        [20, c1.power_raw_centiwatts], [22, c2.power_raw_centiwatts],
        [28, s.gauge_power_raw_centiwatts], [30, s.gauge_average_power_raw_centiwatts]], 32);
    const da2 = frame([[14, kelvinCode(s.gauging_temperature_celsius)]], 24);
    return da1 && da2 ? {...base, da1_hex: da1, da2_hex: da2} : null;
}

export function sbs(report) {
    const s = ok(report?.battery_sbs), c = s?.capacities;
    const base = s && gaugeFrame(s, 30);
    if (!base || !c || typeof c !== 'object') return null;
    const energy = s.capacity_mode === 'energy';
    const capacity = key => {
        const value = c[key + (energy ? '_watt_hours' : '_milliamp_hours')];
        return value === null ? 65535 : scaled(value, energy ? 100 : 1);
    };
    const requested = (maximum, value, scale) => maximum === true ? 65535 : scaled(value, scale);
    const words = [s.specification_raw, s.battery_mode_raw, scaled(s.temperature_celsius * 10 + 2731.5, 1),
        scaled(s.voltage_volts, 1000), scaled(s.current_amperes, 1000), scaled(s.average_current_amperes, 1000),
        requested(s.requested_charging_current_is_maximum, s.requested_charging_current_amperes, 1000),
        requested(s.requested_charging_voltage_is_maximum, s.requested_charging_voltage_volts, 1000),
        s.state_of_charge_maximum_error_percent, s.relative_state_of_charge_percent, s.absolute_state_of_charge_percent,
        capacity('remaining'), capacity('full'), s.cycle_count, capacity('design'), scaled(s.design_voltage_volts, 1000)];
    if (!words.every(x => integer(x, -32768, 65535))) return null;
    return {...base, transport: s.transport, words: words.map(x => x & 65535)};
}

export function lifetime(report) {
    const s = ok(report?.battery_lifetime), prefixes = s?.raw_prefixes;
    const base = s && gaugeFrame(s, 60);
    if (!base || !prefixes || typeof prefixes !== 'object' || typeof s.complete_blocks !== 'boolean') return null;
    const d = {...base, complete_blocks: s.complete_blocks};
    for (const [i, value] of Object.entries(prefixes)) if (/^[1-5]$/.test(i)) d[`block${i}_prefix_hex`] = value;
    if (s.complete_blocks) {
        if (!s.raw_blocks || typeof s.raw_blocks !== 'object') return null;
        for (const [i, value] of Object.entries(s.raw_blocks)) if (/^[1-5]$/.test(i)) d[`block${i}_hex`] = value;
    }
    return d;
}

/* The received alert is paired with the separately read (world-readable)
 * pd_contract frame; a contract change between the two reads drops the rows. */
export function pdIdentity(report, contract = null, contractDecoder = null) {
    const s = ok(report?.usb_pd_identity);
    if (!s || !Array.isArray(s.ports) || s.ports.length !== 2 || typeof contractDecoder !== 'function' ||
        !/^[0-9a-f]{46}$/i.test(contract?.data_hex || '')) return null;
    const states = contractDecoder({schema: 1, data_hex: contract.data_hex});
    const ports = [];
    for (const [i, port] of s.ports.entries()) {
        if (port?.connector !== i + 1 || typeof port.active_contract !== 'boolean') return null;
        if ((states.find(r => r.label === `USB-C ${i + 1} State`)?.value === 'Connected') !== port.active_contract) return null;
        const alert = port.received_alert, record = {connector: i + 1};
        if (alert?.available === true && integer(alert.raw_ado, 0, 4294967295))
            record.alert_hex = [0, 8, 16, 24].map(shift => ((alert.raw_ado >>> shift) & 255).toString(16).padStart(2, '0')).join('');
        else if (!port.active_contract) record.alert_hex = '00000000';
        ports.push(record);
    }
    return {schema: 1, maximum_cache_seconds: s.maximum_cache_seconds, age_milliseconds: s.age_milliseconds,
        contract_hex: contract.data_hex, ports};
}

export function serviceInputs(report = null, contract = null, contractDecoder = null) {
    return {packagePower: packagePower(report), platformPower: platformPower(report), chargerAdc: chargerAdc(report),
        chargerMetrics: chargerMetrics(report), gauge: gauge(report), gaugeExtra: gaugeExtra(report), sbs: sbs(report),
        lifetime: lifetime(report), pdIdentity: pdIdentity(report, contract, contractDecoder)};
}
