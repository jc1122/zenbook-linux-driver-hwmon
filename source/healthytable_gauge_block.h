/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef ZENBOOK_GAUGE_BLOCK_H
#define ZENBOOK_GAUGE_BLOCK_H
#include "healthytable_gauge.h"
#include "healthytable_charger.h"

/* Qualified battery-only SMBus block worker: opcode10/subindex11. This uses
 * the same firmware routine as DE, with a different volatile receive buffer.
 * Fixed SBS READ commands20/21/23, channel B, wire16; no BMS setting or arbitrary
 * request. Commands20/21 here are not ManufacturerAccess selectors20/21.
 * OEM block2/3 lengths differ from the TI reference and stay target specific. */
#define HT_GAUGE_BLOCK_FIELDS 48
/* Measured healthy sessions: battery_lifetime 7.6-8.3 s, battery_gauge_extra
 * 3.0 s, battery_identity 3.6 s. */
#define HT_GAUGE_LIFETIME_BUDGET_US 34000000U
#define HT_GAUGE_MEASUREMENTS_BUDGET_US 12000000U
#define HT_GAUGE_STRINGS_BUDGET_US 15000000U
static const unsigned int ht_gauge_block_fields[HT_GAUGE_BLOCK_FIELDS]={
    0x9000,0x9001,0x9002,0x9003,0x9004,0x9005,0x9006,0x9007,
    0x9008,0x9009,0x900a,0x900b,0x900c,0x900d,0x900e,0x900f,
    0x9040,0x9041,0x9042,0x9043,0x9044,0x9045,0x9046,0x9047,
    0x9048,0x9049,0x904a,0x904b,0x904c,0x904d,0x904e,0x904f,
    0x9050,0x9051,0x9052,0x9053,0x9054,0x9055,0x9056,0x9057,
    0x9058,0x9059,0x905a,0x905b,0x905c,0x905d,0x905e,0x905f
};
static const unsigned int ht_gauge_block_lengths[]={32,8,26,32,32};
struct ht_gauge_full_lifetime {ht_byte identity[2],firmware[13],blocks[5][32];};
struct ht_gauge_full_sample {ht_byte identity[2],firmware[13],da1[32],da2[24];};
struct ht_gauge_strings {ht_byte identity[2],firmware[13],manufacturer[32],model[32],lengths[2];};
struct ht_gauge_full_io {
    struct ht_charger_io ipc;
    int (*query)(void *,unsigned int,ht_byte *);
};
/* Port-broker manufacturer query, gated and accounted like the IPC primitives. */
static inline int ht_ec_query(struct ht_gauge_full_io *full,unsigned int selector,ht_byte *out)
{
    struct ht_charger_io *io=&full->ipc;
    if(ht_ec_expired(io))return -ETIMEDOUT;
    return ht_ec_port_account(io,full->query(io->ctx,selector,out));
}
static inline bool ht_gauge_block_request(ht_byte index,ht_byte value)
{
    return (index==0 && value==2) || (index==5 && value==2) ||
        (index==6 && value==11) || (index==8 && value==0x16) ||
        (index==9 && (value==0x20 || value==0x21 || value==0x23)) || (index==4 && value==0x10);
}
static inline int ht_gauge_block_packet(struct ht_io *io,bool write,ht_byte index,ht_byte value,ht_byte *answer)
{
    ht_time end=io->now_us(io->ctx)+500000;
    int ret;
    if(write ? !ht_gauge_block_request(index,value) : index<0x40 || index>0x5f)return -EPERM;
    if((!write)!=(answer!=NULL))return -EINVAL;
    if(io->status(io->ctx)&1)return -EBUSY;
    ret=ht_wait(io,2,false,end);if(ret)return ret;
    io->command(io->ctx,255);
    ret=ht_wait(io,2,false,end);if(ret)return ret;
    io->command(io->ctx,write ? 0xab:0xaa);
    ret=ht_wait(io,2,false,end);if(ret)return ret;io->write(io->ctx,index);
    if(write){ret=ht_wait(io,2,false,end);if(ret)return ret;io->write(io->ctx,value);}
    ret=ht_wait(io,2,false,end);if(ret || write)return ret;
    ret=ht_wait(io,1,true,end);if(!ret)*answer=io->data(io->ctx);return ret;
}
static inline int ht_gauge_block_set(struct ht_charger_io *io,ht_byte index,ht_byte value)
{
    ht_byte got;
    int ret;
    if(!ht_gauge_block_request(index,value))return -EPERM;
    ret=ht_ec_set(io,index,value);if(ret || index==4)return ret;
    ret=ht_ec_read(io,0x9000+index,&got);return ret ? ret:got==value ? 0:-EPROTO;
}
/* Caller holds ECMT and the transport lock. Different receive sentinels plus
 * equal replies establish the entire expected length without reading a FIFO or
 * trusting bytes left over from a previous manufacturer response. */
