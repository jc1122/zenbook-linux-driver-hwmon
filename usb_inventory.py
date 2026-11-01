# SPDX-License-Identifier: GPL-2.0-only
"""Cached USB inventory, immediate attachment sockets and host-port groups."""
from pathlib import Path
import errno
import json
import re
import stat

NAMES={'RF_USBNum','RF_USBPort','RF_USBISTYPEC','RF_USB_A_Num','RF_USB_C_Num'}
TOPOLOGY=r'[0-9]+-[0-9]+(?:\.[0-9]+)*'


def text(path,limit=4096):
    with path.open('r',encoding='utf-8') as stream:
        try:raw=stream.read(limit+1)
        except UnicodeError:raise OSError(errno.EPROTO,'Invalid USB metadata encoding.') from None
    value=raw.strip()
    if len(raw)>limit or any(ord(c)<32 or ord(c)==127 for c in value):
        raise OSError(errno.EPROTO,'Invalid USB metadata text.')
    return value


def identity(path):
    info=path.stat();return info.st_dev,info.st_ino,str(path.resolve(strict=True))


def inventory_paths(root):
    result=sorted(p for p in root.iterdir() if re.fullmatch(TOPOLOGY,p.name))
    if len(result)>4096:raise OSError(errno.EOVERFLOW,'Too many USB topology objects.')
    return result


def capabilities(root=Path('/sys/class/hwmon')):
    try:
        matches=[]
        for path in sorted(root.iterdir()):
            if not re.fullmatch(r'hwmon[0-9]+',path.name):continue
            try:name=text(path/'name')
            except OSError:continue
            if name=='zenbook_ec':matches.append(path)
        if len(matches)!=1:raise OSError(errno.ENODEV,'No unique native connector-capability provider.')
        value=json.loads(text(matches[0]/'usb_connector_types',65536))
        if not isinstance(value,dict):raise ValueError('Invalid connector-capability object.')
        return value
    except (OSError,ValueError) as error:
        return {'ports':[],'complete':False,'errno':getattr(error,'errno',None) or errno.EPROTO,'error':str(error)}


def upc_connector(kind,connectable):
    if connectable==0:return 'internal'
    if kind in (0,3):return 'A'
    if kind in (8,9,10):return 'C'
    return 'other' if kind in (1,2,4,5,6,7,255) else 'unknown'


def capability_map(caps):
    rows=caps.get('ports') if isinstance(caps,dict) else None
    if not isinstance(rows,list) or len(rows)>512:raise OSError(errno.EPROTO,'Invalid connector-capability list.')
    out={}
    for row in rows:
        if (not isinstance(row,dict) or not isinstance(row.get('path'),str) or not 0<len(row['path'])<=512 or
            type(row.get('type')) is not int or not 0<=row['type']<=255 or
            type(row.get('connectable')) is not int or row['connectable'] not in (0,1,255)):
            raise OSError(errno.EPROTO,'Invalid ACPI connector metadata.')
        key=row['path'].lstrip('\\');value=(row['type'],row['connectable'])
        if key in out and out[key]!=value:raise OSError(errno.EPROTO,'Conflicting ACPI connector metadata.')
        out[key]=value
    return out


def link(path):
    try:info=path.lstat()
    except FileNotFoundError:return None
    if not stat.S_ISLNK(info.st_mode):raise OSError(errno.EPROTO,'Expected a kernel USB association link.')
    return path.resolve(strict=True)


