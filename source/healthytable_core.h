/* SPDX-License-Identifier: MIT */
#ifndef ZENBOOK_HEALTHYTABLE_CORE_H
#define ZENBOOK_HEALTHYTABLE_CORE_H
#ifdef __KERNEL__
#include <linux/errno.h>
#include <linux/types.h>
typedef u8 ht_byte;
typedef u64 ht_time;
#else
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
typedef uint8_t ht_byte;
typedef uint64_t ht_time;
#endif

struct ht_io {
    ht_byte (*status)(void *);
    ht_byte (*data)(void *);
    void (*command)(void *, ht_byte);
    void (*write)(void *, ht_byte);
    ht_time (*now_us)(void *);
    void (*pause)(void *);
    void *ctx;
    /* Zero is an unqualified protocol fixture. The .301 native device uses5:
     * its actual DD switch contains only1..5 and81..85, with a silent default. */
    unsigned int max_dd_bank;
    /* Absolute now_us() bound for every ht_wait while an EC-broker session is
     * open (0 = none). Set and cleared only by the session helpers. */
    ht_time limit_us;
};

static inline bool ht_allowed(ht_byte cmd, const ht_byte *p, size_t n)
{
    if (cmd == 0xbb && n == 1)
        return p[0] == 3 || p[0] == 4 || p[0] == 0x10 || p[0]==0x11 ||
               (p[0] >= 0x12 && p[0] <= 0x3f) || p[0] == 0x50 || p[0] == 0x51 || p[0]==0x52;
    if (cmd==0xde && n==2)
        return (p[0]==4 && (p[1]==1 || p[1]==2 || p[1]==0x51 || p[1]==0x53 ||
                            p[1]==0x60 || p[1]==0x61 || p[1]==0x62 || p[1]==0x63 || p[1]==0x64 || p[1]==0x71 || p[1]==0x72)) ||
               ((p[0]==1 || p[0]==5 || p[0]==3 || (p[0]>=8 && p[0]<=38)) && p[1]==0) ||
               (p[0]==255 && (p[1]==2 || p[1]==4 || p[1]==13 || p[1]==14 || p[1]==20 || p[1]==31)) ||
               (p[0]==2 && p[1]==0x23);
    if (cmd != 0xdd || n != 3) return false;
    if (p[0] == 1 && p[2] == 0)
        return p[1] == 0 || p[1] == 1 || p[1] == 2 || p[1] == 3 ||
               (p[1] >= 0x10 && p[1] <= 0x1a) ||
               (p[1] >= 0x20 && p[1] <= 0x31) ||
               (p[1] >= 0x34 && p[1] <= 0x43) ||
               (p[1] >= 0x48 && p[1] <= 0x57) ||
               p[1]>=0x5b;
    if (p[0]==0x81 && p[1]==0x5a && (p[2]==0x80 || p[2]==0x10)) return true;
    if (p[0] == 3 && p[1] == 1 && p[2] == 0) return true;
    if (p[0] == 5 && p[2] == 1) return p[1] >= 2 && p[1] <= 13;
    if (p[0] == 6 && p[2] == 0)
        return p[1] == 0 || p[1]==1 || p[1]==0x27 || (p[1] >= 2 && p[1] <= 0x26) ||
               (p[1] >= 0x28 && p[1] <= 0x34) ||
               (p[1] >= 0x37 && p[1] <= 0x3e) || p[1] == 0x41 || p[1] == 0x42 ||
               (p[1] >= 0x47 && p[1] <= 0x4a);
    if (p[0]==0x86)
        return (p[2]==0 && (p[1]==1 || p[1]==0x27 || p[1]==0x28)) ||
               p[1]==0x35 ||
               (p[1]==0x36 && p[2]<=1);
    if (p[0]==0x87 && p[1]==9 && (p[2]==5 || p[2]==0x85)) return true;
    if (p[0] == 0x02)
        return p[2] == 0 && (p[1] <= 5 || p[1] == 0x10 || p[1] == 0x11 || p[1] == 0x12 || p[1]==0x13 ||
                            p[1] == 0x30 || p[1] == 0x31 ||
                            p[1] == 0x32 || p[1] == 0x33 || p[1] == 0x34 || p[1]==0x35 || p[1]==0x38 || p[1]==0x39);
    if (p[0]==4 && p[2]==0)
        return p[1]==6 || p[1]==7 || p[1]==8 || p[1]==0x0b || p[1]==0x0c || p[1]==0x0f;
    return p[0] == 0x82 && ((p[1] == 0x11 && p[2] >= 1 && p[2] <= 5) ||
                           (p[1] == 0x31 && p[2] <= 1) ||
                           p[1] == 0x35);
}

static inline int ht_wait(struct ht_io *io, ht_byte mask, bool set, ht_time end)
{
    if (io->limit_us && end > io->limit_us) end = io->limit_us;
    do {
        ht_byte s = io->status(io->ctx);
        if (s == 255) return -ENODEV;
        if (((s & mask) != 0) == set) return 0;
        io->pause(io->ctx);
    } while (io->now_us(io->ctx) < end);
    return -ETIMEDOUT;
}

