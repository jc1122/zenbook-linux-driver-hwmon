/* SPDX-License-Identifier: MIT
 * The .301 firmware duty reply is gated by actual manual mode. */
export function fanRows(data=null) {
    const valid=data?.schema===2 && data.count===1 && data.index===0 &&
        Number.isInteger(data.selection_raw) && data.selection_raw>=0 && data.selection_raw<=255 &&
        (data.mode_raw===0 || data.mode_raw===1) && data.duty_code_maximum===254;
    const duty=valid && data.mode_raw===1 && data.duty_status===0 &&
        Number.isInteger(data.duty_code) && data.duty_code>=0 && data.duty_code<=254 && data.duty_code%2===0;
    return [
        {label:'Fan EC Duty Code',value:duty ? `${data.duty_code} / 254`:valid && data.mode_raw===0 && data.duty_status===-95 && data.duty_code===null ? 'Unavailable (automatic mode)':'Unavailable',type:'fan',format:'string'},
        {label:'Fan EC Control',value:valid ? data.mode_raw===0 ? 'Automatic':'Manual':'Unavailable',type:'fan',format:'string'}
    ];
}
