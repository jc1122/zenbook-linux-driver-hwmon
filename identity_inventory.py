# SPDX-License-Identifier: GPL-2.0-only
"""Read-only firmware, processor, graphics and native OS identity contracts."""
from pathlib import Path
import datetime
import errno
import os
import re
import shlex
import subprocess
import cpu_metadata
from platform_metadata import text,known

DMI={'WMIGetBiosManufacture':'board_vendor','WMIGetBiosReleaseDate':'bios_date',
     'WMIGetBiosVersion':'bios_version','WMIGetComputerFamilyName':'product_family',
     'WMIGetModelName':'board_name','WMIGetProductName':'product_name'}
NAMES=set(DMI)|{'WMIGetCPUInfo','WMIGetGPUInfo','WMIGetOSInfo'}
BDF=r'[0-9a-fA-F]{4,8}:[0-9a-fA-F]{2}:[0-1][0-9a-fA-F]\.[0-7]'
OS_FIELDS={'NAME','PRETTY_NAME','ID','VERSION_ID','VERSION','VERSION_CODENAME','BUILD_ID'}


def validate(name,args):
    if name not in NAMES:raise ValueError('Unknown identity inventory query.')
    if not isinstance(args,dict) or args:raise ValueError('Identity inventory takes no arguments.')


def firmware(name,root=Path('/sys/class/dmi/id')):
    value=known(text(root/DMI[name]))
    if value.casefold() in {'system product name','base board product name','baseboard product name'}:
        raise OSError(errno.ENODATA,'Firmware identity is an unspecified placeholder.')
    if name=='WMIGetBiosReleaseDate':
        if not re.fullmatch(r'[0-9]{2}/[0-9]{2}/[0-9]{4}',value):
            raise OSError(errno.EPROTO,'Firmware BIOS date is not MM/DD/YYYY.')
        try:return datetime.datetime.strptime(value,'%m/%d/%Y').date().isoformat()
        except ValueError:raise OSError(errno.EPROTO,'Firmware BIOS date is invalid.') from None
    return value


def _error(error):return {'errno':error.errno or errno.EIO,'error':str(error)}


def _os_value(raw):
    # The os-release format has assignments and quoting, without expansion,
    # commands or concatenated quoted strings. Never source this file.
    if raw.startswith("'"):
        if len(raw)<2 or raw[-1]!="'" or "'" in raw[1:-1]:raise ValueError('Invalid single quote')
        value=raw[1:-1]
    elif raw.startswith('"'):
        if len(raw)<2 or raw[-1]!='"':raise ValueError('Invalid double quote')
        value='';index=1
        while index<len(raw)-1:
            char=raw[index]
            if char=='\\' and index+1>=len(raw)-1:raise ValueError('Unterminated escape')
            if char=='\\' and index+1<len(raw)-1 and raw[index+1] in '$`"\\':
                index+=1;char=raw[index]
            elif char in '$`"':raise ValueError('Unescaped shell special character')
            value+=char;index+=1
    else:
        if not re.fullmatch(r'[A-Za-z0-9._+\-]*',raw):raise ValueError('Invalid unquoted value')
        value=raw
    if len(value)>4096 or any(ord(c)<32 or ord(c)==127 for c in value):raise ValueError('Invalid identity text')
    return value


def decode_os_release(raw):
    if not isinstance(raw,bytes) or len(raw)>65536:raise OSError(errno.E2BIG,'OS identity exceeds its bound.')
    try:lines=raw.decode('utf-8').splitlines()
    except UnicodeError:raise OSError(errno.EPROTO,'Invalid OS identity encoding.') from None
    values={};errors=0
    for line in lines:
        line=line.strip()
        if not line or line.startswith('#'):continue
        key,separator,value=line.partition('=')
        if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*',key):errors+=1;continue
        if key not in OS_FIELDS:continue
        try:values[key]=_os_value(value)
        except ValueError:values[key]=None;errors+=1
    if values.get('ID') and not re.fullmatch(r'[a-z0-9._\-]+',values['ID']):values['ID']=None;errors+=1
    values={key:value or None for key,value in values.items()}
    return values,errors