def attachment_path(name,root):
    """Use the kernel device->port link; never infer a dock socket from root."""
    bus,chain=name.split('-',1);parts=chain.split('.')
    parent='usb'+bus if len(parts)==1 else bus+'-'+'.'.join(parts[:-1])
    expected=parent+'-port'+parts[-1]
    device=root/name;before=identity(device);path=link(device/'port')
    if path is None:raise OSError(errno.ENODATA,'Kernel USB attachment-port association is unavailable.')
    hub=(root/parent).resolve(strict=True)
    interface=re.escape(bus+'-0' if len(parts)==1 else parent)+r':[0-9]+\.[0-9]+'
    if (path.name!=expected or path.parent.parent!=hub or device.resolve(strict=True).parent!=hub or
            not re.fullmatch(interface,path.parent.name) or text(path.parent/'bInterfaceClass')!='09'):
        raise OSError(errno.EPROTO,'USB attachment link does not identify its immediate parent hub port.')
    if before!=identity(device) or link(device/'port')!=path:
        raise OSError(errno.EAGAIN,'USB attachment association changed during sampling.')
    return path,before


def controller(path):
    for parent in path.parents:
        if re.fullmatch(r'usb[0-9]+',parent.name):return parent.parent
    raise OSError(errno.EPROTO,'USB port is outside a registered bus ancestry.')


def host_connection(name,caps,root=Path('/sys/bus/usb/devices'),typec_root=Path('/sys/class/typec'),scope='host'):
    match=re.fullmatch(r'([0-9]+)-([0-9]+)(?:\.[0-9]+)*',name)
    if not match:return {'connector':'unknown','host_port':None,'group_members':[],'group_complete':False}
    bus,port=match.groups();selected=name if scope=='attachment' else bus+'-'+port
    result={'connector':'unknown','connectable':None,'scope':scope,'port':selected,
            'port_number':int(selected.rsplit('.',1)[-1].split('-')[-1]),
            'host_port':bus+'-'+port,'group_members':[],'group_complete':False,'sources':[]}
    try:
        path,device_before=attachment_path(selected,root)
        before=identity(path);resolved=path.resolve(strict=True);members=[str(resolved)]
        peer=link(path/'peer')
        peer_before=identity(peer) if peer is not None else None
        if peer is not None:
            if (peer==resolved or controller(peer)!=controller(resolved) or
                not re.fullmatch(r'(?:usb[0-9]+|'+TOPOLOGY+r')-port[0-9]+',peer.name) or link(peer/'peer')!=resolved):
                raise OSError(errno.EPROTO,'USB peer association is not reciprocal within one host controller.')
            members.append(str(peer));result['peer_port']=peer.name
        connector=link(path/'connector')
        if connector is not None:
            if not re.fullmatch(r'port[0-9]+',connector.name) or (typec_root/connector.name).resolve(strict=True)!=connector:
                raise OSError(errno.EPROTO,'USB Type-C association does not name a registered host connector.')
            members.append('typec:'+str(connector));result['sources'].append('Linux Type-C connector association')
        try:acpi=text(path/'firmware_node/path').lstrip('\\')
        except OSError as error:
            acpi=None
            if error.errno!=errno.ENOENT:result.update(acpi_errno=error.errno or errno.EIO,acpi_error=str(error))
        try:table=capability_map(caps)
        except OSError as error:table={};result['capability_errno']=error.errno;result['capability_error']=str(error)
        kinds=[]
        try:
            connection=text(path/'connect_type')
            if connection not in ('hotplug','hardwired','not used','unknown'):raise OSError(errno.EPROTO,'Invalid kernel USB connect_type.')
            result.update(connect_type=connection,connectable={'hotplug':True,'hardwired':False,'not used':False,'unknown':None}[connection])
            result['sources'].append('Linux USB port connect_type (user visibility)')
        except OSError as error:
            result.update(connect_type=None,connect_type_errno=error.errno or errno.EIO,connect_type_error=str(error))
        if acpi in table:
            kind,connectable=table[acpi];kinds.append(upc_connector(kind,connectable))
            result.update(acpi_path=acpi,upc_type=kind,upc_connectable=bool(connectable));result['sources'].append('ACPI _UPC')
            # _UPC connectivity alone does not establish user visibility (_PLD).
            if not connectable and result['connectable'] is None:result['connectable']=False
            if not connectable and result['connectable'] is True:
                raise OSError(errno.EPROTO,'USB connect_type and unavailable _UPC port disagree.')
        if connector is not None:kinds.append('C')
        known=set(kinds)-{'unknown'}
        result['connector']=next(iter(known)) if len(known)==1 else 'unknown'
        if len(known)>1:result.update(classification_errno=errno.EPROTO,classification_error='Connector sources disagree.')
        if (before!=identity(path) or peer!=link(path/'peer') or connector!=link(path/'connector') or
                (peer is not None and (identity(peer)!=peer_before or link(peer/'peer')!=resolved)) or
                attachment_path(selected,root)!=(path,device_before)):
            raise OSError(errno.EAGAIN,'USB port association changed during sampling.')
        result.update(group_members=sorted(set(members)),group_complete=True)
    except OSError as error:
        result.update(connector='unknown',connectable=None,group_members=[],group_complete=False,errno=error.errno or errno.EIO,error=str(error))
    return result


