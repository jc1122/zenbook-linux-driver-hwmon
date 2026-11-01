# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import errno
import io
import json
import unittest
from unittest import mock
import api_bridge
import compat
import package_power as power

def sample(a=1000,b=17384,elapsed=1_000_000,exponent=14,age=0):
    delta=(b-a)&0xffffffff
    return {'schema':1,'cpu':0,'energy_before':a,'energy_after':b,'energy_exponent':exponent,
            'elapsed_microseconds':elapsed,'power_microwatts':((delta*1_000_000_000)>>exponent)*1000//elapsed,
            'maximum_cache_seconds':1,'age_microseconds':age}

class PackagePowerTests(unittest.TestCase):
    def test_exact_units_interval_scope_and_single_wrap(self):
        for data,wanted in [(sample(),1),(sample(0xfffffff0,0xf0,200000),.078125)]:
            result=power.decode(data);self.assertEqual(result['watts'],{'package-0':wanted})
            self.assertEqual(result['sample_seconds'],data['elapsed_microseconds']/1_000_000)
            self.assertTrue(result['measurement']);self.assertIn('distinct from PSYS',result['scope'])

    def test_zero_stale_invalid_types_and_inconsistent_values_are_not_watts(self):
        for key,value in [('schema',2),('cpu',1),('energy_before',-1),('energy_after',2**32),('energy_exponent',0),
                          ('energy_exponent',32),('elapsed_microseconds',99999),('elapsed_microseconds',30000001),
                          ('power_microwatts',1),('maximum_cache_seconds',2),('age_microseconds',1000000),('age_microseconds',-1)]:
            data=sample();data[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(OSError):power.decode(data)
        for key in sample():
            data=sample();data[key]=True
            with self.assertRaises(OSError):power.decode(data)
        for data in [None,[],{},dict(sample(),unexpected=1),sample(5,5)]:
            with self.assertRaises(OSError):power.decode(data)
        with self.assertRaises(OSError) as error:power.decode(sample(1,1025,4096000,20))
        self.assertEqual(error.exception.errno,errno.ESTALE)

    def test_read_is_bounded_exact_and_closes_descriptor_on_parse_failures(self):
        for raw in [json.dumps(sample()).encode(),b'null',b'{"schema":1,"schema":1}',b'\xff',b'x'*4097]:
            with mock.patch.object(power.native_oem,'device',return_value=Path('/qualified')),mock.patch.object(power.os,'open',return_value=17) as opened, \
                 mock.patch.object(power.os,'read',return_value=raw) as read,mock.patch.object(power.os,'close') as close:
                if raw.startswith(b'{"schema": 1'):self.assertTrue(power.read()['available'])
                else:
                    with self.assertRaises(OSError):power.read()
                opened.assert_called_once_with(Path('/qualified/cpu_package_power'),power.os.O_RDONLY|power.os.O_CLOEXEC)
                read.assert_called_once_with(17,4097);close.assert_called_once_with(17)

    def test_only_initial_sampling_errors_get_one_bounded_retry(self):
        result=power.decode(sample())
        for code in (errno.ENODATA,errno.EAGAIN,errno.ESTALE):
            with mock.patch.object(power,'read',side_effect=[OSError(code,'warmup'),result]) as read,mock.patch.object(power.time,'sleep') as sleep:
                self.assertEqual(power.report(),result);self.assertEqual(read.call_count,2);sleep.assert_called_once_with(.12)
        for code in (errno.EACCES,errno.EIO,errno.ENOENT,errno.EOPNOTSUPP,errno.EPROTO):
            with mock.patch.object(power,'read',side_effect=OSError(code,'unavailable')) as read,mock.patch.object(power.time,'sleep') as sleep:
                r=power.report();self.assertFalse(r['available']);self.assertEqual(r['errno'],code)
                read.assert_called_once();sleep.assert_not_called()
        with mock.patch.object(power,'read',side_effect=OSError(errno.ENODATA,'stopped')) as read,mock.patch.object(power.time,'sleep'):
            with self.assertRaises(OSError) as error:power.require_report()
            self.assertEqual(error.exception.errno,errno.ENODATA);self.assertEqual(read.call_count,2)

    def test_native_api_and_CLI_power_route_non_root_callers_to_the_service(self):
        # 0.79: the driver's package-power attributes are root-only.
        import auth
        result=power.decode(sample());front=compat.frontend()
        self.assertTrue(compat.needs_root('Thermal_Read_CpuPackagePower',{}))
        client=mock.Mock(call=mock.Mock(return_value=result),control=mock.Mock(return_value=result))
        with mock.patch.object(power,'require_report',side_effect=AssertionError('no unprivileged read')),mock.patch.object(front.os,'geteuid',return_value=1000), \
             mock.patch.object(front,'elevated',side_effect=AssertionError('No elevation')),mock.patch.object(auth,'ServiceClient',return_value=client), \
             mock.patch.object(front,'service_client',return_value=client),mock.patch.object(auth,'deprecated_auth_notice'):
            self.assertEqual(api_bridge.call({'name':'Thermal_Read_CpuPackagePower'}),result)
            client.call.assert_called_once_with('Thermal_Read_CpuPackagePower',{},False,None)
            with mock.patch('sys.stdout',new_callable=io.StringIO) as stdout:
                self.assertEqual(front.main(['power']),0)
            self.assertEqual(json.loads(stdout.getvalue()),result);client.control.assert_called_once_with('power')
        with mock.patch.object(power,'require_report',return_value=result),mock.patch.object(front.os,'geteuid',return_value=0):
            self.assertEqual(api_bridge.call({'name':'Thermal_Read_CpuPackagePower'}),result)  # root: direct
        with mock.patch.object(power,'read',side_effect=AssertionError('No read on invalid arguments')):
            with self.assertRaises(ValueError):api_bridge.call({'name':'Thermal_Read_CpuPackagePower','args':{'path':'/arbitrary'}})

if __name__=='__main__':unittest.main()
