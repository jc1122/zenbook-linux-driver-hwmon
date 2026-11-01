/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef ZENBOOK_OEM_H
#define ZENBOOK_OEM_H
#include "healthytable_core.h"

/* Versioned root-only RPC operations; mutations need an explicit apply flag.
 * OEM adapter writes retain source version gates and qualified bank limits. */
enum ht_oem_op {
    HT_OEM_READ_BYTE=1, HT_OEM_WRITE_BYTE=2, HT_OEM_PD_IC=3,
    HT_OEM_CLEAR_POWER=4, HT_OEM_CLEAR_CHARGER=5, HT_OEM_NOTIFY=6,
    HT_OEM_POWER_MONITOR=7, HT_OEM_READ_CLEAR_POWER=8,
    HT_OEM_READ_CLEAR_CHARGER=9, HT_OEM_WMI_DSTS=10, HT_OEM_EEPROM=11,
    HT_OEM_PD_SNAPSHOT=12, HT_OEM_EEPROM_BUFFER=13,
};
/* Ops 11 and 13 call WMI DEVS, the firmware "set" method. Its selectors are believed
 * to be EEPROM reads, but that is not proved from the ATK/WMNB AML, so they are
 * gated like every other mutation (explicit apply flag) until firmware
 * evidence shows the handler cannot write. The selector allowlist in
 * ht_oem_valid() is deliberately left unchanged: narrowing it to observed
 * selectors also needs that evidence (threat model L1). */
static inline bool ht_oem_mutates(unsigned int op)
{
    return op==HT_OEM_WRITE_BYTE || (op>=HT_OEM_CLEAR_POWER && op<=HT_OEM_READ_CLEAR_CHARGER) ||
           op==HT_OEM_EEPROM || op==HT_OEM_EEPROM_BUFFER;
}
static inline int ht_oem_scalar_status(unsigned int op,int status,unsigned int value)
{
    /* EEPROM date/count sentinels and raw register words need their selector
     * context. A successful all-ones reply must reach the native decoder. */
    if (!status && op==HT_OEM_WMI_DSTS && value==0xffffffff)return -ENODEV;
    return status;
}
static inline int ht_oem_valid(unsigned int op,unsigned int index,unsigned int value,unsigned int flags)
{
    if (flags>1 || op<1 || op>HT_OEM_EEPROM_BUFFER) return -EINVAL;
    if (op==HT_OEM_PD_SNAPSHOT) return !index && !value && !flags ? 0 : -EPERM;
    /* Gated by the apply flag like op 11 (ht_oem_mutates), so flags 0/1 pass here. */
    if (op==HT_OEM_EEPROM_BUFFER) return index==0xe5 && !value ? 0 : -EPERM;
    if ((op==HT_OEM_READ_BYTE || op==HT_OEM_WRITE_BYTE) && index>0x7fff) return -ERANGE;
    if (op==HT_OEM_WMI_DSTS)
        return (index==0x120079 && value==0) ||
               (index==0x1200f2 && value>=1 && value<=3) ||
               (index==0x60068 && value==0) ? 0 : -EPERM;
    if (op==HT_OEM_EEPROM)
        return index==0xe0 || index==0x4e1 || index==0xffe3 || index==0xffe7 ||
               ((index&255)==0xe3 && index<=0x3fe3) ||
               ((index&255)==0xe7 && index<=0x3fe7) ? 0 : -EPERM;
    if (index>65535 || value>255) return -ERANGE;
    if ((op==HT_OEM_NOTIFY || op==HT_OEM_POWER_MONITOR) && value>1) return -ERANGE;
    return 0;
}
static inline int ht_oem_ec(struct ht_io *io,unsigned int op,unsigned int index,
                            unsigned int value,bool apply,long *result,ht_byte *data,unsigned int *length)
{
    ht_byte p[3],b=0,version=0;
    unsigned int i;
    int ret=ht_oem_valid(op,index,value,apply ? 1 : 0);
    *length=0;*result=0;
    if (ret) return ret;
    if (ht_oem_mutates(op) && !apply) return -EAGAIN;
    if (op==HT_OEM_READ_BYTE || op==HT_OEM_WRITE_BYTE) {
        unsigned int bank=index>>8,reg=index&255;
        /* Fan controls must go through the watchdog-protected hwmon API. */
        if (op==HT_OEM_WRITE_BYTE && bank==2 && (reg==0x31 || reg==0x35)) return -EPERM;
        if (op==HT_OEM_WRITE_BYTE && bank==1 && reg==0x5a) return -EPERM;
        p[0]=bank | (op==HT_OEM_WRITE_BYTE ? 0x80 : 0);
        p[1]=reg;p[2]=op==HT_OEM_WRITE_BYTE ? value : bank==5 ? 1 : 0;
        ret=ht_xfer(io,0xdd,p,3,op==HT_OEM_READ_BYTE ? &b : NULL);
        if (!ret)*result=b;
        return ret;
    }
    if (op==HT_OEM_PD_IC || (op>=HT_OEM_CLEAR_POWER && op<=HT_OEM_READ_CLEAR_CHARGER)) {
        unsigned int bank=op==HT_OEM_PD_IC ? 5 : op==HT_OEM_POWER_MONITOR ? 7 : 6;
        const ht_byte selector=0x50;
        /* .301 has no bank6/7 handlers. Reject before even a version read;
         * a zero byte in another bank is not a capability/absence predicate. */
        if(io->max_dd_bank && bank>io->max_dd_bank)return -EOPNOTSUPP;
        ret=ht_xfer(io,0xbb,&selector,1,&version);if(ret)return ret;
        if(version==255 || version<(op==HT_OEM_NOTIFY ? 23 : op==HT_OEM_POWER_MONITOR ? 19 : 14))
            return -EOPNOTSUPP;
    }
    if (op==HT_OEM_PD_IC) {
        for (i=0;i<12;i++) {
            ret=ht_bank(io,5,2+i,&data[i]);
            if (ret)return ret;
        }
        *length=12;return 0;
    }
    if (op<HT_OEM_CLEAR_POWER || op>HT_OEM_READ_CLEAR_CHARGER) return -EOPNOTSUPP;
    /* The Windows API uses bank 7 only for the power-dropped monitor. */
    if (op==HT_OEM_POWER_MONITOR) {
        p[0]=0x87;p[1]=9;p[2]=(value<<7)|5;
        return ht_xfer(io,0xdd,p,3,NULL);
    }
    if (op==HT_OEM_READ_CLEAR_POWER) {
        ret=ht_bank(io,6,1,&b);if (ret)return ret;*result=b;
    }
    if (op==HT_OEM_READ_CLEAR_CHARGER) {
        ret=ht_bank(io,6,0x27,&b);if (ret)return ret;*result=b;
    }
    p[0]=0x86;p[2]=0;
    if (op==HT_OEM_READ_CLEAR_POWER && version>=24) {p[1]=0x35;p[2]=b;}
    else if (op==HT_OEM_CLEAR_POWER || op==HT_OEM_READ_CLEAR_POWER) p[1]=1;
    else if (op==HT_OEM_NOTIFY) {p[1]=0x36;p[2]=value;}
    else p[1]=0x27;
    ret=ht_xfer(io,0xdd,p,3,NULL);
    if (!ret && (op==HT_OEM_CLEAR_CHARGER || op==HT_OEM_READ_CLEAR_CHARGER)) {
        p[1]=0x28;ret=ht_xfer(io,0xdd,p,3,NULL);
    }
    return ret;
}
#endif
