/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef ZENBOOK_CHARGER_H
#define ZENBOOK_CHARGER_H
#include "healthytable_core.h"

/* Qualified UP3404VA.301: firmware OEM combined reads drain pending EC SMBus
 * work before starting. Never drive the SMBus controller from the host.
 * Volatile request writes are distinct from charger configuration writes.
 * Firmware halves the PD current in mA before programming the adapter DAC:
 * this board's input shunt is 10 milliohms, giving 44.4 mA per ADC count. */
#define HT_CHARGER_WORDS 10
#define HT_CHARGER_FIELDS 10
/* Measured healthy charger_adc 1.5 s, charger_metrics 1.3 s per session. */
#define HT_CHARGER_BUDGET_US 6000000U
#define HT_CHARGER_EXTRA_BUDGET_US 6000000U
static const unsigned int ht_charger_fields[HT_CHARGER_FIELDS]={
    0x9000,0x9001,0x9002,0x9003,0x9004,0x900e,0x900f,0x9010,0x9040,0x9041
};
struct ht_charger_sample {
    unsigned int words[HT_CHARGER_WORDS];
    long voltage_mv,current_ua,power_uw;
};
/* One EC-broker session holds ECMT and the driver lock. Bound it: the
 * operation phase may start primitives only before its per-collector deadline
 * and the restore phase gets its own deadline. HT_EC_STALL_TIMEOUTS consecutive
 * timeouts mark the EC stalled: no further primitive is issued, restoration
 * reports failure (-EUCLEAN) and the caller latches its fault. A skipped
 * primitive is never treated as success, so a modified mailbox is never left
 * silently. Stall detection is the dead-EC bound; the deadlines only bound a
 * slow but answering EC. Operation budgets are >=4x the measured healthy
 * uncached sysfs read (one session each, 0.78 driver, 2026-11-01); restore
 * allows 120 ms per restore/readback primitive (measured mean <=11 ms per
 * primitive, headroom for ACPI query load), never less than 3 s. The restore
 * phase starts with a fresh timeout count so one operation-phase timeout
 * cannot shorten it. An expired operation deadline is restored
 * and reported as -ETIMEDOUT (not latched); an expired restore budget latches. */
#define HT_EC_RESTORE_OP_US 120000U
#define HT_EC_RESTORE_MIN_US 3000000U
#define HT_EC_STALL_TIMEOUTS 2U
struct ht_charger_io {
    int (*read)(void *,unsigned int,ht_byte *);
    int (*restore)(void *,unsigned int,ht_byte);
    int (*set)(void *,ht_byte,ht_byte);
    int (*get)(void *,ht_byte,ht_byte *);
    void *ctx;
    ht_time (*now_us)(void *);  /* optional; NULL disables only the deadlines */
    struct ht_io *port;         /* optional; port waits clamp to the deadline */
    /* Session state, owned by the helpers below. */
    ht_time operation_end,restore_end;
    unsigned int timeouts;
    bool restoring,stalled,restore_expired;
};
static inline ht_time ht_ec_restore_budget(unsigned int count)
{
    ht_time budget=(ht_time)HT_EC_RESTORE_OP_US*(2U*count+1U);
    return budget<HT_EC_RESTORE_MIN_US ? HT_EC_RESTORE_MIN_US:budget;
}
static inline void ht_ec_begin(struct ht_charger_io *io,ht_time budget_us)
{
    io->timeouts=0;io->restoring=false;io->stalled=false;io->restore_expired=false;
    io->operation_end=io->now_us ? io->now_us(io->ctx)+budget_us:0;
    if(io->port)io->port->limit_us=io->operation_end;
}
static inline int ht_ec_end(struct ht_charger_io *io,int ret)
{
    if(io->port)io->port->limit_us=0;
    return ret;
}
static inline bool ht_ec_expired(struct ht_charger_io *io)
{
    if(io->stalled || io->restore_expired)return true;
    if(!io->now_us)return false;
    if(io->now_us(io->ctx)<(io->restoring ? io->restore_end:io->operation_end))return false;
    /* An exhausted restore budget is final for the session. */
    if(io->restoring)io->restore_expired=true;
    return true;
}
static inline int ht_ec_account(struct ht_charger_io *io,int ret)
{
    if(ret==-ETIME || ret==-ETIMEDOUT){
        if(++io->timeouts>=HT_EC_STALL_TIMEOUTS)io->stalled=true;
    }else if(!ret)io->timeouts=0;
    return ret;
}
/* A port wait cut short by the session's own operation deadline (ht_wait
 * clamps to limit_us) is a deadline expiry, not evidence of a stalled EC. */
