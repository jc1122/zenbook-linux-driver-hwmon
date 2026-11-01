/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef ZENBOOK_POWER_H
#define ZENBOOK_POWER_H
#include "healthytable_core.h"

/* Intel 32-bit RAPL/PSYS energy counter, sampled power in microwatts.
 * Unit is 2^-energy_exponent joules. Unsigned subtraction handles one wrap.
 * Long gaps and zero/stopped counters are unavailable, never fabricated zero. */
static inline int ht_psys_uw(unsigned int previous,unsigned int sample,
                             ht_time elapsed_us,unsigned int energy_exponent,long *value)
{
    ht_time energy_nj,quotient,remainder;
    unsigned int delta=sample-previous;
    if (energy_exponent>31)return -EINVAL;
    if (elapsed_us<100000)return -EAGAIN;
    if (elapsed_us>30000000)return -ESTALE;
    /* At the accepted1000W ceiling, even one whole counter period must not
     * fit inside the interval. Otherwise additional wraps are ambiguous. */
    if (elapsed_us>=((1ULL<<(32-energy_exponent))*1000ULL))return -ESTALE;
    if (!delta)return -ENODATA;
    energy_nj=((ht_time)delta*1000000000ULL)>>energy_exponent;
    quotient=energy_nj/elapsed_us;remainder=energy_nj%elapsed_us;
    if (quotient>1000000)return -ERANGE;
    *value=quotient*1000+remainder*1000/elapsed_us;
    return *value ? 0 : -ENODATA;
}
/* The first read after a gap (never-initialized, stale or stopped counter) only
 * re-primes the sample. Callers may sleep this long once and sample again; a
 * second failure stays unavailable. Never applied to protocol/MSR errors. */
#define HT_ENERGY_REPRIME_MS 120
static inline int ht_energy_reprime(int ret)
{
    return ret==-ENODATA || ret==-ESTALE;
}
#endif