static inline int ht_gauge_block_read(struct ht_charger_io *io,unsigned int length,ht_byte *out)
{
    ht_byte first[32],v,pattern;
    unsigned int pass,i;
    int ret;
    if(length!=8 && length!=26 && length!=32)return -EPERM;
    for(pass=0;pass<2;pass++) {
        pattern=pass ? 0xa5:0x5a;
        for(i=0;i<32;i++){ret=ht_ec_restore(io,16+i,pattern);if(ret)return ret;}
        ret=ht_gauge_block_set(io,8,0x16);if(ret)return ret;
        ret=ht_gauge_block_set(io,9,0x23);if(ret)return ret;
        ret=ht_gauge_block_set(io,4,0x10);if(ret)return ret;
        ret=ht_ec_read(io,0x9004,&v);if(ret)return ret;if(v)return -EPROTO;
        ret=ht_ec_read(io,0x9007,&v);if(ret)return ret;if(v!=1)return -EIO;
        for(i=0;i<32;i++) {
            ret=ht_ec_get(io,0x40+i,&v);if(ret)return ret;
            if(i>=length){if(v!=pattern)return -EPROTO;continue;}
            if(pass){if(v!=first[i])return -EAGAIN;}
            else first[i]=v;
        }
    }
    for(i=0;i<length;i++)out[i]=first[i];
    return 0;
}
static inline int ht_gauge_full_collect_session(struct ht_gauge_full_io *full,struct ht_gauge_full_lifetime *sample)
{
    static const ht_byte firmware[]={0x45,0x56,2,0x34,0,0x40,2};
    static const unsigned int selectors[]={0x60,0x61,0x62,0x63,0x64};
    static const unsigned int prefixes[]={31,4,4,31,31};
    struct ht_charger_io *io=&full->ipc;
    struct ht_gauge_full_lifetime next={0};
    ht_byte saved[HT_GAUGE_BLOCK_FIELDS],expected[31],v;
    unsigned int i,j;
    int ret,restore;
    for(i=0;i<HT_GAUGE_BLOCK_FIELDS;i++){ret=ht_ec_read(io,ht_gauge_block_fields[i],&saved[i]);if(ret)return ret;}
    for(i=0;i<16;i++){ret=ht_ec_read(io,0x9000+i,&v);if(ret)return ret;if(v)return -EBUSY;}
    ret=ht_ec_query(full,1,next.identity);if(ret)return ret;
    if(next.identity[0]!=0x56 || next.identity[1]!=0x45)return -ENODEV;
    ret=ht_ec_query(full,2,next.firmware);if(ret)return ret;
    for(i=0;i<sizeof(firmware);i++)if(next.firmware[i]!=firmware[i])return -ENODEV;
    ret=ht_gauge_block_set(io,0,2);if(ret)goto out;
    ret=ht_ec_read(io,0x900e,&v);if(ret)goto out;if(v!=1){ret=-EPROTO;goto out;}
    ret=ht_gauge_block_set(io,5,2);if(ret)goto out;
    ret=ht_ec_read(io,0x900d,&v);if(ret)goto out;if(v!=1){ret=-EPROTO;goto out;}
    ret=ht_gauge_block_set(io,6,11);if(ret)goto out;
    for(i=0;i<5;i++) {
        ret=ht_ec_query(full,selectors[i],expected);if(ret)goto out;
        ret=ht_gauge_block_read(io,ht_gauge_block_lengths[i],next.blocks[i]);if(ret)goto out;
        for(j=0;j<prefixes[i];j++)if(next.blocks[i][j]!=expected[j]){ret=-EAGAIN;goto out;}
    }
out:
    restore=ht_ec_restore_fields(io,ht_gauge_block_fields,saved,HT_GAUGE_BLOCK_FIELDS);
    if(restore)return -EUCLEAN;
    if(!ret)*sample=next;
    return ret;
}
static inline int ht_gauge_full_collect(struct ht_gauge_full_io *full,struct ht_gauge_full_lifetime *sample)
{
    ht_ec_begin(&full->ipc,HT_GAUGE_LIFETIME_BUDGET_US);
    return ht_ec_end(&full->ipc,ht_gauge_full_collect_session(full,sample));
}