def version(raw):
    match=re.fullmatch(r'([0-9a-fA-F]{1,2})\.([0-9a-fA-F]{2})',raw)
    if not match:raise OSError(errno.EPROTO,'Invalid cached USB bcdUSB rendering.')
    return f'{int(match[1],16):02x}{int(match[2],16):02x}'


def interfaces(path):
    configuration=text(path/'bConfigurationValue')
    if not re.fullmatch(r'[0-9]{1,3}',configuration) or int(configuration)>255:
        raise OSError(errno.EPROTO,'Invalid cached USB configuration.')
    objects=sorted(path.glob(path.name+':*'))
    if len(objects)>256:raise OSError(errno.EOVERFLOW,'Too many cached USB interfaces.')
    if not objects and int(configuration):raise OSError(errno.ENODATA,'Configured USB interface census is unavailable.')
    classes=[];guards=[]
    for obj in objects:
        match=re.fullmatch(re.escape(path.name)+r':([0-9]{1,3})\.([0-9]{1,3})',obj.name)
        if not match or int(match[1])!=int(configuration):raise OSError(errno.EAGAIN,'USB interface configuration changed.')
        before=identity(obj);kind=text(obj/'bInterfaceClass')
        if not re.fullmatch(r'[0-9a-fA-F]{2}',kind):raise OSError(errno.EPROTO,'Invalid cached USB interface class.')
        classes.append(kind.lower());guards.append((obj,before,kind))
    if (text(path/'bConfigurationValue')!=configuration or sorted(path.glob(path.name+':*'))!=objects or
            any(identity(obj)!=before or text(obj/'bInterfaceClass')!=kind for obj,before,kind in guards)):
        raise OSError(errno.EAGAIN,'USB interface identity/class changed during sampling.')
    return {'configuration':int(configuration),'classes':sorted(classes)}


def version_distribution(rows):
    counts={key:0 for key in ('0200','0210','0300','0310','0320')};other={};unknown_count=0
    for row in rows:
        raw=row['usb_specification_bcd']
        if raw is None:unknown_count+=1
        elif raw in counts:counts[raw]+=1
        else:other[raw]=other.get(raw,0)+1
    return {'usb_specification_bcd_counts':counts,'other_usb_specification_bcd_counts':other,
            'unknown_usb_specification_count':unknown_count,'version_coverage_complete':unknown_count==0}


