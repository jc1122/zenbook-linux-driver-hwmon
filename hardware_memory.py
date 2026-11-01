# SPDX-License-Identifier: GPL-2.0-only
"""Firmware-declared installed memory, separate from OS-usable memory.

Only Type 17 sysfs records are read. No /dev/mem fallback or SPD transactions.
Offsets/units: DMTF DSP0134 3.8, sections 7.18 and 7.18.4/5/14.
https://www.dmtf.org/sites/default/files/standards/documents/DSP0134_3.8.0.pdf
Serial numbers and asset tags are deliberately not decoded or returned.
"""
from pathlib import Path
import errno
import re
import struct

NAMES={'WMIGetMemInfo','WMIGetMemSize','WMIGetMemFrequency','WMIGetMemManufacture','WMIGetMemModel'}
SOURCE='Linux SMBIOS Type 17; firmware-declared installed memory, not OS-usable memory or measured clocks'
MAX_RECORD=65536


def validate(name,args):
    if name not in NAMES:raise KeyError(name)
    if not isinstance(args,dict) or args:raise ValueError('This installed-memory query takes no arguments.')


def decode(raw):
    if (not isinstance(raw,bytes) or not 0x17<=len(raw)<=MAX_RECORD or raw[0]!=17 or
        not 0x15<=raw[1]<=len(raw)-2):
        raise OSError(errno.EPROTO,'Invalid SMBIOS memory-device frame.')
    length=raw[1];tail=raw[length:]
    if tail.find(b'\0\0')!=len(tail)-2:raise OSError(errno.EPROTO,'Invalid SMBIOS string terminator or trailing data.')
    strings=tail[:-2].split(b'\0') if len(tail)>2 else []
    errors={}
    def field(key,offset,width=1):
        if offset+width>length:raise OSError(errno.ENODATA,'SMBIOS field is not supplied in this record version.')
        return int.from_bytes(raw[offset:offset+width],'little')
    def string(key,offset):
        index=field(key,offset)
        if index==0:raise OSError(errno.ENODATA,'SMBIOS string is not supplied.')
        if index>len(strings):raise OSError(errno.EPROTO,'SMBIOS string index is outside the record.')
        try:value=strings[index-1].decode('utf-8',errors='strict').strip()
        except UnicodeDecodeError:raise OSError(errno.EPROTO,'Invalid SMBIOS UTF-8 string.') from None
        if not value or value.casefold() in {'unknown','not specified','not provided','none','n/a','to be filled by o.e.m.'}:
            raise OSError(errno.ENODATA,'SMBIOS string contains no known value.')
        if any(ord(c)<32 or ord(c)==127 for c in value):raise OSError(errno.EPROTO,'Invalid SMBIOS string control character.')
        return value
    def speed(key,offset,extended):
        value=field(key,offset,2)
        if value==0xffff:
            value=field(key,extended,4)
            if value&0x80000000:raise OSError(errno.EPROTO,'Reserved SMBIOS speed bit is set.')
            if 0<value<0xffff:raise OSError(errno.EPROTO,'Invalid SMBIOS extended data rate.')
        if value==0:raise OSError(errno.ENODATA,'SMBIOS memory data rate is unknown.')
        return value
    def capacity():
        value=field('capacity_bytes',0x0c,2)
        if value==0xffff:raise OSError(errno.ENODATA,'SMBIOS installed capacity is unknown.')
        if value==0x7fff:
            value=field('capacity_bytes',0x1c,4)
            if value&0x80000000 or value<0x7fff:raise OSError(errno.EPROTO,'Invalid SMBIOS extended capacity.')
            return value*1024**2
        return (value&0x7fff)*(1024 if value&0x8000 else 1024**2)
    size=field('capacity_bytes',0x0c,2)
    row={'available':True,'handle':struct.unpack_from('<H',raw,2)[0],
         'populated':size!=0,'field_errors':errors,'speed_units':'MT/s','source':SOURCE}
    for key,fn in [('capacity_bytes',capacity),('locator',lambda:string('locator',0x10)),
                   ('bank_locator',lambda:string('bank_locator',0x11)),
                   ('manufacturer',lambda:string('manufacturer',0x17)),
                   ('part_number',lambda:string('part_number',0x1a)),
                   ('speed_mt_s',lambda:speed('speed_mt_s',0x15,0x54)),
                   ('configured_speed_mt_s',lambda:speed('configured_speed_mt_s',0x20,0x58))]:
        try:row[key]=fn()
        except OSError as error:
            row[key]=None;errors[key]={'errno':error.errno,'error':str(error)}
    # A nonzero size with an empty numeric magnitude is not an empty socket.
    if row['populated'] and row['capacity_bytes']==0:
        row['capacity_bytes']=None;errors['capacity_bytes']={'errno':errno.EPROTO,'error':'Invalid zero installed capacity encoding.'}
    return row


