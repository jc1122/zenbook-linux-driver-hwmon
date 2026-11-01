# SPDX-License-Identifier: GPL-2.0-only
"""Fixed read-only Wi-Fi metadata and sanitized root-owned monitoring cache.

No scan, connection, daemon activation, configuration, SSID or credential read.
"""
from pathlib import Path
import errno
import hashlib
import hmac
import json
import math
import os
import re
import stat
import tempfile
import time
import wireless
import wireless_capabilities as caps
from platform_metadata import text

CACHE=Path('/run/zenbook-hardware-metrics/wireless.json')
# Per-boot HMAC key for BSS keys, root-only (0600) beside the world-readable
# cache. /run is cleared at boot and the stored boot_id is checked as well.
SALT=CACHE.parent/'.salt'
SALT_LIMIT=256
NET=Path('/sys/class/net')
DEBUG=Path('/sys/kernel/debug/ieee80211')
NM='org.freedesktop.NetworkManager'
WPA='fi.w1.wpa_supplicant1'
PROP='org.freedesktop.DBus.Properties'
NAMES={'RF_WiFiMaxRate','RF_PhyMode'}|set(wireless.RSSI_NAMES)
TTL=45
LIMIT=131072


def error(e):return {'available':False,'errno':getattr(e,'errno',None) or errno.EPROTO,'error':str(e)}

def boottime():return time.clock_gettime(time.CLOCK_BOOTTIME)

