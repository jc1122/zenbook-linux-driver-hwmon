# SPDX-License-Identifier: GPL-2.0-only
"""Shared Hypothesis profile, strategies and hardware guard for parser fuzzing.

Nothing here opens real sysfs/procfs/devices: tests write fuzzed payloads into a
private temporary directory and redirect the modules' injectable roots there.
"""
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest import mock
import builtins
import io
import json
import math
import os
import subprocess

from hypothesis import HealthCheck, settings, strategies as st

settings.register_profile(
    'asus-fuzz', derandomize=True, max_examples=200, deadline=None, database=None,
    print_blob=False,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large,
                           HealthCheck.filter_too_much, HealthCheck.large_base_example])
settings.load_profile('asus-fuzz')

FORBIDDEN = ('/sys', '/dev', '/proc', '/run', '/etc/zenbook-hardware')


class HardwareAccess(AssertionError):
    """Raised when code under fuzz tries to reach real hardware/system state."""


def _check(path):
    try:
        text = os.fsdecode(os.fspath(path))
    except TypeError:
        return  # file descriptors
    if not os.path.isabs(text):
        return
    for prefix in FORBIDDEN:
        if text == prefix or text.startswith(prefix + '/'):
            raise HardwareAccess('fuzzed code tried to access ' + text)


def _wrap(original):
    def guarded(path, *args, **kwargs):
        _check(path)
        return original(path, *args, **kwargs)
    return guarded


def _refuse(*args, **kwargs):
    raise HardwareAccess('fuzzed code tried to start a subprocess')


@contextmanager
def hardware_guard():
    """Fail loudly if the code under test opens/lists system paths or spawns."""
    with ExitStack() as stack:
        for owner, name in ((os, 'open'), (os, 'scandir'), (os, 'listdir'), (os, 'stat'),
                            (builtins, 'open'), (io, 'open')):
            stack.enter_context(mock.patch.object(owner, name, _wrap(getattr(owner, name))))
        stack.enter_context(mock.patch.object(subprocess, 'run', _refuse))
        stack.enter_context(mock.patch.object(subprocess, 'Popen', _refuse))
        yield


def assert_finite_json(case, value):
    """Output must be strict JSON (no NaN/Infinity) with finite numbers only."""
    json.dumps(value, allow_nan=False)

    def walk(item):
        if isinstance(item, float):
            case.assertTrue(math.isfinite(item), item)
        elif isinstance(item, dict):
            for key, child in item.items():
                case.assertIsInstance(key, str)
                walk(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                walk(child)
    walk(value)


def write(directory, name, data):
    path = Path(directory) / name
    path.write_bytes(data if isinstance(data, bytes) else data.encode('utf-8', 'surrogatepass'))
    return path


# --- strategies -----------------------------------------------------------

SCALARS = st.one_of(
    st.none(), st.booleans(),
    st.integers(-2**70, 2**70), st.sampled_from([0, 1, -1, 255, 65535, 2**32 - 1, 2**64, 10**400]),
    st.floats(allow_nan=True, allow_infinity=True), st.text(max_size=12))
JSON = st.recursive(SCALARS, lambda children: st.one_of(
    st.lists(children, max_size=5), st.dictionaries(st.text(max_size=8), children, max_size=5)),
    max_leaves=20)


def hex_bytes(size):
    return st.binary(min_size=size, max_size=size).map(bytes.hex)


def mutated(base, keys):
    """Near-valid dicts: delete a key or replace it with an arbitrary JSON value."""
    def apply(args):
        value, key, replacement, delete = args
        value = dict(value)
        if delete:
            value.pop(key, None)
        else:
            value[key] = replacement
        return value
    return st.tuples(base, st.sampled_from(sorted(keys)), JSON, st.booleans()).map(apply)


def word_bytes(words):
    return b''.join(int(w & 0xffff).to_bytes(2, 'little') for w in words)


WORD = st.one_of(st.integers(0, 65535), st.sampled_from([0, 1, 0x7fff, 0x8000, 0xffff]))
