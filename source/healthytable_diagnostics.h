/* SPDX-License-Identifier: MIT */
/* Fixed protocol15 diagnostic read recipes recovered from the original logger. */
#ifndef HEALTHYTABLE_DIAGNOSTICS_H
#define HEALTHYTABLE_DIAGNOSTICS_H
#include "healthytable_telemetry.h"
struct ht_diag_field { ht_byte command, bank, reg, width; };
static const struct ht_diag_field ht_diag_fields[]={
    {0xbb,80,0x50,1}, /* HealthyTableVersion */
    {0xbb,16,0x10,1}, /* ChipID */
    {0xbb,17,0x11,1}, /* LengthOfChipName */
    {0xbb,81,0x51,1}, /* ProjectInformation */
    {0xbb,82,0x52,1}, /* PlatformInformation */
    {0xdd,1,0x00,1}, /* PowerSource */
    {0xdd,1,0x01,1}, /* ECBatteryStatus */
    {0xdd,1,0x02,1}, /* ChargerStatus */
    {0xdd,1,0x03,1}, /* BatteryChargeErrorStatus */
    {0xdd,1,0x30,2}, /* RSOC */
    {0xdd,1,0x34,2}, /* BatteryTemperature */
    {0xdd,1,0x36,2}, /* Voltage */
    {0xdd,1,0x38,2}, /* Current */
    {0xdd,1,0x3a,2}, /* AverageCurrent */
    {0xdd,1,0x3c,2}, /* ChargeCurrent */
    {0xdd,1,0x3e,2}, /* ChargeVoltage */
    {0xdd,1,0x40,2}, /* RemainingCapacity */
    {0xdd,1,0x42,2}, /* FullChargeCapacity */
    {0xdd,1,0x48,2}, /* CellVoltage1 */
    {0xdd,1,0x4a,2}, /* CellVoltage2 */
    {0xdd,1,0x4c,2}, /* CellVoltage3 */
    {0xdd,1,0x4e,2}, /* CellVoltage4 */
    {0xdd,1,0x50,2}, /* BatteryStatus */
    {0xdd,1,0x52,2}, /* BatteryMode */
    {0xdd,1,0x54,2}, /* ManufactureDate */
    {0xdd,1,0x56,2}, /* RSOCofHealthCharge */
    {0xdd,2,0x00,1}, /* CPUTemperature1 */
    {0xdd,2,0x01,1}, /* CPUTemperature2 */
    {0xdd,2,0x02,1}, /* PCHTemperature */
    {0xdd,2,0x03,1}, /* GPUTemperature1 */
    {0xdd,2,0x04,1}, /* GPUTemperature2 */
    {0xdd,2,0x05,1}, /* STTTemperature */
    {0xdd,2,0x38,1}, /* CPUTDP */
    {0xdd,2,0x39,1}, /* ThermalSensorFailStatus */
    {0xdd,4,0x06,1}, /* RawDataFunctionStatus */
    {0xdd,4,0x07,1}, /* MBDesignPower */
    {0xdd,4,0x08,1}, /* SupportAdapterType */
    {0xdd,4,0x0b,1}, /* PDNotEnoughWattStatus */
    {0xdd,4,0x0c,1}, /* DCJackAdpaterIn */
    {0xdd,4,0x0f,1}, /* BatteryHealthState */
};
#define HT_DIAG_FIELDS (sizeof(ht_diag_fields)/sizeof(ht_diag_fields[0]))
struct ht_diag_fan { ht_byte mode, count, index, selection_raw, duty; long rpm; int duty_status; };
struct ht_diag_sample {
    long scalar[HT_DIAG_FIELDS];
    int scalar_status[HT_DIAG_FIELDS];
    ht_byte project[32], manufacturer[11], chip[4], board[5];
    int project_status, manufacturer_status, chip_status, board_status, vr_status, fan_status;
    ht_byte board_count, board_saved, vr_count;
    bool board_restored;
    /* Input: board selector fault latched by the driver; no selector walk. */
    bool board_disabled;
    struct ht_diag_fan fan;
};

