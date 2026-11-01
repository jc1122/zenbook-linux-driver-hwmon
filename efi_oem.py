# SPDX-License-Identifier: GPL-2.0-only
"""ASUS GPNV OEM records through efivarfs; no generic EFI-variable writer.

Offsets and GUIDs are recovered from a locally installed AsusWinIO64.dll.
Every write is a fixed-field, expected-revision update retaining attributes.
"""
from pathlib import Path
import datetime
import errno
import fcntl
import hashlib
import json
import os
import re
import stat
import struct
import uuid
import array

ASUS_GUID='91b89306-5bac-4ae0-aab3-207ec12e989b'
NEW_CNFG_GUID='329d6974-be41-4325-b2fd-ad693193525b'
OEM_GUID='f952fc4a-5222-4dbb-9302-c9b9dd9d7c9c'
VARIABLES={'CNFG':(ASUS_GUID,256),'MFG0':(ASUS_GUID,256),
           'HEAL':(ASUS_GUID,256),'OemBDConf':(OEM_GUID,1)}
FIELDS={'activated_time':('CNFG',32,19),'manufactured_time':('MFG0',148,23),
        'random_uuid':('CNFG',0,16),'os_language':('CNFG',112,8),
        'clear_csc_repair_flag':('OemBDConf',0,1)}
def digest(raw):return hashlib.sha256(raw).hexdigest()

def encode_field(field,value):
    if field not in FIELDS:raise ValueError('Unknown OEM field.')
    size=FIELDS[field][2]
    if field=='clear_csc_repair_flag':
        if value is not None and value not in (True,1,'clear'):raise ValueError('CSC clear only accepts the fixed clear action.')
        return b'\x77'
    if field=='random_uuid':
        if not isinstance(value,str) or not re.fullmatch(r'[0-9a-fA-F]{32}',value):
            raise ValueError('Random UUID requires exactly 16 raw bytes as 32 hexadecimal characters.')
        return bytes.fromhex(value)
    if not isinstance(value,str):raise ValueError('OEM field value must be a string.')
    if field in ('activated_time','manufactured_time'):
        fmt='%Y-%m-%d %H:%M:%S' if field=='activated_time' else '%Y-%m-%d %H:%M:%S.%f'
        expected=19 if field=='activated_time' else 23
        if len(value)!=expected:raise ValueError('Timestamp has the wrong fixed field length.')
        datetime.datetime.strptime(value,fmt)
    elif not re.fullmatch(r'[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,4})?',value):
        raise ValueError('Language must be a short locale tag, for example pl-PL.')
    encoded=value.encode('ascii')
    if len(encoded)>size:raise ValueError('OEM field value is too long.')
    return encoded.ljust(size,b'\0')

