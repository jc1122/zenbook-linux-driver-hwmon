# SPDX-License-Identifier: GPL-2.0-only
"""Fixed source-gated native EC diagnostic tables and private JSONL logging.

Raw diagnostic words remain raw; zero or a named bit is not a temperature,
voltage, measured power, physical protection signal or new calibration claim.
"""
from pathlib import Path
import datetime
import errno
import json
import math
import os
import pwd
import stat
import time
import native_oem
import qualified_ec
import firmware_queries

LAYOUT=Path(__file__).with_name('diagnostic_log_layout.json')


def failure(error):
    return {'available':False,'errno':getattr(error,'errno',None) or errno.EPROTO,'error':str(error)}


def integer(value,low,high,label):
    if type(value) is not int or not low<=value<=high:raise OSError(errno.EPROTO,'Invalid diagnostic '+label+'.')
    return value


def status(value):return integer(value,-4095,0,'status')


def unavailable(message,code=errno.EOPNOTSUPP):return {'available':False,'errno':code,'error':message}


def raw_value(value,width=1):
    value=integer(value,0,(1<<(width*8))-1,'raw value')
    return {'available':True,'raw_unsigned':value,'raw_hex':format(value,'0'+str(2*width)+'x'),
            'raw_bytes_le':value.to_bytes(width,'little').hex(),'kind':'raw EC diagnostic value; units not inferred'}


def checked_status(item):
    if not isinstance(item,dict):raise OSError(errno.EPROTO,'Invalid diagnostic field object.')
    code=status(item.get('status'))
    return unavailable('Native diagnostic field read failed.',-code) if code else None


def bytes_value(item,count):
    error=checked_status(item)
    if error:return error
    raw=item.get('raw')
    if not isinstance(raw,list) or len(raw)!=count:raise OSError(errno.EPROTO,'Invalid diagnostic byte count.')
    data=bytes(integer(v,0,255,'raw byte') for v in raw)
    text=data.split(b'\0',1)[0]
    return {'available':True,'raw_hex':data.hex(),'byte_count':count,
            'text':text.decode('ascii') if all(32<=v<127 for v in text) else None,
            'kind':'raw EC diagnostic string; text only if printable ASCII'}


def fan_value(item):
    error=checked_status(item)
    if error:return error
    count=integer(item.get('count'),1,1,'fan count');index=integer(item.get('index'),0,0,'fan index')
    mode=integer(item.get('mode_raw'),0,1,'fan mode');rpm=integer(item.get('rpm'),0,20000,'RPM')
    selection=integer(item.get('selection_raw'),0,255,'raw fan selector')
    duty_status=status(item.get('duty_status'));duty=None
    if item.get('duty_code_maximum')!=254:raise OSError(errno.EPROTO,'Invalid EC fan duty resolution.')
    if not duty_status:
        duty=integer(item.get('duty_code'),0,254,'fan duty code')
        if duty&1 or mode!=1:raise OSError(errno.EPROTO,'Invalid manual-only EC duty code.')
    elif item.get('duty_code') is not None:raise OSError(errno.EPROTO,'Unavailable EC duty exposes a value.')
    if mode==0 and duty_status!=-errno.EOPNOTSUPP:raise OSError(errno.EPROTO,'Invalid automatic-mode duty availability.')
    return {'available':True,'count':count,'index':index,'mode_raw':mode,'mode':'automatic' if mode==0 else 'manual',
            'selection_raw':selection,'index_scope':'native single fixed channel; raw firmware selector is separate',
            'rpm':rpm,'duty_code':duty,'duty_available':not duty_status,'duty_errno':-duty_status if duty_status else None,'duty_code_maximum':254,
            'source':'Fixed HealthyTable DD2/35, twice the seven-bit EC duty register',
            'note':'The firmware replies to the duty read only in manual mode. Its code is separate from requested PWM and an independent electrical measurement.'}


def board_value(data):
    item=data.get('board');error=checked_status(item)
    if data.get('board_selector_restored') is not True:raise OSError(errno.EIO,'Board selector restoration is not verified.')
    if error:return error
    values=item.get('raw')
    if not isinstance(values,list) or len(values)>5:raise OSError(errno.EPROTO,'Invalid indexed diagnostic count.')
    for value in values:integer(value,0,255,'board raw temperature')
    return {'available':True,'count':len(values),'indexing':'one-based native .301 selectors',
            'selector_restored':True,'items':[{'index':i+1,'fields':{'Status':unavailable('Requires HealthyTable23.'),
            'Temperature':raw_value(value)}} for i,value in enumerate(values)],
            'note':'Raw diagnostic codes; BIOS-labelled measured temperatures are provided separately by board_thermistors.'}


