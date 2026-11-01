#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Install the read-only local bridge; preserve edits and session preferences."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

ROOT=Path(__file__).resolve().parents[1]
NAMES=('num-lock.mjs','windows.mjs','extension.js','metadata.json')
PREVIOUS={'extension.js':{'1001ae3ce247b3773f6a7f4367f529c2141e21eb5d8b05be82ffd746d3c717f1','6599e357f60f01adc25719740feb6ef101f095a79ab2b666f50cc8e12b721ba6','724af97328c857d8043ca1c9c894e7c2e733316652c95fa09d20b66e0dd7dede','180e59770799529ce41361685496c0fd4bb306f0719c31fd2564f8dc97bcf40c'},
          'windows.mjs':{'96399e5cd676d140cc3ad83ff3290fa6657b28890c4469c54e48f6674d2f8c3f'},
          'metadata.json':{'e5303ba787cbb749a7ae3b3274b446ee5ec0a3b4d5f98c0b77512ddeee6acb95','2eccea22fe9bcb5ee3647616f5c9265dea398bfc7b44de5319afeac69e9cd54c','9cb009988938bafce2f262f92145d45a444cc8d2102e2d7e5d9d91b932fe59dc'},
          'num-lock.mjs':{'9732ab04d3d5c825b35e7a9159f771d63ef58c68aa1163fd7d9b80824fc52158'}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true');parser.add_argument('--backup',type=Path)
    args=parser.parse_args()
    if os.geteuid()==0:raise PermissionError('Install into the desktop user account, without sudo.')
    target=Path.home()/'.local/share/gnome-shell/extensions/zenbook-hardware-bridge@local'
    if target.is_symlink():raise RuntimeError('Refusing a symlinked bridge directory.')
    proposal={};changed=[]
    for name in NAMES:
        source=ROOT/'gnome-bridge'/name;data=source.read_bytes();digest=hashlib.sha256(data).hexdigest()
        path=target/name
        if path.is_symlink():raise RuntimeError('Refusing a symlinked bridge file: '+name)
        old=hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        if old is not None and old not in PREVIOUS.get(name,set())|{digest}:raise RuntimeError('Preserve locally edited bridge file: '+name)
        proposal[name]={'before_sha256':old,'after_sha256':digest}
        if old!=digest:changed.append(name)
    if args.apply and changed:
        if not args.backup:raise ValueError('--apply requires a new private --backup directory.')
        args.backup.mkdir(mode=0o700)
        for name in NAMES:
            if (target/name).exists():shutil.copy2(target/name,args.backup/name)
        target.mkdir(parents=True,exist_ok=True)
        for name in changed:
            fd,temporary=tempfile.mkstemp(prefix='.bridge-',dir=target)
            try:
                with os.fdopen(fd,'wb') as stream:stream.write((ROOT/'gnome-bridge'/name).read_bytes())
                os.chmod(temporary,0o644);os.replace(temporary,target/name)
            finally:
                if Path(temporary).exists():Path(temporary).unlink()
        for name in NAMES:
            if (target/name).read_bytes()!=(ROOT/'gnome-bridge'/name).read_bytes():raise RuntimeError('Bridge readback differs: '+name)
    print(json.dumps({'applied':bool(args.apply),'changed_files':changed,'files':proposal,'target':str(target),
                      'settings_changed':False,'session_restarted':False,'live_Shell_activation_proven':False,
                      'note':'Existing enabled/disabled preferences are preserved. A normal new login may be required; no reload, unsafe evaluation or logout is performed.'},indent=2))


if __name__=='__main__':main()
