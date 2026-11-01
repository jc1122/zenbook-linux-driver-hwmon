# SPDX-License-Identifier: GPL-2.0-only
"""Rank native process counters without reading command lines or environments."""
from pathlib import Path
import errno
import math
import os
import time

NAMES={'AppList_CpuUsage','AppList_MemUsage'}
WAIT_SECONDS=.2
MIN_INTERVAL_SECONDS=.1
MAX_STAT_BYTES=65536
MAX_STATM_BYTES=4096
MAX_ERROR_DETAILS=64


def validate(name,args):
    if name not in NAMES:raise ValueError('Unknown process-counter query.')
    if not isinstance(args,dict) or args:raise ValueError('Process-counter queries take no arguments.')


def _unsigned(raw):
    if not raw or not raw.isdigit() or len(raw)>20:
        raise OSError(errno.EPROTO,'Invalid process-stat integer.')
    value=int(raw)
    if value>2**64-1:raise OSError(errno.EPROTO,'Process-stat integer overflow.')
    return value


def decode(raw,pid):
    if not isinstance(raw,bytes) or len(raw)>MAX_STAT_BYTES:
        raise OSError(errno.E2BIG,'Process-stat record exceeds its bound.')
    left=raw.find(b' (');right=raw.rfind(b') ')
    if left<1 or right<left+2 or _unsigned(raw[:left])!=pid:
        raise OSError(errno.EPROTO,'Invalid process-stat identity or name framing.')
    fields=raw[right+2:].split()
    if len(fields)<22 or len(fields[0])!=1 or not fields[0].isalpha():
        raise OSError(errno.EPROTO,'Incomplete process-stat counter fields.')
    name=raw[left+2:right]
    if b'\0' in name:raise OSError(errno.EPROTO,'Invalid process name.')
    return {'pid':pid,'name':name.decode('utf-8',errors='replace'),
            'name_encoding_loss':name.decode('utf-8',errors='replace').encode('utf-8')!=name,
            'state':fields[0].decode('ascii'),'user_ticks':_unsigned(fields[11]),
            'system_ticks':_unsigned(fields[12]),'start_ticks':_unsigned(fields[19]),
            'rss_pages':_unsigned(fields[21])}


def _census(root):
    # Names are kernel PID directory entries, never user-provided paths.
    return sorted(int(p.name) for p in root.iterdir()
                  if p.name.isascii() and p.name.isdecimal() and int(p.name)>0)


def decode_statm(raw):
    if not isinstance(raw,bytes) or len(raw)>MAX_STATM_BYTES:
        raise OSError(errno.E2BIG,'Process-statm record exceeds its bound.')
    fields=raw.split()
    if len(fields)<2:raise OSError(errno.EPROTO,'Incomplete resident-memory counters.')
    size=_unsigned(fields[0]);resident=_unsigned(fields[1])
    if resident>size:raise OSError(errno.EPROTO,'Resident pages exceed process virtual size.')
    return resident


def _stat(root,pid,clock):
    before=clock()
    with (root/str(pid)/'stat').open('rb') as stream:raw=stream.read(MAX_STAT_BYTES+1)
    after=clock();row=decode(raw,pid)
    if (type(before) not in (int,float) or type(after) not in (int,float) or
        not math.isfinite(before) or not math.isfinite(after) or after<before):
        raise OSError(errno.EPROTO,'Invalid monotonic process-sampling clock.')
    row.update(sample_monotonic_seconds=(before+after)/2,
               read_window_seconds=after-before)
    return row


def _sample(root,pid,clock):
    before=_stat(root,pid,clock)
    try:
        with (root/str(pid)/'statm').open('rb') as stream:raw=stream.read(MAX_STATM_BYTES+1)
        rss={'rss_available':True,'rss_pages':decode_statm(raw)}
    except OSError as error:
        rss={'rss_available':False,'rss_pages':None,'rss_errno':error.errno or errno.EIO,
             'rss_error':str(error)}
    after=_stat(root,pid,clock)
    if before['start_ticks']!=after['start_ticks']:
        raise OSError(errno.EAGAIN,'PID was reused while bracketing resident memory.')
    after['stat_rss_pages']=after['rss_pages'];after.update(rss)
    return after


