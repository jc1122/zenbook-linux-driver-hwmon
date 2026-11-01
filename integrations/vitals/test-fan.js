// SPDX-License-Identifier: GPL-2.0-only
import assert from 'node:assert/strict';
import {fanRows} from './fan.js';
const data={schema:2,count:1,index:0,selection_raw:1,mode_raw:1,duty_status:0,duty_code:194,duty_code_maximum:254};
assert.equal(fanRows(data)[0].value,'194 / 254');
assert.equal(fanRows(data)[1].value,'Manual');
assert.equal(fanRows({...data,mode_raw:1,duty_code:0})[1].value,'Manual');
assert.equal(fanRows({...data,duty_code:0})[0].value,'0 / 254');
for(const d of [null,{...data,duty_code:195},{...data,duty_code:255},{...data,count:2},{...data,index:1},{...data,mode_raw:2}])
    assert.equal(fanRows(d)[0].value,'Unavailable');
assert.ok(fanRows(data).every(r=>r.type==='fan' && r.format==='string'));
console.log('Vitals EC fan duty: code resolution, mode, real zero and unavailable states passed.');

const auto={...data,mode_raw:0,duty_status:-95,duty_code:null};
assert.equal(fanRows(auto)[0].value,'Unavailable (automatic mode)');
assert.equal(fanRows(auto)[1].value,'Automatic');
