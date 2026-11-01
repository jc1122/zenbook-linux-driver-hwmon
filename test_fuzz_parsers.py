# SPDX-License-Identifier: GPL-2.0-only
"""Property-based fuzz tests for pure firmware/sysfs/subprocess/D-Bus parsers.

Deterministic Hypothesis profile (derandomize, bounded examples, no database);
no real /sys, /proc, /dev or subprocess access (see tests/fuzz/fuzz_support.py).
Known defects found by fuzzing are pinned as expectedFailure reproducers so the
suite stays green until the runtime is fixed (then they become unexpected
successes and must be converted to ordinary tests).
"""
from pathlib import Path
from unittest import mock
import errno
import json
import math
import re
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'tests' / 'fuzz'))
sys.path.insert(0, str(HERE / 'service'))

from hypothesis import given, strategies as st  # noqa: E402

import fuzz_support as fz  # noqa: E402
from fuzz_support import JSON, WORD, assert_finite_json, hardware_guard, hex_bytes, mutated, word_bytes  # noqa: E402

import application_inventory  # noqa: E402
import battery_diagnostics  # noqa: E402
import battery_extra  # noqa: E402
import battery_sbs  # noqa: E402
import charger_adc  # noqa: E402
import charger_metrics  # noqa: E402
import disk_temperature  # noqa: E402
import display_state  # noqa: E402
import gpu_usage  # noqa: E402
import hwd_core  # noqa: E402
import native_oem  # noqa: E402
import package_power  # noqa: E402
import pd_contract  # noqa: E402
import pd_identity  # noqa: E402
import pd_sources  # noqa: E402
import thermistors  # noqa: E402
import usb_inventory  # noqa: E402
import usb_power  # noqa: E402
import wireless  # noqa: E402
import wireless_native  # noqa: E402

# Exceptions each module's own reader converts to an unavailable result.
BATTERY_ERRORS = (OSError, ValueError, TypeError, KeyError, RuntimeError)
CHARGER_ERRORS = (OSError, RuntimeError, ValueError, TypeError)
PD_IDENTITY_ERRORS = (OSError, ValueError, TypeError, KeyError, RuntimeError)
FW_PREFIX = '45560234004002'


def gauge(seconds, **payloads):
    base = st.fixed_dictionaries({
        'schema': st.just(1), 'device_type_hex': st.just('5645'),
        'firmware_hex': hex_bytes(6).map(lambda h: FW_PREFIX + h),
        'age_milliseconds': st.integers(0, seconds * 1000), 'maximum_cache_seconds': st.just(seconds),
        **payloads})
    keys = {'schema', 'device_type_hex', 'firmware_hex', 'age_milliseconds', 'maximum_cache_seconds', *payloads}
    return st.one_of(base, base, base, mutated(base, keys), JSON)


def checked(case, function, allowed, *args):
    """Run function; any exception must be one of the documented types."""
    try:
        return function(*args)
    except allowed:
        return None


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        guard = hardware_guard()
        guard.__enter__()
        self.addCleanup(guard.__exit__, None, None, None)
        patch = mock.patch.object(native_oem, 'device', return_value=self.root)
        patch.start()
        self.addCleanup(patch.stop)


# --------------------------------------------------------------------------
# Battery gauge decoders
# --------------------------------------------------------------------------

@st.composite
def extra_frame(draw):
    volts = [draw(st.integers(1900, 5100)) for _ in range(2)] + [draw(st.sampled_from([0, 65535, 1, 3000])) for _ in range(2)]
    currents = [draw(st.integers(-21000, 21000)) for _ in range(2)]
    powers = [round(volts[i] * currents[i] / 10000) + draw(st.integers(-4, 4)) for i in range(2)]
    a = word_bytes(volts + [draw(WORD) for _ in range(2)] + currents + [draw(WORD) for _ in range(2)]
                   + powers + [draw(WORD) for _ in range(2)] + [draw(st.integers(-25000, 25000)) for _ in range(2)])
    t = draw(st.binary(min_size=14, max_size=14)) + word_bytes([draw(st.integers(2000, 4500))]) + word_bytes(
        [v + draw(st.integers(-600, 600)) for v in volts[:2]] + [draw(st.sampled_from([0, 0, 7])) for _ in range(2)])
    return {'da1_hex': a.hex(), 'da2_hex': t.hex()}


