# SPDX-License-Identifier: GPL-2.0-only
"""Typed owner-only requests to the native EC/WMI bridge."""
from pathlib import Path
import errno
import fcntl
import hashlib
import json
import os
import secrets
import struct

MUTATIONS={
 'Adapter_Clear_Power_Data_Flag':(4,'clear adapter power-data flag'),
 'Adapter_Clear_Charger_Data':(5,'clear adapter charger diagnostic data'),
 'Adapter_Set_Notify_Control':(6,'set adapter notification control'),
 'Power_Set_Monitor_PowerDropped':(7,'set power-drop monitor'),
 'Adapter_Read_Power_Data_Flag':(8,'read and clear adapter power-data flag'),
 'Adapter_Read_Charger_Interrupt':(9,'read and clear charger interrupt/data'),
 'WOA_EC_write':(2,'write a validated HealthyTable logical register'),
}
# Owner policy forbids arbitrary EC writes. WOA_EC_write stays refused unless this
# root-owned, non-group/world-writable regular file exists in a root-owned,
# non-group/world-writable directory (checked without following symlinks).
RAW_EC_WRITE_POLICY=Path('/etc/zenbook-hardware/allow-raw-ec-write')
RAW_EC_WRITE_REFUSAL='raw EC writes are disabled; owner policy forbids arbitrary EC writes'
def raw_ec_write_enabled(path=RAW_EC_WRITE_POLICY,trusted_uid=0):
    import stat
    path=Path(path)
    try:dfd=os.open(path.parent,os.O_PATH|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
    except OSError:return False
    try:
        d=os.fstat(dfd)
        if d.st_uid!=trusted_uid or d.st_mode&0o022:return False
        try:f=os.stat(path.name,dir_fd=dfd,follow_symlinks=False)
        except OSError:return False
        return stat.S_ISREG(f.st_mode) and f.st_uid==trusted_uid and not f.st_mode&0o022
    finally:os.close(dfd)
def require_raw_ec_write():
    if not raw_ec_write_enabled():raise PermissionError(errno.EPERM,RAW_EC_WRITE_REFUSAL)
def device():
    rows=[p for p in Path('/sys/class/hwmon').glob('hwmon*') if (p/'name').read_text().strip()=='zenbook_ec']
    if len(rows)!=1:raise RuntimeError('Expected one native Zenbook device.')
    return rows[0]
def integer(value,low,high,label):
    if isinstance(value,bool) or not isinstance(value,(int,str)):raise ValueError(label+' must be an integer.')
    try:value=int(value,0) if isinstance(value,str) else int(value)
    except (ValueError,TypeError):raise ValueError(label+' must be an integer.')
    if not low<=value<=high:raise ValueError(label+' is outside the supported range.')
    return value
def rpc(op,index=0,value=0,apply=False):
    if os.geteuid()!=0:raise PermissionError('Native OEM requests require privilege.')
    lockdir=Path('/run/zenbook-hardware');lockdir.mkdir(exist_ok=True,mode=0o700)
    fd=os.open(lockdir/'oem.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX);p=device();nonce=secrets.randbits(64)
        request=struct.pack('<8I',1,op,index,value,0,int(apply),nonce&0xffffffff,nonce>>32)
        if (p/'oem_request').write_bytes(request)!=32:raise RuntimeError('Incomplete native request.')
        result=json.loads((p/'oem_response').read_text())
        if result.get('nonce')!=nonce or result.get('op')!=op:raise RuntimeError('Concurrent response changed; no result accepted.')
        if result['status']<0:raise OSError(-result['status'],'Native firmware provider rejected operation '+str(op))
        return result
    finally:os.close(fd)
def raw_index(args,write=False):
    required={'address_space','bank','register'}|({'value'} if write else set())
    if not isinstance(args,dict) or set(args)!=required:
        raise ValueError('Use exactly the native address_space, bank, register'+(' and value.' if write else ' fields.'))
    if args.get('address_space')!='healthytable':
        raise ValueError('Specify address_space=healthytable and native bank/register numbers; ARM WMI byte addresses are not interchangeable.')
    bank=integer(args.get('bank'),0,127,'bank');reg=integer(args.get('register'),0,255,'register')
    return (bank<<8)|reg
def mutation_plan(name,args):
    op,description=MUTATIONS[name];index=0;value=0
    if name=='WOA_EC_write':require_raw_ec_write()
    if name=='WOA_EC_write':index=raw_index(args,write=True);value=integer(args.get('value'),0,255,'value')
    elif name in ('Adapter_Set_Notify_Control','Power_Set_Monitor_PowerDropped'):
        value=integer(args.get('value'),0,1,'value')
    plan={'function':name,'description':description,'op':op,'index':index,'value':value,
          'recipe_revision':3 if name=='WOA_EC_write' else 2,
          'model':Path('/sys/class/dmi/id/product_name').read_text().strip(),
          'bios':Path('/sys/class/dmi/id/bios_version').read_text().strip(),
          'applied':False,'requires_explicit_apply':True}
    if name=='WOA_EC_write':
        plan['protocol_recipe']={'address_space':'healthytable','bank':index>>8,'register':index&255,
                                 'wire_bank':0x80|(index>>8),'wire_value':value}
    elif name=='Power_Set_Monitor_PowerDropped':
        plan['protocol_recipe']={'minimum_version':19,'bank':7,'register':9,'encoded_value':(value<<7)|5}
    elif name=='Adapter_Read_Power_Data_Flag':
        plan['protocol_recipe']={'minimum_version':14,'read_bank':6,'read_register':1,
            'clear_versions14_to23':{'register':1,'value':0},
            'clear_version24_or_newer':{'register':0x35,'value':'the complete flag byte just read'}}
    elif name=='Adapter_Set_Notify_Control':plan['protocol_recipe']={'minimum_version':23,'bank':6,'register':0x36,'encoded_value':value}
    plan['expected_sha256']=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()
    return plan
def call(name,args,apply=False,expected_sha256=None):
    if name=='Adapter_Read_Contract_PDO':
        import pd_contract
        return int(pd_contract.selected(args.get('connector'))['contract']['raw_pdo_hex'],16)
    if name in MUTATIONS:
        plan=mutation_plan(name,args)
        if not apply:return plan
        if expected_sha256!=plan['expected_sha256']:raise RuntimeError('Apply requires the exact digest of the reviewed OEM operation plan.')
        if name=='WOA_EC_write':require_raw_ec_write()
        result=rpc(plan['op'],plan['index'],plan['value'],True)
        return {**plan,'applied':True,'transport_completed':True,'firmware_acknowledged':None,
                'readback_verified':False,'completion_scope':'EC transport completed; this fixed write has no firmware reply.',
                'result':result}
    if name=='WOA_EC_read':return rpc(1,raw_index(args))['value']
    if name=='Adapter_Read_PD_IC_PN':
        raw=bytes.fromhex(rpc(3)['data_hex'])
        return {'raw_hex':raw.hex(),'text':raw.rstrip(b'\0').decode('ascii',errors='replace')}
    if name in ('GetEEPROM_Data','GetSENSOR_WMI_Data'):
        import firmware_queries
        return firmware_queries.call(name,args)
    if name=='CPU_ReadCpuVoltage':
        p=device()/'in6_input'
        if p.exists():
            value=int(p.read_text())
            return {'millivolts':value,'source':'Intel MSR_PERF_STATUS[47:32] / 8192',
                    'kind':'CPU-reported P-state voltage','independent_rail_measurement':False}
        raw=rpc(10,0x120079,0)['value']
        if not raw&0x10000:raise OSError(errno.ENODEV,'Firmware does not advertise CPU voltage.')
        return {'millivolts':raw&0xffff,'raw':raw,'source':'ASUS DSTS'}
    raise KeyError(name)
