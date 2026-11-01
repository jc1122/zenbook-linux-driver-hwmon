/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#ifdef NDEBUG
#error "tests require assertions"
#endif
#include <stdio.h>
#include <string.h>
#include "healthytable_charger.h"
struct fake {ht_byte ram[0x42];unsigned int calls,fail,fail2,restore_fail,starts,unstable,voltage_reads,worker_fail,stall_at,stalled_calls;bool bad;ht_time clock,cost;};
/* stall_at: from that primitive on, the EC never answers (ec_transaction -ETIME).
 * cost: simulated duration of every issued primitive. */
static int fault(struct fake *f){
 f->calls++;f->clock+=f->cost;
 if(f->stall_at && f->calls>=f->stall_at){f->stalled_calls++;return -ETIME;}
 return (f->calls==f->fail || f->calls==f->fail2) ? -ETIMEDOUT : 0;
}
static ht_time clock_now(void *p){return ((struct fake *)p)->clock;}
struct port {ht_time t;unsigned int pauses;};
static ht_byte port_busy(void *p){(void)p;return 2;}
static ht_byte port_data(void *p){(void)p;return 0;}
static void port_out(void *p,ht_byte v){(void)p;(void)v;}
static ht_time port_clock(void *p){return ((struct port *)p)->t;}
static void port_pause(void *p){struct port *x=p;x->t+=1000;x->pauses++;}
static int read_byte(void *p,unsigned int address,ht_byte *value){
 struct fake *f=p;int r=fault(f);if(r)return r;
 if(address==0x380){*value=3;return 0;}
 assert(address>=0x9000 && address<=0x9041);*value=f->ram[address-0x9000];return 0;
}
static int restore(void *p,unsigned int index,ht_byte value){
 struct fake *f=p;int r=fault(f);if(r)return r;
 if(f->restore_fail && index==7)return -EIO;
 assert(index<HT_CHARGER_FIELDS);f->ram[ht_charger_fields[index]-0x9000]=value;return 0;
}
static int set(void *p,ht_byte index,ht_byte value){
 struct fake *f=p;unsigned int word=0;int r=fault(f);if(r)return r;
 assert(ht_charger_request(index,value));f->ram[index]=value;
 if(index==0)f->ram[14]=1;
 if(index==0x10)f->ram[15]++;
 if(index!=4)return 0;
 f->starts++;
 if(f->ram[0]!=2 || f->ram[1]!=0x12 || f->ram[2]!=1 || f->ram[3]!=2)f->bad=true;
 switch(f->ram[16]){
 case 0xfe:word=0x49;break;case 0xff:word=0x0e;break;
 case 0x4c:word=0x4003;break;case 0x4e:word=0xb02c;break;
 case 0x82:word=220;break;case 0x81:word=8320;break;case 0x84:word=10;break;
 case 0x85:word=20;break;case 0x86:word=6016;break;case 0x3a:word=0x8069;break;case 0x91:word=0;break;
 case 0x4d:word=0x4c44;break;case 0x83:word=40;break;case 0x87:word=13056;if(f->unstable && (++f->voltage_reads%2)==0){word+=256;f->unstable--;}break;
 default:assert(0);
 }
 f->ram[0x40]=word&255;f->ram[0x41]=word>>8;f->ram[4]=0x80;f->ram[1]=0;
 if(f->worker_fail){f->worker_fail--;f->ram[4]=0x81;}
 return 0;
}
static int get(void *p,ht_byte index,ht_byte *value){struct fake *f=p;int r=fault(f);if(r)return r;assert(index==0x40 || index==0x41);*value=f->ram[index];return 0;}
static struct ht_charger_io io(struct fake *f){return (struct ht_charger_io){.read=read_byte,.restore=restore,.set=set,.get=get,.ctx=f};}
static struct fake initial(void){struct fake f={0};f.ram[16]=0xa7;f.ram[0x40]=0x12;f.ram[0x41]=0x34;return f;}
int main(void){
 struct fake f=initial();struct ht_charger_io x=io(&f);struct ht_charger_sample sample={0},original;unsigned int calls,n,index,value,allowed=0;
 assert(ht_charger_collect(&x,&sample)==0);assert(!f.bad && f.starts==10);
 assert(sample.voltage_mv==19584 && sample.current_ua==1776000 && sample.power_uw==34781184);
 assert(f.ram[16]==0xa7 && f.ram[0x40]==0x12 && f.ram[0x41]==0x34 && !f.ram[15]);calls=f.calls;
 /* A lost request/response at every boundary must not publish partial data;
  * cleanup must either restore the mailbox or report an explicit hard fault. */
 for(n=1;n<=calls;n++){
  struct fake start=initial();int r;f=start;f.fail=n;x=io(&f);memset(&sample,0x5a,sizeof(sample));memcpy(&original,&sample,sizeof(sample));
  r=ht_charger_collect(&x,&sample);assert(r<0);assert(!memcmp(&sample,&original,sizeof(sample)));
  if(r!=-EUCLEAN)assert(!memcmp(f.ram,start.ram,sizeof(f.ram)));
  assert(!f.bad);
 }
 f=initial();f.unstable=1;x=io(&f);assert(ht_charger_collect(&x,&sample)==0 && f.starts==13);
 f=initial();f.unstable=3;x=io(&f);assert(ht_charger_collect(&x,&sample)==-EAGAIN && f.starts==16);
 f=initial();f.restore_fail=1;x=io(&f);assert(ht_charger_collect(&x,&sample)==-EUCLEAN);
 /* One transient worker failure: exactly one fresh complete transaction. */
 f=initial();f.worker_fail=1;x=io(&f);assert(ht_charger_collect(&x,&sample)==-EIO && f.starts==1 && !memcmp(f.ram,initial().ram,0x10));
 f=initial();f.worker_fail=1;x=io(&f);memset(&sample,0,sizeof(sample));assert(ht_charger_collect_retry(&x,&sample)==0 && f.starts==11 && !f.bad && sample.voltage_mv>0);
 f=initial();f.worker_fail=2;x=io(&f);assert(ht_charger_collect_retry(&x,&sample)==-EIO && f.starts==2);
 f=initial();f.restore_fail=1;f.worker_fail=1;x=io(&f);assert(ht_charger_collect_retry(&x,&sample)==-EUCLEAN && f.starts==1);
 f=initial();f.ram[5]=1;x=io(&f);assert(ht_charger_collect_retry(&x,&sample)==-EBUSY && f.starts==0);
 f=initial();f.ram[5]=1;x=io(&f);assert(ht_charger_collect(&x,&sample)==-EBUSY && f.starts==0);

 /* Stalled EC: from every primitive boundary on, nothing answers. At most
  * HT_EC_STALL_TIMEOUTS+1 primitives (one operation, then a fresh restore count) may be issued into the stall; a modified
  * mailbox always reports -EUCLEAN and never publishes a sample. */
 {unsigned int start=0,stalls=0;
  for(n=1;n<=calls;n++){
   struct fake s0=initial();int r;f=s0;f.stall_at=n;x=io(&f);memset(&sample,0x5a,sizeof(sample));memcpy(&original,&sample,sizeof(sample));
   r=ht_charger_collect(&x,&sample);
   assert(f.stalled_calls>=1 && f.stalled_calls<=HT_EC_STALL_TIMEOUTS+1 && f.calls==n-1+f.stalled_calls);
   assert(!memcmp(&sample,&original,sizeof(sample)) && !f.bad);
   if(r==-EUCLEAN){if(!start)start=n;if(x.stalled)stalls++;}
   else{assert(r==-ETIME && !start && !memcmp(f.ram,s0.ram,sizeof(f.ram)));}
  }
  assert(start==28 && stalls==calls-start);
  /* Retry wrapper never retries into a stall. */
  f=initial();f.stall_at=40;x=io(&f);assert(ht_charger_collect_retry(&x,&sample)==-EUCLEAN && f.stalled_calls==3 && f.starts<=1 && x.stalled && !x.restore_expired);
  /* One operation-phase timeout, then a failed first restore, then a healthy EC:
   * the restore phase starts with a fresh count and restores every field. */
  {struct fake s0=initial();f=s0;f.fail=40;f.fail2=41;x=io(&f);
   assert(ht_charger_collect(&x,&sample)==-EUCLEAN && !x.stalled && !memcmp(f.ram,s0.ram,sizeof(f.ram)));
   f=s0;f.fail=40;x=io(&f);assert(ht_charger_collect(&x,&sample)==-ETIMEDOUT && !memcmp(f.ram,s0.ram,sizeof(f.ram)));}
  printf("Charger stalled EC: %u boundaries, <=%u primitives into the stall, fail closed.\n",calls,HT_EC_STALL_TIMEOUTS+1);
 }
 /* Deadlines with a simulated clock. Healthy fast EC is unaffected. */
 {struct port pt={0};struct ht_io p={port_busy,port_data,port_out,port_out,port_clock,port_pause,&pt,0,0};
  f=initial();f.cost=1000;x=io(&f);x.now_us=clock_now;x.port=&p;
  assert(ht_charger_collect(&x,&sample)==0 && sample.voltage_mv==19584 && p.limit_us==0 && !x.stalled);
  /* Healthy-but-slow: the measured 1.5 s session, and 2.5x that, succeed. */
  f=initial();f.cost=1500000/calls;x=io(&f);x.now_us=clock_now;x.port=&p;
  assert(ht_charger_collect_retry(&x,&sample)==0 && !x.stalled && f.clock>=1400000);
  f=initial();f.cost=1500000*5/2/calls;x=io(&f);x.now_us=clock_now;x.port=&p;
  assert(ht_charger_collect_retry(&x,&sample)==0 && !x.stalled && f.clock>=3700000);
  {struct ht_charger_extra e;f=initial();f.cost=1300000*5/2/120;x=io(&f);x.now_us=clock_now;assert(ht_charger_extra_collect_retry(&x,&e)==0);}
  /* Slow EC (60 ms/primitive): operation deadline aborts, restore completes. */
  f=initial();f.cost=60000;x=io(&f);x.now_us=clock_now;x.port=&p;memcpy(&original,&sample,sizeof(sample));
  assert(ht_charger_collect(&x,&sample)==-ETIMEDOUT && !memcmp(&sample,&original,sizeof(sample)));
  assert(!memcmp(f.ram,initial().ram,sizeof(f.ram)) && p.limit_us==0 && !x.stalled);
  assert(f.clock<=HT_CHARGER_BUDGET_US+f.cost+21*f.cost);
  /* Slower EC (200 ms): restore budget expires, remaining primitives skipped. */
  f=initial();f.cost=200000;x=io(&f);x.now_us=clock_now;x.port=&p;
  assert(ht_charger_collect_retry(&x,&sample)==-EUCLEAN && x.restore_expired && !x.stalled && !memcmp(&sample,&original,sizeof(sample)));
  assert(f.clock<=HT_CHARGER_BUDGET_US+ht_ec_restore_budget(HT_CHARGER_FIELDS)+2*f.cost && p.limit_us==0);
  /* Pre-modification deadline: nothing written, no restore needed. */
  f=initial();f.cost=400000;x=io(&f);x.now_us=clock_now;
  assert(ht_charger_collect(&x,&sample)==-ETIMEDOUT && f.calls==15 && !memcmp(f.ram,initial().ram,sizeof(f.ram)));
  /* Session clamps every port wait to the operation deadline and clears it. */
  f=initial();x=io(&f);x.now_us=clock_now;x.port=&p;f.clock=pt.t=0;
  ht_ec_begin(&x,HT_CHARGER_BUDGET_US);assert(p.limit_us==HT_CHARGER_BUDGET_US && ht_ec_restore_budget(10)==3000000 && ht_ec_restore_budget(48)==11640000 && x.operation_end==p.limit_us);
  /* Deadline-truncated port waits are not EC timeouts; earlier ones are. */
  assert(ht_ec_port_account(&x,-ETIMEDOUT)==-ETIMEDOUT && x.timeouts==1);x.timeouts=0;
  f.clock=HT_CHARGER_BUDGET_US;
  assert(ht_ec_port_account(&x,-ETIMEDOUT)==-ETIMEDOUT && ht_ec_port_account(&x,-ETIMEDOUT)==-ETIMEDOUT && !x.timeouts && !x.stalled);
  f.clock=0;
  assert(ht_ec_end(&x,-EIO)==-EIO && p.limit_us==0);
  /* The restore phase moves the port bound to its own deadline, then back. */
  {struct fake s1=initial();ht_byte keep[HT_CHARGER_FIELDS]={0};unsigned int k;f=s1;x=io(&f);x.now_us=clock_now;x.port=&p;
   for(k=0;k<HT_CHARGER_FIELDS;k++)keep[k]=f.ram[ht_charger_fields[k]-0x9000];
   ht_ec_begin(&x,1000);f.clock=5000;
   assert(ht_ec_restore_fields(&x,ht_charger_fields,keep,HT_CHARGER_FIELDS)==0 && p.limit_us==1000 && x.restore_end==5000+3000000);
   assert(ht_ec_end(&x,0)==0 && p.limit_us==0);}
  assert(ht_charger_packet(&p,true,0,2,NULL)==-ETIMEDOUT && pt.pauses>=499);
  pt=(struct port){0};p.limit_us=5000;
  assert(ht_charger_packet(&p,true,0,2,NULL)==-ETIMEDOUT && pt.pauses<=6);
  pt=(struct port){.t=9000};assert(ht_charger_packet(&p,true,0,2,NULL)==-ETIMEDOUT && pt.pauses<=1);
  p.limit_us=0;
  printf("Charger session deadlines: operation, restore and port-wait bounds passed.\n");
 }
 for(index=0;index<256;index++)for(value=0;value<256;value++)if(ht_charger_request(index,value))allowed++;
 assert(allowed==19);assert(!ht_charger_request(0x10,0x39));assert(!ht_charger_request(0x10,0x90));assert(!ht_charger_request(1,0x16));
 sample=(struct ht_charger_sample){.words={0x49,0xe,0x4003,0xb02c,0x4c44,13056,40,13056,0x4c44,0x4003}};
 assert(ht_charger_decode(&sample)==0);sample.words[6]=256;assert(ht_charger_decode(&sample)==-EPROTO);
 sample.words[6]=40;sample.words[3]|=0x800;assert(ht_charger_decode(&sample)==-ENODATA);
 sample.words[3]=0xb02c;sample.words[7]+=128;assert(ht_charger_decode(&sample)==-EAGAIN);
 sample.words[7]=13056;sample.words[8]=0;assert(ht_charger_decode(&sample)==-ENODATA);

 {struct ht_charger_extra extra={0},saved;unsigned int count;
  f=initial();x=io(&f);assert(ht_charger_extra_collect(&x,&extra)==0);
  f=initial();f.worker_fail=1;x=io(&f);assert(ht_charger_extra_collect_retry(&x,&extra)==0 && f.starts==15);
  f=initial();f.worker_fail=2;x=io(&f);assert(ht_charger_extra_collect_retry(&x,&extra)==-EIO && f.starts==2);
  assert(extra.valid_mask==31 && extra.die_mc==51511 && extra.vbat_mv==8320 && extra.system_mv==9024);
  assert(extra.discharge_ua==888000 && extra.charge_ua==888000);count=f.calls;
  for(n=1;n<=count;n++){
   struct fake start=initial();int r;f=start;f.fail=n;x=io(&f);memset(&extra,0x5a,sizeof(extra));memcpy(&saved,&extra,sizeof(extra));
   r=ht_charger_extra_collect(&x,&extra);assert(r<0);assert(!memcmp(&extra,&saved,sizeof(extra)));
   if(r!=-EUCLEAN)assert(!memcmp(f.ram,start.ram,sizeof(f.ram)));
  }
  for(n=1;n<=count;n++){
   struct fake start=initial();int r;f=start;f.stall_at=n;x=io(&f);memset(&extra,0x5a,sizeof(extra));memcpy(&saved,&extra,sizeof(extra));
   r=ht_charger_extra_collect_retry(&x,&extra);
   assert(f.stalled_calls>=1 && f.stalled_calls<=HT_EC_STALL_TIMEOUTS+1 && !memcmp(&extra,&saved,sizeof(extra)));
   assert(r==-EUCLEAN || (r==-ETIME && !memcmp(f.ram,start.ram,sizeof(f.ram))));
  }
  f=initial();x=io(&f);assert(ht_charger_extra_collect(&x,&extra)==0);
  extra.words[2]=0;assert(ht_charger_extra_decode(&extra)==0 && extra.valid_mask==0);
  extra.words[2]=0x4003;extra.words[3]|=0x800;
  assert(ht_charger_extra_decode(&extra)==0 && extra.valid_mask==7);
  printf("Extra charger metrics: %u failure boundaries; temperature, shunts, disabled ADC and non-clearing status passed.\n",count);
 }
 printf("Charger ADC: %u injected failures, restoration, identity, calibration, unplug and fixed read-only request set passed.\n",calls);
 return 0;
}