def decode(data,layout,now):
    if not isinstance(data,dict) or data.get('schema')!=2 or type(data.get('schema')) is not int or type(data.get('protocol')) is not int or data['protocol']!=15:
        raise OSError(errno.EPROTO,'Invalid native diagnostic schema/protocol.')
    started=integer(data.get('started_boottime_us'),0,2**63-1,'sample start')
    duration=integer(data.get('duration_us'),0,30_000_000,'sample duration')
    age=now-started/1e6
    if not math.isfinite(age) or not 0<=age<=45 or duration/1e6>age+.01:raise OSError(errno.ESTALE,'Native diagnostic sample timing is inconsistent.')
    protocol=data['protocol'];scalars=[row for group in layout['main'] for row in group['rows'] if row['command']!=255 and row['minimum_version']<=protocol]
    values=data.get('values')
    if len(scalars)!=40 or not isinstance(values,list) or len(values)!=40:raise OSError(errno.EPROTO,'Incomplete native scalar diagnostics.')
    mapped={}
    for row,value in zip(scalars,values):
        if not isinstance(value,list) or len(value)!=2:raise OSError(errno.EPROTO,'Invalid scalar diagnostic reply.')
        code=status(value[0])
        if code:
            if value[1] is not None:raise OSError(errno.EPROTO,'Failed scalar diagnostic exposes a value.')
            result=unavailable('Native scalar diagnostic read failed.',-code)
        else:result=raw_value(value[1],row['length'])
        mapped[(row['command'],row['bank_or_special'],row['register_or_count'],row['length'])]=result
    vr=data.get('vr');vr_error=checked_status(vr)
    count=integer(vr.get('count'),0,255,'VR count')
    if not vr_error and count:raise OSError(errno.EPROTO,'Unqualified indexed VR path.')
    specials={0:bytes_value(data.get('chip'),4),1:bytes_value(data.get('project'),32),
              2:bytes_value(data.get('manufacturer'),11),3:board_value(data),
              4:vr_error or {'available':True,'count':0,'items':[],'note':'Qualified firmware reports no indexed VR sensors.'},
              5:fan_value(data.get('fan')),6:unavailable('Consumer VR data requires HealthyTable19 and a qualified provider.'),
              7:unavailable('Power-limit diagnostic helper requires HealthyTable24 and a qualified provider.')}
    groups=[]
    for group in layout['main']:
        rows=[]
        for descriptor in group['rows']:
            minimum=max(descriptor['minimum_version'],24 if descriptor['command']==255 and descriptor['bank_or_special']==7 else 0)
            if minimum>protocol:result=unavailable('Requires HealthyTable'+str(minimum)+'. No request was made.')
            elif descriptor['command']==255:result=specials[descriptor['bank_or_special']]
            else:result=mapped[(descriptor['command'],descriptor['bank_or_special'],descriptor['register_or_count'],descriptor['length'])]
            rows.append({**descriptor,'effective_minimum_version':minimum,**result})
        groups.append({'name':group['name'],'entries':rows})
    return {'schema':2,'available':True,'protocol':protocol,'table_entry_count':sum(len(g['entries']) for g in groups),'groups':groups,
            'sample_age_seconds':round(age,6),'duration_seconds':duration/1e6,'fan':specials[5],
            'source':'Original fixed diagnostic descriptors and native .301 HealthyTable reads',
            'note':'Sequential raw diagnostics, not an atomic sensor frame. Unsupported version rows are explicit and cause no I/O. Unknown units and bit meanings are not guessed.'}


def fan_report():
    try:
        path=native_oem.device();before=qualified_ec.identity(path)
        raw=json.loads(qualified_ec.text(path/'fan_diagnostics'))
        if not isinstance(raw,dict) or type(raw.get('schema')) is not int or raw['schema']!=2:raise OSError(errno.EPROTO,'Invalid native fan schema.')
        result=fan_value({**raw,'status':0})
        if before!=qualified_ec.identity(path):raise OSError(errno.EAGAIN,'Native fan identity changed.')
        return result
    except (OSError,ValueError,TypeError,RuntimeError) as e:return failure(e)


