#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Privileged Zenbook hardware service: org.zenbook.Hardware1 on the system bus.

Run as `/usr/bin/python3 -I -B <runtime>/service/zenbook_hardwared.py` from the
root-owned versioned runtime. Every method is authorised in-process with polkit
CheckAuthorization on the caller's unique bus name; the bus policy only limits
name ownership. Provider code is the existing runtime, imported in-process.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import argparse
import errno
import importlib
import json
import os
import signal
import stat
import sys
import time

# Never write bytecode, and never read cached bytecode from __pycache__
# directories: imports compile from the (ownership-checked) sources.
if __name__=='__main__':
    sys.dont_write_bytecode=True
    sys.pycache_prefix='/nonexistent/zenbook-hardwared-no-bytecode'
HERE=Path(__file__).resolve().parent
# -I leaves the script directory off sys.path; import only from this runtime.
if str(HERE) not in sys.path:sys.path.insert(0,str(HERE))
import hwd_core as core  # noqa: E402

POLKIT_NAME='org.freedesktop.PolicyKit1'
POLKIT_PATH='/org/freedesktop/PolicyKit1/Authority'
POLKIT_INTERFACE='org.freedesktop.PolicyKit1.Authority'
POLKIT_ALLOW_INTERACTION=1
DEFAULT_MARKER='/run/zenbook-hardware/fan-lease.json'
CALL_TIMEOUT=45
HARD_TIMEOUT=120
MAX_PENDING=8
POLKIT_TIMEOUT_MS=25000
POLKIT_INTERACTIVE_TIMEOUT_MS=180000
IDLE_SECONDS=60

XML='''<node>
 <interface name="org.zenbook.Hardware1">
  <method name="Call">
   <arg name="name" type="s" direction="in"/>
   <arg name="args_json" type="s" direction="in"/>
   <arg name="apply" type="b" direction="in"/>
   <arg name="expected_sha256" type="s" direction="in"/>
   <arg name="result_json" type="s" direction="out"/>
  </method>
  <method name="PlanMutation">
   <arg name="name" type="s" direction="in"/>
   <arg name="args_json" type="s" direction="in"/>
   <arg name="result_json" type="s" direction="out"/>
  </method>
  <method name="ApplyMutation">
   <arg name="token" type="s" direction="in"/>
   <arg name="result_json" type="s" direction="out"/>
  </method>
  <method name="VitalsMetrics">
   <arg name="result_json" type="s" direction="out"/>
  </method>
  <method name="Metrics">
   <arg name="result_json" type="s" direction="out"/>
  </method>
  <method name="Control">
   <arg name="command" type="s" direction="in"/>
   <arg name="args_json" type="s" direction="in"/>
   <arg name="result_json" type="s" direction="out"/>
  </method>
  <method name="AcquireFanLease">
   <arg name="seconds" type="u" direction="in"/>
   <arg name="request" type="s" direction="in"/>
   <arg name="lease_id" type="s" direction="out"/>
  </method>
  <method name="ReleaseFanLease">
   <arg name="lease_id" type="s" direction="in"/>
   <arg name="result_json" type="s" direction="out"/>
  </method>
  <method name="SetFanAuto">
   <arg name="result_json" type="s" direction="out"/>
  </method>
  <property name="Version" type="s" access="read"/>
  <signal name="FanLeaseEnded">
   <arg name="lease_id" type="s"/>
   <arg name="reason" type="s"/>
  </signal>
 </interface>
</node>'''


def check_trusted(runtime):
    """As root, refuse a runtime that a non-root user could have modified:
    every directory and file below it (including any __pycache__) and every
    parent directory must be root-owned, not group/world-writable and not a
    symlink."""
    paths=[]
    parent=runtime.parent
    while parent!=parent.parent:paths.append(parent);parent=parent.parent
    for top,directories,files in os.walk(runtime,followlinks=False):
        paths.append(Path(top));paths.extend(Path(top)/n for n in files)
        paths.extend(Path(top)/n for n in directories if (Path(top)/n).is_symlink())
    for path in paths:
        info=path.lstat()
        if info.st_uid!=0 or info.st_mode&0o022 or stat.S_ISLNK(info.st_mode):
            raise PermissionError(errno.EPERM,'Untrusted runtime path: '+str(path))


def self_test(GLib):
    """PyGObject callbacks use libffi closures; under MemoryDenyWriteExecute a
    libffi without static trampolines fails here, before the name is owned."""
    seen=[]
    context=GLib.MainContext.new();source=GLib.timeout_source_new(0)
    source.set_callback(lambda *_a:(seen.append(True),False)[-1]);source.attach(context)
    for _ in range(10):
        context.iteration(False)
        if seen:break
    source.destroy()
    if not seen:raise RuntimeError('GLib callback did not run.')
    return True