def fingerprint(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def ap_key(secret,peer,frequency):
    """Salted BSS grouping key. An unsalted hash of [BSSID, frequency] can be
    brute-forced (about 2^24 BSSIDs per OUI) and then geolocated; HMAC-SHA256
    with the root-only per-boot secret keeps keys stable within a boot only."""
    if not isinstance(secret,bytes) or len(secret)<32:raise ValueError('BSS key secret is too short.')
    return hmac.new(secret,json.dumps([peer,frequency],separators=(',',':')).encode(),hashlib.sha256).hexdigest()


def _read_salt(path,boot,expected_uid):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=expected_uid or st.st_mode&0o077:raise PermissionError(errno.EACCES,'Untrusted BSS key secret.')
        raw=os.read(fd,SALT_LIMIT+1)
    finally:os.close(fd)
    try:stored_boot,value=raw.decode('ascii').split('\n')[:2]
    except (UnicodeError,ValueError):raise OSError(errno.EPROTO,'Invalid BSS key secret.') from None
    if len(raw)>SALT_LIMIT or not re.fullmatch('[0-9a-f]{64}',value):raise OSError(errno.EPROTO,'Invalid BSS key secret.')
    if stored_boot!=boot:raise OSError(errno.ESTALE,'BSS key secret belongs to another boot.')
    return bytes.fromhex(value)


def boot_salt(path=None,boot=None,expected_uid=0):
    """Return (secret, persistent). The root exporter creates the secret once
    per boot with O_EXCL semantics (link of a private 0600 temporary file), so
    concurrent collectors never overwrite it. If it cannot be read or created
    (unprivileged or sandboxed read-only caller) an ephemeral secret is used:
    keys then group observations only within that single collection."""
    path=SALT if path is None else path
    boot=text(Path('/proc/sys/kernel/random/boot_id')) if boot is None else boot
    if not isinstance(boot,str) or not re.fullmatch(r'[0-9a-f-]{1,64}',boot):return os.urandom(32),False
    for _attempt in range(2):
        try:return _read_salt(path,boot,expected_uid),True
        except FileNotFoundError:pass
        except OSError as e:
            if e.errno!=errno.ESTALE:break
            try:path.unlink()
            except OSError:break
        try:
            parent=path.parent.lstat()
            if not stat.S_ISDIR(parent.st_mode) or parent.st_uid!=expected_uid or parent.st_mode&0o022:break
            fd,tmp=tempfile.mkstemp(prefix='.salt-',dir=path.parent)
            try:
                with os.fdopen(fd,'wb') as stream:
                    os.fchmod(stream.fileno(),0o600);stream.write((str(boot)+'\n'+os.urandom(32).hex()+'\n').encode('ascii'))
                try:os.link(tmp,path)
                except FileExistsError:pass
            finally:
                if Path(tmp).exists():Path(tmp).unlink()
        except OSError:break
    return os.urandom(32),False


def number(value,low,high,label):
    if not isinstance(value,int) or isinstance(value,bool) or value.__class__.__name__=='Boolean' or not low<=value<=high:
        raise OSError(errno.EPROTO,'Invalid '+label+'.')
    return int(value)


class Reader:
    def __init__(self):
        import dbus
        self.deadline=time.monotonic()+8;self.dbus=dbus
        try:self.bus=dbus.SystemBus()
        except dbus.DBusException as e:raise self.convert(e) from None
    def remaining(self):
        value=self.deadline-time.monotonic()
        if value<=0:raise OSError(errno.ETIMEDOUT,'Wi-Fi metadata read deadline expired.')
        return min(value,3)
    def owner(self,name):
        try:
            value=self.bus.call_blocking('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetNameOwner','s',(name,),timeout=self.remaining())
        except self.dbus.DBusException as e:raise self.convert(e) from None
        if not isinstance(value,str) or not re.fullmatch(r':[0-9]+\.[0-9]+',value):raise OSError(errno.EPROTO,'Invalid Wi-Fi daemon owner.')
        return str(value)
    def convert(self,e):
        name=e.get_dbus_name()
        code=errno.ENODEV if name.endswith(('NameHasNoOwner','ServiceUnknown','InterfaceUnknown')) else errno.EACCES if name.endswith(('AccessDenied','AuthFailed','NotAuthorized')) else errno.ETIMEDOUT if name.endswith(('NoReply','TimedOut','Timeout')) else errno.EIO
        return OSError(code,'Read-only Wi-Fi daemon request failed.')
    def get(self,owner,path,iface,key):
        try:return self.bus.get_object(owner,path,introspect=False).Get(iface,key,dbus_interface=PROP,timeout=self.remaining())
        except self.dbus.DBusException as e:raise self.convert(e) from None
    def call(self,owner,path,iface,method,*args):
        if (iface,method) not in ((NM,'GetDevices'),(NM+'.Device.Wireless','GetAllAccessPoints'),(WPA,'GetInterface')):raise ValueError('Only existing Wi-Fi inventories may be read.')
        try:return getattr(self.bus.get_object(owner,path,introspect=False),method)(*args,dbus_interface=iface,timeout=self.remaining())
        except self.dbus.DBusException as e:raise self.convert(e) from None


def paths(value,prefix,maximum):
    if not isinstance(value,(list,tuple)) or len(value)>maximum or any(not isinstance(p,str) or not re.fullmatch(re.escape(prefix)+r'/[0-9]+',p) for p in value):
        raise OSError(errno.EPROTO,'Invalid bounded Wi-Fi object inventory.')
    result=sorted(map(str,value))
    if len(set(result))!=len(result):raise OSError(errno.EPROTO,'Duplicate Wi-Fi objects.')
    return result


def context(reader=None,root=None):
    reader=reader or Reader();root=NET if root is None else root;owner=reader.owner(NM)
    device_paths=paths(reader.call(owner,'/org/freedesktop/NetworkManager',NM,'GetDevices'),'/org/freedesktop/NetworkManager/Devices',256)
    result=[]
    for path in device_paths:
        iface=NM+'.Device'
        if number(reader.get(owner,path,iface,'DeviceType'),0,2**32-1,'network type')!=2:continue
        name=str(reader.get(owner,path,iface,'Interface'))
        if not re.fullmatch(r'[^/\s\x00]{1,15}',name) or name in ('.','..'):raise OSError(errno.EPROTO,'Invalid wireless interface name.')
        p=root/name;identity=wireless.identity(p)
        phy=(p/'phy80211').resolve(strict=True).name
        if not re.fullmatch(r'phy[0-9]+',phy):raise OSError(errno.EPROTO,'Invalid wireless PHY identity.')
        phy_stat=(p/'phy80211').stat()
        active=str(reader.get(owner,path,iface,'ActiveConnection'))
        ap=str(reader.get(owner,path,iface+'.Wireless','ActiveAccessPoint'))
        last_scan=number(reader.get(owner,path,iface+'.Wireless','LastScan'),-1,2**63-1,'last cached scan time')
        if active!='/' and not re.fullmatch(r'/org/freedesktop/NetworkManager/ActiveConnection/[0-9]+',active):raise OSError(errno.EPROTO,'Invalid active connection identity.')
        peer=None;frequency=None
        if ap!='/':
            if not re.fullmatch(r'/org/freedesktop/NetworkManager/AccessPoint/[0-9]+',ap):raise OSError(errno.EPROTO,'Invalid access-point identity.')
            peer=str(reader.get(owner,ap,NM+'.AccessPoint','HwAddress')).lower()
            if not re.fullmatch(wireless.MAC,peer):raise OSError(errno.EPROTO,'Invalid associated peer identity.')
            frequency=number(reader.get(owner,ap,NM+'.AccessPoint','Frequency'),2400,7125,'AP frequency')
        if identity!=wireless.identity(p):raise OSError(errno.EAGAIN,'Wi-Fi interface identity changed.')
        result.append({'interface':name,'identity':identity,'phy':phy,'phy_identity':(phy_stat.st_dev,phy_stat.st_ino),
                       'active_connection':active,'ap_object':ap,'peer':peer,'frequency_mhz':frequency,'last_scan_ms':last_scan})
    if device_paths!=paths(reader.call(owner,'/org/freedesktop/NetworkManager',NM,'GetDevices'),'/org/freedesktop/NetworkManager/Devices',256) or owner!=reader.owner(NM):
        raise OSError(errno.EAGAIN,'Wi-Fi device inventory or daemon owner changed.')
    if not result:raise OSError(errno.ENODEV,'No managed wireless interface is present.')
    if len({r['interface'] for r in result})!=len(result):raise OSError(errno.EPROTO,'Duplicate wireless interfaces.')
    return {'owner':owner,'interfaces':sorted(result,key=lambda r:r['interface'])}


def station(row,root=None):
    root=DEBUG if root is None else root
    if row['peer'] is None:raise OSError(errno.ENODATA,'No associated kernel peer.')
    path=root/row['phy']/('netdev:'+row['interface'])/'stations'/row['peer'];before=path.stat();data={}
    for name in ('ht_capa','vht_capa','he_capa','eht_capa'):
        with (path/name).open('r',encoding='ascii',errors='strict') as stream:value=stream.read(16385)
        if len(value)>16384:raise OSError(errno.EOVERFLOW,'Kernel peer capability exceeds its bound.')
        data[name]=value
    after=path.stat()
    if (before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino):raise OSError(errno.EAGAIN,'Kernel peer identity changed.')
    return caps.peer_family(data)


def bssid(raw):
    try:value=bytes(raw)
    except (ValueError,TypeError):raise OSError(errno.EPROTO,'Invalid cached BSS identity.') from None
    if len(value)!=6:raise OSError(errno.EPROTO,'Invalid cached BSS identity length.')
    return ':'.join(f'{b:02x}' for b in value)


def collect():
    if os.geteuid()!=0:raise PermissionError(errno.EACCES,'Fresh Wi-Fi capability reads require privilege.')
    reader=Reader();reader.deadline=time.monotonic()+6
    before=context(reader);owner=reader.owner(WPA);rows=[];associations=[]
    secret,_persistent=boot_salt()
    for row in before['interfaces']:
        result={'interface':row['interface'],'ifindex':row['identity'][2],'connected':row['peer'] is not None,
                'capability':{'available':False},'association_phy':{'available':False},'observations':[],'observations_available':False}
        try:
            path=str(reader.call(owner,'/fi/w1/wpa_supplicant1',WPA,'GetInterface',row['interface']))
            if not re.fullmatch(r'/fi/w1/wpa_supplicant1/Interfaces/[0-9]+',path):raise OSError(errno.EPROTO,'Invalid existing supplicant interface.')
            current=str(reader.get(owner,path,WPA+'.Interface','CurrentBSS'))
            associations.append((path,current))
            if row['peer'] is not None:
                if not re.fullmatch(re.escape(path)+r'/BSSs/[0-9]+',current):raise OSError(errno.EAGAIN,'Associated supplicant BSS is unavailable.')
                if bssid(reader.get(owner,current,WPA+'.BSS','BSSID'))!=row['peer'] or number(reader.get(owner,current,WPA+'.BSS','Frequency'),2400,7125,'BSS frequency')!=row['frequency_mhz']:
                    raise OSError(errno.EAGAIN,'Supplicant and kernel-facing association identities differ.')
                try:
                    raw=bytes(reader.get(owner,current,WPA+'.BSS','IEs'));a=caps.elements(raw)
                    if a!=caps.elements(bytes(reader.get(owner,current,WPA+'.BSS','IEs'))):raise OSError(errno.EAGAIN,'Advertised AP capabilities changed during reading.')
                    result['capability']=caps.decode(raw,row['frequency_mhz'])
                except (OSError,ValueError,TypeError) as e:result['capability']=error(e)
                try:result['association_phy']=station(row)
                except (OSError,ValueError,UnicodeError) as e:result['association_phy']=error(e)
            else:
                result['capability']=error(OSError(errno.ENODATA,'No associated AP.'))
                result['association_phy']=error(OSError(errno.ENODATA,'No associated kernel peer.'))
            try:
                bsses=paths(reader.get(owner,path,WPA+'.Interface','BSSs'),path+'/BSSs',512);observations=[]
                if not bsses and row.get('last_scan_ms',-1)<0:raise OSError(errno.ENODATA,'Empty Wi-Fi cache has no completed scan observation.')
                if row['peer'] is not None and current not in bsses:raise OSError(errno.EAGAIN,'Associated BSS is absent from the cached inventory.')
                for obj in bsses:
                    peer=bssid(reader.get(owner,obj,WPA+'.BSS','BSSID'));freq=number(reader.get(owner,obj,WPA+'.BSS','Frequency'),2400,7125,'cached BSS frequency')
                    band=wireless.band(freq)
                    if band is None:continue
                    try:signal=number(reader.get(owner,obj,WPA+'.BSS','Signal'),-150,50,'BSS dBm signal')
                    except OSError:signal=None
                    try:age=number(reader.get(owner,obj,WPA+'.BSS','Age'),0,2**32-1,'BSS observation age')
                    except OSError:age=None
                    observations.append({'ap_key':ap_key(secret,peer,freq),'frequency_mhz':freq,'band':band,'signal_dbm':signal,'age_seconds':age})
                if bsses!=paths(reader.get(owner,path,WPA+'.Interface','BSSs'),path+'/BSSs',512):raise OSError(errno.EAGAIN,'Cached BSS inventory changed during sampling.')
                result['observations']=observations;result['observations_available']=True
            except (OSError,ValueError,TypeError) as e:result['observations_error']=error(e)
        except (OSError,ValueError,TypeError) as e:
            result.update(error(e));result['capability']=error(e);result['association_phy']=error(e)
        rows.append(result)
    # Reserve a separate short consistency budget even if a BSS-cache query timed out.
    final=Reader();final.deadline=time.monotonic()+2
    if before!=context(final) or owner!=final.owner(WPA):raise OSError(errno.EAGAIN,'Wireless association generation changed during collection.')
    for path,current in associations:
        if current!=str(final.get(owner,path,WPA+'.Interface','CurrentBSS')):raise OSError(errno.EAGAIN,'Supplicant association changed during collection.')
    return {'schema':1,'generated_boottime_seconds':boottime(),'boot_id':text(Path('/proc/sys/kernel/random/boot_id')),
            'maximum_cache_seconds':TTL,'context_id':fingerprint(before),'interfaces':rows,
            'source':'Existing supplicant BSS cache and current mac80211 kernel peer capabilities',
            'note':'Parsed metadata only. No SSID/vendor/WPS information, credentials, scan, connection or settings operation.'}


def validate_cache(data,now,current,boot):
    if not isinstance(data,dict) or type(data.get('schema')) is not int or data['schema']!=1 or data.get('maximum_cache_seconds')!=TTL or data.get('boot_id')!=boot:
        raise OSError(errno.EPROTO,'Invalid wireless cache identity/schema.')
    generated=data.get('generated_boottime_seconds')
    # Bound before math: math.isfinite() raises OverflowError for huge ints.
    if type(generated) not in (int,float) or not -2**63<generated<2**63 or not math.isfinite(generated) or not 0<=now-generated<=TTL:
        raise OSError(errno.ESTALE,'Wireless capability cache is stale.')
    if data.get('available') is False:
        raise OSError(number(data.get('errno'),1,4095,'collector error'),str(data.get('error','Wireless collector is unavailable.')))
    if data.get('context_id')!=fingerprint(current):raise OSError(errno.EAGAIN,'Cached Wi-Fi association generation changed.')
    rows=data.get('interfaces')
    if not isinstance(rows,list) or len(rows)!=len(current['interfaces']):raise OSError(errno.EPROTO,'Incomplete wireless cache inventory.')
    for row,reference in zip(rows,current['interfaces']):
        if not isinstance(row,dict) or row.get('interface')!=reference['interface'] or type(row.get('ifindex')) is not int or row['ifindex']!=reference['identity'][2] or type(row.get('connected')) is not bool or row['connected']!=(reference['peer'] is not None):
            raise OSError(errno.EPROTO,'Invalid wireless cache interface.')
        for key in ('capability','association_phy'):
            item=row.get(key)
            if not isinstance(item,dict) or type(item.get('available')) is not bool:raise OSError(errno.EPROTO,'Invalid cached capability status.')
            if item['available']:
                if key=='association_phy':
                    if item.get('family') not in ('802.11n','802.11ac','802.11ax','802.11be'):raise OSError(errno.EPROTO,'Invalid cached peer PHY.')
                else:
                    value=item.get('maximum_mbit_s')
                    if type(value) not in (int,float) or not math.isfinite(value) or not 0<value<=100000 or item.get('operation_width_mhz') not in (20,40,80,160) or item.get('complete_for_scope') is not True:
                        raise OSError(errno.EPROTO,'Invalid cached AP capability ceiling.')
        if type(row.get('observations_available')) is not bool or not isinstance(row.get('observations'),list) or len(row['observations'])>512:raise OSError(errno.EPROTO,'Invalid cached BSS observations.')
        for item in row['observations']:
            if not isinstance(item,dict) or not isinstance(item.get('ap_key'),str) or not re.fullmatch('[0-9a-f]{64}',item['ap_key']):raise OSError(errno.EPROTO,'Invalid cached BSS key.')
            freq=number(item.get('frequency_mhz'),2400,7125,'cached BSS frequency')
            if item.get('band')!=wireless.band(freq):raise OSError(errno.EPROTO,'Invalid cached BSS band.')
            if item.get('signal_dbm') is not None:number(item['signal_dbm'],-150,50,'cached dBm')
            if item.get('age_seconds') is not None:number(item['age_seconds'],0,2**32-1,'cached BSS age')
    return {**data,'age_seconds':round(now-generated,3)}


def cached(path=None,expected_uid=0):
    path=CACHE if path is None else path
    parent=path.parent.stat()
    if parent.st_uid!=expected_uid or parent.st_mode&0o022 or path.parent.is_symlink():raise PermissionError(errno.EACCES,'Untrusted wireless metrics directory.')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=expected_uid or st.st_mode&0o022:raise PermissionError(errno.EACCES,'Untrusted wireless metrics cache.')
        raw=os.read(fd,LIMIT+1)
    finally:os.close(fd)
    if len(raw)>LIMIT:raise OSError(errno.EOVERFLOW,'Wireless metrics cache exceeds its bound.')
    try:data=json.loads(raw)
    except ValueError:raise OSError(errno.EPROTO,'Invalid wireless metrics JSON.') from None
    reader=Reader();reader.deadline=time.monotonic()+6
    before=context(reader);result=validate_cache(data,boottime(),before,text(Path('/proc/sys/kernel/random/boot_id')))
    if before!=context(reader):raise OSError(errno.EAGAIN,'Wi-Fi association changed while reading cache.')
    return result


def summarize(data):
    observations={};complete=True
    for row in data['interfaces']:
        complete=complete and row['observations_available']
        for item in row['observations']:
            old=observations.get(item['ap_key'])
            if old is None or (item['age_seconds'] if item['age_seconds'] is not None else 2**32)<(old['age_seconds'] if old['age_seconds'] is not None else 2**32):observations[item['ap_key']]=item
    age=data.get('age_seconds',0)
    observations={key:{**item,'age_seconds':item['age_seconds']+age if item['age_seconds'] is not None else None} for key,item in observations.items()}
    hist=caps.histograms(list(observations.values()))
    for value in hist.values():
        value['complete']=value['complete'] and complete;value['available']=any(r['observations_available'] for r in data['interfaces'])
    return {**data,'available':True,'histograms':hist,'observations':list(observations.values())}


def report(refresh=False):
    try:
        data=collect() if refresh else cached()
        data.setdefault('age_seconds',0)
        return summarize(data)
    except (OSError,ValueError,TypeError,RuntimeError) as e:return {'schema':1,**error(e),'interfaces':[],'histograms':{},'observations':[]}


def require(name,args):
    data=report(refresh=os.geteuid()==0)
    if not data['available']:raise OSError(data['errno'],data['error'])
    if name in wireless.RSSI_NAMES:
        band=wireless.RSSI_NAMES[name];hist=data['histograms'][band]
        if not hist['available']:raise OSError(errno.ENODATA,'Cached BSS measurements are unavailable.')
        if 'threshold_dbm' in args:
            if not hist['complete']:raise OSError(errno.ENODATA,'Incomplete BSS signal distribution cannot give a definitive threshold count.')
            return sum(r['band']==band and r['signal_dbm']>=args['threshold_dbm'] for r in data['observations'])
        return hist
    rows=[r for r in data['interfaces'] if r['connected']]
    if not rows:raise OSError(errno.ENODATA,'No associated Wi-Fi peer.')
    item=rows[0]['capability' if name=='RF_WiFiMaxRate' else 'association_phy']
    if not item['available']:raise OSError(item.get('errno',errno.ENODATA),item.get('error','Requested Wi-Fi metadata is unavailable.'))
    return item['maximum_mbit_s'] if name=='RF_WiFiMaxRate' else item['family']


def needs_root(name):
    if os.geteuid()==0:return False
    try:cached();return False
    except OSError as e:return e.errno not in (errno.ENODEV,)


def export(path=None):
    if os.geteuid()!=0:raise PermissionError('Wireless exporter requires privilege.')
    path=CACHE if path is None else path
    try:data=collect()
    except (OSError,ValueError,TypeError,RuntimeError) as e:
        data={'schema':1,'generated_boottime_seconds':boottime(),'boot_id':text(Path('/proc/sys/kernel/random/boot_id')),
              'maximum_cache_seconds':TTL,'context_id':'','interfaces':[],**error(e)}
    raw=(json.dumps(data,allow_nan=False,separators=(',',':'))+'\n').encode()
    if len(raw)>LIMIT:raise OSError(errno.EOVERFLOW,'Wireless export exceeds its bound.')
    path.parent.mkdir(mode=0o755,parents=True,exist_ok=True);st=path.parent.stat()
    if st.st_uid!=0 or st.st_mode&0o022 or path.parent.is_symlink():raise PermissionError('Untrusted wireless metrics directory.')
    fd,tmp=tempfile.mkstemp(prefix='.wireless-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fchmod(stream.fileno(),0o644)
        os.replace(tmp,path)
    finally:
        if Path(tmp).exists():Path(tmp).unlink()
    return data
