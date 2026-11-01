/* SPDX-License-Identifier: GPL-2.0-only */
#include <stdio.h>
#include <string.h>
#include "healthytable_gauge_block.h"
struct fake {
    ht_byte mem[0x60],original[0x60],data[9][32];
    unsigned int calls,fail_at,selector,block_reads,lengths[9],restore_start,stall_at,stalled;
    bool bad,restoring,bad_restore,change,prefix_mismatch,bad_identity;
    ht_time clock,cost;
};
/* stall_at: the EC stops answering from that primitive on (-ETIME). */
static int step(struct fake *f){
    f->calls++;f->clock+=f->cost;
    if(f->stall_at && f->calls>=f->stall_at){f->stalled++;return -ETIME;}
    return f->calls==f->fail_at ? -EIO:0;
}
static ht_time clock_now(void *ctx){return ((struct fake *)ctx)->clock;}
static int read_byte(void *ctx,unsigned int address,ht_byte *v){
    struct fake *f=ctx;int ret=step(f);if(ret)return ret;
    if(!((address>=0x9000 && address<=0x900f) || (address>=0x9040 && address<=0x905f))){f->bad=true;return -EPERM;}
    *v=f->mem[address-0x9000];return 0;
}
static int restore_byte(void *ctx,unsigned int index,ht_byte value){
    struct fake *f=ctx;int ret;
    if(index==4 && !value && !f->restoring){f->restoring=true;f->restore_start=f->calls+1;}
    ret=step(f);if(ret)return ret;
    if(index>=HT_GAUGE_BLOCK_FIELDS){f->bad=true;return -EPERM;}
    if(f->bad_restore && f->restoring && index==16)value^=1;
    f->mem[ht_gauge_block_fields[index]-0x9000]=value;return 0;
}
static int set_byte(void *ctx,ht_byte index,ht_byte value){
    struct fake *f=ctx;int ret=step(f);if(ret)return ret;
    if(!ht_gauge_block_request(index,value)){f->bad=true;return -EPERM;}
    f->mem[index]=value;
    if(index==9 && (value==0x20 || value==0x21))f->selector=value==0x20 ? 7:8;
    if(index==0)f->mem[14]=1;
    if(index==5)f->mem[13]=1;
    if(index==4){
        for(unsigned int i=0;i<f->lengths[f->selector];i++)f->mem[0x40+i]=f->data[f->selector][i];
        f->block_reads++;
        if(f->change && f->block_reads==2)f->mem[0x40]^=1;
        f->mem[4]=0;f->mem[7]=1;f->mem[8]=0;f->mem[15]=0;
    }
    return 0;
}
static int get_byte(void *ctx,ht_byte index,ht_byte *value){
    struct fake *f=ctx;int ret=step(f);if(ret)return ret;
    if(index<0x40 || index>0x5f){f->bad=true;return -EPERM;}
    *value=f->mem[index];return 0;
}
static int query(void *ctx,unsigned int selector,ht_byte *out){
    struct fake *f=ctx;int ret=step(f);if(ret)return ret;
    if(selector==1){out[0]=f->bad_identity ? 0:0x56;out[1]=0x45;return 0;}
    if(selector==2){static const ht_byte fw[]={0x45,0x56,2,0x34,0,0x40,2,0,0,0,0,0,0};memcpy(out,fw,13);return 0;}
    if(selector==0x71 || selector==0x72){f->selector=selector==0x71 ? 5:6;memcpy(out,f->data[f->selector],selector==0x71 ? 20:14);return 0;}
    if(selector<0x60 || selector>0x64){f->bad=true;return -EPERM;}
    f->selector=selector-0x60;
    memcpy(out,f->data[f->selector],f->selector==1 || f->selector==2 ? 4:31);
    if(f->prefix_mismatch)out[0]^=1;
    return 0;
}
static struct ht_gauge_full_io io_for(struct fake *f){
    struct ht_gauge_full_io io={.ipc={.read=read_byte,.restore=restore_byte,.set=set_byte,.get=get_byte,.ctx=f},.query=query};return io;
}
static void setup(struct fake *f){
    memset(f,0,sizeof(*f));
    for(unsigned int i=0;i<9;i++){
        f->lengths[i]=i<5 ? ht_gauge_block_lengths[i]:i==5 ? 32:i==6 ? 24:i==7 ? 10:7;
        for(unsigned int j=0;j<32;j++)f->data[i][j]=(ht_byte)(3*i+j+1);
    }
    for(unsigned int i=0x40;i<0x60;i++)f->mem[i]=(ht_byte)(i+9);
    memcpy(f->original,f->mem,sizeof(f->mem));
}
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x);return 1;}}while(0)
/* Stalled EC from every primitive boundary on: at most HT_EC_STALL_TIMEOUTS+1
 * primitives are issued into the stall; fail closed; never publish a sample.
 * A healthy EC taking the measured session time (and 2.5x it) succeeds; a
 * 150 ms/primitive EC exhausts the restore budget and fails closed in time. */
