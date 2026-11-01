/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef ZENBOOK_EEPROM_H
#define ZENBOOK_EEPROM_H
#include "healthytable_core.h"
#define HT_EEPROM_REPLY_MAX 1024
#define HT_EEPROM_FRAME_MAX 264
static inline bool ht_eeprom_ready(int status,unsigned int version)
{
    return !status && version<=0x7fffffff;
}
/* Original E5 helper checks5a/a5 and consumes9+byte6 bytes. Validate the
 * actual reply bound: its fixed256-byte copy could otherwise over-read. */
static inline int ht_eeprom_frame(const ht_byte *bytes,unsigned int size,unsigned int *length)
{
    unsigned int frame;
    if (!bytes || !length)return -EINVAL;
    *length=0;
    if (size>HT_EEPROM_REPLY_MAX)return -EOVERFLOW;
    if (size==4 && bytes[0]==0xfe && bytes[1]==0xff && bytes[2]==0xff && bytes[3]==0xff)
        return -EOPNOTSUPP;
    if (size<7)return -EMSGSIZE;
    if (bytes[0]!=0x5a || bytes[1]!=0xa5)return -ENODATA;
    frame=9U+bytes[6];
    if (frame>size)return -EMSGSIZE;
    *length=frame;
    return 0;
}
#endif
