# SPDX-License-Identifier: GPL-2.0-only
"""Specific, read-only ModemManager providers; never return a modem inventory.

No enable, scan, connect, PIN, AT-command, polling or threshold mutation is used.
IMSI, ICCID, IMEI, phone numbers and bearer/authentication data are not queried.
"""
import errno
import math
import re
import time
import xml.etree.ElementTree as XML

SERVICE='org.freedesktop.ModemManager1'
MODEM=SERVICE+'.Modem'
SIM=SERVICE+'.Sim'
GPP=MODEM+'.Modem3gpp'
SIGNAL=MODEM+'.Signal'
NAMES={'RF_WWAN_Access_Technology','RF_WWAN_Home_Provider','RF_WWAN_RSSI'}
TECHNOLOGIES=('POTS','GSM','GSM compact','GPRS','EDGE','UMTS','HSDPA','HSUPA',
              'HSPA','HSPA+','CDMA 1xRTT','EVDO 0','EVDO A','EVDO B','LTE','5G NR','LTE Cat-M','LTE NB-IoT')
RADIOS={'Gsm':0x1e,'Umts':0x3e0,'Cdma':1<<10,'Evdo':0x3800,
        'Lte':(1<<14)|(1<<16)|(1<<17),'Nr5g':1<<15}
PROPERTIES={MODEM:{'State','AccessTechnologies','SignalQuality','Sim'},
            SIM:{'OperatorIdentifier','OperatorName'},GPP:{'OperatorCode','OperatorName'},
            SIGNAL:{'Rate','RssiThreshold','ErrorRateThreshold',*RADIOS}}


def unavailable(message,number=errno.ENODATA):raise OSError(number,message)


def path_valid(value,kind):
    return isinstance(value,str) and re.fullmatch('/org/freedesktop/ModemManager1/'+kind+r'/[0-9]+',value) is not None


def validate(name,args):
    if name not in NAMES:raise ValueError('Unknown WWAN query.')
    if not isinstance(args,dict) or set(args)-{'modem'}:raise ValueError('Only an optional modem object path is accepted.')
    if 'modem' in args and not path_valid(args['modem'],'Modem'):raise ValueError('Invalid ModemManager modem path.')


class Reader:
    """Pin one existing service owner; enumerate names without private properties."""
    def __init__(self):
        import dbus
        self.dbus=dbus;self.bus=dbus.SystemBus();self.deadline=time.monotonic()+10
        self.unique=self.owner()
        if not isinstance(self.unique,str) or not re.fullmatch(r':[0-9]+\.[0-9]+',self.unique):
            unavailable('Invalid ModemManager owner.',errno.EPROTO)

    def timeout(self):
        remaining=self.deadline-time.monotonic()
        if remaining<=0:unavailable('WWAN property-read budget expired.',errno.ETIMEDOUT)
        return min(2,remaining)

    def invoke(self,function):
        try:return function()
        except self.dbus.DBusException as error:
            kind=error.get_dbus_name()
            code=errno.EACCES if kind.endswith(('AccessDenied','AuthFailed','Unauthorized','NotAuthorized')) else errno.ENODEV if kind.endswith(('UnknownObject','ServiceUnknown','NameHasNoOwner')) else errno.EOPNOTSUPP if kind.endswith(('UnknownInterface','UnknownProperty','UnknownMethod')) else errno.ETIMEDOUT if kind.endswith(('NoReply','TimedOut','Timeout')) else errno.EIO
            unavailable('ModemManager read-only query failed.',code)

    def owner(self):
        return self.invoke(lambda:self.bus.call_blocking('org.freedesktop.DBus','/org/freedesktop/DBus',
            'org.freedesktop.DBus','GetNameOwner','s',(SERVICE,),timeout=self.timeout()))

    def paths(self):
        # Introspection returns object names and interface signatures, never
        # subscriber/equipment identifiers, bearers or authentication values.
        root='/org/freedesktop/ModemManager1/Modem'
        raw=self.invoke(lambda:self.bus.get_object(self.unique,root,introspect=False).Introspect(
            dbus_interface='org.freedesktop.DBus.Introspectable',timeout=self.timeout()))
        if not isinstance(raw,str) or len(raw)>65536:
            unavailable('Invalid modem object-name metadata.',errno.EPROTO)
        raw=re.sub(r'<!DOCTYPE node PUBLIC\s+"-//freedesktop//DTD D-BUS Object Introspection 1\.0//EN"\s+"http://www\.freedesktop\.org/standards/dbus/1\.0/introspect\.dtd">','',raw,count=1)
        if re.search(r'<!\s*(?:DOCTYPE|ENTITY)',raw,re.I):
            unavailable('Unexpected modem object-name declaration.',errno.EPROTO)
        try:tree=XML.fromstring(raw)
        except XML.ParseError:unavailable('Invalid modem object-name XML.',errno.EPROTO)
        if tree.tag!='node':unavailable('Invalid modem object-name root.',errno.EPROTO)
        names=[node.attrib.get('name') for node in tree.findall('node')]
        if len(names)>32 or any(not isinstance(n,str) or not re.fullmatch(r'[0-9]+',n) for n in names) or len(set(names))!=len(names):
            unavailable('Invalid ModemManager modem list.',errno.EPROTO)
        return sorted(root+'/'+n for n in names)

    def unbox(self,value):
        if isinstance(value,self.dbus.Boolean):return bool(value)
        if isinstance(value,dict):return {str(k):self.unbox(v) for k,v in value.items()}
        if isinstance(value,(list,tuple)):return [self.unbox(v) for v in value]
        return value

    def get(self,path,interface,prop):
        if prop not in PROPERTIES.get(interface,set()) or not path_valid(path,'SIM' if interface==SIM else 'Modem'):
            unavailable('Property is outside the fixed WWAN read set.',errno.EPERM)
        value=self.invoke(lambda:self.bus.get_object(self.unique,path,introspect=False).Get(
            interface,prop,dbus_interface='org.freedesktop.DBus.Properties',timeout=self.timeout()))
        return self.unbox(value)

    def finish(self,paths):
        if self.paths()!=paths or self.owner()!=self.unique:
            unavailable('ModemManager owner or modem inventory changed during sampling.',errno.EAGAIN)


