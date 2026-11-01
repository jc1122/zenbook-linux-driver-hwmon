# SPDX-License-Identifier: GPL-2.0-only
"""Existing Linux temperature and firmware-storage metadata providers."""
from pathlib import Path
import firmware_queries


def temperatures(root=Path('/sys/class/hwmon')):
    result={}
    for device in root.glob('hwmon*'):
        try:name=(device/'name').read_text().strip()
        except OSError:continue
        if name=='zenbook_ec':continue
        for sensor in device.glob('temp*_input'):
            try:value=int(sensor.read_text())/1000
            except (OSError,ValueError):continue
            label=sensor.with_name(sensor.name.replace('_input','_label'))
            try:label=label.read_text().strip()
            except OSError:label=sensor.name.replace('_input','')
            key=name+'/'+label
            if key in result:key=name+'/'+device.name+'/'+label
            result[key]=value
    return result


def firmware_storage(root=Path('/sys/bus/nvmem/devices'),mtd=Path('/sys/class/mtd')):
    """Inventory only: never open nvmem contents, BIOS secrets or CMOS data."""
    result=[]
    for device in sorted(root.iterdir()) if root.exists() else []:
        content=device/'nvmem'
        if not content.exists():continue
        row={'provider':device.name,'bytes':content.stat().st_size,'contents_read':False}
        if device.name.startswith('mtd'):
            try:
                row['region']=(mtd/device.name/'name').read_text().strip()
                flags=int((mtd/device.name/'flags').read_text(),0)
                row['writable']=bool(flags&0x400)
            except (OSError,ValueError):pass
        else:row['region']='CMOS NVRAM' if device.name.startswith('cmos_nvram') else 'NVMEM'
        result.append(row)
    table=firmware_queries.report()['eeprom_table']
    known_absent=table.get('status')=='firmware_unsupported'
    return {'storage':result,'asus_eeprom_table_available':True if table['available'] else False if known_absent else None,'asus_eeprom_table':table,
            'note':'BIOS/CMOS storage inventory is separate from the ASUS EEPROM diagnostic table.'}
