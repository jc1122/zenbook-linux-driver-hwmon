# SPDX-License-Identifier: GPL-2.0-only
"""Bounded AP capability decoding and standard HT/VHT/HE rate arithmetic.

Rates are capability calculations, not throughput or negotiated NIC limits.
Only capability IEs are retained; SSID/vendor/WPS data is never returned.
"""
import errno
from fractions import Fraction

MCS=((1,1,2),(2,1,2),(2,3,4),(4,1,2),(4,3,4),(6,2,3),(6,3,4),(6,5,6),(8,3,4),(8,5,6),(10,3,4),(10,5,6))
SELECTED={(1,None),(50,None),(45,None),(61,None),(191,None),(192,None),(255,35),(255,36),(255,108)}


def fail(message):raise OSError(errno.EPROTO,message)


def elements(raw):
    if not isinstance(raw,bytes) or not 1<=len(raw)<=8192:fail('Invalid bounded AP information-element frame.')
    result={};offset=0
    while offset<len(raw):
        if offset+2>len(raw):fail('Truncated AP information-element header.')
        kind,size=raw[offset:offset+2];data=raw[offset+2:offset+2+size];offset+=2+size
        if len(data)!=size or kind==255 and not data:fail('Truncated AP information element.')
        key=(kind,data[0] if kind==255 else None)
        if key in SELECTED:
            if key in result and result[key]!=data:fail('Conflicting duplicate AP capability element.')
            result[key]=data
    return result


def word(raw,index):return int.from_bytes(raw[index:index+2],'little')


def rate(family,width,nss,mcs,gi):
    if family not in ('HT','VHT','HE') or width not in (20,40,80,160) or not 1<=nss<=8 or not 0<=mcs<len(MCS):
        raise ValueError('Invalid standard rate parameters.')
    bits,num,den=MCS[mcs]
    if family=='HE':
        if gi not in (.8,1.6,3.2):raise ValueError('Invalid HE guard interval.')
        subcarriers={20:234,40:468,80:980,160:1960}[width];duration={.8:136,1.6:144,3.2:160}[gi]
    else:
        if gi not in (.4,.8) or family=='HT' and (width>40 or mcs>7):raise ValueError('Invalid OFDM rate parameters.')
        subcarriers={20:52,40:108,80:234,160:468}[width];duration={.4:36,.8:40}[gi]
    return Fraction(subcarriers*bits*num*nss*10,den*duration)


def wide_operation(raw,previous):
    if len(raw)!=3 or raw[0]>3:fail('Invalid VHT operation channel declaration.')
    if raw[0]==0:return previous,'contiguous'
    if raw[0]==1:
        if not raw[1]:fail('Missing VHT channel center.')
        if not raw[2]:return 80,'contiguous'
        difference=abs(raw[1]-raw[2])
        if difference==8:return 160,'contiguous'
        if difference>16:return 160,'80+80'
        fail('Invalid wide VHT channel centers.')
    return 160,'80+80' if raw[0]==3 else 'contiguous'


def operation(ies,frequency,details=False):
    if type(frequency) is not int or not 2400<=frequency<=7125:fail('Invalid AP frequency.')
    ht=ies.get((61,None));vht=ies.get((192,None));he=ies.get((255,36));width=20;mode='contiguous'
    if ht is not None:
        if len(ht)!=22:fail('Invalid HT operation length.')
        if ht[1]&4:
            if ht[1]&3 not in (1,3):fail('Invalid HT secondary-channel declaration.')
            width=40
    if vht is not None:
        if len(vht)!=5:fail('Invalid VHT operation.')
        width,mode=wide_operation(vht[:3],width)
    if he is not None:
        if len(he)<7:fail('Incomplete HE operation.')
        flags=int.from_bytes(he[1:5],'little');size=7+(3 if flags&0x4000 else 0)+(1 if flags&0x8000 else 0)
        if flags&0x4000:
            if len(he)<10:fail('Truncated HE optional VHT operation.')
            declared=wide_operation(he[7:10],width)
            if vht is not None and declared!=(width,mode):fail('Conflicting HE and VHT operation widths.')
            width,mode=declared
        if flags&0x20000:
            if len(he)<size+5:fail('Incomplete6GHz HE operation.')
            op=he[size:size+5];width=(20,40,80,160)[op[1]&3]
            if not op[0]:fail('Invalid6GHz primary channel.')
            if width==160:
                if not op[2] or not op[3]:fail('Missing wide6GHz channel centers.')
                difference=abs(op[2]-op[3])
                if difference==8:mode='contiguous'
                elif difference>16:mode='80+80'
                else:fail('Invalid wide6GHz channel centers.')
        if len(he)<size+(5 if flags&0x20000 else 0):fail('Truncated variable HE operation.')
    if frequency>=5925 and (he is None or not int.from_bytes(he[1:5],'little')&0x20000):
        raise OSError(errno.ENODATA,'6GHz operation width is unavailable.')
    return (width,mode) if details else width


