/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef ZENBOOK_PD_IDENTITY_H
#define ZENBOOK_PD_IDENTITY_H
#include "healthytable_charger.h"
#define HT_PD_IC_FIELDS 34
/* Measured healthy pd_identity 2.2-2.3 s per session; pd_extended issues fewer primitives. */
#define HT_PD_IC_BUDGET_US 10000000U
static const unsigned int ht_pd_ic_fields[HT_PD_IC_FIELDS]={
    0x9000,0x9001,0x9002,0x9003,0x9004,0x900e,0x900f,0x9010,
    0x9040,0x9041,0x9042,0x9043,0x9044,0x9045,0x9046,0x9047,0x9048,
    0x9049,0x904a,0x904b,0x904c,0x904d,0x904e,0x904f,0x9050,0x9051,
    0x9052,0x9053,0x9054,0x9055,0x9056,0x9057,0x9058,0x9059
};
struct ht_pd_identity {ht_byte sop[2][25],cable[2][25],alert[2][4];};
static inline bool ht_pd_ic_request(ht_byte index,ht_byte value)
{
    return (index==0 && value==1) || (index==1 && (value==0x40 || value==0x48)) ||
        (index==2 && value==1) || (index==3 && (value==5 || value==26)) ||
        (index==4 && value==4) || (index==0x10 && (value==3 || value==0x48 || value==0x49 || value==0x74 ||
         value==0x41 || value==0x42 || value==0x76 || value==0x78));
}
/* Same firmware broker, separate fixed policy. Only a one-byte register pointer
 * is sent to a TCPC: never a 4CC, role, power, reset or discovery command. */
static inline int ht_pd_ic_packet(struct ht_io *io,bool write,ht_byte index,ht_byte value,ht_byte *answer)
{
    ht_time end=io->now_us(io->ctx)+500000;
    int ret;
    if(write ? !ht_pd_ic_request(index,value) : index<0x40 || index>0x59)return -EPERM;
    if((!write)!=(answer!=NULL))return -EINVAL;
    if(io->status(io->ctx)&1)return -EBUSY;
    ret=ht_wait(io,2,false,end);if(ret)return ret;
    io->command(io->ctx,255);
    ret=ht_wait(io,2,false,end);if(ret)return ret;
    io->command(io->ctx,write ? 0xab:0xaa);
    ret=ht_wait(io,2,false,end);if(ret)return ret;io->write(io->ctx,index);
    if(write){ret=ht_wait(io,2,false,end);if(ret)return ret;io->write(io->ctx,value);}
    ret=ht_wait(io,2,false,end);if(ret || write)return ret;
    ret=ht_wait(io,1,true,end);if(!ret)*answer=io->data(io->ctx);return ret;
}
static inline int ht_pd_ic_set(struct ht_charger_io *io,ht_byte index,ht_byte value)
{
    ht_byte got;
    int ret;
    if(!ht_pd_ic_request(index,value))return -EPERM;
    ret=ht_ec_set(io,index,value);if(ret || index==4)return ret;
    ret=ht_ec_read(io,0x9000+index,&got);return ret ? ret:got==value ? 0:-EPROTO;
}
static inline int ht_pd_ic_block(struct ht_charger_io *io,unsigned int port,ht_byte reg,ht_byte *out)
{
    unsigned int i,length=(reg==3 || reg==0x74) ? 5:26;
    ht_byte status;
    int ret;
    if(port>1 || (reg!=3 && reg!=0x48 && reg!=0x49 && reg!=0x74))return -EPERM;
    ret=ht_pd_ic_set(io,1,port ? 0x48:0x40);if(ret)return ret;
    ret=ht_pd_ic_set(io,3,length);if(ret)return ret;
    ret=ht_pd_ic_set(io,0x10,reg);if(ret)return ret;
    ret=ht_pd_ic_set(io,4,4);if(ret)return ret;
    ret=ht_ec_read(io,0x9004,&status);if(ret)return ret;if(status!=0x80)return -EIO;
    ret=ht_ec_read(io,0x9001,&status);if(ret)return ret;if(status)return -EPROTO;
    for(i=0;i<length;i++){ret=ht_ec_get(io,0x40+i,&out[i]);if(ret)return ret;}
    if(out[0]!=length-1)return -EPROTO;
    if(reg==3 && (out[1]!='A' || out[2]!='P' || out[3]!='P' || out[4]!=' '))return -ENODEV;
    return 0;
}
/* ECMT and driver transport locks held. Active is derived only from a qualified
 * contract snapshot, never from a user-supplied address or port bitmask. */