def signal_adder(gi,GLib):
    """GLibUnix.signal_add (newer GLib/PyGObject) or GLib.unix_signal_add
    (older, e.g. Ubuntu 24.04); both are (priority, signum, handler)."""
    try:
        gi.require_version('GLibUnix','2.0')
        module=importlib.import_module('gi.repository.GLibUnix')
        function=getattr(module,'signal_add',None)
        if callable(function):return function
    except (ImportError,ValueError,AttributeError):pass
    for name in ('unix_signal_add','unix_signal_add_full'):
        function=getattr(GLib,name,None)
        if callable(function):return function
    raise RuntimeError('No GLib Unix signal source API (GLibUnix.signal_add or GLib.unix_signal_add).')


class RuntimeBackend:
    """In-process access to the existing provider runtime."""

    def __init__(self,runtime):
        self.runtime=Path(runtime).resolve()
        if str(self.runtime) not in sys.path:sys.path.insert(1,str(self.runtime))
        self.capabilities=json.loads((self.runtime/'capabilities.json').read_text())
        self.bridge=importlib.import_module('api_bridge')
        self.compat=importlib.import_module('compat')

    def version(self):return str(self.capabilities.get('module_version',''))
    def exports(self):return set(self.capabilities['exports'])
    def module_loaded(self):return Path('/sys/module/zenbook_healthytable').exists()

    def fan_device(self):return importlib.import_module('native_oem').device()

    def call(self,name,args,apply,digest):
        if name in core.HARDWARE_ONLY:
            command,key,field=core.HARDWARE_ONLY[name]
            self.compat.validate(name,args,apply,digest)
            result=self.compat.frontend().control(SimpleNamespace(command=command,value=args[key]))
            return {**result,'remembered':False,'client_persistence':{'field':field,'value':args[key]}}
        return self.bridge.call({'name':name,'args':args,'apply':apply,'expected_sha256':digest})

    def metrics(self):return importlib.import_module('metrics').report()

    def vitals(self):
        """The Vitals subset; one failing section does not hide the others."""
        result={'schema':1}
        for section,(module,function) in core.VITALS_SECTIONS.items():
            try:result[section]=getattr(importlib.import_module(module),function)()
            except (OSError,RuntimeError,ValueError) as error:
                result[section]={'available':False,'errno':getattr(error,'errno',None) or errno.EIO,'error':str(error)}
        return result

    def control(self,command,args):
        front=self.compat.frontend()
        if command=='profile':
            if set(args)!={'value'} or args['value'] not in ('quiet','balanced','performance'):raise ValueError('profile needs value quiet, balanced or performance.')
            request=SimpleNamespace(command='profile',value=args['value'])
        elif command in ('charge-limit','keyboard'):
            top=100 if command=='charge-limit' else 3
            if set(args)!={'value'} or type(args['value']) is not int or not 0<=args['value']<=top:raise ValueError(command+' needs integer value 0..'+str(top)+'.')
            request=SimpleNamespace(command=command,value=args['value'])
        elif command=='charger':
            if set(args)-{'connector'} or args.get('connector') not in (None,1,2) or type(args.get('connector')) is bool:raise ValueError('connector must be 1 or 2.')
            request=SimpleNamespace(command='charger',connector=args.get('connector'))
        else:
            if args:raise ValueError('This control takes no arguments.')
            request=SimpleNamespace(command='battery-history' if command=='battery-history-refresh' else command,refresh=True)
        return front.control(request)