class BatteryDecoderFuzz(unittest.TestCase):
    @given(gauge(15, da1_hex=hex_bytes(32), da2_hex=hex_bytes(24)) | gauge(15).flatmap(
        lambda base: extra_frame().map(lambda f: {**base, **f}) if isinstance(base, dict) else st.just(base)))
    def test_extra_decode(self, data):
        with hardware_guard():
            result = checked(self, battery_extra.decode, BATTERY_ERRORS, data)
        if result is None:
            return
        assert_finite_json(self, result)
        self.assertEqual([c['cell'] for c in result['cells']], [1, 2])
        for cell in result['cells']:
            self.assertTrue(2 <= cell['voltage_volts'] <= 5)
            self.assertEqual(cell['power_watts'] is not None, cell['power_encoding_consistent_with_frame'])
            if cell['power_watts'] is not None:
                self.assertLessEqual(abs(cell['current_amperes']), 20)
        for key in ('gauge_power_watts', 'gauge_average_power_watts'):
            self.assertTrue(result[key] is None or abs(result[key]) <= 200)
        temp = result['gauging_temperature_celsius']
        self.assertTrue(temp is None or -40 <= temp <= 125)
        uncomp = result['uncompensated_cells']
        self.assertEqual(bool(uncomp['cells']), uncomp['available'])
        self.assertEqual('errno' in uncomp, not uncomp['available'])

    @given(gauge(5, da1_hex=hex_bytes(20), da2_hex=hex_bytes(14)) | gauge(5).flatmap(
        lambda base: st.tuples(st.lists(st.integers(1900, 5100), min_size=2, max_size=2),
                               st.lists(WORD, min_size=8, max_size=8), st.binary(min_size=14, max_size=14)).map(
            lambda p: {**base, 'da1_hex': (word_bytes(p[0] + [0, 0]) + word_bytes(p[1][:6])).hex(),
                       'da2_hex': p[2].hex()}) if isinstance(base, dict) else st.just(base)))
    def test_metrics_decode(self, data):
        result = checked(self, battery_diagnostics.decode_metrics, BATTERY_ERRORS, data)
        if result is None:
            return
        assert_finite_json(self, result)
        self.assertEqual([c['cell'] for c in result['cells']], [1, 2])
        for cell in result['cells']:
            self.assertTrue(2 <= cell['voltage_volts'] <= 5)
        for value in result['temperatures_celsius'].values():
            self.assertTrue(value is None or -40 <= value <= 125)
        for key in ('bat_pin_voltage_volts', 'pack_pin_voltage_volts'):
            self.assertTrue(result[key] is None or 4 <= result[key] <= 17)

    @given(st.binary(max_size=40))
    def test_runtime_regions_balancing(self, raw):
        for function in (battery_diagnostics.recorded_runtime, battery_diagnostics.recorded_regions,
                         battery_diagnostics.recorded_balancing):
            result = function(raw)
            assert_finite_json(self, result)
            if not result['available']:
                self.assertIn('errno', result)
                self.assertIsNone(result['resolution_hours'])
        runtime = battery_diagnostics.recorded_runtime(raw)
        if runtime['available']:
            self.assertEqual(len(raw), 26)
            self.assertEqual(runtime['hours'], 2 * int.from_bytes(raw[:2], 'little'))
            regions = battery_diagnostics.recorded_regions(raw)
            self.assertGreaterEqual(regions['rounding_gap_hours'], 0)
            self.assertLessEqual(regions['rounding_gap_hours'], 14)
        balancing = battery_diagnostics.recorded_balancing(raw)
        for cell in balancing['cells']:
            self.assertTrue((cell['hours'] is None) == cell['saturated'])
            self.assertTrue(cell['hours'] is None or 0 <= cell['hours'] < 510)

    @given(st.data())
    def test_lifetime_decode(self, draw):
        data = draw.draw(lifetime() | gauge(60, **{f'block{i}_prefix_hex': hex_bytes(4 if i == 3 else 31) for i in (1, 3, 4, 5)}))
        result = checked(self, battery_diagnostics.decode_lifetime, BATTERY_ERRORS, data)
        if result is None:
            return
        assert_finite_json(self, result)
        self.assertEqual([c['cell'] for c in result['cells']], [1, 2])
        for cell in result['cells']:
            self.assertTrue(1.5 <= cell['minimum_voltage_volts'] <= cell['maximum_voltage_volts'] <= 5)
        for value in result['temperatures_celsius'].values():
            self.assertTrue(-40 <= value <= 125)
        self.assertTrue(0 <= result['maximum_charge_current_amperes'] <= 20)
        self.assertTrue(0 <= result['maximum_discharge_current_amperes'] <= 20)
        self.assertLessEqual(result['max_cell_delta_millivolts'], 3000)
        self.assertEqual(result['raw_blocks'] is not None, result['complete_blocks'])
        self.assertEqual(len(result['lifetime_events']), 16)


@st.composite
def lifetime(draw):
    """Mostly-valid lifetime envelopes (complete or prefix-only) with small perturbations."""
    highs = [draw(st.integers(1400, 5100)) for _ in range(2)]
    lows = [draw(st.integers(max(1400, h - 800), h + 20)) for h in highs]
    b1 = word_bytes(highs + [0, 0] + lows + [draw(st.sampled_from([0, 32767])) for _ in range(2)]
                    + [draw(st.integers(0, 3100)), draw(st.integers(-100, 20100)), draw(st.integers(-20100, 100)),
                       draw(st.integers(-20100, 100)), draw(st.integers(-20100, 100))])
    tmin, tmax = sorted(draw(st.integers(-45, 130)) for _ in range(2))
    imin, imax = sorted(draw(st.integers(-45, 130)) for _ in range(2))
    if draw(st.integers(0, 9)) == 0:
        tmin, tmax = tmax, tmin
    b1 += bytes([tmax & 255, tmin & 255, draw(st.integers(0, 255)), imax & 255, imin & 255,
                 draw(st.integers(-45, 130)) & 255])
    parts = [draw(st.integers(0, 4000)) for _ in range(7)]
    b3 = word_bytes([sum(parts) + draw(st.integers(-1, 8))] + parts) + draw(st.binary(min_size=10, max_size=10))
    b2 = draw(st.binary(min_size=6, max_size=6)) + draw(st.sampled_from([b'\0\0', b'\0\1']))
    b4, b5 = (draw(st.binary(min_size=32, max_size=32)) for _ in range(2))
    blocks = {1: b1, 2: b2, 3: b3, 4: b4, 5: b5}
    data = {'schema': 1, 'device_type_hex': '5645', 'firmware_hex': FW_PREFIX + '00' * 6,
            'age_milliseconds': draw(st.integers(0, 60000)), 'maximum_cache_seconds': 60}
    for i, size in ((1, 31), (3, 4), (4, 31), (5, 31)):
        data[f'block{i}_prefix_hex'] = blocks[i][:size].hex()
    if draw(st.booleans()):
        data['block2_prefix_hex'] = b2[:4].hex()
    complete = draw(st.sampled_from([True, False, None]))
    if complete is not None:
        data['complete_blocks'] = complete
    if complete:
        for i, raw in blocks.items():
            data[f'block{i}_hex'] = raw.hex()
    return data


@st.composite
def sbs_words(draw):
    return [0x31, draw(WORD), draw(st.integers(1900, 4100)), draw(st.integers(3900, 11100)),
            draw(st.integers(-21000, 21000)) & 0xffff, draw(st.integers(-21000, 21000)) & 0xffff,
            draw(WORD), draw(WORD), draw(st.integers(0, 110)), draw(st.integers(0, 110)),
            draw(st.integers(0, 110)), draw(WORD), draw(WORD), draw(WORD), draw(WORD), draw(st.integers(3900, 11100))]


