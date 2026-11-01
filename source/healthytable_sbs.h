/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef ZENBOOK_SBS_H
#define ZENBOOK_SBS_H
#include "healthytable_gauge_block.h"

/* Fixed SBS READ words. The current target uses native SMBus ReadWord;
 * the older combined-read helper remains for regression/rollback evidence.
 * Never an SBS data write or ManufacturerAccess selection.
 * BatteryStatus is excluded: it carries communication-error state. */
#define HT_SBS_WORDS 16
#define HT_SBS_FIELDS 49
/* Measured healthy battery_sbs session 5.7 s. */
#define HT_SBS_BUDGET_US 24000000U
#define HT_SBS_TAIL_GUARD 0x5a
static const ht_byte ht_sbs_commands[HT_SBS_WORDS]={
    0x1a,0x03,0x08,0x09,0x0a,0x0b,0x14,0x15,
    0x0c,0x0d,0x0e,0x0f,0x10,0x17,0x18,0x19
};
static const unsigned int ht_sbs_fields[HT_SBS_FIELDS]={
    0x9000,0x9001,0x9002,0x9003,0x9004,0x9005,0x9006,0x9007,
    0x9008,0x9009,0x900a,0x900b,0x900c,0x900d,0x900e,0x900f,0x9010,
    0x9040,0x9041,0x9042,0x9043,0x9044,0x9045,0x9046,0x9047,
    0x9048,0x9049,0x904a,0x904b,0x904c,0x904d,0x904e,0x904f,
    0x9050,0x9051,0x9052,0x9053,0x9054,0x9055,0x9056,0x9057,
    0x9058,0x9059,0x905a,0x905b,0x905c,0x905d,0x905e,0x905f
};
struct ht_sbs_sample {ht_byte identity[2],firmware[13];unsigned int words[HT_SBS_WORDS];};
enum ht_sbs_phase {
    HT_SBS_NONE,HT_SBS_SNAPSHOT,HT_SBS_IDLE,HT_SBS_IDENTITY,HT_SBS_FIRMWARE,
    HT_SBS_PREPARE,HT_SBS_SENTINEL,HT_SBS_CHANNEL,HT_SBS_COMMAND,HT_SBS_SUBMIT,
    HT_SBS_COMPLETION,HT_SBS_BUS_STATUS,HT_SBS_RX_LOW,HT_SBS_RX_HIGH,
    HT_SBS_BRACKET,HT_SBS_COMPLETE,HT_SBS_NATIVE_COMPLETION,HT_SBS_NATIVE_RESULT,HT_SBS_RX_TAIL
};
/* In-memory tracing of existing operations adds no I/O. A separately invoked
 * fixed software-SRAM observer is defined below. Neither changes SBS requests. */
