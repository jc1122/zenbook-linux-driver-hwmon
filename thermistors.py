# SPDX-License-Identifier: GPL-2.0-only
"""BIOS-labelled NTC roles, matched to the one-based EC selectors on .301."""
import native_oem

MAPPING=((1,'SSD NTC','SEN2','TSR2',0x322),(2,'Ambient NTC','SEN3','TSR9',0x329),
         (3,'CPU NTC','SEN1','TSR4',0x324),(4,'Charger NTC','SEN5','TSR5',0x325),
         (5,'DDR NTC','SEN4','TSR6',0x326))


def report():
    try:p=native_oem.device()
    except RuntimeError:return {'available':False,'sensors':[]}
    sensors=[]
    for index,label,device,field,address in MAPPING:
        try:
            actual=(p/f'temp{index+1}_label').read_text().strip()
            value=int((p/f'temp{index+1}_input').read_text())/1000
            if actual!=label or not 0<value<=125:value=None
        except (OSError,ValueError):value=None
        sensors.append({'label':label,'temperature_celsius':value,'ec_index':index,'acpi_device':device,
                        'acpi_field':field,'ec_cache_address':f'0x{address:04x}'})
    return {'available':any(s['temperature_celsius'] is not None for s in sensors),'sensors':sensors,
            'source':'UP3404VA.301 ACPI SEN1-SEN5 labels, matched to EC HealthyTable selector dispatch',
            'note':'NTCs monitor component areas; CPU/SSD/DDR NTCs are separate from internal silicon temperatures. Ambient is the BIOS sensor name, not a room-temperature measurement.'}
