# SPDX-License-Identifier: GPL-2.0-only
import errno
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import compat
import pd_sources
from test_pd_contract import snapshot


def sources(port=1):
    record=bytes([4])+b''.join(w.to_bytes(4,'little') for w in (0x0a01912c,0x2d12c,0x4b12c,0x64145))+bytes(12)
    return snapshot(port=port)+(record+bytes(29) if port==1 else bytes(29)+record)


OBJECTS=(0x1912c,0x2d12c,0x4b12c,0x64145,0x40019234,0x800abcde,0xc0dc213c)
def complete_sources(count=7,port=1,active_index=0):
    word=OBJECTS[active_index]
    fixed=word>>30==0
    mv=((word>>10)&1023)*50 if fixed else 0
    ma=(word&1023)*10 if fixed else 0
    watts=round(mv*ma/1_000_000)
    contract=bytes([0x45,watts])+mv.to_bytes(2,'little')+ma.to_bytes(2,'little')+word.to_bytes(4,'little')
    header=bytes([1,3,watts])+(contract+bytes(10) if port==1 else bytes(10)+contract)
    record=bytes([count])+b''.join(w.to_bytes(4,'little') for w in OBJECTS[:count])+bytes(28-4*count)
    return header+(record+bytes(29) if port==1 else bytes(29)+record)


class PDSourcesTests(unittest.TestCase):
    def test_all_seven_slots_counts_and_raw_supply_types_on_each_port(self):
        for port in (1,2):
            for count in range(1,8):
                result=pd_sources.decode(complete_sources(count,port))
                profiles=result['ports'][port-1]['profiles']
                self.assertEqual([int(p['raw_pdo_hex'],16) for p in profiles],list(OBJECTS[:count]))
                for p in profiles:
                    if p['supply_type_bits']:
                        self.assertEqual(p['type'],'unqualified_nonfixed')
                        self.assertNotIn('power_limit_watts',p)
                with mock.patch.object(pd_sources,'report',return_value=result):
                    for i in range(7):
                        if i<count:
                            self.assertEqual(compat.dispatch('Adapter_Read_PDO',{'index':i,'connector':port}),OBJECTS[i])
                            self.assertEqual(compat.dispatch(f'Adapter_Read_PDO{i+1}',{'connector':port}),OBJECTS[i])
                        else:
                            with self.assertRaises(OSError) as error:compat.dispatch(f'Adapter_Read_PDO{i+1}',{})
                            self.assertEqual(error.exception.errno,errno.ENODATA)

    def test_raw_source_objects_remain_readable_with_unconverted_nonfixed_active_contract(self):
        for port in (1,2):
            for active in (4,5,6):
                result=pd_sources.decode(complete_sources(7,port,active))
                row=result['ports'][port-1]
                self.assertTrue(row['available']);self.assertEqual(row['active_contract_format'],'unqualified_nonfixed')
                with mock.patch.object(pd_sources,'report',return_value=result):
                    self.assertEqual(compat.dispatch('Adapter_Read_PDO7',{'connector':port}),OBJECTS[6])
                self.assertNotIn('power_limit_watts',row)

    def test_both_active_ports_require_explicit_connector_and_keep_distinct_counts(self):
        left=complete_sources(7,1);right=complete_sources(1,2)
        data=left[:13]+right[13:23]+left[23:52]+right[52:]
        result=pd_sources.decode(data)
        with mock.patch.object(pd_sources,'report',return_value=result):
            with self.assertRaises(OSError) as error:pd_sources.selected()
            self.assertEqual(error.exception.errno,errno.EBUSY)
            self.assertEqual(compat.dispatch('Adapter_Read_PDO7',{'connector':1}),OBJECTS[6])
            with self.assertRaises(OSError) as error:compat.dispatch('Adapter_Read_PDO7',{'connector':2})
            self.assertEqual(error.exception.errno,errno.ENODATA)

    def test_inconsistent_active_fixed_contract_and_nonmember_raw_contract_are_errors(self):
        for port in (1,2):
            offset=3+10*(port-1)
            fixed=bytearray(complete_sources(7,port));fixed[offset+2]^=1
            with self.assertRaises(OSError):pd_sources.decode(fixed)
            raw=bytearray(complete_sources(7,port,6));raw[offset+6:offset+10]=(0xc1234567).to_bytes(4,'little')
            with self.assertRaises(OSError):pd_sources.decode(raw)

    def test_public_envelope_requires_exact_schema_and_complete_packet(self):
        valid={'schema':1,'maximum_cache_seconds':2,'data_hex':complete_sources().hex()}
        with tempfile.TemporaryDirectory() as temp,mock.patch.object(pd_sources.native_oem,'device',return_value=Path(temp)):
            path=Path(temp)/'pd_source_caps';path.write_text(json.dumps(valid));self.assertTrue(pd_sources.report()['available'])
            for data in (None,[],{**valid,'schema':True},{**valid,'maximum_cache_seconds':True},
                         {**valid,'data_hex':3},{**valid,'data_hex':valid['data_hex'][:-2]},
                         {**valid,'data_hex':'00 '*81},{**valid,'data_hex':'g'*162}):
                path.write_text(json.dumps(data));result=pd_sources.report()
                self.assertFalse(result['available']);self.assertEqual(result['errno'],errno.EPROTO)
            path.unlink();self.assertEqual(pd_sources.report()['errno'],errno.ENOENT)

    def test_complete_fourth_pdo_and_each_port(self):
        for port in (1,2):
            result=pd_sources.decode(sources(port))
            active=result['ports'][port-1]
            self.assertTrue(active['available']);self.assertFalse(result['ports'][2-port]['available'])
            self.assertEqual([p['voltage_volts'] for p in active['profiles']],[5,9,15,20])
            self.assertEqual(active['profiles'][3]['current_limit_amperes'],3.25)
            with mock.patch.object(pd_sources,'report',return_value=result):
                self.assertEqual(compat.dispatch('Adapter_Read_PDO4',{}),0x64145)
                self.assertEqual(compat.dispatch('Adapter_Read_PDO',{'index':0,'connector':port}),0x0a01912c)
                with self.assertRaises(OSError) as error:compat.dispatch('Adapter_Read_PDO5',{})
                self.assertEqual(error.exception.errno,errno.ENODATA)
                with self.assertRaises(OSError):pd_sources.selected(3-port)

    def test_partial_stale_and_inconsistent_snapshots_rejected(self):
        for offset,value in ((0,2),(23,8),(26,0),(40,1),(52,4),(37,0)):
            data=bytearray(sources());data[offset]=value
            with self.subTest(offset=offset),self.assertRaises(OSError):pd_sources.decode(data)
        data=bytearray(sources());data[1]=2
        with self.assertRaises(OSError):pd_sources.decode(data)
        data[23:]=bytes(58)
        self.assertFalse(pd_sources.decode(data)['available'])
        with self.assertRaises(OSError):pd_sources.decode(sources()[:-1])

    def test_public_api_selectors_are_bounded(self):
        for name in pd_sources.NAMES:
            self.assertFalse(compat.needs_root(name,{}))
            for args in ({'connector':True},{'connector':0},{'address':0xb32}):
                if name=='Adapter_Read_PDO':args={**args,'index':0}
                with self.assertRaises(ValueError):compat.validate(name,args)
        for index in (-1,7,True):
            with self.assertRaises(ValueError):compat.validate('Adapter_Read_PDO',{'index':index})


if __name__=='__main__':unittest.main()
