/* SPDX-License-Identifier: MIT */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "healthytable_oem.h"
static unsigned int checks,failures;
#define CHECK(x) do {checks++;if(!(x)){fprintf(stderr,"line%d: %s\n",__LINE__,#x);exit(1);}} while(0)
struct frame {ht_byte command,p[3];unsigned int count;};
struct fake {
    ht_byte command,p[3],version,answer,flags;unsigned int used,frames,status_calls,fail_at;
    bool pending,arrive,bad;struct frame trace[20];
};
static ht_byte status(void *ctx){struct fake *f=ctx;if(++f->status_calls==f->fail_at)return 255;return f->pending ? 1:0;}
static ht_byte data(void *ctx){struct fake *f=ctx;f->pending=false;return f->answer;}
static void command(void *ctx,ht_byte value){struct fake *f=ctx;if(value==255){f->used=0;f->command=0;}else f->command=value;}
static void write_byte(void *ctx,ht_byte value)
{
    struct fake *f=ctx;unsigned int n=f->command==0xbb ? 1:3;
    if(f->used>=3){f->bad=true;return;}f->p[f->used++]=value;if(f->used<n)return;
    if(f->frames>=20){f->bad=true;return;}
    struct frame *r=&f->trace[f->frames++];r->command=f->command;r->count=n;memcpy(r->p,f->p,n);
    if(f->command==0xbb){f->answer=f->version;f->pending=true;return;}
    if(f->p[0]==6){f->answer=f->p[1]==1 ? f->flags:0x42;f->pending=true;return;}
    if(f->p[0]==5){f->answer=(ht_byte)('A'+f->p[1]-2);f->pending=true;return;}
    f->pending=false;
    if(f->p[0]==0x86 && (f->p[1]==1 || f->p[1]==0x35)){
        if(f->arrive)f->flags|=0x80;
        if(f->p[1]==1)f->flags=0;else f->flags&=(ht_byte)~f->p[2];
    }
}
static ht_time now(void *ctx){(void)ctx;return 0;}
static void pause_io(void *ctx){(void)ctx;}
static struct ht_io io_for(struct fake *f){return (struct ht_io){.status=status,.data=data,.command=command,.write=write_byte,.now_us=now,.pause=pause_io,.ctx=f};}
static int call(struct fake *f,unsigned int op,unsigned int value,bool apply,long *out)
{
    struct ht_io io=io_for(f);ht_byte bytes[256];unsigned int count;
    int result=ht_oem_ec(&io,op,0,value,apply,out,bytes,&count);
    if(op==HT_OEM_PD_IC){
        if(!result)CHECK(count==12 && !memcmp(bytes,"ABCDEFGHIJKL",12));
        else CHECK(count==0);
    }
    return result;
}
static void packet(const struct fake *f,unsigned int i,ht_byte bank,ht_byte reg,ht_byte value)
{
    CHECK(i<f->frames && f->trace[i].command==0xdd && f->trace[i].count==3);
    CHECK(f->trace[i].p[0]==bank && f->trace[i].p[1]==reg && f->trace[i].p[2]==value);
}
int main(void)
{
    long out;
    for(unsigned int v=0;v<=255;v++)for(unsigned int op=HT_OEM_PD_IC;op<=HT_OEM_READ_CLEAR_CHARGER;op++){
        struct fake f={.version=(ht_byte)v,.flags=0x25,.arrive=true};
        unsigned int min=op==HT_OEM_NOTIFY ? 23:op==HT_OEM_POWER_MONITOR ? 19:14;
        int result=call(&f,op,op==HT_OEM_NOTIFY || op==HT_OEM_POWER_MONITOR ? 1:0,true,&out);
        if(v<min || v==255){CHECK(result==-EOPNOTSUPP && f.frames==1);continue;}
        CHECK(result==0 && !f.bad);CHECK(f.trace[0].command==0xbb && f.trace[0].p[0]==0x50);
        if(op==HT_OEM_READ_CLEAR_POWER){
            CHECK(out==0x25 && f.frames==3);packet(&f,1,6,1,0);
            packet(&f,2,0x86,v>=24 ? 0x35:1,v>=24 ? 0x25:0);
            CHECK(f.flags==(v>=24 ? 0x80:0));
        }else if(op==HT_OEM_POWER_MONITOR){CHECK(f.frames==2);packet(&f,1,0x87,9,0x85);}
        else if(op==HT_OEM_NOTIFY){CHECK(f.frames==2);packet(&f,1,0x86,0x36,1);}
        else if(op==HT_OEM_CLEAR_POWER){CHECK(f.frames==2);packet(&f,1,0x86,1,0);}
        else if(op==HT_OEM_CLEAR_CHARGER || op==HT_OEM_READ_CLEAR_CHARGER){
            unsigned int i=op==HT_OEM_READ_CLEAR_CHARGER ? 2:1;
            if(i==2){CHECK(out==0x42);packet(&f,1,6,0x27,0);}
            CHECK(f.frames==i+2);packet(&f,i,0x86,0x27,0);packet(&f,i+1,0x86,0x28,0);
        }else{CHECK(f.frames==13);for(unsigned int i=0;i<12;i++)packet(&f,i+1,5,(ht_byte)(i+2),1);}
    }
    for(unsigned int op=HT_OEM_PD_IC;op<=HT_OEM_READ_CLEAR_CHARGER;op++){
        struct fake good={.version=24,.flags=0xff};CHECK(call(&good,op,0,true,&out)==0);
        for(unsigned int fail=1;fail<=good.status_calls;fail++){
            struct fake f={.version=24,.flags=0xff,.fail_at=fail};
            CHECK(call(&f,op,0,true,&out)==-ENODEV && !f.bad);failures++;
        }
        struct fake f={.version=24};struct ht_io io=io_for(&f);ht_byte bytes[256];unsigned int count;
        io.max_dd_bank=5;
        if(op!=HT_OEM_PD_IC)CHECK(ht_oem_ec(&io,op,0,0,true,&out,bytes,&count)==-EOPNOTSUPP && !f.frames && !f.status_calls);
        f=(struct fake){.version=24};
        if(op!=HT_OEM_PD_IC)CHECK(call(&f,op,0,false,&out)==-EAGAIN && !f.frames && !f.status_calls);
    }
    for(unsigned int mask=0;mask<=255;mask+=255){
        struct fake f={.version=24,.flags=(ht_byte)mask};CHECK(call(&f,HT_OEM_READ_CLEAR_POWER,0,true,&out)==0 && out==mask);packet(&f,2,0x86,0x35,(ht_byte)mask);
    }
    struct fake off={.version=19};CHECK(call(&off,HT_OEM_POWER_MONITOR,0,true,&out)==0);packet(&off,1,0x87,9,5);
    /* The native logical primitive uses the reviewed packet directly. A
     * different register's zero/nonzero byte cannot declare its availability. */
    struct fake raw={0};struct ht_io raw_io=io_for(&raw);ht_byte bytes[256];unsigned int count;
    CHECK(ht_oem_ec(&raw_io,HT_OEM_WRITE_BYTE,0x0636,1,true,&out,bytes,&count)==0 && raw.frames==1);
    packet(&raw,0,0x86,0x36,1);
    raw=(struct fake){0};raw_io.max_dd_bank=5;
    CHECK(ht_oem_ec(&raw_io,HT_OEM_WRITE_BYTE,0x0636,1,true,&out,bytes,&count)==-EOPNOTSUPP && !raw.frames && !raw.status_calls);
    raw=(struct fake){0};raw_io.max_dd_bank=0;
    CHECK(ht_oem_ec(&raw_io,HT_OEM_WRITE_BYTE,0x0636,1,false,&out,bytes,&count)==-EAGAIN && !raw.frames && !raw.status_calls);
    for(unsigned int selector=0x31;selector<=0x35;selector+=4){
        raw=(struct fake){0};CHECK(ht_oem_ec(&raw_io,HT_OEM_WRITE_BYTE,0x0200|selector,255,true,&out,bytes,&count)==-EPERM && !raw.frames && !raw.status_calls);
    }
    raw=(struct fake){0};CHECK(ht_oem_ec(&raw_io,HT_OEM_WRITE_BYTE,0x015a,0x10,true,&out,bytes,&count)==-EPERM && !raw.frames && !raw.status_calls);
    const ht_byte invalid[][3]={{0x87,9,0},{0x87,9,1},{0x87,9,0x84},{0x86,0x34,1},{0x86,0x36,2}};
    for(unsigned int i=0;i<sizeof(invalid)/sizeof(invalid[0]);i++)CHECK(!ht_allowed(0xdd,invalid[i],3));
    printf("OEM recipes: all256 protocol versions, 0/ff masks, concurrent new flag preservation, %u status-failure boundaries, %u checks passed.\n",failures,checks);
    return 0;
}
