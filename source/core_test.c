/* SPDX-License-Identifier: MIT */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "healthytable_history.h"
#include "healthytable_oem.h"
#include "healthytable_voltage.h"
#include "healthytable_frequency.h"
#include "healthytable_pd.h"
#include "healthytable_power.h"
#include "healthytable_eeprom.h"

struct fake_pd { unsigned int reads,fail_at; bool changing,bad_address; };
static int pd_read(void *context,unsigned int address,ht_byte *out)
{
    struct fake_pd *f=context;
    unsigned int n=f->reads++;
    if (address!=0x380 && address!=0x381 && address!=0xbf0 && address!=0xbf1 &&
        !(address>=0xab1 && address<=0xaba) && !(address>=0xb28 && address<=0xb2b) &&
        !(address>=0xb98 && address<=0xb9b)) {f->bad_address=true;return -EPERM;}
    if (f->fail_at && f->reads==f->fail_at)return -EIO;
    *out=(ht_byte)(address+(f->changing && n>=22 ? 1 : 0));
    return 0;
}

struct fake_sources { unsigned int reads,fail_at,change_at,source_reads[2]; ht_byte bytes[4096]; };
static int sources_read(void *context,unsigned int address,ht_byte *out)
{
    struct fake_sources *f=context;
    f->reads++;
    if(address>=0xb32 && address<=0xb4e)f->source_reads[0]++;
    if(address>=0xba2 && address<=0xbbe)f->source_reads[1]++;
    if(f->fail_at==f->reads)return -EIO;
    if(address>=sizeof(f->bytes))return -EPERM;
    *out=f->bytes[address];
    if(f->change_at && f->reads>=f->change_at && address==0x380)*out^=1;
    return 0;
}

