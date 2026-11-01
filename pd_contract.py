# SPDX-License-Identifier: GPL-2.0-only
"""Qualified, read-only EC USB-C contract cache; never live ADC telemetry."""
import errno
import json
import native_oem
import time


def decode(data):
    if len(data)!=23 or data[0]!=1 or data[1]==255:
        raise OSError(errno.EPROTO,'Invalid EC PD snapshot layout/status.')
    online=bool(data[1]&1)
    ports=[]
    for index in range(2):
        offset=3+10*index
        flags,watts=data[offset:offset+2]
        if flags==255:raise OSError(errno.EPROTO,'EC PD validity read failed.')
        row={'ec_port':'AB'[index],'connector':index+1,'available':False,'contract':None}
        ports.append(row)
        # Unplug can leave old PDO bytes behind. Both AC-in and the firmware's
        # contract-valid bit must be present before any cached limit is used.
        if not online or not flags&0x40:continue
        millivolts=int.from_bytes(data[offset+2:offset+4],'little')
        milliamps=int.from_bytes(data[offset+4:offset+6],'little')
        pdo=int.from_bytes(data[offset+6:offset+10],'little')
        if pdo>>30:
            row['error']='Only the recovered fixed-supply contract format is qualified.'
            continue
        if (not 4500<=millivolts<=50000 or not 50<=milliamps<=5000 or
            millivolts!=((pdo>>10)&1023)*50 or milliamps!=(pdo&1023)*10 or
            watts in (0,255) or abs(watts-millivolts*milliamps/1_000_000)>1):
            row['error']='Inconsistent EC contract fields; no power limit accepted.'
            continue
        row.update(available=True,contract={
            'raw_pdo_hex':f'0x{pdo:08x}','type':'fixed',
            'voltage_volts':millivolts/1000,'current_limit_amperes':milliamps/1000,
            'power_limit_watts':round(millivolts*milliamps/1_000_000,3),
            'ec_reported_watts':watts,'measurement':False})
    active=[p for p in ports if p['available']]
    reported=data[2] if active and data[2]!=255 and abs(data[2]-max(p['contract']['ec_reported_watts'] for p in active))<=1 else None
    return {'source':'UP3404VA.301 EC contract cache via serialized ACPI RDER',
            'ac_online':online,'ports':ports,'ec_adapter_watts':reported,
            'snapshot_consistency':'two identical consecutive passes',
            'instantaneous_measurements_available':False,
            'note':'Voltage and current are negotiated supply limits, not instantaneous voltage/current measurements.'}


def report():
    path=native_oem.device()/'pd_contract'
    if path.exists():
        envelope=json.loads(path.read_text())
        if envelope.get('schema')!=1:raise OSError(errno.EPROTO,'Unknown public PD monitor schema.')
        return decode(bytes.fromhex(envelope['data_hex']))
    return decode(bytes.fromhex(native_oem.rpc(12)['data_hex']))


def platform_power(sleep=None):
    # The first read after an idle gap only re-primes the PSYS counter (ESTALE/
    # ENODATA, then EAGAIN inside100ms). Allow one measured retry, as for RAPL.
    sleep=sleep or time.sleep
    for attempt in range(2):
        try:
            try:value=int((native_oem.device()/'power1_input').read_text())
            except ValueError:raise OSError(errno.EPROTO,'Invalid platform power text.') from None
            if not 0<value<=1_000_000_000:raise OSError(errno.ERANGE,'Invalid platform power.')
            break
        except (OSError,RuntimeError) as error:
            code=getattr(error,'errno',None) or errno.ENODEV
            if attempt==0 and code in (errno.ENODATA,errno.ESTALE,errno.EAGAIN):
                sleep(.12);continue
            return {'available':False,'errno':code,'source':'Intel PSYS hardware energy counter'}
    return {'available':True,'watts':value/1_000_000,'measurement':True,
            'source':'Intel PSYS hardware energy counter','scope':'total platform, sampled',
            'independent_usb_c_input_measurement':False}


def selected(connector=None):
    if connector is not None and (isinstance(connector,bool) or connector not in (1,2)):
        raise ValueError('connector must be 1 or 2.')
    rows=[p for p in report()['ports'] if p['available'] and (connector is None or connector==p['connector'])]
    if len(rows)!=1:
        raise OSError(errno.ENODEV if not rows else errno.EBUSY,'Select one available EC contract with connector=1 or 2.')
    return rows[0]
