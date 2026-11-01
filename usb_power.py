# SPDX-License-Identifier: GPL-2.0-only
"""Read-only UCSI power roles and contract/advertisement metadata, never ADCs."""
from pathlib import Path
import errno
import re

ROOT=Path('/sys/class/power_supply')
FIELDS={'voltage_now':'selected_voltage_volts','current_now':'requested_or_advertised_current_amperes',
        'voltage_max':'maximum_advertised_voltage_volts','current_max':'maximum_advertised_current_amperes'}


def identity(path):
    stat=path.stat()
    return stat.st_dev,stat.st_ino


def state(path):
    online=(path/'online').read_text().strip()
    status=(path/'status').read_text().strip()
    types=(path/'usb_type').read_text().strip()
    if online not in ('0','1','2') or status not in ('Charging','Discharging','Not charging','Unknown'):
        raise OSError(errno.EPROTO,'Invalid UCSI online/status value.')
    selected=re.findall(r'\[([A-Z0-9_]+)\]',types)
    tokens=types.split()
    if len(selected)!=1 or selected[0] not in ('C','PD','PD_PPS') or any(
            token not in ('C','PD','PD_PPS','[C]','[PD]','[PD_PPS]') for token in tokens):
        raise OSError(errno.EPROTO,'Invalid or unknown selected UCSI USB type.')
    if status=='Unknown':raise OSError(errno.ENODATA,'UCSI power status is unknown.')
    online=int(online)
    if (online==0 and status=='Charging') or (online!=0 and status=='Discharging'):
        raise OSError(errno.EAGAIN,'UCSI power role/status is inconsistent.')
    return online,status,types,selected[0]


def supplies(root):
    return sorted((p for p in root.iterdir() if p.name.startswith('ucsi-source-psy-')),key=lambda p:p.name)


def rows(root,include_values):
    paths=supplies(root);result=[]
    for path in paths:
        row={'port':path.name,'available':False,'online':None,'status':None,'usb_type':None,
             'selected_usb_type':None,'power_role':None,'pd_input_online':None,
             'voltage_volts':None,'current_amperes':None,'max_voltage_volts':None,'max_current_amperes':None,
             'electrical_measurements_available':False,'source':'Linux UCSI power_supply; contract/advertisement metadata'}
        try:
            before=identity(path);first=state(path)
            online,status,types,selected=first
            values={key:None for key in FIELDS.values()};errors={}
            # Offline supplies can retain defaults. A source-facing connected
            # port can advertise current with online=0; that is not local input.
            if include_values and (online or status=='Discharging'):
                for name,key in FIELDS.items():
                    try:
                        raw=(path/name).read_text().strip()
                        limit=50_000_000 if name.startswith('voltage') else 10_000_000
                        if not re.fullmatch(r'[0-9]{1,10}',raw):raise OSError(errno.EPROTO,'Invalid UCSI electrical metadata.')
                        value=int(raw)
                        if not 0<value<=limit:raise OSError(errno.ENODATA,'UCSI contract/advertisement value is unavailable.')
                        values[key]=value/1_000_000
                    except OSError as error:errors[name]={'errno':error.errno or errno.EIO,'error':str(error)}
            if first!=state(path) or before!=identity(path):
                raise OSError(errno.EAGAIN,'UCSI supply or power state changed during sampling.')
            row.update(available=True,online=online,status=status,usb_type=types,selected_usb_type=selected,
                       power_role='sink' if online else 'source' if status=='Discharging' else None,
                       pd_input_online=bool(online and status=='Charging' and selected in ('PD','PD_PPS')))
            if include_values:
                row['ucsi_values']={'measurement':False,'contract_verified':False,**values,'errors':errors,
                    'semantics':'PD source/request values' if selected in ('PD','PD_PPS') else 'Type-C nominal voltage/current advertisement',
                    'note':'Kernel-reported values; PDO type and partner target are not independently qualified here. Independent advertised maxima may belong to different PDOs. These values cannot be multiplied into measured power.'}
        except OSError as error:row.update(errno=error.errno or errno.EIO,error=str(error))
        result.append(row)
    if [p.name for p in paths]!=[p.name for p in supplies(root)]:
        raise OSError(errno.EAGAIN,'UCSI power supply inventory changed during sampling.')
    return result


def result(root=None,include_values=True):
    try:
        ports=rows(ROOT if root is None else root,include_values)
        if not ports:raise OSError(errno.ENODEV,'No UCSI power supply provider is available.')
        # A known positive survives another port's unavailable state. A negative
        # requires all ports to have known state; failed reads never become off.
        positive=any(p['pd_input_online'] is True for p in ports)
        unknown=next((p for p in ports if not p['available']),None)
        answer=True if positive else None if unknown else False
        value={'available':unknown is None,'ports':ports,'pd_input_online':answer,
               'electrical_measurements_available':False}
        if unknown:value.update(errno=unknown['errno'],error=unknown['error'])
        return value
    except OSError as error:
        return {'available':False,'ports':[],'pd_input_online':None,'electrical_measurements_available':False,
                'errno':error.errno or errno.EIO,'error':str(error)}


def pd_input_online():
    report=result(include_values=False)
    if report['pd_input_online'] is None:raise OSError(report['errno'],report['error'])
    return report['pd_input_online']
