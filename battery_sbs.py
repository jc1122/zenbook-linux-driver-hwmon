# SPDX-License-Identifier: GPL-2.0-only
"""Direct, fixed SBS reads. Gauge capacity and SOC values remain gauge estimates.

Charge requests are desired values, separate from actual current and voltage.
The gauge type/firmware is format qualified; its physical IC vendor is unknown.
"""
import errno
import battery_diagnostics as battery
TRANSPORTS={'legacy_i2c_combined_read_word','native_smbus_read_word'}


def decode(data):
    battery.validate(data,30)
    transport=data.get('transport','legacy_i2c_combined_read_word')
    if transport not in TRANSPORTS:raise OSError(errno.EPROTO,'Unqualified SBS transport.')
    w=data.get('words')
    if not isinstance(w,list) or len(w)!=16 or any(type(n) is not int or not 0<=n<=65535 for n in w):
        raise ValueError('Invalid SBS word frame.')
    if w[0]!=0x31:
        raise OSError(errno.ENODEV,'Unqualified SBS specification/scaling.')
    signed=lambda n:n-65536 if n>=32768 else n
    current,average=signed(w[4]),signed(w[5])
    if not 2000<=w[2]<=4000 or not 4000<=w[3]<=11000 or any(abs(n)>20000 for n in (current,average)):
        raise OSError(errno.EPROTO,'Invalid SBS temperature, voltage or current.')
    if any(w[i]>100 for i in (8,9,10)) or not 4000<=w[15]<=11000:
        raise OSError(errno.EPROTO,'Invalid SBS state of charge or design voltage.')
    energy_mode=bool(w[1]&0x8000)
    capacities={key:None for key in ('remaining_milliamp_hours','full_milliamp_hours','design_milliamp_hours',
                                    'remaining_watt_hours','full_watt_hours','design_watt_hours')}
    for key,value in zip(('remaining','full','design'),(w[11],w[12],w[14])):
        if value==65535:continue
        capacities[key+('_watt_hours' if energy_mode else '_milliamp_hours')]=value/100 if energy_mode else value
    return {'available':True,'transport':transport,
            'source':'Fixed firmware native SMBus ReadWord worker' if transport=='native_smbus_read_word' else 'Fixed firmware combined-read worker; direct SBS READ words',
            'voltage_volts':w[3]/1000,'current_amperes':current/1000,'average_current_amperes':average/1000,
            'temperature_celsius':w[2]/10-273.15,'relative_state_of_charge_percent':w[9],
            'absolute_state_of_charge_percent':w[10],'state_of_charge_maximum_error_percent':w[8],
            'requested_charging_current_amperes':None if w[6]==65535 else w[6]/1000,
            'requested_charging_voltage_volts':None if w[7]==65535 else w[7]/1000,
            'requested_charging_current_is_maximum':w[6]==65535,
            'requested_charging_voltage_is_maximum':w[7]==65535,
            'cycle_count':w[13],'design_voltage_volts':w[15]/1000,'capacities':capacities,
            'capacity_mode':'energy' if energy_mode else 'charge','battery_mode_raw':w[1],
            'specification_raw':w[0],'age_milliseconds':data['age_milliseconds'],'maximum_cache_seconds':30,
            'sequential_reads':True,'note':'Positive current means charging. Desired charging values are requests, not measured flow. SOC/capacities and the error margin are gauge estimates; energy capacity is reported only in energy mode, without voltage-based conversion. SBS temperature is the selected battery temperature, not another physical sensor. Words have different sample times; mode and specification are bracketed.'}


def report():return battery.read('battery_sbs',decode)