def group_connections(rows,connections,field):
    parent={}
    def find(x):
        parent.setdefault(x,x)
        if parent[x]!=x:parent[x]=find(parent[x])
        return parent[x]
    for connection in connections.values():
        members=connection['group_members']
        for member in members:parent[find(member)]=find(members[0])
    groups={}
    for row in rows:
        if not row['available']:continue
        name=row['device'] if field=='attachment_connection' else re.match(r'[0-9]+-[0-9]+',row['device'])[0]
        connection=dict(connections[name]);members=connection['group_members']
        key=find(members[0]) if members else 'unknown:'+name
        group=groups.setdefault(key,{'members':set(),'kinds':set(),'connectable':set(),'complete':True})
        group['members'].update(members);group['kinds'].add(connection['connector']);group['connectable'].add(connection['connectable'])
        group['complete']&=connection['group_complete'];row[field]=connection
    for group in groups.values():
        known=group['kinds']-{'unknown'};connectable=group['connectable']-{None}
        group['connector']=next(iter(known)) if len(known)==1 else 'unknown'
        group['user_connectable']=next(iter(connectable)) if len(connectable)==1 else None
        group['complete']&=len(connectable)==1 and (group['user_connectable'] is False or len(known)==1)
        if len(connectable)>1:group['connector']='unknown'
        group['key']='|'.join(sorted(group['members']))
    for row in rows:
        if not row['available']:continue
        connection=row[field];members=connection['group_members'];name=connection['port']
        group=groups[find(members[0]) if members else 'unknown:'+name]
        connection.update(reported_connector=connection['connector'],port_group=group['key'],connector=group['connector'],
                          connectable=group['user_connectable'],group_complete=group['complete'])
        if len(group['kinds']-{'unknown'})>1 or len(group['connectable']-{None})>1:
            connection.update(group_errno=errno.EPROTO,group_error='Connected port-group classifications disagree.')
        if field=='attachment_connection':row['connector']=connection['connector']
    return [{'port_group':g['key'],'connector':g['connector'],'connectable':g['user_connectable'],'complete':g['complete']} for g in groups.values()]


def essential(path):
    out={}
    for field,width in [('idVendor',4),('idProduct',4),('bDeviceClass',2)]:
        raw=text(path/field)
        if not re.fullmatch(r'[0-9a-fA-F]{'+str(width)+'}',raw):raise OSError(errno.EPROTO,'Invalid USB descriptor metadata.')
        out[field]=raw.lower()
    for field,maximum in [('busnum',65535),('devnum',127)]:
        raw=text(path/field)
        if not re.fullmatch(r'[0-9]{1,5}',raw) or not 1<=int(raw)<=maximum:raise OSError(errno.EPROTO,'Invalid USB bus/device address.')
        out[field]=int(raw)
    if out['busnum']!=int(path.name.split('-')[0]):raise OSError(errno.EAGAIN,'USB bus identity changed.')
    return out


def unknown(path,error):
    return {'device':path.name,'available':False,'is_hub':None,'connector':'unknown','host_connection':None,
            'errno':error.errno or errno.EIO,'error':str(error)}