/* A live measurement is allowed to change between requests. Firmware fills its
 * dedicated RX buffer sequentially and leaves it stable until the next request.
 * A replaced final byte proves a complete frame; untouched suffix bytes reject
 * an overlong reply. Retry with a different sentinel if the last byte collides.
 * Never combine bytes from different transactions or substitute a prior frame. */
static inline int ht_gauge_measurement_block(struct ht_charger_io *io,unsigned int length,ht_byte *out)
{
    ht_byte frame[32],pattern,v;
    unsigned int attempt,i;
    int ret;
    if(length!=24 && length!=32)return -EPERM;
    for(attempt=0;attempt<2;attempt++) {
        pattern=attempt ? 0xa5:0x5a;
        for(i=0;i<32;i++){ret=ht_ec_restore(io,16+i,pattern);if(ret)return ret;}
        ret=ht_gauge_block_set(io,8,0x16);if(ret)return ret;
        ret=ht_gauge_block_set(io,9,0x23);if(ret)return ret;
        ret=ht_gauge_block_set(io,4,0x10);if(ret)return ret;
        ret=ht_ec_read(io,0x9004,&v);if(ret)return ret;if(v)return -EPROTO;
        ret=ht_ec_read(io,0x9007,&v);if(ret)return ret;if(v!=1)return -EIO;
        for(i=0;i<32;i++) {
            ret=ht_ec_get(io,0x40+i,&frame[i]);if(ret)return ret;
            if(i>=length && frame[i]!=pattern)return -EPROTO;
        }
        if(frame[length-1]==pattern)continue;
        for(i=0;i<length;i++)out[i]=frame[i];
        return 0;
    }
    return -ENODATA;
}
static inline int ht_gauge_measurements_collect_session(struct ht_gauge_full_io *full,struct ht_gauge_full_sample *sample)
{
    static const ht_byte firmware[]={0x45,0x56,2,0x34,0,0x40,2};
    struct ht_charger_io *io=&full->ipc;
    struct ht_gauge_full_sample next={0};
    ht_byte saved[HT_GAUGE_BLOCK_FIELDS],prefix[31],v;
    unsigned int i;
    int ret,restore;
    for(i=0;i<HT_GAUGE_BLOCK_FIELDS;i++){ret=ht_ec_read(io,ht_gauge_block_fields[i],&saved[i]);if(ret)return ret;}
    for(i=0;i<16;i++){ret=ht_ec_read(io,0x9000+i,&v);if(ret)return ret;if(v)return -EBUSY;}
    ret=ht_ec_query(full,1,next.identity);if(ret)return ret;
    if(next.identity[0]!=0x56 || next.identity[1]!=0x45)return -ENODEV;
    ret=ht_ec_query(full,2,next.firmware);if(ret)return ret;
    for(i=0;i<sizeof(firmware);i++)if(next.firmware[i]!=firmware[i])return -ENODEV;
    ret=ht_gauge_block_set(io,0,2);if(ret)goto out;
    ret=ht_ec_read(io,0x900e,&v);if(ret)goto out;if(v!=1){ret=-EPROTO;goto out;}
    ret=ht_gauge_block_set(io,5,2);if(ret)goto out;
    ret=ht_ec_read(io,0x900d,&v);if(ret)goto out;if(v!=1){ret=-EPROTO;goto out;}
    ret=ht_gauge_block_set(io,6,11);if(ret)goto out;
    ret=ht_ec_query(full,0x71,prefix);if(ret)goto out;
    ret=ht_gauge_measurement_block(io,32,next.da1);if(ret)goto out;
    ret=ht_ec_query(full,0x72,prefix);if(ret)goto out;
    ret=ht_gauge_measurement_block(io,24,next.da2);
out:
    restore=ht_ec_restore_fields(io,ht_gauge_block_fields,saved,HT_GAUGE_BLOCK_FIELDS);
    if(restore)return -EUCLEAN;
    if(!ret)*sample=next;
    return ret;
}
static inline int ht_gauge_measurements_collect(struct ht_gauge_full_io *full,struct ht_gauge_full_sample *sample)
{
    ht_ec_begin(&full->ipc,HT_GAUGE_MEASUREMENTS_BUDGET_US);
    return ht_ec_end(&full->ipc,ht_gauge_measurements_collect_session(full,sample));
}

