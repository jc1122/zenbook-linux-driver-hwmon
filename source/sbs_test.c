/* SPDX-License-Identifier: GPL-2.0-only */
#include <stdio.h>
#include <string.h>
#include "healthytable_sbs.h"
struct fake {
    ht_byte mem[0x60],original[0x60];
    unsigned int words[256],reads[256],calls,fail_at,restore_start;
    unsigned int observations;
    ht_byte completion_override;
    unsigned int tail_seeds,overlong_offset;
    bool native,bad,restoring,bad_restore,short_reply,wrong_completion,wrong_bus,change,bad_identity,overlong,bad_worker;
    unsigned int stall_at,stalled;
    ht_time clock,cost;
};
/* stall_at: the EC stops answering from that primitive on (-ETIME). */
static int step(struct fake *f){
    ++f->calls;f->clock+=f->cost;
    if(f->stall_at && f->calls>=f->stall_at){f->stalled++;return -ETIME;}
    return f->calls==f->fail_at ? -EIO:0;
}
static ht_time clock_now(void *ctx){return ((struct fake *)ctx)->clock;}
static int read_byte(void *ctx,unsigned int address,ht_byte *v){
    struct fake *f=ctx;int ret=step(f);if(ret)return ret;
    if(!(address>=0x9000 && address<=0x9010) && !(address>=0x9040 && address<=0x905f)){f->bad=true;return -EPERM;}
    *v=f->mem[address-0x9000];return 0;
}
static int restore_byte(void *ctx,unsigned int index,ht_byte value){
    struct fake *f=ctx;int ret;
    if(index==4 && !value && !f->restoring){f->restoring=true;f->restore_start=f->calls+1;}
    ret=step(f);if(ret)return ret;
    if(index>=HT_SBS_FIELDS){f->bad=true;return -EPERM;}
    if(f->native && !f->restoring && index>=19)f->tail_seeds++;
    if(f->bad_restore && f->restoring && index==17)value^=1;
    f->mem[ht_sbs_fields[index]-0x9000]=value;return 0;
}
static int set_byte(void *ctx,ht_byte index,ht_byte value){
    struct fake *f=ctx;int ret=step(f);unsigned int command,word;if(ret)return ret;
    if(!(f->native ? ht_sbs_native_request(index,value):ht_sbs_request(index,value))){f->bad=true;return -EPERM;}
    f->mem[index]=value;
    if(index==0)f->mem[14]=1;
    if(index==5)f->mem[13]=1;
    if(index==4){
        command=f->mem[f->native ? 9:0x10];word=f->words[command];
        if(f->change && command==3 && f->reads[command])word^=0x8000;
        f->reads[command]++;
        f->mem[0x40]=word&255;
        if(!f->short_reply)f->mem[0x41]=word>>8;
        f->mem[4]=f->wrong_completion ? f->completion_override:f->native ? 0:0x80;
        if(f->native){f->mem[7]=f->bad_worker ? 0:1;if(f->overlong)f->mem[0x40+f->overlong_offset]^=1;}
        else f->mem[1]=f->wrong_bus ? 1:0;
    }
    return 0;
}
static int get_byte(void *ctx,ht_byte index,ht_byte *value){
    struct fake *f=ctx;int ret=step(f);if(ret)return ret;
    if(f->native ? index<0x40 || index>0x5f:index!=0x40 && index!=0x41){f->bad=true;return -EPERM;}
    *value=f->mem[index];return 0;
}
static int query(void *ctx,unsigned int selector,ht_byte *out){
    struct fake *f=ctx;int ret=step(f);if(ret)return ret;
    if(selector==1){out[0]=f->bad_identity ? 0:0x56;out[1]=0x45;return 0;}
    if(selector==2){static const ht_byte fw[]={0x45,0x56,2,0x34,0,0x40,2,0,0,0,0,0,0};memcpy(out,fw,13);return 0;}
    f->bad=true;return -EPERM;
}
static struct ht_gauge_full_io io_for(struct fake *f){
    struct ht_gauge_full_io io={.ipc={.read=read_byte,.restore=restore_byte,.set=set_byte,.get=get_byte,.ctx=f},.query=query};return io;
}
static void setup(struct fake *f){
    memset(f,0,sizeof(*f));
    for(unsigned int i=0;i<HT_SBS_WORDS;i++)f->words[ht_sbs_commands[i]]=1000+i;
    f->words[0x1a]=0x31;f->words[3]=0x6001;
    f->mem[0x10]=73;
    for(unsigned int i=0x40;i<0x60;i++)f->mem[i]=i+7;
    memcpy(f->original,f->mem,sizeof(f->mem));
}
struct observation_fake {ht_byte bytes[4];unsigned int calls,fail_at;bool changing,bad;};
static int observation_read(void *ctx,unsigned int address,ht_byte *value){
    static const unsigned int addresses[]={0x9602,0x9603,0x961f,0x9620};
    struct observation_fake *f=ctx;unsigned int index=f->calls%4;
    if(address!=addresses[index]){f->bad=true;return -EPERM;}
    f->calls++;if(f->calls==f->fail_at)return -EIO;
    *value=f->bytes[index];if(f->changing && f->calls==5)*value^=1;return 0;
}
static void observe_failure(void *ctx,struct ht_sbs_trace *trace){
    struct fake *f=ctx;
    f->observations++;if(f->restoring)f->bad=true;
    trace->software=(struct ht_sbs_software_observation){.sampled=true,.result=-EIO};
}
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x);return 1;}}while(0)
int main(void){
    struct fake f,g;struct ht_gauge_full_io io;struct ht_sbs_sample sample,before;
    struct ht_sbs_trace trace;
    unsigned int count,restore_start;int ret;
    {
        struct observation_fake o={.bytes={0x82,0,1,0}};
        struct ht_sbs_software_observation observed;
        CHECK(ht_sbs_observe_software(observation_read,&o,&observed)==0 && o.calls==8 && !o.bad);
        CHECK(observed.sampled && !observed.result && !memcmp(observed.bytes,o.bytes,4));
        for(unsigned int n=1;n<=8;n++){
            o=(struct observation_fake){.bytes={0x82,0,1,1},.fail_at=n};
            CHECK(ht_sbs_observe_software(observation_read,&o,&observed)==-EIO && !o.bad);
            CHECK(observed.sampled && observed.result==-EIO && !memcmp(observed.bytes,(ht_byte[4]){0},4));
        }
        o=(struct observation_fake){.bytes={0,0,1,1},.changing=true};
        CHECK(ht_sbs_observe_software(observation_read,&o,&observed)==-EAGAIN && !o.bad);
        for(unsigned int n=1;n<4;n++){
            o=(struct observation_fake){.bytes={0,0,1,0}};o.bytes[n]=2;
            CHECK(ht_sbs_observe_software(observation_read,&o,&observed)==-ESTALE && !o.bad);
            CHECK(observed.result==-ESTALE && !memcmp(observed.bytes,(ht_byte[4]){0},4));
        }
        printf("SBS software observer:8 fixed reads/fault boundaries, double-pass/context gates, no write callbacks passed.\n");
    }
    setup(&f);io=io_for(&f);CHECK(ht_sbs_collect(&io,&sample)==0 && !f.bad);
    count=f.calls;restore_start=f.restore_start;
    CHECK(!memcmp(f.mem,f.original,sizeof(f.mem)) && sample.words[0]==0x31 && sample.words[1]==0x6001);
    for(unsigned int n=1;n<=count;n++){
        setup(&f);f.fail_at=n;io=io_for(&f);memset(&sample,0xa5,sizeof(sample));memcpy(&before,&sample,sizeof(sample));
        ret=ht_sbs_collect(&io,&sample);
        CHECK(ret<0 && !memcmp(&sample,&before,sizeof(sample)) && !f.bad);
        if(n<restore_start)CHECK(ret==-EIO && !memcmp(f.mem,f.original,sizeof(f.mem)));
        else CHECK(ret==-EUCLEAN);
        setup(&g);g.fail_at=n;io=io_for(&g);memcpy(&sample,&before,sizeof(sample));
        CHECK(ht_sbs_collect_trace(&io,&sample,&trace)==ret && trace.result==ret);
        CHECK(trace.phase>HT_SBS_NONE && trace.phase<=HT_SBS_COMPLETE);
        CHECK(g.calls==f.calls && !memcmp(g.mem,f.mem,sizeof(f.mem)) && !memcmp(&sample,&before,sizeof(sample)));
        if(ret==-EUCLEAN)CHECK(trace.restoration_status<0);
        else CHECK(trace.operation_status==ret && trace.restoration_status==0);
    }
    setup(&f);f.bad_restore=true;io=io_for(&f);CHECK(ht_sbs_collect(&io,&sample)==-EUCLEAN);
    setup(&f);f.short_reply=true;io=io_for(&f);CHECK(ht_sbs_collect(&io,&sample)==-ENODATA && !memcmp(f.mem,f.original,sizeof(f.mem)));
    setup(&f);f.wrong_completion=true;io=io_for(&f);CHECK(ht_sbs_collect(&io,&sample)==-EIO && !memcmp(f.mem,f.original,sizeof(f.mem)));
    setup(&f);f.wrong_completion=true;io=io_for(&f);CHECK(ht_sbs_collect_trace(&io,&sample,&trace)==-EIO);
    CHECK(trace.phase==HT_SBS_COMPLETION && trace.command_valid && trace.command==0x1a && trace.completion_valid && trace.completion==0 && !trace.bus_status_valid && !trace.bracket && trace.operation_status==-EIO && !trace.restoration_status);
    CHECK(!memcmp(f.mem,f.original,sizeof(f.mem)));
    CHECK(!ht_sbs_retryable(&trace));trace.completion=0x40;CHECK(ht_sbs_retryable(&trace));
    trace.restoration_status=-EIO;trace.result=-EUCLEAN;CHECK(!ht_sbs_retryable(&trace));
    trace.restoration_status=0;trace.result=-EIO;trace.command=0x16;CHECK(!ht_sbs_retryable(&trace));
    trace.command=0x1a;trace.command_valid=false;CHECK(!ht_sbs_retryable(&trace));
    trace.command_valid=true;trace.completion_valid=false;CHECK(!ht_sbs_retryable(&trace));
    trace.completion_valid=true;trace.phase=HT_SBS_RX_HIGH;CHECK(!ht_sbs_retryable(&trace));
    trace.phase=HT_SBS_COMPLETION;trace.operation_status=-EPROTO;CHECK(!ht_sbs_retryable(&trace));
    setup(&f);f.wrong_completion=true;f.completion_override=0x40;io=io_for(&f);memset(&sample,0xa5,sizeof(sample));memcpy(&before,&sample,sizeof(sample));
    CHECK(ht_sbs_collect_observed(&io,&sample,&trace,observe_failure)==-EIO && f.observations==1 && !f.bad);
    CHECK(trace.software.sampled && trace.software.result==-EIO && !trace.restoration_status && !memcmp(f.mem,f.original,sizeof(f.mem)) && !memcmp(&sample,&before,sizeof(sample)));
    setup(&f);f.wrong_completion=true;f.completion_override=0x40;f.bad_restore=true;io=io_for(&f);
    CHECK(ht_sbs_collect_observed(&io,&sample,&trace,observe_failure)==-EUCLEAN && f.observations==1 && trace.restoration_status<0 && !f.bad);
    setup(&f);f.wrong_completion=true;io=io_for(&f);
    CHECK(ht_sbs_collect_observed(&io,&sample,&trace,observe_failure)==-EIO && !f.observations);
    setup(&f);f.wrong_bus=true;io=io_for(&f);CHECK(ht_sbs_collect_trace(&io,&sample,&trace)==-EPROTO);
    CHECK(trace.phase==HT_SBS_BUS_STATUS && trace.command==0x1a && trace.completion_valid && trace.completion==0x80 && trace.bus_status_valid && trace.bus_status==1 && trace.operation_status==-EPROTO && !trace.restoration_status);
    setup(&f);io=io_for(&f);CHECK(ht_sbs_collect_trace(&io,&sample,&trace)==0 && f.calls==count);
    CHECK(trace.phase==HT_SBS_COMPLETE && trace.result==0 && trace.command==3 && trace.bracket && trace.completion_valid && trace.completion==0x80 && trace.bus_status_valid && trace.bus_status==0 && !trace.operation_status && !trace.restoration_status);
    setup(&f);f.change=true;io=io_for(&f);CHECK(ht_sbs_collect(&io,&sample)==-EAGAIN && !memcmp(f.mem,f.original,sizeof(f.mem)));
    setup(&f);f.words[0x0b]=0x5a34;io=io_for(&f);CHECK(ht_sbs_collect(&io,&sample)==0 && sample.words[5]==0x5a34 && f.reads[0x0b]==2);
    {unsigned int retry_count=f.calls,retry_restore=f.restore_start;
     for(unsigned int n=1;n<=retry_count;n++){
        setup(&f);f.words[0x0b]=0x5a34;f.fail_at=n;io=io_for(&f);
        memset(&sample,0xa5,sizeof(sample));memcpy(&before,&sample,sizeof(sample));ret=ht_sbs_collect(&io,&sample);
        CHECK(ret<0 && !memcmp(&sample,&before,sizeof(sample)) && !f.bad);
        if(n<retry_restore)CHECK(ret==-EIO && !memcmp(f.mem,f.original,sizeof(f.mem)));
        else CHECK(ret==-EUCLEAN);
        setup(&g);g.words[0x0b]=0x5a34;g.fail_at=n;io=io_for(&g);memcpy(&sample,&before,sizeof(sample));
        CHECK(ht_sbs_collect_trace(&io,&sample,&trace)==ret && trace.result==ret);
        CHECK(g.calls==f.calls && !memcmp(g.mem,f.mem,sizeof(f.mem)) && !memcmp(&sample,&before,sizeof(sample)));
     }
     printf("SBS sentinel retry: %u additional injected failures passed.\n",retry_count);
    }
    setup(&f);f.words[0x0b]=0;io=io_for(&f);CHECK(ht_sbs_collect(&io,&sample)==0 && sample.words[5]==0);
    setup(&f);f.bad_identity=true;io=io_for(&f);CHECK(ht_sbs_collect(&io,&sample)==-ENODEV && !f.restoring);
    for(unsigned int i=0;i<16;i++){
        setup(&f);f.mem[i]=1;io=io_for(&f);CHECK(ht_sbs_collect(&io,&sample)==-EBUSY && !f.restoring);
    }
    for(unsigned int c=0;c<256;c++){
        bool allowed=false;for(unsigned int i=0;i<HT_SBS_WORDS;i++)if(c==ht_sbs_commands[i])allowed=true;
        CHECK(ht_sbs_request(0x10,c)==allowed);
    }
    CHECK(!ht_sbs_request(1,0x12) && !ht_sbs_request(2,2) && !ht_sbs_request(4,3) && !ht_sbs_command(0x16));
    printf("SBS READ words: %u injected failures; exact command/address/direction gates, short replies, mode bracket and restoration passed.\n",count);
    for(unsigned int retry=0;retry<2;retry++){
        setup(&f);f.native=true;if(retry)f.words[0x0b]=0x5a34;io=io_for(&f);
        CHECK(ht_sbs_native_collect(&io,&sample,&trace)==0 && !f.bad && f.tail_seeds==30);
        count=f.calls;restore_start=f.restore_start;
        CHECK(!memcmp(f.mem,f.original,sizeof(f.mem)) && trace.native_word && trace.phase==HT_SBS_COMPLETE);
        CHECK(trace.completion_valid && !trace.completion && trace.worker_result_valid && trace.worker_result==1 && !trace.bus_status_valid);
        if(retry)CHECK(sample.words[5]==0x5a34 && f.reads[0x0b]==2);
        for(unsigned int n=1;n<=count;n++){
            setup(&f);f.native=true;if(retry)f.words[0x0b]=0x5a34;f.fail_at=n;io=io_for(&f);memset(&sample,0xa5,sizeof(sample));memcpy(&before,&sample,sizeof(sample));
            ret=ht_sbs_native_collect(&io,&sample,&trace);
            CHECK(ret<0 && trace.result==ret && trace.native_word && !f.bad && !memcmp(&sample,&before,sizeof(sample)));
            if(n<restore_start)CHECK(ret==-EIO && !memcmp(f.mem,f.original,sizeof(f.mem)));
            else CHECK(ret==-EUCLEAN && trace.restoration_status<0);
            setup(&g);g.native=true;if(retry)g.words[0x0b]=0x5a34;g.fail_at=n;io=io_for(&g);memcpy(&sample,&before,sizeof(sample));
            CHECK(ht_sbs_native_collect(&io,&sample,NULL)==ret && g.calls==f.calls && !g.bad && !memcmp(g.mem,f.mem,sizeof(f.mem)) && !memcmp(&sample,&before,sizeof(sample)));
        }
        printf("Native SBS ReadWord%s: %u injected failures; full30-byte tail after every word, single tail seed, trace parity/restoration passed.\n",retry ? " sentinel retry":"",count);
    }
    for(unsigned int n=2;n<32;n++){
        setup(&f);f.native=true;f.overlong=true;f.overlong_offset=n;io=io_for(&f);
        CHECK(ht_sbs_native_collect(&io,&sample,&trace)==-EPROTO && !f.bad && !memcmp(f.mem,f.original,sizeof(f.mem)) && !ht_sbs_retryable(&trace));
    }
    /* Native SBS, stalled EC from every boundary: bounded primitives, no
     * sample, fail closed, trace keeps the restoration error, never retryable. */
    setup(&f);f.native=true;io=io_for(&f);CHECK(ht_sbs_native_collect(&io,&sample,&trace)==0);count=f.calls;
    for(unsigned int n=1;n<=count;n++){
        setup(&f);f.native=true;f.stall_at=n;io=io_for(&f);memset(&sample,0xa5,sizeof(sample));memcpy(&before,&sample,sizeof(sample));
        ret=ht_sbs_native_collect(&io,&sample,&trace);
        CHECK(f.stalled>=1 && f.stalled<=HT_EC_STALL_TIMEOUTS+1 && f.calls==n-1+f.stalled && !f.bad);
        CHECK(!memcmp(&sample,&before,sizeof(sample)) && trace.result==ret && !ht_sbs_retryable(&trace));
        if(ret==-EUCLEAN)CHECK(trace.restoration_status<0);
        else CHECK(ret==-ETIME && !memcmp(f.mem,f.original,sizeof(f.mem)));
    }
    setup(&f);f.native=true;f.cost=1000;io=io_for(&f);io.ipc.now_us=clock_now;
    CHECK(ht_sbs_native_collect(&io,&sample,&trace)==0 && !io.ipc.stalled);
    /* Healthy-but-slow: measured 5.7 s session, and 2.5x that, succeed. */
    setup(&f);f.native=true;f.cost=5700000/count;io=io_for(&f);io.ipc.now_us=clock_now;
    CHECK(ht_sbs_native_collect(&io,&sample,&trace)==0 && f.clock>=5500000);
    setup(&f);f.native=true;f.cost=5700000*5/2/count;io=io_for(&f);io.ipc.now_us=clock_now;
    CHECK(ht_sbs_native_collect(&io,&sample,&trace)==0 && !io.ipc.stalled);
    setup(&f);f.native=true;f.cost=150000;io=io_for(&f);io.ipc.now_us=clock_now;memcpy(&before,&sample,sizeof(sample));
    CHECK(ht_sbs_native_collect(&io,&sample,&trace)==-EUCLEAN && io.ipc.restore_expired && !io.ipc.stalled && !memcmp(&sample,&before,sizeof(sample)));
    CHECK(f.clock<=HT_SBS_BUDGET_US+ht_ec_restore_budget(HT_SBS_FIELDS)+2*f.cost && !ht_sbs_retryable(&trace));
    printf("Native SBS stalled EC: %u boundaries, <=%u primitives into the stall; deadlines bounded.\n",count,HT_EC_STALL_TIMEOUTS+1);
    setup(&f);f.native=true;f.short_reply=true;io=io_for(&f);CHECK(ht_sbs_native_collect(&io,&sample,&trace)==-ENODATA && !ht_sbs_retryable(&trace));
    setup(&f);f.native=true;f.bad_worker=true;io=io_for(&f);CHECK(ht_sbs_native_collect(&io,&sample,&trace)==-EIO && ht_sbs_retryable(&trace));
    CHECK(trace.phase==HT_SBS_NATIVE_RESULT && !trace.completion && trace.worker_result_valid && !trace.worker_result && !trace.software.sampled);
    setup(&f);f.native=true;f.wrong_completion=true;f.completion_override=0x40;io=io_for(&f);CHECK(ht_sbs_native_collect(&io,&sample,&trace)==-EPROTO && !ht_sbs_retryable(&trace));
    setup(&f);f.native=true;f.bad_restore=true;io=io_for(&f);CHECK(ht_sbs_native_collect(&io,&sample,&trace)==-EUCLEAN && !ht_sbs_retryable(&trace));
    setup(&f);f.native=true;f.change=true;io=io_for(&f);CHECK(ht_sbs_native_collect(&io,&sample,&trace)==-EAGAIN && !ht_sbs_retryable(&trace));
    CHECK(!ht_sbs_native_request(6,5) && !ht_sbs_native_request(6,11) && !ht_sbs_native_request(9,0x16) && !ht_sbs_native_request(4,4));
    return 0;
}