static inline int ht_xfer(struct ht_io *io, ht_byte cmd, const ht_byte *p,
                          size_t n, ht_byte *answer)
{
    ht_time end;
    ht_byte s;
    size_t i;
    int ret;
    if (!ht_allowed(cmd, p, n)) return -EPERM;
    if (cmd==0xdd && io->max_dd_bank && (p[0]&0x7f)>io->max_dd_bank)
        return -EOPNOTSUPP;
    if ((cmd==0xbb || (cmd==0xdd && (p[0]&0x80)==0) ||
         (cmd==0xde && (p[0]==3 || (p[0]>=8 && p[0]<=38)))) != (answer!=NULL)) return -EINVAL;
    s = io->status(io->ctx);
    if (s == 255) return -ENODEV;
    if (s & 1) return -EBUSY;
    end = io->now_us(io->ctx) + 500000;
    ret = ht_wait(io, 2, false, end);
    if (ret) return ret;
    io->command(io->ctx, 255);
    ret = ht_wait(io, 2, false, end);
    if (ret) return ret;
    io->command(io->ctx, cmd);
    for (i = 0; i < n; i++) {
        ret = ht_wait(io, 2, false, end);
        if (ret) return ret;
        io->write(io->ctx, p[i]);
    }
    ret = ht_wait(io, 2, false, end);
    if (ret || !answer) return ret;
    ret = ht_wait(io, 1, true, end);
    if (!ret) *answer = io->data(io->ctx);
    return ret;
}

static inline int ht_read(struct ht_io *io, ht_byte selector, ht_byte *answer)
{
    const ht_byte p[] = {0x02, selector, 0};
    return ht_xfer(io, 0xdd, p, 3, answer);
}

static inline int ht_write(struct ht_io *io, ht_byte selector, ht_byte value)
{
    const ht_byte p[] = {0x82, selector, value};
    return ht_xfer(io, 0xdd, p, 3, NULL);
}

static inline int ht_bank(struct ht_io *io, ht_byte bank, ht_byte selector, ht_byte *answer)
{
    const ht_byte p[] = {bank, selector, bank == 5 ? 1 : 0};
    return ht_xfer(io, 0xdd, p, 3, answer);
}

/* EC register words are little-endian; recheck the high byte across rollover. */
static inline int ht_word(struct ht_io *io, ht_byte bank, ht_byte low, long *value)
{
    unsigned int i;
    for (i = 0; i < 3; i++) {
        ht_byte hi, lo, check;
        int ret = ht_bank(io, bank, low + 1, &hi);
        if (!ret) ret = ht_bank(io, bank, low, &lo);
        if (!ret) ret = ht_bank(io, bank, low + 1, &check);
        if (ret) return ret;
        if (hi != check) continue;
        *value = ((long)hi << 8) | lo;
        return 0;
    }
    return -EAGAIN;
}

static inline long ht_signed_word(long value)
{
    return value >= 32768 ? value - 65536 : value;
}

static inline int ht_dword(struct ht_io *io, ht_byte bank, ht_byte low, long *value)
{
    unsigned int attempt, i;
    for (attempt=0; attempt<3; attempt++) {
        ht_byte bytes[4], check;
        int ret=0;
        for (i=4; i>0 && !ret; i--) ret=ht_bank(io,bank,low+i-1,&bytes[i-1]);
        if (!ret) ret=ht_bank(io,bank,low+3,&check);
        if (ret) return ret;
        if (check!=bytes[3]) continue;
        *value=(long)(((ht_time)bytes[3]<<24) | ((ht_time)bytes[2]<<16) |
                      ((ht_time)bytes[1]<<8) | bytes[0]);
        return 0;
    }
    return -EAGAIN;
}

static inline int ht_temperature(long raw, bool battery, long *mc)
{
    if (battery) {
        if (raw < 2331 || raw > 3731) return -ENODATA;
        *mc = raw * 100 - 273150; /* SBS tenths kelvin -> hwmon millidegrees C. */
    } else {
        if (raw <= 0 || raw > 125) return -ENODATA;
        *mc = raw * 1000;
    }
    return 0;
}

static inline int ht_manual(struct ht_io *io, ht_byte duty)
{
    ht_byte mode = 255;
    int ret;
    ret = ht_write(io, 0x31, 1);
    if (!ret) ret = ht_write(io, 0x35, duty);
    if (!ret) ret = ht_read(io, 0x31, &mode);
    return !ret && mode != 1 ? -EIO : ret;
}

static inline int ht_identify(struct ht_io *io)
{
    const ht_byte p[] = {0x50};
    ht_byte version = 0, count = 0;
    int ret = ht_xfer(io, 0xbb, p, 1, &version);
    if (ret) return ret;
    if (version != 15) return -ENODEV;
    ret = ht_read(io, 0x30, &count);
    if (ret) return ret;
    return count == 1 ? 0 : -ENODEV;
}

static inline int ht_rpm(struct ht_io *io, long *rpm)
{
    unsigned int i;
    for (i = 0; i < 3; i++) {
        ht_byte hi, lo, check;
        int ret = ht_read(io, 0x34, &hi);
        if (!ret) ret = ht_read(io, 0x33, &lo);
        if (!ret) ret = ht_read(io, 0x34, &check);
        if (ret) return ret;
        if (hi != check) continue;
        *rpm = ((long)hi << 8) | lo;
        return *rpm <= 20000 ? 0 : -ERANGE;
    }
    return -EAGAIN;
}

/* Caller holds exclusive channel ownership; queued data can only be its own
 * incomplete reply. Initial probes and ordinary reads never drain output. */
static inline int ht_restore_owned(struct ht_io *io)
{
    ht_byte status = io->status(io->ctx), mode = 255;
    int ret;
    if (status == 255) return -ENODEV;
    if (status & 1) (void)io->data(io->ctx);
    ret = ht_write(io, 0x31, 0);
    if (!ret) ret = ht_read(io, 0x31, &mode);
    return !ret && mode != 0 ? -EIO : ret;
}

static inline int ht_full(struct ht_io *io)
{
    return ht_manual(io, 255);
}

static inline long ht_minimum_rpm(long baseline)
{
    return baseline / 2 > 500 ? baseline / 2 : 500;
}

static inline bool ht_fan_unsafe(int status,ht_byte mode,long rpm,long minimum)
{
    return status || mode!=1 || rpm<minimum;
}
#endif
