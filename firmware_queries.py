# SPDX-License-Identifier: GPL-2.0-only
"""Public native results for fixed cached ASUS firmware diagnostic queries.

EEPROM table support, its recovered read-version selector and p_sensor are
separate queries. A zero DSTS support value is not a DEVS version/date result.
Cached reports read no BIOS/CMOS contents or register arrays. A supported,
explicit table API delegates its fixed privileged reads to eeprom_table.
"""
import errno
import qualified_ec
import eeprom_table

NAMES={'GetEEPROM_Data','GetSENSOR_WMI_Data'}
RECIPES={'eeprom_support':('DSTS',0x60059,0),
         'eeprom_version':('DEVS',0x60059,0xe0),
         'sensor_mask':('DSTS',0x60068,0)}
UNSUPPORTED_METHOD=0xfffffffe


def validate(name,args):
    if name not in NAMES:raise KeyError(name)
    if not isinstance(args,dict) or args:raise ValueError('This firmware diagnostic query takes no arguments.')


def decode(raw):
    if (not isinstance(raw,dict) or type(raw.get('schema')) is not int or raw['schema']!=1 or raw.get('cached_metadata_only') is not True or
        type(raw.get('query_count')) is not int or raw['query_count']!=3 or not isinstance(raw.get('queries'),dict) or
        set(raw['queries'])!=set(RECIPES)):
        raise OSError(errno.EPROTO,'Unqualified firmware diagnostic schema.')
    rows=raw['queries']
    transport=raw.get('eeprom_buffer')
    if transport is not None and (not isinstance(transport,dict) or set(transport)!={'abi','firmware_calls','guard_rejections'} or
        type(transport.get('abi')) is not int or transport['abi']!=1 or
        any(type(transport.get(k)) is not int or not 0<=transport[k]<2**64 for k in ['firmware_calls','guard_rejections'])):
        raise OSError(errno.EPROTO,'Invalid EEPROM buffer transport metadata.')
    for name,(method,device,selector) in RECIPES.items():
        row=rows[name]
        if (not isinstance(row,dict) or row.get('method')!=method or type(row.get('device_id')) is not int or
            row['device_id']!=device or type(row.get('selector')) is not int or row['selector']!=selector or
            type(row.get('status')) is not int or not -4095<=row['status']<=0 or type(row.get('raw')) is not int or
            not 0<=row['raw']<=0xffffffff or type(row.get('raw_valid')) is not bool):
            raise OSError(errno.EPROTO,'Invalid firmware diagnostic reply metadata.')
        valid=row['status']==0 or (row['status']==-errno.ENODEV and row['raw']==UNSUPPORTED_METHOD)
        if row['raw_valid']!=valid or (row['raw']==UNSUPPORTED_METHOD and row['status']==0):
            raise OSError(errno.EPROTO,'Firmware status and reply validity disagree.')
    def failed(row,label):
        return {'available':False,'value':None,'status':'query_failed','errno':-row['status'] if row['status'] else errno.ENODATA,
                'reason':label+' did not return a supported value.'}
    support,version,mask=(rows[k] for k in ['eeprom_support','eeprom_version','sensor_mask'])
    eeprom=failed(version,'EEPROM version query')
    if version['status']==-errno.ENODEV and version['raw_valid'] and version['raw']==UNSUPPORTED_METHOD:
        eeprom.update(status='firmware_unsupported',errno=errno.EOPNOTSUPP,
            reason='The ASUS EEPROM diagnostic table version query returned the firmware unsupported-method sentinel. BIOS/CMOS storage is a separate interface.')
    elif version['status']==0 and version['raw']<=0x7fffffff and transport is not None:
        eeprom={'available':True,'status':'version_responded','version':version['raw'],
                'data_collected':False,'collection_requires_root':True,
                'note':'Full table/E5 collection is explicit; metrics reads only cached probe metadata. Positive hardware qualification remains separate from recovered protocol support.'}
    elif version['status']==0 and version['raw']<=0x7fffffff:
        eeprom.update(status='buffer_transport_unavailable',errno=errno.EOPNOTSUPP,
            reason='The version query responded, but the loaded module lacks the recovered E5 transport.')
    eeprom.update(support_raw=support['raw'] if support['raw_valid'] else None,
                  version_reply_raw=version['raw'] if version['raw_valid'] else None,
                  source='ASUS DSTS0x60059 and original DEVS0x60059/read-selector0xe0')
    if support['status']:eeprom['support_query_errno']=-support['status']
    sensor=failed(mask,'p_sensor query')
    if not mask['status'] and mask['raw']!=0xffffffff:
        sensor={'available':True,'value':{'p_sensor':hex(mask['raw']),'raw':mask['raw'],'source':'ASUS DSTS 0x60068','cached':True},
                'status':'reported_raw_mask','note':'Raw firmware sensor mask, not a temperature or inferred physical sensor list.'}
    return {'schema':1,'provider_available':True,'cached_metadata_only':True,'queries':rows,'eeprom_table':eeprom,'sensor_mask':sensor,
            'eeprom_buffer_transport':transport}


def report():
    try:return decode(qualified_ec.firmware_metadata())
    except OSError as error:
        row={'available':False,'value':None,'status':'provider_unavailable','errno':error.errno or errno.EIO,'reason':str(error)}
        return {'schema':1,'provider_available':False,'eeprom_table':dict(row),'sensor_mask':dict(row),'errno':row['errno'],'error':str(error)}


def call(name,args):
    validate(name,args);row=report()['eeprom_table' if name=='GetEEPROM_Data' else 'sensor_mask']
    if not row['available']:raise OSError(row['errno'],row['reason'])
    if name=='GetEEPROM_Data':return eeprom_table.collect(row['version'])
    return row['value']
