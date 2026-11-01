/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef ZENBOOK_HISTORY_H
#define ZENBOOK_HISTORY_H
#include "healthytable_telemetry.h"
/* Fixed original cache read requests. No persistent battery configuration.
 * Firmware error/busy bits are authoritative; never return padded partial data.
 * The caller holds the transport lock and excludes manual fan ownership. */
struct ht_cache_frame {
    ht_byte data[32], status, timeout;
    unsigned int length, ready_bit;
    bool refresh_requested;
};
static inline int ht_cache_state(struct ht_io *io, ht_byte *status, ht_byte *timeout)
{
    int ret=ht_bank(io,1,0x5b,status);
    return ret ? ret : ht_bank(io,1,3,timeout);
}
static inline int ht_cache_collect(struct ht_io *io, unsigned int kind,
                                  void (*delay_ms)(void *,unsigned int), void *ctx,
                                  struct ht_cache_frame *out)
{
    struct ht_cache_frame frame={0};
    ht_byte a[32], b[32], status, timeout, version, selector=0x50;
    unsigned int i, poll, first;
    int ret;
    if ((kind!=0x10 && kind!=0x80) || !delay_ms) return -EINVAL;
    ret=ht_xfer(io,0xbb,&selector,1,&version);
    if (ret) return ret;
    if (version<10) return -EOPNOTSUPP;
    frame.ready_bit=kind==0x10 ? 0x10 : 0x20;
    frame.length=kind==0x10 ? 32 : 4;
    first=kind==0x10 ? 0x60 : 0x5c;
    ret=ht_cache_state(io,&status,&timeout);
    if (ret) return ret;
    if (status&0x40) return -EIO;
    if (status&0x80) return -EBUSY;
    if (!(timeout&4)) {
        const ht_byte request[]={0x81,0x5a,(ht_byte)kind};
        ret=ht_xfer(io,0xdd,request,3,NULL);
        if (ret) return ret;
        frame.refresh_requested=true;
    }
    for (poll=0;poll<4;poll++) {
        ret=ht_cache_state(io,&status,&timeout);
        if (ret) return ret;
        if (status&0x40) return -EIO;
        if (status&0x80) return -EBUSY;
        if (status&frame.ready_bit) break;
        if (poll<3) delay_ms(ctx,1000);
    }
    if (!(status&frame.ready_bit)) return -ETIMEDOUT;
    frame.status=status;frame.timeout=timeout;
    for (i=0;i<frame.length;i++) {
        ret=ht_bank(io,1,first+i,&a[i]);
        if (ret) return ret;
    }
    ret=ht_cache_state(io,&status,&timeout);
    if (ret) return ret;
    if (status!=frame.status || timeout!=frame.timeout) return -EAGAIN;
    for (i=0;i<frame.length;i++) {
        ret=ht_bank(io,1,first+i,&b[i]);
        if (ret) return ret;
        if (a[i]!=b[i]) return -EAGAIN;
    }
    ret=ht_cache_state(io,&status,&timeout);
    if (ret) return ret;
    if (status!=frame.status || timeout!=frame.timeout) return -EAGAIN;
    for (i=0;i<frame.length;i++) frame.data[i]=a[i];
    *out=frame;
    return 0;
}
struct ht_history {
    ht_byte status, timeout, blocks[4][32];
    long permanent_failure;
};
static inline int ht_history_read(struct ht_io *io, struct ht_history *h)
{
    static const ht_byte bits[]={8,4,2,1};
    unsigned int i,j;
    int ret=ht_bank(io,1,0x5b,&h->status);
    if (!ret) ret=ht_bank(io,1,3,&h->timeout);
    if (ret) return ret;
    h->permanent_failure=-1;
    if (h->status & 0x20) {
        ret=ht_dword(io,1,0x5c,&h->permanent_failure);
        if (ret) return ret;
    }
    for (i=0;i<4;i++) {
        if (!(h->status & bits[i])) continue;
        for (j=0;j<32;j++) {
            ret=ht_bank(io,1,0x80+i*32+j,&h->blocks[i][j]);
            if (ret) return ret;
        }
    }
    return 0;
}
static inline int ht_history_refresh(struct ht_io *io)
{
    const ht_byte p[]={0x81,0x5a,0x80};
    ht_byte status;
    int ret=ht_bank(io,1,0x5b,&status);
    if (ret) return ret;
    if (status & 0x80) return -EBUSY;
    return ht_xfer(io,0xdd,p,3,NULL);
}
/* Exact Windows SafetyStatus/PFStatus recipes. The only manufacturer-access
 * selectors allowed are read-only 0x0051 and 0x0053; no unseal/reset/write API. */
static inline int ht_gauge_status(struct ht_io *io, ht_byte selector, long *value)
{
    ht_byte setup[][2]={{4,selector},{5,0},{1,0},{3,0},{255,4},{2,0x23},{3,0}};
    unsigned int i;
    int ret;
    if (selector!=0x51 && selector!=0x53) return -EPERM;
    for (i=0;i<7;i++) {
        ht_byte status=0;
        ret=ht_xfer(io,0xde,setup[i],2,setup[i][0]==3 ? &status : NULL);
        if (ret) return ret;
        if (setup[i][0]==3 && status==0x40) return -ENODATA;
    }
    *value=0;
    for (i=4;i>0;i--) {
        const ht_byte p[]={(ht_byte)(8+i-1),0};
        ht_byte b;
        ret=ht_xfer(io,0xde,p,2,&b);
        if (ret) return ret;
        *value=(*value<<8)|b;
    }
    return 0;
}
#endif
