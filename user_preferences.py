# SPDX-License-Identifier: GPL-2.0-only
"""Private records of successful user selections, without a policy daemon.

Root callers use their sudo caller's UID. User-file operations run after dropping
privileges; custom XDG paths cannot become privileged filesystem writes.
"""
from pathlib import Path
from contextlib import contextmanager
import datetime
import errno
import fcntl
import hashlib
import json
import os
import pwd
import stat
import subprocess
import sys
import tempfile
import time

LIMIT=8192
_CONTEXT=None
_COMMITTED=False
FIELDS={'battery_charge_limit_percent','platform_profile'}

class PreferenceError(OSError):
    def __init__(self,code,message,committed=False):
        super().__init__(code,message);self.committed=committed


def validate_value(field,value):
    if field=='battery_charge_limit_percent' and type(value) is int and 0<=value<=100:return
    if field=='platform_profile' and isinstance(value,str) and value in ('quiet','balanced','performance'):return
    raise ValueError('Invalid remembered setting or value.')


def configure(home):
    global _CONTEXT
    if home is not None and (not isinstance(home,str) or not 1<=len(home)<=4096 or '\0' in home or not Path(home).is_absolute()):
        raise ValueError('The caller configuration directory must be absolute.')
    _CONTEXT=home


def actor():
    uid=os.getuid()
    if uid==0 and 'SUDO_UID' in os.environ:
        raw=os.environ['SUDO_UID']
        if not raw.isascii() or not raw.isdecimal() or not 0<=int(raw)<2**32-1:raise PermissionError(errno.EACCES,'Invalid sudo caller identity.')
        uid=int(raw)
    try:account=pwd.getpwuid(uid)
    except KeyError:raise OSError(errno.ENOENT,'The caller has no local account.') from None
    return account


def configuration_home():
    account=actor();home=_CONTEXT or os.environ.get('XDG_CONFIG_HOME') or str(Path(account.pw_dir)/'.config')
    if not Path(home).is_absolute() or len(home)>4096 or '\0' in home:raise ValueError('Invalid user configuration directory.')
    return home


def _pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate key')
        result[key]=value
    return result


def _directory(create):
    base=Path(os.environ['XDG_CONFIG_HOME'])/'zenbook-hardware'
    if create:base.mkdir(parents=True,exist_ok=True,mode=0o700)
    try:info=base.lstat()
    except FileNotFoundError:return base,False
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
        raise PermissionError(errno.EACCES,'User settings directory must be private and owned by the caller.')
    return base,True


def _trusted_fd(fd):
    info=os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o777!=0o600 or info.st_nlink!=1:
        raise PermissionError(errno.EACCES,'User settings must be a private owned regular file without hard links.')
    return info


def _load(base):
    path=base/'preferences.json'
    try:fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW|os.O_NONBLOCK)
    except FileNotFoundError:
        return {'schema':1,'values':{},'revision':hashlib.sha256(b'absent').hexdigest(),'exists':False,
                'owner_uid':os.getuid(),'path':str(path)}
    try:
        before=_trusted_fd(fd);raw=os.read(fd,LIMIT+1)
        current=path.lstat()
        if (current.st_dev,current.st_ino)!=(before.st_dev,before.st_ino):raise OSError(errno.EAGAIN,'User settings changed while reading.')
    finally:os.close(fd)
    if len(raw)>LIMIT:raise OSError(errno.EOVERFLOW,'User settings exceed the supported bound.')
    try:value=json.loads(raw,object_pairs_hook=_pairs)
    except (ValueError,UnicodeError):raise OSError(errno.EPROTO,'Invalid user settings JSON.') from None
    if not isinstance(value,dict) or set(value)-{'schema','values','updated_utc'} or type(value.get('schema')) is not int or value['schema']!=1 or not isinstance(value.get('values'),dict) or set(value['values'])-FIELDS:
        raise OSError(errno.EPROTO,'Invalid user settings schema.')
    try:
        for key,item in value['values'].items():validate_value(key,item)
    except ValueError:raise OSError(errno.EPROTO,'Invalid remembered user setting.') from None
    stamp=value.get('updated_utc')
    if stamp is not None and (not isinstance(stamp,str) or len(stamp)>64 or not stamp.isascii() or not all(32<=ord(c)<127 for c in stamp)):
        raise OSError(errno.EPROTO,'Invalid user settings timestamp.')
    return {**value,'revision':hashlib.sha256(raw).hexdigest(),'exists':True,'owner_uid':os.getuid(),'path':str(path)}


