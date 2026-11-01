# SPDX-License-Identifier: GPL-2.0-only
"""Read-only nl80211 link and cached BSS measurements; no scan or connection call."""
from pathlib import Path
import errno
import math
import re
import subprocess

NET_ROOT=Path('/sys/class/net')
LINK_NAMES={'RF_WiFiIsConnected','RF_AP_MAC','RF_PhyMode','RF_WiFiRssi','RF_WiFiMaxRate','RF_WiFiChannel','RF_WiFi_Main_Aux_Rssi'}
RSSI_NAMES={f'RF_WiFi_{band}_AP_RSSI_Num':band for band in ('2_4G','5G','6G')}
CACHE_NAMES={'RF_WiFi_2_4G_AP_Ch_Num','RF_WiFi_2_4G_AP_Num','RF_WiFi_5G_AP_Band_Num','RF_WiFi_5G_AP_Num','RF_WiFi_6G_AP_NUII_Num','RF_WiFi_6G_AP_Num'}
CARD_NAMES={'RF_WiFiCardName','WMIGetWiFiCardName'}
MAC=r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}'


def identity(path):
    info=path.stat();raw=(path/'ifindex').read_text().strip()
    if not re.fullmatch(r'[0-9]{1,10}',raw) or not 0<int(raw)<=0x7fffffff:
        raise OSError(errno.EPROTO,'Invalid wireless interface index.')
    return info.st_dev,info.st_ino,int(raw)


def interfaces(root):
    result=[]
    for path in sorted(root.iterdir()):
        try:(path/'wireless').stat()
        except FileNotFoundError:continue
        if not re.fullmatch(r'[^/\s\x00]{1,15}',path.name) or path.name in ('.','..'):
            raise OSError(errno.EPROTO,'Invalid wireless interface name.')
        result.append(path)
    return result


def query(iface,operation):
    if not re.fullmatch(r'[^/\s\x00]{1,15}',iface) or operation not in (('link',),('station','dump'),('scan','dump')):
        raise ValueError('Only fixed wireless link/station/cache reads are accepted.')
    import linux_services
    try:proc=subprocess.run([linux_services.system_tool('iw'),'dev',iface,*operation],capture_output=True,text=True,timeout=5)
    except subprocess.TimeoutExpired:raise OSError(errno.ETIMEDOUT,'Wireless read timed out.') from None
    if proc.returncode:raise OSError(errno.EACCES if 'permitted' in proc.stderr.lower() else errno.ENODATA,'Wireless read-only query failed.')
    if len(proc.stdout)>2_000_000:raise OSError(errno.EOVERFLOW,'Wireless reply exceeds its bounded parser size.')
    return proc.stdout


def band(frequency):
    if 2400<=frequency<2500:return '2_4G'
    if 4900<=frequency<5925:return '5G'
    if 5925<=frequency<7125:return '6G'
    return None


def channel(frequency):
    if type(frequency) is not int:return None
    if frequency==2484:return 14
    if 2412<=frequency<=2472 and (frequency-2407)%5==0:return (frequency-2407)//5
    if 4910<=frequency<=4980 and frequency%5==0:return (frequency-4000)//5
    if 5000<frequency<5925 and frequency%5==0:return (frequency-5000)//5
    if frequency==5935:return 2
    if 5955<=frequency<=7115 and frequency%5==0:return (frequency-5950)//5
    if 58320<=frequency<=70200 and (frequency-56160)%2160==0:return (frequency-56160)//2160
    return None


def dbm(text,pattern):
    match=re.search(pattern,text,re.M)
    if not match:return None
    value=float(match[1])
    return value if math.isfinite(value) and -150<=value<=50 else None