def distribution(paths=(Path('/etc/os-release'),Path('/usr/lib/os-release'))):
    for path in paths:
        try:
            with path.open('rb') as stream:
                before=os.fstat(stream.fileno());raw=stream.read(65537);after=os.fstat(stream.fileno())
            identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
            if identity(before)!=identity(after) or identity(after)!=identity(path.stat()):
                raise OSError(errno.EAGAIN,'OS identity file changed during sampling.')
            fields,errors=decode_os_release(raw)
            caption_key='PRETTY_NAME' if fields.get('PRETTY_NAME') else 'NAME' if fields.get('NAME') else None
            caption=fields[caption_key] if caption_key else None
            result={'available':caption is not None,'caption':caption,'caption_field':caption_key,
                    'fields':{k:fields.get(k) for k in sorted(OS_FIELDS)},'parse_errors':errors,
                    'complete':caption is not None and errors==0,'source':str(path)}
            if caption is None:result.update(errno=errno.ENODATA,error='No declared native OS caption.')
            return result
        except FileNotFoundError:continue
    raise OSError(errno.ENODATA,'No native OS identity file is present.')


def os_info():
    try:distro=distribution()
    except OSError as error:distro={'available':False,'caption':None,'complete':False,**_error(error)}
    try:
        uname=os.uname();machine=uname.machine
        if not all(isinstance(v,str) and v and len(v)<=4096 and all(ord(c)>=32 and ord(c)!=127 for c in v)
                   for v in (uname.sysname,uname.release,uname.version,machine)):
            raise OSError(errno.EPROTO,'Invalid kernel identity.')
        kernel={'available':True,'system':uname.sysname,'release':uname.release,'version':uname.version,'machine':machine}
        bits=(64 if machine.casefold() in ('x86_64','amd64','aarch64','arm64','ia64','ppc64','ppc64le','s390x','riscv64','mips64','mips64el')
              else 32 if re.fullmatch(r'i[3-6]86|x86|armv[4-8][a-z0-9]*|arm|ppc|powerpc|s390|riscv32|mips|mipsel',machine.casefold()) else None)
        arch={'available':bits is not None,'machine':machine,'bits':bits,'source':'Kernel uname machine; explicit native ISA-width mapping'}
        if bits is None:arch.update(errno=errno.EOPNOTSUPP,error='Kernel ISA width has no verified mapping.')
    except OSError as error:
        kernel={'available':False,**_error(error)};arch={'available':False,'machine':None,'bits':None,**_error(error)}
    return {'available':distro['available'] or kernel['available'],'caption':distro.get('caption'),
            'distribution':distro,'kernel':kernel,'architecture':arch,
            'complete':distro['complete'] and kernel['available'] and arch['available'],
            'note':'Native OS caption is the distribution declaration, separate from kernel version and kernel ISA width. No hostname, executable probe, variable expansion or shell execution.'}


def decode_pci_names(raw):
    if not isinstance(raw,str) or len(raw)>4*1024*1024:raise OSError(errno.E2BIG,'PCI name report exceeds its bound.')
    rows={};duplicates=set();errors=0
    for line in raw.splitlines():
        if not line.strip():continue
        try:
            fields=[field for field in shlex.split(line)
                    if not (field.startswith('-') and not any(c.isspace() for c in field))]
            if len(fields)<4 or not re.fullmatch(BDF,fields[0]):raise ValueError('Invalid PCI identity')
            address=fields[0].lower()
            decoded=[]
            for field in fields[1:4]:
                match=re.fullmatch(r'(.*?) \[([0-9a-fA-F]{4})\]',field)
                if not match:raise ValueError('Missing numeric identity')
                label=match[1]
                if len(label)>4096 or any(ord(c)<32 or ord(c)==127 for c in label):raise ValueError('Invalid PCI name')
                decoded.append((label,match[2].lower()))
            if address in rows or address in duplicates:
                rows.pop(address,None);duplicates.add(address);errors+=1;continue
            rows[address]={'class_id':decoded[0][1],'vendor_id':decoded[1][1],'device_id':decoded[2][1],
                           'vendor_name':decoded[1][0],'device_name':decoded[2][0]}
        except ValueError:errors+=1
    return rows,errors


def pci_names():
    try:
        result=subprocess.run(['/usr/bin/lspci','-A','linux-sysfs','-D','-mm','-nn'],
                              capture_output=True,text=True,encoding='utf-8',errors='strict',timeout=5,env={'LC_ALL':'C'})
    except FileNotFoundError:raise OSError(errno.ENODEV,'Local PCI name utility is unavailable.') from None
    except subprocess.TimeoutExpired:raise OSError(errno.ETIMEDOUT,'Local PCI name query timed out.') from None
    except UnicodeError:raise OSError(errno.EPROTO,'Invalid local PCI name encoding.') from None
    if result.returncode:raise OSError(errno.EIO,'Local PCI name query failed.')
    return decode_pci_names(result.stdout)


