# SPDX-License-Identifier: GPL-2.0-only
"""Read-only Intel thermal counters; per-CPU copies are never summed."""
from pathlib import Path
import re
import time

FIELDS=('core_throttle_count','core_throttle_total_time_ms','core_throttle_max_time_ms',
        'package_throttle_count','package_throttle_total_time_ms','package_throttle_max_time_ms')


def report(root=Path('/sys/devices/system/cpu')):
    rows=[]
    for cpu in sorted((p for p in root.glob('cpu[0-9]*') if re.fullmatch(r'cpu[0-9]+',p.name)),key=lambda p:int(p.name[3:])):
        if not re.fullmatch(r'cpu[0-9]+',cpu.name):continue
        values={}
        for name in FIELDS:
            try:
                raw=(cpu/'thermal_throttle'/name).read_text().strip()
                if not raw.isdecimal() or len(raw)>20:continue
                value=int(raw)
                if value<=2**64-1:values[name]=str(value)
            except OSError:continue
        if not values:continue
        row={'cpu':int(cpu.name[3:]),'counters':values}
        for name in ['physical_package_id','core_id']:
            try:row[name]=int((cpu/'topology'/name).read_text())
            except (OSError,ValueError):row[name]=None
        rows.append(row)
    summary={}
    for name in FIELDS:
        matches=[r for r in rows if name in r['counters']]
        if matches:
            chosen=max(matches,key=lambda r:int(r['counters'][name]))
            summary[name]={'value':chosen['counters'][name],'cpu':chosen['cpu'],'aggregation':'maximum per-CPU counter'}
    return {'schema':1,'available':bool(rows),'source':'Linux thermal_throttle sysfs',
            'captured_monotonic_seconds':time.monotonic(),'scope':'since OS boot; per-CPU observations, not instantaneous throttle state',
            'cpus':rows,'summary':summary,'note':'Package events are broadcast to CPUs; counters are not summed. CPU hotplug and sampling can produce different per-CPU copies.'}
