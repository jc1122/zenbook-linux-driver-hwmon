# SPDX-License-Identifier: GPL-2.0-only
"""Bounded read-only provider audit. Never executes OEM or configuration writes."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import time
import compat
import efi_oem
import native_oem
import api_bridge
import wireless_native

DEFAULTS={'HealthyTable_SetFanIndex':{'index':0},'wmiadd':{'value':41},'Adapter_Read_PDO':{'index':0},
 'WOA_EC_read':{'address_space':'healthytable','bank':2,'register':0x30},
 'GetSENSOR_WMI_Data':{}}
SKIP=set(efi_oem.WRITES)|set(native_oem.MUTATIONS)|compat.REVERSIBLE_SETTERS|{'StopWinIoDriver','WMISetAppPath','TraceOutput','TraceOutputCritical','SaveEcLog'}
def run(root_only=False):
    matrix=json.loads((Path(__file__).parent/'capabilities.json').read_text())
    rows=[]
    for name,row in matrix['exports'].items():
        if name in SKIP:continue
        args=DEFAULTS.get(name,{})
        privileged=compat.needs_root(name,args) or row.get('field','').startswith('gauge.')
        # Cached Wi-Fi APIs belong to the user audit. Their live root fallback
        # depends on cache freshness; using that transient state to split the
        # census can otherwise omit them from both user and root passes.
        # The actual API call retains its normal permission check and errors.
        if name in wireless_native.NAMES:privileged=False
        if privileged!=root_only:continue
        start=time.monotonic()
        result={'name':name,'root':privileged}
        try:
            compat.validate(name,args)
            value=api_bridge.call({'name':name,'args':args})
            encoded=json.dumps(value,sort_keys=True,default=str).encode()
            result.update(status='ok' if value is not None else 'no_value',value_type=type(value).__name__,
                          value_sha256=hashlib.sha256(encoded).hexdigest(),serialized_bytes=len(encoded))
        except Exception as e:
            result.update(status='error',error_type=type(e).__name__,errno=getattr(e,'errno',None),error=str(e)[:400])
        result['seconds']=round(time.monotonic()-start,3);rows.append(result)
    return rows
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root-only',action='store_true');p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if args.root_only and os.geteuid()!=0:raise SystemExit('Root-only read audit requires root.')
    out=run(args.root_only)
    fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(out,stream,indent=2);stream.write('\n')
    print(json.dumps({'checked':len(out),'ok':sum(x['status']=='ok' for x in out),
       'errors':[{k:x.get(k) for k in ('name','status','error_type','errno','error')} for x in out if x['status']!='ok']},indent=2))
