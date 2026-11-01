# SPDX-License-Identifier: GPL-2.0-only
"""Recovered scalar EEPROM diagnostic table and opaque E5 event frames.

Only explicit privileged table calls collect data. No EEPROM writes, stream
reset/clear command or raw BIOS/CMOS reads are implemented here. Event payloads
remain opaque; two unusable replies are the original stop rule, not proof that
the complete history has been read.
"""
import datetime
import errno
import fcntl
import os
from pathlib import Path
import re
import native_oem

MAX_REGISTERS=64
MAX_EVENTS=64
MAX_REPLY_BYTES=1024


def frame(reply):
    if not isinstance(reply,bytes):raise OSError(errno.EPROTO,'EEPROM event reply is not a byte buffer.')
    if len(reply)>MAX_REPLY_BYTES:raise OSError(errno.EOVERFLOW,'EEPROM event reply exceeds1024 bytes.')
    if reply==b'\xfe\xff\xff\xff':raise OSError(errno.EOPNOTSUPP,'EEPROM event query returned the firmware unsupported-method reply.')
    if len(reply)<7:raise OSError(errno.EMSGSIZE,'EEPROM event header is truncated.')
    if reply[:2]!=b'\x5a\xa5':raise OSError(errno.ENODATA,'EEPROM event reply has no accepted frame magic.')
    size=9+reply[6]
    if size>len(reply):raise OSError(errno.EMSGSIZE,'EEPROM event frame is truncated.')
    return {'raw_hex':reply[:size].hex(),'frame_bytes':size,'length_byte_raw':reply[6],
            'payload_decoded':False}


def unsigned(value,label):
    if type(value) is not int or not 0<=value<=0xffffffff:
        raise OSError(errno.EPROTO,'Invalid EEPROM '+label+' reply.')
    return value


def read_table(scalar,buffer,expected_version,max_events=MAX_EVENTS):
    """Protocol adapter with injectable fixed-query transports for fixtures."""
    if type(expected_version) is not int or not 0<=expected_version<=0x7fffffff:
        raise ValueError('A supported probe-time EEPROM version is required.')
    if type(max_events) is not int or not 1<=max_events<=MAX_EVENTS:
        raise ValueError('EEPROM event bound must be1..64.')
    def query(selector,label):return unsigned(scalar(selector),label)
    version=query(0xe0,'version')
    if version!=expected_version:raise OSError(errno.EAGAIN,'EEPROM version changed since module probe.')
    date=query(0x4e1,'manufacture date')
    try:formatted=None if date==0xffffffff else datetime.datetime.fromtimestamp(date).date().isoformat()
    except (ValueError,OverflowError,OSError):raise OSError(errno.EPROTO,'EEPROM local-time date conversion failed.') from None
    def registers(selector,count_selector,label):
        count=query(count_selector,label+' count')
        if count==0xffffffff:raise OSError(errno.ENODATA,'EEPROM '+label+' count is unavailable.')
        if count>MAX_REGISTERS:raise OSError(errno.EOVERFLOW,'EEPROM '+label+' count exceeds the recovered native selector bound.')
        return [f'0x{query(selector+(i<<8),label):08x}' for i in range(count)]
    common=registers(0xe3,0xffe3,'common register')
    bu=registers(0xe7,0xffe7,'BU register') if version>7 else []
    events=[];failures=[];consecutive=0;attempts=0;termination='record_limit'
    while len(events)<max_events:
        attempts+=1
        try:packet=frame(buffer())
        except OSError as error:
            consecutive+=1
            failures.append({'attempt':attempts,'errno':error.errno or errno.EIO,'error':str(error)[:160]})
            if consecutive==2:termination='two_unusable_replies';break
        else:events.append(packet);consecutive=0
    return {'version':version,'M_date':formatted,'M_date_raw':date,'date_timezone':'system local time',
            'register_count':len(common),'register':common,'BU_register_count':len(bu),'BU_register':bu,
            'BU_register_applicable':version>7,'event':events,
            'event_stream':{'available':bool(events),'attempts':attempts,'failures':failures,'termination':termination,
                'record_limit':max_events,'truncated':termination=='record_limit','complete_history_proven':False,
                'note':'Opaque frames only. No checksum, event type, temperature or unit interpretation is claimed. The E5 query may advance firmware diagnostic stream state; no reset/clear is sent.'},
            'sequential_reads':True,'source':'ASUS DEVS0x60059 recovered fixed scalar selectors and E5 frames'}


def collect(expected_version):
    if os.geteuid()!=0:raise PermissionError(errno.EACCES,'EEPROM table collection requires a privileged caller.')
    directory=Path('/run/zenbook-hardware');directory.mkdir(exist_ok=True,mode=0o700)
    descriptor=os.open(directory/'eeprom.lock',os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(descriptor,fcntl.LOCK_EX)
        def scalar(selector):return native_oem.rpc(11,selector,apply=True)['value']
        def buffer():
            response=native_oem.rpc(13,0xe5,apply=True);encoded=response.get('data_hex')
            if not isinstance(encoded,str) or len(encoded)>2*MAX_REPLY_BYTES or len(encoded)%2 or not re.fullmatch('[0-9a-fA-F]*',encoded):
                raise OSError(errno.EPROTO,'Invalid native EEPROM event buffer encoding.')
            return bytes.fromhex(encoded)
        return read_table(scalar,buffer,expected_version)
    finally:os.close(descriptor)