static inline int ht_diag_bb(struct ht_io *io,ht_byte reg,ht_byte *value)
{
    return ht_xfer(io,0xbb,&reg,1,value);
}

static inline int ht_diag_fan_read(struct ht_io *io,struct ht_diag_fan *s)
{
    ht_byte mode,index;
    int ret=ht_read(io,0x31,&s->mode);
    if(!ret && s->mode>1)ret=-EPROTO;
    if(!ret)ret=ht_read(io,0x30,&s->count);
    if(!ret && s->count!=1)ret=-EOPNOTSUPP;
    s->index=0; /* Qualified single fixed RPM channel; raw selector is separate. */
    if(!ret)ret=ht_read(io,0x32,&s->selection_raw);
    if(!ret)ret=ht_rpm(io,&s->rpm);
    s->duty_status=-EOPNOTSUPP;
    /* .301 DD2/35 has no reply unless the DD2/31 manual gate is enabled. */
    if(!ret && s->mode==1) {
        s->duty_status=ht_read(io,0x35,&s->duty);
        if(!s->duty_status && (s->duty>254 || (s->duty&1)))s->duty_status=-EPROTO;
        if(s->duty_status && s->duty_status!=-EAGAIN)ret=s->duty_status;
    }
    if(!ret)ret=ht_read(io,0x32,&index);
    if(!ret && index!=s->selection_raw)ret=-EAGAIN;
    if(!ret)ret=ht_read(io,0x31,&mode);
    return !ret && mode!=s->mode ? -EAGAIN : ret;
}

/* Exclusive caller ownership has already been established. Drain only this
 * operation's possible late reply; restore only the saved board selector. */
static inline int ht_diag_board_restore(struct ht_io *io,ht_byte saved)
{
    unsigned int attempt;
    int ret=-EIO;
    for(attempt=0;attempt<2;attempt++) {
        ht_byte state=io->status(io->ctx),check=0;
        if(state==255) {ret=-ENODEV;continue;}
        if(state&1)(void)io->data(io->ctx);
        ret=ht_write(io,0x11,saved);
        if(!ret)ret=ht_read(io,0x11,&check);
        if(!ret && check!=saved)ret=-EIO;
        if(!ret)return 0;
    }
    return ret;
}

static inline int ht_diag_board_read(struct ht_io *io,struct ht_diag_sample *s)
{
    unsigned int i;
    ht_byte check=0,count=0;
    bool touched=false;
    int restore=0,ret;
    s->board_restored=true;
    /* Latched selector fault: report -EUCLEAN (the driver's latch code) and
     * do not touch selector 0x11 at all. */
    if(s->board_disabled) {s->board_count=0;return -EUCLEAN;}
    ret=ht_read(io,0x10,&s->board_count);
    if(!ret && s->board_count>5)ret=-EOPNOTSUPP;
    if(!ret && !s->board_count)return 0;
    if(!ret)ret=ht_read(io,0x11,&s->board_saved);
    if(!ret && (s->board_saved<1 || s->board_saved>5))ret=-EPROTO;
    for(i=0;!ret && i<s->board_count;i++) {
        touched=true;s->board_restored=false;
        ret=ht_write(io,0x11,i+1);
        if(!ret)ret=ht_read(io,0x11,&check);
        if(!ret && check!=i+1)ret=-EIO;
        if(!ret)ret=ht_read(io,0x12,&s->board[i]);
    }
    if(touched) {
        restore=ht_diag_board_restore(io,s->board_saved);
        s->board_restored=!restore;
    }
    if(!ret && !restore)ret=ht_read(io,0x10,&count);
    if(!ret && count!=s->board_count)ret=-EAGAIN;
    return restore ? restore : ret;
}