def decode_diagnostics(data):
    phases={'snapshot','idle','identity','firmware','prepare','word-sentinel','word-channel',
            'word-command','word-submit','word-completion','word-bus-status','word-rx-low',
            'word-rx-high','mode-bracket','complete','native-word-completion','native-word-result','word-rx-tail'}
    if not isinstance(data,dict) or type(data.get('schema')) is not int or data['schema']!=1 or data.get('cached_metadata_only') is not True:
        raise ValueError('Invalid SBS diagnostic metadata schema.')
    transport=data.get('transport','legacy_i2c_combined_read_word')
    if transport not in TRANSPORTS:raise ValueError('Invalid SBS diagnostic transport.')
    for name in ('attempts','successes','failures'):
        if type(data.get(name)) is not int or not 0<=data[name]<2**64:raise ValueError('Invalid SBS diagnostic counter.')
    if data['attempts']!=data['successes']+data['failures']:raise ValueError('Inconsistent SBS diagnostic counters.')
    retry_keys={'retries','recovered_refreshes','retry_limit','retry_backoff_milliseconds'}
    if set(data)&retry_keys:
        if not retry_keys<=set(data) or any(type(data[key]) is not int or not 0<=data[key]<2**64 for key in retry_keys):
            raise ValueError('Invalid SBS retry metadata.')
        if data['retry_limit']!=1 or data['retry_backoff_milliseconds']!=100 or data['retries']>data['failures'] or data['recovered_refreshes']>min(data['retries'],data['successes']):
            raise ValueError('Inconsistent SBS bounded retry counters/policy.')
    for name,count in [('last_attempt',data['attempts']),('last_failure',data['failures'])]:
        trace=data.get(name)
        if not count:
            if trace is not None:raise ValueError('SBS trace exists without a recorded attempt.')
            continue
        if not isinstance(trace,dict) or trace.get('phase') not in phases:raise ValueError('Invalid SBS trace phase.')
        if trace.get('transport',transport)!=transport:raise ValueError('SBS trace/diagnostic transport mismatch.')
        for key in ('result','operation_status','restoration_status'):
            if type(trace.get(key)) is not int or not -4095<=trace[key]<=0:raise ValueError('Invalid SBS trace status.')
        if trace['result']!=(-errno.EUCLEAN if trace['restoration_status'] else trace['operation_status']):raise ValueError('Inconsistent SBS trace status.')
        if name=='last_failure' and not trace['result']:raise ValueError('A successful read is not a failed SBS attempt.')
        if not trace['result'] and trace['phase']!='complete':raise ValueError('Successful SBS trace is incomplete.')
        if type(trace.get('age_milliseconds')) is not int or not 0<=trace['age_milliseconds']<2**64:raise ValueError('Invalid SBS diagnostic age.')
        if type(trace.get('sentinel_attempt')) is not int or trace['sentinel_attempt'] not in (0,1) or type(trace.get('bracket')) is not bool:
            raise ValueError('Invalid SBS trace attempt/bracket.')
        for key in ('command','completion_status','bus_status','worker_result'):
            value=trace.get(key)
            if value is not None and (type(value) is not int or not 0<=value<=255):raise ValueError('Invalid SBS diagnostic byte.')
        if trace.get('command') is not None and trace['command'] not in (0x1a,3,8,9,10,11,20,21,12,13,14,15,16,23,24,25):
            raise ValueError('Unknown SBS trace command.')
        if transport=='native_smbus_read_word':
            if trace.get('bus_status') is not None or trace.get('worker_result') not in (None,0,1) or trace.get('software_observation') is not None:
                raise ValueError('Native SBS trace contains invalid or legacy status metadata.')
            if not trace['result'] and (trace.get('completion_status')!=0 or trace.get('worker_result')!=1):
                raise ValueError('Native SBS success lacks qualified worker completion.')
        elif trace.get('worker_result') is not None:raise ValueError('Legacy SBS trace contains native worker metadata.')
        software=trace.get('software_observation')
        if software is not None:
            if not isinstance(software,dict) or type(software.get('result')) is not int or not -4095<=software['result']<=0 or software.get('atomic') is not False or software.get('current_operation_proven') is not False:
                raise ValueError('Invalid SBS software observation metadata.')
            if software['result']:
                if software.get('raw_hex') is not None:raise ValueError('Failed SBS software observation has raw bytes.')
            else:
                raw=software.get('raw_hex')
                if not isinstance(raw,str) or len(raw)!=8:raise ValueError('Invalid SBS software observation length.')
                try:raw=bytes.fromhex(raw)
                except ValueError:raise ValueError('Invalid SBS software observation bytes.') from None
                if len(raw)!=4 or raw[1]!=0 or raw[2]!=1 or raw[3]>1:raise ValueError('SBS software observation does not match the qualified context.')
    return {'available':True,**data,'source':'Cached module-local observations of existing SBS operations',
            'note':'Attempt counters cover this module instance. This cached read performs no controller access. Optional software observations are non-atomic double samples of firmware SRAM copies before mandatory IPC restoration; they may be stale/reused and do not prove a current hardware fault. Historical failures remain visible after recovery; successful recovery alone does not prove a protocol fix.'}


def diagnostics():return battery.read('battery_sbs_diagnostics',decode_diagnostics)
