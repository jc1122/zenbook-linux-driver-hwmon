# SPDX-License-Identifier: GPL-2.0-only
"""Fixed read-only UCSI diagnostics for the qualified ASUS ACPI controller.

No power/role/reset command is accepted. Decoded PDO profiles have unverified
target identity and are not live measurements. Firmware quirks remain explicit.
"""
from pathlib import Path
import errno
import fcntl
import os
import re
import pd_contract
import pd_sources
import pd_identity
import charger_adc
import charger_metrics

ROOT=Path('/sys/kernel/debug/usb/ucsi/USBC000:00')
COMMANDS={'capability':0x06,'connector_capability':0x10007,
          'connector_status':0x10012,'partner_source_pdos':0x700810010}


def decode_pdo(raw):
    kind=raw>>30
    row={'raw_hex':f'0x{raw:08x}','type':('fixed','battery','variable','augmented')[kind]}
    if kind==0:
        row.update(voltage_volts=((raw>>10)&1023)*.05,max_current_amperes=(raw&1023)*.01)
        row['max_power_watts']=round(row['voltage_volts']*row['max_current_amperes'],3)
    return row


def decode_asus_source_pdos(data):
    # Observed UP3404VA.301 quirk: a count byte precedes PDOs; debugfs returns
    # only 16 bytes and the firmware ignores the offset/count request fields.
    # Decode complete objects only. Never invent the missing final flag byte.
    if len(data)!=16 or not 1<=data[0]<=7:
        raise OSError(errno.EPROTO,'Unexpected qualified ASUS PDO response layout.')
    count=data[0];complete=min(count,(len(data)-1)//4)
    rows=[decode_pdo(int.from_bytes(data[1+4*i:5+4*i],'little')) for i in range(complete)]
    if any(x['type']=='fixed' and (not .1<=x['voltage_volts']<=50 or not 0<x['max_current_amperes']<=10) for x in rows):
        raise OSError(errno.EPROTO,'Invalid advertised source PDO.')
    return {'reported_count':count,'complete_pdos':rows,'complete':complete==count,
            'truncated_bytes_hex':data[1+4*complete:].hex() if complete<count else '',
            'maximum_profile_watts':max((r['max_power_watts'] for r in rows if 'max_power_watts' in r),default=None) if complete==count else None,
            'measurement':False,'target_verified':False,
            'note':'Firmware repeats this payload for local/partner and source/sink selections; these are diagnostic profiles, not verified charger capabilities or a negotiated contract.',
            'source':'qualified ASUS count-prefixed UCSI GET_PDOS'}


def decode_response(text):
    if not re.fullmatch(r'0x[0-9a-fA-F]{32}',text.strip()):raise OSError(errno.EPROTO,'Invalid UCSI debugfs response.')
    return int(text.strip(),16).to_bytes(16,'little')


def query(root,name,connector=1):
    if name not in COMMANDS:raise ValueError('Only fixed GET diagnostic queries are supported.')
    if isinstance(connector,bool) or connector not in (1,2):raise ValueError('connector must be 1 or 2.')
    command=COMMANDS[name]
    if name!='capability':command=(command&~(0x7f<<16))|(connector<<16)
    (root/'command').write_text(hex(command)+'\n')
    return decode_response((root/'response').read_text())


def ucsi_report(connector=None):
    if os.geteuid()!=0:raise PermissionError(errno.EACCES,'UCSI diagnostics require privilege.')
    if Path('/sys/class/dmi/id/product_name').read_text().strip()!='Zenbook Flip UP3404VA_UP3404VA' or Path('/sys/class/dmi/id/bios_version').read_text().strip()!='UP3404VA.301':
        raise OSError(errno.ENODEV,'This UCSI response quirk is qualified only for UP3404VA.301.')
    if not ROOT.exists():raise OSError(errno.ENODEV,'Kernel UCSI debugfs provider is unavailable.')
    connected=[]
    for index in (0,1):
        partner=Path('/sys/class/typec')/('port'+str(index))/('port'+str(index)+'-partner')
        try:pd=(partner/'supports_usb_power_delivery').read_text().strip()=='yes'
        except OSError:pd=False
        if pd:connected.append(index+1)
    if connector is None:
        if len(connected)!=1:raise OSError(errno.ENODEV if not connected else errno.EBUSY,'Select one connected PD connector with --connector 1 or 2.')
        connector=connected[0]
    if connector not in connected:raise OSError(errno.ENODEV,'Selected connector has no connected PD partner.')
    directory=Path('/run/zenbook-hardware');directory.mkdir(exist_ok=True,mode=0o700)
    fd=os.open(directory/'ucsi.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX)
        result={'connector':connector,'source':'Linux UCSI','queries':{},'live_measurements':{}}
        for name in COMMANDS:
            try:
                data=query(ROOT,name,connector)
                result['queries'][name]={'raw_hex':data.hex()}
                if name=='partner_source_pdos':result['firmware_pd_profiles']=decode_asus_source_pdos(data)
            except OSError as error:result['queries'][name]={'errno':error.errno,'error':str(error)}
        # These kernel debug counters refer to the first connector. Never
        # attribute them to connector two without a per-connector provider.
        for file,key,unit in [('vbus_voltage','voltage_volts',1000),('avg_current','average_current_amperes',1000),('peak_current','peak_current_amperes',1000)]:
            raw=int((ROOT/file).read_text().split()[0]) if connector==1 else 0
            result['live_measurements'][key]=raw/unit if raw>0 else None
        result['live_measurements']['available']=result['live_measurements']['voltage_volts'] is not None
        return result
    finally:os.close(fd)


def report(connector=None):
    if connector is not None and (isinstance(connector,bool) or connector not in (1,2)):
        raise ValueError('connector must be 1 or 2.')
    result=pd_contract.report()
    result['platform_power']=pd_contract.platform_power()
    result['source_capabilities']=pd_sources.report()
    result['received_identities']=pd_identity.report()
    result['controller_metrics']=charger_metrics.report()
    measured=charger_adc.report()
    active=[p for p in result['ports'] if p['available']]
    measured['connector']=active[0]['connector'] if measured['available'] and len(active)==1 else None
    result['input_measurements']=measured
    result['instantaneous_measurements_available']=measured['available']
    for port in result['ports']:
        port['input_measurements']=measured if measured['available'] and measured['connector']==port['connector'] else {'available':False,'measurement':False}

    if connector is not None:result['ports']=[p for p in result['ports'] if p['connector']==connector]
    try:result['ucsi_diagnostics']=ucsi_report(connector)
    except OSError as error:result['ucsi_diagnostics']={'errno':error.errno,'error':str(error)}
    return result
