# SPDX-License-Identifier: GPL-2.0-only
"""Format-qualified OEM battery gauge reads, separate from its faulty EC history cache."""
import errno
import json
import os
import native_oem

TEMPERATURES=('internal','ts1','ts2','ts3','ts4','cell','fet')
HISTORY_NAMES={f'BatteryHealthy_Read_LifetimeBlock{i}':i for i in (1,3,4,5)}
PEAK_NAMES={'BatteryHealthy_Read_MaxCellDeltaVoltage':'max_cell_delta_millivolts',
            'BatteryHealthy_Read_MaxChargeCurrent':'max_charge_current_milliamps',
            'BatteryHealthy_Read_MaxDischargeCurrent':'max_discharge_current_raw'}
NAMES=set(HISTORY_NAMES)|set(PEAK_NAMES)
EVENT_NAMES={4:('Cell Overvoltage','Cell Undervoltage','Discharge Overcurrent 1','Discharge Overcurrent 2',
                'Charge Overcurrent 1','Charge Overcurrent 2','Discharge Overload','Discharge Short Circuit'),
             5:('Charge Short Circuit','Charge Overtemperature','Discharge Overtemperature','FET Overtemperature',
                'Valid Charge Termination','Qmax Update','Resistance Update','Resistance Update Disable')}
RESET_NAMES=('shutdowns','partial_resets','full_resets','watchdog_resets')
TIME_REGION_CODES=('UT','LT','STL','RT','STH','HT','OT')


def signed_current(raw):
    if type(raw) is not int or not 0<=raw<=65535:return None
    return raw-65536 if raw>=32768 else raw


def battery_error(flags):
    return bool(flags&0x80) if type(flags) is int and 0<=flags<=255 else None


def is_full(status):
    if status=='Full':return True
    if status in ('Charging','Discharging','Not charging'):return False
    return None


def legacy_pf_gate(status):
    if type(status) is not int or not 0<=status<=255:return None
    return bool(status&0x80) and not bool(status&0x40)


def payload(data,key,size):
    value=data.get(key)
    if not isinstance(value,str) or len(value)!=size*2:raise ValueError('Invalid '+key+' length.')
    raw=bytes.fromhex(value)
    if len(raw)!=size:raise ValueError('Invalid '+key+' bytes.')
    return raw


def validate(data,seconds):
    if not isinstance(data,dict) or type(data.get('schema')) is not int or data['schema']!=1 or data.get('device_type_hex')!='5645':
        raise OSError(errno.ENODEV,'Unqualified battery gauge identity.')
    fw=payload(data,'firmware_hex',13)
    if fw[:7]!=bytes.fromhex('45560234004002'):raise OSError(errno.ENODEV,'Unqualified battery gauge firmware/layout.')
    age=data.get('age_milliseconds')
    if type(age) is not int or not 0<=age<=seconds*1000 or data.get('maximum_cache_seconds')!=seconds:
        raise OSError(errno.ESTALE,'Invalid battery gauge cache age.')


def word(raw,offset,signed=False):return int.from_bytes(raw[offset:offset+2],'little',signed=signed)


def recorded_runtime(raw):
    """Caller validates the exact target identity/firmware and complete blocks.

    Compatible published block3 begins with eight U16 time counters. Target
    word0 advanced twice with a measured7200..7440s interval. The rounding
    relationship of the first eight words is retained as a layout guard; their
    temperature thresholds and the extra OEM bytes are not decoded here.
    """
    result={'available':False,'counter_raw':None,'counter_bits':16,'hours':None,
            'resolution_hours':None,'unit_verified':False}
    if len(raw)!=26:
        return {**result,'errno':errno.ENODATA,'error':'Complete target lifetime block3 is required for runtime decoding.'}
    values=[word(raw,2*i) for i in range(8)];result['counter_raw']=values[0]
    if any(value==65535 for value in values):
        return {**result,'errno':errno.ENODATA,'error':'Maximum counter value seen; saturation/wrap/reset behavior is unqualified.'}
    delta=values[0]-sum(values[1:])
    if not 0<=delta<=7:
        return {**result,'errno':errno.ENODATA,'error':'Time-prefix counters do not satisfy the qualified layout/rounding relationship.'}
    return {**result,'available':True,'hours':values[0]*2,'resolution_hours':2,'unit_verified':True,
            'historical':True,'reset_behavior_verified':False,
            'source':'Lifetime block3 offset0, little-endian U16; target-qualified two-hour stored resolution',
            'note':'Recorded firmware counter in two-hour steps, without interpolation. Not host uptime or battery age. Reset/wrap behavior and physical IC vendor are unverified.'}