static inline int ht_diag_bytes(struct ht_io *io,ht_byte command,ht_byte first,
                               unsigned int count,ht_byte *out)
{
    ht_byte check;
    unsigned int i;
    int ret=0;
    for(i=0;!ret && i<count;i++)
        ret=command==0xbb ? ht_diag_bb(io,first+i,&out[i]) : ht_bank(io,1,first+i,&out[i]);
    for(i=0;!ret && i<count;i++) {
        ret=command==0xbb ? ht_diag_bb(io,first+i,&check) : ht_bank(io,1,first+i,&check);
        if(!ret && check!=out[i])ret=-EAGAIN;
    }
    return ret;
}

static inline int ht_diag_recover(struct ht_io *io,int ret)
{
    if(!ret || ret==-EAGAIN || ret==-EUCLEAN)return 0;
    return ht_optional_recover(io,ret);
}

static inline int ht_diag_collect(struct ht_io *io,struct ht_diag_sample *s)
{
    unsigned int i;
    ht_byte version=0,mode=255;
    int recovery,ret;
    /* True until the board walk actually runs and its restore fails, so an
     * early return (timeout, version, ownership, -EAGAIN) never reads as an
     * unverified selector restore. */
    s->board_restored=true;
    ret=ht_diag_bb(io,0x50,&version);
    if(!ret && (version!=15 || (io->max_dd_bank && io->max_dd_bank!=5)))ret=-EOPNOTSUPP;
    if(!ret)ret=ht_read(io,0x31,&mode);
    if(!ret && mode!=0)ret=-EBUSY;
    if(ret)return ret;
    for(i=0;i<HT_DIAG_FIELDS;i++) {
        const struct ht_diag_field *f=&ht_diag_fields[i];
        ht_byte byte;
        s->scalar[i]=0;
        if(f->command==0xbb) {
            ret=ht_diag_bb(io,f->bank,&byte);
            if(!ret)s->scalar[i]=byte;
        } else if(f->width==2)ret=ht_word(io,f->bank,f->reg,&s->scalar[i]);
        else {
            ret=ht_bank(io,f->bank,f->reg,&byte);
            if(!ret)s->scalar[i]=byte;
        }
        s->scalar_status[i]=ret;
        recovery=ht_diag_recover(io,ret);
        if(recovery)return recovery;
    }
    if(s->scalar_status[0] || s->scalar[0]!=15)return -EAGAIN;
    s->chip_status=ht_diag_bytes(io,0xbb,0x12,4,s->chip);
    recovery=ht_diag_recover(io,s->chip_status);
    if(recovery)return recovery;
    s->project_status=ht_diag_bytes(io,0xbb,0x20,32,s->project);
    recovery=ht_diag_recover(io,s->project_status);
    if(recovery)return recovery;
    s->manufacturer_status=ht_diag_bytes(io,0xdd,0x10,11,s->manufacturer);
    recovery=ht_diag_recover(io,s->manufacturer_status);
    if(recovery)return recovery;
    s->board_status=ht_diag_board_read(io,s);
    if(!s->board_restored)return s->board_status;
    recovery=ht_diag_recover(io,s->board_status);
    if(recovery)return recovery;
    s->vr_count=0;
    s->vr_status=ht_read(io,0x13,&s->vr_count);
    /* .301 implements no indexed VR temperature path; its count is zero. */
    if(!s->vr_status && s->vr_count)s->vr_status=-EOPNOTSUPP;
    if(s->vr_status!=-EOPNOTSUPP) {
        recovery=ht_diag_recover(io,s->vr_status);
        if(recovery)return recovery;
    }
    s->fan_status=ht_diag_fan_read(io,&s->fan);
    recovery=ht_diag_recover(io,s->fan_status);
    if(recovery)return recovery;
    ret=ht_diag_bb(io,0x50,&version);
    if(!ret && version!=15)ret=-EAGAIN;
    if(!ret)ret=ht_read(io,0x31,&mode);
    if(!ret && mode!=0)ret=-EBUSY;
    return ret;
}
#endif
