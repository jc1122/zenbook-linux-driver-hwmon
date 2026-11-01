/* SPDX-License-Identifier: GPL-2.0-only */
#include <stdio.h>
#include <string.h>
#include "healthytable_pd_identity.h"
struct fake {ht_byte mem[0x60];unsigned int step,fail_at,stall_at,stalled;bool bad,restore_fail,bad_alert_length,ext_absent,ext_overlong;ht_time clock,cost;};
/* stall_at: the EC stops answering from that primitive on (-ETIME). */
static int tick(struct fake *f){f->step++;f->clock+=f->cost;if(f->stall_at && f->step>=f->stall_at){f->stalled++;return -ETIME;}return f->step==f->fail_at ? -EIO:0;}
static ht_time clock_now(void *ctx){return ((struct fake *)ctx)->clock;}
static unsigned int offset(unsigned int addr){return addr>=0x9040 ? 0x40+addr-0x9040:addr-0x9000;}
static int read_byte(void *ctx,unsigned int addr,ht_byte *out){struct fake *f=ctx;int r=tick(f);if(r)return r;*out=f->mem[offset(addr)];return 0;}
static int restore(void *ctx,unsigned int index,ht_byte value){struct fake *f=ctx;int r=tick(f);if(r)return r;if(f->restore_fail)return -EIO;f->mem[offset(ht_pd_ic_fields[index])]=value;return 0;}
static int set(void *ctx,ht_byte index,ht_byte value){
 struct fake *f=ctx;int r=tick(f);if(r)return r;if(!ht_pd_ic_request(index,value)){f->bad=true;return -EPERM;}
 f->mem[index]=value;
 if(index==0)f->mem[14]=0;
 if(index==16)f->mem[15]++;
 if(index==4){
  memset(f->mem+0x40,0,26);
  if(f->mem[16]==3){memcpy(f->mem+0x40,"\004APP ",5);}
  else if(f->mem[16]==0x74){f->mem[0x40]=f->bad_alert_length ? 3:4;f->mem[0x43]=0x21;f->mem[0x44]=0x02;}
  else if(f->mem[16]==0x41 || f->mem[16]==0x42){f->mem[0x40]=f->ext_absent ? 0:4;f->mem[0x41]=f->mem[16];}
  else if(f->mem[16]==0x76){f->mem[0x40]=f->ext_overlong ? 26:24;f->mem[0x41]=0xb3;f->mem[0x42]=0x05;}
  else if(f->mem[16]==0x78){f->mem[0x40]=f->ext_absent ? 0:7;}
  else f->mem[0x40]=25;
  f->mem[4]=0x80;f->mem[1]=0;
 }
 return 0;
}
static int get(void *ctx,ht_byte index,ht_byte *out){struct fake *f=ctx;int r=tick(f);if(r)return r;if(index<0x40 || index>0x59){f->bad=true;return -EPERM;}*out=f->mem[index];return 0;}
static struct ht_charger_io io_for(struct fake *f){struct ht_charger_io io={.read=read_byte,.restore=restore,.set=set,.get=get,.ctx=f};return io;}
static void setup(struct fake *f){memset(f,0,sizeof(*f));for(unsigned int i=0x40;i<0x60;i++)f->mem[i]=(ht_byte)(i+10);}
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x);return 1;}}while(0)
int main(void){
 struct fake f;struct ht_charger_io io;struct ht_pd_identity sample,before;ht_byte saved[0x60];unsigned int count;
 setup(&f);memcpy(saved,f.mem,sizeof(saved));io=io_for(&f);
 CHECK(ht_pd_identity_collect(&io,3,&sample)==0 && sample.sop[0][0]==0 && sample.alert[0][2]==0x21 && sample.alert[1][3]==2 && !f.bad && !memcmp(saved,f.mem,sizeof(saved)));count=f.step;
 CHECK(count>0);
 for(unsigned int n=1;n<=count;n++){
  int ret;setup(&f);memcpy(saved,f.mem,sizeof(saved));f.fail_at=n;io=io_for(&f);memset(&sample,0xa5,sizeof(sample));memcpy(&before,&sample,sizeof(sample));
  ret=ht_pd_identity_collect(&io,3,&sample);
  CHECK((ret==-EIO || ret==-EUCLEAN) && !memcmp(&before,&sample,sizeof(sample)) && !f.bad);
  if(ret==-EIO)CHECK(!memcmp(saved,f.mem,sizeof(saved)));
 }
 /* Stalled EC at every boundary: bounded primitives, fail closed, no sample. */
 for(unsigned int n=1;n<=count;n++){
  int ret;setup(&f);memcpy(saved,f.mem,sizeof(saved));f.stall_at=n;io=io_for(&f);memset(&sample,0xa5,sizeof(sample));memcpy(&before,&sample,sizeof(sample));
  ret=ht_pd_identity_collect(&io,3,&sample);
  CHECK(f.stalled>=1 && f.stalled<=HT_EC_STALL_TIMEOUTS+1 && f.step==n-1+f.stalled && !memcmp(&before,&sample,sizeof(sample)) && !f.bad);
  CHECK(ret==-EUCLEAN || (ret==-ETIME && !memcmp(saved,f.mem,sizeof(saved))));
  if(n>HT_PD_IC_FIELDS+16 && n<count)CHECK(ret==-EUCLEAN && io.stalled);
 }
 setup(&f);f.cost=1000;io=io_for(&f);io.now_us=clock_now;CHECK(ht_pd_identity_collect(&io,3,&sample)==0 && !io.stalled);
 /* Healthy-but-slow: measured 2.3 s session, and 2.5x that, succeed. */
 setup(&f);f.cost=2300000/count;io=io_for(&f);io.now_us=clock_now;CHECK(ht_pd_identity_collect(&io,3,&sample)==0 && f.clock>=2200000);
 setup(&f);f.cost=2300000*5/2/count;io=io_for(&f);io.now_us=clock_now;CHECK(ht_pd_identity_collect(&io,3,&sample)==0 && !io.stalled);
 setup(&f);memcpy(saved,f.mem,sizeof(saved));f.cost=150000;io=io_for(&f);io.now_us=clock_now;memcpy(&before,&sample,sizeof(sample));
 CHECK(ht_pd_identity_collect(&io,3,&sample)==-EUCLEAN && io.restore_expired && !memcmp(&before,&sample,sizeof(sample)));
 CHECK(f.clock<=HT_PD_IC_BUDGET_US+ht_ec_restore_budget(HT_PD_IC_FIELDS)+2*f.cost);
 printf("PD identity stalled EC: %u boundaries, <=%u primitives into the stall; deadlines bounded.\n",count,HT_EC_STALL_TIMEOUTS+1);
 setup(&f);f.restore_fail=true;io=io_for(&f);CHECK(ht_pd_identity_collect(&io,1,&sample)==-EUCLEAN);
 setup(&f);f.bad_alert_length=true;io=io_for(&f);memcpy(saved,f.mem,sizeof(saved));memset(&sample,0xa5,sizeof(sample));memcpy(&before,&sample,sizeof(sample));
 CHECK(ht_pd_identity_collect(&io,1,&sample)==-EPROTO && !memcmp(&sample,&before,sizeof(sample)) && !memcmp(saved,f.mem,sizeof(saved)));
 setup(&f);io=io_for(&f);CHECK(ht_pd_identity_collect(&io,1,&sample)==0 && sample.alert[1][0]==0 && sample.alert[1][3]==0);
 {ht_byte scratch[26];setup(&f);io=io_for(&f);CHECK(ht_pd_ic_block(&io,0,0x75,scratch)==-EPERM && f.step==0);}
 setup(&f);f.mem[5]=1;io=io_for(&f);CHECK(ht_pd_identity_collect(&io,1,&sample)==-EBUSY);
 setup(&f);io=io_for(&f);CHECK(ht_pd_identity_collect(&io,0,&sample)==0 && f.step==0);
 CHECK(ht_pd_identity_collect(&io,4,&sample)==-EINVAL);
 {struct ht_pd_extended ext,eb;unsigned int ecount;
  setup(&f);memcpy(saved,f.mem,sizeof(saved));io=io_for(&f);
  CHECK(ht_pd_extended_collect(&io,2,&ext)==0 && !f.bad && !memcmp(saved,f.mem,sizeof(saved)));
  CHECK(ext.ports==2 && ext.length[1][0]==4 && ext.data[1][0][0]==0x41 && ext.length[1][2]==24 && ext.data[1][2][0]==0xb3 && ext.data[1][2][1]==5 && ext.length[1][3]==7 && ext.length[0][2]==0);
  ecount=f.step;
  for(unsigned int n=1;n<=ecount;n++){
   int ret;setup(&f);memcpy(saved,f.mem,sizeof(saved));f.fail_at=n;io=io_for(&f);memset(&ext,0xa5,sizeof(ext));memcpy(&eb,&ext,sizeof(ext));
   ret=ht_pd_extended_collect(&io,2,&ext);
   CHECK((ret==-EIO || ret==-EUCLEAN) && !memcmp(&eb,&ext,sizeof(ext)) && !f.bad);
   if(ret==-EIO)CHECK(!memcmp(saved,f.mem,sizeof(saved)));
  }
  for(unsigned int n=1;n<=ecount;n++){
   int ret;setup(&f);memcpy(saved,f.mem,sizeof(saved));f.stall_at=n;io=io_for(&f);memset(&ext,0xa5,sizeof(ext));memcpy(&eb,&ext,sizeof(ext));
   ret=ht_pd_extended_collect(&io,2,&ext);
   CHECK(f.stalled>=1 && f.stalled<=HT_EC_STALL_TIMEOUTS+1 && !memcmp(&eb,&ext,sizeof(ext)) && !f.bad);
   CHECK(ret==-EUCLEAN || (ret==-ETIME && !memcmp(saved,f.mem,sizeof(saved))));
  }
  setup(&f);f.ext_absent=true;io=io_for(&f);CHECK(ht_pd_extended_collect(&io,1,&ext)==0 && ext.length[0][0]==0 && ext.length[0][3]==0 && ext.length[0][2]==24);
  setup(&f);f.ext_overlong=true;io=io_for(&f);memcpy(saved,f.mem,sizeof(saved));memset(&ext,0xa5,sizeof(ext));memcpy(&eb,&ext,sizeof(ext));
  CHECK(ht_pd_extended_collect(&io,1,&ext)==-EPROTO && !memcmp(&eb,&ext,sizeof(ext)) && !memcmp(saved,f.mem,sizeof(saved)));
  setup(&f);f.restore_fail=true;io=io_for(&f);CHECK(ht_pd_extended_collect(&io,1,&ext)==-EUCLEAN);
  setup(&f);f.mem[5]=1;io=io_for(&f);CHECK(ht_pd_extended_collect(&io,1,&ext)==-EBUSY);
  setup(&f);io=io_for(&f);CHECK(ht_pd_extended_collect(&io,0,&ext)==0 && f.step==0 && ext.ports==0);
  {ht_byte len,data[25];setup(&f);io=io_for(&f);CHECK(ht_pd_ic_raw(&io,0,0x08,&len,data)==-EPERM && ht_pd_ic_raw(&io,0,0x09,&len,data)==-EPERM && f.step==0);}
  printf("PD extended: %u injected failures; four read-only registers, length bound, absent registers and restoration passed.\n",ecount);
 }
 for(unsigned int reg=0;reg<256;reg++)CHECK(ht_pd_ic_request(16,reg)==(reg==3 || reg==0x48 || reg==0x49 || reg==0x74 || reg==0x41 || reg==0x42 || reg==0x76 || reg==0x78));
 CHECK(!ht_pd_ic_request(2,2) && !ht_pd_ic_request(0,2) && !ht_pd_ic_request(4,1));
 printf("PD identity: %u injected failures; fixed pointer-only reads, active gating and verified IPC restoration passed.\n",count);
 return 0;
}