def parse_link(text,iface):
    if text.strip()=='Not connected.':return {'connected':False,'peer':None,'frequency_mhz':None}
    match=re.search(r'^Connected to ('+MAC+r') \(on '+re.escape(iface)+r'\)',text,re.M)
    if not match:raise OSError(errno.EPROTO,'Unrecognized wireless link reply; connection state is unknown.')
    freq=re.search(r'^\s*freq:\s*([0-9]+(?:\.[0-9]+)?)\s*$',text,re.M)
    frequency=float(freq[1]) if freq else None
    if frequency is not None and frequency.is_integer():frequency=int(frequency)
    if frequency is not None and not 100<=frequency<=100000:frequency=None
    rates={}
    for direction in ('tx','rx'):
        match_rate=re.search(r'^\s*'+direction+r' bitrate:\s*([0-9]+(?:\.[0-9]+)?) MBit/s(?:\s|$)',text,re.M)
        value=float(match_rate[1]) if match_rate else None
        rates[direction]=value if value is not None and math.isfinite(value) and 0<value<=1_000_000 else None
    rate_lines='\n'.join(re.findall(r'^\s*(?:tx|rx) bitrate:.*$',text,re.M))
    phy=next((name for marker,name in [('EHT-MCS','802.11be'),('HE-MCS','802.11ax'),('VHT-MCS','802.11ac'),('MCS','802.11n')] if re.search(r'(?<![-\w])'+marker+r'\s+[0-9]+\b',rate_lines)),None)
    return {'connected':True,'peer':match[1].lower(),'frequency_mhz':frequency,'channel':channel(frequency),
            'signal_dbm':dbm(text,r'^\s*signal:\s*([+-]?[0-9]+(?:\.[0-9]+)?)\s+dBm\s*$'),
            'reported_rates_mbit':rates,'maximum_reported_link_rate_mbit':max((v for v in rates.values() if v is not None),default=None),
            'phy':phy}


def association(row):return row['connected'],row['peer'],row['frequency_mhz']


def links(root=None):
    root=NET_ROOT if root is None else root;rows=[]
    try:
        paths=interfaces(root)
        if not paths:raise OSError(errno.ENODEV,'No wireless interfaces are available.')
        for path in paths:
            row={'interface':path.name,'available':False,'connected':None}
            try:
                before=identity(path);first=parse_link(query(path.name,('link',)),path.name)
                second=parse_link(query(path.name,('link',)),path.name)
                if before!=identity(path) or association(first)!=association(second):
                    raise OSError(errno.EAGAIN,'Wireless interface or association changed during sampling.')
                row.update(first,available=True)
            except OSError as error:row.update(errno=error.errno or errno.EIO,error=str(error))
            rows.append(row)
        if [p.name for p in paths]!=[p.name for p in interfaces(root)]:
            raise OSError(errno.EAGAIN,'Wireless interface inventory changed during sampling.')
        positive=any(row['connected'] is True for row in rows);unknown=next((r for r in rows if not r['available']),None)
        result={'available':unknown is None,'interfaces':rows,'connected':True if positive else None if unknown else False,
                'source':'Linux nl80211 via fixed iw link reads','note':'Sequential driver-reported RSSI/rates, not throughput or maximum card capability. Missing fields remain unavailable. No NetworkManager, scan, connect or device setting is used.'}
        if unknown:result.update(errno=unknown['errno'],error=unknown['error'])
        return result
    except OSError as error:return {'available':False,'interfaces':rows,'connected':None,'errno':error.errno or errno.EIO,'error':str(error)}


def cards():
    import wireless_inventory
    return wireless_inventory.cards()


def selected_link():
    report=links()
    if report['connected'] is None:raise OSError(report['errno'],report['error'])
    connected=[row for row in report['interfaces'] if row.get('connected') is True and row['available']]
    if not connected:raise OSError(report.get('errno',errno.ENODATA),report.get('error','No associated wireless link is available.'))
    return connected[0]  # Deterministic first associated interface by kernel name.


def chains(iface,peer,text):
    blocks=re.split(r'(?m)^Station ',text)[1:]
    matches=[block for block in blocks if re.match(re.escape(peer)+r' \(on '+re.escape(iface)+r'\)',block,re.I)]
    if len(matches)!=1:raise OSError(errno.ENODATA,'No unique active-peer station measurement is available.')
    match=re.search(r'^\s*signal:\s*([+-]?[0-9]+)(?:\s*\[([^]]+)\])?\s+dBm\s*$',matches[0],re.M)
    if not match:raise OSError(errno.ENODATA,'Active station has no dBm signal reading.')
    raw=match[2];values=[]
    # Bound digit counts before int(): huge decimal strings exceed Python's
    # int-string limit (ValueError) instead of being a protocol error.
    if len(match[1].lstrip('+-'))>4:raise OSError(errno.EPROTO,'Invalid station signal range.')
    aggregate=int(match[1])
    if raw is not None:
        if len(raw)>256 or not re.fullmatch(r'\s*[+-]?[0-9]{1,4}(?:\s*,\s*[+-]?[0-9]{1,4})*\s*',raw):raise OSError(errno.EPROTO,'Invalid per-chain signal values.')
        values=[int(x) for x in raw.split(',')]
    if not -128<=aggregate<=127 or len(values)>16 or any(not -128<=x<=127 for x in values):
        raise OSError(errno.EPROTO,'Invalid station signal range.')
    return {'aggregate_dbm':aggregate,'chains_dbm':values,'chain_signal_available':bool(values),'physical_main_aux_mapping':'unverified'}


