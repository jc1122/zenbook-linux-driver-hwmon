/* SPDX-License-Identifier: GPL-2.0-only */
#include <stdio.h>
#include <string.h>
#include "healthytable_gauge.h"
struct fake {
    ht_byte cmd,p[2],used,selector,answer;
    bool pending,blocked,bad,change;
    unsigned int requests,fail_at,queries;
    ht_time clock;
    ht_byte data[0x73][31];
};
static ht_byte status(void *ctx){struct fake *f=ctx;return f->blocked ? 2 : f->pending ? 1:0;}
static ht_byte input(void *ctx){struct fake *f=ctx;f->pending=false;return f->answer;}
static void command(void *ctx,ht_byte v){struct fake *f=ctx;if(v==255){f->used=0;return;}if(v!=0xde)f->bad=true;f->cmd=v;}
static void output(void *ctx,ht_byte v){
    struct fake *f=ctx;
    if(f->used>=2){f->bad=true;return;}f->p[f->used++]=v;if(f->used!=2)return;
    f->requests++;
    if(!ht_allowed(f->cmd,f->p,2)){f->bad=true;return;}
    if(f->fail_at==f->requests){f->blocked=true;return;}
    if(f->p[0]==4){f->selector=v;f->queries++;}
    else if(f->p[0]==3){f->answer=0x80;f->pending=true;}
    else if(f->p[0]>=8 && f->p[0]<=38){
        f->answer=f->data[f->selector][f->p[0]-8];
        if(f->change && f->selector==0x60 && f->queries>=4)f->answer^=1;
        f->pending=true;
    }
}
static ht_time now(void *ctx){return ((struct fake *)ctx)->clock;}
static void pause_io(void *ctx){((struct fake *)ctx)->clock+=1000;}
static struct ht_io io_for(struct fake *f){struct ht_io io={status,input,command,output,now,pause_io,f,0,0};return io;}
static void setup(struct fake *f){
    static const ht_byte fw[]={0x45,0x56,2,0x34,0,0x40,2};
    memset(f,0,sizeof(*f));f->data[1][0]=0x56;f->data[1][1]=0x45;memcpy(f->data[2],fw,sizeof(fw));
    for(unsigned int i=0;i<31;i++){f->data[0x60][i]=i+1;f->data[0x63][i]=i+2;f->data[0x64][i]=i+3;}
}
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x);return 1;}}while(0)
int main(void){
    struct fake f;struct ht_io io;struct ht_gauge_sample sample,before;struct ht_gauge_lifetime life,prior;unsigned int count;
    setup(&f);io=io_for(&f);CHECK(ht_gauge_sample_read(&io,&sample)==0 && !f.bad);count=f.requests;
    for(unsigned int n=1;n<=count;n++){
        setup(&f);f.fail_at=n;io=io_for(&f);memset(&sample,0xa5,sizeof(sample));memcpy(&before,&sample,sizeof(sample));
        CHECK(ht_gauge_sample_read(&io,&sample)==-ETIMEDOUT && !memcmp(&before,&sample,sizeof(sample)) && !f.bad);
    }
    printf("Gauge metrics: %u injected packet failures; no partial sample returned.\n",count);
    setup(&f);io=io_for(&f);CHECK(ht_gauge_lifetime_read(&io,&life)==0 && life.blocks[0][30]==31 && !f.bad);count=f.requests;
    for(unsigned int n=1;n<=count;n++){
        setup(&f);f.fail_at=n;io=io_for(&f);memset(&life,0xa5,sizeof(life));memcpy(&prior,&life,sizeof(life));
        CHECK(ht_gauge_lifetime_read(&io,&life)==-ETIMEDOUT && !memcmp(&prior,&life,sizeof(life)) && !f.bad);
    }
    setup(&f);f.change=true;io=io_for(&f);CHECK(ht_gauge_lifetime_read(&io,&life)==-EAGAIN);
    setup(&f);f.data[1][0]=0;io=io_for(&f);CHECK(ht_gauge_sample_read(&io,&sample)==-ENODEV && f.queries==1);
    setup(&f);f.data[2][6]=3;io=io_for(&f);CHECK(ht_gauge_sample_read(&io,&sample)==-ENODEV && f.queries==2);
    for(unsigned int selector=0;selector<256;selector++){
        ht_byte scratch[31];
        if(selector==1 || selector==2 || selector==0x60 || selector==0x61 || selector==0x62 || selector==0x63 || selector==0x64 || selector==0x71 || selector==0x72)continue;
        setup(&f);io=io_for(&f);CHECK(ht_gauge_query(&io,selector,scratch)==-EPERM && f.requests==0);
    }
    {ht_byte p[]={39,0};CHECK(!ht_allowed(0xde,p,2));}
    printf("Gauge lifetime: %u injected packet failures; coherence, identity, fixed selectors and scratch exclusion passed.\n",count);
    return 0;
}