def recorded_regions(raw):
    runtime=recorded_runtime(raw)
    if not runtime['available']:
        return {'available':False,'regions':[],'resolution_hours':None,'unit_verified':False,
                'errno':runtime['errno'],'error':runtime['error']}
    regions=[{'code':code,'counter_raw':word(raw,2+2*i),'hours':2*word(raw,2+2*i),
              'thresholds_celsius':None} for i,code in enumerate(TIME_REGION_CODES)]
    total=sum(region['hours'] for region in regions)
    return {'available':True,'historical':True,'regions':regions,'resolution_hours':2,'unit_verified':True,
            'sum_recorded_hours':total,'rounding_gap_hours':runtime['hours']-total,
            'configured_thresholds_available':False,'reset_behavior_verified':False,
            'reference_default_thresholds_celsius':{'T1':0,'T2':12,'T5':20,'T6':25,'T3':30,'T4':55,'hysteresis':1,
                'regions':{'UT':'<T1','LT':'T1..T2','STL':'T2..T5','RT':'T5..T6','STH':'T6..T3','HT':'T3..T4','OT':'>T4'},
                'read_from_pack':False,'source':'TI bq40z50-family data-flash defaults; the pack OEM may have changed them (sealed data flash is not read)'},
            'source':'Lifetime block3 offsets2..15, U16 counters; compatible firmware-region codes',
            'note':'Firmware-defined temperature-region history in two-hour steps. Actual configured Celsius thresholds are unavailable; region codes are not physical sensor locations. Independent quantization can leave the region sum below the recorded runtime. OEM bytes16..25 remain raw.'}


def recorded_balancing(raw):
    if len(raw)!=8 or raw[6:]!=bytes(2):
        return {'available':False,'cells':[],'resolution_hours':None,'unit_verified':False,
                'errno':errno.ENODATA,'error':'Complete qualified two-cell balancing layout is unavailable.'}
    cells=[]
    for i in range(2):
        count=raw[4+i]
        # TI: stored with 2 h resolution up to a limit of510 h; 255 is saturation.
        cell={'cell':i+1,'available':True,'counter_raw':count,'saturated':count==255,
              'hours':count*2 if count<255 else None,'hours_at_least':510 if count==255 else None}
        cells.append(cell)
    result={'available':all(c['available'] for c in cells),'historical':True,'cells':cells,
            'resolution_hours':2,'unit_from_compatible_reference':True,'physical_nonzero_scaling_verified':False,
            'reset_behavior_verified':False,'inactive_channel_bytes_hex':raw[6:].hex(),'saturation_limit_hours':510,
            'source':'Complete lifetime block2 offsets4/5; two-cell topology; compatible U8 balancing-time layout',
            'note':'Quantized recorded balancing counters, not current balancing status. Two-hour units and the 255 = at least510 h saturation limit come from the matched compatible TI reference; meaningful nonzero accumulation has not been physically qualified. No inactive third/fourth cell is reported.'}
    return result


def lifetime_events(blocks):
    events=[]
    for block,names in EVENT_NAMES.items():
        raw=blocks[block]
        for i,name in enumerate(names):
            offset=4*i;count=word(raw,offset)
            complete=offset+4<=len(raw)
            last=word(raw,offset+2) if complete else None
            events.append({'name':name,'count':count,'last_event_cycle_count':last if count and last!=65535 else None,
                           'last_cycle_field_complete':complete,'block':block,
                           'category':'safety' if block==4 or i<4 else 'gauging_and_charging'})
    return events