class ModemPaths(list):
    def __init__(self,reader):
        self.reader=reader;super().__init__(reader.paths())


def list_modems():return ModemPaths(Reader())


def dbus_getter(reader=None):return (reader or Reader()).get


def unsigned(value,maximum=0xffffffff):
    if isinstance(value,bool) or not isinstance(value,int) or not 0<=value<=maximum:
        unavailable('Invalid WWAN numeric property.',errno.EPROTO)
    return int(value)


def optional(get,path,interface,prop):
    try:return get(path,interface,prop)
    except OSError as error:
        if error.errno not in (errno.EOPNOTSUPP,errno.ENODATA):raise
        return None


def operator(code,name):
    if code is not None and (not isinstance(code,str) or code and not re.fullmatch(r'[0-9]{5,6}',code)):
        unavailable('Invalid mobile operator code.',errno.EPROTO)
    if name is not None and (not isinstance(name,str) or len(name)>256 or any(ord(c)<32 for c in name)):
        unavailable('Invalid mobile operator name.',errno.EPROTO)
    return {'code':str(code) if code else None,'name':str(name) if name else None}


def access_technology(get,path):
    mask=unsigned(get(path,MODEM,'AccessTechnologies'))
    state=get(path,MODEM,'State')
    if isinstance(state,bool) or not isinstance(state,int) or not -1<=state<=11:unavailable('Invalid modem state.',errno.EPROTO)
    registered=8<=state<=11
    known=(1<<len(TECHNOLOGIES))-1
    names=[name for i,name in enumerate(TECHNOLOGIES) if mask&(1<<i)] if registered and mask!=0xffffffff else []
    return {'available':bool(names),'technologies':names,'raw_mask':mask,'modem_state':int(state),
            'unknown_mask':mask&~known if mask!=0xffffffff else mask,
            'note':'Current registered access technologies; unknown bits are preserved, not renamed.'}


def home_provider(get,path):
    sim=get(path,MODEM,'Sim')
    if sim=='/':unavailable('No primary SIM is available.')
    if not path_valid(sim,'SIM'):unavailable('Invalid primary SIM path.',errno.EPROTO)
    def read_operator(object_path,interface,code_prop):
        values={};errors={}
        for label,prop in [('code',code_prop),('name','OperatorName')]:
            try:
                value=get(object_path,interface,prop)
                checked=operator(value,None) if label=='code' else operator(None,value)
                values[label]=checked[label]
            except OSError as error:
                values[label]=None;errors[label]={'errno':error.errno or errno.EIO,'error':str(error)}
        return operator(values['code'],values['name']),errors
    home,home_errors=read_operator(sim,SIM,'OperatorIdentifier')
    serving,serving_errors=read_operator(path,GPP,'OperatorCode')
    result={'available':any(home.values()),'home_provider':home,'serving_provider':serving,
            'home_provider_errors':home_errors,'serving_provider_errors':serving_errors,
            'note':'Home provider comes only from the primary SIM; the serving network may differ while roaming.'}
    if not result['available'] and home_errors:result.update(next(iter(home_errors.values())))
    return result