static inline int ht_ec_port_account(struct ht_charger_io *io,int ret)
{
    if((ret==-ETIME || ret==-ETIMEDOUT) && io->now_us && !io->restoring &&
       io->now_us(io->ctx)>=io->operation_end)return ret;
    return ht_ec_account(io,ret);
}
/* Gated primitives: an expired or stalled session issues nothing. */
static inline int ht_ec_read(struct ht_charger_io *io,unsigned int address,ht_byte *value)
{
    if(ht_ec_expired(io))return -ETIMEDOUT;
    return ht_ec_account(io,(io->read)(io->ctx,address,value));
}
static inline int ht_ec_restore(struct ht_charger_io *io,unsigned int index,ht_byte value)
{
    if(ht_ec_expired(io))return -ETIMEDOUT;
    return ht_ec_account(io,(io->restore)(io->ctx,index,value));
}
static inline int ht_ec_set(struct ht_charger_io *io,ht_byte index,ht_byte value)
{
    if(ht_ec_expired(io))return -ETIMEDOUT;
    return ht_ec_port_account(io,(io->set)(io->ctx,index,value));
}
static inline int ht_ec_get(struct ht_charger_io *io,ht_byte index,ht_byte *value)
{
    if(ht_ec_expired(io))return -ETIMEDOUT;
    return ht_ec_port_account(io,(io->get)(io->ctx,index,value));
}
/* Shared bounded restoration of a fixed volatile mailbox snapshot. Field 4
 * (0x9004) is cleared first and rewritten last; every field is read back.
 * Returns 0 only for a verified complete restore, else the first error. */
