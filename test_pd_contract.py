# SPDX-License-Identifier: GPL-2.0-only
import errno
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import charger
import compat
import native_oem
import pd_contract


def snapshot(ac=3,flags=0x45,port=1):
    active=bytes([flags,65])+int(20000).to_bytes(2,'little')+int(3250).to_bytes(2,'little')+int(0x64145).to_bytes(4,'little')
    inactive=bytes(10)
    return bytes([1,ac,65])+(active+inactive if port==1 else inactive+active)


class PDContractTests(unittest.TestCase):
    def test_fixed_contract_is_a_limit_and_not_actual_draw(self):
        result=pd_contract.decode(snapshot())
        self.assertTrue(result['ac_online']);self.assertEqual(result['ec_adapter_watts'],65)
        self.assertFalse(result['instantaneous_measurements_available'])
        contract=result['ports'][0]['contract']
        self.assertEqual((contract['voltage_volts'],contract['current_limit_amperes'],contract['power_limit_watts']),(20,3.25,65))
        self.assertEqual(contract['raw_pdo_hex'],'0x00064145');self.assertFalse(contract['measurement'])
        self.assertFalse(result['ports'][1]['available'])

    def test_unplug_and_invalid_bit_suppress_stale_nonzero_cache(self):
        for data in (snapshot(ac=2),snapshot(flags=5)):
            result=pd_contract.decode(data)
            self.assertTrue(all(p['contract'] is None for p in result['ports']))
            self.assertIsNone(result['ec_adapter_watts'])

    def test_changed_or_partial_fields_cannot_become_a_contract(self):
        for offset in (4,5,7,9,10):
            data=bytearray(snapshot());data[offset]^=0x10
            self.assertFalse(pd_contract.decode(data)['ports'][0]['available'])
        for data in (bytes(22),bytes(23),b'\x02'+snapshot()[1:],snapshot(ac=255),snapshot(flags=255)):
            with self.assertRaises(OSError):pd_contract.decode(data)
        data=bytearray(snapshot());data[12]=0xc0
        self.assertFalse(pd_contract.decode(data)['ports'][0]['available'])

    def test_second_port_has_separate_contract_and_selection(self):
        result=pd_contract.decode(snapshot(port=2))
        with mock.patch.object(pd_contract,'report',return_value=result):
            self.assertEqual(pd_contract.selected()['connector'],2)
            self.assertEqual(pd_contract.selected(2)['ec_port'],'B')
            with self.assertRaises(OSError):pd_contract.selected(1)
        for connector in (0,3,True):
            with self.assertRaises(ValueError):pd_contract.selected(connector)

    def test_ambiguous_contract_requires_selection(self):
        data=snapshot();result=pd_contract.decode(data[:13]+data[3:13])
        with mock.patch.object(pd_contract,'report',return_value=result):
            with self.assertRaises(OSError) as error:pd_contract.selected()
            self.assertEqual(error.exception.errno,errno.EBUSY)
            self.assertEqual(pd_contract.selected(1)['connector'],1)

    def test_typed_read_and_original_contract_api_return_real_pdo(self):
        with tempfile.TemporaryDirectory() as temp,mock.patch.object(native_oem,'device',return_value=Path(temp)),mock.patch.object(native_oem,'rpc',return_value={'data_hex':snapshot().hex()}) as rpc:
            self.assertEqual(native_oem.call('Adapter_Read_Contract_PDO',{}),0x64145)
            self.assertTrue(compat.needs_root('Adapter_Read_Contract_PDO',{}))
        rpc.assert_called_once_with(12)
        for args in ({'connector':True},{'connector':3},{'address':0xab1}):
            with self.assertRaises(ValueError):compat.validate('Adapter_Read_Contract_PDO',args)

    def test_public_monitor_and_power_need_no_privileged_rpc(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);(path/'pd_contract').write_text(json.dumps({'schema':1,'data_hex':snapshot().hex()}))
            (path/'power1_input').write_text('28500000')
            with mock.patch.object(native_oem,'device',return_value=path),mock.patch.object(native_oem,'rpc') as rpc:
                self.assertEqual(pd_contract.report()['ec_adapter_watts'],65)
                self.assertFalse(compat.needs_root('Adapter_Read_Contract_PDO',{}))
                power=pd_contract.platform_power();self.assertEqual(power['watts'],28.5)
                self.assertTrue(power['measurement']);self.assertFalse(power['independent_usb_c_input_measurement'])
            rpc.assert_not_called()

    def test_stopped_or_missing_power_provider_is_not_zero_draw(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)
            with mock.patch.object(native_oem,'device',return_value=path):
                self.assertFalse(pd_contract.platform_power()['available'])
                for text in ('0','-1','1000000001'):
                    (path/'power1_input').write_text(text)
                    self.assertFalse(pd_contract.platform_power()['available'])

    def test_non_integer_power_text_is_an_unretried_protocol_error(self):
        for text in ('nan\n','','1.5','inf',b'\xff\xfe'):
            naps=[]
            with tempfile.TemporaryDirectory() as temp:
                path=Path(temp)
                (path/'power1_input').write_bytes(text if isinstance(text,bytes) else text.encode())
                with self.subTest(text=text),mock.patch.object(native_oem,'device',return_value=path):
                    power=pd_contract.platform_power(sleep=naps.append)
            self.assertFalse(power['available']);self.assertEqual(power['errno'],errno.EPROTO);self.assertEqual(naps,[])

    def test_idle_reprime_gets_one_measured_retry_without_masking_hard_errors(self):
        for first in (errno.ESTALE,errno.ENODATA,errno.EAGAIN):
            reads=[OSError(first,'reprimed'),'14560000'];naps=[]
            def read(*_):
                value=reads.pop(0)
                if isinstance(value,Exception):raise value
                return value
            with self.subTest(first=first),mock.patch.object(native_oem,'device',return_value=Path('/nonexistent')),mock.patch.object(Path,'read_text',read):
                power=pd_contract.platform_power(sleep=naps.append)
            self.assertEqual(power['watts'],14.56);self.assertEqual(naps,[.12])
        for errors in ([OSError(errno.ESTALE,'a'),OSError(errno.EAGAIN,'b')],[OSError(errno.EIO,'hard')]):
            naps=[];pending=list(errors)
            def read(*_):raise pending.pop(0)
            with mock.patch.object(native_oem,'device',return_value=Path('/nonexistent')),mock.patch.object(Path,'read_text',read):
                power=pd_contract.platform_power(sleep=naps.append)
            self.assertFalse(power['available']);self.assertEqual(power['errno'],errors[-1].errno);self.assertLessEqual(len(naps),1)

    def test_working_cache_does_not_depend_on_broken_ucsi(self):
        result=pd_contract.decode(snapshot())
        with mock.patch.object(pd_contract,'report',return_value=result),mock.patch.object(charger,'ucsi_report',side_effect=OSError(errno.ENODEV,'no UCSI')):
            report=charger.report()
        self.assertTrue(report['ports'][0]['available'])
        self.assertEqual(report['ucsi_diagnostics']['errno'],errno.ENODEV)


if __name__=='__main__':unittest.main()