struct fake {
    unsigned int fault, writes, requests, high_reads, fail_request, cache_reads, delays;
    bool corrupt_cache, change_cache_state, no_cache_ready;
    ht_byte command, payload[3], answer, mode, duty, version, count;
    size_t used;
    bool pending, bad;
    ht_time clock;
    ht_byte regs[8][256];
    ht_byte board[5], board_index;
    /* Drop selector writes of ignore_selector after letting the first
     * ignore_selector_after of them through, ignore_selector_count times. */
    ht_byte ignore_selector;
    unsigned int ignore_selector_after, ignore_selector_count, selector_writes;
};
static ht_byte status(void *p)
{
    struct fake *f=p;
    if (f->fault==1 || (f->fail_request && f->requests==f->fail_request)) return 255;
    if (f->fault==2) return 2;
    if (f->fault==3) return 1;
    return f->pending ? 1 : 0;
}
static ht_byte data(void *p)
{
    struct fake *f=p;
    if (!f->pending) f->bad=true;
    f->pending=false;
    return f->answer;
}
static void command(void *p, ht_byte v)
{
    struct fake *f=p;
    f->writes++;
    if (v==255) { f->used=0; f->command=0; }
    else if (v==0xbb || v==0xdd || v==0xde) f->command=v;
    else f->bad=true;
}
static void write_data(void *p, ht_byte v)
{
    struct fake *f=p;
    unsigned int rpm;
    f->writes++;
    if (f->used>=3) { f->bad=true; return; }
    f->payload[f->used++]=v;
    if (f->used!=(f->command==0xbb ? 1U : f->command==0xde ? 2U : 3U)) return;
    if (!ht_allowed(f->command,f->payload,f->used)) { f->bad=true; return; }
    f->requests++;
    if (f->command==0xdd && (f->payload[0]==0x86 || f->payload[0]==0x87)) {
        f->regs[f->payload[0]&0x7f][f->payload[1]]=v;f->pending=false;return;
    }
    if (f->command==0xde) {
        if (f->payload[0]==3 || (f->payload[0]>=8 && f->payload[0]<=11)) {
            f->answer=f->payload[0]==3 ? (f->fault==8 ? 0x40 : 0) : f->regs[0][f->payload[0]];
            f->pending=true;
        } else f->pending=false;
        return;
    }
    if (f->command==0xdd && f->payload[0]==0x81) {
        f->regs[1][0x5b]=f->no_cache_ready ? 0 : v==0x10 ? 0x10 : 0x2f;f->pending=false;return;
    }
    if (f->fault==6 && f->command==0xdd && f->payload[0]==6 && f->payload[1]==0) return;
    if (f->command==0xbb) f->answer=f->payload[0]==0x50 ? f->version : 0;
    else if (f->payload[0]==0x82) {
        if (f->payload[1]==0x11) {
            f->selector_writes++;
            if (f->ignore_selector_count && v==f->ignore_selector) {
                if (f->ignore_selector_after) f->ignore_selector_after--;
                else {f->ignore_selector_count--;return;}
            }
            if(v>=1 && v<=5)f->board_index=v;
            return;
        }
        if (f->payload[1]==0x31) { f->mode=v; if (v==1) f->duty=0; }
        else f->duty=v;
        f->pending=false;
        return;
    } else if (f->payload[0]!=2) { f->answer=f->regs[f->payload[0]][f->payload[1]]; }
    else if (f->payload[1]==0x30) f->answer=f->count;
    else if (f->payload[1]==0x31) f->answer=f->mode;
    else if (f->payload[1]==0x11) f->answer=f->board_index;
    else if (f->payload[1]==0x12 && f->fault==9 && f->board_index==3) return;
    else if (f->payload[1]==0x12) f->answer=f->board[(f->board_index ? f->board_index:1)-1];
    else if (f->payload[1]==0 || f->payload[1]==3 || f->payload[1]==0x10) f->answer=f->regs[2][f->payload[1]];
    else {
        rpm=f->mode ? (6160U*f->duty/255U) : 2890U;
        if (f->fault==4) rpm=65535U;
        if (f->payload[1]==0x34) {
            f->high_reads++;
            f->answer=(ht_byte)(rpm>>8);
            if (f->fault==5 && f->high_reads==1) f->answer--;
        } else f->answer=(ht_byte)(rpm&255U);
    }
    if (f->command==0xdd && f->payload[0]==1 && f->payload[1]>=0x60 && f->payload[1]<=0x7f) {
        if (f->corrupt_cache && f->cache_reads>=32) f->answer^=1;
        f->cache_reads++;
    }
    if (f->change_cache_state && f->command==0xdd && f->payload[0]==1 && f->payload[1]==0x5b && f->cache_reads>=32) f->answer^=1;
    f->pending=true;
}
static void cache_delay(void *context,unsigned int ms)
{
    struct fake *f=context;f->clock+=(ht_time)ms*1000;f->delays++;
}
static ht_time now(void *p) { return ((struct fake *)p)->clock; }
static void pause_io(void *p) { ((struct fake *)p)->clock+=100; }
static struct ht_io io_for(struct fake *f)
{
    struct ht_io io={status,data,command,write_data,now,pause_io,f,0,0};
    return io;
}
static unsigned int passed;
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); return 1; } passed++; } while(0)
int main(void)
{
    {
        ht_byte bytes[HT_EEPROM_REPLY_MAX]={0x5a,0xa5};unsigned int length=99;
        CHECK(ht_eeprom_ready(0,0) && ht_eeprom_ready(0,8));
        CHECK(!ht_eeprom_ready(-ENODEV,0xfffffffe) && !ht_eeprom_ready(0,0xffffffff));
        CHECK(ht_eeprom_frame(bytes,9,&length)==0 && length==9);
        bytes[6]=255;
        CHECK(ht_eeprom_frame(bytes,256,&length)==-EMSGSIZE && !length);
        CHECK(ht_eeprom_frame(bytes,264,&length)==0 && length==264);
        CHECK(ht_eeprom_frame(bytes,HT_EEPROM_REPLY_MAX,&length)==0 && length==264);
        bytes[0]=0;
        CHECK(ht_eeprom_frame(bytes,264,&length)==-ENODATA && !length);
        CHECK(ht_eeprom_frame(bytes,6,&length)==-EMSGSIZE);
        CHECK(ht_eeprom_frame(bytes,1025,&length)==-EOVERFLOW);
        bytes[0]=0xfe;bytes[1]=0xff;bytes[2]=0xff;bytes[3]=0xff;
        CHECK(ht_eeprom_frame(bytes,4,&length)==-EOPNOTSUPP && !length);
        CHECK(ht_oem_valid(HT_OEM_EEPROM_BUFFER,0xe5,0,0)==0);
        CHECK(ht_oem_valid(HT_OEM_EEPROM_BUFFER,0xe5,0,1)==0 && ht_oem_mutates(HT_OEM_EEPROM_BUFFER));
        CHECK(ht_oem_valid(HT_OEM_EEPROM_BUFFER,0xe5,0,2)==-EINVAL && ht_oem_valid(HT_OEM_EEPROM_BUFFER,0xe3,0,1)==-EPERM);
        CHECK(ht_oem_valid(HT_OEM_EEPROM_BUFFER,0xe3,0,0)==-EPERM);
        CHECK(ht_oem_valid(HT_OEM_EEPROM_BUFFER,0xe5,1,0)==-EPERM);
        CHECK(ht_oem_scalar_status(HT_OEM_EEPROM,0,0xffffffff)==0);
        CHECK(ht_oem_scalar_status(HT_OEM_WMI_DSTS,0,0xffffffff)==-ENODEV);
        CHECK(ht_oem_scalar_status(HT_OEM_EEPROM,-EIO,0xffffffff)==-EIO);
    }
    {
        long power=0;
        CHECK(ht_psys_uw(0,16384,1000000,14,&power)==0 && power==1000000);
        CHECK(ht_energy_reprime(-ENODATA) && ht_energy_reprime(-ESTALE));
        CHECK(!ht_energy_reprime(0) && !ht_energy_reprime(-EAGAIN) && !ht_energy_reprime(-EPROTO) && !ht_energy_reprime(-EIO) && !ht_energy_reprime(-ERANGE));
        CHECK(HT_ENERGY_REPRIME_MS>=100 && HT_ENERGY_REPRIME_MS<1000);
        CHECK(ht_psys_uw(0xffffc000U,0,1000000,14,&power)==0 && power==1000000);
        CHECK(ht_psys_uw(0,491520,500000,14,&power)==0 && power==60000000);
        CHECK(ht_psys_uw(0,1,1000000,14,&power)==0 && power==61);
        CHECK(ht_psys_uw(5,5,1000000,14,&power)==-ENODATA);
        CHECK(ht_psys_uw(0,100,99999,14,&power)==-EAGAIN);
        CHECK(ht_psys_uw(0,100,30000001,14,&power)==-ESTALE);
        CHECK(ht_psys_uw(0,100,1000000,32,&power)==-EINVAL);
        CHECK(ht_psys_uw(0,100,100000,31,&power)==-ESTALE);
        CHECK(ht_psys_uw(0,100,4096000,20,&power)==-ESTALE);
        CHECK(ht_psys_uw(0,0xffffffffU,1000000,0,&power)==-ERANGE);
    }
    {
        struct fake_pd pd={0};
        ht_byte bytes[HT_PD_SIZE]={0};unsigned int size=99;
        CHECK(ht_pd_snapshot(pd_read,&pd,bytes,&size)==0 && size==23 && pd.reads==44 && !pd.bad_address);
        CHECK(bytes[0]==1 && bytes[1]==0x80 && bytes[2]==0x81 && bytes[3]==0xf0 && bytes[13]==0xf1);
        pd=(struct fake_pd){.changing=true};
        CHECK(ht_pd_snapshot(pd_read,&pd,bytes,&size)==-EAGAIN && size==0 && pd.reads==44);
        pd=(struct fake_pd){.fail_at=5};
        CHECK(ht_pd_snapshot(pd_read,&pd,bytes,&size)==-EIO && size==0 && pd.reads==5);
        CHECK(ht_oem_valid(HT_OEM_PD_SNAPSHOT,0,0,0)==0 && !ht_oem_mutates(HT_OEM_PD_SNAPSHOT));
        CHECK(ht_oem_valid(HT_OEM_PD_SNAPSHOT,0xab1,0,0)==-EPERM);
        CHECK(ht_oem_valid(HT_OEM_PD_SNAPSHOT,0,1,0)==-EPERM);
        CHECK(ht_oem_valid(HT_OEM_PD_SNAPSHOT,0,0,1)==-EPERM);
    }
    {
        struct fake_sources f={0};
        ht_byte bytes[HT_PD_SOURCES_SIZE];unsigned int size=0,i,reads;
        f.bytes[0x380]=1;f.bytes[0xbf0]=0x40;f.bytes[0xb32]=4;
        for(i=0;i<16;i++)f.bytes[0xb33+i]=(ht_byte)(i+1);
        f.bytes[0xba2]=255; /* Ignore inactive stale source cache. */
        CHECK(ht_pd_sources_snapshot(sources_read,&f,bytes,&size)==0 && size==81);
        CHECK(bytes[23]==4 && bytes[24]==1 && bytes[39]==16 && bytes[40]==0 && bytes[52]==0);
        reads=f.reads;
        for(i=1;i<=reads;i++) {
            f.reads=0;f.fail_at=i;
            CHECK(ht_pd_sources_snapshot(sources_read,&f,bytes,&size)==-EIO && size==0);
        }
        f.fail_at=0;f.reads=0;f.change_at=40;
        CHECK(ht_pd_sources_snapshot(sources_read,&f,bytes,&size)==-EAGAIN && size==0);
        f.change_at=0;f.reads=0;f.bytes[0xb32]=8;
        CHECK(ht_pd_sources_snapshot(sources_read,&f,bytes,&size)==-EPROTO && size==0);
        f.reads=0;f.bytes[0x380]=0;
        CHECK(ht_pd_sources_snapshot(sources_read,&f,bytes,&size)==0 && bytes[23]==0 && bytes[52]==0);
        f.reads=0;f.bytes[0x380]=1;f.bytes[0xbf0]=0;f.bytes[0xbf1]=0x40;f.bytes[0xba2]=1;
        f.bytes[0xba3]=123;
        CHECK(ht_pd_sources_snapshot(sources_read,&f,bytes,&size)==0 && bytes[23]==0 && bytes[52]==1 && bytes[53]==123);
        for (unsigned int port=0;port<2;port++) for (unsigned int count=1;count<=7;count++) {
            unsigned int address=port ? 0xba2:0xb32,offset=23+29*port;
            f=(struct fake_sources){0};f.bytes[0x380]=1;f.bytes[port ? 0xbf1:0xbf0]=0x40;
            f.bytes[address]=(ht_byte)count;
            for(i=0;i<4*count;i++)f.bytes[address+1+i]=(ht_byte)(i*19+7);
            CHECK(ht_pd_sources_snapshot(sources_read,&f,bytes,&size)==0 && size==81 && bytes[offset]==count);
            CHECK(!memcmp(bytes+offset+1,f.bytes+address+1,4*count));
            CHECK(f.source_reads[port]==2*(1+4*count) && !f.source_reads[1-port]);
            for(i=4*count;i<28;i++)CHECK(bytes[offset+1+i]==0);
            reads=f.reads;
            for(i=1;i<=reads;i++) {
                ht_byte unchanged[HT_PD_SOURCES_SIZE];
                memset(bytes,0xa5,sizeof(bytes));memcpy(unchanged,bytes,sizeof(bytes));
                f.reads=0;f.fail_at=i;
                CHECK(ht_pd_sources_snapshot(sources_read,&f,bytes,&size)==-EIO && size==0);
                CHECK(!memcmp(bytes,unchanged,sizeof(bytes)));
            }
        }
    }
    struct fake f={.version=15,.count=1};
    struct ht_io io=io_for(&f);
    long rpm=0;
    ht_byte mode=255, answer=0;
    CHECK(ht_identify(&io)==0);
    CHECK(ht_rpm(&io,&rpm)==0 && rpm==2890);
    CHECK(ht_full(&io)==0 && f.mode==1 && f.duty==255);
    CHECK(ht_rpm(&io,&rpm)==0 && rpm==6160);
    CHECK(ht_restore_owned(&io)==0 && f.mode==0);
    CHECK(ht_read(&io,0x31,&mode)==0 && mode==0);
    CHECK(ht_rpm(&io,&rpm)==0 && rpm==2890 && !f.bad);
    const ht_byte denied[][3]={{0x82,0x31,2},
                              {0x82,0x32,0},{0x02,0x36,0},{0x02,0x30,1}};
    for (size_t i=0;i<sizeof(denied)/sizeof(denied[0]);i++) {
        unsigned int before=f.writes;
        CHECK(ht_xfer(&io,0xdd,denied[i],3,NULL)==-EPERM && f.writes==before);
    }
    const ht_byte read_packet[]={0x02,0x31,0}, write_packet[]={0x82,0x31,0};
    CHECK(ht_xfer(&io,0xdd,read_packet,3,NULL)==-EINVAL);
    CHECK(ht_xfer(&io,0xdd,write_packet,3,&answer)==-EINVAL);
    {const ht_byte duty_read[]={2,0x35,0};unsigned int before=f.writes;
        CHECK(ht_xfer(&io,0xdd,duty_read,3,NULL)==-EINVAL && f.writes==before);}
    for (unsigned int fault=1;fault<=3;fault++) {
        struct fake bad={.fault=fault,.version=15,.count=1};
        struct ht_io bad_io=io_for(&bad);
        int expected=fault==1 ? -ENODEV : fault==2 ? -ETIMEDOUT : -EBUSY;
        CHECK(ht_identify(&bad_io)==expected && bad.writes==0);
    }
    for (unsigned int version=0;version<=255;version+=255) {
        struct fake bad={.version=(ht_byte)version,.count=1};
        struct ht_io bad_io=io_for(&bad);
        CHECK(ht_identify(&bad_io)==-ENODEV && bad.requests==1);
    }
    for (unsigned int count=0;count<=2;count+=2) {
        struct fake bad={.version=15,.count=(ht_byte)count};
        struct ht_io bad_io=io_for(&bad);
        CHECK(ht_identify(&bad_io)==-ENODEV && bad.requests==2);
    }
    f.fault=4; CHECK(ht_rpm(&io,&rpm)==-ERANGE);
    f.fault=5; f.high_reads=0; CHECK(ht_rpm(&io,&rpm)==0 && rpm==2890 && f.high_reads==4);
    CHECK(ht_minimum_rpm(200)==500 && ht_minimum_rpm(2890)==1445);
    f.fault=0; f.pending=true; f.answer=17; f.mode=1;
    CHECK(ht_restore_owned(&io)==0 && f.mode==0);
    for (unsigned int duty=0;duty<256;duty++) {
        const ht_byte packet[]={0x82,0x35,(ht_byte)duty};
        CHECK(ht_allowed(0xdd,packet,3));
        struct fake range={.version=15,.count=1};
        struct ht_io range_io=io_for(&range);
        CHECK(ht_manual(&range_io,(ht_byte)duty)==0 && range.mode==1 && range.duty==duty && !range.bad);
        CHECK(ht_restore_owned(&range_io)==0 && range.mode==0 && !range.bad);
        for (unsigned int fail=1;fail<=3;fail++) {
            range=(struct fake){.version=15,.count=1,.fail_request=fail};
            CHECK(ht_manual(&range_io,(ht_byte)duty)==-ENODEV);
            range.fail_request=0;
            CHECK(ht_restore_owned(&range_io)==0 && range.mode==0 && !range.bad);
        }
        {
            unsigned int writes=range.writes,length=0;
            long result=0;ht_byte out[4];
            CHECK(ht_oem_ec(&range_io,HT_OEM_WRITE_BYTE,0x0235,duty,true,&result,out,&length)==-EPERM && range.writes==writes);
            CHECK(ht_oem_ec(&range_io,HT_OEM_WRITE_BYTE,0x0231,duty,true,&result,out,&length)==-EPERM && range.writes==writes);
        }
    }
    CHECK(ht_manual(&io,127)==0 && f.mode==1 && f.duty==127);
    CHECK(ht_restore_owned(&io)==0 && f.mode==0);
    CHECK(ht_manual(&io,128)==0 && f.mode==1 && f.duty==128);
    CHECK(ht_rpm(&io,&rpm)==0 && rpm>=3000);
    CHECK(ht_restore_owned(&io)==0 && f.mode==0);
    for (unsigned int observed=0;observed<256;observed++) {
        CHECK(ht_fan_unsafe(0,(ht_byte)observed,1445,1445)==(observed!=1));
        CHECK(ht_fan_unsafe(0,(ht_byte)observed,1444,1445));
        CHECK(ht_fan_unsafe(-EIO,(ht_byte)observed,20000,1445));
    }
    CHECK(ht_fan_unsafe(0,1,0,500) && !ht_fan_unsafe(0,1,500,500));
    f.regs[1][0x34]=0xad; f.regs[1][0x35]=0x0b;
    CHECK(ht_word(&io,1,0x34,&rpm)==0 && rpm==2989);
    CHECK(ht_temperature(rpm,true,&rpm)==0 && rpm==25750);
    CHECK(ht_temperature(80,false,&rpm)==0 && rpm==80000);
    CHECK(ht_temperature(0,false,&rpm)==-ENODATA);
    CHECK(ht_temperature(65535,true,&rpm)==-ENODATA);
    CHECK(ht_signed_word(65535)==-1 && ht_signed_word(65536-1500)==-1500);
    f.regs[6][2]=0x12; f.regs[6][3]=0x34;f.regs[6][4]=0x56;f.regs[6][5]=0x78;
    CHECK(ht_dword(&io,6,2,&rpm)==0 && rpm==0x78563412);
    struct ht_snapshot snap={0};
    f.regs[1][0x10]='A'; f.regs[1][0x20]='B';
    CHECK(ht_snapshot_read(&io,&snap)==0 && !strcmp(snap.manufacturer,"A") && !strcmp(snap.battery_name,"B"));
    CHECK(snap.value[3]==2989 && snap.value[24]==-1 && !f.bad);
    f.regs[2][0x10]=5;
    for (unsigned int j=0;j<5;j++) f.board[j]=30+j;
    f.board_index=4;
    CHECK(ht_snapshot_read(&io,&snap)==0 && snap.board[4]==34 && snap.board[0]==30 && f.board_index==4 && f.mode==0);
    f.fault=6; snap.unavailable_mask=0;
    CHECK(ht_snapshot_read(&io,&snap)==0 && snap.value[23]==-1 && snap.unavailable_mask==((ht_time)1<<23));
    ht_time before_time=f.clock;
    CHECK(ht_snapshot_read(&io,&snap)==0 && f.clock==before_time);
    f.regs[1][0x10]=255;
    CHECK(ht_string(&io,0x10,11,snap.manufacturer)==-ENODATA);
    f.fault=9;
    CHECK(ht_snapshot_read(&io,&snap)==-ETIMEDOUT && f.board_index==4);
    f.fault=0;
    /* L3: one dropped restore write is detected by readback and retried. */
    f.ignore_selector=4;f.ignore_selector_after=1;f.ignore_selector_count=1;f.selector_writes=0;
    CHECK(ht_snapshot_read(&io,&snap)==0 && f.board_index==4 && !snap.board_restore_failed &&
          f.selector_writes==7 && !f.ignore_selector_count);
    /* Two dropped restore writes: reported, not adopted as the original. */
    f.ignore_selector_after=1;f.ignore_selector_count=2;f.selector_writes=0;
    CHECK(ht_snapshot_read(&io,&snap)==-EIO && snap.board_restore_failed && f.board_index==5 &&
          f.selector_writes==7 && !f.bad);
    /* Latched by the caller: no further selector writes; other fields still read. */
    snap.board_disabled=true;f.selector_writes=0;f.board_index=4;
    CHECK(ht_snapshot_read(&io,&snap)==0 && !f.selector_writes && snap.board[0]==-1 &&
          snap.board_celsius==-1 && snap.value[3]==2989 && !snap.board_restore_failed);
    snap.board_disabled=false;
    /* L6: a stray queued byte is drained once and the field retried, rather
     * than a sticky -EBUSY or a field marked unavailable. */
    f.pending=true;f.answer=0x5a;snap.unavailable_mask=0;
    CHECK(ht_snapshot_read(&io,&snap)==0 && !snap.unavailable_mask && snap.value[0]==f.regs[2][0] && !f.bad);
    {
        /* Permanently asserted OBF: one drain and resync attempt, then -EBUSY. */
        struct fake stuck={.fault=3,.version=15,.count=1};
        struct ht_io stuck_io=io_for(&stuck);
        struct ht_snapshot stuck_snap={0};
        CHECK(ht_snapshot_read(&stuck_io,&stuck_snap)==-EBUSY && stuck.requests==0);
        CHECK(ht_stray_recover(&stuck_io)==-EBUSY && stuck.requests==0);
        /* ECMT/mailbox -EBUSY reaches ht_optional_recover: a queued byte that
         * may be firmware's is never drained and no command is issued. */
        stuck.fault=0;stuck.writes=0;stuck.pending=true;stuck.answer=0x77;stuck.bad=false;
        CHECK(ht_optional_recover(&stuck_io,-EBUSY)==-EBUSY && !stuck.writes && stuck.pending && !stuck.bad);
        stuck.pending=false;
        CHECK(ht_optional_recover(&stuck_io,-EBUSY)==-EBUSY && !stuck.writes);
        /* No queued byte: the stray-byte path does nothing either. */
        CHECK(ht_stray_recover(&stuck_io)==-EBUSY && !stuck.writes);
    }
    const ht_byte factory[][3]={{0x86,0x36,2},{0x86,0x27,1},{0x81,0x5a,1},{4,0x51,5},{6,0x35,0},{0x82,0x11,0},{0x82,0x11,6}};
    for (size_t j=0;j<sizeof(factory)/sizeof(factory[0]);j++) {
        unsigned int before=f.writes;
        CHECK(ht_xfer(&io,0xdd,factory[j],3,NULL)==-EPERM && f.writes==before);
    }
    struct ht_history history={0};
    CHECK(ht_history_refresh(&io)==0 && f.mode==0);
    CHECK(ht_history_read(&io,&history)==0 && history.status==0x2f);
    f.regs[0][8]=0x78;f.regs[0][9]=0x56;f.regs[0][10]=0x34;f.regs[0][11]=0x12;
    CHECK(ht_gauge_status(&io,0x51,&rpm)==0 && rpm==0x12345678);
    CHECK(ht_gauge_status(&io,0x53,&rpm)==0 && f.mode==0);
    unsigned int before=f.writes;
    CHECK(ht_gauge_status(&io,0xff,&rpm)==-EPERM && f.writes==before);
    f.fault=8;
    CHECK(ht_gauge_status(&io,0x51,&rpm)==-ENODATA && f.mode==0);
    const ht_byte invalid_gauge[]={4,0x52};
    CHECK(ht_xfer(&io,0xde,invalid_gauge,2,NULL)==-EPERM);
    ht_byte out[256];unsigned int length;long result;
    before=f.writes;
    CHECK(ht_oem_ec(&io,HT_OEM_CLEAR_POWER,0,0,false,&result,out,&length)==-EAGAIN && f.writes==before);
    CHECK(ht_oem_ec(&io,HT_OEM_WRITE_BYTE,0x0231,1,true,&result,out,&length)==-EPERM && f.mode==0);
    CHECK(ht_oem_valid(HT_OEM_WRITE_BYTE,0x8231,1,1)==-ERANGE);
    CHECK(ht_oem_valid(HT_OEM_WRITE_BYTE,0x8235,255,1)==-ERANGE);
    CHECK(ht_oem_valid(HT_OEM_NOTIFY,0,2,1)==-ERANGE);
    CHECK(ht_oem_valid(HT_OEM_EEPROM,0xe0,0,0)==0 && ht_oem_valid(HT_OEM_EEPROM,0x4e1,0,0)==0);
    CHECK(ht_oem_valid(HT_OEM_EEPROM,0x4321,0,0)==-EPERM);
    /* L1: DEVS is a set method, so op 11 needs the explicit apply flag. */
    CHECK(ht_oem_mutates(HT_OEM_EEPROM) && ht_oem_valid(HT_OEM_EEPROM,0xe0,0,1)==0);
    CHECK(!ht_oem_mutates(HT_OEM_WMI_DSTS) && ht_oem_mutates(HT_OEM_EEPROM_BUFFER) &&
          !ht_oem_mutates(HT_OEM_READ_BYTE) && !ht_oem_mutates(HT_OEM_PD_IC));
    for (unsigned int op=HT_OEM_CLEAR_POWER;op<=HT_OEM_READ_CLEAR_CHARGER;op++) CHECK(ht_oem_mutates(op));
    CHECK(ht_oem_mutates(HT_OEM_WRITE_BYTE));
    CHECK(ht_oem_valid(HT_OEM_WMI_DSTS,0x120079,0,0)==0);
    CHECK(ht_oem_valid(HT_OEM_WMI_DSTS,0x60068,0,0)==0);
    CHECK(ht_oem_valid(HT_OEM_WMI_DSTS,0x60068,1,0)==-EPERM);
    CHECK(ht_oem_valid(HT_OEM_WMI_DSTS,0x120079,3,0)==-EPERM);
    CHECK(ht_oem_valid(HT_OEM_WMI_DSTS,0x1200f2,1,0)==0);
    CHECK(ht_oem_valid(HT_OEM_WMI_DSTS,0x1200f2,4,0)==-EPERM);
    CHECK(ht_oem_valid(HT_OEM_WMI_DSTS,0x123456,0,0)==-EPERM);
    f.fault=0;f.regs[6][0]=1;f.regs[6][0x27]=12;f.regs[6][0x28]=11;
    CHECK(ht_oem_ec(&io,HT_OEM_CLEAR_CHARGER,0,0,true,&result,out,&length)==0 && f.regs[6][0x27]==0 && f.regs[6][0x28]==0 && f.mode==0);
    f.version=23;
    CHECK(ht_oem_ec(&io,HT_OEM_NOTIFY,0,1,true,&result,out,&length)==0 && f.regs[6][0x36]==1);
    CHECK(ht_oem_ec(&io,HT_OEM_POWER_MONITOR,0,1,true,&result,out,&length)==0 && f.regs[7][9]==0x85);
    CHECK(ht_oem_ec(&io,HT_OEM_POWER_MONITOR,0,0,true,&result,out,&length)==0 && f.regs[7][9]==5);
    f.version=15;
    /* Current .301 source rejects both directions before any port I/O. The
     * preceding generic fixtures retain recovered original protocol recipes. */
    io.max_dd_bank=5;
    before=f.writes;
    CHECK(ht_bank(&io,6,0,&answer)==-EOPNOTSUPP && f.writes==before);
    CHECK(ht_dword(&io,6,2,&rpm)==-EOPNOTSUPP && f.writes==before);
    CHECK(ht_oem_ec(&io,HT_OEM_CLEAR_CHARGER,0,0,true,&result,out,&length)==-EOPNOTSUPP && f.writes==before);
    CHECK(ht_oem_ec(&io,HT_OEM_NOTIFY,0,1,true,&result,out,&length)==-EOPNOTSUPP && f.writes==before);
    CHECK(ht_oem_ec(&io,HT_OEM_POWER_MONITOR,0,1,true,&result,out,&length)==-EOPNOTSUPP && f.writes==before);
    snap.unavailable_mask=0;
    CHECK(ht_snapshot_read(&io,&snap)==0 && snap.value[23]==-1 && !snap.unavailable_mask);
    CHECK(snap.unsupported_mask & ((ht_time)1<<23));
    for (size_t j=0;j<HT_FIELDS;j++)
        CHECK(!!(snap.unsupported_mask & ((ht_time)1<<j))==(ht_fields[j].bank==6));
    CHECK(snap.board[0]==30 && snap.board[4]==34 && f.board_index==4 && !f.bad);
    io.max_dd_bank=0;
    long voltage=0;
    CHECK(ht_perf_status_mv((ht_time)0x2000<<32,&voltage)==0 && voltage==1000);
    CHECK(ht_perf_status_mv((ht_time)0x1000<<32,&voltage)==0 && voltage==500);
    CHECK(ht_perf_status_mv(((ht_time)0x262f<<32)|0x1f00,&voltage)==0 && voltage==1193);
    CHECK(ht_perf_status_mv(0,&voltage)==-ENODATA);
    CHECK(ht_perf_status_mv((ht_time)0xffff<<32,&voltage)==-ENODATA);
    CHECK(ht_perf_status_mv((ht_time)1<<32,&voltage)==-ENODATA);
    CHECK(ht_perf_status_mv((ht_time)0x6000<<32,&voltage)==-ENODATA);
    {
        unsigned int ratio=999,mhz=999;
        for (unsigned int value=0;value<256;value++) {
            int ret=ht_ratio_mhz(((ht_time)0x242d<<32)|(value<<8),false,100,&ratio,&mhz);
            CHECK((value&0x7f) ? (ret==0 && ratio==(value&0x7f) && mhz==ratio*100) : ret==-ENODATA);
            ret=ht_ratio_mhz(0x2c2c2c2c2c2c0000ULL|value,true,100,&ratio,&mhz);
            CHECK((value && value!=255) ? (ret==0 && ratio==value && mhz==ratio*100) : ret==-ENODATA);
        }
        CHECK(ht_ratio_mhz(0x2e00,false,0,&ratio,&mhz)==-ENODATA);
        CHECK(ht_ratio_mhz(0x2e,true,1001,&ratio,&mhz)==-ENODATA);
        CHECK(ht_ratio_mhz(0x2e00,false,133,&ratio,&mhz)==0 && mhz==6118);
        CHECK(ht_ratio_mhz(0x2e,true,1000,&ratio,&mhz)==0 && mhz==46000);
    }
    {
        struct fake c={.version=15,.count=1};
        struct ht_io cache_io=io_for(&c);
        struct ht_cache_frame frame={0}, unchanged;
        unsigned int requests;
        memset(&unchanged,0xa5,sizeof(unchanged));
        for (unsigned int j=0;j<32;j++) c.regs[1][0x60+j]=(ht_byte)(j+1);
        CHECK(ht_cache_collect(&cache_io,0x10,cache_delay,&c,&frame)==0);
        CHECK(frame.length==32 && frame.ready_bit==0x10 && frame.refresh_requested && frame.data[31]==32 && !c.bad && !c.delays);
        requests=c.requests;
        for (unsigned int fail=1;fail<=requests;fail++) {
            c=(struct fake){.version=15,.count=1,.fail_request=fail};memcpy(&frame,&unchanged,sizeof(frame));
            CHECK(ht_cache_collect(&cache_io,0x10,cache_delay,&c,&frame)<0);
            CHECK(!memcmp(&frame,&unchanged,sizeof(frame)));
        }
        c=(struct fake){.version=15,.count=1};c.regs[1][0x5c]=0x12;c.regs[1][0x5f]=0x78;
        CHECK(ht_cache_collect(&cache_io,0x80,cache_delay,&c,&frame)==0 && frame.length==4 && frame.ready_bit==0x20 && frame.data[0]==0x12 && frame.data[3]==0x78);
        c=(struct fake){.version=9,.count=1};
        CHECK(ht_cache_collect(&cache_io,0x10,cache_delay,&c,&frame)==-EOPNOTSUPP && c.requests==1);
        c=(struct fake){.version=15};
        CHECK(ht_cache_collect(&cache_io,0x11,cache_delay,&c,&frame)==-EINVAL && !c.requests);
        c.regs[1][0x5b]=0x40;
        CHECK(ht_cache_collect(&cache_io,0x10,cache_delay,&c,&frame)==-EIO && c.requests==3);
        c=(struct fake){.version=15};c.regs[1][0x5b]=0x80;
        CHECK(ht_cache_collect(&cache_io,0x10,cache_delay,&c,&frame)==-EBUSY && c.requests==3);
        c=(struct fake){.version=15};c.regs[1][0x5b]=0x10;c.regs[1][3]=4;
        CHECK(ht_cache_collect(&cache_io,0x10,cache_delay,&c,&frame)==0 && !frame.refresh_requested);
        c=(struct fake){.version=15,.no_cache_ready=true};memcpy(&frame,&unchanged,sizeof(frame));
        CHECK(ht_cache_collect(&cache_io,0x10,cache_delay,&c,&frame)==-ETIMEDOUT && c.delays==3);
        CHECK(!memcmp(&frame,&unchanged,sizeof(frame)));
        c=(struct fake){.version=15,.corrupt_cache=true};memcpy(&frame,&unchanged,sizeof(frame));
        CHECK(ht_cache_collect(&cache_io,0x10,cache_delay,&c,&frame)==-EAGAIN && !memcmp(&frame,&unchanged,sizeof(frame)));
        c=(struct fake){.version=15,.change_cache_state=true};memcpy(&frame,&unchanged,sizeof(frame));
        CHECK(ht_cache_collect(&cache_io,0x10,cache_delay,&c,&frame)==-EAGAIN && !memcmp(&frame,&unchanged,sizeof(frame)));
    }
    printf("PASS: %u transport/control checks; mocked I/O only.\n",passed);
    return 0;
}