class SbsFuzz(unittest.TestCase):
    @given(gauge(30, words=st.one_of(sbs_words(), st.lists(WORD, min_size=15, max_size=17), JSON),
                 transport=st.sampled_from(['legacy_i2c_combined_read_word', 'native_smbus_read_word', 'x'])))
    def test_decode(self, data):
        result = checked(self, battery_sbs.decode, BATTERY_ERRORS, data)
        if result is None:
            return
        assert_finite_json(self, result)
        self.assertTrue(4 <= result['voltage_volts'] <= 11)
        self.assertTrue(-73.16 <= result['temperature_celsius'] <= 126.86)
        for key in ('relative_state_of_charge_percent', 'absolute_state_of_charge_percent',
                    'state_of_charge_maximum_error_percent'):
            self.assertTrue(0 <= result[key] <= 100)
        self.assertLessEqual(abs(result['current_amperes']), 20)
        mode = result['capacity_mode']
        for key, value in result['capacities'].items():
            if value is not None:
                self.assertEqual('watt' in key, mode == 'energy')

    @given(st.one_of(st.deferred(lambda: diagnostics()), JSON))
    def test_diagnostics(self, data):
        result = checked(self, battery_sbs.decode_diagnostics, BATTERY_ERRORS, data)
        if result is None:
            return
        json.dumps(result)
        self.assertEqual(result['attempts'], result['successes'] + result['failures'])
        if not result['attempts']:
            self.assertIsNone(result.get('last_attempt'))


@st.composite
def diagnostics(draw):
    successes, failures = draw(st.integers(0, 3)), draw(st.integers(0, 3))
    transport = draw(st.sampled_from(['legacy_i2c_combined_read_word', 'native_smbus_read_word']))

    def trace(failed):
        status = draw(st.sampled_from([0, -errno.EIO, -errno.ETIMEDOUT])) if not failed else draw(st.sampled_from([-errno.EIO, -1]))
        restoration = draw(st.sampled_from([0, 0, -1]))
        row = {'phase': draw(st.sampled_from(['complete', 'word-command', 'bogus'])), 'operation_status': status,
               'restoration_status': restoration, 'result': -errno.EUCLEAN if restoration else status,
               'age_milliseconds': draw(st.integers(0, 10**6)), 'sentinel_attempt': draw(st.sampled_from([0, 1, 2])),
               'bracket': draw(st.booleans()), 'command': draw(st.sampled_from([None, 3, 8, 0x1a, 99])),
               'completion_status': draw(st.sampled_from([None, 0, 1])),
               'worker_result': draw(st.sampled_from([None, 0, 1]))}
        if draw(st.booleans()):
            row['software_observation'] = draw(st.one_of(st.just({'result': 0, 'atomic': False, 'current_operation_proven': False,
                                                                  'raw_hex': draw(st.sampled_from(['00000100', '0000010x', 'zz']))}), JSON))
        return row
    data = {'schema': 1, 'cached_metadata_only': True, 'transport': transport,
            'attempts': successes + failures + draw(st.sampled_from([0, 0, 1])), 'successes': successes,
            'failures': failures, 'last_attempt': trace(False) if successes + failures else None,
            'last_failure': trace(True) if failures else None}
    if draw(st.booleans()):
        data.update(retries=draw(st.integers(0, 2)), recovered_refreshes=draw(st.integers(0, 2)),
                    retry_limit=1, retry_backoff_milliseconds=draw(st.sampled_from([100, 99])))
    return data


# --------------------------------------------------------------------------
# Charger and package-power decoders
# --------------------------------------------------------------------------

@st.composite
def charger_adc_frame(draw):
    v = draw(st.integers(40, 255))
    words = [0x49, 0x0e, draw(st.sampled_from([1, 1, 3, 0])), draw(st.sampled_from([0, 0, 0x800])),
             0x4000 | (draw(st.sampled_from([1, 2, 3, 3, 0, 4])) << 5), (v << 6) | draw(st.sampled_from([0, 0, 0, 1])),
             draw(st.integers(0, 256)), (v + draw(st.sampled_from([0, 0, 1, -1, 2]))) % 256 << 6,
             0x4000 | (draw(st.integers(1, 3)) << 5), draw(st.sampled_from([1, 1, 0]))]
    mv, ua = (words[7] >> 6) * 96, words[6] * 44400
    data = {'schema': 1, 'words': words, 'input_millivolts': mv, 'input_microamps': ua,
            'input_microwatts': (mv * ua + 500) // 1000, 'current_resolution_microamps': 44400,
            'voltage_resolution_millivolts': 96, 'input_shunt_milliohms': 10, 'maximum_cache_seconds': 2,
            'age_milliseconds': draw(st.integers(0, 2100))}
    return data


class ChargerFuzz(unittest.TestCase):
    @given(st.one_of(charger_adc_frame(), charger_adc_frame(), mutated(charger_adc_frame(), {'words', 'schema', 'input_millivolts', 'age_milliseconds'}),
                     st.dictionaries(st.text(max_size=8), JSON, max_size=4)))
    def test_adc_decode(self, data):
        result = checked(self, charger_adc.decode, CHARGER_ERRORS, data)
        if result is None:
            return
        assert_finite_json(self, result)
        self.assertTrue(4 <= result['voltage_volts'] <= 24)
        self.assertTrue(0 <= result['current_amperes'] <= 255 * .0444 + 1e-9)
        self.assertAlmostEqual(result['power_watts'], result['voltage_volts'] * result['current_amperes'], places=2)

    @given(st.one_of(st.dictionaries(st.sampled_from(['schema', 'words', 'age_milliseconds', 'valid_mask',
                                                      'battery_shunt_milliohms', 'maximum_cache_seconds']), JSON),
                     st.fixed_dictionaries({'schema': st.just(1), 'words': st.lists(WORD, min_size=14, max_size=14).map(
                         lambda w: [0x49, 0x0e] + w[2:11] + [w[11] & 0x1fff, w[12] & 0x7fff, w[13]]),
                         'valid_mask': st.just(0), 'battery_shunt_milliohms': st.just(5),
                         'maximum_cache_seconds': st.just(2), 'age_milliseconds': st.integers(0, 2000)})))
    def test_metrics_decode(self, data):
        result = checked(self, charger_metrics.decode, CHARGER_ERRORS, data)
        if result is None:
            return
        assert_finite_json(self, result)
        die = result['die_temperature_celsius']
        self.assertTrue(die is None or -10 <= die <= 170)
        self.assertEqual(result['adc_available'], any(result[k] is not None for k in (
            'die_temperature_celsius', 'vbat_pin_voltage_volts', 'system_voltage_volts',
            'battery_discharge_current_amperes', 'battery_charge_current_amperes')))

    @given(st.one_of(st.dictionaries(st.sampled_from(sorted(package_power.FIELDS)), st.integers(-2**40, 2**40)),
                     st.fixed_dictionaries({k: st.just(v) for k, v in
                                            {'schema': 1, 'cpu': 0, 'maximum_cache_seconds': 1}.items()} | {
                         'age_microseconds': st.integers(-1, 1_000_001), 'energy_before': st.integers(0, 2**32),
                         'energy_after': st.integers(0, 2**32), 'energy_exponent': st.integers(0, 32),
                         'elapsed_microseconds': st.integers(99_999, 30_000_001),
                         'power_microwatts': st.integers(0, 2**31)}).map(lambda d: _fix_power(d)), JSON))
    def test_package_decode(self, data):
        result = checked(self, package_power.decode, (OSError,), data)
        if result is None:
            return
        assert_finite_json(self, result)
        self.assertTrue(0 < result['watts']['package-0'] <= 1000)
        self.assertTrue(.1 <= result['sample_seconds'] <= 30)