def report(root=Path('/sys/bus/usb/devices'),caps=None,typec_root=Path('/sys/class/typec')):
    if caps is None:caps=capabilities()
    objects=inventory_paths(root);rows=[];guards=[];hosts={};attachments={}
    for path in objects:
        try:
            before=identity(path);fields=essential(path)
            row={'device':path.name,'available':True,'is_hub':fields['bDeviceClass']=='09',
                 'vendor_id':fields['idVendor'],'product_id':fields['idProduct'],'device_class':fields['bDeviceClass'],
                 'bus_number':fields['busnum'],'device_number':fields['devnum'],'port_path':before[2],'metadata_errors':{}}
            for field,key in [('product','product'),('manufacturer','manufacturer'),('speed','speed_mbit'),('removable','removable'),('bcdDevice','firmware_bcd')]:
                try:
                    value=text(path/field)
                    if not value:raise OSError(errno.ENODATA,'USB metadata is not supplied.')
                    if field=='bcdDevice' and not re.fullmatch(r'[0-9a-fA-F]{4}',value):raise OSError(errno.EPROTO,'Invalid raw bcdDevice.')
                    if field=='speed' and (not re.fullmatch(r'[0-9]{1,6}(?:\.[0-9]{1,3})?',value) or float(value)<=0):raise OSError(errno.ENODATA,'USB link speed is unavailable.')
                    row[key]=value
                except OSError as error:row[key]=None;row['metadata_errors'][key]={'errno':error.errno or errno.EIO,'error':str(error)}
            try:row['usb_specification_bcd']=version(text(path/'version'))
            except OSError as error:
                row['usb_specification_bcd']=None;row['metadata_errors']['usb_specification_bcd']={'errno':error.errno or errno.EIO,'error':str(error)}
            try:
                interface=interfaces(path);row.update(interfaces=interface,usb_mass_storage_class=fields['bDeviceClass']=='08' or '08' in interface['classes'])
            except OSError as error:
                row.update(interfaces=None,usb_mass_storage_class=True if fields['bDeviceClass']=='08' else None)
                row['metadata_errors']['interfaces']={'errno':error.errno or errno.EIO,'error':str(error)}
            if before!=identity(path) or fields!=essential(path):raise OSError(errno.EAGAIN,'USB device identity changed during sampling.')
            host_name=re.match(r'[0-9]+-[0-9]+',path.name)[0]
            if host_name not in hosts:hosts[host_name]=host_connection(host_name,caps,root,typec_root)
            attachments[path.name]=host_connection(path.name,caps,root,typec_root,'attachment')
            row['host_connection']=hosts[host_name];row['attachment_connection']=attachments[path.name];row['connector']=attachments[path.name]['connector']
            guards.append((path,before,fields,len(rows)))
        except OSError as error:row=unknown(path,error)
        rows.append(row)
    if objects!=inventory_paths(root):raise OSError(errno.EAGAIN,'USB topology census changed during sampling.')
    for path,before,fields,index in guards:
        try:
            if before!=identity(path) or fields!=essential(path):raise OSError(errno.EAGAIN,'USB identity changed during final check.')
            row=rows[index]
            if row['interfaces'] is not None:
                try:
                    if interfaces(path)!=row['interfaces']:raise OSError(errno.EAGAIN,'USB configuration/interface classes changed before publication.')
                except OSError as error:
                    row.update(interfaces=None,usb_mass_storage_class=True if fields['bDeviceClass']=='08' else None)
                    row['metadata_errors']['interfaces']={'errno':error.errno or errno.EIO,'error':str(error)}
            if row['usb_specification_bcd'] is not None:
                try:
                    if version(text(path/'version'))!=row['usb_specification_bcd']:raise OSError(errno.EAGAIN,'USB specification descriptor changed before publication.')
                except OSError as error:
                    row['usb_specification_bcd']=None;row['metadata_errors']['usb_specification_bcd']={'errno':error.errno or errno.EIO,'error':str(error)}
        except OSError as error:rows[index]=unknown(path,error)
    for scope,connections in [('host',hosts),('attachment',attachments)]:
        for name,old in list(connections.items()):
            if old!=host_connection(name,caps,root,typec_root,scope):
                connections[name]={'connector':'unknown','connectable':None,'scope':scope,'port':name,'host_port':name,
                                   'group_members':[],'group_complete':False,'errno':errno.EAGAIN,'error':'USB port metadata changed during final check.'}
    host_groups=group_connections(rows,hosts,'host_connection')
    groups=group_connections(rows,attachments,'attachment_connection')
    complete=all(r['available'] for r in rows)
    return {'devices':[r for r in rows if r['is_hub'] is not True],'all_devices':rows,'enumeration_complete':complete,
            'groups':groups,'host_groups':host_groups,
            'source':'Linux cached USB descriptors, ACPI _UPC and validated kernel peer/Type-C links',
            'note':'USBNum excludes hubs; connection queries include enumerated hubs. Default connector/connection counts describe immediate attachment sockets, including downstream hubs. Host scope is separate. User-visible connect_type gates counts; raw _UPC connectivity alone does not establish user visibility. Peer halves and Type-C links group one socket. These are enumerated USB data connections, not power-only cables, cable identity or I/O throughput. USB specification is cached bcdUSB, distinct from firmware bcdDevice and negotiated link speed. No power, authorization, bind, reset, descriptor request or controller operation is requested.'}