struct ht_sbs_software_observation {
    ht_byte bytes[4];
    bool sampled;
    int result;
};
struct ht_sbs_trace {
    unsigned int phase,attempt;
    ht_byte command,completion,bus_status,worker_result;
    bool command_valid,completion_valid,bus_status_valid,worker_result_valid,bracket,native_word;
    int operation_status,restoration_status,result;
    struct ht_sbs_software_observation software;
};
static inline void ht_sbs_phase(struct ht_sbs_trace *trace,unsigned int phase)
{
    if(trace)trace->phase=phase;
}
static inline bool ht_sbs_command(ht_byte value)
{
    unsigned int i;
    for(i=0;i<HT_SBS_WORDS;i++)if(value==ht_sbs_commands[i])return true;
    return false;
}
static inline bool ht_sbs_request(ht_byte index,ht_byte value)
{
    return (index==0 && value==2) || (index==1 && value==0x16) ||
        (index==2 && value==1) || (index==3 && value==2) ||
        (index==4 && value==4) || (index==0x10 && ht_sbs_command(value));
}
static inline bool ht_sbs_native_request(ht_byte index,ht_byte value)
{
    return (index==0 && value==2) || (index==5 && value==2) ||
        (index==6 && value==9) || (index==8 && value==0x16) ||
        (index==9 && ht_sbs_command(value)) || (index==4 && value==0x10);
}
static inline int ht_sbs_wire_packet(struct ht_io *io,bool write,ht_byte index,ht_byte value,ht_byte *answer,bool native)
{
    ht_time end=io->now_us(io->ctx)+500000;
    int ret;
    if(write ? !(native ? ht_sbs_native_request(index,value):ht_sbs_request(index,value)):
       (native ? index<0x40 || index>0x5f:(index!=0x40 && index!=0x41)))return -EPERM;
    if((!write)!=(answer!=NULL))return -EINVAL;
    if(io->status(io->ctx)&1)return -EBUSY;
    ret=ht_wait(io,2,false,end);if(ret)return ret;io->command(io->ctx,255);
    ret=ht_wait(io,2,false,end);if(ret)return ret;io->command(io->ctx,write ? 0xab:0xaa);
    ret=ht_wait(io,2,false,end);if(ret)return ret;io->write(io->ctx,index);
    if(write){ret=ht_wait(io,2,false,end);if(ret)return ret;io->write(io->ctx,value);}
    ret=ht_wait(io,2,false,end);if(ret || write)return ret;
    ret=ht_wait(io,1,true,end);if(!ret)*answer=io->data(io->ctx);return ret;
}
static inline int ht_sbs_packet(struct ht_io *io,bool write,ht_byte index,ht_byte value,ht_byte *answer)
{
    return ht_sbs_wire_packet(io,write,index,value,answer,false);
}
static inline int ht_sbs_native_packet(struct ht_io *io,bool write,ht_byte index,ht_byte value,ht_byte *answer)
{
    return ht_sbs_wire_packet(io,write,index,value,answer,true);
}
static inline int ht_sbs_set(struct ht_charger_io *io,ht_byte index,ht_byte value)
{
    ht_byte got;
    int ret;
    if(!ht_sbs_request(index,value))return -EPERM;
    ret=ht_ec_set(io,index,value);if(ret || index==4)return ret;
    ret=ht_ec_read(io,0x9000+index,&got);return ret ? ret:got==value ? 0:-EPROTO;
}
static inline int ht_sbs_native_set(struct ht_charger_io *io,ht_byte index,ht_byte value)
{
    ht_byte got;int ret;
    if(!ht_sbs_native_request(index,value))return -EPERM;
    ret=ht_ec_set(io,index,value);if(ret || index==4)return ret;
    ret=ht_ec_read(io,0x9000+index,&got);return ret ? ret:got==value ? 0:-EPROTO;
}
static inline int ht_sbs_word_trace(struct ht_charger_io *io,ht_byte command,unsigned int *word,struct ht_sbs_trace *trace)
{
    ht_byte low,high,status,pattern;
    unsigned int attempt;
    int ret;
    if(trace){trace->command=command;trace->command_valid=true;}
    if(!ht_sbs_command(command))return -EPERM;
    for(attempt=0;attempt<2;attempt++){
        if(trace){trace->attempt=attempt;trace->completion_valid=false;trace->bus_status_valid=false;}
        pattern=attempt ? 0xa5:0x5a;
        ht_sbs_phase(trace,HT_SBS_SENTINEL);
        ret=ht_ec_restore(io,17,pattern);if(ret)return ret;
        ret=ht_ec_restore(io,18,pattern);if(ret)return ret;
        ht_sbs_phase(trace,HT_SBS_CHANNEL);
        ret=ht_sbs_set(io,1,0x16);if(ret)return ret;
        ht_sbs_phase(trace,HT_SBS_COMMAND);
        ret=ht_sbs_set(io,0x10,command);if(ret)return ret;
        ht_sbs_phase(trace,HT_SBS_SUBMIT);
        ret=ht_sbs_set(io,4,4);if(ret)return ret;
        ht_sbs_phase(trace,HT_SBS_COMPLETION);
        ret=ht_ec_read(io,0x9004,&status);if(ret)return ret;
        if(trace){trace->completion=status;trace->completion_valid=true;}
        if(status!=0x80)return -EIO;
        ht_sbs_phase(trace,HT_SBS_BUS_STATUS);
        ret=ht_ec_read(io,0x9001,&status);if(ret)return ret;
        if(trace){trace->bus_status=status;trace->bus_status_valid=true;}
        if(status)return -EPROTO;
        ht_sbs_phase(trace,HT_SBS_RX_LOW);
        ret=ht_ec_get(io,0x40,&low);if(ret)return ret;
        ht_sbs_phase(trace,HT_SBS_RX_HIGH);
        ret=ht_ec_get(io,0x41,&high);if(ret)return ret;
        /* The firmware fills RX sequentially. A replaced final byte proves the
         * complete word. Do not combine bytes from different transactions. */
        if(high==pattern)continue;
        *word=low+256U*high;return 0;
    }
    return -ENODATA;
}
static inline int ht_sbs_word(struct ht_charger_io *io,ht_byte command,unsigned int *word)
{
    return ht_sbs_word_trace(io,command,word,NULL);
}
static inline int ht_sbs_native_word(struct ht_charger_io *io,ht_byte command,unsigned int *word,struct ht_sbs_trace *trace)
{
    ht_byte frame[32],status,pattern;unsigned int attempt,i;int ret;
    if(trace){trace->command=command;trace->command_valid=true;}
    if(!ht_sbs_command(command))return -EPERM;
    for(attempt=0;attempt<2;attempt++){
        if(trace){trace->attempt=attempt;trace->completion_valid=false;trace->bus_status_valid=false;trace->worker_result_valid=false;}
        pattern=attempt ? 0xa5:0x5a;
        ht_sbs_phase(trace,HT_SBS_SENTINEL);
        ret=ht_ec_restore(io,17,pattern);if(ret)return ret;
        ret=ht_ec_restore(io,18,pattern);if(ret)return ret;
        ht_sbs_phase(trace,HT_SBS_CHANNEL);
        ret=ht_sbs_native_set(io,8,0x16);if(ret)return ret;
        ht_sbs_phase(trace,HT_SBS_COMMAND);
        ret=ht_sbs_native_set(io,9,command);if(ret)return ret;
        ht_sbs_phase(trace,HT_SBS_SUBMIT);
        ret=ht_sbs_native_set(io,4,0x10);if(ret)return ret;
        ht_sbs_phase(trace,HT_SBS_NATIVE_COMPLETION);
        ret=ht_ec_read(io,0x9004,&status);if(ret)return ret;
        if(trace){trace->completion=status;trace->completion_valid=true;}
        if(status)return -EPROTO;
        ht_sbs_phase(trace,HT_SBS_NATIVE_RESULT);
        ret=ht_ec_read(io,0x9007,&status);if(ret)return ret;
        if(trace){trace->worker_result=status;trace->worker_result_valid=true;}
        if(status!=1)return status ? -EPROTO:-EIO;
        for(i=0;i<32;i++){
            ht_sbs_phase(trace,i==0 ? HT_SBS_RX_LOW:i==1 ? HT_SBS_RX_HIGH:HT_SBS_RX_TAIL);
            ret=ht_ec_get(io,0x40+i,&frame[i]);if(ret)return ret;
            if(i>=2 && frame[i]!=HT_SBS_TAIL_GUARD)return -EPROTO;
        }
        /* The30-byte suffix is seeded once before any word and checked after
         * every frame. It is never rewritten between words, so a changed byte
         * aborts before any later request could conceal an overlong response. */
        if(frame[1]==pattern)continue;
        *word=frame[0]+256U*frame[1];return 0;
    }
    return -ENODATA;
}
/* Caller holds transport and ECMT locks, with manual fan ownership excluded. */
static inline int ht_sbs_collect_session(struct ht_gauge_full_io *full,struct ht_sbs_sample *sample,struct ht_sbs_trace *trace,void (*observe)(void *,struct ht_sbs_trace *),bool native)
{
    static const ht_byte firmware[]={0x45,0x56,2,0x34,0,0x40,2};
    struct ht_charger_io *io=&full->ipc;
    struct ht_sbs_sample next={0};
    ht_byte saved[HT_SBS_FIELDS],v;
    unsigned int i,bracket;
    int ret,restore;
    ht_sbs_phase(trace,HT_SBS_SNAPSHOT);
    for(i=0;i<HT_SBS_FIELDS;i++){ret=ht_ec_read(io,ht_sbs_fields[i],&saved[i]);if(ret)return ret;}
    ht_sbs_phase(trace,HT_SBS_IDLE);
    for(i=0;i<16;i++){ret=ht_ec_read(io,0x9000+i,&v);if(ret)return ret;if(v)return -EBUSY;}
    ht_sbs_phase(trace,HT_SBS_IDENTITY);
    ret=ht_ec_query(full,1,next.identity);if(ret)return ret;
    if(next.identity[0]!=0x56 || next.identity[1]!=0x45)return -ENODEV;
    ht_sbs_phase(trace,HT_SBS_FIRMWARE);
    ret=ht_ec_query(full,2,next.firmware);if(ret)return ret;
    for(i=0;i<sizeof(firmware);i++)if(next.firmware[i]!=firmware[i])return -ENODEV;
    ht_sbs_phase(trace,HT_SBS_PREPARE);
    ret=ht_sbs_set(io,0,2);if(ret)goto out;
    ret=ht_ec_read(io,0x900e,&v);if(ret)goto out;if(v!=1){ret=-EPROTO;goto out;}
    if(native){
        ret=ht_sbs_native_set(io,5,2);if(ret)goto out;
        ret=ht_ec_read(io,0x900d,&v);if(ret)goto out;if(v!=1){ret=-EPROTO;goto out;}
        ret=ht_sbs_native_set(io,6,9);if(ret)goto out;
        ht_sbs_phase(trace,HT_SBS_SENTINEL);
        for(i=0;i<32;i++){ret=ht_ec_restore(io,17+i,HT_SBS_TAIL_GUARD);if(ret)goto out;}
    }else{
        ret=ht_sbs_set(io,2,1);if(ret)goto out;
        ret=ht_sbs_set(io,3,2);if(ret)goto out;
    }
    for(i=0;i<HT_SBS_WORDS;i++){
        ret=native ? ht_sbs_native_word(io,ht_sbs_commands[i],&next.words[i],trace):ht_sbs_word_trace(io,ht_sbs_commands[i],&next.words[i],trace);
        if(ret)goto out;
    }
    if(trace)trace->bracket=true;
    for(i=0;i<2;i++){
        ret=native ? ht_sbs_native_word(io,ht_sbs_commands[i],&bracket,trace):ht_sbs_word_trace(io,ht_sbs_commands[i],&bracket,trace);if(ret)goto out;
        ht_sbs_phase(trace,HT_SBS_BRACKET);
        if(bracket!=next.words[i]){ret=-EAGAIN;goto out;}
    }
out:
    if(trace)trace->operation_status=ret;
    /* Observe only a completed failed fixed read, before restoration can reuse
     * firmware scratch. The callback cannot alter ret; restoration always runs. */
    if(!native && observe && trace && ret==-EIO && trace->phase==HT_SBS_COMPLETION &&
       trace->completion_valid && trace->completion==0x40)
        observe(io->ctx,trace);
    restore=ht_ec_restore_fields(io,ht_sbs_fields,saved,HT_SBS_FIELDS);
    if(trace)trace->restoration_status=restore;
    if(restore)return -EUCLEAN;
    if(!ret){*sample=next;ht_sbs_phase(trace,HT_SBS_COMPLETE);}
    return ret;
}
static inline int ht_sbs_collect_inner(struct ht_gauge_full_io *full,struct ht_sbs_sample *sample,struct ht_sbs_trace *trace,void (*observe)(void *,struct ht_sbs_trace *),bool native)
{
    ht_ec_begin(&full->ipc,HT_SBS_BUDGET_US);
    return ht_ec_end(&full->ipc,ht_sbs_collect_session(full,sample,trace,observe,native));
}
static inline int ht_sbs_collect_observed(struct ht_gauge_full_io *full,struct ht_sbs_sample *sample,struct ht_sbs_trace *trace,void (*observe)(void *,struct ht_sbs_trace *))
{
    int ret;
    if(trace)*trace=(struct ht_sbs_trace){0};
    ret=ht_sbs_collect_inner(full,sample,trace,observe,false);
    if(trace){
        trace->result=ret;
        if(ret && !trace->operation_status && !trace->restoration_status)trace->operation_status=ret;
    }
    return ret;
}
static inline int ht_sbs_collect_trace(struct ht_gauge_full_io *full,struct ht_sbs_sample *sample,struct ht_sbs_trace *trace)
{
    return ht_sbs_collect_observed(full,sample,trace,NULL);
}
static inline int ht_sbs_collect(struct ht_gauge_full_io *full,struct ht_sbs_sample *sample)
{
    return ht_sbs_collect_trace(full,sample,NULL);
}
static inline int ht_sbs_native_collect(struct ht_gauge_full_io *full,struct ht_sbs_sample *sample,struct ht_sbs_trace *trace)
{
    int ret;
    if(trace)*trace=(struct ht_sbs_trace){.native_word=true};
    ret=ht_sbs_collect_inner(full,sample,trace,NULL,true);
    if(trace){
        trace->result=ret;
        if(ret && !trace->operation_status && !trace->restoration_status)trace->operation_status=ret;
    }
    return ret;
}
static inline bool ht_sbs_retryable(const struct ht_sbs_trace *trace)
{
    /* The qualified worker writes40h after a completed unsuccessful transfer.
     * This is not permission to poll pending work, accept RX bytes, retry a
     * restoration error or repeat any unqualified/manufacturer command. */
    if(trace->result!=-EIO || trace->operation_status!=-EIO || trace->restoration_status ||
       !trace->command_valid || !ht_sbs_command(trace->command) || !trace->completion_valid)return false;
    if(trace->native_word)return trace->phase==HT_SBS_NATIVE_RESULT && !trace->completion && trace->worker_result_valid && !trace->worker_result;
    return trace->phase==HT_SBS_COMPLETION && trace->completion==0x40;
}
/* Target-firmware software SRAM copies only, not hardware status/FIFO registers.
 * Double sampling reduces torn observations; it cannot prove that the firmware
 * has not reused a copy. Never use these bytes to accept data or decide control. */
static inline int ht_sbs_observe_software(int (*read)(void *,unsigned int,ht_byte *),void *context,struct ht_sbs_software_observation *out)
{
    static const unsigned int addresses[]={0x9602,0x9603,0x961f,0x9620};
    struct ht_sbs_software_observation next={.sampled=true};
    ht_byte v;unsigned int i,pass;int ret=0;
    for(pass=0;pass<2;pass++)for(i=0;i<4;i++){
        ret=read(context,addresses[i],&v);if(ret)goto out;
        if(pass){if(v!=next.bytes[i]){ret=-EAGAIN;goto out;}}
        else next.bytes[i]=v;
    }
    if(next.bytes[1]!=0 || next.bytes[2]!=1 || next.bytes[3]>1)ret=-ESTALE;
out:
    if(ret)for(i=0;i<4;i++)next.bytes[i]=0;
    next.result=ret;*out=next;return ret;
}
#endif