class Daemon:
    def __init__(self,Gio,GLib,connection,backend,authorization,audit,limiter,leases,loop,idle_seconds=IDLE_SECONDS,clock=time.monotonic):
        self.Gio=Gio;self.GLib=GLib;self.conn=connection;self.backend=backend;self.authorization=authorization
        self.audit=audit;self.limiter=limiter;self.leases=leases;self.loop=loop;self.idle_seconds=idle_seconds
        self.clock=clock;self.last_activity=clock();self.inflight=0;self.pending=0;self.running={}
        self.cache=core.ResultCache(clock=clock);self.tokens=core.MutationTokens(clock=clock);self.waiters={}
        self.slow_cache=core.ResultCache(clock=clock,seconds=core.SLOW_SECONDS);self.group_refreshed={}
        self.worker=ThreadPoolExecutor(max_workers=1,thread_name_prefix='provider')
        self.uids={};self.lease_watch=None;self.tick_source=None;self.registration=None

    # ---- bus plumbing -------------------------------------------------
    def register(self):
        node=self.Gio.DBusNodeInfo.new_for_xml(XML)
        self.registration=self.conn.register_object(core.OBJECT_PATH,node.interfaces[0],self.on_method,self.on_property,None)
        self.GLib.timeout_add_seconds(5,self.check_idle)

    def on_property(self,connection,sender,path,interface,name):
        if name=='Version':return self.GLib.Variant('s',self.backend.version())
        return None

    def emit_lease_end(self,lease_id,reason):
        try:self.conn.emit_signal(None,core.OBJECT_PATH,core.INTERFACE,'FanLeaseEnded',self.GLib.Variant('(ss)',(lease_id,reason)))
        except Exception:pass  # noqa: S110 - signal delivery is best effort; restoration already happened
        self.unwatch_owner()

    def caller_uid(self,sender):
        if sender in self.uids:return self.uids[sender]
        reply=self.conn.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetConnectionUnixUser',
            self.GLib.Variant('(s)',(sender,)),self.GLib.VariantType('(u)'),self.Gio.DBusCallFlags.NONE,2000,None)
        if len(self.uids)>1024:self.uids.clear()
        self.uids[sender]=uid=reply.unpack()[0];return uid

    def check_idle(self):
        busy=self.inflight or self.pending or self.leases.needs_ticks()
        if busy:self.last_activity=self.clock()
        if any(self.clock()-started>HARD_TIMEOUT for started in list(self.running.values())):
            self.audit.write(event='provider_wedged',reason='hard_timeout',result='error')
            self.leases.stop();os._exit(70)
        if not busy and self.idle_seconds and self.clock()-self.last_activity>self.idle_seconds:
            self.loop.quit();return False
        return True

    # ---- authorisation ------------------------------------------------
    def authorize(self,invocation,sender,action,done):
        flags=0
        if invocation.get_message().get_flags()&self.Gio.DBusMessageFlags.ALLOW_INTERACTIVE_AUTHORIZATION:flags=POLKIT_ALLOW_INTERACTION
        subject=('system-bus-name',{'name':self.GLib.Variant('s',sender)})
        self.inflight+=1
        def finished(connection,result):
            self.inflight-=1;self.last_activity=self.clock()
            try:
                authorized,challenge,_details=connection.call_finish(result).unpack()[0]
                if authorized:return done(None)
                done(core.ServiceError(errno.EACCES,'Not authorized by polkit for '+action+('; interactive authentication required.' if challenge else '.')))
            except Exception as error:
                done(core.ServiceError(errno.EACCES,'polkit authorization unavailable: '+type(error).__name__))
        self.conn.call(POLKIT_NAME,POLKIT_PATH,POLKIT_INTERFACE,'CheckAuthorization',
            self.GLib.Variant('((sa{sv})sa{ss}us)',(subject,action,{},flags,'')),self.GLib.VariantType('((bba{ss}))'),
            self.Gio.DBusCallFlags.NONE,POLKIT_INTERACTIVE_TIMEOUT_MS if flags else POLKIT_TIMEOUT_MS,None,finished)

    # ---- execution ----------------------------------------------------
    def run_in_worker(self,function,reply,timeout_error=None,late=None):
        """Run provider work off the main loop. After CALL_TIMEOUT the caller gets
        timeout_error() (default ETIMEDOUT); a job that still finishes later is
        passed to late(result, error) so its real outcome can be recorded."""
        if self.pending>=MAX_PENDING:return reply(None,core.ServiceError(errno.EBUSY,'Too many pending hardware requests.'))
        self.pending+=1;state={'replied':False};job=object()
        def complete(future):
            self.running.pop(job,None)
            def deliver():
                self.pending-=1;self.last_activity=self.clock()
                if state['replied']:
                    if late is not None:
                        try:value,failure=future.result(),None
                        except Exception as error:value,failure=None,error
                        late(value,failure)
                    return False
                state['replied']=True
                try:reply(future.result(),None)
                except Exception as error:reply(None,error)
                return False
            self.GLib.idle_add(deliver)
        def started():
            # Every job has its own start time, so HARD_TIMEOUT covers each one.
            self.running[job]=self.clock();return function()
        future=self.worker.submit(started);future.add_done_callback(complete)
        def expire():
            if not state['replied'] and not future.done():
                state['replied']=True
                reply(None,timeout_error() if timeout_error else core.ServiceError(errno.ETIMEDOUT,'Hardware request exceeded its time bound.'))
            return False
        self.GLib.timeout_add_seconds(CALL_TIMEOUT,expire)

    def on_method(self,connection,sender,path,interface,method,parameters,invocation):
        self.last_activity=self.clock()
        try:uid=self.caller_uid(sender)
        except Exception:
            return invocation.return_dbus_error(core.dbus_error_name(errno.EACCES),'Caller identity unavailable.')
        handler={'Call':self.do_call,'PlanMutation':self.do_plan,'ApplyMutation':self.do_apply,'Metrics':self.do_metrics,'VitalsMetrics':self.do_vitals,'Control':self.do_control,'AcquireFanLease':self.do_acquire,
                 'ReleaseFanLease':self.do_release,'SetFanAuto':self.do_set_auto}.get(method)
        if handler is None:return invocation.return_dbus_error('org.freedesktop.DBus.Error.UnknownMethod','Unknown method.')
        handler(invocation,sender,uid,parameters.unpack())

    def reply_json(self,invocation,result,error):
        invocation.return_value(self.GLib.Variant('(s)',(core.success(result) if error is None else core.failure(error),)))

    def reply_plain(self,invocation,value,error):
        if error is None:return invocation.return_value(self.GLib.Variant('(s)',(value,)))
        code=getattr(error,'errno',None) or errno.EIO
        invocation.return_dbus_error(core.dbus_error_name(code),str(error))

    def limited(self,uid,action):
        return not self.limiter.allow(uid,'mutating' if core.is_mutating(action) else 'read')

    def do_call(self,invocation,sender,uid,params):
        name,args_json,apply,digest=params
        try:name,args,apply,digest,action=core.parse_call(name,args_json,apply,digest,self.authorization)
        except core.ServiceError as error:return self.reply_json(invocation,None,error)
        audit=core.is_mutating(action)
        def log(result,code=None):
            if audit:self.audit.write(event='call',uid=uid,sender=sender,action=action,name=name,apply=apply,arg_keys=core.arg_keys(args),result=result,errno=code)
        def fail(error,result='refused'):
            log(result,core.error_detail(error)['errno']);self.reply_json(invocation,None,error)
        if self.limited(uid,action):return fail(core.ServiceError(errno.EAGAIN,'Rate limit exceeded; retry later.'))
        if apply and name in core.MUTATION_EXPORTS:
            return fail(core.ServiceError(errno.EPERM,'Apply through the service needs a token: call PlanMutation, then ApplyMutation.'))
        if name in core.CLIENT_ONLY:return fail(core.ServiceError(errno.EOPNOTSUPP,name+' is performed by the unprivileged client: '+core.CLIENT_ONLY[name]+'.'))
        if action==core.FIRMWARE and apply:
            return fail(core.ServiceError(errno.EOPNOTSUPP,'Firmware writes need CAP_LINUX_IMMUTABLE and the backup directory, which this sandboxed service does not hold; use the root CLI.'))
        if action==core.DRIVER and (apply or not self.backend.module_loaded()):
            return fail(core.ServiceError(errno.EOPNOTSUPP,'Driver load/unload needs CAP_SYS_MODULE, which this service does not hold; use the root CLI.'))
        def authorized(error):
            if error is not None:return fail(error,'denied')
            if name in core.FAN_EXPORTS:
                # Runs on the main loop under the lease lock so it cannot race
                # with expiry/disconnect restoration.
                with self.leases.lock:
                    try:
                        if not self.leases.held_by(sender) and not (name=='HealthyTable_SetFanTestMode' and args.get('manual') is False):
                            raise core.ServiceError(errno.EPERM,'Manual fan requests require an active fan lease held by this caller.')
                        result=self.backend.call(name,args,apply,digest)
                    except Exception as failure:return fail(failure,'error')
                log('ok');return self.reply_json(invocation,result,None)
            if name in core.SLOW_CALLS:
                def slow_reply(text,failure):
                    if failure is not None:return fail(failure,'error')
                    invocation.return_value(self.GLib.Variant('(s)',(text,)))
                return self.slow_call(name,args,uid,sender,slow_reply)
            key=core.ResultCache.key(name,args) if core.cacheable(name,action,apply) else None
            cached=self.cache.get(key) if key else None
            if cached is not None:
                # Served on the main loop: a slow provider call cannot delay it.
                return invocation.return_value(self.GLib.Variant('(s)',(cached,)))
            def reply(result,failure):
                self.report_denials(name,uid,sender,result,failure)
                if failure is not None:return fail(failure,'error')
                log('ok')
                try:text=core.success(result)
                except (TypeError,ValueError) as error:return fail(error,'error')
                if key:self.cache.put(key,text)
                invocation.return_value(self.GLib.Variant('(s)',(text,)))
            self.run_in_worker(lambda:self.backend.call(name,args,apply,digest),reply)
        self.authorize(invocation,sender,action,authorized)

    def do_plan(self,invocation,sender,uid,params):
        name,args_json=params
        try:name,args,_apply,_digest,action=core.parse_call(name,args_json,False,'',self.authorization)
        except core.ServiceError as error:return self.reply_json(invocation,None,error)
        def finish(result,error,event_result=None):
            self.audit.write(event='plan',uid=uid,sender=sender,action=action,name=name,arg_keys=core.arg_keys(args),
                             result=event_result or ('ok' if error is None else 'error'),errno=None if error is None else core.error_detail(error)['errno'],
                             token=result.get('service_token','')[:8] or None if isinstance(result,dict) else None)
            self.reply_json(invocation,result,error)
        if name not in core.MUTATION_EXPORTS:return finish(None,core.ServiceError(errno.EINVAL,'This export has no plan/apply step.'),'refused')
        if self.limited(uid,action):return finish(None,core.ServiceError(errno.EAGAIN,'Rate limit exceeded; retry later.'),'refused')
        def authorized(error):
            if error is not None:return finish(None,error,'denied')
            def planned(plan,failure):
                if failure is not None:return finish(None,failure)
                if not isinstance(plan,dict):return finish(None,core.ServiceError(errno.EPROTO,'Unexpected plan shape.'))
                plan=dict(plan)
                if name in core.SERVICE_APPLY:
                    try:token=self.tokens.issue(sender,uid,action,name,args,plan.get('expected_sha256'))
                    except core.ServiceError as issue:return finish(None,issue)
                    plan.update(service_token=token,service_token_expires_in=core.TOKEN_SECONDS,service_apply_supported=True)
                else:plan['service_apply_supported']=False
                finish(plan,None)
            self.run_in_worker(lambda:self.backend.call(name,args,False,None),planned)
        self.authorize(invocation,sender,action,authorized)

    def do_apply(self,invocation,sender,uid,params):
        (token,)=params
        try:entry=self.tokens.consume(token,sender,uid)
        except core.ServiceError as error:
            self.audit.write(event='apply',uid=uid,sender=sender,result='refused',errno=error.errno)
            return self.reply_json(invocation,None,error)
        name,args,action=entry['name'],entry['args'],entry['action']
        def finish(result,error,event_result=None):
            if event_result is None and getattr(error,'outcome_unknown',False):event_result='outcome_unknown'
            self.audit.write(event='apply',uid=uid,sender=sender,action=action,name=name,apply=True,arg_keys=core.arg_keys(args),token=token[:8],
                             result=event_result or ('ok' if error is None else 'error'),errno=None if error is None else core.error_detail(error)['errno'])
            self.reply_json(invocation,result,error)
        def outcome_unknown():
            # The worker cannot be cancelled once it may be writing, so a
            # timeout is not a failure: the mutation may still commit.
            error=core.ServiceError(errno.EINPROGRESS,'Apply exceeded its time bound while the provider may still commit; '
                                    'the outcome is unknown. Read the state back before planning again.')
            error.outcome_unknown=True;return error
        def late(result,error):
            # The eventual worker outcome after the caller was told outcome_unknown.
            self.audit.write(event='apply_late_outcome',uid=uid,sender=sender,action=action,name=name,apply=True,arg_keys=core.arg_keys(args),
                             token=token[:8],result='ok' if error is None else 'error',errno=None if error is None else core.error_detail(error)['errno'])
        if self.limited(uid,action):return finish(None,core.ServiceError(errno.EAGAIN,'Rate limit exceeded; retry later.'),'refused')
        def authorized(error):
            # Re-checked at apply: ec-oem is auth_admin without _keep.
            if error is not None:return finish(None,error,'denied')
            def apply():
                fresh=self.backend.call(name,args,False,None)
                if not isinstance(fresh,dict) or fresh.get('expected_sha256')!=entry['digest']:
                    raise core.ServiceError(errno.EAGAIN,'The target state or plan changed since PlanMutation; plan again.')
                return self.backend.call(name,args,True,entry['digest'])
            self.run_in_worker(apply,finish,timeout_error=outcome_unknown,late=late)
        self.authorize(invocation,sender,action,authorized)

    def report_denials(self,name,uid,sender,result=None,error=None):
        """Log a sandbox_denied marker when a provider hit EPERM/EACCES, either as
        the whole reply or inside rows of an otherwise successful report."""
        count=core.sandbox_denials(result) if error is None else int(getattr(error,'errno',None) in core.SANDBOX_ERRNOS)
        if count:self.audit.write(event='sandbox_denied',uid=uid,sender=sender,name=name,count=count,
                                  errno=getattr(error,'errno',None) if error is not None else None)

    def shared(self,key,function,deliver,cache,before_run=None,name=None,uid=None,sender=None):
        """Run function at most once for concurrent requests with the same key;
        successful serialised replies go into cache. deliver(text, failure)."""
        if key in self.waiters:
            if len(self.waiters[key])>=64:return deliver(None,core.ServiceError(errno.EBUSY,'Too many waiting requests.'))
            self.waiters[key].append(deliver);return None
        self.waiters[key]=[deliver]
        if before_run:before_run()
        def reply(result,failure):
            waiting=self.waiters.pop(key,[]);text=None
            if name:self.report_denials(name,uid,sender,result,failure)
            if failure is None:
                try:text=core.success(result);cache.put(key,text)
                except (TypeError,ValueError) as error:failure=error
            for waiter in waiting:waiter(text,failure)
        self.run_in_worker(function,reply)

    def deliver_to(self,invocation):
        def deliver(text,failure):
            if text is not None:invocation.return_value(self.GLib.Variant('(s)',(text,)))
            else:self.reply_json(invocation,None,failure)
        return deliver

    def cached_report(self,invocation,key,function):
        """Shared 2 s cache for whole reports. Hits are answered on the main loop;
        concurrent misses coalesce into one provider job."""
        cached=self.cache.get(key)
        if cached is not None:return invocation.return_value(self.GLib.Variant('(s)',(cached,)))
        self.shared(key,function,self.deliver_to(invocation),self.cache,name=key[0])

    def slow_call(self,name,args,uid,sender,deliver):
        """Slow class without needless EAGAIN: serve the last result for the same
        (name, args) within 10 s, join an in-flight refresh, ride along a shared
        group refresh, or wait up to 5 s for the per-uid/global budget."""
        key=core.ResultCache.key(name,args)
        cached=self.slow_cache.get(key)
        if cached is not None:return deliver(cached,None)
        if key in self.waiters:return self.shared(key,None,deliver,self.slow_cache)
        group=core.SLOW_GROUPS.get(name,name)
        def mark():self.group_refreshed[group]=self.clock()
        def start():
            self.shared(key,lambda:self.backend.call(name,args,False,None),deliver,self.slow_cache,before_run=mark,name=name,uid=uid,sender=sender)
        if self.clock()-self.group_refreshed.get(group,-1e9)<core.SLOW_SECONDS:return start()
        if self.limiter.allow_slow(uid):return start()
        wait=core.slow_wait(self.limiter,uid)
        if wait>core.SLOW_WAIT_SECONDS:
            return deliver(None,core.ServiceError(errno.EAGAIN,'Heavy read budget exhausted (one refresh per 10 s); retry later.'))
        # Queue one refresh; later identical requests join it as waiters.
        self.waiters[key]=[deliver];self.pending+=1
        def retry():
            self.pending-=1
            waiting=self.waiters.pop(key,[])
            if not waiting:return False
            if not self.limiter.allow_slow(uid):
                for waiter in waiting:waiter(None,core.ServiceError(errno.EAGAIN,'Heavy read budget exhausted (one refresh per 10 s); retry later.'))
                return False
            self.shared(key,lambda:self.backend.call(name,args,False,None),waiting[0],self.slow_cache,before_run=mark,name=name,uid=uid,sender=sender)
            self.waiters[key].extend(waiting[1:])
            return False
        self.GLib.timeout_add(int(wait*1000)+20,retry)

    def do_metrics(self,invocation,sender,uid,params):
        if self.limited(uid,core.READ):return self.reply_json(invocation,None,core.ServiceError(errno.EAGAIN,'Rate limit exceeded; retry later.'))
        def authorized(error):
            if error is not None:return self.reply_json(invocation,None,error)
            self.cached_report(invocation,('__metrics__',''),self.backend.metrics)
        self.authorize(invocation,sender,core.READ,authorized)

    def do_vitals(self,invocation,sender,uid,params):
        if self.limited(uid,core.READ):return self.reply_json(invocation,None,core.ServiceError(errno.EAGAIN,'Rate limit exceeded; retry later.'))
        def authorized(error):
            if error is not None:return self.reply_json(invocation,None,error)
            self.cached_report(invocation,('__vitals__',''),self.backend.vitals)
        self.authorize(invocation,sender,core.READ,authorized)

    def do_control(self,invocation,sender,uid,params):
        command,args_json=params
        action=core.CONTROLS.get(command)
        if action is None:return self.reply_json(invocation,None,core.ServiceError(errno.EINVAL,'Unknown control.'))
        try:args=core.parse_args(args_json)
        except core.ServiceError as error:return self.reply_json(invocation,None,error)
        audit=core.is_mutating(action)
        def finish(result,error):
            self.report_denials(command,uid,sender,result,error)
            if audit:self.audit.write(event='control',uid=uid,sender=sender,action=action,command=command,arg_keys=core.arg_keys(args),
                                      result='ok' if error is None else 'error',errno=None if error is None else core.error_detail(error)['errno'])
            self.reply_json(invocation,result,error)
        if self.limited(uid,action):return finish(None,core.ServiceError(errno.EAGAIN,'Rate limit exceeded; retry later.'))
        def authorized(error):
            if error is not None:return finish(None,error)
            if command in core.SLOW_CONTROLS and not self.limiter.allow_slow(uid):
                return finish(None,core.ServiceError(errno.EAGAIN,'Trigger/heavy operation rate limit (one per 10 s); retry later.'))
            self.run_in_worker(lambda:self.backend.control(command,args),finish)
        self.authorize(invocation,sender,action,authorized)

    def do_acquire(self,invocation,sender,uid,params):
        seconds,request=params
        if self.limited(uid,core.FAN_LEASE):return self.reply_plain(invocation,None,core.ServiceError(errno.EAGAIN,'Rate limit exceeded; retry later.'))
        def authorized(error):
            if error is not None:
                self.audit.write(event='fan_lease_acquired',uid=uid,sender=sender,action=core.FAN_LEASE,result='denied',errno=errno.EACCES)
                return self.reply_plain(invocation,None,error)
            try:
                with self.leases.lock:
                    lease=self.leases.acquire(sender,uid,int(seconds),request)
                    self.watch_owner(sender)
            except Exception as failure:
                if not isinstance(failure,core.ServiceError) or failure.errno!=errno.EINVAL:
                    self.audit.write(event='fan_lease_acquired',uid=uid,sender=sender,action=core.FAN_LEASE,result='error',errno=getattr(failure,'errno',None) or errno.EIO)
                return self.reply_plain(invocation,None,failure)
            self.start_ticks();self.reply_plain(invocation,lease,None)
        self.authorize(invocation,sender,core.FAN_LEASE,authorized)

    def do_release(self,invocation,sender,uid,params):
        (lease_id,)=params
        try:result=self.leases.release(lease_id,sender,privileged=uid==0)
        except Exception as error:return self.reply_plain(invocation,None,error)
        self.reply_plain(invocation,core.success(result),None)

    def do_set_auto(self,invocation,sender,uid,params):
        if self.limited(uid,core.READ):return self.reply_json(invocation,None,core.ServiceError(errno.EAGAIN,'Rate limit exceeded; retry later.'))
        def authorized(error):
            if error is not None:return self.reply_json(invocation,None,error)
            try:result=self.leases.set_auto()
            except Exception as failure:result=None;error=failure
            self.audit.write(event='fan_set_auto',uid=uid,sender=sender,action=core.READ,result='ok' if error is None else 'error',
                             errno=None if error is None else core.error_detail(error)['errno'])
            self.reply_json(invocation,result,error)
        self.authorize(invocation,sender,core.READ,authorized)

    # ---- lease supervision --------------------------------------------
    def watch_owner(self,owner):
        self.unwatch_owner()
        def changed(connection,sender_name,path,interface,signal_name,parameters):
            name,_old,new=parameters.unpack()
            if name==owner and not new:self.leases.owner_vanished(owner);self.uids.pop(owner,None)
        self.lease_watch=self.conn.signal_subscribe('org.freedesktop.DBus','org.freedesktop.DBus','NameOwnerChanged','/org/freedesktop/DBus',
                                                    owner,self.Gio.DBusSignalFlags.NONE,changed)
        # Close the race where the holder left before the subscription existed.
        reply=self.conn.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','NameHasOwner',
            self.GLib.Variant('(s)',(owner,)),self.GLib.VariantType('(b)'),self.Gio.DBusCallFlags.NONE,2000,None)
        if not reply.unpack()[0]:self.leases.owner_vanished(owner)

    def unwatch_owner(self):
        if self.lease_watch is not None:
            self.conn.signal_unsubscribe(self.lease_watch);self.lease_watch=None

    def start_ticks(self):
        if self.tick_source is None:self.tick_source=self.GLib.timeout_add(1000,self.tick)

    def tick(self):
        self.leases.tick()
        if self.leases.needs_ticks():return True
        self.tick_source=None;self.unwatch_owner();return False

    def stop(self):
        self.leases.stop();self.loop.quit()
        return False