def decode_metrics(data):
    validate(data,5)
    a=payload(data,'da1_hex',20);t=payload(data,'da2_hex',14)
    cells=[]
    for i in range(4):
        mv=word(a,2*i)
        if 2000<=mv<=5000:cells.append({'cell':i+1,'voltage_volts':mv/1000,'current_amperes':word(a,12+2*i,True)/1000})
        elif mv not in (0,65535):raise OSError(errno.EPROTO,'Invalid gauge cell voltage.')
    if [c['cell'] for c in cells]!=[1,2]:raise OSError(errno.ENODEV,'Expected qualified two-cell battery topology.')
    temps={}
    for i,name in enumerate(TEMPERATURES):
        mc=word(t,2*i)*100-273150
        temps[name]=mc/1000 if -40000<=mc<=125000 else None
    volt=lambda o:word(a,o)/1000 if 4000<=word(a,o)<=17000 else None
    return {'available':True,'source':'OEM gauge DE manufacturer-data broker; target-qualified DAStatus layout',
            'temperatures_celsius':temps,'cells':cells,'bat_pin_voltage_volts':volt(8),'pack_pin_voltage_volts':volt(10),
            'age_milliseconds':data['age_milliseconds'],'maximum_cache_seconds':5,
            'note':'TS channels keep gauge pin names; unconnected/out-of-range inputs are unavailable. FET/internal refer to the battery pack. These are separate from motherboard NTCs and the laptop charger IC.'}


def decode_lifetime(data):
    validate(data,60)
    blocks={i:payload(data,f'block{i}_prefix_hex',4 if i==3 else 31) for i in (1,3,4,5)}
    resets=payload(data,'block2_prefix_hex',4) if 'block2_prefix_hex' in data else None
    if resets is not None:blocks[2]=resets
    prefixes=dict(blocks)
    complete=data.get('complete_blocks',False)
    if type(complete) is not bool:raise ValueError('Invalid complete-block marker.')
    if complete:
        blocks={i:payload(data,f'block{i}_hex',size) for i,size in enumerate((32,8,26,32,32),1)}
        if set(prefixes)!=set(blocks) or any(raw!=blocks[i][:len(raw)] for i,raw in prefixes.items()):
            raise OSError(errno.EPROTO,'Complete battery blocks disagree with their legacy prefixes.')
    b=blocks[1];cells=[]
    for i in range(4):
        high=word(b,2*i);low=word(b,8+2*i)
        if high==0 and low in (0,32767):continue
        if not 1500<=low<=high<=5000:raise OSError(errno.EPROTO,'Invalid lifetime cell extrema; no history accepted.')
        cells.append({'cell':i+1,'maximum_voltage_volts':high/1000,'minimum_voltage_volts':low/1000})
    if [c['cell'] for c in cells]!=[1,2]:raise OSError(errno.ENODEV,'Unqualified lifetime battery topology.')
    charge=word(b,18,True);discharge=word(b,20,True);avg=word(b,22,True);power=word(b,24,True)
    if not 0<=charge<=20000 or not -20000<=discharge<=0 or not -20000<=avg<=0 or not -20000<=power<=0:
        raise OSError(errno.EPROTO,'Invalid lifetime current/power sign or range.')
    temperatures={key:int.from_bytes(b[o:o+1],'little',signed=True) for key,o in
                  [('cell_maximum',26),('cell_minimum',27),('internal_maximum',29),('internal_minimum',30)]}
    if complete:temperatures['fet_maximum']=int.from_bytes(b[31:32],'little',signed=True)
    if any(not -40<=v<=125 for v in temperatures.values()) or temperatures['cell_minimum']>temperatures['cell_maximum'] or temperatures['internal_minimum']>temperatures['internal_maximum']:
        raise OSError(errno.EPROTO,'Invalid lifetime temperature extrema.')
    result={'available':True,'source':'Fresh fixed manufacturer queries; two identical reads per qualified prefix',
            'historical':True,'cells':cells,'max_cell_delta_millivolts':word(b,16),
            'max_charge_current_milliamps':charge,'max_discharge_current_raw':word(b,20),
            'maximum_charge_current_amperes':charge/1000,'maximum_discharge_current_amperes':-discharge/1000,
            'maximum_average_discharge_current_amperes':-avg/1000,'maximum_average_discharge_power_watts':-power/100,
            'temperatures_celsius':temperatures,'maximum_cell_temperature_delta_celsius':b[28],
            'raw_prefixes':{str(i):raw.hex() for i,raw in prefixes.items()},
            'raw_blocks':{str(i):raw.hex() for i,raw in blocks.items()} if complete else None,
            'complete_blocks':complete,'runtime_counter_raw':int.from_bytes(blocks[3][:4],'little'),
            'runtime_unit_verified':False,'age_milliseconds':data['age_milliseconds'],'maximum_cache_seconds':60,
            'recorded_firmware_runtime':recorded_runtime(blocks[3]),
            'recorded_temperature_region_time':recorded_regions(blocks[3]),
            'recorded_cell_balancing_time':recorded_balancing(blocks.get(2,b'')),
            'power_event_counts':dict(zip(RESET_NAMES,resets)) if resets is not None else None,
            'lifetime_events':lifetime_events(blocks),
            'unmapped_block_bytes':{'2':{'offset':6,'data_hex':blocks[2][6:].hex()},
                                    '3':{'offset':16,'data_hex':blocks[3][16:].hex()}} if complete else None,
            'note':'Recorded gauge extrema/events and counters, not present faults or battery age. Physical IC vendor is unverified. The four-byte runtime_counter_raw compatibility field remains opaque and runtime_unit_verified applies only to that field; use recorded_firmware_runtime for the qualified16-bit counter. Firmware-region codes do not assign Celsius thresholds. Remaining OEM bytes and inactive balancing-channel storage are retained raw.'}
    if result['max_cell_delta_millivolts']>3000:raise OSError(errno.EPROTO,'Invalid recorded cell imbalance.')
    return result


