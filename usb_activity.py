# SPDX-License-Identifier: GPL-2.0-only
"""Bounded USB traffic counters using usbmon headers; never request payloads."""
import ctypes
import errno
import fcntl
import math
import os
from pathlib import Path
import select
import struct
import stat
import subprocess
import time


class GetArg(ctypes.Structure):
    _fields_=[('header',ctypes.c_void_p),('data',ctypes.c_void_p),('alloc',ctypes.c_size_t)]

MAX_EVENTS=20000
GET_STATS=(2<<30)|(8<<16)|(0x92<<8)|3
FLUSH=(0x92<<8)|8

def statistics(fd):
    data=bytearray(8);fcntl.ioctl(fd,GET_STATS,data,True)
    return struct.unpack('=II',data)


def sample(seconds=.2):
    if type(seconds) not in (int,float) or not math.isfinite(seconds) or not .05<=seconds<=1:raise ValueError('USB sample must be a finite0.05..1 seconds.')
    path=Path('/dev/usbmon0')
    if not path.exists():
        if os.geteuid()!=0:raise PermissionError(errno.EACCES,'USB activity counters require privilege.')
        import linux_services
        subprocess.run([linux_services.system_tool('modprobe'),'usbmon'],check=True,timeout=8,capture_output=True)
        if not path.exists():raise OSError(errno.ENODEV,'The standard Linux usbmon provider is unavailable.')
    fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_CLOEXEC|os.O_NOFOLLOW)
    try:
        if not stat.S_ISCHR(os.fstat(fd).st_mode):raise OSError(errno.ENODEV,'Opened USB monitor is not a character device.')
        header=ctypes.create_string_buffer(64)
        arg=GetArg(ctypes.addressof(header),None,0)
        # MON_IOCX_GETX uses a 64-byte header. NULL data/alloc=0 prevent all
        # transfer payload copies, including keyboard and storage contents.
        operation=(1<<30)|(ctypes.sizeof(arg)<<16)|(0x92<<8)|10
        poll=select.poll();poll.register(fd,select.POLLIN)
        queued,initial_dropped=statistics(fd)
        if queued:fcntl.ioctl(fd,FLUSH,queued) # This newly opened reader's queue only.
        start=time.monotonic();boot_start=time.clock_gettime(time.CLOCK_BOOTTIME)
        end=start+seconds;events=0;completed=0;total=0;iso_errors=0
        while time.monotonic()<end and events<MAX_EVENTS:
            wait=max(1,int((end-time.monotonic())*1000))
            ready=poll.poll(wait)
            if not ready:continue
            if any(mask&(select.POLLERR|select.POLLHUP|select.POLLNVAL) for _,mask in ready):raise OSError(errno.EIO,'USB monitor poll failed.')
            if not any(mask&select.POLLIN for _,mask in ready):continue
            ctypes.memset(ctypes.addressof(header),0,64)
            try:fcntl.ioctl(fd,operation,arg)
            except BlockingIOError:continue
            events+=1
            # Exclude control and interrupt transfers (e.g. HID); report bulk
            # and isochronous traffic across disks, network, cameras and audio.
            raw=header.raw
            if raw[8] not in (ord('S'),ord('C'),ord('E')) or raw[9] not in (0,1,2,3):raise OSError(errno.EPROTO,'Invalid USB monitor event header.')
            if raw[8]==ord('C') and raw[9] in (0,3) and struct.unpack_from('=i',raw,28)[0]==0:
                if raw[9]==0:
                    count=struct.unpack_from('=i',raw,40)[0]
                    if count<0:raise OSError(errno.EPROTO,'Invalid isochronous error count.')
                    if count:iso_errors+=1;continue
                completed+=1;total+=struct.unpack_from('=I',raw,32)[0]
        pending,dropped=statistics(fd);boot_end=time.clock_gettime(time.CLOCK_BOOTTIME);elapsed=time.monotonic()-start
        if not math.isfinite(elapsed) or elapsed<=0 or abs((boot_end-boot_start)-elapsed)>.05:
            raise OSError(errno.ESTALE,'USB sampling interval is invalid or crossed suspend.')
        complete=not (dropped or pending or events>=MAX_EVENTS or iso_errors)
        return {'available':complete,'capture_complete':complete,'active':True if total else False if complete else None,
                'completed_transfers':completed,'bytes':total if complete else None,'observed_successful_bytes':total,
                'sample_seconds':elapsed,'requested_seconds':seconds,'observed_events':events,
                'event_limit_reached':events>=MAX_EVENTS,'dropped_events':dropped,'pending_events':pending,
                'iso_error_completions':iso_errors,'pre_window_discarded_events':queued,'pre_window_dropped_events':initial_dropped,
                'source':'usbmon successful bulk/isochronous completion header counters','payload_bytes_requested':0,
                'scope':'Completed transfers may span the sample window; this is not electrical USB bus bandwidth. Incomplete capture bytes are a lower bound; inactive is unknown without complete coverage.'}
    finally:os.close(fd)
