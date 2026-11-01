/* SPDX-License-Identifier: MIT */
#include <stdio.h>
#include <string.h>
#include "healthytable_diagnostics.h"
struct fake {
    ht_byte command, payload[3], used, answer, mode, selected, duty, count, version;
    bool pending,bad,faulted,change_project,change_count,wrong_selector;
    unsigned int requests,fail_at,bb_project_reads,board_writes,policy_writes,restore_request,status_calls,fail_status;
    ht_time clock;
};
static ht_byte state(void *context)
{
    struct fake *f=context;
    f->status_calls++;
    if(f->fail_status==f->status_calls) {f->faulted=true;return 255;}
    if(f->fail_at && f->requests==f->fail_at && !f->faulted) {f->faulted=true;return 255;}
    return f->pending ? 1:0;
}
static ht_byte data(void *context)
{
    struct fake *f=context;
    if(!f->pending)f->bad=true;
    f->pending=false;return f->answer;
}
static void command(void *context,ht_byte value)
{
    struct fake *f=context;
    if(value==255) {f->used=0;f->command=0;}
    else if(value==0xbb || value==0xdd)f->command=value;
    else f->bad=true;
}
static void put(void *context,ht_byte value)
{
    struct fake *f=context;ht_byte bank,reg;
    if(f->used>=3) {f->bad=true;return;}
    f->payload[f->used++]=value;
    if(f->used!=(f->command==0xbb ? 1:3))return;
    f->requests++;
    if(!ht_allowed(f->command,f->payload,f->used)) {f->bad=true;return;}
    if(f->command==0xbb) {
        reg=f->payload[0];f->answer=reg==0x50 ? f->version:reg;
        if(reg>=0x20 && reg<0x40) {
            if(f->change_project && f->bb_project_reads>=32)f->answer++;
            f->bb_project_reads++;
        }
    } else {
        bank=f->payload[0];reg=f->payload[1];f->answer=reg;
        if(bank==0x82) {
            if(reg!=0x11 || value<1 || value>5) {f->bad=true;f->policy_writes++;}
            else {if(f->board_writes==5)f->restore_request=f->requests;f->selected=value;f->board_writes++;}
            return;
        }
        if(bank>5 || f->payload[2])f->bad=true;
        if(bank==2) {
            if(reg==0x10)f->answer=f->change_count && f->board_writes ? 4:5;
            if(reg==0x11)f->answer=f->wrong_selector && f->board_writes ? 5:f->selected;
            if(reg==0x12)f->answer=30+f->selected;
            if(reg==0x13)f->answer=0;
            if(reg==0x30)f->answer=f->count;
            if(reg==0x31)f->answer=f->mode;
            if(reg==0x32)f->answer=1;
            if(reg==0x33)f->answer=0x34;
            if(reg==0x34)f->answer=0x12;
            if(reg==0x35) {if(!f->mode)f->bad=true;f->answer=f->duty;}
        }
    }
    f->pending=true;
}
static ht_time now(void *context) {return ((struct fake *)context)->clock;}
static void pause_io(void *context) {((struct fake *)context)->clock+=100;}
static struct ht_io io_for(struct fake *f)
{
    struct ht_io io={state,data,command,put,now,pause_io,f,5,0};return io;
}
static struct fake fresh(void)
{
    struct fake f={0};f.selected=4;f.duty=194;f.count=1;f.version=15;return f;
}
static unsigned int checks;
#define CHECK(x) do {if(!(x)) {fprintf(stderr,"FAIL diagnostics line%d: %s\n",__LINE__,#x);return 1;} checks++;}while(0)
int main(void)
{
    unsigned int n,total,board_total,restore_request,board_stages;
    struct fake f=fresh();struct ht_io io=io_for(&f);struct ht_diag_sample s={0};
    CHECK(HT_DIAG_FIELDS==40);
    CHECK(ht_diag_collect(&io,&s)==0);total=f.requests;restore_request=f.restore_request;
    CHECK(!f.bad && !f.policy_writes && f.selected==4 && s.board_restored);
    CHECK(!s.project_status && !s.chip_status && !s.manufacturer_status && !s.board_status && !s.fan_status && !s.vr_status);
    CHECK(s.fan.duty_status==-EOPNOTSUPP && s.fan.selection_raw==1 && !s.fan.index && s.fan.rpm==0x1234 && s.fan.mode==0);
    CHECK(s.project[0]==0x20 && s.project[31]==0x3f);
    CHECK(s.board[0]==31 && s.board[4]==35 && s.vr_count==0);
    for(n=0;n<HT_DIAG_FIELDS;n++)CHECK(!s.scalar_status[n]);
    for(n=1;n<=total;n++) {
        f=fresh();f.fail_at=n;io=io_for(&f);memset(&s,0,sizeof(s));
        {int ret=ht_diag_collect(&io,&s);CHECK(ret || n==restore_request || n==restore_request+1);}
        CHECK(f.selected==4 && !f.policy_writes && !f.bad);
    }
    f=fresh();io=io_for(&f);memset(&s,0,sizeof(s));
    CHECK(ht_diag_board_read(&io,&s)==0);board_total=f.requests;board_stages=f.status_calls;
    for(n=1;n<=board_total;n++) {
        int ret;
        f=fresh();f.fail_at=n;io=io_for(&f);memset(&s,0,sizeof(s));
        ret=ht_diag_board_read(&io,&s);
        CHECK(f.selected==4 && !f.policy_writes && !f.bad);
        /* A one-shot failure on restoration may recover on the bounded retry. */
        CHECK(ret || (s.board_restored && n>=18));
    }
    for(n=1;n<=board_stages;n++) {
        f=fresh();f.fail_status=n;io=io_for(&f);memset(&s,0,sizeof(s));
        (void)ht_diag_board_read(&io,&s);
        CHECK(f.selected==4 && !f.policy_writes && !f.bad && f.faulted);
    }
    f=fresh();f.version=14;io=io_for(&f);CHECK(ht_diag_collect(&io,&s)==-EOPNOTSUPP && f.requests==1);
    f=fresh();f.mode=1;io=io_for(&f);CHECK(ht_diag_collect(&io,&s)==-EBUSY && !f.board_writes);
    f=fresh();f.change_project=true;io=io_for(&f);CHECK(ht_diag_collect(&io,&s)==0 && s.project_status==-EAGAIN);
    f=fresh();f.change_count=true;io=io_for(&f);CHECK(ht_diag_collect(&io,&s)==0 && s.board_status==-EAGAIN && s.board_restored);
    f=fresh();f.selected=0;io=io_for(&f);CHECK(ht_diag_board_read(&io,&s)==-EPROTO && !f.board_writes);
    f=fresh();f.wrong_selector=true;io=io_for(&f);CHECK(ht_diag_board_read(&io,&s)!=0 && !s.board_restored);
    /* Early returns leave board_restored true (no latch); only a walk whose
     * restore fails clears it (the driver latches on that alone). */
    f=fresh();f.version=14;io=io_for(&f);memset(&s,0,sizeof(s));
    CHECK(ht_diag_collect(&io,&s)==-EOPNOTSUPP && s.board_restored && !f.board_writes);
    f=fresh();f.mode=1;io=io_for(&f);memset(&s,0,sizeof(s));
    CHECK(ht_diag_collect(&io,&s)==-EBUSY && s.board_restored && !f.board_writes);
    f=fresh();f.fail_at=1;io=io_for(&f);memset(&s,0,sizeof(s));
    CHECK(ht_diag_collect(&io,&s)!=0 && s.board_restored && !f.board_writes);
    f=fresh();f.wrong_selector=true;io=io_for(&f);memset(&s,0,sizeof(s));
    CHECK(ht_diag_collect(&io,&s)!=0 && !s.board_restored && f.board_writes);
    /* Latched board fault: no selector traffic, board reported -EUCLEAN, rest collected. */
    f=fresh();io=io_for(&f);memset(&s,0,sizeof(s));s.board_disabled=true;
    CHECK(ht_diag_collect(&io,&s)==0 && !f.board_writes && s.board_status==-EUCLEAN && s.board_restored &&
          !s.board_count && !s.fan_status && !f.bad);
    {unsigned int requests=f.requests;memset(&s,0,sizeof(s));s.board_disabled=true;
        CHECK(ht_diag_board_read(&io,&s)==-EUCLEAN && f.requests==requests);}
    f=fresh();f.mode=1;io=io_for(&f);CHECK(ht_diag_fan_read(&io,&s.fan)==0 && s.fan.mode==1 && s.fan.duty==194 && !s.fan.duty_status && !f.board_writes);
    f=fresh();f.mode=1;f.duty=195;io=io_for(&f);CHECK(ht_diag_fan_read(&io,&s.fan)==-EPROTO);
    printf("Diagnostics: %u complete-collection, %u selector-request and %u partial-transaction failure boundaries, %u checks; fixed reads, version/ownership, raw duty and exact board restoration passed.\n",total,board_total,board_stages,checks);
    return 0;
}
