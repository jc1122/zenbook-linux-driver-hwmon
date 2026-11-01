# SPDX-License-Identifier: GPL-2.0-only
"""Read native package registrations; never run installers or inspect app commands."""
from pathlib import Path
import errno
import http.client
import json
import os
import re
import socket
import subprocess

NATIVE={'GetApplist_x64':64,'App_Get_Win32App':64,
        'GetApplist_x86':32,'App_Get_Win32WOW6432App':32}
BUNDLED={'GetApplist_UWP','App_Get_UWPApp'}
NAMES=set(NATIVE)|BUNDLED
MAX_BYTES=8*1024*1024
DPKG_FORMAT='${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Status}\n'
STATES={'not-installed','config-files','half-installed','unpacked','half-configured',
        'triggers-awaited','triggers-pending','installed'}


def validate(name,args):
    if name not in NAMES:raise ValueError('Unknown application-inventory query.')
    if not isinstance(args,dict) or args:raise ValueError('Application inventory takes no arguments.')


def _text(value,maximum=1024,empty=False):
    return (isinstance(value,str) and len(value)<=maximum and (empty or bool(value))
            and not any(c in value for c in '\r\n\t\0'))


def _token(value,maximum=128):
    return _text(value,maximum) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]*',value) is not None


def _command(args):
    try:
        import linux_services
        result=subprocess.run([linux_services.system_tool(args[0]),*args[1:]],capture_output=True,timeout=5)
    except FileNotFoundError as error:raise OSError(errno.ENODEV,'Native inventory tool is not installed.') from error
    except subprocess.TimeoutExpired as error:raise OSError(errno.ETIMEDOUT,'Native inventory command timed out.') from error
    if result.returncode:raise OSError(errno.EIO,'Native inventory command failed.')
    if len(result.stdout)>MAX_BYTES:raise OSError(errno.E2BIG,'Native inventory output exceeds8MiB.')
    try:return result.stdout.decode('utf-8')
    except UnicodeDecodeError as error:raise OSError(errno.EPROTO,'Invalid inventory text encoding.') from error


def _failed(provider,scope,error):
    return {'provider':provider,'scope':scope,'available':False,'complete':False,
            'errno':error.errno or errno.EIO,'error':str(error)}


def _parse_error(line):
    return {'record':line,'errno':errno.EPROTO,'error':'Malformed or duplicated inventory record.'}


def native(bits):
    try:output=_command(['dpkg-query','-W','-f='+DPKG_FORMAT])
    except OSError as error:
        return _finish([_failed('dpkg','system',error)],[],architecture_bits=bits,
                       architecture_independent=[],unclassified_packages=[])
    rows=[];errors=[];seen=set();excluded=0
    for index,line in enumerate(output.splitlines(),1):
        fields=line.split('\t')
        if len(fields)!=4:
            errors.append(_parse_error(index));continue
        name,version,arch,state=fields
        if (re.fullmatch(r'[a-z0-9][a-z0-9+.-]*(?::[a-z0-9][a-z0-9-]*)?',name) is None or
            not _token(arch,64) or state not in STATES or name in seen):
            errors.append(_parse_error(index));continue
        seen.add(name)
        if state in ('not-installed','config-files'):excluded+=1;continue
        if not _text(version):errors.append(_parse_error(index));continue
        rows.append({'name':name,'version':version,'architecture':arch,'state':state,
                     'fully_installed':state=='installed','source':'dpkg','scope':'system'})
    selected=[];independent=[];unknown=[];widths={};field_errors=[]
    for row in rows:
        arch=row['architecture']
        if arch=='all':
            row.update(architecture_bits=None,architecture_independent=True);independent.append(row);continue
        if arch not in widths:
            try:
                raw=_command(['dpkg-architecture','--host-arch='+arch,'--query=DEB_HOST_ARCH_BITS']).strip()
                if re.fullmatch(r'[1-9][0-9]{0,2}',raw) is None:
                    raise OSError(errno.EPROTO,'Invalid declared ABI word size.')
                widths[arch]=int(raw)
            except OSError as error:
                widths[arch]=None;field_errors.append({'architecture':arch,'errno':error.errno,'error':str(error)})
        row.update(architecture_bits=widths[arch],architecture_independent=False)
        if widths[arch] is None:unknown.append(row)
        elif widths[arch]==bits:selected.append(row)
    provider={'provider':'dpkg','scope':'system','available':True,
              'complete':not errors and not unknown,'parse_errors':errors[:64],
              'parse_error_count':len(errors),'parse_errors_truncated':len(errors)>64,
              'architecture_errors':field_errors,'registered_present_packages':len(rows),
              'removed_records_excluded':excluded}
    for group in [selected,independent,unknown]:group.sort(key=lambda row:row['name'])
    return _finish([provider],selected,architecture_bits=bits,
                   architecture_independent=independent,unclassified_packages=unknown)