def _fix_power(data):
    if data['energy_exponent'] and data['elapsed_microseconds']:
        delta = (data['energy_after'] - data['energy_before']) & 0xffffffff
        data = dict(data, power_microwatts=((delta * 1_000_000_000) >> data['energy_exponent']) * 1000 // data['elapsed_microseconds'])
    return data


class ReaderFuzz(TempDirCase):
    """Raw bytes through the modules' own sysfs readers (native_oem.device redirected)."""

    @given(st.one_of(st.binary(max_size=64), JSON.map(lambda v: json.dumps(v).encode()),
                     st.dictionaries(st.sampled_from(sorted(package_power.FIELDS)), st.integers(0, 3)).map(
                         lambda d: json.dumps(d).encode()),
                     st.just(b'{"schema":1,"schema":1}'), st.just(b' ' * 4097)))
    def test_package_power_read(self, raw):
        fz.write(self.root, 'cpu_package_power', raw)
        try:
            package_power.read()
        except OSError as error:
            self.assertTrue(error.errno)

    @given(st.dictionaries(st.text(max_size=6), JSON, max_size=4).map(lambda v: json.dumps(v).encode()) | st.binary(max_size=40))
    def test_charger_reports_dict_or_garbage(self, raw):
        for name, module in (('charger_adc', charger_adc), ('charger_metrics', charger_metrics)):
            fz.write(self.root, name, raw)
            result = module.report()
            self.assertFalse(result['available'])
            self.assertTrue(result['errno'])

    def test_known_bug_charger_report_non_object_json(self):
        # Reproducer: a valid JSON non-object (list/number/string) escapes
        # report() as AttributeError ('list' object has no attribute 'get').
        for name, module in (('charger_adc', charger_adc), ('charger_metrics', charger_metrics)):
            fz.write(self.root, name, b'[]')
            self.assertFalse(module.report()['available'])

    @given(st.lists(st.tuples(st.sampled_from(['SSD NTC', 'Ambient NTC', 'CPU NTC', 'x', '']),
                              st.one_of(st.integers(-10**6, 10**6).map(str), st.text(max_size=8),
                                        st.just('9' * 5000))), min_size=5, max_size=5))
    def test_thermistors(self, rows):
        for index, (label, value) in enumerate(rows, 2):
            fz.write(self.root, f'temp{index}_label', label)
            fz.write(self.root, f'temp{index}_input', value)
        result = thermistors.report()
        assert_finite_json(self, result)
        self.assertEqual(result['available'], any(s['temperature_celsius'] is not None for s in result['sensors']))
        for sensor in result['sensors']:
            value = sensor['temperature_celsius']
            self.assertTrue(value is None or 0 < value <= 125)

    @given(st.one_of(st.integers(-10, 2 * 10**9).map(str), st.just('0')))
    def test_platform_power_integers(self, text):
        fz.write(self.root, 'power1_input', text)
        result = pd_contract.platform_power(sleep=lambda _: None)
        assert_finite_json(self, result)
        if result['available']:
            self.assertTrue(0 < result['watts'] <= 1000)
        else:
            self.assertTrue(result['errno'])

    def test_known_bug_platform_power_non_integer(self):
        # Reproducer: power1_input containing non-integer text ('nan', '', or
        # non-UTF-8) raises ValueError out of platform_power() instead of
        # returning {'available': False, ...}; only OSError/RuntimeError are caught.
        fz.write(self.root, 'power1_input', 'nan\n')
        self.assertFalse(pd_contract.platform_power(sleep=lambda _: None)['available'])


# --------------------------------------------------------------------------
# USB-PD decoders
# --------------------------------------------------------------------------

@st.composite
def pd_snapshot(draw):
    data = bytearray([1, draw(st.sampled_from([0, 1, 1, 3, 255])), draw(st.integers(0, 255))])
    for _ in range(2):
        mv = draw(st.sampled_from([5000, 9000, 15000, 20000, 48000, 4000, 51150]))
        ma = draw(st.sampled_from([500, 1500, 3000, 5000, 6000, 40]))
        pdo = draw(st.sampled_from([0, 0, 1, 2, 3])) << 30 | ((mv // 50) & 1023) << 10 | ((ma // 10) & 1023)
        watts = round(mv * ma / 1_000_000) + draw(st.sampled_from([0, 0, 2]))
        flags = draw(st.sampled_from([0x40, 0x40, 0, 0xff, 0x41]))
        data += bytes([flags, watts & 255]) + mv.to_bytes(2, 'little') + ma.to_bytes(2, 'little') + pdo.to_bytes(4, 'little')
    return bytes(data)


class PdFuzz(unittest.TestCase):
    def check_contract(self, result):
        assert_finite_json(self, result)
        for port in result['ports']:
            if port['available']:
                self.assertTrue(result['ac_online'])
                contract = port['contract']
                self.assertTrue(4.5 <= contract['voltage_volts'] <= 50)
                self.assertTrue(.05 <= contract['current_limit_amperes'] <= 5)
                self.assertAlmostEqual(contract['power_limit_watts'],
                                       contract['voltage_volts'] * contract['current_limit_amperes'], places=2)
                self.assertFalse(contract['measurement'])
            else:
                self.assertIsNone(port['contract'])
        if result['ec_adapter_watts'] is not None:
            self.assertTrue(any(p['available'] for p in result['ports']))

    @given(st.one_of(pd_snapshot(), st.binary(max_size=30)))
    def test_contract_decode(self, data):
        result = checked(self, pd_contract.decode, (OSError,), data)
        if result is not None:
            self.check_contract(result)

    @given(pd_snapshot(), st.lists(st.tuples(st.integers(0, 8), st.lists(st.integers(0, 2**32 - 1), max_size=8)),
                                   min_size=2, max_size=2), st.binary(max_size=4))
    def test_sources_decode(self, snapshot, ports, noise):
        tail = bytearray()
        for count, words in ports:
            if words and snapshot:
                words[0] = (words[0] & ~(0xc00ffc00)) | (100 << 10)
            block = bytes([count]) + b''.join(w.to_bytes(4, 'little') for w in words[:7])
            tail += block[:29].ljust(29, b'\0')
        data = snapshot + bytes(tail)
        for candidate in (data, data[:-1] + noise[:1] if noise else data, bytes([1]) + noise * 20):
            result = checked(self, pd_sources.decode, (OSError,), candidate)
            if result is None:
                continue
            assert_finite_json(self, result)
            self.assertEqual(result['available'], any(p['available'] for p in result['ports']))
            for port in result['ports']:
                if not port['available']:
                    self.assertEqual(port['profiles'], [])
                    continue
                self.assertTrue(1 <= len(port['profiles']) <= 7)
                for profile in port['profiles']:
                    if profile['type'] == 'fixed':
                        self.assertTrue(4.5 <= profile['voltage_volts'] <= 50)
                        self.assertTrue(.05 <= profile['current_limit_amperes'] <= 5)

    @given(st.binary(min_size=0, max_size=30))
    def test_identity_and_alert(self, raw):
        if len(raw) == 25 or raw[:1]:
            raw25 = (raw + bytes(25))[:25]
            result = checked(self, pd_identity.identity, (OSError, ValueError), raw25)
            if result is not None:
                assert_finite_json(self, result)
                if result['available']:
                    self.assertEqual(result['response'], 'acknowledged')
                    self.assertNotIn(result['vendor_id'], (0, 65535))
                    self.assertEqual(len(result['raw_vdos_hex']), result['valid_vdo_count'])
                    self.assertEqual('other_raw_vdo' in result, result['valid_vdo_count'] >= 5)
        result = checked(self, pd_identity.identity, (OSError, ValueError), raw)
        if result is not None:
            self.assertEqual(len(raw), 25)
        for candidate in (raw[:4], bytes(2) + raw[:2]):
            alert = checked(self, pd_identity.received_alert, (OSError, ValueError), candidate)
            if alert is not None:
                self.assertEqual(alert['raw_ado'] & 0xffff, 0)
                assert_finite_json(self, alert)
        alert = None
        if alert is not None:
            self.assertEqual(alert['raw_ado'] & 0xffff, 0)
            assert_finite_json(self, alert)

    @given(st.one_of(
        st.fixed_dictionaries({
            'schema': st.just(1), 'maximum_cache_seconds': st.just(5), 'age_milliseconds': st.integers(0, 5000),
            'contract_hex': pd_snapshot().map(bytes.hex),
            'ports': st.tuples(*[st.fixed_dictionaries({
                'connector': st.just(i), 'sop_hex': hex_bytes(25) | st.just('00' * 25),
                'cable_hex': st.just('41' + '00' * 24) | hex_bytes(25)},
                optional={'alert_hex': hex_bytes(4) | st.just('00000000')}) for i in (1, 2)]).map(list)}),
        st.dictionaries(st.sampled_from(['schema', 'maximum_cache_seconds', 'age_milliseconds', 'contract_hex', 'ports']), JSON)))
    def test_identity_decode(self, data):
        result = checked(self, pd_identity.decode, PD_IDENTITY_ERRORS, data)
        if result is None:
            return
        assert_finite_json(self, result)
        for port in result['ports']:
            if not port['active_contract']:
                self.assertFalse(port['partner']['available'])
                self.assertFalse(port['cable']['available'])

    def test_known_bug_identity_non_object_port(self):
        # Reproducer: a port record that is not a JSON object escapes as
        # AttributeError, which pd_identity.report() does not catch.
        data = {'schema': 1, 'maximum_cache_seconds': 5, 'age_milliseconds': 0,
                'contract_hex': (bytes([1, 0, 0]) + bytes(20)).hex(), 'ports': [1, 2]}
        try:
            pd_identity.decode(data)
        except PD_IDENTITY_ERRORS:
            pass

    @given(st.sampled_from(sorted(pd_identity.NAMES) + ['bogus']), JSON)
    def test_identity_validate(self, name, args):
        try:
            pd_identity.validate(name, args)
        except ValueError:
            return
        self.assertIsInstance(args, dict)
        self.assertIn(name, pd_identity.NAMES)
        for key in ('raw_header', 'native_alert'):
            if key in args:
                self.assertIs(type(args[key]), bool)
        if 'connector' in args:
            self.assertIn(args['connector'], (1, 2))


# --------------------------------------------------------------------------
# GPU, USB, display, disk
# --------------------------------------------------------------------------

COUNTER = st.integers(0, 2**64 - 1)


class SysfsTextFuzz(unittest.TestCase):
    @given(st.text(max_size=24) | st.integers(0, 2**70).map(str), st.integers(0, 2**64))
    def test_gpu_unsigned(self, raw, maximum):
        try:
            value = gpu_usage.unsigned(raw, maximum)
        except OSError as error:
            self.assertEqual(error.errno, errno.EPROTO)
            return
        self.assertTrue(0 <= value <= maximum)
        self.assertEqual(value, int(raw))

    @given(st.tuples(COUNTER, COUNTER, COUNTER), st.tuples(COUNTER, COUNTER, COUNTER),
           st.floats(allow_nan=True, allow_infinity=True), st.floats(-1, 6))
    def test_gpu_counter_result(self, before, after, elapsed, gap):
        for b, a in ((before, after), (before, tuple(x + 10**9 for x in before)),
                     ((0, 0, 0), (min(before[0], 10**9), 10**9, 10**9))):
            result = checked(self, gpu_usage.counter_result, (OSError,), b, a, elapsed if b is before else 1.0,
                             gap if b is before else 1.0)
            if result is None:
                continue
            assert_finite_json(self, result)
            self.assertTrue(0 <= result['percent'] <= 100)
            self.assertFalse(result['multiplexed'])

    @given(st.text(max_size=8))
    def test_usb_version(self, raw):
        try:
            value = usb_inventory.version(raw)
        except OSError:
            return
        self.assertRegex(value, r'\A[0-9a-f]{4}\Z')

    @given(st.binary(max_size=200))
    def test_edid_identity(self, tail):
        header = b'\0\xff\xff\xff\xff\xff\xff\0'
        for data in (tail, header + tail, _edid(tail)):
            result = checked(self, display_state.edid_identity, (OSError,), data)
            if result is None:
                continue
            assert_finite_json(self, result)
            self.assertRegex(result['manufacturer'], r'\A[A-Z]{3}\Z')
            self.assertTrue(0 <= result['product_id'] <= 65535)
            if result['model_available']:
                self.assertTrue(1 <= len(result['model']) <= 13)
                self.assertTrue(all(32 <= ord(c) <= 126 for c in result['model']))
            else:
                self.assertNotIn('model', result)


def _edid(tail):
    body = bytearray(b'\0\xff\xff\xff\xff\xff\xff\0' + (tail + bytes(128))[:120])
    body[18] = 1
    body[8:10] = (((tail[:1] or b'\x04')[0] % 26 + 1) << 10 | 3 << 5 | 7).to_bytes(2, 'big')
    if tail[1:2] and tail[1] & 1:
        body[54:59] = b'\0\0\0\xfc\0'
    body[127] = (-sum(body[:127])) % 256
    return bytes(body)


class FakeNode:
    """Minimal Path stand-in returning fixed text for usb_power.state()."""

    def __init__(self, files):
        self.files = files

    def __truediv__(self, name):
        node = FakeNode(self.files)
        node.name = name
        return node

    def read_text(self):
        return self.files[self.name]


class UsbAndDiskFuzz(TempDirCase):
    @given(st.sampled_from(['0', '1', '2', '3', '']), st.sampled_from(['Charging', 'Discharging', 'Not charging', 'Unknown', 'x']),
           st.lists(st.sampled_from(['C', 'PD', 'PD_PPS', '[C]', '[PD]', '[PD_PPS]', '[X]', 'C]']), max_size=4).map(' '.join))
    def test_usb_power_state(self, online, status, types):
        node = FakeNode({'online': online, 'status': status, 'usb_type': types})
        try:
            result = usb_power.state(node)
        except OSError as error:
            self.assertTrue(error.errno)
            return
        self.assertIn(result[0], (0, 1, 2))
        self.assertIn(result[3], ('C', 'PD', 'PD_PPS'))
        self.assertNotEqual(result[1], 'Unknown')

    @given(st.binary(max_size=80), st.integers(1, 64))
    def test_usb_text(self, raw, limit):
        path = fz.write(self.root, 'attr', raw)
        try:
            value = usb_inventory.text(path, limit)
        except OSError as error:
            self.assertEqual(error.errno, errno.EPROTO)
            return
        self.assertLessEqual(len(value), limit)
        self.assertFalse(any(ord(c) < 32 or ord(c) == 127 for c in value))

    @given(st.one_of(st.integers(-1, 300), st.just(None), st.just('0')),
           st.one_of(JSON.map(json.dumps), st.text(max_size=20), st.just(None),
                     st.floats(-100, 200).map(lambda t: json.dumps({'temperature': {'current': t}})),
                     st.integers(-100, 200).map(lambda t: json.dumps({'nvme_smart_health_information_log': {'temperature': t}}))))
    def test_smart_temperature(self, returncode, stdout):
        proc = subprocess.CompletedProcess([], returncode, stdout, '')
        runner = mock.Mock(return_value=proc)
        try:
            value = disk_temperature.smart_temperature(Path('/nonexistent/sdx'), runner, 1)
        except OSError as error:
            self.assertTrue(error.errno)
            return
        self.assertTrue(disk_temperature.valid(value))
        self.assertIn(type(value), (int, float))

    def test_known_bug_smart_deep_nesting(self):
        # Reproducer: a <1 MiB smartctl reply nested 100000 levels deep raises
        # RecursionError from json.loads; smart_temperature() catches only
        # ValueError and disk_temperature.report() only OSError/TimeoutExpired,
        # so one bad reply aborts the whole multi-disk report.
        proc = subprocess.CompletedProcess([], 0, '[' * 100000, '')
        try:
            disk_temperature.smart_temperature(Path('/nonexistent/sdx'), mock.Mock(return_value=proc), 1)
        except OSError:
            pass


# --------------------------------------------------------------------------
# Wireless text and cache parsers
# --------------------------------------------------------------------------

MAC = st.binary(min_size=6, max_size=6).map(lambda b: ':'.join(f'{x:02x}' for x in b))
LINE = st.one_of(
    st.text(max_size=20),
    st.integers(-200, 200).map(lambda v: f'\tsignal: {v} dBm'),
    st.floats(-1, 200000).map(lambda v: f'\tfreq: {v}'),
    st.integers(0, 200000).map(lambda v: f'\tfreq: {v}'),
    st.sampled_from(['\ttx bitrate: 866.7 MBit/s VHT-MCS 9', '\trx bitrate: 1200.9 MBit/s HE-MCS 11',
                     '\ttx bitrate: 0 MBit/s', '\trx bitrate: 1e400 MBit/s', '\tsignal: -40 [-41, -45] dBm',
                     '\tsignal: -40 [x] dBm', '\tsignal: 999 dBm', 'Not connected.']))


class WirelessFuzz(unittest.TestCase):
    @given(MAC, st.lists(LINE, max_size=8))
    def test_parse_link(self, peer, lines):
        for text in ('\n'.join(lines), f'Connected to {peer} (on wlan0)\n' + '\n'.join(lines)):
            result = checked(self, wireless.parse_link, (OSError,), text, 'wlan0')
            if result is None:
                continue
            assert_finite_json(self, result)
            if not result['connected']:
                self.assertIsNone(result['peer'])
                continue
            self.assertRegex(result['peer'], r'\A([0-9a-f]{2}:){5}[0-9a-f]{2}\Z')
            freq = result['frequency_mhz']
            self.assertTrue(freq is None or 100 <= freq <= 100000)
            self.assertTrue(result['signal_dbm'] is None or -150 <= result['signal_dbm'] <= 50)
            for value in result['reported_rates_mbit'].values():
                self.assertTrue(value is None or 0 < value <= 1_000_000)

    @given(st.lists(st.tuples(MAC, st.lists(LINE, max_size=5)), max_size=4), st.text(max_size=10))
    def test_parse_bss(self, blocks, prefix):
        text = ''.join(f'BSS {mac}(on wlan0)\n' + '\n'.join(lines) + '\n' for mac, lines in blocks)
        for candidate in (text, prefix + text):
            result = checked(self, wireless.parse_bss, (OSError,), candidate)
            if result is None:
                continue
            assert_finite_json(self, result)
            for row in result:
                self.assertTrue(100 <= row['frequency_mhz'] <= 100000)
                self.assertTrue(row['signal_dbm'] is None or -150 <= row['signal_dbm'] <= 50)

    @given(MAC, st.lists(LINE, max_size=6), st.booleans())
    def test_chains(self, peer, lines, duplicate):
        block = f'Station {peer} (on wlan0)\n' + '\n'.join(lines) + '\n'
        result = checked(self, wireless.chains, (OSError,), 'wlan0', peer, block * (2 if duplicate else 1))
        if result is None:
            return
        self.assertFalse(duplicate)
        self.assertTrue(-128 <= result['aggregate_dbm'] <= 127)
        self.assertTrue(len(result['chains_dbm']) <= 16)
        self.assertEqual(result['chain_signal_available'], bool(result['chains_dbm']))

    def test_known_bug_chains_huge_integer(self):
        # Reproducer: a 5000-digit signal value exceeds Python's int-string
        # limit and raises ValueError instead of the documented OSError(EPROTO).
        text = 'Station 00:11:22:33:44:55 (on wlan0)\n\tsignal: -' + '9' * 5000 + ' dBm\n'
        try:
            wireless.chains('wlan0', '00:11:22:33:44:55', text)
        except OSError:
            pass

    @given(st.sampled_from(sorted(wireless.RSSI_NAMES) + sorted(wireless.LINK_NAMES)),
           st.dictionaries(st.sampled_from(['threshold_dbm', 'x']), st.one_of(
               st.floats(allow_nan=True, allow_infinity=True), st.integers(-200, 200), st.booleans(), st.text(max_size=3)),
               max_size=2))
    def test_validate(self, name, args):
        try:
            wireless.validate(name, args)
        except ValueError:
            return
        value = args.get('threshold_dbm', -65)
        self.assertTrue(math.isfinite(value) and -120 <= value <= 0)

    def test_known_bug_validate_huge_threshold(self):
        # Reproducer: JSON integer threshold_dbm=10**400 raises OverflowError
        # from math.isfinite() instead of ValueError.
        try:
            wireless.validate('RF_WiFi_5G_AP_RSSI_Num', {'threshold_dbm': 10**400})
        except ValueError:
            pass

    @given(st.data())
    def test_validate_cache(self, draw):
        boot = 'boot'
        current = {'interfaces': [{'interface': 'wlan0', 'identity': (1, 2, 3), 'peer': draw.draw(st.sampled_from([None, 'aa:bb:cc:dd:ee:ff']))}]}
        ok_row = {'interface': 'wlan0', 'ifindex': 3, 'connected': current['interfaces'][0]['peer'] is not None,
                  'capability': draw.draw(st.sampled_from([{'available': False}, {'available': True, 'maximum_mbit_s': 1200,
                                                                                  'operation_width_mhz': 80, 'complete_for_scope': True}])),
                  'association_phy': draw.draw(st.sampled_from([{'available': False}, {'available': True, 'family': '802.11ax'},
                                                                {'available': True, 'family': 'x'}])),
                  'observations_available': True,
                  'observations': draw.draw(st.lists(st.fixed_dictionaries({
                      'ap_key': st.just('a' * 64) | st.text(max_size=3),
                      'frequency_mhz': st.integers(2300, 7200) | st.sampled_from([2412, 5180, 5955]),
                      'band': st.sampled_from(['2_4G', '5G', '6G', None]),
                      'signal_dbm': st.none() | st.integers(-160, 60), 'age_seconds': st.none() | st.integers(-1, 10)}), max_size=3))}
        base = {'schema': 1, 'maximum_cache_seconds': 45, 'boot_id': boot,
                'generated_boottime_seconds': draw.draw(st.floats(0, 200) | st.integers(0, 200) | st.just(math.nan)),
                'context_id': wireless_native.fingerprint(current), 'interfaces': [ok_row], 'available': True}
        data = draw.draw(st.one_of(st.just(base), mutated(st.just(base), set(base)),
                                   mutated(st.just(ok_row), set(ok_row)).map(lambda r: {**base, 'interfaces': [r]}), JSON))
        try:
            result = wireless_native.validate_cache(data, 100.0, current, boot)
        except OSError as error:
            self.assertTrue(error.errno)
            return
        self.assertTrue(0 <= result['age_seconds'] <= 45)
        for row in result['interfaces']:
            for item in row['observations']:
                self.assertEqual(item['band'], wireless.band(item['frequency_mhz']))

    def test_known_bug_validate_cache_huge_integer(self):
        # Reproducer: generated_boottime_seconds=10**400 (valid JSON integer)
        # raises OverflowError from math.isfinite(); wireless_native.report()
        # catches only OSError/ValueError/TypeError/RuntimeError.
        data = {'schema': 1, 'maximum_cache_seconds': 45, 'boot_id': 'b', 'generated_boottime_seconds': 10**400}
        try:
            wireless_native.validate_cache(data, 100.0, {'interfaces': []}, 'b')
        except OSError:
            pass


# --------------------------------------------------------------------------
# dpkg inventory parsing
# --------------------------------------------------------------------------

DPKG_LINE = st.one_of(
    st.text(max_size=30),
    st.tuples(st.sampled_from(['bash', 'libc6:amd64', 'Bad', 'x', '', 'bash', 'zlib1g:i386']),
              st.sampled_from(['5.2-1', '', '1:2.3']),
              st.sampled_from(['amd64', 'all', 'i386', 'arm64', '', 'a b']),
              st.sampled_from(sorted(application_inventory.STATES) + ['bogus'])).map('\t'.join))


class InventoryFuzz(unittest.TestCase):
    @given(st.lists(DPKG_LINE, max_size=12), st.sampled_from([32, 64]),
           st.dictionaries(st.sampled_from(['amd64', 'i386', 'arm64']), st.sampled_from(['64', '32', 'x', '0', '999', None])))
    def test_native(self, lines, bits, arch_bits):
        output = '\n'.join(lines)

        def command(args):
            if args[0] == 'dpkg-query':
                return output
            arch = args[1].split('=', 1)[1]
            value = arch_bits.get(arch)
            if value is None:
                raise OSError(errno.EIO, 'Native inventory command failed.')
            return value + '\n'
        with hardware_guard(), mock.patch.object(application_inventory, '_command', command):
            result = application_inventory.native(bits)
        assert_finite_json(self, result)
        provider = result['providers'][0]
        self.assertTrue(result['available'])
        self.assertEqual(provider['parse_error_count'] + provider['registered_present_packages'] + provider['removed_records_excluded'],
                         len(output.splitlines()))
        self.assertEqual(result['complete'], provider['complete'])
        names = [row['name'] for row in result['packages'] + result['architecture_independent'] + result['unclassified_packages']]
        self.assertEqual(len(names), len(set(names)))
        for row in result['packages']:
            self.assertEqual(row['architecture_bits'], bits)
            self.assertNotEqual(row['architecture'], 'all')
        for row in result['architecture_independent']:
            self.assertEqual(row['architecture'], 'all')
        if result['unclassified_packages'] or provider['parse_error_count']:
            self.assertFalse(result['complete'])


# --------------------------------------------------------------------------
# Request validation: service (hwd_core) and C/FFI bridge (api_bridge)
# --------------------------------------------------------------------------

AUTH = {'GetEEPROM_Data': hwd_core.READ, 'RF_WiFi_5G_AP_RSSI_Num': hwd_core.READ, 'WOA_EC_write': hwd_core.EC_OEM}


class ServiceRequestFuzz(unittest.TestCase):
    @given(st.one_of(JSON.map(lambda v: json.dumps(v)), st.text(max_size=40), st.just(''), st.none(), st.integers(),
                     st.integers(1, 12000).map(lambda n: '{"a":' * n + '1' + '}' * n),
                     st.integers(1, 40000).map(lambda n: '[' * n),
                     st.sampled_from(['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', '{"a":-Infinity}',
                                      '{"a":' + '9' * 5000 + '}', '{"\\ud800":1}', ' ' * 65537, '{}\x00'])))
    def test_parse_args(self, raw):
        try:
            args = hwd_core.parse_args(raw)
        except hwd_core.ServiceError as error:
            self.assertIn(error.errno, (errno.EINVAL, errno.E2BIG))
            return
        self.assertIsInstance(args, dict)
        self.assertLessEqual(len(raw.encode('utf-8', 'surrogatepass')), hwd_core.MAX_ARGS_BYTES)
        json.dumps(args, allow_nan=False)  # no NaN/Infinity accepted

    def test_known_bug_parse_args_overflowing_float(self):
        # Reproducer: parse_constant only intercepts the NaN/Infinity tokens;
        # an overflowing literal such as 1e999 decodes to float('inf') and is
        # accepted, contradicting the 'Non-finite JSON value' rejection.
        with self.assertRaises(hwd_core.ServiceError):
            hwd_core.parse_args('{"a":1e999}')

    @given(st.one_of(st.sampled_from(sorted(AUTH)), st.text(max_size=12), st.none(), st.integers()),
           st.one_of(st.booleans(), st.none(), st.integers(0, 1)),
           st.one_of(st.just(''), st.just('a' * 64), st.text(alphabet='0123456789abcdefABCDEF\n', max_size=65), st.none()),
           st.one_of(st.just('{}'), JSON.map(json.dumps)))
    def test_parse_call(self, name, apply, digest, raw):
        try:
            result = hwd_core.parse_call(name, raw, apply, digest, AUTH)
        except hwd_core.ServiceError as error:
            self.assertEqual(error.errno, errno.EINVAL)
            return
        self.assertIn(name, AUTH)
        self.assertIs(type(apply), bool)
        self.assertTrue(result[3] is None or re.fullmatch(r'[0-9a-f]{64}', result[3]))
        self.assertEqual(result[4], AUTH[name])


ARG_KEYS = ['connector', 'index', 'threshold_dbm', 'percent', 'duty', 'value', 'text', 'path', 'raw_header',
            'native_alert', 'manual', 'profile', 'refresh', 'bank', 'offset', 'length', 'kind']


class ApiBridgeFuzz(unittest.TestCase):
    """api_bridge.call() validation with dispatch mocked: no provider runs."""

    @classmethod
    def setUpClass(cls):
        import api_bridge
        import compat
        import efi_oem
        cls.api_bridge, cls.compat, cls.native_oem, cls.efi_oem = api_bridge, compat, native_oem, efi_oem
        cls.names = sorted(json.loads((HERE / 'capabilities.json').read_text())['exports'])

    @given(st.data())
    def test_call_validation(self, draw):
        name = draw.draw(st.sampled_from(self.names) | st.text(max_size=8) | st.none())
        request = draw.draw(st.one_of(
            st.fixed_dictionaries({'name': st.just(name)}, optional={
                'args': st.dictionaries(st.sampled_from(ARG_KEYS), JSON, max_size=3) | JSON,
                'apply': st.just(False) | JSON, 'expected_sha256': st.none() | st.just('a' * 64) | JSON}),
            st.dictionaries(st.text(max_size=6), JSON, max_size=3), JSON))
        sentinel = object()
        # Plan builders read DMI/efivars/policy files; stub them (their own
        # argument checks are covered by their module tests) so nothing real is read.
        plan = {'expected_sha256': '0' * 64}
        with hardware_guard(), mock.patch('os.geteuid', return_value=0), \
                mock.patch.object(self.native_oem, 'mutation_plan', return_value=plan), \
                mock.patch.object(self.efi_oem, 'call', return_value=plan), \
                mock.patch.object(self.compat, 'dispatch', return_value=sentinel) as dispatch:
            try:
                result = self.api_bridge.call(request)
            except (ValueError, KeyError, TypeError, OSError, RuntimeError):
                dispatch.assert_not_called()
                return
            except OverflowError:
                return  # documented below as a known defect (wireless threshold)
        self.assertIs(result, sentinel)
        self.assertIsInstance(request, dict)
        self.assertLessEqual(set(request), {'name', 'args', 'apply', 'expected_sha256'})
        self.assertIn(request['name'], self.names)
        self.assertIsInstance(request.get('apply', False), bool)
        self.assertIsInstance(request.get('args', {}), dict)
        dispatch.assert_called_once()


if __name__ == '__main__':
    unittest.main()