def collect(name,root=Path('/proc'),clock=time.monotonic,wait=time.sleep,sysconf=os.sysconf,
            selected_pids=None,all_rows=False):
    validate(name,{})
    if selected_pids is not None:
        if (not isinstance(selected_pids,(list,tuple,set)) or len(selected_pids)>4096 or
            any(type(pid) is not int or not 1<=pid<2**31 for pid in selected_pids)):
            raise ValueError('Invalid selected process IDs.')
        selected_pids=sorted(set(selected_pids))
    ticks=sysconf('SC_CLK_TCK');pages=sysconf('SC_PAGE_SIZE')
    if type(ticks) is not int or ticks<=0 or type(pages) is not int or pages<=0:
        raise OSError(errno.EPROTO,'Invalid native CPU tick or page-size unit.')
    first_pids=_census(root) if selected_pids is None else selected_pids;first={};errors=[]
    def failure(pid,phase,error):
        code=error.errno or errno.EIO
        if code==errno.ENOENT:code=errno.ESRCH
        errors.append({'pid':pid,'phase':phase,'errno':code,'error':str(error)})
    for pid in first_pids:
        try:first[pid]=_sample(root,pid,clock)
        except OSError as error:failure(pid,'baseline',error)
    wait(WAIT_SECONDS)
    last_pids=_census(root) if selected_pids is None else selected_pids;rows=[];missing_cpu=0;missing_rss=0;intervals=[];reused=0
    for pid in last_pids:
        try:last=_sample(root,pid,clock)
        except OSError as error:
            failure(pid,'final',error);missing_cpu+=1;missing_rss+=1;continue
        row={k:last[k] for k in ('pid','name','name_encoding_loss','state','start_ticks')}
        row.update(rss_available=last['rss_available'],
                   rss_bytes=last['rss_pages']*pages if last['rss_available'] else None,
                   cpu_percent=None,cpu_available=False)
        if not last['rss_available']:
            row.update(rss_errno=last['rss_errno'],rss_error=last['rss_error']);missing_rss+=1
            failure(pid,'rss',OSError(last['rss_errno'],last['rss_error']))
        start=first.get(pid)
        try:
            if start is None:raise OSError(errno.ENODATA,'No valid baseline for this process.')
            if start['start_ticks']!=last['start_ticks']:
                reused+=1
                raise OSError(errno.EAGAIN,'PID was reused during sampling.')
            elapsed=last['sample_monotonic_seconds']-start['sample_monotonic_seconds']
            if not math.isfinite(elapsed) or elapsed<MIN_INTERVAL_SECONDS:
                raise OSError(errno.EAGAIN,'Process CPU sampling interval is too short or invalid.')
            read_window=start['read_window_seconds']+last['read_window_seconds']
            if read_window>=elapsed:
                raise OSError(errno.EAGAIN,'Process-stat read uncertainty spans the CPU interval.')
            du=last['user_ticks']-start['user_ticks'];ds=last['system_ticks']-start['system_ticks']
            if du<0 or ds<0:raise OSError(errno.EPROTO,'Process CPU counter regressed.')
            percent=(du+ds)/ticks/elapsed*100
            if not math.isfinite(percent):raise OSError(errno.EPROTO,'Invalid process CPU percentage.')
            row.update(cpu_available=True,cpu_percent=percent,sample_interval_seconds=elapsed,
                       cpu_time_delta_ticks=du+ds,
                       sample_read_window_seconds=read_window)
            intervals.append(elapsed)
        except OSError as error:
            row.update(cpu_errno=error.errno,cpu_error=str(error));missing_cpu+=1
            failure(pid,'cpu_delta',error)
        rows.append(row)
    cpu=name=='AppList_CpuUsage';limit=5 if cpu else 10
    eligible=([r for r in rows if r['cpu_available'] and r['cpu_percent']>0] if cpu
              else [r for r in rows if r['rss_available'] and r['rss_bytes']>0])
    key='cpu_percent' if cpu else 'rss_bytes'
    eligible.sort(key=lambda row:(-row[key],row['pid']))
    missing=missing_cpu if cpu else missing_rss
    known=len(last_pids)-missing
    result={'available':known>0 or missing==0,'processes':rows if all_rows else eligible[:limit],
            'rank_by':key,'limit':limit,'ranking_complete':missing==0,
            'positive_processes_observed':len(eligible),'sampled_processes':len(rows),
            'initial_pid_count':len(first_pids),'final_pid_count':len(last_pids),
            'exited_since_initial_census':len(set(first_pids)-set(last_pids)),
            'new_since_initial_census':len(set(last_pids)-set(first_pids)),
            'reused_pids':reused,'unknown_cpu_processes':missing_cpu,
            'unknown_rss_processes':missing_rss,'sample_errors':errors[:MAX_ERROR_DETAILS],
            'sample_error_count':len(errors),'sample_errors_truncated':len(errors)>MAX_ERROR_DETAILS,
            'sampling':{'requested_wait_seconds':WAIT_SECONDS,'clock_ticks_per_second':ticks,
                        'page_size_bytes':pages,'minimum_interval_seconds':min(intervals,default=None),
                        'maximum_interval_seconds':max(intervals,default=None)},
            'source':'Linux /proc/PID/stat CPU ticks and identity; bracketed statm resident pages',
            'coverage':'PIDs visible in the caller procfs/PID namespace, without a UID filter. Rankings are among valid samples; missing candidates make ranking_complete false.',
            'note':'CPU percent uses one CPU as 100% and may exceed100 for multithreaded work. RSS bytes use statm resident pages times page size, not unique/private memory or the separate stat RSS counter. Names are kernel comm values, which may be truncated. Samples are sequential; new processes lack a CPU baseline. No command line or environment is read.'}
    if not result['available']:
        result.update(errno=errno.ENODATA,error='No valid final candidates for the requested process counter.')
    if all_rows:
        result.update(rank_by=None,limit=None,
                      coverage='Only the supplied existing window-provider PIDs, with zero-valued rows retained. No ranking filter is applied.')
    return result


def call(name,args):
    validate(name,args)
    return collect(name)


def sample_pids(pids):
    """Unranked process values for an existing compositor's reported PIDs."""
    return collect('AppList_MemUsage',selected_pids=pids,all_rows=True)


def verify_identity(pid,start_ticks,root=Path('/proc')):
    if _stat(root,pid,time.monotonic)['start_ticks']!=start_ticks:
        raise OSError(errno.EAGAIN,'Window PID was reused after process sampling.')
