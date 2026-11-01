# SPDX-License-Identifier: GPL-2.0-only
import errno
import json
import unittest
from unittest import mock
import pd_identity as p
from test_pd_contract import snapshot


def identity(response=1,count=3):
 words=[0x18001234,0x12345678,0x56780102]
 return bytes([(response<<6)|count])+b''.join(w.to_bytes(4,'little') for w in words)+bytes(12)
def envelope():
 return {'schema':1,'age_milliseconds':0,'maximum_cache_seconds':5,'contract_hex':snapshot().hex(),
         'ports':[{'connector':1,'sop_hex':identity().hex(),'cable_hex':identity().hex()},
                  {'connector':2,'sop_hex':bytes(25).hex(),'cable_hex':bytes(25).hex()}]}


class PDIdentityTests(unittest.TestCase):
 def test_received_alert_byte_order_zero_and_inactive_suppression(self):
  e=envelope();e['ports'][0]['alert_hex']='00002102';e['ports'][1]['alert_hex']='00000000'
  r=p.decode(e);a=r['ports'][0]['received_alert']
  self.assertEqual((a['raw_ado'],a['alert_type'],a['fixed_battery_change_mask'],a['hot_swappable_battery_change_mask']),(0x02210000,2,2,1))
  with mock.patch.object(p,'report',return_value=r):self.assertEqual(p.call('Adapter_Read_PD_ADO',{'native_alert':True}),0x02210000)
  self.assertTrue(p.received_alert(bytes(4))['available'])
  self.assertFalse(r['ports'][1]['received_alert']['available'])
  e['ports'][1]['alert_hex']='00000002'
  with self.assertRaises(OSError):p.decode(e)
 def test_old_driver_and_malformed_alert_do_not_become_zero(self):
  r=p.decode(envelope());self.assertFalse(r['ports'][0]['received_alert']['available'])
  with mock.patch.object(p,'report',return_value=r),self.assertRaises(OSError) as error:p.call('Adapter_Read_PD_ADO',{'native_alert':True})
  self.assertEqual(error.exception.errno,errno.ENODATA)
  for raw in (bytes(3),b'\x01\x00\x00\x00'):
   with self.assertRaises((OSError,ValueError)):p.received_alert(raw)
 def test_emark_other_requires_the_fifth_received_vdo(self):
  raw=bytearray(identity(count=5));raw[17:21]=(0xdeadbeef).to_bytes(4,'little')
  e=envelope();e['ports'][0]['cable_hex']=raw.hex();r=p.decode(e)
  with mock.patch.object(p,'report',return_value=r):self.assertEqual(p.call('Adapter_Read_PD_Get_Emark_Other',{}),0xdeadbeef)
  with mock.patch.object(p,'report',return_value=p.decode(envelope())),self.assertRaises(OSError) as error:p.call('Adapter_Read_PD_Get_Emark_Other',{})
  self.assertEqual(error.exception.errno,errno.ENODATA)
  import compat
  # 0.79: received PD identity is root-only; the ADO cache-byte query is not.
  self.assertFalse(compat.needs_root('Adapter_Read_PD_ADO',{}))
  self.assertTrue(compat.needs_root('Adapter_Read_PD_ADO',{'native_alert':True}))
  for name in ('Adapter_Read_PD_ADO','Adapter_Read_PD_Get_Emark_Other'):
   self.assertEqual(compat.needs_root(name,{}),name!='Adapter_Read_PD_ADO')
   with self.assertRaises(ValueError):compat.validate(name,{'register':0x75})
 def test_acknowledged_identity_and_native_emark_read(self):
  r=p.decode(envelope());c=r['ports'][0]['cable']
  self.assertTrue(c['available']);self.assertEqual((c['vendor_id'],c['product_id'],c['certification_xid']),(0x1234,0x5678,0x12345678))
  with mock.patch.object(p,'report',return_value=r):self.assertEqual(p.call('Adapter_Read_PD_Get_Emark_PID',{}),0x5678)
 def test_empty_pending_negative_and_busy_are_not_zero_identities(self):
  for code in (0,2,3):
   r=p.identity(identity(code));self.assertFalse(r['available']);self.assertNotIn('vendor_id',r)
  e=envelope();e['ports'][0]['cable_hex']=bytes(25).hex();r=p.decode(e)
  with mock.patch.object(p,'report',return_value=r),self.assertRaises(OSError) as error:p.call('Adapter_Read_PD_Get_Emark_VID',{})
  self.assertEqual(error.exception.errno,errno.ENODATA)
 def test_stale_malformed_and_wrong_port_values_rejected(self):
  for update in [{'age_milliseconds':5001},{'maximum_cache_seconds':30},{'contract_hex':snapshot(ac=2).hex()}]:
   with self.assertRaises(OSError):p.decode({**envelope(),**update})
  with self.assertRaises(OSError):p.identity(identity(count=7))
  with self.assertRaises(OSError):p.identity(identity(count=1))
 def test_non_object_port_records_are_protocol_errors(self):
  for ports in ([1,2],[None,{}],['a','b'],[[],[]]):
   with self.subTest(ports=ports),self.assertRaises(OSError) as caught:p.decode({**envelope(),'ports':ports})
   self.assertEqual(caught.exception.errno,errno.EPROTO)
  with mock.patch.object(p.native_oem,'device',return_value=__import__('pathlib').Path('/test')), \
       mock.patch.object(p.os,'open',return_value=7),mock.patch.object(p.os,'close'), \
       mock.patch.object(p.os,'read',return_value=json.dumps({**envelope(),'ports':[1,2]}).encode()):
   row=p.report()
  self.assertFalse(row['available']);self.assertEqual(row['errno'],errno.EPROTO)
 def test_arbitrary_controller_commands_cannot_be_submitted(self):
  for args in [{'register':4},{'connector':True},{'connector':0}]:
   with self.assertRaises(ValueError):p.call('Adapter_Read_PD_Get_Emark_PID',args)
 def test_original_full_header_quantity_is_available_beside_16_bit_vendor_id(self):
  e=envelope();raw=bytearray.fromhex(e['ports'][0]['cable_hex']);raw[1:5]=(0xa5c01234).to_bytes(4,'little');e['ports'][0]['cable_hex']=raw.hex();r=p.decode(e)
  self.assertEqual(r['ports'][0]['cable']['id_header_raw_vdo'],0xa5c01234)
  # Original reads bank6/3a,39,38,37 and accumulates all four bytes.
  cache={0x37+i:raw[1+i] for i in range(4)};original=0
  for reg in (0x3a,0x39,0x38,0x37):original=(original<<8)|cache[reg]
  with mock.patch.object(p,'report',return_value=r):
   self.assertEqual(p.call('Adapter_Read_PD_Get_Emark_VID',{}),0x1234)
   self.assertEqual(p.call('Adapter_Read_PD_Get_Emark_VID',{'raw_header':False}),0x1234)
   self.assertEqual(p.call('Adapter_Read_PD_Get_Emark_VID',{'raw_header':True}),original)
   self.assertEqual(p.call('Adapter_Read_PD_Get_Emark_VID',{'raw_header':True,'connector':1}),0xa5c01234)
 def test_raw_header_still_requires_a_completed_qualified_cable_identity(self):
  e=envelope();e['ports'][0]['cable_hex']=bytes(25).hex()
  with mock.patch.object(p,'report',return_value=p.decode(e)),self.assertRaises(OSError) as error:
   p.call('Adapter_Read_PD_Get_Emark_VID',{'raw_header':True})
  self.assertEqual(error.exception.errno,errno.ENODATA)
 def test_new_selectors_are_strict_and_checked_before_any_hardware_read(self):
  import compat
  name='Adapter_Read_PD_Get_Emark_VID'
  for args in [{'raw_header':1},{'raw_header':'true'},{'raw_header':None},{'connector':1.0},{'connector':None},{'register':0x49}]:
   with self.subTest(args=args),mock.patch.object(p,'report') as report:
    with self.assertRaises(ValueError):compat.validate(name,args)
    with self.assertRaises(ValueError):p.call(name,args)
    report.assert_not_called()
  for other in set(p.NAMES)-{name}:
   with self.subTest(name=other),self.assertRaises(ValueError):compat.validate(other,{'raw_header':False})
  compat.validate(name,{'raw_header':True});self.assertTrue(compat.needs_root(name,{'raw_header':True}))

 def test_original_alert_byte_is_not_replaced_by_a_different_32bit_quantity(self):
  import adapter_diagnostics as diagnostics
  raw={'max_dd_bank':5,'unsupported_mask':1<<23,'unavailable_mask':0,'adapter_config':-1}
  with mock.patch.object(diagnostics.qualified_ec,'snapshot',return_value=(raw,{})),mock.patch.object(p,'report') as native:
   for args in [{},{'native_alert':False}]:
    with self.assertRaises(OSError) as error:p.call('Adapter_Read_PD_ADO',args)
    self.assertEqual(error.exception.errno,errno.EOPNOTSUPP)
   native.assert_not_called()
  with mock.patch.object(diagnostics.qualified_ec,'snapshot',return_value=({},{})),self.assertRaises(OSError) as error:
   p.call('Adapter_Read_PD_ADO',{})
  self.assertEqual(error.exception.errno,errno.EPROTO)

 def test_native_alert_selectors_are_strict_and_apply_only_to_that_quantity(self):
  import adapter_diagnostics as diagnostics
  for args in [{'native_alert':1},{'native_alert':None},{'native_alert':'true'},{'connector':1},{'native_alert':False,'connector':1}]:
   with self.subTest(args=args),mock.patch.object(p,'report') as read,mock.patch.object(diagnostics.qualified_ec,'snapshot') as legacy:
    with self.assertRaises(ValueError):p.call('Adapter_Read_PD_ADO',args)
    read.assert_not_called();legacy.assert_not_called()
  for name in set(p.NAMES)-{'Adapter_Read_PD_ADO'}:
   with self.assertRaises(ValueError):p.validate(name,{'native_alert':True})

if __name__=='__main__':unittest.main()
