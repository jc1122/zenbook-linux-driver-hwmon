# SPDX-License-Identifier: GPL-2.0-only
"""Complete, fixed read-only RX_SOURCE_CAPS cache for qualified UP3404VA.301."""
import errno
import json
import os
import re
import native_oem
import pd_contract


NAMES={'Adapter_Read_PDO',*(f'Adapter_Read_PDO{i}' for i in range(1,8))}


def decode(data):
    if len(data)!=81 or data[0]!=1:
        raise OSError(errno.EPROTO,'Invalid PD source capability layout.')
    contract=pd_contract.decode(data[:23])
    ports=[]
    for i,active in enumerate(contract['ports']):
        offset=23+29*i
        port_offset=3+10*i
        count=data[offset]
        row={'connector':i+1,'ec_port':'AB'[i],'available':False,'profiles':[]}
        ports.append(row)
        if not contract['ac_online'] or not data[port_offset]&0x40:
            if any(data[offset:offset+29]):
                raise OSError(errno.EPROTO,'Inactive port exposed stale source capabilities.')
            continue
        if not 1<=count<=7 or any(data[offset+1+4*count:offset+29]):
            raise OSError(errno.EPROTO,'Invalid source PDO count/padding.')
        active_word=int.from_bytes(data[port_offset+6:port_offset+10],'little')
        words=[int.from_bytes(data[offset+1+4*j:offset+5+4*j],'little') for j in range(count)]
        if (any(not w for w in words) or words[0]>>30 or ((words[0]>>10)&1023)!=100 or
                active_word not in words):
            raise OSError(errno.EPROTO,'Source capabilities do not match the active contract.')
        if active_word>>30==0 and not active['available']:
            raise OSError(errno.EPROTO,'Inconsistent fixed active contract fields.')
        row.update(active_contract_raw_pdo_hex=f'0x{active_word:08x}',
                   active_contract_format='fixed' if active_word>>30==0 else 'unqualified_nonfixed')
        for j,w in enumerate(words):
            profile={'index':j,'raw_pdo_hex':f'0x{w:08x}','supply_type_bits':w>>30,'measurement':False}
            if w>>30==0:
                mv=((w>>10)&1023)*50;ma=(w&1023)*10
                if not 4500<=mv<=50000 or not 50<=ma<=5000:
                    raise OSError(errno.EPROTO,'Invalid fixed source PDO voltage/current.')
                profile.update(type='fixed',voltage_volts=mv/1000,current_limit_amperes=ma/1000,
                               power_limit_watts=round(mv*ma/1_000_000,3))
            else:profile.update(type='unqualified_nonfixed',note='Raw object retained; this supply type has no qualified conversion.')
            row['profiles'].append(profile)
        row['available']=True
    return {'available':any(p['available'] for p in ports),'ports':ports,
            'source':'UP3404VA.301 per-port RX_SOURCE_CAPS EC cache',
            'snapshot_consistency':'contract bracketed; two identical complete passes',
            'measurement':False,'note':'Advertised source objects, not measurements. Fixed-supply limits are decoded; nonfixed objects and active contracts remain raw and unconverted. No cable identity is inferred.'}


def report():
    try:
        fd=os.open(native_oem.device()/'pd_source_caps',os.O_RDONLY)
        try:envelope=json.loads(os.read(fd,8192))
        finally:os.close(fd)
        if (not isinstance(envelope,dict) or type(envelope.get('schema')) is not int or envelope['schema']!=1 or
                type(envelope.get('maximum_cache_seconds')) is not int or envelope['maximum_cache_seconds']!=2 or
                not isinstance(envelope.get('data_hex'),str) or not re.fullmatch(r'[0-9a-fA-F]{162}',envelope['data_hex'])):
            raise OSError(errno.EPROTO,'Unknown PD source monitor schema.')
        return decode(bytes.fromhex(envelope['data_hex']))
    except (OSError,RuntimeError,ValueError,KeyError,TypeError) as error:
        return {'available':False,'ports':[],'errno':getattr(error,'errno',None) or errno.EPROTO,
                'error':str(error),'measurement':False}


def selected(connector=None):
    if connector is not None and (isinstance(connector,bool) or connector not in (1,2)):
        raise ValueError('connector must be 1 or 2.')
    result=report()
    if not result['available']:raise OSError(result.get('errno',errno.ENODEV),result.get('error','No active source capabilities.'))
    rows=[p for p in result['ports'] if p['available'] and (connector is None or p['connector']==connector)]
    if len(rows)!=1:raise OSError(errno.ENODEV if not rows else errno.EBUSY,'Select one active source with connector=1 or 2.')
    return rows[0]


def call(name,args):
    index=native_oem.integer(args.get('index'),0,6,'PDO index') if name=='Adapter_Read_PDO' else int(name[-1])-1
    profiles=selected(args.get('connector'))['profiles']
    if index>=len(profiles):raise OSError(errno.ENODATA,'The source does not advertise that PDO slot.')
    return int(profiles[index]['raw_pdo_hex'],16)