def gpu_info(root=Path('/sys/bus/pci/devices')):
    def census():
        values=sorted(root.iterdir())
        if len(values)>16384:raise OSError(errno.E2BIG,'PCI device census exceeds its bound.')
        return values
    def identity(path):
        item=path.stat();values={}
        for field,width in [('class',6),('vendor',4),('device',4)]:
            value=text(path/field)
            if not re.fullmatch(r'0x[0-9a-fA-F]{'+str(width)+'}',value):raise OSError(errno.EPROTO,'Invalid cached PCI identity.')
            values[field]=value[2:].lower()
        return (item.st_dev,item.st_ino),values
    def class_identity(path):
        item=path.stat();value=text(path/'class')
        if not re.fullmatch(r'0x[0-9a-fA-F]{6}',value):raise OSError(errno.EPROTO,'Invalid cached PCI class.')
        return (item.st_dev,item.st_ino),value[2:].lower()
    objects=census();rows=[];failures=[];classes={}
    try:names,parse_errors=pci_names();name_provider={'available':True,'parse_errors':parse_errors}
    except OSError as error:names={};name_provider={'available':False,**_error(error)}
    for path in objects:
        try:
            if not re.fullmatch(BDF,path.name):raise OSError(errno.EPROTO,'Invalid cached PCI address.')
            class_token,class_id=class_identity(path);classes[path]=class_token,class_id
            if class_id[:2]!='03':continue
            token,ids=identity(path)
            if token!=class_token or ids['class']!=class_id:raise OSError(errno.EAGAIN,'PCI classification changed during sampling.')
            row={'device':path.name,'available':True,'class_id':ids['class'],
                 'vendor_id':ids['vendor'],'device_id':ids['device'],'caption':None,'caption_available':False}
            named=names.get(path.name.lower())
            try:
                if not name_provider['available']:raise OSError(name_provider['errno'],'Local PCI caption provider is unavailable.')
                if named is None:raise OSError(errno.ENODATA,'No local PCI caption for this graphics device.')
                if (named['vendor_id'],named['device_id'],named['class_id'])!=(ids['vendor'],ids['device'],ids['class'][:4]):
                    raise OSError(errno.EAGAIN,'PCI caption numeric identity disagrees with cached graphics identity.')
                if named['device_name'].casefold() in ('','device','unknown device'):
                    raise OSError(errno.ENODATA,'Local PCI database has no descriptive graphics-device name.')
                vendor=named['vendor_name']
                if vendor.casefold() in ('vendor','unknown vendor'):vendor=''
                row.update(caption_available=True,caption=' '.join(v for v in [vendor,named['device_name']] if v),
                           caption_source='Local pciutils names, matched against cached numeric device/class identity')
            except OSError as error:row['caption_error']=_error(error)
            if (token,ids)!=identity(path):raise OSError(errno.EAGAIN,'Graphics-device identity changed during sampling.')
            rows.append(row)
        except OSError as error:failures.append({'device':path.name,**_error(error)})
    if objects!=census():raise OSError(errno.EAGAIN,'PCI census changed during graphics sampling.')
    for path,expected in classes.items():
        if class_identity(path)!=expected:raise OSError(errno.EAGAIN,'PCI class census changed during graphics sampling.')
    selection_complete=not failures
    return {'available':True,'adapters':rows,'present':True if rows else False if selection_complete else None,
            'selection_complete':selection_complete,'selection_errors':failures[:64],
            'selection_error_count':len(failures),'selection_errors_truncated':len(failures)>64,
            'caption_provider':name_provider,'complete':selection_complete and all(r['caption_available'] for r in rows),
            'source':'Cached PCI display-class03 devices and local ID-matched descriptions',
            'note':'Native caption counterpart, not a Windows driver display name. Unbound PCI graphics devices remain included; non-PCI graphics are outside this qualified PCI provider. Missing descriptions do not become numeric-ID captions. No network database query, rescan or configuration write.'}


def call(name,args):
    validate(name,args)
    if name in DMI:return firmware(name)
    if name=='WMIGetCPUInfo':return cpu_metadata.model_name()
    if name=='WMIGetGPUInfo':return gpu_info()
    return os_info()