def flatpak(kind):
    args=['flatpak','list','--'+kind,'--all','--columns=application,version,arch,branch,origin,installation']
    try:output=_command(args)
    except OSError as error:return [],_failed('flatpak_'+kind,'reported_installations',error)
    rows=[];errors=[];seen=set()
    for index,line in enumerate(output.splitlines(),1):
        fields=line.split('\t')
        if len(fields)!=6:errors.append(_parse_error(index));continue
        name,version,arch,branch,origin,installation=fields
        identity=(name,arch,branch,installation)
        if (not all(_token(x) for x in (name,arch,branch)) or
            not _text(installation,128) or not _text(version,empty=True) or
            not _text(origin,empty=True) or identity in seen):
            errors.append(_parse_error(index));continue
        seen.add(identity)
        rows.append({'name':name,'version':version or None,'version_available':bool(version),
                     'architecture':arch,'architecture_available':True,'branch':branch,
                     'origin':origin or None,'installation':installation,
                     'scope':'user' if installation=='user' else 'system',
                     'kind':kind,'source':'flatpak'})
    return rows,{'provider':'flatpak_'+kind,'scope':'reported_installations','available':True,
                 'complete':not errors,'parse_errors':errors[:64],'parse_error_count':len(errors),
                 'parse_errors_truncated':len(errors)>64,'records':len(rows)}


class _UnixHTTP(http.client.HTTPConnection):
    def __init__(self,path):
        super().__init__('localhost',timeout=5);self.path=path
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout);self.sock.connect(self.path)


def _snapd(path='/run/snapd.socket'):
    connection=_UnixHTTP(path)
    try:
        connection.request('GET','/v2/snaps?select=all')
        response=connection.getresponse();raw=response.read(MAX_BYTES+1)
        if response.status!=200:
            raise OSError(errno.EACCES if response.status in (401,403) else errno.EIO,'snapd inventory HTTP error.')
        if len(raw)>MAX_BYTES:raise OSError(errno.E2BIG,'snapd inventory exceeds8MiB.')
        try:body=json.loads(raw)
        except (ValueError,UnicodeDecodeError) as error:raise OSError(errno.EPROTO,'Invalid snapd inventory JSON.') from error
        if (not isinstance(body,dict) or body.get('type')!='sync' or
            type(body.get('status-code')) is not int or body['status-code']!=200 or
            not isinstance(body.get('result'),list)):
            raise OSError(errno.EPROTO,'Invalid synchronous snapd inventory envelope.')
        return body['result']
    except FileNotFoundError as error:raise OSError(errno.ENODEV,'Installed snapd socket is absent.') from error
    except TimeoutError as error:raise OSError(errno.ETIMEDOUT,'snapd inventory timed out.') from error
    except http.client.HTTPException as error:raise OSError(errno.EPROTO,'Invalid snapd HTTP response.') from error
    finally:connection.close()


