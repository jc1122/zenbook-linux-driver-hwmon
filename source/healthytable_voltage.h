/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef HEALTHYTABLE_VOLTAGE_H
#define HEALTHYTABLE_VOLTAGE_H
#include "healthytable_core.h"

/* CPU-reported P-state voltage: MSR_PERF_STATUS[47:32] / 2^13 volts.
 * A read-only report, not a motherboard ADC or voltage-control interface.
 * Qualification is restricted to the driver's exact Intel/DMI model. */
static inline int ht_perf_status_mv(ht_time status,long *millivolts)
{
    unsigned int code=(unsigned int)((status>>32)&0xffff);
    unsigned int mv=(code*1000U+4096U)/8192U;
    if (!code || code==0xffff || mv<200 || mv>2000) return -ENODATA;
    *millivolts=mv;
    return 0;
}
#endif