static inline int ht_ec_restore_fields(struct ht_charger_io *io,const unsigned int *fields,const ht_byte *saved,unsigned int count)
{
    ht_byte v;
    unsigned int i;
    int restore,r;
    io->restoring=true;
    if(!io->stalled)io->timeouts=0;
    io->restore_end=io->now_us ? io->now_us(io->ctx)+ht_ec_restore_budget(count):0;
    if(io->port)io->port->limit_us=io->restore_end;
    restore=ht_ec_restore(io,4,0);
    for(i=0;i<count;i++){
        if(i==4)continue;
        r=ht_ec_restore(io,i,saved[i]);if(r && !restore)restore=r;
    }
    r=ht_ec_restore(io,4,saved[4]);if(r && !restore)restore=r;
    for(i=0;i<count;i++){
        r=ht_ec_read(io,fields[i],&v);
        if((r || v!=saved[i]) && !restore)restore=r ? r:-EIO;
    }
    io->restoring=false;
    if(io->port)io->port->limit_us=io->operation_end;
    return restore;
}
static inline bool ht_charger_register(ht_byte reg)
{
    return reg==0xfe || reg==0xff || reg==0x4c || reg==0x4e ||
           reg==0x4d || reg==0x83 || reg==0x87 || reg==0x81 || reg==0x82 ||
           reg==0x84 || reg==0x85 || reg==0x86 || reg==0x3a || reg==0x91;
}
static inline bool ht_charger_request(ht_byte index,ht_byte value)
{
    return (index==0 && value==2) || (index==1 && value==0x12) ||
           (index==2 && value==1) || (index==3 && value==2) ||
           (index==4 && value==4) || (index==0x10 && ht_charger_register(value));
}
/* Separate from the HealthyTable packet set; no raw caller-facing API. */
static inline int ht_charger_packet(struct ht_io *io,bool write,ht_byte index,
                                   ht_byte value,ht_byte *answer)
{
    ht_time end=io->now_us(io->ctx)+500000;
    int ret;
    if (write ? !ht_charger_request(index,value) :
        (index!=0x40 && index!=0x41))return -EPERM;
    if ((!write)!=(answer!=NULL))return -EINVAL;
    if (io->status(io->ctx)&1)return -EBUSY;
    ret=ht_wait(io,2,false,end);if(ret)return ret;
    io->command(io->ctx,255);
    ret=ht_wait(io,2,false,end);if(ret)return ret;
    io->command(io->ctx,write ? 0xab : 0xaa);
    ret=ht_wait(io,2,false,end);if(ret)return ret;
    io->write(io->ctx,index);
    if(write){ret=ht_wait(io,2,false,end);if(ret)return ret;io->write(io->ctx,value);}
    ret=ht_wait(io,2,false,end);if(ret || write)return ret;
    ret=ht_wait(io,1,true,end);if(!ret)*answer=io->data(io->ctx);
    return ret;
}
static inline int ht_charger_set(struct ht_charger_io *io,ht_byte index,ht_byte value)
{
    ht_byte got;
    int ret;
    if(!ht_charger_request(index,value))return -EPERM;
    ret=ht_ec_set(io,index,value);if(ret)return ret;
    if(index==4)return 0; /* Synchronous worker replaces request with completion. */
    ret=ht_ec_read(io,0x9000+index,&got);
    return ret ? ret : got==value ? 0 : -EPROTO;
}
static inline int ht_charger_word(struct ht_charger_io *io,ht_byte reg,unsigned int *word)
{
    ht_byte status,low,high;
    int ret;
    if(!ht_charger_register(reg))return -EPERM;
    ret=ht_charger_set(io,1,0x12);if(ret)return ret;
    ret=ht_charger_set(io,0x10,reg);if(ret)return ret;
    ret=ht_charger_set(io,4,4);if(ret)return ret;
    ret=ht_ec_read(io,0x9004,&status);if(ret)return ret;
    if(status!=0x80)return -EIO;
    ret=ht_ec_read(io,0x9001,&status);if(ret)return ret;
    if(status)return -EPROTO;
    ret=ht_ec_get(io,0x40,&low);if(ret)return ret;
    ret=ht_ec_get(io,0x41,&high);if(ret)return ret;
    *word=low+256U*high;
    return 0;
}
static inline int ht_charger_decode(struct ht_charger_sample *sample)
{
    unsigned int *w=sample->words,v0=w[5]>>6,v1=w[7]>>6;
    if(w[0]!=0x49 || w[1]!=0x0e)return -ENODEV;
    if(!(w[2]&1) || !(w[9]&1) || (w[3]&0x800))return -ENODATA;
    if(!(w[4]&0x4000) || !(w[8]&0x4000) ||
       ((w[4]>>5)&7)<1 || ((w[4]>>5)&7)>3 ||
       ((w[8]>>5)&7)<1 || ((w[8]>>5)&7)>3)return -ENODATA;
    if(w[6]>255 || (w[5]&~0x3fc0U) || (w[7]&~0x3fc0U))return -EPROTO;
    if(v0+1<v1 || v1+1<v0)return -EAGAIN;
    sample->voltage_mv=v1*96L;
    if(sample->voltage_mv<4000 || sample->voltage_mv>24000)return -ENODATA;
    sample->current_ua=w[6]*44400L;
    sample->power_uw=(long)(((unsigned long long)sample->voltage_mv*sample->current_ua+500)/1000);
    return 0;
}
/* Caller holds both its transport mutex and the firmware ECMT mutex. */
static inline int ht_charger_collect_session(struct ht_charger_io *io,struct ht_charger_sample *sample)
{
    static const ht_byte regs[HT_CHARGER_WORDS]={0xfe,0xff,0x4c,0x4e,0x4d,0x87,0x83,0x87,0x4d,0x4c};
    struct ht_charger_sample next={0};
    ht_byte saved[HT_CHARGER_FIELDS],v;
    unsigned int i,attempt;
    int ret,restore;
    for(i=0;i<HT_CHARGER_FIELDS;i++){ret=ht_ec_read(io,ht_charger_fields[i],&saved[i]);if(ret)return ret;}
    for(i=0;i<16;i++){ret=ht_ec_read(io,0x9000+i,&v);if(ret)return ret;if(v)return -EBUSY;}
    ret=ht_ec_read(io,0x0380,&v);if(ret)return ret;
    if(!(v&1) || v==255)return -ENODATA;
    /* From here, even partial failures restore the fixed volatile mailbox. */
    ret=ht_charger_set(io,0,2);if(ret)goto out;
    ret=ht_ec_read(io,0x900e,&v);if(ret)goto out;
    if(v!=1){ret=-EPROTO;goto out;}
    ret=ht_charger_set(io,2,1);if(ret)goto out;
    ret=ht_charger_set(io,3,2);if(ret)goto out;
    for(i=0;i<5;i++){
        ret=ht_charger_word(io,regs[i],&next.words[i]);if(ret)goto out;
        if((i==0 && next.words[i]!=0x49) || (i==1 && next.words[i]!=0x0e)){ret=-ENODEV;goto out;}
        if(i==2 && !(next.words[i]&1)){ret=-ENODATA;goto out;}
    }
    /* A load step can move VIN by multiple ADC quanta during a triplet.
     * Retry fresh V/I/V reads at most twice; do not relax the consistency
     * threshold or reuse an older value. */
    for(attempt=0;attempt<3;attempt++){
        unsigned int a,b;
        for(i=5;i<8;i++){
            ret=ht_charger_word(io,regs[i],&next.words[i]);if(ret)goto out;
        }
        a=next.words[5]>>6;b=next.words[7]>>6;
        if(a+1>=b && b+1>=a)break;
    }
    for(i=8;i<HT_CHARGER_WORDS;i++){
        ret=ht_charger_word(io,regs[i],&next.words[i]);if(ret)goto out;
    }
    ret=ht_ec_read(io,0x0380,&v);if(ret)goto out;
    ret=(!(v&1) || v==255) ? -ENODATA : ht_charger_decode(&next);
out:
    restore=ht_ec_restore_fields(io,ht_charger_fields,saved,HT_CHARGER_FIELDS);
    if(restore)return -EUCLEAN;
    if(!ret)*sample=next;
    return ret;
}
static inline int ht_charger_collect(struct ht_charger_io *io,struct ht_charger_sample *sample)
{
    ht_ec_begin(io,HT_CHARGER_BUDGET_US);
    return ht_ec_end(io,ht_charger_collect_session(io,sample));
}
/* Extra read-only metrics. Information3 (0x90) clears interrupt flags on
 * read and is deliberately excluded; Information4 (0x91) is non-latching. */