static inline int ht_pd_identity_collect_session(struct ht_charger_io *io,unsigned int active,struct ht_pd_identity *sample)
{
    struct ht_pd_identity next={0};
    ht_byte saved[HT_PD_IC_FIELDS],block[26],v;
    unsigned int i,j,port;
    int ret,restore;
    if(active>3)return -EINVAL;
    if(!active){*sample=next;return 0;}
    for(i=0;i<HT_PD_IC_FIELDS;i++){ret=ht_ec_read(io,ht_pd_ic_fields[i],&saved[i]);if(ret)return ret;}
    for(i=0;i<16;i++){ret=ht_ec_read(io,0x9000+i,&v);if(ret)return ret;if(v)return -EBUSY;}
    ret=ht_pd_ic_set(io,0,1);if(ret)goto out;
    ret=ht_ec_read(io,0x900e,&v);if(ret)goto out;if(v){ret=-EPROTO;goto out;}
    ret=ht_pd_ic_set(io,2,1);if(ret)goto out;
    for(port=0;port<2;port++){
        if(!(active&(1U<<port)))continue;
        ret=ht_pd_ic_block(io,port,3,block);if(ret)goto out;
        for(j=0;j<2;j++){
            ret=ht_pd_ic_block(io,port,0x48+j,block);if(ret)goto out;
            for(i=0;i<25;i++)(j ? next.cable[port]:next.sop[port])[i]=block[i+1];
        }
        ret=ht_pd_ic_block(io,port,0x74,block);if(ret)goto out;
        for(i=0;i<4;i++)next.alert[port][i]=block[i+1];
    }
out:
    restore=ht_ec_restore_fields(io,ht_pd_ic_fields,saved,HT_PD_IC_FIELDS);
    if(restore)return -EUCLEAN;
    if(!ret)*sample=next;
    return ret;
}
static inline int ht_pd_identity_collect(struct ht_charger_io *io,unsigned int active,struct ht_pd_identity *sample)
{
    ht_ec_begin(io,HT_PD_IC_BUDGET_US);
    return ht_ec_end(io,ht_pd_identity_collect_session(io,active,sample));
}
/* Read-only received-PD extended registers (TI host-interface layout of the
 * sibling TPS65987: 0x41 PD3 status, 0x42 PD3 configuration, 0x76 RX SCEDB,
 * 0x78 RX SDB). Same pointer-and-read operation 4; never a 4CC or write to the
 * controller. The register's own length byte is reported: 0 means the register
 * is not implemented, a full length of zeros means nothing was received. */
#define HT_PD_EXT_REGS 4
static const ht_byte ht_pd_ext_regs[HT_PD_EXT_REGS]={0x41,0x42,0x76,0x78};
struct ht_pd_extended {ht_byte length[2][HT_PD_EXT_REGS],data[2][HT_PD_EXT_REGS][25];unsigned int ports;};
static inline int ht_pd_ic_raw(struct ht_charger_io *io,unsigned int port,ht_byte reg,ht_byte *length,ht_byte *data)
{
    ht_byte status,out[26];
    unsigned int i;
    int ret;
    if(port>1 || (reg!=0x41 && reg!=0x42 && reg!=0x76 && reg!=0x78))return -EPERM;
    ret=ht_pd_ic_set(io,1,port ? 0x48:0x40);if(ret)return ret;
    ret=ht_pd_ic_set(io,3,26);if(ret)return ret;
    ret=ht_pd_ic_set(io,0x10,reg);if(ret)return ret;
    ret=ht_pd_ic_set(io,4,4);if(ret)return ret;
    ret=ht_ec_read(io,0x9004,&status);if(ret)return ret;if(status!=0x80)return -EIO;
    ret=ht_ec_read(io,0x9001,&status);if(ret)return ret;if(status)return -EPROTO;
    for(i=0;i<26;i++){ret=ht_ec_get(io,0x40+i,&out[i]);if(ret)return ret;}
    if(out[0]>25)return -EPROTO;
    *length=out[0];
    for(i=0;i<25;i++)data[i]=i<out[0] ? out[i+1]:0;
    return 0;
}
static inline int ht_pd_extended_collect_session(struct ht_charger_io *io,unsigned int active,struct ht_pd_extended *sample)
{
    struct ht_pd_extended next={0};
    ht_byte saved[HT_PD_IC_FIELDS],block[26],v;
    unsigned int i,j,port;
    int ret,restore;
    if(active>3)return -EINVAL;
    next.ports=active;
    if(!active){*sample=next;return 0;}
    for(i=0;i<HT_PD_IC_FIELDS;i++){ret=ht_ec_read(io,ht_pd_ic_fields[i],&saved[i]);if(ret)return ret;}
    for(i=0;i<16;i++){ret=ht_ec_read(io,0x9000+i,&v);if(ret)return ret;if(v)return -EBUSY;}
    ret=ht_pd_ic_set(io,0,1);if(ret)goto out;
    ret=ht_ec_read(io,0x900e,&v);if(ret)goto out;if(v){ret=-EPROTO;goto out;}
    ret=ht_pd_ic_set(io,2,1);if(ret)goto out;
    for(port=0;port<2;port++){
        if(!(active&(1U<<port)))continue;
        ret=ht_pd_ic_block(io,port,3,block);if(ret)goto out;   /* requires APP mode */
        for(j=0;j<HT_PD_EXT_REGS;j++){
            ret=ht_pd_ic_raw(io,port,ht_pd_ext_regs[j],&next.length[port][j],next.data[port][j]);if(ret)goto out;
        }
    }
out:
    restore=ht_ec_restore_fields(io,ht_pd_ic_fields,saved,HT_PD_IC_FIELDS);
    if(restore)return -EUCLEAN;
    if(!ret)*sample=next;
    return ret;
}
static inline int ht_pd_extended_collect(struct ht_charger_io *io,unsigned int active,struct ht_pd_extended *sample)
{
    ht_ec_begin(io,HT_PD_IC_BUDGET_US);
    return ht_ec_end(io,ht_pd_extended_collect_session(io,active,sample));
}

#endif
