/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef HEALTHYTABLE_FREQUENCY_H
#define HEALTHYTABLE_FREQUENCY_H
#include "healthytable_core.h"

/* The qualified Intel source uses PERF_STATUS[14:8] or TURBO_RATIO_LIMIT[7:0]
 * multiplied by the reference clock. Native CPUID.16H supplies that clock
 * without the original driver's write to the overclocking mailbox. */
static inline int ht_ratio_mhz(ht_time status, bool maximum,
                              unsigned int reference, unsigned int *ratio,
                              unsigned int *mhz)
{
    unsigned int value=maximum ? (unsigned int)(status&0xff) :
                                (unsigned int)((status>>8)&0x7f);
    if (!reference || reference>1000) return -ENODATA;
    if (!value || (maximum && value==0xff)) return -ENODATA;
    *ratio=value;
    *mhz=value*reference;
    return 0;
}
#endif
