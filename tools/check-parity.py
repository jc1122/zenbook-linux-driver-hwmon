#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Validate the public API inventory and explicit implementation evidence."""
import importlib.util
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import compat

d=json.loads((ROOT/'capabilities.json').read_text())
assert len(d['exports'])==252
for name,row in d['exports'].items():
    assert ('field' in row) != ('backend' in row),name
    assert row.get('parity') in {'native_equivalent','recovered_protocol','not_applicable','hardware_provider_required','firmware_provider_required'},name
    assert row.get('evidence'),name
    assert row.get('verification'),name
assert d['module_version']=='0.85.0'
print('252 API names: routes, parity classification and evidence present.')
