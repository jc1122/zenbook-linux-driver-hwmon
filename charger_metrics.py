# SPDX-License-Identifier: GPL-2.0-only
"""Qualified charger die/pin ADCs and non-clearing protection status."""
import errno
import json
import os
import native_oem

REGISTERS=(0xfe,0xff,0x4c,0x4e,0x4d,0x82,0x81,0x84,0x85,0x86,0x3a,0x91,0x4d,0x4c)
STATUS_BITS={0:'diode_mode',1:'reverse_turbo_mode',2:'bypass_gate_power_good',3:'ngate_power_good',
             4:'trickle_charge',5:'input_above_system_voltage',6:'battery_gate_power_good',
             10:'low_system_voltage_prochot',11:'battery_overcurrent_prochot',12:'adapter_overcurrent_prochot',15:'internal_reference_active'}
LIVE_BITS={0:'ntc_boundary_status',1:'ready',2:'fet_fault',3:'charge_cc_to_cv',4:'autonomous_charge_terminated',
           5:'otg_power_good',6:'thermal_warning',7:'input_current_loop_selected',8:'input_voltage_loop_selected',
           9:'input_overvoltage',10:'system_overvoltage',11:'autonomous_charge_timer_expired',12:'smbus_timeout'}
STATES={0:'reset',2:'autonomous_charging',4:'battery_low_power',6:'charging',7:'fault',9:'otg_or_supplemental',10:'ready',12:'system_regulation'}
MODES={0:'off',1:'forward_boost',2:'forward_buck',3:'forward_buck_boost',5:'otg_boost',6:'otg_buck',7:'otg_buck_boost'}


def decode(data):
    if not isinstance(data,dict):raise OSError(errno.EPROTO,'Charger metrics reply is not a JSON object.')
    w=data.get('words')
    if (data.get('schema')!=1 or not isinstance(w,list) or len(w)!=14 or
        any(type(n) is not int or not 0<=n<=65535 for n in w) or w[:2]!=[0x49,0x0e] or
        w[11]&~0x1fff or w[12]&0x8000):raise OSError(errno.EPROTO,'Invalid charger metrics identity/status.')
    state=(w[12]>>8)&15;mask=0;expected={}
    adc=bool(w[2]&1 and w[13]&1 and not (w[4]^w[12])&0xf00 and state in (2,6,9,10,12))
    if adc:
        n=(2517-10*w[5])*1_000_000
        temp=(abs(n)//6154)*(-1 if n<0 else 1)
        if 0<w[5]<255 and -10000<=temp<=170000:mask|=1;expected['die_millicelsius']=temp
        vbat=(w[6]>>6)*64
        if not w[6]&~0x3fc0 and 2500<=vbat<=17000:mask|=2;expected['vbat_pin_millivolts']=vbat
        system=(w[9]>>6)*96
        if not w[9]&~0x3fc0 and 2500<=system<=24500:mask|=4;expected['system_millivolts']=system
        if not w[3]&0x800:
            if w[7]<255:mask|=8;expected['discharge_microamps']=w[7]*88800
            if w[8]<255:mask|=16;expected['charge_microamps']=w[8]*44400
    expected.update(valid_mask=mask,battery_shunt_milliohms=5,maximum_cache_seconds=2)
    if (any(type(data.get(k)) is not int or data[k]!=v for k,v in expected.items()) or
        type(data.get('age_milliseconds')) is not int or not 0<=data['age_milliseconds']<=2000):
        raise OSError(errno.EPROTO,'Charger metrics conversion/freshness mismatch.')
    def value(bit,key,scale):return data[key]/scale if mask&bit else None
    return {'available':True,'adc_available':bool(mask),'source':'ISL9241 via firmware-mediated fixed read-only queries',
            'die_temperature_celsius':value(1,'die_millicelsius',1000),
            'vbat_pin_voltage_volts':value(2,'vbat_pin_millivolts',1000),
            'system_voltage_volts':value(4,'system_millivolts',1000),
            'battery_discharge_current_amperes':value(8,'discharge_microamps',1_000_000),
            'battery_charge_current_amperes':value(16,'charge_microamps',1_000_000),
            'status':{'state':STATES.get(state,'startup_or_unknown'),'power_stage':MODES.get((w[12]>>5)&7,'unknown'),
                      'adapter_present':bool(w[12]&0x4000),'battery_present':not bool(w[12]&0x1000),
                      'active_control_loop':('system_voltage','charge_current','input_current','input_voltage')[(w[10]>>13)&3],
                      'information1':{name:bool(w[10]&(1<<bit)) for bit,name in STATUS_BITS.items()},
                      'live_protection':{name:bool(w[11]&(1<<bit)) for bit,name in LIVE_BITS.items()}},
            'raw_registers':{f'0x{r:02x}':w[i] for i,r in enumerate(REGISTERS)},
            'resolutions':{'die_temperature_celsius':1/.6154,'vbat_pin_voltage_volts':.064,'system_voltage_volts':.096,
                           'battery_charge_current_amperes':.0444,'battery_discharge_current_amperes':.0888},
            'battery_shunt_milliohms':5,'age_milliseconds':data['age_milliseconds'],'maximum_cache_seconds':2,
            'note':'VBAT is the charger IC pin reading; battery-gauge pack voltage is separate. Protection flags are live, not an interrupt-history log. Current scaling is model-qualified; external meter calibration is unverified.'}


def report():
    try:
        fd=os.open(native_oem.device()/'charger_metrics',os.O_RDONLY|os.O_CLOEXEC)
        try:data=json.loads(os.read(fd,4096))
        finally:os.close(fd)
        return decode(data)
    except (OSError,RuntimeError,ValueError,TypeError) as error:
        return {'available':False,'source':'ISL9241 extra metrics','errno':getattr(error,'errno',None) or errno.ENODEV,'error':str(error)}
