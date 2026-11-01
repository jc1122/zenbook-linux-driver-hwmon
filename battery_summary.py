# SPDX-License-Identifier: GPL-2.0-only
"""Source-correct battery summary quantities and complete cell-channel reports."""
from pathlib import Path
import errno
import re
import qualified_ec
from platform_metadata import text

NAMES={'Battery_Read_ASOC','Battery_Read_Capacity','Battery_Read_CellVoltage','BatteryHealthyTable_ECChipID'}


def validate(name,args):
    if name not in NAMES:raise ValueError('Unknown battery summary query.')
    if not isinstance(args,dict) or args:raise ValueError('Battery summary queries take no arguments.')


def unsigned(path):
    value=text(path)
    if not re.fullmatch(r'[0-9]{1,20}',value) or int(value)>2**64-1:
        raise OSError(errno.EPROTO,'Invalid battery charge counter.')
    return int(value)


def charge_summary(name,root=Path('/sys/class/power_supply/BAT0')):
    def identity():
        item=root.stat()
        if text(root/'type')!='Battery' or text(root/'present')!='1':
            raise OSError(errno.ENODEV,'Qualified battery is not present.')
        return item.st_dev,item.st_ino
    before=identity()
    if name=='Battery_Read_ASOC':
        full=unsigned(root/'charge_full');design=unsigned(root/'charge_full_design')
        if design==0:raise OSError(errno.ENODATA,'No positive design charge capacity.')
        if full!=unsigned(root/'charge_full') or design!=unsigned(root/'charge_full_design'):
            raise OSError(errno.EAGAIN,'Battery full/design charge counters changed during sampling.')
        result=full/design
    else:
        remaining=unsigned(root/'charge_now')
        result={'value':remaining/1000,'units':'mAh','quantity':'remaining_charge',
                'source':'Linux power_supply charge_now in microamp-hours divided by1000',
                'note':'Native remaining charge; no energy or relative-unit value is inferred.'}
    if before!=identity():raise OSError(errno.EAGAIN,'Battery identity changed during sampling.')
    return result


def cell_voltages(raw):
    rows=[];frame_complete=True
    for index in range(1,5):
        value=raw.get(f'battery_cell{index}_mV')
        valid=type(value) is int and 0<=value<=65535
        row={'channel':index,'available':valid and 0<value<65535,
             'millivolts':value if valid and 0<value<65535 else None,
             'raw_millivolts':value if valid else None}
        if not valid:frame_complete=False
        if not row['available']:
            row.update(errno=errno.ENODATA if value is None or type(value) is int and value in (-1,0,65535) else errno.EPROTO,
                       error='No valid positive cell-channel voltage.' if value is None or type(value) is int and value in (-1,0,65535) else 'Invalid cell-channel voltage field.')
        rows.append(row)
    measured=sum(row['available'] for row in rows)
    result={'available':measured>0,'cells':rows,'frame_complete':frame_complete,'measured_channels':measured,
            'source':'Qualified HealthyTable bank1 cell-voltage channels1..4, millivolts',
            'note':'All four source channels are retained. Raw zero/sentinels do not become measured zero volts or a claim about installed cell count.'}
    if measured==0:result.update(errno=errno.ENODATA,error='No measured cell-channel voltage.')
    return result


def call(name,args):
    validate(name,args)
    if name in {'Battery_Read_ASOC','Battery_Read_Capacity'}:return charge_summary(name)
    raw,_=qualified_ec.snapshot()
    if name=='BatteryHealthyTable_ECChipID':return raw['chip_id']
    return cell_voltages(raw)