@contextmanager
def _locked(base):
    fd=os.open(base/'preferences.lock',os.O_RDWR|os.O_CREAT|os.O_CLOEXEC|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
    try:
        _trusted_fd(fd);deadline=time.monotonic()+1
        while True:
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:
                if time.monotonic()>=deadline:raise OSError(errno.ETIMEDOUT,'User settings are busy.') from None
                time.sleep(.01)
        yield
    finally:os.close(fd)


def _invalid_constant(value):raise ValueError('Non-finite JSON value')


def _application_load(base):
    path=base/'compat.json'
    try:fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW|os.O_NONBLOCK)
    except FileNotFoundError:raw=None;values={}
    else:
        try:
            before=_trusted_fd(fd);raw=os.read(fd,LIMIT+1);current=path.lstat()
            if (current.st_dev,current.st_ino)!=(before.st_dev,before.st_ino):raise OSError(errno.EAGAIN,'Application configuration changed during reading.')
        finally:os.close(fd)
        if len(raw)>LIMIT:raise OSError(errno.EOVERFLOW,'Application configuration exceeds the supported bound.')
        try:values=json.loads(raw,object_pairs_hook=_pairs,parse_constant=_invalid_constant)
        except (ValueError,UnicodeError):raise OSError(errno.EPROTO,'Invalid application configuration JSON.') from None
        if not isinstance(values,dict):raise OSError(errno.EPROTO,'Application configuration must be an object.')
    return {'values':values,'revision':hashlib.sha256(b'absent' if raw is None else raw).hexdigest(),
            'exists':raw is not None,'owner_uid':os.getuid(),'path':str(path)}


