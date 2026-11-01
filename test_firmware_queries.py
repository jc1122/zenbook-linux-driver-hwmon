# SPDX-License-Identifier: GPL-2.0-only
import errno
import tempfile
from pathlib import Path
import unittest
from unittest import mock
import api_bridge
import compat
import extra_sensors
import firmware_queries as p
import native_oem


def metadata():
    return {'schema':1,'cached_metadata_only':True,'query_count':3,
        'eeprom_buffer':{'abi':1,'firmware_calls':0,'guard_rejections':0},'queries':{
        name:{'method':method,'device_id':device,'selector':selector,
              'status':-errno.ENODEV if name=='eeprom_version' else 0,
              'raw':p.UNSUPPORTED_METHOD if name=='eeprom_version' else 0,'raw_valid':True}
        for name,(method,device,selector) in p.RECIPES.items()}}


class FirmwareQueryTests(unittest.TestCase):
    def test_public_zero_mask_and_unsupported_eeprom_need_no_root_or_rpc(self):
        with mock.patch.object(p.qualified_ec,'firmware_metadata',return_value=metadata()),mock.patch.object(native_oem,'rpc',side_effect=AssertionError('Unexpected firmware request')),mock.patch('os.geteuid',return_value=1000):
            for name in p.NAMES:self.assertFalse(compat.needs_root(name,{}))
            value=api_bridge.call({'name':'GetSENSOR_WMI_Data'})
            self.assertEqual(value['p_sensor'],'0x0');self.assertEqual(value['raw'],0)
            self.assertTrue(value['cached'])
            with self.assertRaises(OSError) as caught:api_bridge.call({'name':'GetEEPROM_Data'})
            self.assertEqual(caught.exception.errno,errno.EOPNOTSUPP)

    def test_recognized_firmware_return_is_not_a_version_or_epoch_date(self):
        table=p.decode(metadata())['eeprom_table']
        self.assertEqual(table['status'],'firmware_unsupported')
        self.assertEqual(table['version_reply_raw'],0xfffffffe)
        self.assertIsNone(table['value']);self.assertNotIn('M_date',table)

    def test_zero_support_query_alone_cannot_prove_devs_unsupported(self):
        data=metadata();data['queries']['eeprom_version'].update(status=0,raw=8)
        table=p.decode(data)['eeprom_table']
        self.assertEqual(table['support_raw'],0)
        self.assertEqual(table['status'],'version_responded')
        self.assertTrue(table['available']);self.assertFalse(table['data_collected'])

    def test_transport_errors_even_with_a_stale_sentinel_keep_their_errno(self):
        for name in ['eeprom_version','sensor_mask']:
            data=metadata();data['queries'][name].update(status=-errno.EIO,raw=0xfffffffe,raw_valid=False)
            row=p.decode(data)['sensor_mask' if name=='sensor_mask' else 'eeprom_table']
            self.assertEqual(row['status'],'query_failed');self.assertEqual(row['errno'],errno.EIO)

    def test_optional_support_failure_does_not_erase_definite_version_reply(self):
        data=metadata();data['queries']['eeprom_support'].update(status=-errno.EIO,raw=0xffffffff,raw_valid=False)
        table=p.decode(data)['eeprom_table']
        self.assertEqual(table['status'],'firmware_unsupported');self.assertEqual(table['support_query_errno'],errno.EIO)
        data['queries']['eeprom_version'].update(status=0,raw=8)
        with mock.patch.object(p.qualified_ec,'firmware_metadata',return_value=data),mock.patch.object(p.eeprom_table,'collect',return_value={'version':8}) as collect:
            self.assertTrue(compat.needs_root('GetEEPROM_Data',{}))
            self.assertEqual(p.call('GetEEPROM_Data',{}),{'version':8})
        collect.assert_called_once_with(8)

    def test_positive_table_requires_transport_abi_and_privileged_collection(self):
        data=metadata();data['queries']['eeprom_version'].update(status=0,raw=8)
        data.pop('eeprom_buffer')
        with mock.patch.object(p.qualified_ec,'firmware_metadata',return_value=data),mock.patch.object(p.eeprom_table,'collect') as collect:
            self.assertFalse(compat.needs_root('GetEEPROM_Data',{}))
            with self.assertRaises(OSError) as caught:p.call('GetEEPROM_Data',{})
            self.assertEqual(caught.exception.errno,errno.EOPNOTSUPP)
            collect.assert_not_called()
        data['eeprom_buffer']={'abi':1,'firmware_calls':0,'guard_rejections':0}
        with mock.patch.object(p.qualified_ec,'firmware_metadata',return_value=data),mock.patch.object(p.eeprom_table,'collect') as collect,mock.patch('os.geteuid',return_value=1000):
            with self.assertRaises(PermissionError) as caught:api_bridge.call({'name':'GetEEPROM_Data'})
            self.assertEqual(caught.exception.errno,errno.EACCES);collect.assert_not_called()

    def test_invalid_buffer_transport_counters_are_not_a_capability(self):
        variants=[None,{},True,{'abi':2,'firmware_calls':0,'guard_rejections':0},
                  {'abi':1,'firmware_calls':True,'guard_rejections':0},
                  {'abi':1,'firmware_calls':-1,'guard_rejections':0},
                  {'abi':1,'firmware_calls':2**64,'guard_rejections':0}]
        for value in variants:
            if value is None:continue  # Older module: unsupported transport, not corrupt metadata.
            data=metadata();data['eeprom_buffer']=value
            with self.subTest(value=value),self.assertRaises(OSError) as caught:p.decode(data)
            self.assertEqual(caught.exception.errno,errno.EPROTO)

    def test_provider_and_owner_failures_do_not_become_firmware_absence(self):
        for code in [errno.EACCES,errno.EIO,errno.EBUSY,errno.EAGAIN,errno.ENOENT]:
            with self.subTest(code=code),mock.patch.object(p.qualified_ec,'firmware_metadata',side_effect=OSError(code,'Read failed')):
                result=p.report();self.assertFalse(result['provider_available'])
                self.assertTrue(all(result[k]['status']=='provider_unavailable' and result[k]['errno']==code for k in ['eeprom_table','sensor_mask']))

    def test_unknown_schema_and_wrong_recipe_are_rejected(self):
        invalid=[None,[],{}, {**metadata(),'schema':True},{**metadata(),'cached_metadata_only':False},
                 {**metadata(),'query_count':True}]
        for name,key,value in [('eeprom_version','method','DSTS'),('eeprom_version','selector',0xe3),
                               ('sensor_mask','device_id',0x120079),('eeprom_support','device_id',True)]:
            data=metadata();data['queries'][name][key]=value;invalid.append(data)
        for data in invalid:
            with self.subTest(data=data),self.assertRaises(OSError) as caught:p.decode(data)
            self.assertEqual(caught.exception.errno,errno.EPROTO)

    def test_reply_types_and_status_validity_must_agree(self):
        for key,value in [('status',True),('status',1),('status',-4096),('raw',True),('raw',-1),
                          ('raw',2**32),('raw_valid',False),('raw_valid',1)]:
            data=metadata();data['queries']['eeprom_support'][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(OSError):p.decode(data)
        data=metadata();data['queries']['eeprom_version']['status']=0
        with self.assertRaises(OSError):p.decode(data)

    def test_all_ones_mask_is_not_reported_as_real_sensor_state(self):
        data=metadata();data['queries']['sensor_mask']['raw']=0xffffffff
        row=p.decode(data)['sensor_mask'];self.assertFalse(row['available'])
        self.assertEqual(row['errno'],errno.ENODATA)

    def test_nonzero_raw_mask_retains_bits_without_temperature_labels(self):
        data=metadata();data['queries']['sensor_mask']['raw']=0x1234
        row=p.decode(data)['sensor_mask'];self.assertTrue(row['available'])
        self.assertEqual(row['value']['p_sensor'],'0x1234');self.assertNotIn('temperature',row['value'])

    def test_storage_inventory_keeps_unknown_table_availability_on_provider_error(self):
        with tempfile.TemporaryDirectory() as temp,mock.patch.object(p,'report',return_value={'eeprom_table':{'available':False,'status':'provider_unavailable','errno':errno.ENOENT}}):
            result=extra_sensors.firmware_storage(Path(temp)/'missing')
        self.assertEqual(result['storage'],[]);self.assertIsNone(result['asus_eeprom_table_available'])
        self.assertEqual(result['asus_eeprom_table']['errno'],errno.ENOENT)

    def test_arguments_are_rejected_before_provider_access(self):
        with mock.patch.object(p,'report',side_effect=AssertionError('Unexpected access')):
            for name in p.NAMES:
                for args in [{'selector':0xe0},{'device_id':0x60068},[]]:
                    with self.subTest(name=name,args=args),self.assertRaises(ValueError):api_bridge.call({'name':name,'args':args})

    def test_shared_metadata_guard_rechecks_identity_and_ownership_and_bounds_json(self):
        import json
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'name').write_text('zenbook_ec');(root/'pwm1_enable').write_text('2')
            cache=root/'firmware_diagnostics';cache.write_text(json.dumps(metadata()))
            with mock.patch.object(p.qualified_ec.native_oem,'device',return_value=root),mock.patch.object(p.qualified_ec,'snapshot'):
                self.assertEqual(p.qualified_ec.firmware_metadata(),metadata())
                for content,code in [('[]',errno.EPROTO),('{',errno.EPROTO),(' '*16385,errno.EOVERFLOW)]:
                    cache.write_text(content)
                    with self.subTest(code=code),self.assertRaises(OSError) as caught:p.qualified_ec.firmware_metadata()
                    self.assertEqual(caught.exception.errno,code)
                cache.write_text(json.dumps(metadata()));(root/'pwm1_enable').write_text('1')
                with self.assertRaises(OSError) as caught:p.qualified_ec.firmware_metadata()
                self.assertEqual(caught.exception.errno,errno.EBUSY)
                (root/'pwm1_enable').write_text('2')
            def replace_identity():
                (root/'name').write_text('other_device')
            with mock.patch.object(p.qualified_ec.native_oem,'device',return_value=root),mock.patch.object(p.qualified_ec,'snapshot',side_effect=replace_identity):
                with self.assertRaises(OSError) as caught:p.qualified_ec.firmware_metadata()
                self.assertEqual(caught.exception.errno,errno.ENODEV)


if __name__=='__main__':unittest.main()