class Firmware:
    def __init__(self,root='/sys/firmware/efi/efivars',backup_root='/var/lib/zenbook-hardware/firmware-backups'):
        self.root=Path(root);self.backup_root=Path(backup_root)

    def variable(self,name):
        if name not in VARIABLES:raise ValueError('Variable is outside the fixed ASUS OEM set.')
        guid,size=VARIABLES[name]
        if name=='CNFG' and list(Path('/sys/bus/acpi/devices').glob('ASUS2025*')):
            guid=NEW_CNFG_GUID
        p=self.root/(name+'-'+guid)
        if p.is_symlink():raise RuntimeError('Refusing an EFI-variable symlink.')
        return p,size

    def read(self,name):
        p,size=self.variable(name)
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
        try:raw=os.read(fd,size+5)
        finally:os.close(fd)
        if len(raw)!=size+4:raise RuntimeError('Unexpected ASUS record length; no compatible layout established.')
        attributes=struct.unpack('<I',raw[:4])[0]
        if attributes & ~0x7f or not attributes & 2:raise RuntimeError('Unexpected EFI attributes.')
        return p,raw

    @staticmethod
    def get_flags(fd):
        flags=array.array('I',[0])
        try:fcntl.ioctl(fd,0x80086601,flags,True)
        except OSError as e:
            if e.errno not in (errno.ENOTTY,errno.EOPNOTSUPP):raise
        return flags[0]

    @staticmethod
    def set_flags(fd,flags):fcntl.ioctl(fd,0x40086602,array.array('I',[flags]))

    def get(self,name):
        if name in FIELDS:
            var,offset,size=FIELDS[name];p,raw=self.read(var);value=raw[4+offset:4+offset+size]
            result={'variable':p.name,'field':name,'offset':offset,'length':size,'record_sha256':digest(raw)}
            if name=='random_uuid':result['raw_hex']=value.hex()
            elif name=='clear_csc_repair_flag':result['raw_value']=value[0]
            else:result['value']=value.rstrip(b'\0').decode('ascii',errors='replace')
            return result
        if name=='csc_repair_flag':
            p,raw=self.read('HEAL');return {'variable':p.name,'value':raw[5],'record_sha256':digest(raw)}
        p,raw=self.read(name)
        return {'variable':p.name,'attributes':struct.unpack('<I',raw[:4])[0],
                'data_hex':raw[4:].hex(),'length':len(raw)-4,'record_sha256':digest(raw)}

    def plan(self,field,value):
        encoded=encode_field(field,value);name,offset,size=FIELDS[field]
        p,raw=self.read(name);after=raw[:4+offset]+encoded+raw[4+offset+size:]
        if len(after)!=len(raw) or len(encoded)!=size:
            raise ValueError('Factory field plan would change the EFI record length; refusing the write plan.')
        changed=[i-4 for i,(a,b) in enumerate(zip(raw,after)) if a!=b]
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
        try:immutable=bool(self.get_flags(fd)&0x10)
        finally:os.close(fd)
        return {'operation':field,'variable':p.name,'expected_sha256':digest(raw),
                'result_sha256':digest(after),'attributes':struct.unpack('<I',raw[:4])[0],
                'field_offset':offset,'field_length':size,'changed_data_offsets':changed,
                'before_field_hex':raw[4+offset:4+offset+size].hex(),
                'after_field_hex':encoded.hex(),'will_write':bool(changed) or field=='clear_csc_repair_flag',
                'immutable':immutable,'immutable_removal_requires_opt_in':immutable,
                'applied':False},raw,after

    def backup(self,p,raw):
        self.backup_root.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.backup_root.is_symlink():raise RuntimeError('Refusing backup-directory symlink.')
        stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        target=self.backup_root/(stamp+'-'+p.name+'-'+digest(raw)+'.bin')
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:
            if os.write(fd,raw)!=len(raw):raise OSError('Incomplete backup.')
            os.fsync(fd)
        finally:os.close(fd)
        if target.read_bytes()!=raw:raise RuntimeError('Backup readback failed.')
        return target

    def apply(self,field,value,expected_sha256,allow_immutable=False):
        if not re.fullmatch('[0-9a-f]{64}',expected_sha256 or ''):
            raise ValueError('Apply requires the exact SHA-256 from the reviewed plan.')
        plan,raw,after=self.plan(field,value)
        if digest(raw)!=expected_sha256:raise RuntimeError('Firmware record changed; create a fresh plan.')
        if not plan['will_write']:return {**plan,'applied':False,'unchanged':True}
        name=FIELDS[field][0];p,_=self.variable(name)
        # Never recreate a missing variable. An immutable record is unlocked only
        # when explicitly requested, after a verified private backup, then relocked.
        guard=os.open(p,os.O_RDONLY|os.O_NOFOLLOW);original_flags=self.get_flags(guard)
        unlocked=False
        try:
            if original_flags & 0x10 and not allow_immutable:
                raise PermissionError('EFI record is immutable. The reviewed apply must explicitly request allow_immutable=true.')
            backup=self.backup(p,raw)
            if original_flags & 0x10:
                self.set_flags(guard,original_flags & ~0x10);unlocked=True
            fd=os.open(p,os.O_WRONLY|os.O_NOFOLLOW)
            try:
                if self.read(name)[1]!=raw:raise RuntimeError('Record changed immediately before writing.')
                if os.write(fd,after)!=len(after):raise OSError('Incomplete firmware-variable write.')
            finally:os.close(fd)
        finally:
            try:
                if unlocked:
                    self.set_flags(guard,original_flags)
                    if self.get_flags(guard)!=original_flags:raise RuntimeError('Original EFI file protection flags did not read back.')
            finally:os.close(guard)
        if self.read(name)[1]!=after:
            raise RuntimeError('Firmware readback differs; original backup retained at '+str(backup))
        return {**plan,'applied':True,'backup':str(backup),'readback_verified':True,
                'original_immutable_flag_restored':bool(original_flags & 0x10)}

READS={'GPNV_Get_ActivatedTime':'activated_time','GPNV_Get_ManufacturedTime':'manufactured_time',
       'GPNV_Get_RandomUUID':'random_uuid','GPNV_Get_HEAL_table':'HEAL',
       'GPNV_Get_HEAL_table_CSC_Repair_Flag':'csc_repair_flag'}
WRITES={'GPNV_Set_ActivatedTime':'activated_time','GPNV_Set_ManufacturedTime':'manufactured_time',
        'GPNV_Set_RandomUUID':'random_uuid','GPNV_Clear_CSC_Repair_Flag':'clear_csc_repair_flag',
        'Update_AsusOsLanguage':'os_language'}

def call(name,args,apply=False,expected_sha256=None,firmware=None):
    fw=firmware or Firmware()
    if name in READS:return fw.get(READS[name])
    if name not in WRITES:raise ValueError('Unknown GPNV operation.')
    field=WRITES[name];value=args.get('value')
    if not apply:return fw.plan(field,value)[0]
    if Path('/sys/class/dmi/id/product_name').read_text().strip()!='Zenbook Flip UP3404VA_UP3404VA' or Path('/sys/class/dmi/id/bios_version').read_text().strip()!='UP3404VA.301':
        raise RuntimeError('OEM writes require the verified UP3404VA.301 layout.')
    lockdir=Path('/run/zenbook-hardware');lockdir.mkdir(exist_ok=True,mode=0o700)
    fd=os.open(lockdir/'firmware.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX)
        return fw.apply(field,value,expected_sha256,args.get('allow_immutable',False))
    finally:os.close(fd)
