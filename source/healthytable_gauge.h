/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef ZENBOOK_GAUGE_H
#define ZENBOOK_GAUGE_H
#include "healthytable_core.h"

/* Existing DE manufacturer-data broker. Only fixed identification, DA status
 * and lifetime read queries; no unseal, reset, calibration or data-flash write.
 * Byte 31 overlaps firmware SMBus scratch at XDATA 0x0354. Never export it as
 * battery payload. Shorter blocks use only their qualified prefix. */
static inline int ht_gauge_query(struct ht_io *io,unsigned int selector,ht_byte *out)
{
    unsigned int i,length;
    ht_byte status;
    int ret;
    switch(selector) {
    case 1:length=2;break;
    case 2:length=13;break;
    case 0x60:case 0x63:case 0x64:length=31;break;
    case 0x61:case 0x62:length=4;break;
    case 0x71:length=20;break;
    case 0x72:length=14;break;
    default:return -EPERM;
    }
    {
        ht_byte setup[][2]={{4,selector},{5,0},{1,0},{3,0},{255,length},{2,0x23},{3,0}};
        for(i=0;i<7;i++) {
            status=0;
            ret=ht_xfer(io,0xde,setup[i],2,setup[i][0]==3 ? &status:NULL);
            if(ret)return ret;
            if(setup[i][0]==3 && status!=0x80)return -EIO;
        }
    }
    for(i=0;i<length;i++) {
        const ht_byte p[]={8+i,0};
        ret=ht_xfer(io,0xde,p,2,&out[i]);if(ret)return ret;
    }
    return 0;
}

static inline int ht_gauge_identity(struct ht_io *io,ht_byte *identity,ht_byte *firmware)
{
    static const ht_byte expected[]={0x45,0x56,0x02,0x34,0x00,0x40,0x02};
    unsigned int i;
    int ret=ht_gauge_query(io,1,identity);if(ret)return ret;
    if(identity[0]!=0x56 || identity[1]!=0x45)return -ENODEV;
    ret=ht_gauge_query(io,2,firmware);if(ret)return ret;
    /* Format-qualified OEM gauge; this is not a claim that it is a TI IC. */
    for(i=0;i<sizeof(expected);i++)if(firmware[i]!=expected[i])return -ENODEV;
    return 0;
}

struct ht_gauge_sample {ht_byte identity[2],firmware[13],da1[20],da2[14];};
struct ht_gauge_lifetime {ht_byte identity[2],firmware[13],blocks[5][31];};
static inline int ht_gauge_sample_read(struct ht_io *io,struct ht_gauge_sample *out)
{
    struct ht_gauge_sample next={0};
    int ret=ht_gauge_identity(io,next.identity,next.firmware);if(ret)return ret;
    ret=ht_gauge_query(io,0x71,next.da1);if(ret)return ret;
    ret=ht_gauge_query(io,0x72,next.da2);if(ret)return ret;
    *out=next;return 0;
}
static inline int ht_gauge_lifetime_read(struct ht_io *io,struct ht_gauge_lifetime *out)
{
    static const ht_byte selectors[]={0x60,0x61,0x62,0x63,0x64};
    static const unsigned int lengths[]={31,4,4,31,31};
    struct ht_gauge_lifetime next={0};
    ht_byte second[31];
    unsigned int i,j;
    int ret=ht_gauge_identity(io,next.identity,next.firmware);if(ret)return ret;
    for(i=0;i<5;i++) {
        ret=ht_gauge_query(io,selectors[i],next.blocks[i]);if(ret)return ret;
        ret=ht_gauge_query(io,selectors[i],second);if(ret)return ret;
        for(j=0;j<lengths[i];j++)if(next.blocks[i][j]!=second[j])return -EAGAIN;
    }
    *out=next;return 0;
}
#endif