def _snap_architecture(name,revision,root=Path('/snap')):
    try:import yaml
    except ImportError as error:raise OSError(errno.ENODEV,'PyYAML is required for installed snap architecture metadata.') from error
    path=root/name/revision/'meta/snap.yaml'
    with path.open('rb') as stream:
        before=os.fstat(stream.fileno());raw=stream.read(1024*1024+1);after=os.fstat(stream.fileno())
    current=path.stat()
    signature=lambda st:(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)
    if signature(before)!=signature(after) or signature(after)!=signature(current):
        raise OSError(errno.EAGAIN,'Installed snap manifest changed during reading.')
    if len(raw)>1024*1024:raise OSError(errno.E2BIG,'Installed snap manifest exceeds1MiB.')
    try:data=yaml.safe_load(raw.decode('utf-8'))
    except (yaml.YAMLError,UnicodeDecodeError,RecursionError) as error:
        raise OSError(errno.EPROTO,'Malformed installed snap manifest.') from error
    if not isinstance(data,dict) or data.get('name')!=name.split('_',1)[0]:
        raise OSError(errno.EPROTO,'Installed snap manifest identity disagrees with snapd.')
    architectures=data.get('architectures')
    # snapd2.77.1 InfoFromSnapYaml prepares [all] when the declared list is
    # empty. This is the package-format default, never the host architecture.
    defaulted=architectures is None or architectures==[]
    if defaulted:architectures=['all']
    if (not isinstance(architectures,list) or not 1<=len(architectures)<=32 or
        not all(_token(a,64) for a in architectures) or len(set(architectures))!=len(architectures)):
        raise OSError(errno.ENODATA,'No valid declared snap architecture list.')
    return architectures,defaulted


def snaps():
    try:records=_snapd()
    except OSError as error:return [],_failed('snapd','system',error)
    rows=[];errors=[];seen=set()
    for index,record in enumerate(records,1):
        if not isinstance(record,dict):errors.append(_parse_error(index));continue
        name=record.get('name');revision=record.get('revision');version=record.get('version');status=record.get('status')
        if (not isinstance(name,str) or re.fullmatch(r'[a-z0-9][a-z0-9-]*(?:_[a-z0-9]{1,10})?',name) is None or len(name)>80 or
            not isinstance(revision,str) or re.fullmatch(r'x?[0-9]{1,20}',revision) is None or
            not _text(version) or status not in ('active','installed') or (name,revision) in seen):
            errors.append(_parse_error(index));continue
        seen.add((name,revision))
        row={'name':name,'version':version,'version_available':True,'revision':revision,
             'status':status,'active':status=='active','scope':'system','source':'snapd',
             'kind':record['type'] if _token(record.get('type')) else None,
             'architecture_available':False,'architectures':None,'architecture':None}
        try:
            architectures,defaulted=_snap_architecture(name,revision)
            row.update(architectures=architectures,architecture=architectures[0] if len(architectures)==1 else None,
                       architecture_available=True,
                       architecture_source='snap manifest format default all' if defaulted else 'installed snap manifest')
        except OSError as error:row.update(architecture_errno=error.errno,architecture_error=str(error))
        rows.append(row)
    return rows,{'provider':'snapd','scope':'system','available':True,'complete':not errors,
                 'parse_errors':errors[:64],'parse_error_count':len(errors),
                 'parse_errors_truncated':len(errors)>64,'records':len(rows),
                 'transport':'GET /v2/snaps?select=all on existing Unix socket'}


def _finish(providers,packages,**extra):
    available=any(p['available'] for p in providers)
    result={'available':available,'complete':all(p['available'] and p['complete'] for p in providers),
            'packages':packages,'providers':providers,**extra,
            'note':'Native registered-package inventory, including components. Collection completeness is separate from optional field availability. Debian architecture-independent records are separate, never assigned to64 or32. Scope follows package registrations; arbitrary/manual executables are not inferred as installed software. No install, refresh, store query or application execution occurs.'}
    if not available:result.update(errno=errno.ENODATA,error='No requested native inventory provider is available.')
    return result


def call(name,args):
    validate(name,args)
    if name in NATIVE:return native(NATIVE[name])
    packages=[];providers=[]
    for kind in ['app','runtime']:
        rows,provider=flatpak(kind);packages.extend(rows);providers.append(provider)
    rows,provider=snaps();packages.extend(rows);providers.append(provider)
    packages.sort(key=lambda r:(r['source'],r['name'],r.get('installation',''),r.get('architecture') or '',r.get('branch',''),r.get('revision','')))
    return _finish(providers,packages)