def paths(root):
    found=sorted(p for p in root.iterdir() if re.fullmatch(r'17-[0-9]+',p.name))
    if len(found)>1024:raise OSError(errno.EOVERFLOW,'SMBIOS memory-device census exceeds the supported bound.')
    return found


def identity(path):
    st=path.stat();return st.st_dev,st.st_ino


def read(path):
    with (path/'raw').open('rb') as stream:raw=stream.read(MAX_RECORD+1)
    if len(raw)>MAX_RECORD:raise OSError(errno.EOVERFLOW,'SMBIOS memory record exceeds the supported bound.')
    return raw


def unknown(path,error):
    return {'device':path.name,'available':False,'populated':None,'capacity_bytes':None,
            'errno':error.errno or errno.EIO,'error':str(error),'source':SOURCE}


def report(root=Path('/sys/firmware/dmi/entries')):
    objects=paths(root)
    if not objects:raise OSError(errno.ENODATA,'No SMBIOS memory-device records are available.')
    rows=[];guards=[]
    for path in objects:
        try:
            before=identity(path);raw=read(path);row={'device':path.name,**decode(raw)}
            guards.append((path,before,raw,len(rows)))
        except OSError as error:row=unknown(path,error)
        rows.append(row)
    if objects!=paths(root):raise OSError(errno.EAGAIN,'SMBIOS memory-device census changed during sampling.')
    for path,before,raw,index in guards:
        try:
            if identity(path)!=before or read(path)!=raw:raise OSError(errno.EAGAIN,'SMBIOS memory-device record changed during sampling.')
        except OSError as error:rows[index]=unknown(path,error)
    if objects!=paths(root):raise OSError(errno.EAGAIN,'SMBIOS memory-device census changed during final check.')
    handles={}
    for index,row in enumerate(rows):
        if row['available']:handles.setdefault(row['handle'],[]).append(index)
    for indices in handles.values():
        if len(indices)>1:
            for index in indices:rows[index]=unknown(objects[index],OSError(errno.EPROTO,'Duplicate SMBIOS memory-device handle.'))
    complete=all(r['available'] and r['capacity_bytes'] is not None for r in rows) and any(r['populated'] for r in rows)
    subtotal=sum(r['capacity_bytes'] or 0 for r in rows)
    return {'devices':rows,'installed_capacity_bytes':subtotal if complete else None,
            'capacity_available':complete,'known_capacity_bytes':subtotal,'observed_device_records':len(rows),
            'populated_devices':sum(r['populated'] is True for r in rows) if all(r['available'] for r in rows) else None,
            'source':SOURCE,'note':'Firmware inventory, not an independent physical measurement. Empty sockets are retained; unknown capacity withholds the total. Data rates are not measured memory clocks.'}


def call(name,args):
    validate(name,args);result=report()
    if name=='WMIGetMemInfo':return result
    if name=='WMIGetMemSize':
        if not result['capacity_available']:raise OSError(errno.ENODATA,'Complete installed memory capacity is unavailable; inspect WMIGetMemInfo for per-device errors.')
        return result['installed_capacity_bytes']
    key={'WMIGetMemFrequency':'configured_speed_mt_s','WMIGetMemManufacture':'manufacturer','WMIGetMemModel':'part_number'}[name]
    out=[]
    for row in result['devices']:
        if row['populated'] is False:continue
        value=row.get(key);item={'device':row['device'],'locator':row.get('locator'),'value':value,
                                'available':row['available'] and value is not None,'source':SOURCE}
        if name=='WMIGetMemFrequency':item['units']='MT/s'
        if not item['available']:item.update(row.get('field_errors',{}).get(key) or {'errno':row.get('errno',errno.ENODATA),'error':row.get('error','Requested memory field is unknown.')})
        out.append(item)
    return out