def build_leases(backend,audit,marker,on_end=None):
    return core.FanLeases(core.SysfsFan(backend.fan_device),audit,marker=marker,on_end=on_end)


def restore_only(backend,audit,marker):
    """ExecStopPost: restore automatic fan only if a lease marker remains."""
    leases=build_leases(backend,audit,marker)
    try:leases.recover();return 0
    except (OSError,RuntimeError) as error:
        audit.write(event='fan_lease_recovered',action=core.FAN_LEASE,reason='stop_post',result='error',errno=getattr(error,'errno',None) or errno.EIO)
        return 1


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore-fan-auto',action='store_true',help='Restore automatic fan if a lease marker remains, then exit')
    parser.add_argument('--bus',choices=('system','session'),default='system',help=argparse.SUPPRESS)
    parser.add_argument('--runtime',type=Path,help=argparse.SUPPRESS)
    parser.add_argument('--marker',type=Path,help=argparse.SUPPRESS)
    parser.add_argument('--idle-timeout',type=int,default=IDLE_SECONDS,help=argparse.SUPPRESS)
    parser.add_argument('--slow-limit',help=argparse.SUPPRESS)
    parser.add_argument('--self-test',action='store_true',help='Check PyGObject callbacks in this sandbox, then exit')
    args=parser.parse_args(argv)
    testing=args.bus!='system' or args.runtime is not None or args.marker is not None or args.slow_limit is not None
    if testing and os.geteuid()==0:parser.error('Test options are refused for root.')
    os.umask(0o077);os.chdir('/')
    runtime=(args.runtime or HERE.parent).resolve()
    if os.geteuid()==0:check_trusted(runtime)
    audit=core.AuditLog()
    marker=args.marker or Path(DEFAULT_MARKER)
    backend=RuntimeBackend(runtime)
    if args.restore_fan_auto:return restore_only(backend,audit,marker)
    authorization=core.load_authorization(backend.exports())

    import gi
    gi.require_version('Gio','2.0');gi.require_version('GLib','2.0')
    from gi.repository import Gio,GLib
    try:self_test(GLib)
    except Exception as error:
        print('zenbook-hardwared: PyGObject callback self-test failed ('+type(error).__name__+'). If MemoryDenyWriteExecute '
              'blocks libffi closures, install the documented zenbook-hardwared-mdwe-off.conf drop-in.',flush=True)
        return 1
    if args.self_test:
        print('zenbook-hardwared: self-test passed',flush=True);return 0
    expected=os.environ.get('ZENBOOK_HWMON_CONTAINER')
    if expected:
        try:actual=str(Path(backend.fan_device()).resolve().parent)
        except (OSError,RuntimeError):actual=None
        if actual!=expected:
            print('zenbook-hardwared: warning: zenbook_ec hwmon container is',actual,'but the sandbox allows writes under',expected,
                  '- rerun tools/install.py --service-only',flush=True)
    loop=GLib.MainLoop();holder={}
    leases=build_leases(backend,audit,marker,on_end=lambda lease_id,reason:holder['daemon'].emit_lease_end(lease_id,reason) if 'daemon' in holder else None)
    try:leases.recover()
    except (OSError,RuntimeError) as error:
        audit.write(event='fan_lease_recovered',action=core.FAN_LEASE,reason='startup',result='error',errno=getattr(error,'errno',None) or errno.EIO)
    state={'status':0}

    def acquired(connection,name):
        print('zenbook-hardwared: serving',name,'version',backend.version(),flush=True)
    def lost(connection,name):
        state['status']=1
        print('zenbook-hardwared: bus name lost',flush=True);loop.quit()
    def bus_acquired(connection,name):
        limiter=core.RateLimiter()
        if args.slow_limit:
            rate,burst=(float(x) for x in args.slow_limit.split(','));limiter.limits['slow']=(rate,burst)
        daemon=Daemon(Gio,GLib,connection,backend,authorization,audit,limiter,leases,loop,args.idle_timeout)
        daemon.register();holder['daemon']=daemon
    bus=Gio.BusType.SYSTEM if args.bus=='system' else Gio.BusType.SESSION
    owner=Gio.bus_own_name(bus,core.BUS_NAME,Gio.BusNameOwnerFlags.DO_NOT_QUEUE,bus_acquired,acquired,lost)
    signal_add=signal_adder(gi,GLib)
    for number in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):
        signal_add(GLib.PRIORITY_HIGH,number,lambda:(leases.stop(),loop.quit(),False)[-1])
    try:loop.run()
    finally:
        leases.stop()
        Gio.bus_unown_name(owner)
        if 'daemon' in holder:holder['daemon'].worker.shutdown(wait=False,cancel_futures=True)
    return state['status']


if __name__=='__main__':sys.exit(main())
