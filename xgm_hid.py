# SPDX-License-Identifier: GPL-2.0-only
"""ASUS GC31/GC33 firmware query recovered from GetXgmFw.

The 64-byte HID feature report uses report ID 0x5a and command 0xa0.
Only the ff31/0076 collection on VID 0b05, PID 1970/1a9a is eligible.
No USB interface is detached and no firmware update command is provided.
"""
from pathlib import Path
import errno
import fcntl
import os
import re
import struct
import time

HIDRAW = Path('/sys/class/hidraw')
PIDS = (0x1970, 0x1a9a)
FEATURE_SIZE = 64
DESCRIPTOR_MAX = 4096


def collection_matches(descriptor, page=0xff31, usage=0x76):
    """Parse HID short items, including global push/pop and long-item skipping."""
    pos = 0
    current_page = 0
    stack = []
    usages = []
    matched=False
    depth=0
    while pos < len(descriptor):
        prefix = descriptor[pos]
        pos += 1
        if prefix == 0xfe:
            if pos + 2 > len(descriptor):
                raise ValueError('Truncated HID long item.')
            size = descriptor[pos]
            pos += 2 + size
            if pos > len(descriptor):
                raise ValueError('Truncated HID long item payload.')
            continue
        size = (0, 1, 2, 4)[prefix & 3]
        if pos + size > len(descriptor):
            raise ValueError('Truncated HID short item.')
        value = int.from_bytes(descriptor[pos:pos + size], 'little')
        pos += size
        typ, tag = (prefix >> 2) & 3, prefix >> 4
        if typ == 1:
            if tag == 0:
                current_page = value
            elif tag == 10:
                stack.append(current_page)
            elif tag == 11:
                if not stack:
                    raise ValueError('Unbalanced HID global pop.')
                current_page = stack.pop()
        elif typ == 2 and tag == 0:
            usages.append(((value >> 16) if size == 4 else current_page, value & 0xffff))
        elif typ == 0:
            if tag == 10:
                depth+=1
                if value == 1 and (page, usage) in usages:matched=True
            elif tag == 12:
                if not depth:raise ValueError('Unbalanced HID end collection.')
                depth-=1
            usages = []
    if depth or stack:raise ValueError('Unterminated HID collection/global stack.')
    return matched


def candidates(root=None):
    rows = []
    for entry in (root or HIDRAW).glob('hidraw*'):
        device = entry / 'device'
        values = dict(line.split('=', 1) for line in (device / 'uevent').read_text().splitlines() if '=' in line)
        match = re.fullmatch(r'([0-9a-fA-F]+):([0-9a-fA-F]+):([0-9a-fA-F]+)', values.get('HID_ID', ''))
        if not match:
            continue
        bus, vid, pid = (int(v, 16) for v in match.groups())
        if bus != 3 or vid != 0x0b05 or pid not in PIDS:
            continue
        if collection_matches((device / 'report_descriptor').read_bytes()):
            rows.append({'path': '/dev/' + entry.name, 'product_id': pid})
    # Preserve the original GC31-before-GC33 search order.
    return sorted(rows, key=lambda row: (PIDS.index(row['product_id']), row['path']))


def feature_ioctl(write, size):
    # HIDIOCSFEATURE / HIDIOCGFEATURE, _IOC_READ|_IOC_WRITE, type H.
    return (3 << 30) | (size << 16) | (ord('H') << 8) | (6 if write else 7)


def verify_collection(fd):
    size=bytearray(4)
    fcntl.ioctl(fd,0x80044801,size,True)  # HIDIOCGRDESCSIZE, same open descriptor.
    length=struct.unpack('=I',size)[0]
    if not 1<=length<=DESCRIPTOR_MAX:raise OSError(errno.EPROTO,'Invalid XG HID descriptor length.')
    descriptor=bytearray(4+DESCRIPTOR_MAX);descriptor[:4]=struct.pack('=I',length)
    fcntl.ioctl(fd,0x90044802,descriptor,True)  # HIDIOCGRDESC
    actual=struct.unpack('=I',descriptor[:4])[0]
    if actual!=length:raise OSError(errno.EAGAIN,'XG HID descriptor length changed.')
    try:matched=collection_matches(descriptor[4:4+length])
    except ValueError:raise OSError(errno.EPROTO,'Invalid XG HID collection descriptor.') from None
    if not matched:raise OSError(errno.ENODEV,'Open HID device has no XG firmware collection.')


def query(path):
    fd = os.open(path, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        info=bytearray(8)
        fcntl.ioctl(fd,0x80084803,info,True)  # HIDIOCGRAWINFO
        bus,vid,pid=struct.unpack('=IHH',info)
        if bus!=3 or vid!=0x0b05 or pid not in PIDS:
            raise OSError(errno.ENODEV,'HID device identity changed before the query.')
        verify_collection(fd)
        request = bytearray(FEATURE_SIZE)
        request[:2] = b'\x5a\xa0'
        if fcntl.ioctl(fd, feature_ioctl(True, len(request)), request, True) != FEATURE_SIZE:
            raise OSError(errno.EIO, 'Incomplete XG Mobile firmware request.')
        time.sleep(.1)  # Same device turnaround as the recovered implementation.
        reply = bytearray(FEATURE_SIZE)
        reply[0] = 0x5a
        size = fcntl.ioctl(fd, feature_ioctl(False, len(reply)), reply, True)
        if size != FEATURE_SIZE or reply[0] != 0x5a or reply[1] != 0xa0:
            raise OSError(errno.EPROTO, 'Invalid XG Mobile firmware response.')
        # Original copies32 bytes from offset1 (command +31 firmware bytes),
        # then returns the31 firmware bytes followed by its zero initializer.
        raw = bytes(reply[2:33])
        if not raw.strip(b'\x00\xff'):
            raise OSError(errno.ENODATA, 'XG Mobile returned no firmware identifier.')
        return {'firmware': raw.rstrip(b'\0').decode('ascii', errors='replace'),
                'firmware_raw_hex': raw.hex(), 'firmware_payload_bytes':31,
                'source': 'ASUS HID feature 5a/a0'}
    finally:
        os.close(fd)


def firmware():
    rows = candidates()
    if not rows:
        raise OSError(errno.ENODEV, 'No ASUS GC31/GC33 ff31/0076 HID collection is connected.')
    # Multiple matching devices are ambiguous; do not address an arbitrary one.
    preferred = [r for r in rows if r['product_id'] == rows[0]['product_id']]
    if len(preferred) != 1:
        raise OSError(errno.EBUSY, 'Multiple matching XG Mobile devices are connected.')
    return query(preferred[0]['path'])