#define STALL_SWEEP(collect,type,total,budget,measured) do{ \
    type out_,prior_; \
    CHECK((total)>0); \
    for(unsigned int n_=1;n_<=(total);n_++){ \
        setup(&f);f.stall_at=n_;io=io_for(&f);memset(&out_,0xa5,sizeof(out_));memcpy(&prior_,&out_,sizeof(out_)); \
        ret=collect(&io,&out_); \
        CHECK(f.stalled>=1 && f.stalled<=HT_EC_STALL_TIMEOUTS+1 && f.calls==n_-1+f.stalled); \
        CHECK(!memcmp(&out_,&prior_,sizeof(out_)) && !f.bad); \
        CHECK(ret==-EUCLEAN || (ret==-ETIME && !memcmp(f.mem,f.original,sizeof(f.mem)))); \
    } \
    setup(&f);f.cost=1000;io=io_for(&f);io.ipc.now_us=clock_now;CHECK(collect(&io,&out_)==0 && !io.ipc.stalled); \
    setup(&f);f.cost=(measured)/(total);io=io_for(&f);io.ipc.now_us=clock_now;CHECK(collect(&io,&out_)==0 && f.clock*10>=(measured)*9); \
    setup(&f);f.cost=(measured)*5/2/(total);io=io_for(&f);io.ipc.now_us=clock_now;CHECK(collect(&io,&out_)==0 && !io.ipc.stalled); \
    setup(&f);f.cost=150000;io=io_for(&f);io.ipc.now_us=clock_now;memcpy(&prior_,&out_,sizeof(out_)); \
    CHECK(collect(&io,&out_)==-EUCLEAN && io.ipc.restore_expired && !io.ipc.stalled && !memcmp(&out_,&prior_,sizeof(out_))); \
    CHECK(f.clock<=(budget)+ht_ec_restore_budget(HT_GAUGE_BLOCK_FIELDS)+2*f.cost); \
    printf("%s stalled EC: %u boundaries, <=%u primitives into the stall; deadlines bounded.\n",#collect,(total),HT_EC_STALL_TIMEOUTS+1); \
}while(0)
int main(void){
    struct fake f;struct ht_gauge_full_io io;struct ht_gauge_full_lifetime sample,before;unsigned int count,restore_start;int ret;
    setup(&f);io=io_for(&f);CHECK(ht_gauge_full_collect(&io,&sample)==0 && !f.bad);count=f.calls;
    restore_start=f.restore_start;
    CHECK(!memcmp(f.mem,f.original,sizeof(f.mem)));
    CHECK(sample.blocks[0][31]==32 && sample.blocks[1][7]==11 && sample.blocks[2][25]==32);
    for(unsigned int n=1;n<=count;n++){
        setup(&f);f.fail_at=n;io=io_for(&f);memset(&sample,0xa5,sizeof(sample));memcpy(&before,&sample,sizeof(sample));
        ret=ht_gauge_full_collect(&io,&sample);
        CHECK(ret<0 && !memcmp(&sample,&before,sizeof(sample)) && !f.bad);
        if(n<restore_start)CHECK(ret==-EIO && !memcmp(f.mem,f.original,sizeof(f.mem)));
        else CHECK(ret==-EUCLEAN);
    }
    STALL_SWEEP(ht_gauge_full_collect,struct ht_gauge_full_lifetime,count,HT_GAUGE_LIFETIME_BUDGET_US,8300000ULL);
    setup(&f);f.bad_restore=true;io=io_for(&f);CHECK(ht_gauge_full_collect(&io,&sample)==-EUCLEAN);
    for(unsigned int i=0;i<5;i++){
        setup(&f);f.lengths[i]--;io=io_for(&f);CHECK(ht_gauge_full_collect(&io,&sample)<0 && !memcmp(f.mem,f.original,sizeof(f.mem)));
    }
    setup(&f);f.lengths[1]++;io=io_for(&f);CHECK(ht_gauge_full_collect(&io,&sample)==-EPROTO);
    setup(&f);f.change=true;io=io_for(&f);CHECK(ht_gauge_full_collect(&io,&sample)==-EAGAIN);
    setup(&f);f.prefix_mismatch=true;io=io_for(&f);CHECK(ht_gauge_full_collect(&io,&sample)==-EAGAIN);
    setup(&f);f.bad_identity=true;io=io_for(&f);CHECK(ht_gauge_full_collect(&io,&sample)==-ENODEV && !f.restoring);
    for(unsigned int i=0;i<16;i++){
        setup(&f);f.mem[i]=1;io=io_for(&f);CHECK(ht_gauge_full_collect(&io,&sample)==-EBUSY && !f.restoring);
    }
    CHECK(!ht_gauge_block_request(8,0x12) && !ht_gauge_block_request(9,0x44));
    CHECK(!ht_gauge_block_request(4,4) && !ht_gauge_block_request(6,10));
    CHECK(!ht_gauge_block_request(0x10,0x28));
    printf("Complete battery blocks: %u injected communication failures; exact lengths, sentinels, prefix/identity gates and restoration passed.\n",count);
    {
        struct ht_gauge_full_sample live,prior;
        setup(&f);io=io_for(&f);CHECK(ht_gauge_measurements_collect(&io,&live)==0 && !f.bad);
        CHECK(!memcmp(f.mem,f.original,sizeof(f.mem)));count=f.calls;restore_start=f.restore_start;
        CHECK(!memcmp(live.da1,f.data[5],32) && !memcmp(live.da2,f.data[6],24));
        for(unsigned int n=1;n<=count;n++){
            setup(&f);f.fail_at=n;io=io_for(&f);memset(&live,0xa5,sizeof(live));memcpy(&prior,&live,sizeof(live));
            ret=ht_gauge_measurements_collect(&io,&live);
            CHECK(ret<0 && !memcmp(&live,&prior,sizeof(live)) && !f.bad);
            if(n<restore_start)CHECK(ret==-EIO && !memcmp(f.mem,f.original,sizeof(f.mem)));
            else CHECK(ret==-EUCLEAN);
        }
        STALL_SWEEP(ht_gauge_measurements_collect,struct ht_gauge_full_sample,count,HT_GAUGE_MEASUREMENTS_BUDGET_US,3000000ULL);
        setup(&f);f.change=true;io=io_for(&f);CHECK(ht_gauge_measurements_collect(&io,&live)==0);
        CHECK(live.da2[0]==(ht_byte)(f.data[6][0]^1)); /* No splice/false equality gate. */
        setup(&f);f.data[5][31]=0x5a;io=io_for(&f);CHECK(ht_gauge_measurements_collect(&io,&live)==0 && live.da1[31]==0x5a && f.block_reads==3);
        {
            unsigned int retry_count=f.calls,retry_restore=f.restore_start;
            for(unsigned int n=1;n<=retry_count;n++){
                setup(&f);f.data[5][31]=0x5a;f.fail_at=n;io=io_for(&f);memset(&live,0xa5,sizeof(live));memcpy(&prior,&live,sizeof(live));
                ret=ht_gauge_measurements_collect(&io,&live);
                CHECK(ret<0 && !memcmp(&live,&prior,sizeof(live)) && !f.bad);
                if(n<retry_restore)CHECK(ret==-EIO && !memcmp(f.mem,f.original,sizeof(f.mem)));
                else CHECK(ret==-EUCLEAN);
            }
            printf("Battery measurement sentinel retry: %u injected communication failures passed.\n",retry_count);
        }
        for(unsigned int block=5;block<7;block++){
            setup(&f);f.lengths[block]--;io=io_for(&f);CHECK(ht_gauge_measurements_collect(&io,&live)==-ENODATA);
            CHECK(!memcmp(f.mem,f.original,sizeof(f.mem)));
        }
        setup(&f);f.lengths[6]=25;io=io_for(&f);CHECK(ht_gauge_measurements_collect(&io,&live)==-EPROTO);
        setup(&f);f.bad_restore=true;io=io_for(&f);CHECK(ht_gauge_measurements_collect(&io,&live)==-EUCLEAN);
        setup(&f);f.bad_identity=true;io=io_for(&f);CHECK(ht_gauge_measurements_collect(&io,&live)==-ENODEV);
        printf("Complete battery measurements: %u injected failures; changing frames, sentinel collision, short/long replies and restoration passed.\n",count);
    }
    {
        struct ht_gauge_strings strings,prior;
        setup(&f);io=io_for(&f);CHECK(ht_gauge_strings_collect(&io,&strings)==0 && !f.bad);
        count=f.calls;restore_start=f.restore_start;
        CHECK(strings.lengths[0]==10 && strings.lengths[1]==7);
        CHECK(!memcmp(strings.manufacturer,f.data[7],10) && !memcmp(strings.model,f.data[8],7));
        CHECK(!memcmp(f.mem,f.original,sizeof(f.mem)));
        for(unsigned int n=1;n<=count;n++){
            setup(&f);f.fail_at=n;io=io_for(&f);memset(&strings,0xa5,sizeof(strings));memcpy(&prior,&strings,sizeof(strings));
            ret=ht_gauge_strings_collect(&io,&strings);
            CHECK(ret<0 && !memcmp(&strings,&prior,sizeof(strings)) && !f.bad);
            if(n<restore_start)CHECK(ret==-EIO && !memcmp(f.mem,f.original,sizeof(f.mem)));
            else CHECK(ret==-EUCLEAN);
        }
        STALL_SWEEP(ht_gauge_strings_collect,struct ht_gauge_strings,count,HT_GAUGE_STRINGS_BUDGET_US,3600000ULL);
        setup(&f);f.change=true;io=io_for(&f);CHECK(ht_gauge_strings_collect(&io,&strings)==-EAGAIN);
        setup(&f);f.lengths[7]=0;io=io_for(&f);CHECK(ht_gauge_strings_collect(&io,&strings)==-ENODATA);
        for(unsigned int n=1;n<=32;n++){
            setup(&f);f.lengths[7]=n;memset(f.data[7],0x5a,32);io=io_for(&f);
            CHECK(ht_gauge_strings_collect(&io,&strings)==0 && strings.lengths[0]==n);
            setup(&f);f.lengths[8]=n;memset(f.data[8],0xa5,32);io=io_for(&f);
            CHECK(ht_gauge_strings_collect(&io,&strings)==0 && strings.lengths[1]==n);
        }
        setup(&f);f.bad_restore=true;io=io_for(&f);CHECK(ht_gauge_strings_collect(&io,&strings)==-EUCLEAN);
        setup(&f);f.bad_identity=true;io=io_for(&f);CHECK(ht_gauge_strings_collect(&io,&strings)==-ENODEV && !f.restoring);
        CHECK(ht_gauge_string_block(&io.ipc,0x22,strings.model,&strings.lengths[1])==-EPERM);
        printf("Complete battery identity: %u injected communication failures; variable lengths, sentinel collisions, changing/empty replies and restoration passed.\n",count);
    }
    return 0;
}
