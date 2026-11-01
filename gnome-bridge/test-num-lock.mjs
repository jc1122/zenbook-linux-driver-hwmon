// SPDX-License-Identifier: GPL-2.0-only
import assert from 'node:assert/strict';
import {getNumLock} from './num-lock.mjs';
const stageFor = backend => ({get_context: () => ({get_backend: () => backend})});

for (const value of [false, true]) {
    let reads = 0;
    const backend = {get_default_seat: () => ({get_keymap: () => ({
        get_num_lock_state: () => { reads++; return value; },
    })})};
    assert.equal(getNumLock(stageFor(backend)), value);
    assert.equal(reads, 1);
}
for (const stage of [null, {}, {get_context: () => null},
    {get_context: () => ({get_backend: () => null})}])
    assert.throws(() => getNumLock(stage));
for (const backend of [null, {}, {get_default_seat: () => null},
    {get_default_seat: () => ({get_keymap: () => null})}])
    assert.throws(() => getNumLock(stageFor(backend)));
for (const value of [0, 1, null, undefined, 'false'])
    assert.throws(() => getNumLock(stageFor({get_default_seat: () => ({get_keymap: () => ({
        get_num_lock_state: () => value,
    })})})));
assert.throws(() => getNumLock(stageFor({get_default_seat: () => {throw new Error('failed');}})));
console.log('Desktop Num Lock stage/context/Clutter backend adapter: one logical-state read, false/true and missing/invalid/error states passed.');