def signal(get,path):
    access=access_technology(get,path)
    quality=get(path,MODEM,'SignalQuality')
    if not isinstance(quality,(list,tuple)) or len(quality)!=2 or type(quality[1]) is not bool:
        unavailable('Invalid modem signal quality.',errno.EPROTO)
    percent=unsigned(quality[0],100);recent=quality[1]
    rate=optional(get,path,SIGNAL,'Rate')
    rate=unsigned(rate) if rate is not None else None
    threshold=optional(get,path,SIGNAL,'RssiThreshold')
    threshold=unsigned(threshold) if threshold is not None else None
    errors=optional(get,path,SIGNAL,'ErrorRateThreshold')
    if errors is not None and type(errors) is not bool:unavailable('Invalid signal threshold state.',errno.EPROTO)
    configured=bool(rate or threshold or errors)
    measurements=[];measurement_errors={}
    fields={'rssi':('rssi_dbm',-250,0),'rsrp':('rsrp_dbm',-250,0),
            'rsrq':('rsrq_db',-100,100),'snr':('snr_db',-100,100),
            'rscp':('rscp_dbm',-250,0),'ecio':('ecio_db',-200,100),
            'sinr':('sinr_db',-100,100),'io':('io_dbm',-250,0),
            'error-rate':('error_rate_percent',0,100)}
    if configured and access['available']:
        for radio,mask in RADIOS.items():
            if not access['raw_mask']&mask:continue
            try:raw=optional(get,path,SIGNAL,radio)
            except OSError as error:
                measurement_errors[radio]={'errno':error.errno or errno.EIO,'error':str(error)}
                continue
            if raw is None:continue
            if not isinstance(raw,dict):unavailable('Invalid extended signal dictionary.',errno.EPROTO)
            values={}
            for key,(label,low,high) in fields.items():
                if radio=='Nr5g' and key=='rssi':continue  # NR RSRP is not RSSI.
                value=raw.get(key)
                if key=='ecio' and radio in ('Cdma','Evdo'):label='ecio_dbm'
                if isinstance(value,(int,float)) and not isinstance(value,bool) and low<=value<=high and math.isfinite(value):values[label]=float(value)
            if values:measurements.append({'radio':radio,**values})
    rssi=any('rssi_dbm' in row for row in measurements)
    return {'available':rssi,'rssi_available':rssi,'measurements':measurements,'measurement_errors':measurement_errors,
            'signal_quality_percent':percent if recent and access['available'] else None,'signal_quality_recent':recent,
            'periodic_refresh_seconds':rate,'rssi_threshold_dbm':threshold,'error_rate_threshold':errors,
            'sample_age_seconds':None,'freshness_verified':False,'value_kind':'modem-reported cached measurements',
            'note':'Signal quality is not converted to dBm. NR RSRP stays RSRP. No polling/threshold setup is changed; cached measurements have no exposed timestamp.'}


def collect(name,paths,get):
    readers={'RF_WWAN_Access_Technology':access_technology,'RF_WWAN_Home_Provider':home_provider,'RF_WWAN_RSSI':signal}
    rows=[]
    for path in paths:
        row={'modem':path,'source':'ModemManager read-only D-Bus properties'}
        try:
            # Recheck only properties actually used by this query. Dynamic
            # transitions must not publish a mixture of SIM/radio contexts.
            observed={}
            context={'RF_WWAN_Access_Technology':{(MODEM,'State'),(MODEM,'AccessTechnologies')},
                     'RF_WWAN_Home_Provider':{(MODEM,'Sim')},
                     'RF_WWAN_RSSI':{(MODEM,'State'),(MODEM,'AccessTechnologies'),(MODEM,'SignalQuality'),
                                     (SIGNAL,'Rate'),(SIGNAL,'RssiThreshold'),(SIGNAL,'ErrorRateThreshold')}}[name]
            def guarded(p,interface,prop):
                try:value=get(p,interface,prop)
                except OSError as error:
                    if p==path and (interface,prop) in context:observed[(interface,prop)]=('error',error.errno)
                    raise
                if p==path and (interface,prop) in context:observed[(interface,prop)]=('value',value)
                return value
            result=readers[name](guarded,path)
            for (interface,prop),before in observed.items():
                try:after=('value',get(path,interface,prop))
                except OSError as error:after=('error',error.errno)
                if before!=after:unavailable('Modem context changed during sampling.',errno.EAGAIN)
            row.update(result)
        except OSError as error:row.update(available=False,errno=error.errno or errno.EIO,error=str(error))
        if not row['available'] and 'errno' not in row:row.update(errno=errno.ENODATA,error='The requested modem data is unavailable.')
        rows.append(row)
    return rows


def call(name,args):
    validate(name,args)
    paths=list_modems()
    inventory=list(paths);reader=getattr(paths,'reader',None)
    if 'modem' in args:paths=[p for p in paths if p==args['modem']]
    if not paths:
        if reader:reader.finish(inventory)
        unavailable('No requested WWAN modem is present.',errno.ENODEV)
    rows=collect(name,paths,dbus_getter(reader))
    if reader:reader.finish(inventory)
    return rows