def report(include_eeprom=False):
    try:
        path=native_oem.device();before=qualified_ec.identity(path);qualified_ec.snapshot()
        raw=json.loads(qualified_ec.text(path/'ec_diagnostics'))
        result=decode(raw,json.loads(LAYOUT.read_text()),time.clock_gettime(time.CLOCK_BOOTTIME))
        if before!=qualified_ec.identity(path) or qualified_ec.text(path/'pwm1_enable')!='2':raise OSError(errno.EAGAIN,'Native diagnostic ownership or identity changed.')
    except (OSError,ValueError,TypeError,RuntimeError) as e:result={'schema':1,**failure(e),'groups':[]}
    # The original raw-data helper is already implemented by the bounded EEPROM
    # provider. Only an explicit logger asks for its contents/event stream.
    if include_eeprom:
        try:result['raw_data']={'available':True,'value':firmware_queries.call('GetEEPROM_Data',{})}
        except (OSError,ValueError,RuntimeError) as e:result['raw_data']=failure(e)
    return result


def _decimal_id(raw,label):
    if not raw.isascii() or not raw.isdecimal() or not 0<=int(raw)<2**32-1:raise PermissionError(errno.EACCES,'Invalid '+label+' caller identity.')
    return int(raw)


def invoking_identity():
    """(uid, gid) of the unprivileged user a root process acts for, else None."""
    if os.geteuid()!=0:return None
    if 'SUDO_UID' in os.environ:
        uid=_decimal_id(os.environ['SUDO_UID'],'sudo')
        gid=_decimal_id(os.environ['SUDO_GID'],'sudo') if 'SUDO_GID' in os.environ else None
    elif 'PKEXEC_UID' in os.environ:uid=_decimal_id(os.environ['PKEXEC_UID'],'pkexec');gid=None
    else:return None
    if uid==0:return None
    if gid is None:
        try:gid=pwd.getpwuid(uid).pw_gid
        except KeyError:raise OSError(errno.ENOENT,'The caller has no local account.') from None
    return uid,gid


def _create_private(path):
    """Create a new 0600 file without following any symlink in the path.

    Every directory component is opened with O_PATH|O_DIRECTORY|O_NOFOLLOW
    relative to its parent, so a swapped-in symlink fails instead of
    redirecting a root write. When root acts for a sudo/pkexec user, the target
    directory must belong to that user and the new file is chowned to them.
    """
    if os.path.basename(path) in ('','.','..') or '\0' in path:raise ValueError('A new private log file name is required.')
    parent,name=os.path.split(os.path.abspath(path))
    caller=invoking_identity()
    flags=os.O_PATH|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
    dfd=os.open('/',flags)
    try:
        for part in [c for c in parent.split('/') if c]:
            try:nfd=os.open(part,flags,dir_fd=dfd)
            except OSError as e:
                if e.errno in (errno.ELOOP,errno.ENOTDIR):raise OSError(e.errno,'Log directory path must not contain symlinks: '+parent) from None
                raise
            os.close(dfd);dfd=nfd
        info=os.fstat(dfd)
        if caller is not None and info.st_uid!=caller[0]:
            raise PermissionError(errno.EACCES,'The log directory must be owned by the invoking user.')
        fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=dfd)
    finally:os.close(dfd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):raise OSError(errno.EINVAL,'Log path is not a regular file.')
        if caller is not None:os.fchown(fd,*caller)
    except BaseException:
        os.close(fd);raise
    return fd


def write_log(path,samples=1,interval=1,snapshot=None):
    if not isinstance(path,str) or not path:raise ValueError('A new private log path is required.')
    if type(samples) is not int or not 1<=samples<=300 or type(interval) not in (int,float) or not math.isfinite(interval) or not .5<=interval<=60:
        raise ValueError('Use1..300 samples and a finite0.5..60 second interval.')
    fd=_create_private(path)
    with os.fdopen(fd,'w') as stream:
        for index in range(samples):
            if index:time.sleep(interval)
            data=snapshot() if snapshot else {'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat()}
            data['ec_diagnostics']=report(include_eeprom=True)
            stream.write(json.dumps(data,allow_nan=False)+'\n');stream.flush()
    return {'path':path,'samples':samples,'format':'private native JSONL with original EC diagnostic tables and bounded raw-data report',
            'source_table_entries_per_successful_sample':69}
