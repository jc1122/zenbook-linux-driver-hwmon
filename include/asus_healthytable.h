/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef ASUS_HEALTHYTABLE_H
#define ASUS_HEALTHYTABLE_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

/* Native Linux ABI version 1. The request/result schemas are documented JSON.
 * The returned string is allocated even for a provider error. Free it with
 * asus_ht_free(). Returns 0 for success, 1 for a JSON provider error, or -errno
 * for a local transport error, including -ETIMEDOUT when the bridge does not
 * finish within the bounded wait (60 s; the child is killed). The bridge runs
 * as an isolated interpreter with a fixed minimal environment. No shell or
 * implicit privilege elevation runs. For a non-root caller, names that need
 * privilege are forwarded to the system service org.zenbook.Hardware1 without
 * interactive authorisation: a polkit denial or an unavailable service is a
 * provider error with errno EACCES (return 1). Root callers keep the direct
 * in-process path. */
int asus_ht_call(const char *request_json, char **response_json);
void asus_ht_free(char *response_json);
unsigned int asus_ht_abi_version(void);
/* Read CPUID on the calling thread. Four unsigned EAX/EBX/ECX/EDX registers.
 * Returns 0 or -errno. Never enables CPUID or changes processor policy. */
int asus_ht_cpuid(uint32_t leaf, uint32_t subleaf, uint32_t registers[4]);

#ifdef __cplusplus
}
#endif
#endif
