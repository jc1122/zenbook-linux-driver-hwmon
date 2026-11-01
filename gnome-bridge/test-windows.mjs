// SPDX-License-Identifier: GPL-2.0-only
import assert from 'node:assert/strict';
import {getWindows, parsePreferences, splitNul, authorizeCaller, requestPolicy, processStartTime} from './windows.mjs';

let titleReads = 0;
const windowFor = (id, pid) => ({
    get_stable_sequence: () => id, get_pid: () => pid,
    get_wm_class: () => 'fallback', minimized: id === 1,
    get_title: () => {titleReads++; return `title${id}`;},
});
const low = windowFor(1, 10), high = windowFor(2, 11);
const tracker = {get_window_app: () => ({get_id: () => 'app.desktop', get_name: () => 'Application'})};
const display = {
    focus_window: high,
    get_tab_list: (kind, workspace) => {assert.equal(kind, 42); assert.equal(workspace, null); return [high, low];},
    sort_windows_by_stacking: members => {assert.deepEqual(members, [high, low]); return [low, high];},
};
let result = JSON.parse(getWindows(display, tracker, false, 42));
assert.deepEqual(result.windows.map(w => [w.id, w.z_order, w.focused, w.minimized]),
    [[2, 0, true, false], [1, 1, false, true]]);
assert.equal(titleReads, 0); assert.equal(result.complete, true);
assert.equal('title' in result.windows[0], false);
result = JSON.parse(getWindows(display, tracker, true, 42));
assert.deepEqual(result.windows.map(w => w.title), ['title2', 'title1']); assert.equal(titleReads, 2);
const failing = {get_window_app: w => {if (w === high) throw new Error('gone'); return null;}};
result = JSON.parse(getWindows(display, failing, false, 42));
assert.equal(result.complete, false); assert.equal(result.enumeration_errors, 1);
assert.equal(result.windows[0].z_order, 0); assert.equal(result.windows[0].application, 'fallback');
const empty = {...display, get_tab_list: () => [], sort_windows_by_stacking: () => []};
assert.deepEqual(JSON.parse(getWindows(empty, tracker, false, 42)).windows, []);
const unstable = {...display}; let reads = 0;
Object.defineProperty(unstable, 'focus_window', {get: () => ++reads === 1 ? high : low});
assert.equal(JSON.parse(getWindows(unstable, tracker, false, 42)).complete, false);
assert.throws(() => getWindows(display, tracker, 1, 42));
assert.throws(() => getWindows({...display, get_tab_list: () => {throw new Error('failed');}}, tracker, false, 42));
console.log('Window membership/stack/focus/minimized, optional titles, partial/error and empty reports passed.');

// Caller policy: titles opt-in, runtime allowlist, process identity.
assert.deepEqual(parsePreferences(null), {exposeWindowTitles: false, trustedScripts: []});
assert.deepEqual(parsePreferences('{}'), {exposeWindowTitles: false, trustedScripts: []});
assert.equal(parsePreferences('{"expose_window_titles": true}').exposeWindowTitles, true);
assert.deepEqual(parsePreferences('{"trusted_scripts": ["/home/u/src/zenbook-hardware.py"]}').trustedScripts,
    ['/home/u/src/zenbook-hardware.py']);
for (const bad of ['[]', 'null', '{"expose_window_titles": 1}', '{"trusted_scripts": ["relative.py"]}',
    '{"trusted_scripts": ["/a/../b.py"]}', '{"trusted_scripts": "/a.py"}', 'x'.repeat(9000)])
    assert.throws(() => parsePreferences(bad), bad.slice(0, 40));
assert.deepEqual(splitNul('a\0b\0'), ['a', 'b']); assert.deepEqual(splitNul(null), []);
const stat = '1234 (gnome) shell) S 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 987654 19';
assert.equal(processStartTime(stat), '987654'); assert.equal(processStartTime('bad'), null);
const script = '/usr/local/lib/asus-healthytable/0.83.0/zenbook-hardware.py';
const good = {uid: 1000, sessionUid: 1000, exe: '/usr/bin/python3.14', cmdline: ['/usr/bin/python3', script, 'windows'],
    environ: ['HOME=/home/u'], startBefore: '5', startAfter: '5'};
assert.equal(authorizeCaller(good).ok, true);
assert.equal(authorizeCaller({...good, cmdline: ['python3', '-I', '-B', '/usr/local/lib/asus-healthytable/0.83.0/api_bridge.py']}).ok, true);
assert.equal(authorizeCaller({...good, cmdline: ['/usr/bin/python3', '-I', script], environ: ['PYTHONPATH=/tmp']}).ok, true);
const refusals = {
    'other user': {...good, uid: 1001}, 'missing uid': {...good, uid: undefined},
    'pid reuse': {...good, startAfter: '6'}, 'no start': {...good, startBefore: null, startAfter: null},
    'other interpreter': {...good, exe: '/tmp/python3'}, 'gjs': {...good, exe: '/usr/bin/gjs-console'},
    'inline code': {...good, cmdline: ['/usr/bin/python3', '-c', 'import x']},
    'module mode': {...good, cmdline: ['/usr/bin/python3', '-m', 'zenbook']},
    'user copy': {...good, cmdline: ['/usr/bin/python3', '/home/u/zenbook-hardware.py']},
    'lookalike path': {...good, cmdline: ['/usr/bin/python3', '/usr/local/lib/asus-healthytable/0.83.0/../x/zenbook-hardware.py']},
    'other script': {...good, cmdline: ['/usr/bin/python3', '/usr/local/lib/asus-healthytable/0.83.0/compat.py']},
    'pythonpath injection': {...good, environ: ['PYTHONPATH=/tmp/evil']},
    'preload': {...good, cmdline: ['/usr/bin/python3', '-I', script], environ: ['LD_PRELOAD=/tmp/x.so']},
    'argv0 spoof': {...good, cmdline: ['/tmp/python3', script]},
};
for (const [label, caller] of Object.entries(refusals)) assert.equal(authorizeCaller(caller).ok, false, label);
assert.equal(authorizeCaller(null).ok, false);
assert.equal(authorizeCaller({...good, cmdline: ['/usr/bin/python3', '/home/u/src/zenbook-hardware.py']},
    ['/home/u/src/zenbook-hardware.py']).ok, true);
const policy = extra => requestPolicy({method: 'GetWindows', includeTitles: false, owned: true, authorized: true,
    exposeTitles: false, ...extra});
assert.equal(policy({}), null);
assert.match(policy({includeTitles: true})[0], /TitlesDisabled$/);
assert.equal(policy({includeTitles: true, exposeTitles: true}), null);
assert.match(policy({authorized: false})[0], /AccessDenied$/);
assert.match(policy({owned: false})[0], /NotOwner$/);
assert.match(policy({includeTitles: 1})[0], /InvalidArgs$/);
assert.match(policy({method: 'GetNumLock', authorized: false})[0], /AccessDenied$/);
assert.equal(policy({method: 'GetNumLock', includeTitles: undefined}), null);
assert.equal(policy({method: 'GetVersion', owned: false, authorized: false}), null);
console.log('Bridge caller allowlist, opt-in titles, ownership and process-identity policy passed.');
