/* SPDX-License-Identifier: GPL-2.0-only */
/* Fixed recipes recovered from AsusWinIO64.dll, SHA in source-manifest.json.
 * No general EC/SMBus access, factory writes or clear-on-read commands. */
#ifndef ZENBOOK_TELEMETRY_H
#define ZENBOOK_TELEMETRY_H
#include "healthytable_core.h"
struct ht_field { const char *name; ht_byte bank, selector, width; };
static const struct ht_field ht_fields[] = {
    {"cpu_celsius",2,0,1}, {"gpu_celsius",2,3,1},
    {"board_sensor_count",2,0x10,1},
    {"battery_temperature_dK",1,0x34,2},
    {"battery_voltage_mV",1,0x36,2}, {"battery_current_mA_raw",1,0x38,2},
    {"battery_charge_current_mA",1,0x3c,2}, {"battery_charge_voltage_mV",1,0x3e,2},
    {"battery_remaining_mAh",1,0x40,2}, {"battery_full_mAh",1,0x42,2},
    {"battery_design_voltage_mV",1,0x2c,2}, {"battery_cycles",1,0x2e,2},
    {"battery_percent",1,0x30,2},
    {"battery_cell1_mV",1,0x48,2}, {"battery_cell2_mV",1,0x4a,2},
    {"battery_cell3_mV",1,0x4c,2}, {"battery_cell4_mV",1,0x4e,2},
    {"battery_manufacture_date_raw",1,0x54,2}, {"battery_serial_raw",1,0x28,2},
    {"battery_status_flags",1,1,1}, {"battery_timeout_flags",1,3,1},
    {"ac_status_flags",1,0,1}, {"lid_status_flags",3,1,1},
    {"adapter_config",6,0,1}, {"adapter_ADO_raw",6,0x26,1},
    {"adapter_charger_info",6,0x28,1},
    {"adapter_source_VID",6,0x29,2}, {"adapter_source_PID",6,0x2b,2},
    {"adapter_firmware",6,0x31,1}, {"adapter_hardware",6,0x32,1},
    {"adapter_temperature_raw",6,0x33,1}, {"adapter_status_flags",6,0x34,1},
    {"adapter_cable_PID",6,0x41,2},
    {"adapter_PDO1_raw",6,2,4}, {"adapter_PDO2_raw",6,6,4},
    {"adapter_PDO3_raw",6,0x0a,4}, {"adapter_PDO4_raw",6,0x0e,4},
    {"adapter_PDO5_raw",6,0x12,4}, {"adapter_PDO6_raw",6,0x16,4},
    {"adapter_PDO7_raw",6,0x1a,4}, {"adapter_contract_PDO_raw",6,0x1e,4},
    {"adapter_PDO_watts_raw",6,0x22,4}, {"adapter_source_XID",6,0x2d,4},
    {"adapter_cable_VID_raw",6,0x37,4}, {"adapter_cable_XID",6,0x3b,4},
    {"adapter_cable_other_raw",6,0x47,4},
};
#define HT_FIELDS (sizeof(ht_fields)/sizeof(ht_fields[0]))
struct ht_snapshot {
    long value[HT_FIELDS], board_celsius;
    unsigned int valid;
    ht_byte vendor, chip_id, chip_name[4], firmware[2];
    char manufacturer[12], battery_name[9];
    ht_time unavailable_mask, unsupported_mask;
    unsigned int last_field;
    bool static_loaded;
    long board[5];
    /* Input: skip the board-thermistor walk entirely (fault latched by the
     * caller after an unverified selector restore). Output: set when the
     * saved selector could not be written back and read back. */
    bool board_disabled, board_restore_failed;
};
/* A missing optional reply may leave its own late byte queued. Consume only
 * that owned reply and require a successful known fan-mode read to resync. */
/* Never acts on -EBUSY: callers also pass -EBUSY from a failed ECMT acquire
 * or a busy mailbox, when a queued byte may belong to firmware's own
 * transaction and must not be drained without ECMT. */
static inline int ht_optional_recover(struct ht_io *io, int ret)
{
    ht_byte st, mode;
    if (ret!=-ETIMEDOUT && ret!=-ENODATA) return ret;
    st=io->status(io->ctx);
    if (st==255 || (st&2)) return -EIO;
    if (st&1) (void)io->data(io->ctx);
    return ht_read(io,0x31,&mode);
}
/* L6: used only by the snapshot field loop, whose -EBUSY can come solely from
 * ht_xfer()'s "output byte already queued" check (plain 0x25c port reads, no
 * ECMT or mailbox). Under ht->lock that byte is a late reply to this driver's
 * own request (port use by AML is unverified, I6, as for the -ETIMEDOUT
 * drain). Drain it once and resync; a reappearing byte returns -EBUSY. */