def parse_bss(text):
    if not text.strip():return []
    blocks=re.split(r'(?m)^BSS ',text)
    if len(blocks)<2 or blocks[0].strip():raise OSError(errno.EPROTO,'Unrecognized cached BSS reply.')
    result=[]
    for block in blocks[1:]:
        match=re.match('('+MAC+r')(?:\s|\()',block)
        freq=re.search(r'^\s*freq:\s*([0-9]+(?:\.[0-9]+)?)\s*$',block,re.M)
        if not match or not freq or not 100<=float(freq[1])<=100000:
            raise OSError(errno.EPROTO,'Cached BSS identity/frequency is incomplete.')
        frequency=float(freq[1]);frequency=int(frequency) if frequency.is_integer() else frequency
        result.append({'bssid':match[1].lower(),'frequency_mhz':frequency,
            'signal_dbm':dbm(block,r'^\s*signal:\s*([+-]?[0-9]+(?:\.[0-9]+)?)\s+dBm\s*$')})
    return result


def validate(name,args):
    if not isinstance(args,dict):raise ValueError('Wireless arguments must be an object.')
    if name in RSSI_NAMES:
        value=args.get('threshold_dbm',-65)
        # Range-check before math.isfinite(): it raises OverflowError for huge ints.
        if set(args)-{'threshold_dbm'} or type(value) not in (int,float) or not -120<=value<=0 or not math.isfinite(value):
            raise ValueError('Only a finite numeric threshold_dbm in-120..0 is accepted.')
    elif args:raise ValueError('This wireless read takes no arguments.')


def rssi_count(name,args):
    validate(name,args);threshold=args.get('threshold_dbm',-65);groups={};paths=interfaces(NET_ROOT)
    if not paths:raise OSError(errno.ENODEV,'No wireless interfaces are available.')
    for path in paths:
        before=identity(path);rows=parse_bss(query(path.name,('scan','dump')))
        if before!=identity(path):raise OSError(errno.EAGAIN,'Wireless interface changed during cached BSS read.')
        for row in rows:
            if band(row['frequency_mhz'])==RSSI_NAMES[name]:
                groups.setdefault((row['bssid'],row['frequency_mhz']),[]).append(row['signal_dbm'])
    if [p.name for p in paths]!=[p.name for p in interfaces(NET_ROOT)]:
        raise OSError(errno.EAGAIN,'Wireless interface inventory changed during cached BSS read.')
    count=0
    for values in groups.values():
        if any(value is not None and value>=threshold for value in values):count+=1
        elif any(value is None for value in values):raise OSError(errno.ENODATA,'Cached target-band BSS lacks measured dBm; relative quality cannot determine RSSI count.')
    return count


def call(name,args):
    validate(name,args)
    import wireless_native
    if name in wireless_native.NAMES:return wireless_native.require(name,args)
    if name=='RF_WiFiIsConnected':
        report=links()
        if report['connected'] is None:raise OSError(report['errno'],report['error'])
        return report['connected']
    row=selected_link()
    if name=='RF_WiFi_Main_Aux_Rssi':
        iface=row['interface'];path=NET_ROOT/iface;before=identity(path)
        value=chains(iface,row['peer'],query(iface,('station','dump')))
        if before!=identity(path) or association(row)!=association(parse_link(query(iface,('link',)),iface)):
            raise OSError(errno.EAGAIN,'Wireless association changed during station measurement.')
        return value
    key={'RF_AP_MAC':'peer','RF_PhyMode':'phy','RF_WiFiRssi':'signal_dbm','RF_WiFiMaxRate':'maximum_reported_link_rate_mbit','RF_WiFiChannel':'channel'}[name]
    if row.get(key) is None:raise OSError(errno.ENODATA,'Associated wireless link lacks the requested measured metadata.')
    return row[key]
