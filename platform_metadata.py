# SPDX-License-Identifier: GPL-2.0-only
"""Exact firmware/device metadata selections for the original platform queries."""
from pathlib import Path
import datetime
import errno
import re
import stat
import uuid
import usb_inventory

NAMES={'WMIGet90Number','WMIGetBoardUUID','WMIGetSN','WMIGetType2SN',
       'WMIGetSystemChassisTypes','WMIGetCardReaderCaption','WMIGetMacAddress','System_Read_LocalTime'}
ROOT_READS={'WMIGet90Number','WMIGetBoardUUID','WMIGetSN','WMIGetType2SN'}
UNKNOWN={'unknown','none','n/a','not specified','not provided','not available',
         'not applicable','to be filled by o.e.m.','to be filled by oem',
         'default string','system serial number'}


def validate(name,args):
    if name not in NAMES:raise ValueError('Unknown platform metadata query.')
    if not isinstance(args,dict) or args:raise ValueError('Platform metadata takes no arguments.')


def text(path,limit=4096):
    with path.open('r',encoding='utf-8') as stream:
        try:value=stream.read(limit+1)
        except UnicodeError:raise OSError(errno.EPROTO,'Invalid platform metadata encoding.') from None
    if len(value)>limit:raise OSError(errno.E2BIG,'Platform metadata exceeds its bound.')
    value=value.strip()
    if any(ord(c)<32 or ord(c)==127 for c in value):raise OSError(errno.EPROTO,'Invalid platform metadata control character.')
    return value


def known(value):
    if not value or value.casefold() in UNKNOWN:
        raise OSError(errno.ENODATA,'Firmware field does not provide a known value.')
    return value


def identifier(name,root=Path('/sys/class/dmi/id')):
    field={'WMIGetBoardUUID':'product_uuid','WMIGetSN':'product_serial','WMIGetType2SN':'board_serial'}[name]
    value=known(text(root/field))
    if name=='WMIGetBoardUUID':
        if not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',value):
            raise OSError(errno.EPROTO,'Invalid firmware system UUID.')
        parsed=uuid.UUID(value)
        if parsed.int in (0,2**128-1):raise OSError(errno.ENODATA,'Firmware system UUID is unspecified.')
        return str(parsed)
    return value


def decode_fifth_oem(raw):
    if not isinstance(raw,bytes) or not 7<=len(raw)<=65536 or raw[0]!=11 or not 5<=raw[1]<=len(raw)-2:
        raise OSError(errno.EPROTO,'Invalid SMBIOS OEM-string frame.')
    tail=raw[raw[1]:]
    if tail.find(b'\0\0')!=len(tail)-2:raise OSError(errno.EPROTO,'Invalid OEM string terminator or trailing data.')
    strings=tail[:-2].split(b'\0') if len(tail)>2 else []
    if len(strings)!=raw[4]:raise OSError(errno.EPROTO,'OEM-string count disagrees with the frame.')
    if len(strings)<5:raise OSError(errno.ENODATA,'The original fifth OEM string is not supplied.')
    try:value=strings[4].decode('utf-8').strip()
    except UnicodeError:raise OSError(errno.EPROTO,'Invalid fifth OEM string encoding.') from None
    if len(value)>4096 or any(ord(c)<32 or ord(c)==127 for c in value):
        raise OSError(errno.EPROTO,'Invalid fifth OEM string.')
    return known(value)


def fifth_oem(root=Path('/sys/firmware/dmi/entries')):
    def paths():return sorted(p for p in root.iterdir() if re.fullmatch(r'11-[0-9]+',p.name))
    objects=paths()
    if not objects:raise OSError(errno.ENODATA,'No cached SMBIOS OEM-string record.')
    if len(objects)!=1:raise OSError(errno.EOPNOTSUPP,'Multiple OEM-string frames have no verified WMI-array ordering.')
    path=objects[0]
    def identity():
        value=path.stat();return value.st_dev,value.st_ino
    def read():
        with (path/'raw').open('rb') as stream:return stream.read(65537)
    before=identity();raw=read();value=decode_fifth_oem(raw)
    if before!=identity() or raw!=read() or objects!=paths():
        raise OSError(errno.EAGAIN,'OEM-string record changed during sampling.')
    return value