/* SBS identity blocks have a variable length up to32. Two sentinel passes
 * determine the complete written extent and require identical stable data.
 * No manufacturer-access selection is sent for these standard block READs. */
static inline int ht_gauge_string_block(struct ht_charger_io *io,unsigned int command,ht_byte *out,ht_byte *length)
{
    ht_byte frames[2][32],pattern,v;
    unsigned int attempt,i,n=0;
    int ret;
    if(command!=0x20 && command!=0x21)return -EPERM;
    for(attempt=0;attempt<2;attempt++) {
        pattern=attempt ? 0xa5:0x5a;
        for(i=0;i<32;i++){ret=ht_ec_restore(io,16+i,pattern);if(ret)return ret;}
        ret=ht_gauge_block_set(io,8,0x16);if(ret)return ret;
        ret=ht_gauge_block_set(io,9,command);if(ret)return ret;
        ret=ht_gauge_block_set(io,4,0x10);if(ret)return ret;
        ret=ht_ec_read(io,0x9004,&v);if(ret)return ret;if(v)return -EPROTO;
        ret=ht_ec_read(io,0x9007,&v);if(ret)return ret;if(v!=1)return -EIO;
        for(i=0;i<32;i++){ret=ht_ec_get(io,0x40+i,&frames[attempt][i]);if(ret)return ret;}
    }
    for(i=0;i<32;i++)if(frames[0][i]!=0x5a || frames[1][i]!=0xa5)n=i+1;
    if(!n)return -ENODATA;
    for(i=0;i<n;i++)if(frames[0][i]!=frames[1][i])return -EAGAIN;
    for(i=0;i<n;i++)out[i]=frames[0][i];
    *length=n;
    return 0;
}
static inline int ht_gauge_strings_collect_session(struct ht_gauge_full_io *full,struct ht_gauge_strings *sample)
{
    static const ht_byte firmware[]={0x45,0x56,2,0x34,0,0x40,2};
    struct ht_charger_io *io=&full->ipc;
    struct ht_gauge_strings next={0};
    ht_byte saved[HT_GAUGE_BLOCK_FIELDS],v;
    unsigned int i;
    int ret,restore;
    for(i=0;i<HT_GAUGE_BLOCK_FIELDS;i++){ret=ht_ec_read(io,ht_gauge_block_fields[i],&saved[i]);if(ret)return ret;}
    for(i=0;i<16;i++){ret=ht_ec_read(io,0x9000+i,&v);if(ret)return ret;if(v)return -EBUSY;}
    ret=ht_ec_query(full,1,next.identity);if(ret)return ret;
    if(next.identity[0]!=0x56 || next.identity[1]!=0x45)return -ENODEV;
    ret=ht_ec_query(full,2,next.firmware);if(ret)return ret;
    for(i=0;i<sizeof(firmware);i++)if(next.firmware[i]!=firmware[i])return -ENODEV;
    ret=ht_gauge_block_set(io,0,2);if(ret)goto out;
    ret=ht_ec_read(io,0x900e,&v);if(ret)goto out;if(v!=1){ret=-EPROTO;goto out;}
    ret=ht_gauge_block_set(io,5,2);if(ret)goto out;
    ret=ht_ec_read(io,0x900d,&v);if(ret)goto out;if(v!=1){ret=-EPROTO;goto out;}
    ret=ht_gauge_block_set(io,6,11);if(ret)goto out;
    ret=ht_gauge_string_block(io,0x20,next.manufacturer,&next.lengths[0]);if(ret)goto out;
    ret=ht_gauge_string_block(io,0x21,next.model,&next.lengths[1]);
out:
    restore=ht_ec_restore_fields(io,ht_gauge_block_fields,saved,HT_GAUGE_BLOCK_FIELDS);
    if(restore)return -EUCLEAN;
    if(!ret)*sample=next;
    return ret;
}
static inline int ht_gauge_strings_collect(struct ht_gauge_full_io *full,struct ht_gauge_strings *sample)
{
    ht_ec_begin(&full->ipc,HT_GAUGE_STRINGS_BUDGET_US);
    return ht_ec_end(&full->ipc,ht_gauge_strings_collect_session(full,sample));
}
#endif