#define HT_CHARGER_EXTRA_WORDS 14
struct ht_charger_extra {
    unsigned int words[HT_CHARGER_EXTRA_WORDS],valid_mask;
    long die_mc,vbat_mv,system_mv,discharge_ua,charge_ua;
};
static inline int ht_charger_extra_decode(struct ht_charger_extra *s)
{
    unsigned int *w=s->words,state=(w[12]>>8)&15;
    long temperature;
    s->valid_mask=0;
    if(w[0]!=0x49 || w[1]!=0x0e)return -ENODEV;
    if((w[11]&~0x1fffU) || (w[12]&0x8000))return -EPROTO;
    /* Status stays readable when the ADC is disabled; stale ADC codes do not. */
    if(!(w[2]&1) || !(w[13]&1) || ((w[4]^w[12])&0x0f00) ||
       (state!=2 && state!=6 && state!=9 && state!=10 && state!=12))return 0;
    if(w[5]>0 && w[5]<255){
        /* Datasheet Eq.3: code = 251.7 - 0.6154 * Tj(C). */
        temperature=(long)((2517LL-10LL*w[5])*1000000LL/6154);
        if(temperature>=-10000 && temperature<=170000){s->die_mc=temperature;s->valid_mask|=1;}
    }
    if(!(w[6]&~0x3fc0U)){
        s->vbat_mv=(w[6]>>6)*64L;
        if(s->vbat_mv>=2500 && s->vbat_mv<=17000)s->valid_mask|=2;
    }
    if(!(w[9]&~0x3fc0U)){
        s->system_mv=(w[9]>>6)*96L;
        if(s->system_mv>=2500 && s->system_mv<=24500)s->valid_mask|=4;
    }
    /* Firmware current-DAC halving qualifies the battery shunt at 5 mOhm. */
    if(!(w[3]&0x800)){
        if(w[7]<255){s->discharge_ua=w[7]*88800L;s->valid_mask|=8;}
        if(w[8]<255){s->charge_ua=w[8]*44400L;s->valid_mask|=16;}
    }
    return 0;
}
static inline int ht_charger_extra_collect_session(struct ht_charger_io *io,struct ht_charger_extra *sample)
{
    static const ht_byte regs[HT_CHARGER_EXTRA_WORDS]={0xfe,0xff,0x4c,0x4e,0x4d,0x82,0x81,0x84,0x85,0x86,0x3a,0x91,0x4d,0x4c};
    struct ht_charger_extra next={0};
    ht_byte saved[HT_CHARGER_FIELDS],v;
    unsigned int i;
    int ret,restore;
    for(i=0;i<HT_CHARGER_FIELDS;i++){ret=ht_ec_read(io,ht_charger_fields[i],&saved[i]);if(ret)return ret;}
    for(i=0;i<16;i++){ret=ht_ec_read(io,0x9000+i,&v);if(ret)return ret;if(v)return -EBUSY;}
    ret=ht_charger_set(io,0,2);if(ret)goto out;
    ret=ht_ec_read(io,0x900e,&v);if(ret)goto out;
    if(v!=1){ret=-EPROTO;goto out;}
    ret=ht_charger_set(io,2,1);if(ret)goto out;
    ret=ht_charger_set(io,3,2);if(ret)goto out;
    for(i=0;i<HT_CHARGER_EXTRA_WORDS;i++){
        ret=ht_charger_word(io,regs[i],&next.words[i]);if(ret)goto out;
        if((i==0 && next.words[i]!=0x49) || (i==1 && next.words[i]!=0x0e)){ret=-ENODEV;goto out;}
    }
    ret=ht_charger_extra_decode(&next);
out:
    restore=ht_ec_restore_fields(io,ht_charger_fields,saved,HT_CHARGER_FIELDS);
    if(restore)return -EUCLEAN;
    if(!ret)*sample=next;
    return ret;
}
static inline int ht_charger_extra_collect(struct ht_charger_io *io,struct ht_charger_extra *sample)
{
    ht_ec_begin(io,HT_CHARGER_EXTRA_BUDGET_US);
    return ht_ec_end(io,ht_charger_extra_collect_session(io,sample));
}

/* A worker completion other than 0x80 (-EIO) is a transient firmware transaction
 * failure: the mailbox has already been restored and verified (restoration
 * failure is -EUCLEAN). Run exactly one fresh complete transaction; never retry
 * protocol, identity, busy, timeout or restoration errors, and never reuse
 * partial words. Both attempts share one operation deadline (one ECMT hold). */
static inline int ht_charger_collect_retry(struct ht_charger_io *io,struct ht_charger_sample *sample)
{
    int ret;
    ht_ec_begin(io,HT_CHARGER_BUDGET_US);
    ret=ht_charger_collect_session(io,sample);
    if(ret==-EIO)ret=ht_charger_collect_session(io,sample);
    return ht_ec_end(io,ret);
}
static inline int ht_charger_extra_collect_retry(struct ht_charger_io *io,struct ht_charger_extra *sample)
{
    int ret;
    ht_ec_begin(io,HT_CHARGER_EXTRA_BUDGET_US);
    ret=ht_charger_extra_collect_session(io,sample);
    if(ret==-EIO)ret=ht_charger_extra_collect_session(io,sample);
    return ht_ec_end(io,ret);
}

#endif