def chassis(root=Path('/sys/class/dmi/id')):
    raw=text(root/'chassis_type')
    if not re.fullmatch(r'[0-9]{1,3}',raw) or not 0<=int(raw)<=127:
        raise OSError(errno.EPROTO,'Invalid kernel SMBIOS chassis type.')
    code=int(raw)
    category='Desktop' if code in (3,13,35) else 'Notebook' if code in (10,30,31,32) else 'unknown'
    return {'code':code,'classification':category,
            'source':'Kernel SMBIOS chassis type and original ASUS classification table'}


def card_reader():
    data=usb_inventory.report();rows=[]
    for device in data['all_devices']:
        if not device['available'] or (device.get('vendor_id'),device.get('product_id'))!=('0bda','0129'):continue
        caption=device.get('product');row={'device':device['device'],'available':caption is not None,
                                         'caption':caption,'vendor_id':'0bda','product_id':'0129'}
        if caption is None:row.update(device.get('metadata_errors',{}).get('product') or
                                     {'errno':errno.ENODATA,'error':'Reader product caption is unavailable.'})
        rows.append(row)
    complete=data['enumeration_complete']
    return {'available':True,'readers':rows,'present':True if rows else False if complete else None,
            'complete':complete and all(r['available'] for r in rows),
            'source':'Cached USB0bda:0129 identity and kernel product caption; original fixed DeviceID selector',
            'note':'Other USB/PCI readers do not substitute for the original selected reader. Unknown USB identities prevent a complete absence claim.'}


def physical_macs(root=Path('/sys/class/net')):
    def paths():return sorted(root.iterdir())
    objects=paths();rows=[];excluded=0
    if len(objects)>65536:raise OSError(errno.E2BIG,'Network-interface census exceeds its bound.')
    for path in objects:
        try:relation=(path/'device').lstat()
        except FileNotFoundError:excluded+=1;continue
        except OSError as error:
            rows.append({'interface':path.name,'available':False,'address':None,
                         'errno':error.errno or errno.EIO,'error':str(error)});continue
        row={'interface':path.name,'available':False,'address':None}
        try:
            if not stat.S_ISLNK(relation.st_mode):raise OSError(errno.EPROTO,'Expected a kernel hardware-device relation.')
            device=(path/'device').resolve(strict=True);before=text(path/'ifindex')
            if not re.fullmatch(r'[1-9][0-9]{0,9}',before) or int(before)>2**31-1:
                raise OSError(errno.EPROTO,'Invalid network-interface index.')
            address=text(path/'address').lower();parts=address.split(':')
            if (len(parts) not in (6,8,20) or not all(re.fullmatch(r'[0-9a-f]{2}',p) for p in parts) or
                all(p=='00' for p in parts) or all(p=='ff' for p in parts)):
                raise OSError(errno.ENODATA,'No valid current hardware-interface address.')
            if (before!=text(path/'ifindex') or device!=(path/'device').resolve(strict=True) or
                address!=text(path/'address').lower()):
                raise OSError(errno.EAGAIN,'Network-interface identity/address changed during sampling.')
            row.update(available=True,address=address,ifindex=int(before))
        except OSError as error:row.update(errno=error.errno or errno.EIO,error=str(error))
        rows.append(row)
    if objects!=paths():raise OSError(errno.EAGAIN,'Network-interface census changed during sampling.')
    return {'available':True,'adapters':rows,'complete':all(r['available'] for r in rows),
            'software_interfaces_excluded':excluded,
            'source':'Kernel device-backed network interfaces and current link-layer addresses',
            'note':'Native counterpart of physicalAdapter=true. Software-only interfaces are excluded. Device-backed virtual/multiplexed hardware interfaces retain their kernel identity; current addresses are not asserted to be permanent factory addresses.'}


def call(name,args):
    validate(name,args)
    if name=='WMIGet90Number':return fifth_oem()
    if name in {'WMIGetBoardUUID','WMIGetSN','WMIGetType2SN'}:return identifier(name)
    if name=='WMIGetSystemChassisTypes':return chassis()
    if name=='WMIGetCardReaderCaption':return card_reader()
    if name=='WMIGetMacAddress':return physical_macs()
    return datetime.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')