def _application(request):
    global _COMMITTED
    if request['op']=='application_read':
        if set(request)!={'op'}:raise ValueError('Invalid application read.')
        base,_=_directory(False);return _application_load(base)
    if set(request)!={'op','path','apply','expected_sha256'} or type(request['apply']) is not bool:
        raise ValueError('Invalid application configuration operation.')
    value=request['path']
    if not isinstance(value,str) or not 1<=len(value)<=4096 or '\0' in value or not Path(value).is_absolute():
        raise ValueError('Application path must be absolute.')
    app=Path(value)
    if not app.is_file() or not (os.access(app,os.X_OK) or app.suffix=='.desktop'):
        raise ValueError('Application path must be an installed executable or desktop file.')
    base,_=_directory(False);before=_application_load(base);after={**before['values'],'app_path':str(app)}
    raw=(json.dumps(after,sort_keys=True,allow_nan=False)+'\n').encode()
    if len(raw)>LIMIT:raise OSError(errno.EOVERFLOW,'Resulting application configuration exceeds the supported bound.')
    plan={'schema':1,'operation':'set_app_path','path':before['path'],'owner_uid':os.getuid(),
          'before':before['values'],'after':after,'expected_sha256':before['revision'],'applied':False}
    if not request['apply']:return plan
    if request['expected_sha256']!=before['revision']:raise OSError(errno.EAGAIN,'Application configuration changed or the reviewed digest was not supplied.')
    base,_=_directory(True)
    with _locked(base):
        if _application_load(base)['revision']!=before['revision']:raise OSError(errno.EAGAIN,'Application configuration changed before update.')
        if before['exists'] and before['values']==after:return {**plan,'unchanged':True,'readback_verified':True}
        fd,tmp=tempfile.mkstemp(prefix='.compat-',dir=base)
        try:
            with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
            if _application_load(base)['revision']!=before['revision']:raise OSError(errno.EAGAIN,'Application configuration changed before replacement.')
            os.replace(tmp,base/'compat.json');_COMMITTED=True
            directory=os.open(base,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
            try:os.fsync(directory)
            finally:os.close(directory)
            current=_application_load(base)
            if current['values']!=after or current['revision']!=hashlib.sha256(raw).hexdigest():
                raise OSError(errno.EAGAIN,'Application configuration changed after replacement.')
            return {**plan,'applied':True,'readback_verified':True,'revision':current['revision']}
        finally:
            if Path(tmp).exists():Path(tmp).unlink()


def _local(request):
    global _COMMITTED
    if not isinstance(request,dict) or request.get('op') not in ('read','update','application_read','application_set'):raise ValueError('Invalid user settings operation.')
    if request['op'].startswith('application_'):return _application(request)
    if request['op']=='read':
        if set(request)-{'op','prepare'} or type(request.get('prepare',False)) is not bool:raise ValueError('Invalid read request.')
        base,exists=_directory(request.get('prepare',False))
        if request.get('prepare'):
            with _locked(base):return _load(base)
        return _load(base)
    if set(request)!={'op','field','value','expected_revision'}:raise ValueError('Invalid update request.')
    validate_value(request['field'],request['value'])
    base,_=_directory(True)
    with _locked(base):
        before=_load(base)
        if request['expected_revision']!=before['revision']:raise OSError(errno.EAGAIN,'Remembered settings changed; retry the operation.')
        if before['values'].get(request['field'])==request['value']:return before
        value={'schema':1,'values':{**before['values'],request['field']:request['value']},
               'updated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
        raw=(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
        if len(raw)>LIMIT:raise OSError(errno.EOVERFLOW,'User settings exceed the supported bound.')
        fd,tmp=tempfile.mkstemp(prefix='.preferences-',dir=base)
        try:
            with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
            if _load(base)['revision']!=before['revision']:raise OSError(errno.EAGAIN,'User settings changed before replacement.')
            os.replace(tmp,base/'preferences.json');_COMMITTED=True
            directory=os.open(base,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
            try:os.fsync(directory)
            finally:os.close(directory)
            after=_load(base)
            if after['values']!=value['values']:raise OSError(errno.EAGAIN,'Remembered settings changed after replacement.')
            return after
        finally:
            if Path(tmp).exists():Path(tmp).unlink()


def _request(request):
    account=actor();config_home=configuration_home()
    kwargs={'input':json.dumps(request),'text':True,'capture_output':True,'timeout':5,'cwd':'/',
            'env':{'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','XDG_CONFIG_HOME':config_home}}
    if os.geteuid()==0:
        groups=os.getgrouplist(account.pw_name,account.pw_gid)
        kwargs.update(user=account.pw_uid,group=account.pw_gid,
                      extra_groups=sorted(set(groups)-{account.pw_gid}))
    try:proc=subprocess.run([sys.executable,str(Path(__file__).resolve()),'_worker'],**kwargs)
    except subprocess.TimeoutExpired:raise PreferenceError(errno.ETIMEDOUT,'User settings worker timed out; verify saved settings.',None) from None
    if len(proc.stdout)>32768:raise PreferenceError(errno.EOVERFLOW,'Invalid user settings response.',None)
    try:body=json.loads(proc.stdout)
    except ValueError:raise PreferenceError(errno.EPROTO,'Invalid user settings response.',None) from None
    if not isinstance(body,dict) or type(body.get('ok')) is not bool:raise PreferenceError(errno.EPROTO,'Invalid user settings status.',None)
    if not body['ok']:
        code=body.get('errno');code=code if type(code) is int and 0<code<4096 else errno.EIO
        raise PreferenceError(code,body.get('error','User settings failed.'),body.get('committed'))
    result=body.get('result')
    if proc.returncode or not isinstance(result,dict) or result.get('owner_uid')!=account.pw_uid or type(result.get('owner_uid')) is not int:
        raise PreferenceError(errno.EPROTO,'User settings caller identity mismatch.',None)
    return result


def read(prepare=False):return _request({'op':'read','prepare':prepare})

def remember(field,value,expected_revision):
    validate_value(field,value)
    return _request({'op':'update','field':field,'value':value,'expected_revision':expected_revision})


def application_config():return _request({'op':'application_read'})


def set_application_path(path,apply=False,expected_sha256=None):
    return _request({'op':'application_set','path':path,'apply':apply,'expected_sha256':expected_sha256})


def _main():
    if sys.argv[1:]!=['_worker']:raise SystemExit('Internal user settings helper.')
    try:
        raw=sys.stdin.buffer.read(LIMIT+1)
        if len(raw)>LIMIT:raise ValueError('Request too large')
        result=_local(json.loads(raw));print(json.dumps({'ok':True,'result':result}));return 0
    except Exception as error:
        code=getattr(error,'errno',None) or (errno.EINVAL if isinstance(error,ValueError) else errno.EIO)
        print(json.dumps({'ok':False,'errno':code,'error':str(error) if isinstance(error,OSError) else 'Invalid user settings request.','committed':_COMMITTED}));return 1

if __name__=='__main__':sys.exit(_main())
