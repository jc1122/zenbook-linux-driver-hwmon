#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""One native API call as bounded JSON over stdin/stdout (for C/FFI clients)."""
import errno
import importlib.util
import json
import os
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
# The C ABI runs this bridge as `python3 -I -B`, which leaves the script
# directory off sys.path; import providers only from this runtime directory.
if str(HERE) not in sys.path:sys.path.insert(0,str(HERE))
import compat  # noqa: E402


def call(request):
    if not isinstance(request,dict):raise ValueError('Request must be an object.')
    allowed={'name','args','apply','expected_sha256'}
    if set(request)-allowed:raise ValueError('Unknown request field.')
    name=request.get('name');args=request.get('args',{})
    cap=json.loads((HERE/'capabilities.json').read_text())
    if not isinstance(name,str) or name not in cap['exports']:raise ValueError('Unknown ASUS API name.')
    apply=request.get('apply',False)
    if not isinstance(apply,bool):raise ValueError('apply must be a boolean.')
    digest=request.get('expected_sha256')
    compat.validate(name,args,apply,digest)
    if os.geteuid()!=0 and compat.needs_root(name,args,apply):
        # Root keeps the direct in-process path. A non-root caller is routed to
        # org.zenbook.Hardware1 without interactive authorisation: a polkit
        # denial or an unavailable service is EACCES, as before the service.
        route=compat.privilege_route(name,args,apply)
        if route=='root-cli':raise PermissionError(errno.EACCES,'This API requires a privileged caller; '+compat.ROOT_CLI_HINT+'.')
        if route=='service':
            import auth
            return auth.service_call(name,args,apply,digest,interactive=False)
        # 'client': caller-owned outputs run unprivileged in this process.
    row=cap['exports'][name]
    if row.get('backend'):return compat.dispatch(name,args,apply,digest)
    spec=importlib.util.spec_from_file_location('zenbook_native_frontend',HERE/'zenbook-hardware.py')
    front=importlib.util.module_from_spec(spec);spec.loader.exec_module(front)
    return front.api_field(row)


def main():
    try:
        raw=sys.stdin.buffer.read(65537)
        if len(raw)>65536:raise ValueError('Request exceeds 64 KiB.')
        result=call(json.loads(raw))
        print(json.dumps({'ok':True,'result':result},allow_nan=False))
        return 0
    except Exception as error:
        code=getattr(error,'errno',None) or (errno.EACCES if isinstance(error,PermissionError) else errno.EINVAL if isinstance(error,(ValueError,KeyError)) else errno.EIO)
        detail={'errno':code,'message':str(error)}
        if hasattr(error,'control_result'):detail['control']=error.control_result
        if hasattr(error,'committed'):detail['configuration_committed']=error.committed
        print(json.dumps({'ok':False,'error':detail}))
        return 1


if __name__=='__main__':sys.exit(main())