def decode(raw,frequency):
    ies=elements(raw);width,mode=operation(ies,frequency,True);profiles=[];limitations=[]
    def add(family,w,nss,mcs,gi,direction):
        value=rate(family,w,nss,mcs,gi)
        profiles.append({'family':family,'width_mhz':w,'spatial_streams':nss,'mcs':mcs,'guard_interval_us':gi,
                         'direction':direction,'ceiling_mbit_s':round(float(value),3)})
    legacy=[(b&127)/2 for key in ((1,None),(50,None)) for b in ies.get(key,b'') if 0<(b&127)<122]
    ht=ies.get((45,None));vht=ies.get((191,None));he=ies.get((255,35))
    if ht is not None:
        if len(ht)!=26:fail('Invalid HT capability length.')
        if (61,None) not in ies:raise OSError(errno.ENODATA,'HT operation is unavailable.')
        cap=word(ht,0);w=40 if cap&2 and width>=40 else 20
        gi=.4 if cap&(0x40 if w==40 else 0x20) else .8
        bitmap=ht[3:13]
        for index in range(32):
            if bitmap[index//8]&(1<<(index%8)):add('HT',w,index//8+1,index%8,gi,'AP receive')
        if any(bitmap[4:]):limitations.append('Optional unequal-modulation HT MCS entries are outside this decoder.')
    if vht is not None:
        if len(vht)!=12:fail('Invalid VHT capability length.')
        if (192,None) not in ies:raise OSError(errno.ENODATA,'VHT operation is unavailable.')
        cap=int.from_bytes(vht[:4],'little');supported=(cap>>2)&3
        if supported==3:fail('Reserved VHT channel-width capability.')
        w=min(width,160 if supported else 80)
        if width==160 and not supported:fail('VHT operation exceeds advertised capability.')
        if mode=='80+80' and supported!=2:fail('VHT80+80 operation lacks advertised capability.')
        if w in (20,40):sgi=bool(ht and word(ht,0)&(0x20 if w==20 else 0x40))
        else:sgi=bool(cap&(0x20 if w==80 else 0x40))
        for direction,offset in (('AP receive',4),('AP transmit',8)):
            mapping=word(vht,offset)
            for nss in range(1,9):
                code=(mapping>>(2*(nss-1)))&3
                if code==3:continue
                mcs=(7,8,9)[code]
                if w==20 and mcs==9 and nss%3:mcs=8
                add('VHT',w,nss,mcs,.4 if sgi else .8,direction)
    if he is not None:
        if len(he)<22:fail('Incomplete HE capability/MCS maps.')
        phy=he[7:18];count=4+4*bool(phy[0]&8)+4*bool(phy[0]&16);end=18+count
        if len(he)<end:fail('Missing bandwidth-specific HE MCS maps.')
        if phy[6]&0x80:
            if len(he)<=end:fail('Missing HE PPE header.')
            header=he[end];ppe=(6*(1+(header&7))*((header&0x78).bit_count())+7+7)//8
            if len(he)<end+ppe:fail('Truncated HE PPE thresholds.')
        if width==40 and frequency<2500 and not phy[0]&2:fail('HE40 operation lacks2GHz width support.')
        if width>=40 and frequency>=2500 and not phy[0]&4:fail('HE wide operation lacks width support.')
        maps=[(min(width,80),18)]
        if width==160:
            if mode=='contiguous' and phy[0]&8:maps.append((160,22))
            elif mode=='80+80' and phy[0]&16:maps.append((160,22+4*bool(phy[0]&8)))
            else:fail('HE160 operation lacks bandwidth-specific capability.')
        for w,offset in maps:
            for direction,index in (('AP receive',offset),('AP transmit',offset+2)):
                mapping=word(he,index)
                for nss in range(1,9):
                    code=(mapping>>(2*(nss-1)))&3
                    if code!=3:add('HE',w,nss,(7,9,11)[code],.8,direction)
    if not profiles and not legacy:raise OSError(errno.ENODATA,'No decoded AP capability rate.')
    best=max(profiles,key=lambda p:p['ceiling_mbit_s']) if profiles else None
    maximum=max([p['ceiling_mbit_s'] for p in profiles]+legacy)
    # Unhandled unequal HT MCS cannot exceed the4-stream HT40 short-GI ceiling.
    complete=not limitations or maximum>=600
    eht=(255,108) in ies
    result={'available':complete,'complete_for_scope':complete,'complete_overall':complete and not eht,
            'maximum_mbit_s':maximum if complete else None,'operation_width_mhz':width,'operation_channel_layout':mode,'best_profile':best,
            'legacy_maximum_mbit_s':max(legacy) if legacy else None,'higher_EHT_capability_present':eht,
            'scope':'Advertised AP HT/VHT/HE capability ceiling; EHT is outside the original getter scope',
            'kind':'derived capability metadata','profiles':profiles,'limitations':limitations,
            'note':'Standard full-bandwidth SU rate arithmetic; HE ceiling uses the fastest standard0.8us GI. Not throughput, observed link rate, NIC-intersection rate or guaranteed airtime. Vendor table anomalies and integer endpoint/rounding errors are not reproduced.'}
    if not complete:result.update(errno=errno.ENODATA,error='Unsupported HT modulation can affect the ceiling.')
    return result


def peer_family(files):
    supported=[]
    for name,label,family in (('ht_capa','ht','802.11n'),('vht_capa','VHT','802.11ac'),('he_capa','HE','802.11ax'),('eht_capa','EHT','802.11be')):
        raw=files.get(name)
        if not isinstance(raw,str) or len(raw)>16384:raise OSError(errno.ENODATA,'Kernel peer capability file is unavailable.')
        head=raw.splitlines()[0] if raw.splitlines() else ''
        if head==label+' supported':supported.append(family)
        elif head!=label+' not supported':fail('Unrecognized kernel peer capability header.')
    if not supported:raise OSError(errno.ENODATA,'Exact legacy association PHY is not exposed by these kernel capability files.')
    return {'available':True,'family':supported[-1],'enabled_families':supported,'source':'Current mac80211 peer capability files',
            'note':'Kernel peer capabilities, independent of instantaneous Tx/Rx rate fallback. Legacy a/b/g is not guessed from AP or frame-rate metadata.'}


def histograms(observations):
    result={}
    for band in ('2_4G','5G','6G'):
        bins=[{'lower_dbm':-20-10*i,'upper_dbm':-10-10*i,'count':0} for i in range(9)]
        rows=[r for r in observations if r['band']==band];unknown=outside=0;ages=[]
        for row in rows:
            value=row.get('signal_dbm');age=row.get('age_seconds')
            if age is not None:ages.append(age)
            if value is None:unknown+=1;continue
            match=next((b for b in bins if b['lower_dbm']<=value<b['upper_dbm']),None)
            if match:match['count']+=1
            else:outside+=1
        result[band]={'available':True,'complete':unknown==0,'bins':bins,'total_aps':len(rows),'unknown_signal_count':unknown,
                      'outside_bins_count':outside,'maximum_observation_age_seconds':max(ages) if ages else None,
                      'range_convention':'lower inclusive, upper exclusive','source':'Existing cached BSS dBm observations',
                      'note':'Cached observations, not a new scan or a claim of complete current radio coverage. Integral decade boundaries are counted once instead of omitted as in the original helper.'}
    return result
