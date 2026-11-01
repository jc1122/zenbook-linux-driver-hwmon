# SPDX-License-Identifier: GPL-2.0-only
"""Complete gauge-returned power and algorithm-temperature frames.

Powers are computed by the gauge from its sampled voltage/current, not by a
charger-input estimator or an independent power ADC. Positive means charging.
"""
import errno
import battery_diagnostics as battery


def decode(data):
    battery.validate(data,15)
    a=battery.payload(data,'da1_hex',32);t=battery.payload(data,'da2_hex',24)
    volts=[battery.word(a,2*i) for i in range(4)]
    if not all(2000<=v<=5000 for v in volts[:2]) or any(v not in (0,65535) for v in volts[2:]):
        raise OSError(errno.ENODEV,'Unqualified extra-gauge cell topology.')
    cells=[]
    for i in range(2):
        current=battery.word(a,12+2*i,True)
        raw=battery.word(a,20+2*i,True);watts=raw/100
        # Validate the declared cW encoding against the very same gauge frame.
        # Do not replace a rejected register with a locally computed power.
        valid=abs(watts-volts[i]*current/1000000)<=.03 and abs(current)<=20000
        cells.append({'cell':i+1,'voltage_volts':volts[i]/1000,'current_amperes':current/1000,
                      'power_watts':watts if valid else None,'power_raw_centiwatts':raw,
                      'power_encoding_consistent_with_frame':valid})
    total_raw=battery.word(a,28,True);average_raw=battery.word(a,30,True)
    total=total_raw/100;average=average_raw/100
    # DAStatus1 pack power uses SBS Voltage()*Current(), not the sum of
    # the individually sampled cell V/I pairs (TI SLUUCH2 16.1.63).
    # Preserve the reported register; the cell sum is a diagnostic only.
    total_valid=abs(total)<=200
    cell_sum=sum(c['power_watts'] for c in cells) if all(c['power_watts'] is not None for c in cells) else None
    mc=battery.word(t,14)*100-273150
    # DA2 bytes16..23: uncompensated cell voltages 1..4 (TI DAStatus2 layout
    # without UserTemperature). Accept only when active cells are plausible and
    # near their compensated DA1 values and inactive cells are zero.
    uncomp=[battery.word(t,16+2*i) for i in range(4)]
    uncomp_ok=all(2000<=uncomp[i]<=5000 and abs(uncomp[i]-volts[i])<=500 for i in range(2)) and uncomp[2:]==[0,0]
    return {'available':True,'source':'Fixed OEM battery block worker; target-qualified DAStatus layout',
            'cells':cells,'gauge_power_watts':total if total_valid else None,
            'gauge_average_power_watts':average if abs(average)<=200 else None,
            'gauge_power_raw_centiwatts':total_raw,'gauge_average_power_raw_centiwatts':average_raw,
            'power_sum_comparison':{'cell_sum_watts':cell_sum,
                'pack_minus_cell_sum_watts':total-cell_sum if total_valid and cell_sum is not None else None,
                'time_alignment_verified':False,'used_as_validity_gate':False},
            'gauging_temperature_celsius':mc/1000 if -40000<=mc<=125000 else None,
            'power_resolution_watts':.01,'power_computed_by_gauge':True,
            'independent_power_adc':False,'age_milliseconds':data['age_milliseconds'],
            'maximum_cache_seconds':15,'da2_tail_hex':t[16:].hex(),'unmapped_da2_tail_hex':t[16:].hex(),
            'uncompensated_cells':{'available':uncomp_ok,'cells':[{'cell':i+1,'voltage_volts':uncomp[i]/1000,
                'minus_compensated_millivolts':uncomp[i]-volts[i]} for i in range(2)] if uncomp_ok else [],
                'layout':'DAStatus2 bytes16..23 uncompensated CellVoltage1..4 (U16 mV); TI layout without UserTemperature',
                'layout_check':'active cells track DA1 compensated cells, inactive cells zero',**({} if uncomp_ok else {'errno':errno.ENODATA})},
            'note':'Signed battery-side gauge power; positive charging, negative discharge. Pack power uses gauge SBS Voltage()*Current(); cell powers use their own V/I sample pairs. A complete reply groups those quantities without establishing aligned acquisition times; the cell sum is diagnostic, not a pack validity test. The two blocks can have different sample times. Gauging temperature (DA2 bytes14..15) is an algorithm input, not an additional physical thermistor. Uncompensated cell voltages come from DA2 bytes16..23 only when the layout check passes; differences from compensated values reflect IR compensation, not a separate ADC.'}


def report():return battery.read('battery_gauge_extra',decode)