def validate(name,args):
    if name not in NAMES:raise KeyError(name)
    allowed={'device','scope'} if name=='RF_USBISTYPEC' else {'scope'} if name in ('RF_USB_A_Num','RF_USB_C_Num') else {'detailed'} if name=='RF_USBNum' else set()
    if set(args)-allowed:raise ValueError('Unsupported USB query argument.')
    if 'scope' in args and (not isinstance(args['scope'],str) or args['scope'] not in ('attachment','host')):
        raise ValueError('scope must be attachment or host.')
    if 'detailed' in args and type(args['detailed']) is not bool:raise ValueError('detailed must be boolean.')
    if 'device' in args and (not isinstance(args['device'],str) or not re.fullmatch(TOPOLOGY,args['device'])):
        raise ValueError('device must be a USB topology name.')


def call(name,args):
    validate(name,args);result=report();rows=result['all_devices']
    if name=='RF_USBPort':return result['devices']
    if name=='RF_USBNum':
        for row in rows:
            if not row['available']:raise OSError(row['errno'],row['error'])
        if not args.get('detailed'):return len(result['devices'])
        storage=[r for r in result['devices'] if r['usb_mass_storage_class'] is True]
        unknown=sum(r['usb_mass_storage_class'] is None for r in result['devices'])
        return {'count':len(result['devices']),**version_distribution(result['devices']),
                'mass_storage':{'count':len(storage) if not unknown else None,'observed_count':len(storage),'classification_unknown_count':unknown,
                                'classification_complete':unknown==0,**version_distribution(storage),
                                'source':'Cached USB device class08 or active interface class08; not a Windows friendly-name filter'},
                'source':result['source'],'coverage':result['note']}
    if name=='RF_USBISTYPEC':
        if 'device' in args:
            rows=[r for r in rows if r['device']==args['device']]
            if not rows:raise OSError(errno.ENODEV,'Requested USB topology device is not present.')
        field='host_connection' if args.get('scope')=='host' else 'attachment_connection'
        def kind(row):return row[field]['connector'] if row['available'] else 'unknown'
        positive=any(kind(r)=='C' for r in rows)
        complete=all(kind(r)!='unknown' for r in rows)
        value=True if positive else False if complete else None
        return {'type_c':value,'available':value is not None,'coverage_complete':complete,'scope':args.get('scope','attachment'),
                'unclassified':sum(kind(r)=='unknown' for r in rows),
                **({field:rows[0][field]} if 'device' in args and rows[0]['available'] else {}),'coverage':result['note']}
    if name in ('RF_USB_A_Num','RF_USB_C_Num'):
        kind='A' if name=='RF_USB_A_Num' else 'C';groups=result['host_groups'] if args.get('scope')=='host' else result['groups']
        field='host_connection' if args.get('scope')=='host' else 'attachment_connection'
        complete=result['enumeration_complete'] and all(g['complete'] for g in groups)
        # Original "A" is the user-connectable !PortIsTypeC branch, including
        # known B/proprietary connectors. Preserve its quantity without calling
        # those physical sockets type A in the detailed inventory.
        def selected(connection):return (connection['connector'] in ('A','other') if kind=='A' else connection['connector']=='C') and connection['connectable'] is True
        count=sum(r['available'] and selected(r[field]) for r in rows)
        sockets=sum(selected(g) for g in groups)
        return {'count':count if complete else None,'observed_count':count,'available':complete,'coverage_complete':complete,
                'quantity':'user-connectable non-Type-C USB device connections' if kind=='A' else 'user-connectable Type-C USB device connections',
                'socket_count':sockets if complete else None,'observed_socket_count':sockets,
                'scope':args.get('scope','attachment'),'unclassified':sum(not g['complete'] for g in groups)+sum(not r['available'] for r in rows),'coverage':result['note']}
    raise KeyError(name)