static inline int ht_stray_recover(struct ht_io *io)
{
    ht_byte st=io->status(io->ctx), mode;
    if (st==255 || (st&2)) return -EIO;
    if (!(st&1)) return -EBUSY;
    (void)io->data(io->ctx);
    return ht_read(io,0x31,&mode);
}
/* Write the board-thermistor selector and read it back, two attempts. */
static inline int ht_board_select_verified(struct ht_io *io, ht_byte selector)
{
    unsigned int attempt;
    int ret=-EIO;
    for (attempt=0; attempt<2; attempt++) {
        ht_byte check=0;
        ret=ht_write(io,0x11,selector);
        if (!ret) ret=ht_bank(io,2,0x11,&check);
        if (!ret && check!=selector) ret=-EIO;
        if (!ret) return 0;
    }
    return ret;
}
static inline int ht_field_read(struct ht_io *io, const struct ht_field *f, long *value)
{
    ht_byte b;
    int ret;
    if (f->width==4) return ht_dword(io,f->bank,f->selector,value);
    if (f->width==2) return ht_word(io,f->bank,f->selector,value);
    ret=ht_bank(io,f->bank,f->selector,&b);
    if (!ret) *value=b;
    return ret;
}
static inline int ht_string(struct ht_io *io, ht_byte first, unsigned int n, char *s)
{
    unsigned int i;
    for (i=0; i<n; i++) {
        ht_byte c;
        int ret=ht_bank(io,1,first+i,&c);
        if (ret) return ret;
        if (!c) break;
        if (c<32 || c>126) return -ENODATA;
        s[i]=(char)c;
    }
    s[i]=0;
    return i ? 0 : -ENODATA;
}
static inline int ht_snapshot_read(struct ht_io *io, struct ht_snapshot *s)
{
    unsigned int i;
    int ret;
    ht_byte b;
    s->valid=0; s->board_celsius=-1; s->unsupported_mask=0;
    for (i=0; i<HT_FIELDS; i++) {
        const struct ht_field *f=&ht_fields[i];
        s->last_field=i;
        s->value[i]=-1;
        if (io->max_dd_bank && f->bank>io->max_dd_bank) {
            s->unsupported_mask |= (ht_time)1<<i;
            continue;
        }
        if (s->unavailable_mask & ((ht_time)1<<i)) continue;
        /* Adapter is absent or firmware advertises no diagnostic support. */
        if (f->bank==6 && f->selector!=0 && s->value[23]<=0) continue;
        ret=ht_field_read(io,f,&s->value[i]);
        if (ret==-EBUSY) {
            /* A stray queued byte: drain once, then retry this field once. */
            int recovery=ht_stray_recover(io);
            if (recovery) return recovery;
            ret=ht_field_read(io,f,&s->value[i]);
            if (ret==-EBUSY) return ret;
        }
        if (ret) {
            int recovery=ht_optional_recover(io,ret);
            if (recovery) return recovery;
            s->value[i]=-1;
            s->unavailable_mask |= (ht_time)1<<i;
            continue;
        }
        if (!ret) s->valid++;
    }
    /* UP3404VA.301 uses one-based thermistor selectors. Zero is ignored by
     * firmware, which previously duplicated the prior channel and omitted DDR.
     * Preserve the caller's valid selection; default to the first if invalid. */
    for (i=0;i<5;i++) s->board[i]=-1;
    s->board_restore_failed=false;
    if (!s->board_disabled && s->value[2]>0 && s->value[2]<=5) {
        int restore;
        ht_byte selected;
        ret=ht_bank(io,2,0x11,&selected);
        if(ret)return ret;
        if(selected<1 || selected>5)selected=1;
        ret=0;
        for (i=0;i<(unsigned int)s->value[2];i++) {
            ret=ht_write(io,0x11,i+1);
            if (!ret) ret=ht_bank(io,2,0x12,&b);
            if (ret) break;
            if (b>0 && b<=125) s->board[i]=b;
        }
        /* Read the restored selector back (one retry) so a dropped write
         * cannot become the next refresh's "original" selection (L3). */
        restore=ht_board_select_verified(io,selected);
        if (restore) s->board_restore_failed=true;
        if (ret || restore) return ret ? ret : restore;
        s->board_celsius=s->board[0];
    }
    if (s->static_loaded) return 0;
    s->last_field=100;
    b=0x51; ret=ht_xfer(io,0xbb,&b,1,&s->vendor);
    if (!ret) { b=0x10; ret=ht_xfer(io,0xbb,&b,1,&s->chip_id); }
    for (i=0; !ret && i<4; i++) { b=0x12+i; ret=ht_xfer(io,0xbb,&b,1,&s->chip_name[i]); }
    for (i=0; !ret && i<2; i++) { b=3+i; ret=ht_xfer(io,0xbb,&b,1,&s->firmware[i]); }
    if (ret) {
        int recovery=ht_optional_recover(io,ret);
        if (recovery) return recovery;
        s->vendor=255; s->chip_id=255;
    }
    ret=ht_string(io,0x10,11,s->manufacturer);
    if (ret) { int recovery=ht_optional_recover(io,ret); if (recovery) return recovery; }
    if (ret) s->manufacturer[0]=0;
    ret=ht_string(io,0x20,8,s->battery_name);
    if (ret) { int recovery=ht_optional_recover(io,ret); if (recovery) return recovery; }
    if (ret) s->battery_name[0]=0;
    s->static_loaded=true;
    return 0;
}
#endif