def read(attribute,decoder):
    try:
        fd=os.open(native_oem.device()/attribute,os.O_RDONLY|os.O_CLOEXEC)
        try:data=json.loads(os.read(fd,8192))
        finally:os.close(fd)
        return decoder(data)
    except (OSError,ValueError,TypeError,KeyError,RuntimeError) as error:
        return {'available':False,'errno':getattr(error,'errno',None) or errno.EPROTO,'error':str(error)}


def report():
    import battery_extra,battery_sbs
    result=read('battery_gauge_metrics',decode_metrics)
    result['additional_metrics']=battery_extra.report()
    result['smart_battery']=battery_sbs.report()
    result['smart_battery_diagnostics']=battery_sbs.diagnostics()
    return result
def lifetime_report():return read('battery_lifetime',decode_lifetime)


def call(name,args):
    if args:raise ValueError('This battery read takes no arguments.')
    data=lifetime_report()
    if not data['available']:raise OSError(data['errno'],data['error'])
    if name in PEAK_NAMES:return data[PEAK_NAMES[name]]
    i=HISTORY_NAMES[name]
    complete=data['complete_blocks']
    result={'data_hex':(data['raw_blocks'] if complete else data['raw_prefixes'])[str(i)],'complete':complete,
            'source':'fresh fixed manufacturer query; complete payload' if complete else 'fresh manufacturer query; qualified prefix only',
            'note':'Complete raw data does not establish units for unmapped OEM fields.' if complete else 'Unqualified trailing bytes are excluded, including shared firmware scratch.'}
    if i==3:
        result['recorded_firmware_runtime']=data['recorded_firmware_runtime']
        result['recorded_temperature_region_time']=data['recorded_temperature_region_time']
    return result
