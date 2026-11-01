# SPDX-License-Identifier: GPL-2.0-only
"""Read-only received USB-PD identities; no discovery/power command is issued."""
import errno
import json
import os
import native_oem
import pd_contract

NAMES={'Adapter_Read_PD_Get_Emark_VID':'vendor_id','Adapter_Read_PD_Get_Emark_PID':'product_id',
       'Adapter_Read_PD_Get_Emark_XID':'certification_xid','Adapter_Read_PD_Get_Emark_Other':'other_raw_vdo',
       'Adapter_Read_PD_ADO':'received_alert'}


def identity(raw):
 if len(raw)!=25:raise ValueError('Invalid received identity length.')
 status=raw[0];count=status&7;response=status>>6
 if status&0x38 or count>6:raise OSError(errno.EPROTO,'Invalid identity response status/count.')
 states=['not_requested_or_pending','acknowledged','not_supported_or_timed_out','busy']
 row={'available':False,'response':states[response],'valid_vdo_count':count}
 if response!=1:return row
 if count<3:raise OSError(errno.EPROTO,'Incomplete identity acknowledgement.')
 words=[int.from_bytes(raw[1+4*i:5+4*i],'little') for i in range(count)]
 vid=words[0]&65535;pid=words[2]>>16
 if vid in (0,65535):raise OSError(errno.EPROTO,'Invalid identity vendor ID.')
 result={**row,'available':True,'vendor_id':vid,'id_header_raw_vdo':words[0],'product_id':pid,'certification_xid':words[1],
         'device_revision_bcd':words[2]&65535,'product_type_bits':(words[0]>>27)&7,'raw_vdos_hex':[f'0x{w:08x}' for w in words]}
 # ASUS's opaque "Other" field is four dwords after its header/VID slot.
 # Preserve that raw VDO; do not treat an absent or shorter ACK as zero.
 if count>=5:result['other_raw_vdo']=words[4]
 return result


def received_alert(raw):
 if len(raw)!=4:raise ValueError('Invalid received alert length.')
 value=int.from_bytes(raw,'little')
 if value&65535:raise OSError(errno.EPROTO,'Received ADO reserved bits are nonzero.')
 return {'available':True,'raw_ado':value,'raw_ado_hex':f'0x{value:08x}','alert_type':value>>24,
         'fixed_battery_change_mask':(value>>20)&15,'hot_swappable_battery_change_mask':(value>>16)&15,
         'note':'Last received Alert Data Object. Zero means no alert recorded; this is not a current protection/alarm reading.'}


def decode(data):
 if not isinstance(data,dict) or data.get('schema')!=1 or data.get('maximum_cache_seconds')!=5 or type(data.get('age_milliseconds')) is not int or not 0<=data['age_milliseconds']<=5000:
  raise OSError(errno.ESTALE,'Invalid PD identity schema/cache age.')
 contract=pd_contract.decode(bytes.fromhex(data['contract_hex']))
 if not isinstance(data.get('ports'),list) or len(data['ports'])!=2:raise ValueError('Invalid identity port list.')
 rows=[]
 for i,record in enumerate(data['ports']):
  if not isinstance(record,dict):raise OSError(errno.EPROTO,'Identity port record is not a JSON object.')
  if record.get('connector')!=i+1:raise ValueError('Invalid identity connector mapping.')
  row={'connector':i+1,'active_contract':contract['ports'][i]['available']}
  for field,key in [('partner','sop_hex'),('cable','cable_hex')]:
   raw=bytes.fromhex(record[key])
   if len(raw)!=25:raise ValueError('Invalid identity payload length.')
   if not row['active_contract']:
    if any(raw):raise OSError(errno.EPROTO,'Inactive port exposed stale identity.')
    row[field]={'available':False,'response':'no_active_charger_contract'}
   else:row[field]=identity(raw)
  if 'alert_hex' not in record:
   row['received_alert']={'available':False,'reason':'requires_driver_0.15_or_later'}
  else:
   raw=bytes.fromhex(record['alert_hex'])
   if len(raw)!=4:raise ValueError('Invalid received alert payload length.')
   if not row['active_contract'] and any(raw):raise OSError(errno.EPROTO,'Inactive port exposed stale received alert.')
   row['received_alert']=received_alert(raw) if row['active_contract'] else {'available':False,'reason':'no_active_charger_contract'}
  rows.append(row)
 return {'available':True,'ports':rows,'age_milliseconds':data['age_milliseconds'],'maximum_cache_seconds':5,
         'source':'TPS65994BF fixed received-identity registers via OEM combined-read broker',
         'note':'No discovery, reset or role command is sent. An empty/pending identity is unavailable, never inferred from source PDOs or charger branding.'}


def report():
 try:
  fd=os.open(native_oem.device()/'pd_identity',os.O_RDONLY|os.O_CLOEXEC)
  try:data=json.loads(os.read(fd,8192))
  finally:os.close(fd)
  return decode(data)
 except (OSError,ValueError,TypeError,KeyError,RuntimeError) as error:
  return {'available':False,'ports':[],'errno':getattr(error,'errno',None) or errno.EPROTO,'error':str(error)}


def validate(name,args):
 if name not in NAMES:raise ValueError('Unknown received PD identity query.')
 allowed={'connector','raw_header'} if name=='Adapter_Read_PD_Get_Emark_VID' else {'connector','native_alert'} if name=='Adapter_Read_PD_ADO' else {'connector'}
 if not isinstance(args,dict) or set(args)-allowed:raise ValueError('Only a connector selector and optional VID raw_header boolean are accepted.')
 if 'connector' in args and (type(args['connector']) is not int or args['connector'] not in (1,2)):raise ValueError('connector must be integer 1 or 2.')
 if 'raw_header' in args and type(args['raw_header']) is not bool:raise ValueError('raw_header must be a boolean.')
 if 'native_alert' in args and type(args['native_alert']) is not bool:raise ValueError('native_alert must be a boolean.')
 if name=='Adapter_Read_PD_ADO' and not args.get('native_alert',False) and 'connector' in args:
  raise ValueError('connector applies only to native_alert=true; the original cache-byte query has no connector selector.')


def call(name,args):
 validate(name,args)
 if name=='Adapter_Read_PD_ADO' and not args.get('native_alert',False):
  import adapter_diagnostics
  return adapter_diagnostics.legacy_received_alert()
 connector=args.get('connector')
 data=report()
 if not data['available']:raise OSError(data['errno'],data['error'])
 rows=[r for r in data['ports'] if r['active_contract'] and (connector is None or r['connector']==connector)]
 if len(rows)!=1:raise OSError(errno.ENODEV if not rows else errno.EBUSY,'Select one active charger connector.')
 if name=='Adapter_Read_PD_ADO':
  alert=rows[0]['received_alert']
  if not alert['available']:raise OSError(errno.ENODATA,'Received PD alert reader is unavailable: '+alert['reason'])
  return alert['raw_ado']
 cable=rows[0]['cable']
 if not cable['available']:raise OSError(errno.ENODATA,'Controller has no completed cable identity: '+cable['response'])
 if args.get('raw_header',False):return cable['id_header_raw_vdo']
 if NAMES[name] not in cable:raise OSError(errno.ENODATA,'Acknowledged cable identity omits the requested VDO.')
 return cable[NAMES[name]]
