/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef ZENBOOK_PD_H
#define ZENBOOK_PD_H
#include "healthytable_core.h"

/* UP3404VA.301 only. Two equal passes reject a changing firmware cache.
 * RDER is firmware's serialized EC read mailbox, never its WTER counterpart.
 * No caller-supplied address, raw SMBus transaction or controller write exists.
 * Layout: version, AC/battery flags, ADPW, then two ten-byte port records:
 * validity flags, whole watts, LE millivolts, LE milliamps, LE active PDO.
 * Voltage/current are negotiated limits, not ADC measurements of live draw. */
#define HT_PD_SIZE 23
static const unsigned int ht_pd_addresses[HT_PD_SIZE-1]={
    0x0380,0x0381,
    0x0bf0,0x0ab1,0x0ab2,0x0ab3,0x0ab4,0x0ab5,0x0b28,0x0b29,0x0b2a,0x0b2b,
    0x0bf1,0x0aba,0x0ab6,0x0ab7,0x0ab8,0x0ab9,0x0b98,0x0b99,0x0b9a,0x0b9b
};
static inline int ht_pd_snapshot(int (*read_byte)(void *, unsigned int, ht_byte *),
                                void *ctx, ht_byte *out, unsigned int *length)
{
    ht_byte first[HT_PD_SIZE-1],second[HT_PD_SIZE-1];
    unsigned int i;
    int ret;
    *length=0;
    for (i=0;i<HT_PD_SIZE-1;i++) {
        ret=read_byte(ctx,ht_pd_addresses[i],&first[i]);if (ret)return ret;
    }
    for (i=0;i<HT_PD_SIZE-1;i++) {
        ret=read_byte(ctx,ht_pd_addresses[i],&second[i]);if (ret)return ret;
    }
    for (i=0;i<HT_PD_SIZE-1;i++) if (first[i]!=second[i])return -EAGAIN;
    out[0]=1;
    for (i=0;i<HT_PD_SIZE-1;i++)out[i+1]=second[i];
    *length=HT_PD_SIZE;
    return 0;
}

/* Firmware's per-port RX_SOURCE_CAPS register 0x30 cache: count plus seven
 * complete LE32 objects. Fixed addresses recovered for this BIOS only.
 * An unplug leaves stale bytes. Gate by AC and port validity, bracket source
 * reads with the contract fields, then require two identical whole passes. */
#define HT_PD_SOURCES_SIZE (HT_PD_SIZE+2*29)
static inline int ht_pd_sources_pass(int (*read_byte)(void *,unsigned int,ht_byte *),
                                    void *ctx,ht_byte *out)
{
    unsigned int i,port;
    ht_byte value,count;
    int ret;
    for(i=0;i<HT_PD_SOURCES_SIZE;i++)out[i]=0;
    out[0]=1;
    for(i=0;i<HT_PD_SIZE-1;i++) {
        ret=read_byte(ctx,ht_pd_addresses[i],&out[i+1]);if(ret)return ret;
    }
    if(out[1]==255 || out[3]==255 || out[13]==255)return -EPROTO;
    for(port=0;port<2;port++) {
        unsigned int address=port ? 0x0ba2:0x0b32;
        unsigned int offset=HT_PD_SIZE+29*port;
        if(!(out[1]&1) || !(out[3+10*port]&0x40))continue;
        ret=read_byte(ctx,address,&count);if(ret)return ret;
        if(count<1 || count>7)return -EPROTO;
        out[offset]=count;
        for(i=0;i<4*count;i++) {
            ret=read_byte(ctx,address+1+i,&out[offset+1+i]);if(ret)return ret;
        }
    }
    for(i=0;i<HT_PD_SIZE-1;i++) {
        ret=read_byte(ctx,ht_pd_addresses[i],&value);if(ret)return ret;
        if(value!=out[i+1])return -EAGAIN;
    }
    return 0;
}

static inline int ht_pd_sources_snapshot(int (*read_byte)(void *,unsigned int,ht_byte *),
                                        void *ctx,ht_byte *out,unsigned int *length)
{
    ht_byte first[HT_PD_SOURCES_SIZE],second[HT_PD_SOURCES_SIZE];
    unsigned int i;
    int ret;
    *length=0;
    ret=ht_pd_sources_pass(read_byte,ctx,first);if(ret)return ret;
    ret=ht_pd_sources_pass(read_byte,ctx,second);if(ret)return ret;
    for(i=0;i<HT_PD_SOURCES_SIZE;i++)if(first[i]!=second[i])return -EAGAIN;
    for(i=0;i<HT_PD_SOURCES_SIZE;i++)out[i]=second[i];
    *length=HT_PD_SOURCES_SIZE;
    return 0;
}
#endif
