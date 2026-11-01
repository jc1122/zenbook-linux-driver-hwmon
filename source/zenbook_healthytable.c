// SPDX-License-Identifier: GPL-2.0-only
/* Native hwmon bridge for the qualified UP3404VA.301 HealthyTable.
 * Load/probe and normal sensor reads do not change fan policy. Only the
 * qualified automatic/full/manual controls are exposed, root-writable.
 */
#include <linux/delay.h>
#include <linux/dmi.h>
#include <linux/hwmon.h>
#include <linux/io.h>
#include <linux/ioport.h>
#include <linux/jiffies.h>
#include <linux/ktime.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/platform_device.h>
#include <linux/pm.h>
#include <linux/slab.h>
#include <linux/workqueue.h>
#include <linux/version.h>
#if LINUX_VERSION_CODE >= KERNEL_VERSION(6,12,0)
#include <linux/unaligned.h>
#else
#include <asm/unaligned.h>
#endif
#include <linux/platform_data/x86/asus-wmi.h>
#include "healthytable_history.h"
#include "healthytable_oem.h"
#include "healthytable_voltage.h"
#include "healthytable_frequency.h"
#include "healthytable_pd.h"
#include "healthytable_power.h"
#include "healthytable_charger.h"
#include "healthytable_gauge.h"
#include "healthytable_gauge_block.h"
#include "healthytable_sbs.h"
#include "healthytable_pd_identity.h"
#include "healthytable_eeprom.h"
#include "healthytable_diagnostics.h"
#include <asm/msr.h>
#include <asm/processor.h>
#include <linux/smp.h>
#include <linux/acpi.h>
#include <linux/cred.h>
#include <linux/sched.h>

#define DRIVER "zenbook_healthytable"
/* L2: one rate-limited notice per privileged write path (per call site),
 * with the operation, outcome and calling task; never payload secrets. */
#define ht_audit(ht, fmt, ...) \
    dev_notice_ratelimited((ht)->dev, fmt " (uid %u pid %d comm %s)\n", ##__VA_ARGS__, \
        from_kuid(&init_user_ns, current_uid()), task_pid_nr(current), current->comm)
#define PORT_DATA 0x25c
#define PORT_STATUS 0x25d
#ifndef ASUS_WMI_MGMT_GUID
/* Older kernels keep this established management GUID private to asus-wmi. */
#define ASUS_WMI_MGMT_GUID "97845ED0-4E6D-11DE-8A39-0800200C9A66"
#endif

struct ht_firmware_reply { int status; u32 raw; };
struct ht_firmware_recipe { const char *name; u32 method,device,selector; };
static const struct ht_firmware_recipe ht_firmware_queries[]={
    {"eeprom_support",ASUS_WMI_METHODID_DSTS,0x60059,0},
    /* Recovered read-version selector, not an EEPROM write operation. */
    {"eeprom_version",ASUS_WMI_METHODID_DEVS,0x60059,0xe0},
    {"sensor_mask",ASUS_WMI_METHODID_DSTS,0x60068,0},
};

struct ht_frequency_sample {
    u32 reference;
    u64 status[2];
    unsigned int ratio[2],mhz[2];
    int error,field_error[2];
};

/* L4: minimum age of a cached unprivileged MSR/AML/EC-diagnostic sample. */
#define HT_SAMPLE_CACHE (HZ)

struct zenbook_ht {
    struct device *dev;
    struct ht_io io;
    struct mutex lock;
    struct delayed_work watchdog;
    bool manual_owned;
    /* THIS_MODULE reference held exactly while manual_owned (H2), so rmmod
     * cannot unload the driver with the fan in manual mode. */
    bool module_ref;
    /* Set under lock once teardown starts; refuses writes and watchdog re-arm. */
    bool removing;
    /* Board-thermistor selector restore could not be verified (L3); the
     * selector walk stays disabled until the module is reloaded. */
    bool board_faulted;
    bool rpm_valid;
    unsigned long updated;
    long rpm;
    long minimum_rpm;
    long requested_pwm;
    struct ht_snapshot snapshot;
    unsigned long telemetry_updated;
    bool telemetry_valid;
    bool supported_temp[8], supported_in[7], supported_curr[2];
    u64 oem_nonce;
    unsigned int oem_op,oem_length;
    int oem_status;
    long oem_value;
    ht_byte oem_data[HT_EEPROM_REPLY_MAX];
    ht_byte pd_data[HT_PD_SIZE];
    unsigned long pd_updated;
    bool pd_valid;
    ht_byte pd_sources[HT_PD_SOURCES_SIZE];
    unsigned long pd_sources_updated;
    bool pd_sources_valid;
    bool psys_supported,psys_initialized,psys_valid;
    u32 psys_energy;
    unsigned int psys_exponent;
    u64 psys_time_us;
    long psys_power_uw;
    bool package_supported,package_initialized,package_valid;
    u32 package_energy,package_before;
    unsigned int package_exponent;
    u64 package_time_us,package_elapsed_us;
    long package_power_uw;
    struct ht_charger_sample charger;
    unsigned long charger_updated;
    bool charger_sampled,charger_faulted;
    int charger_status;
    struct ht_charger_extra charger_extra;
    unsigned long extra_updated;
    bool extra_sampled;
    int extra_status;
    struct ht_gauge_sample gauge_sample;
    struct ht_gauge_full_sample gauge_extra;
    struct ht_gauge_full_lifetime gauge_lifetime;
    unsigned long gauge_updated,lifetime_updated;
    bool gauge_sampled,lifetime_sampled;
    int gauge_status,lifetime_status;
    unsigned long gauge_extra_updated;
    bool gauge_extra_sampled;
    int gauge_extra_status;
    struct ht_sbs_sample sbs;
    unsigned long sbs_updated;
    bool sbs_sampled;
    int sbs_status;
    struct ht_sbs_trace sbs_trace,sbs_last_failure;
    u64 sbs_attempts,sbs_successes,sbs_failures,sbs_trace_time,sbs_failure_time;
    u64 sbs_retries,sbs_recovered_refreshes;
    struct ht_gauge_strings gauge_strings;
    unsigned long gauge_identity_updated;
    bool gauge_identity_sampled;
    int gauge_identity_status;
    struct ht_pd_identity identity;
    ht_byte identity_contract[HT_PD_SIZE];
    unsigned long identity_updated;
    bool identity_sampled;
    int identity_status;
    struct ht_pd_extended extended;
    ht_byte extended_contract[HT_PD_SIZE];
    unsigned long extended_updated;
    bool extended_sampled;
    int extended_status;
    struct ht_firmware_reply firmware_reply[ARRAY_SIZE(ht_firmware_queries)];
    u64 eeprom_buffer_calls,eeprom_buffer_rejections;
    /* L4 caches. usb_connector_types: built at probe and on reprobe. */
    char *upc_cache;
    struct ht_frequency_sample frequency;
    unsigned long frequency_updated;
    bool frequency_sampled;
    int frequency_status;
    long cpu_mv;
    unsigned long cpu_mv_updated;
    bool cpu_mv_sampled;
    int cpu_mv_status;
    struct ht_diag_sample diag;
    u64 diag_started_us,diag_duration_us;
    unsigned long diag_updated;
    bool diag_sampled;
    int diag_status;
};

static ht_byte port_status(void *ctx) { return inb(PORT_STATUS); }
static ht_byte port_data(void *ctx) { return inb(PORT_DATA); }
static void port_command(void *ctx, ht_byte value) { outb(value, PORT_STATUS); }
static void port_write(void *ctx, ht_byte value) { outb(value, PORT_DATA); }
static ht_time port_now(void *ctx) { return ktime_to_us(ktime_get()); }
static void port_pause(void *ctx) { usleep_range(100, 200); }

static int refresh_rpm(struct zenbook_ht *ht, bool force)
{
    int ret;
    if (!force && ht->rpm_valid && time_before(jiffies, ht->updated + HZ))
        return 0;
    ret = ht_rpm(&ht->io, &ht->rpm);
    ht->rpm_valid = !ret;
    if (!ret) ht->updated = jiffies;
    return ret;
}

/* Caller holds ht->lock. Take ownership of restoration plus a module
 * reference; fails (no state change) once the module is going away. */
static int ht_own_manual(struct zenbook_ht *ht)
{
    if (!ht->module_ref) {
        if (!try_module_get(THIS_MODULE)) return -ENODEV;
        ht->module_ref = true;
    }
    ht->manual_owned = true;
    return 0;
}

/* Caller holds ht->lock. Automatic mode is verified (or teardown gives up). */
static void ht_release_manual(struct zenbook_ht *ht)
{
    ht->manual_owned = false;
    if (ht->module_ref) {
        ht->module_ref = false;
        module_put(THIS_MODULE);
    }
}

static int return_auto(struct zenbook_ht *ht)
{
    int ret = ht_restore_owned(&ht->io);
    if (!ret) ht_release_manual(ht);
    ht->rpm_valid = false;
    return ret;
}

static void fan_watchdog(struct work_struct *work)
{
    struct zenbook_ht *ht = container_of(to_delayed_work(work), struct zenbook_ht, watchdog);
    ht_byte mode = 255;
    int ret;
    mutex_lock(&ht->lock);
    /* Teardown owns the final restoration and must not see a re-queue. */
    if (!ht->manual_owned || ht->removing) goto out;
    ret = ht_read(&ht->io, 0x31, &mode);
    if (!ret && mode == 0) {
        ht_release_manual(ht);
        ht->rpm_valid = false;
        goto out;
    }
    if (!ret) ret = refresh_rpm(ht, true);
    if (ht_fan_unsafe(ret,mode,ht->rpm,ht->minimum_rpm)) {
        dev_warn_ratelimited(ht->dev, "Manual fan monitoring failed; restoring automatic mode\n");
        ret = return_auto(ht);
        if (ret) dev_err_ratelimited(ht->dev, "Automatic restoration failed: %d\n", ret);
    }
    if (ht->manual_owned) schedule_delayed_work(&ht->watchdog, HZ);
out:
    mutex_unlock(&ht->lock);
}

static int refresh_telemetry(struct zenbook_ht *ht)
{
    int ret;
    if (ht->manual_owned) return -EBUSY;
    if (ht->telemetry_valid && time_before(jiffies, ht->telemetry_updated + 2*HZ)) return 0;
    ht->snapshot.board_disabled=ht->board_faulted;
    ret=ht_snapshot_read(&ht->io,&ht->snapshot);
    if (ht->snapshot.board_restore_failed && !ht->board_faulted) {
        /* Never adopt an unverified selector as the next "original". */
        ht->board_faulted=true;
        dev_err(ht->dev,"Board thermistor selector restore not verified after retry (%d); board temperature walk disabled until reload\n",ret);
    }
    ht->telemetry_valid=!ret;
    if (!ret) ht->telemetry_updated=jiffies;
    return ret;
}

static ssize_t ec_telemetry_show(struct device *dev, struct device_attribute *attr, char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    unsigned int i;
    int ret, len=0;
    mutex_lock(&ht->lock);
    ret=refresh_telemetry(ht);
    if (ret) goto out;
    len=sysfs_emit(buf,"{\"protocol\":15,\"vendor\":%u,\"chip_id\":%u,\"chip_name_raw\":[%u,%u,%u,%u],\"firmware_raw\":[%u,%u],\"board_celsius\":%ld",
        ht->snapshot.vendor,ht->snapshot.chip_id,
        ht->snapshot.chip_name[0],ht->snapshot.chip_name[1],ht->snapshot.chip_name[2],ht->snapshot.chip_name[3],
        ht->snapshot.firmware[0],ht->snapshot.firmware[1],ht->snapshot.board_celsius);
    for (i=0;i<HT_FIELDS;i++) len+=sysfs_emit_at(buf,len,",\"%s\":%ld",ht_fields[i].name,ht->snapshot.value[i]);
    len+=sysfs_emit_at(buf,len,",\"unavailable_mask\":%llu",ht->snapshot.unavailable_mask);
    len+=sysfs_emit_at(buf,len,",\"unsupported_mask\":%llu,\"max_dd_bank\":%u",
        ht->snapshot.unsupported_mask,ht->io.max_dd_bank);
    len+=sysfs_emit_at(buf,len,",\"board_celsius_all\":[%ld,%ld,%ld,%ld,%ld]",
        ht->snapshot.board[0],ht->snapshot.board[1],ht->snapshot.board[2],ht->snapshot.board[3],ht->snapshot.board[4]);
    len+=sysfs_emit_at(buf,len,"}\n");
out:
    mutex_unlock(&ht->lock);
    return ret ? ret : len;
}
static DEVICE_ATTR_RO(ec_telemetry);

static ssize_t fan_diagnostics_show(struct device *dev,struct device_attribute *attr,char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    struct ht_diag_fan fan={0};
    int ret;
    mutex_lock(&ht->lock);
    /* Independent non-mutating fan reads remain available during manual mode. */
    ret=ht_diag_fan_read(&ht->io,&fan);
    mutex_unlock(&ht->lock);
    if(ret)return ret;
    if(fan.duty_status)
        return sysfs_emit(buf,"{\"schema\":2,\"count\":%u,\"index\":%u,\"selection_raw\":%u,\"mode_raw\":%u,\"rpm\":%ld,\"duty_status\":%d,\"duty_code\":null,\"duty_code_maximum\":254}\n",
            fan.count,fan.index,fan.selection_raw,fan.mode,fan.rpm,fan.duty_status);
    return sysfs_emit(buf,"{\"schema\":2,\"count\":%u,\"index\":%u,\"selection_raw\":%u,\"mode_raw\":%u,\"rpm\":%ld,\"duty_status\":0,\"duty_code\":%u,\"duty_code_maximum\":254}\n",
        fan.count,fan.index,fan.selection_raw,fan.mode,fan.rpm,fan.duty);
}
static DEVICE_ATTR_RO(fan_diagnostics);

static int diagnostic_bytes(char *buf,int len,const char *key,int status,
                            const ht_byte *bytes,unsigned int count)
{
    unsigned int i;
    len+=sysfs_emit_at(buf,len,",\"%s\":{\"status\":%d,\"raw\":[",key,status);
    if(!status)
        for(i=0;i<count;i++)len+=sysfs_emit_at(buf,len,"%s%u",i ? "," : "",bytes[i]);
    return len+sysfs_emit_at(buf,len,"]}");
}

static ssize_t ec_diagnostics_show(struct device *dev,struct device_attribute *attr,char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    const struct ht_diag_sample *s=&ht->diag;
    unsigned int i;
    int ret,len=0;
    mutex_lock(&ht->lock);
    if(ht->manual_owned) {ret=-EBUSY;goto out;}
    /* L4: one EC burst per second at most, errors included. The existing
     * started_boottime_us field carries the sample's age. */
    if(!ht->diag_sampled || time_after_eq(jiffies,ht->diag_updated+HT_SAMPLE_CACHE)) {
        memset(&ht->diag,0,sizeof(ht->diag));
        ht->diag.board_disabled=ht->board_faulted;
        ht->diag.board_restored=true; /* also set by ht_diag_collect() */
        ht->diag_started_us=ktime_get_boottime_ns()/1000;
        ht->diag_status=ht_diag_collect(&ht->io,&ht->diag);
        if(!ht->diag.board_restored && !ht->board_faulted) {
            ht->board_faulted=true;
            dev_err(ht->dev,"Diagnostics board thermistor selector restore not verified (%d); board temperature walk disabled until reload\n",ht->diag.board_status);
        }
        ht->diag_duration_us=ktime_get_boottime_ns()/1000-ht->diag_started_us;
        ht->diag_updated=jiffies;ht->diag_sampled=true;
    }
    ret=ht->diag_status;
    if(ret)goto out;
    len=sysfs_emit(buf,"{\"schema\":2,\"protocol\":15,\"started_boottime_us\":%llu,\"duration_us\":%llu,\"values\":[",
        ht->diag_started_us,ht->diag_duration_us);
    for(i=0;i<HT_DIAG_FIELDS;i++) {
        if(s->scalar_status[i])len+=sysfs_emit_at(buf,len,"%s[%d,null]",i ? "," : "",s->scalar_status[i]);
        else len+=sysfs_emit_at(buf,len,"%s[0,%ld]",i ? "," : "",s->scalar[i]);
    }
    len+=sysfs_emit_at(buf,len,"]");
    len=diagnostic_bytes(buf,len,"chip",s->chip_status,s->chip,4);
    len=diagnostic_bytes(buf,len,"project",s->project_status,s->project,32);
    len=diagnostic_bytes(buf,len,"manufacturer",s->manufacturer_status,s->manufacturer,11);
    len=diagnostic_bytes(buf,len,"board",s->board_status,s->board,s->board_count);
    len+=sysfs_emit_at(buf,len,",\"board_selector_restored\":%s,\"vr\":{\"status\":%d,\"count\":%u},\"fan\":{\"status\":%d",
        s->board_restored ? "true" : "false",s->vr_status,s->vr_count,s->fan_status);
    if(!s->fan_status) {
        len+=sysfs_emit_at(buf,len,",\"count\":%u,\"index\":%u,\"selection_raw\":%u,\"mode_raw\":%u,\"rpm\":%ld,\"duty_status\":%d,\"duty_code_maximum\":254,\"duty_code\":",
            s->fan.count,s->fan.index,s->fan.selection_raw,s->fan.mode,s->fan.rpm,s->fan.duty_status);
        if(s->fan.duty_status)len+=sysfs_emit_at(buf,len,"null");
        else len+=sysfs_emit_at(buf,len,"%u",s->fan.duty);
    }
    len+=sysfs_emit_at(buf,len,"}}\n");
out:
    mutex_unlock(&ht->lock);
    return ret ? ret : len;
}
static DEVICE_ATTR_RO(ec_diagnostics);

static ssize_t firmware_diagnostics_show(struct device *dev,struct device_attribute *attr,char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    unsigned int i;
    int len;
    /* Probe-time replies and module-local counters; no firmware calls here. */
    mutex_lock(&ht->lock);
    len=sysfs_emit(buf,"{\"schema\":1,\"cached_metadata_only\":true,\"query_count\":%zu,\"queries\":{",
        ARRAY_SIZE(ht_firmware_queries));
    for(i=0;i<ARRAY_SIZE(ht_firmware_queries);i++) {
        const struct ht_firmware_recipe *q=&ht_firmware_queries[i];
        const struct ht_firmware_reply *r=&ht->firmware_reply[i];
        bool valid=!r->status || (r->status==-ENODEV && r->raw==ASUS_WMI_UNSUPPORTED_METHOD);
        len+=sysfs_emit_at(buf,len,"%s\"%s\":{\"method\":\"%s\",\"device_id\":%u,\"selector\":%u,\"status\":%d,\"raw\":%u,\"raw_valid\":%s}",
            i ? "," : "",q->name,q->method==ASUS_WMI_METHODID_DSTS ? "DSTS" : "DEVS",
            q->device,q->selector,r->status,r->raw,valid ? "true" : "false");
    }
    len+=sysfs_emit_at(buf,len,"},\"eeprom_buffer\":{\"abi\":1,\"firmware_calls\":%llu,\"guard_rejections\":%llu}}\n",
        ht->eeprom_buffer_calls,ht->eeprom_buffer_rejections);
    mutex_unlock(&ht->lock);return len;
}
static DEVICE_ATTR_RO(firmware_diagnostics);

/* I4: world-readable fail-closed latches, so userspace can tell why broker
 * reads are refused. Driver state only; no EC, ACPI or MSR access. */
static ssize_t fault_state_show(struct device *dev,struct device_attribute *attr,char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    int len;
    mutex_lock(&ht->lock);
    len=sysfs_emit(buf,"{\"schema\":1,\"charger_ipc_faulted\":%s,\"board_selector_faulted\":%s,\"manual_owned\":%s,\"module_pinned\":%s,\"removing\":%s,\"latches_cleared_by\":\"module_reload\"}\n",
        ht->charger_faulted ? "true" : "false",ht->board_faulted ? "true" : "false",
        ht->manual_owned ? "true" : "false",ht->module_ref ? "true" : "false",
        ht->removing ? "true" : "false");
    mutex_unlock(&ht->lock);
    return len;
}
static DEVICE_ATTR_RO(fault_state);
static int refresh_battery_identity(struct zenbook_ht *ht);
static ssize_t battery_identity_text(char *buf,const ht_byte *data,unsigned int length)
{
    unsigned int i;
    bool nonblank=false;
    for(i=0;i<length;i++) {
        if(data[i]<32 || data[i]>126)return -ENODATA;
        if(data[i]!=' ')nonblank=true;
    }
    if(!nonblank)return -ENODATA;
    return sysfs_emit(buf,"%.*s\n",(int)length,(const char *)data);
}
static ssize_t battery_manufacturer_show(struct device *dev, struct device_attribute *attr, char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    int ret;
    mutex_lock(&ht->lock);
    ret=refresh_battery_identity(ht);
    if (!ret) ret=battery_identity_text(buf,ht->gauge_strings.manufacturer,ht->gauge_strings.lengths[0]);
    mutex_unlock(&ht->lock);
    return ret;
}
static DEVICE_ATTR(battery_manufacturer,0400,battery_manufacturer_show,NULL);
static ssize_t battery_model_show(struct device *dev, struct device_attribute *attr, char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    int ret;
    mutex_lock(&ht->lock);
    ret=refresh_battery_identity(ht);
    if (!ret) ret=battery_identity_text(buf,ht->gauge_strings.model,ht->gauge_strings.lengths[1]);
    mutex_unlock(&ht->lock);
    return ret;
}
static DEVICE_ATTR(battery_model,0400,battery_model_show,NULL);
static ssize_t battery_history_show(struct device *dev, struct device_attribute *attr, char *buf)
{
    static const unsigned int bits[]={8,4,2,1}, names[]={1,3,4,5};
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    struct ht_history h={0};
    unsigned int i,j;
    int ret,len=0;
    mutex_lock(&ht->lock);
    ret=ht_history_read(&ht->io,&h);
    if (!ret) {
        len=sysfs_emit(buf,"{\"status\":%u,\"timeout_flags\":%u,\"permanent_failure_raw\":%ld",h.status,h.timeout,h.permanent_failure);
        for (i=0;i<4;i++) {
            len+=sysfs_emit_at(buf,len,",\"lifetime_block_%u\":",names[i]);
            if (!(h.status & bits[i])) {len+=sysfs_emit_at(buf,len,"null");continue;}
            len+=sysfs_emit_at(buf,len,"\"");
            for (j=0;j<32;j++) len+=sysfs_emit_at(buf,len,"%02x",h.blocks[i][j]);
            len+=sysfs_emit_at(buf,len,"\"");
        }
        if (h.status & 8) len+=sysfs_emit_at(buf,len,",\"max_cell_delta_mV\":%u,\"max_charge_current_mA\":%u,\"max_discharge_current_mA_raw\":%u",
            h.blocks[0][16] | ((unsigned int)h.blocks[0][17]<<8),
            h.blocks[0][18] | ((unsigned int)h.blocks[0][19]<<8),
            h.blocks[0][20] | ((unsigned int)h.blocks[0][21]<<8));
        len+=sysfs_emit_at(buf,len,"}\n");
    } else (void)ht_optional_recover(&ht->io,ret);
    mutex_unlock(&ht->lock);
    return ret ? ret : len;
}
static DEVICE_ATTR_RO(battery_history);
static ssize_t battery_history_refresh_store(struct device *dev, struct device_attribute *attr,
                                            const char *buf,size_t count)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    unsigned int value;
    int ret=kstrtouint(buf,10,&value);
    if (ret || value!=1) return -EINVAL;
    mutex_lock(&ht->lock);
    /* DD-bank request on the 0x25c port protocol, like fan and telemetry
     * traffic, not the 0xde broker or the ACPI EC mailbox; no ECMT taken. */
    ret=ht->removing ? -ENODEV : ht_history_refresh(&ht->io);
    mutex_unlock(&ht->lock);
    ht_audit(ht,"battery_history_refresh: %d",ret);
    return ret ? ret : count;
}
static DEVICE_ATTR_WO(battery_history_refresh);
static char *ht_upc_build(void);
static ssize_t diagnostics_reprobe_store(struct device *dev, struct device_attribute *attr,
                                        const char *buf,size_t count)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    unsigned int value;
    char *upc;
    int ret=kstrtouint(buf,10,&value);
    if (ret || value!=1) return -EINVAL;
    /* Explicit privileged reprobe: rebuild the static _UPC table outside
     * ht->lock and swap it in; on allocation failure keep the old copy. */
    upc=ht_upc_build();
    mutex_lock(&ht->lock);
    if (ht->removing) {
        mutex_unlock(&ht->lock);
        kfree(upc);
        ht_audit(ht,"diagnostics_reprobe: %d",-ENODEV);
        return -ENODEV;
    }
    if (upc) swap(ht->upc_cache,upc);
    ht->snapshot.unavailable_mask=0;
    ht->snapshot.static_loaded=false;
    ht->sbs_sampled=false;ht->gauge_identity_sampled=false;
    ht->diag_sampled=false;ht->frequency_sampled=false;ht->cpu_mv_sampled=false;
    ht->telemetry_valid=false;
    ret=refresh_telemetry(ht);
    mutex_unlock(&ht->lock);
    kfree(upc);
    ht_audit(ht,"diagnostics_reprobe: %d",ret);
    return ret ? ret : count;
}
static DEVICE_ATTR_WO(diagnostics_reprobe);
static ssize_t battery_gauge_status_show(struct device *dev, struct device_attribute *attr, char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    long safety=-1,pf=-1;
    acpi_handle ec;
    int ret,len=0;
    mutex_lock(&ht->lock);
    /* Same 0xde manufacturer-access broker as refresh_gauge(), so serialize
     * it against firmware AML with ECMT in the same way. */
    if (ACPI_FAILURE(acpi_get_handle(NULL,"\\_SB.PC00.LPCB.H_EC",&ec)) || ec_get_handle()!=ec) {
        ret=-ENODEV;
    } else if (ACPI_FAILURE(acpi_acquire_mutex(ec,"ECMT",1000))) {
        ret=-EBUSY;
    } else {
        ret=ht_gauge_status(&ht->io,0x51,&safety);
        if (!ret) ret=ht_gauge_status(&ht->io,0x53,&pf);
        acpi_release_mutex(ec,"ECMT");
    }
    if (!ret) len=sysfs_emit(buf,"{\"safety_status_raw\":%ld,\"permanent_failure_raw\":%ld}\n",safety,pf);
    else (void)ht_optional_recover(&ht->io,ret);
    mutex_unlock(&ht->lock);
    return ret ? ret : len;
}
/* Manufacturer-access bus commands run only on an explicit privileged read. */
static DEVICE_ATTR(battery_gauge_status,0400,battery_gauge_status_show,NULL);
static void ht_cache_delay(void *context, unsigned int milliseconds)
{
    msleep(milliseconds);
}
static int ht_cache_owner(struct zenbook_ht *ht)
{
    ht_byte mode;
    int ret;
    if (ht->manual_owned) return -EBUSY;
    ret=ht_read(&ht->io,0x31,&mode);
    return ret ? ret : mode ? -EBUSY : 0;
}
static ssize_t battery_cache_state_show(struct device *dev, struct device_attribute *attr, char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    ht_byte status,timeout;
    int ret;
    mutex_lock(&ht->lock);
    ret=ht_cache_state(&ht->io,&status,&timeout);
    if (ret) (void)ht_optional_recover(&ht->io,ret);
    mutex_unlock(&ht->lock);
    return ret ? ret : sysfs_emit(buf,"{\"schema\":1,\"status\":%u,\"timeout_flags\":%u}\n",status,timeout);
}
static DEVICE_ATTR_RO(battery_cache_state);
static ssize_t battery_cache_payload_show(struct device *dev, struct device_attribute *attr, char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    struct ht_cache_frame frame;
    unsigned int i,kind=!strcmp(attr->attr.name,"battery_information") ? 0x10 : 0x80;
    int ret,len=0;
    mutex_lock(&ht->lock);
    /* No ECMT: the 0x81/0x5a refresh and bank-1 polls are DD-bank port
     * traffic like fan and telemetry reads, not the 0xde broker or the ACPI
     * EC mailbox, and holding ECMT across the 1 s polls would stall AML. */
    ret=ht_cache_owner(ht);
    if (!ret) ret=ht_cache_collect(&ht->io,kind,ht_cache_delay,NULL,&frame);
    if (!ret) {
        len=sysfs_emit(buf,"{\"schema\":1,\"status\":%u,\"timeout_flags\":%u,\"ready_bit\":%u,\"refresh_requested\":%s,\"data_hex\":\"",
            frame.status,frame.timeout,frame.ready_bit,frame.refresh_requested ? "true" : "false");
        for (i=0;i<frame.length;i++) len+=sysfs_emit_at(buf,len,"%02x",frame.data[i]);
        len+=sysfs_emit_at(buf,len,"\"}\n");
    } else (void)ht_optional_recover(&ht->io,ret);
    mutex_unlock(&ht->lock);
    return ret ? ret : len;
}
/* Explicit privileged read because a fixed volatile refresh may be requested. */
static DEVICE_ATTR(battery_information,0400,battery_cache_payload_show,NULL);
static DEVICE_ATTR(battery_pf_cache,0400,battery_cache_payload_show,NULL);
static ssize_t ec_chip_name_show(struct device *dev, struct device_attribute *attr, char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    ht_byte bytes[14];
    unsigned int i;
    int ret,len=0;
    mutex_lock(&ht->lock);
    ret=ht_cache_owner(ht);
    for (i=0;!ret && i<14;i++) {
        ht_byte selector=0x12+i;
        ret=ht_xfer(&ht->io,0xbb,&selector,1,&bytes[i]);
    }
    if (!ret) {
        len=sysfs_emit(buf,"{\"schema\":1,\"data_hex\":\"");
        for (i=0;i<14;i++) len+=sysfs_emit_at(buf,len,"%02x",bytes[i]);
        len+=sysfs_emit_at(buf,len,"\"}\n");
    } else (void)ht_optional_recover(&ht->io,ret);
    mutex_unlock(&ht->lock);
    return ret ? ret : len;
}
static DEVICE_ATTR_RO(ec_chip_name);
/* Binary request: eight little-endian u32s, ABI/op/index/value/reserved/flags/nonce-lo/nonce-hi.
 * Sysfs active references protect device lifetime; response nonces reject races. */
static int ht_acpi_ec_byte(void *context,unsigned int address,ht_byte *result)
{
    union acpi_object argument={.type=ACPI_TYPE_INTEGER};
    struct acpi_object_list input={1,&argument};
    unsigned long long value;
    acpi_status status;
    argument.integer.value=address;
    status=acpi_evaluate_integer((acpi_handle)context,"RDER",&input,&value);
    if (ACPI_FAILURE(status))return -EIO;
    if (value>255)return -EPROTO;
    *result=value;
    return 0;
}

static int ht_read_pd(struct zenbook_ht *ht)
{
    acpi_handle ec;
    if (ACPI_FAILURE(acpi_get_handle(NULL,"\\_SB.PC00.LPCB.H_EC",&ec)))return -ENODEV;
    return ht_pd_snapshot(ht_acpi_ec_byte,ec,ht->oem_data,&ht->oem_length);
}

/* One unprivileged read-only monitoring snapshot, cached for two seconds.
 * Keep this separate from nonce-protected root-only OEM RPC responses. */
static ssize_t pd_contract_show(struct device *dev,struct device_attribute *attr,char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    acpi_handle ec;
    unsigned int length=0,i;
    int ret=0,len;
    mutex_lock(&ht->lock);
    if (ht->manual_owned) {ret=-EBUSY;goto out;}
    if (!ht->pd_valid || time_after_eq(jiffies,ht->pd_updated+2*HZ)) {
        ht->pd_valid=false;
        if (ACPI_FAILURE(acpi_get_handle(NULL,"\\_SB.PC00.LPCB.H_EC",&ec))) {ret=-ENODEV;goto out;}
        ret=ht_pd_snapshot(ht_acpi_ec_byte,ec,ht->pd_data,&length);
        if (ret)goto out;
        ht->pd_valid=true;ht->pd_updated=jiffies;
    }
    len=sysfs_emit(buf,"{\"schema\":1,\"data_hex\":\"");
    for (i=0;i<HT_PD_SIZE;i++)len+=sysfs_emit_at(buf,len,"%02x",ht->pd_data[i]);
    len+=sysfs_emit_at(buf,len,"\",\"maximum_cache_seconds\":2}\n");
    ret=len;
out:
    mutex_unlock(&ht->lock);return ret;
}
static DEVICE_ATTR_RO(pd_contract);

static ssize_t pd_source_caps_show(struct device *dev,struct device_attribute *attr,char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    acpi_handle ec;
    unsigned int length=0,i;
    int ret=0,len;
    mutex_lock(&ht->lock);
    if(ht->manual_owned) {ret=-EBUSY;goto out;}
    if(!ht->pd_sources_valid || time_after_eq(jiffies,ht->pd_sources_updated+2*HZ)) {
        ht->pd_sources_valid=false;
        if(ACPI_FAILURE(acpi_get_handle(NULL,"\\_SB.PC00.LPCB.H_EC",&ec))) {ret=-ENODEV;goto out;}
        ret=ht_pd_sources_snapshot(ht_acpi_ec_byte,ec,ht->pd_sources,&length);
        if(ret)goto out;
        ht->pd_sources_valid=true;ht->pd_sources_updated=jiffies;
    }
    len=sysfs_emit(buf,"{\"schema\":1,\"data_hex\":\"");
    for(i=0;i<HT_PD_SOURCES_SIZE;i++)len+=sysfs_emit_at(buf,len,"%02x",ht->pd_sources[i]);
    ret=len+sysfs_emit_at(buf,len,"\",\"maximum_cache_seconds\":2}\n");
out:
    mutex_unlock(&ht->lock);return ret;
}
static DEVICE_ATTR_RO(pd_source_caps);

/* Distinguishes a stalled EC (remaining restore primitives deliberately not
 * issued after consecutive timeouts or the restore deadline) in the one log
 * line emitted when the fault latch is set. */
static const char *ht_ipc_stall_note(const struct ht_charger_io *io)
{
    if(io->stalled)return " (EC stopped responding; remaining restore operations skipped)";
    return io->restore_expired ? " (EC restore budget expired; remaining restore operations skipped)":"";
}
/* Fixed OEM IPC only: neither callback accepts a charger register write. */
static int charger_ec_read(void *context,unsigned int address,ht_byte *value)
{
    u8 params[2]={address>>8,address&255};
    if(address!=0x0380 && !(address>=0x9000 && address<=0x9010) &&
       address!=0x9040 && address!=0x9041)return -EPERM;
    return ec_transaction(0x92,params,2,value,1);
}
static int charger_ec_restore(void *context,unsigned int index,ht_byte value)
{
    u16 address;
    u8 params[3];
    if(index>=HT_CHARGER_FIELDS)return -EPERM;
    address=ht_charger_fields[index];
    params[0]=address>>8;params[1]=address&255;params[2]=value;
    return ec_transaction(0x93,params,3,NULL,0);
}
static int charger_set(void *context,ht_byte index,ht_byte value)
{
    struct zenbook_ht *ht=context;
    return ht_charger_packet(&ht->io,true,index,value,NULL);
}
static int charger_get(void *context,ht_byte index,ht_byte *value)
{
    struct zenbook_ht *ht=context;
    return ht_charger_packet(&ht->io,false,index,0,value);
}
static int refresh_charger(struct zenbook_ht *ht)
{
    struct ht_charger_io io={.read=charger_ec_read,.restore=charger_ec_restore,.set=charger_set,.get=charger_get,.ctx=ht,.now_us=port_now,.port=&ht->io};
    acpi_handle ec;
    int ret;
    if(ht->manual_owned)return -EBUSY;
    if(ht->charger_faulted)return -EUCLEAN;
    if(ht->charger_sampled && time_before(jiffies,ht->charger_updated+2*HZ))return ht->charger_status;
    /* Handle and ECMT failures are cached like any other error. */
    if(ACPI_FAILURE(acpi_get_handle(NULL,"\\_SB.PC00.LPCB.H_EC",&ec)) || ec_get_handle()!=ec){ret=-ENODEV;goto cache;}
    if(ACPI_FAILURE(acpi_acquire_mutex(ec,"ECMT",1000))){ret=-EBUSY;goto cache;}
    ret=ht_charger_collect_retry(&io,&ht->charger);
    acpi_release_mutex(ec,"ECMT");
cache:
    ht->charger_updated=jiffies;ht->charger_sampled=true;ht->charger_status=ret;
    if(ret==-EUCLEAN){
        ht->charger_faulted=true;
        dev_err(ht->dev,"Charger IPC restoration failed%s; further charger requests disabled\n",ht_ipc_stall_note(&io));
    }
    return ret;
}
static ssize_t charger_adc_show(struct device *dev,struct device_attribute *attr,char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    unsigned int i;
    int ret,len;
    mutex_lock(&ht->lock);
    ret=refresh_charger(ht);
    if(ret)goto out;
    len=sysfs_emit(buf,"{\"schema\":1,\"input_millivolts\":%ld,\"input_microamps\":%ld,\"input_microwatts\":%ld,\"current_resolution_microamps\":44400,\"voltage_resolution_millivolts\":96,\"input_shunt_milliohms\":10,\"maximum_cache_seconds\":2,\"age_milliseconds\":%u,\"words\":[",
        ht->charger.voltage_mv,ht->charger.current_ua,ht->charger.power_uw,
        jiffies_to_msecs(jiffies-ht->charger_updated));
    for(i=0;i<HT_CHARGER_WORDS;i++)len+=sysfs_emit_at(buf,len,"%s%u",i ? "," : "",ht->charger.words[i]);
    len+=sysfs_emit_at(buf,len,"]}\n");ret=len;
out:
    mutex_unlock(&ht->lock);return ret;
}
static DEVICE_ATTR(charger_adc,0400,charger_adc_show,NULL);

static int refresh_charger_extra(struct zenbook_ht *ht)
{
    struct ht_charger_io io={.read=charger_ec_read,.restore=charger_ec_restore,.set=charger_set,.get=charger_get,.ctx=ht,.now_us=port_now,.port=&ht->io};
    acpi_handle ec;
    int ret;
    if(ht->manual_owned)return -EBUSY;
    if(ht->charger_faulted)return -EUCLEAN;
    if(ht->extra_sampled && time_before(jiffies,ht->extra_updated+2*HZ))return ht->extra_status;
    if(ACPI_FAILURE(acpi_get_handle(NULL,"\\_SB.PC00.LPCB.H_EC",&ec)) || ec_get_handle()!=ec){ret=-ENODEV;goto cache;}
    if(ACPI_FAILURE(acpi_acquire_mutex(ec,"ECMT",1000))){ret=-EBUSY;goto cache;}
    ret=ht_charger_extra_collect_retry(&io,&ht->charger_extra);
    acpi_release_mutex(ec,"ECMT");
cache:
    ht->extra_updated=jiffies;ht->extra_sampled=true;ht->extra_status=ret;
    if(ret==-EUCLEAN){
        ht->charger_faulted=true;
        dev_err(ht->dev,"Charger metrics IPC restoration failed%s; further charger requests disabled\n",ht_ipc_stall_note(&io));
    }
    return ret;
}
static ssize_t charger_metrics_show(struct device *dev,struct device_attribute *attr,char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    struct ht_charger_extra *s=&ht->charger_extra;
    unsigned int i;
    int ret,len;
    mutex_lock(&ht->lock);
    ret=refresh_charger_extra(ht);if(ret)goto out;
    len=sysfs_emit(buf,"{\"schema\":1,\"valid_mask\":%u,\"die_millicelsius\":%ld,\"vbat_pin_millivolts\":%ld,\"system_millivolts\":%ld,\"discharge_microamps\":%ld,\"charge_microamps\":%ld,\"battery_shunt_milliohms\":5,\"maximum_cache_seconds\":2,\"age_milliseconds\":%u,\"words\":[",
        s->valid_mask,s->die_mc,s->vbat_mv,s->system_mv,s->discharge_ua,s->charge_ua,
        jiffies_to_msecs(jiffies-ht->extra_updated));
    for(i=0;i<HT_CHARGER_EXTRA_WORDS;i++)len+=sysfs_emit_at(buf,len,"%s%u",i ? "," : "",s->words[i]);
    len+=sysfs_emit_at(buf,len,"]}\n");ret=len;
out:
    mutex_unlock(&ht->lock);return ret;
}
static DEVICE_ATTR(charger_metrics,0400,charger_metrics_show,NULL);


static int pd_ic_read(void *context,unsigned int address,ht_byte *value)
{
    u8 p[]={address>>8,address&255};
    if(!(address>=0x9000 && address<=0x9010) && !(address>=0x9040 && address<=0x9059))return -EPERM;
    return ec_transaction(0x92,p,2,value,1);
}
static int pd_ic_restore(void *context,unsigned int index,ht_byte value)
{
    u16 address;
    u8 p[3];
    if(index>=HT_PD_IC_FIELDS)return -EPERM;
    address=ht_pd_ic_fields[index];p[0]=address>>8;p[1]=address&255;p[2]=value;
    return ec_transaction(0x93,p,3,NULL,0);
}
static int pd_ic_set(void *context,ht_byte index,ht_byte value)
{
    struct zenbook_ht *ht=context;
    return ht_pd_ic_packet(&ht->io,true,index,value,NULL);
}
static int pd_ic_get(void *context,ht_byte index,ht_byte *value)
{
    struct zenbook_ht *ht=context;
    return ht_pd_ic_packet(&ht->io,false,index,0,value);
}
static int refresh_pd_identity_once(struct zenbook_ht *ht)
{
    struct ht_charger_io io={.read=pd_ic_read,.restore=pd_ic_restore,.set=pd_ic_set,.get=pd_ic_get,.ctx=ht,.now_us=port_now,.port=&ht->io};
    ht_byte after[HT_PD_SIZE];
    struct ht_pd_identity next;
    unsigned int size,active=0,i;
    acpi_handle ec;
    int ret;
    if(ht->manual_owned)return -EBUSY;
    if(ht->charger_faulted)return -EUCLEAN;
    if(ht->identity_sampled && time_before(jiffies,ht->identity_updated+(ht->identity_status ? 1:5)*HZ))return ht->identity_status;
    if(ACPI_FAILURE(acpi_get_handle(NULL,"\\_SB.PC00.LPCB.H_EC",&ec)) || ec_get_handle()!=ec){ret=-ENODEV;goto done;}
    ret=ht_pd_snapshot(ht_acpi_ec_byte,ec,ht->identity_contract,&size);if(ret)goto done;
    if(ht->identity_contract[1]==255 || ht->identity_contract[3]==255 || ht->identity_contract[13]==255){ret=-EPROTO;goto done;}
    if(ht->identity_contract[1]&1)for(i=0;i<2;i++)if(ht->identity_contract[3+10*i]&0x40)active|=1U<<i;
    if(ACPI_FAILURE(acpi_acquire_mutex(ec,"ECMT",1000))){ret=-EBUSY;goto done;}
    ret=ht_pd_identity_collect(&io,active,&next);
    acpi_release_mutex(ec,"ECMT");
    if(ret==-EUCLEAN){ht->charger_faulted=true;dev_err(ht->dev,"PD identity IPC restoration failed%s; further controller requests disabled\n",ht_ipc_stall_note(&io));}
    if(ret)goto done;
    ret=ht_pd_snapshot(ht_acpi_ec_byte,ec,after,&size);if(ret)goto done;
    for(i=0;i<HT_PD_SIZE;i++)if(after[i]!=ht->identity_contract[i]){ret=-EAGAIN;goto done;}
    ht->identity=next;
done:
    ht->identity_sampled=true;ht->identity_status=ret;ht->identity_updated=jiffies;return ret;
}
/* A contract change between the bracketing snapshots (-EAGAIN) discards the
 * sample. Take exactly one fresh complete bracketed sample; never merge halves. */
static int refresh_pd_identity(struct zenbook_ht *ht)
{
    int ret=refresh_pd_identity_once(ht);
    if(ret==-EAGAIN){ht->identity_sampled=false;ret=refresh_pd_identity_once(ht);}
    return ret;
}
static ssize_t pd_identity_show(struct device *dev,struct device_attribute *attr,char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    unsigned int i,j;
    int ret,len;
    mutex_lock(&ht->lock);
    ret=refresh_pd_identity(ht);if(ret)goto out;
    len=sysfs_emit(buf,"{\"schema\":1,\"maximum_cache_seconds\":5,\"age_milliseconds\":%u,\"contract_hex\":\"",jiffies_to_msecs(jiffies-ht->identity_updated));
    for(i=0;i<HT_PD_SIZE;i++)len+=sysfs_emit_at(buf,len,"%02x",ht->identity_contract[i]);
    len+=sysfs_emit_at(buf,len,"\",\"ports\":[");
    for(i=0;i<2;i++){
        len+=sysfs_emit_at(buf,len,"%s{\"connector\":%u,\"sop_hex\":\"",i ? ",":"",i+1);
        for(j=0;j<25;j++)len+=sysfs_emit_at(buf,len,"%02x",ht->identity.sop[i][j]);
        len+=sysfs_emit_at(buf,len,"\",\"cable_hex\":\"");
        for(j=0;j<25;j++)len+=sysfs_emit_at(buf,len,"%02x",ht->identity.cable[i][j]);
        len+=sysfs_emit_at(buf,len,"\",\"alert_hex\":\"");
        for(j=0;j<4;j++)len+=sysfs_emit_at(buf,len,"%02x",ht->identity.alert[i][j]);
        len+=sysfs_emit_at(buf,len,"\"}");
    }
    ret=len+sysfs_emit_at(buf,len,"]}\n");
out:
    mutex_unlock(&ht->lock);return ret;
}
static DEVICE_ATTR(pd_identity,0400,pd_identity_show,NULL);

/* Root-only read of received-PD extended registers; same bracketing, locks,
 * mailbox restoration and fault latch as pd_identity. No controller write. */
static int refresh_pd_extended_once(struct zenbook_ht *ht)
{
    struct ht_charger_io io={.read=pd_ic_read,.restore=pd_ic_restore,.set=pd_ic_set,.get=pd_ic_get,.ctx=ht,.now_us=port_now,.port=&ht->io};
    ht_byte after[HT_PD_SIZE];
    struct ht_pd_extended next;
    unsigned int size,active=0,i;
    acpi_handle ec;
    int ret;
    if(ht->manual_owned)return -EBUSY;
    if(ht->charger_faulted)return -EUCLEAN;
    if(ht->extended_sampled && time_before(jiffies,ht->extended_updated+(ht->extended_status ? 1:5)*HZ))return ht->extended_status;
    if(ACPI_FAILURE(acpi_get_handle(NULL,"\\_SB.PC00.LPCB.H_EC",&ec)) || ec_get_handle()!=ec){ret=-ENODEV;goto done;}
    ret=ht_pd_snapshot(ht_acpi_ec_byte,ec,ht->extended_contract,&size);if(ret)goto done;
    if(ht->extended_contract[1]==255 || ht->extended_contract[3]==255 || ht->extended_contract[13]==255){ret=-EPROTO;goto done;}
    if(ht->extended_contract[1]&1)for(i=0;i<2;i++)if(ht->extended_contract[3+10*i]&0x40)active|=1U<<i;
    if(ACPI_FAILURE(acpi_acquire_mutex(ec,"ECMT",1000))){ret=-EBUSY;goto done;}
    ret=ht_pd_extended_collect(&io,active,&next);
    acpi_release_mutex(ec,"ECMT");
    if(ret==-EUCLEAN){ht->charger_faulted=true;dev_err(ht->dev,"PD extended IPC restoration failed%s; further controller requests disabled\n",ht_ipc_stall_note(&io));}
    if(ret)goto done;
    ret=ht_pd_snapshot(ht_acpi_ec_byte,ec,after,&size);if(ret)goto done;
    for(i=0;i<HT_PD_SIZE;i++)if(after[i]!=ht->extended_contract[i]){ret=-EAGAIN;goto done;}
    ht->extended=next;
done:
    ht->extended_sampled=true;ht->extended_status=ret;ht->extended_updated=jiffies;return ret;
}
static int refresh_pd_extended(struct zenbook_ht *ht)
{
    int ret=refresh_pd_extended_once(ht);
    if(ret==-EAGAIN){ht->extended_sampled=false;ret=refresh_pd_extended_once(ht);}
    return ret;
}
static ssize_t pd_extended_show(struct device *dev,struct device_attribute *attr,char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    unsigned int i,j,k;
    int ret,len;
    mutex_lock(&ht->lock);
    ret=refresh_pd_extended(ht);if(ret)goto out;
    len=sysfs_emit(buf,"{\"schema\":1,\"maximum_cache_seconds\":5,\"age_milliseconds\":%u,\"active_ports\":%u,\"ports\":[",
        jiffies_to_msecs(jiffies-ht->extended_updated),ht->extended.ports);
    for(i=0;i<2;i++){
        len+=sysfs_emit_at(buf,len,"%s{\"connector\":%u,\"read\":%s,\"registers\":[",i ? ",":"",i+1,(ht->extended.ports&(1U<<i)) ? "true":"false");
        for(j=0;j<HT_PD_EXT_REGS;j++){
            len+=sysfs_emit_at(buf,len,"%s{\"register\":%u,\"length\":%u,\"data_hex\":\"",j ? ",":"",ht_pd_ext_regs[j],ht->extended.length[i][j]);
            for(k=0;k<ht->extended.length[i][j];k++)len+=sysfs_emit_at(buf,len,"%02x",ht->extended.data[i][j][k]);
            len+=sysfs_emit_at(buf,len,"\"}");
        }
        len+=sysfs_emit_at(buf,len,"]}");
    }
    ret=len+sysfs_emit_at(buf,len,"]}\n");
out:
    mutex_unlock(&ht->lock);return ret;
}
static DEVICE_ATTR(pd_extended,0400,pd_extended_show,NULL);

static int gauge_block_read(void *context,unsigned int address,ht_byte *value)
{
    u8 p[]={address>>8,address&255};
    if(!(address>=0x9000 && address<=0x900f) && !(address>=0x9040 && address<=0x905f))return -EPERM;
    return ec_transaction(0x92,p,2,value,1);
}
/* Fixed volatile RX seeding and restoration only. Never a BMS register write. */
static int gauge_block_restore(void *context,unsigned int index,ht_byte value)
{
    u16 address;
    u8 p[3];
    if(index>=HT_GAUGE_BLOCK_FIELDS)return -EPERM;
    address=ht_gauge_block_fields[index];p[0]=address>>8;p[1]=address&255;p[2]=value;
    return ec_transaction(0x93,p,3,NULL,0);
}
static int gauge_block_set(void *context,ht_byte index,ht_byte value)
{
    struct zenbook_ht *ht=context;
    return ht_gauge_block_packet(&ht->io,true,index,value,NULL);
}
static int gauge_block_get(void *context,ht_byte index,ht_byte *value)
{
    struct zenbook_ht *ht=context;
    return ht_gauge_block_packet(&ht->io,false,index,0,value);
}
static int gauge_prefix_query(void *context,unsigned int selector,ht_byte *value)
{
    struct zenbook_ht *ht=context;
    return ht_gauge_query(&ht->io,selector,value);
}
/* Read-only manufacturer queries through the firmware's battery broker. */
static int refresh_gauge(struct zenbook_ht *ht,bool lifetime)
{
    struct ht_gauge_full_io io={.ipc={.read=gauge_block_read,.restore=gauge_block_restore,.set=gauge_block_set,.get=gauge_block_get,.ctx=ht,.now_us=port_now,.port=&ht->io},.query=gauge_prefix_query};
    acpi_handle ec;
    unsigned long *updated=lifetime ? &ht->lifetime_updated:&ht->gauge_updated;
    bool *sampled=lifetime ? &ht->lifetime_sampled:&ht->gauge_sampled;
    int *status=lifetime ? &ht->lifetime_status:&ht->gauge_status;
    unsigned int seconds=lifetime ? 60:5;
    int ret;
    if(ht->manual_owned)return -EBUSY;
    if(ht->charger_faulted)return -EUCLEAN;
    if(*sampled && time_before(jiffies,*updated+(*status ? 1:seconds)*HZ))return *status;
    if(ACPI_FAILURE(acpi_get_handle(NULL,"\\_SB.PC00.LPCB.H_EC",&ec)) || ec_get_handle()!=ec){ret=-ENODEV;goto cache;}
    if(ACPI_FAILURE(acpi_acquire_mutex(ec,"ECMT",1000))){ret=-EBUSY;goto cache;}
    ret=lifetime ? ht_gauge_full_collect(&io,&ht->gauge_lifetime):ht_gauge_sample_read(&ht->io,&ht->gauge_sample);
    acpi_release_mutex(ec,"ECMT");
    if(ret==-EUCLEAN){ht->charger_faulted=true;dev_err(ht->dev,"Battery block IPC restoration failed%s; further controller requests disabled\n",ht_ipc_stall_note(&io.ipc));}
cache:
    if(ret)(void)ht_optional_recover(&ht->io,ret);
    *status=ret;*sampled=true;*updated=jiffies;return ret;
}
static int emit_gauge_hex(char *buf,int len,const ht_byte *data,unsigned int count)
{
    unsigned int i;
    for(i=0;i<count;i++)len+=sysfs_emit_at(buf,len,"%02x",data[i]);
    return len;
}
static int refresh_gauge_extra(struct zenbook_ht *ht)
{
    struct ht_gauge_full_io io={.ipc={.read=gauge_block_read,.restore=gauge_block_restore,.set=gauge_block_set,.get=gauge_block_get,.ctx=ht,.now_us=port_now,.port=&ht->io},.query=gauge_prefix_query};
    acpi_handle ec;
    int ret;
    if(ht->manual_owned)return -EBUSY;
    if(ht->charger_faulted)return -EUCLEAN;
    if(ht->gauge_extra_sampled && time_before(jiffies,ht->gauge_extra_updated+(ht->gauge_extra_status ? 1:15)*HZ))return ht->gauge_extra_status;
    if(ACPI_FAILURE(acpi_get_handle(NULL,"\\_SB.PC00.LPCB.H_EC",&ec)) || ec_get_handle()!=ec){ret=-ENODEV;goto cache;}
    if(ACPI_FAILURE(acpi_acquire_mutex(ec,"ECMT",1000))){ret=-EBUSY;goto cache;}
    ret=ht_gauge_measurements_collect(&io,&ht->gauge_extra);
    acpi_release_mutex(ec,"ECMT");
    if(ret==-EUCLEAN){ht->charger_faulted=true;dev_err(ht->dev,"Battery measurement IPC restoration failed%s; further controller requests disabled\n",ht_ipc_stall_note(&io.ipc));}
cache:
    if(ret)(void)ht_optional_recover(&ht->io,ret);
    ht->gauge_extra_status=ret;ht->gauge_extra_sampled=true;ht->gauge_extra_updated=jiffies;return ret;
}
static ssize_t battery_gauge_extra_show(struct device *dev,struct device_attribute *attr,char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    struct ht_gauge_full_sample *s=&ht->gauge_extra;
    int ret,len;
    mutex_lock(&ht->lock);
    ret=refresh_gauge_extra(ht);if(ret)goto out;
    len=sysfs_emit(buf,"{\"schema\":1,\"maximum_cache_seconds\":15,\"age_milliseconds\":%u,\"device_type_hex\":\"",jiffies_to_msecs(jiffies-ht->gauge_extra_updated));
    len=emit_gauge_hex(buf,len,s->identity,2);
    len+=sysfs_emit_at(buf,len,"\",\"firmware_hex\":\"");len=emit_gauge_hex(buf,len,s->firmware,13);
    len+=sysfs_emit_at(buf,len,"\",\"da1_hex\":\"");len=emit_gauge_hex(buf,len,s->da1,32);
    len+=sysfs_emit_at(buf,len,"\",\"da2_hex\":\"");len=emit_gauge_hex(buf,len,s->da2,24);
    ret=len+sysfs_emit_at(buf,len,"\"}\n");
out:
    mutex_unlock(&ht->lock);return ret;
}
static DEVICE_ATTR(battery_gauge_extra,0400,battery_gauge_extra_show,NULL);
static int sbs_read(void *context,unsigned int address,ht_byte *value)
{
    if(address==0x9010){u8 p[]={0x90,0x10};return ec_transaction(0x92,p,2,value,1);}
    return gauge_block_read(context,address,value);
}
static int sbs_restore(void *context,unsigned int index,ht_byte value)
{
    u16 address;
    u8 p[3];
    if(index>=HT_SBS_FIELDS)return -EPERM;
    address=ht_sbs_fields[index];p[0]=address>>8;p[1]=address&255;p[2]=value;
    return ec_transaction(0x93,p,3,NULL,0);
}
static int sbs_set(void *context,ht_byte index,ht_byte value)
{
    struct zenbook_ht *ht=context;
    return ht_sbs_native_packet(&ht->io,true,index,value,NULL);
}
static int sbs_get(void *context,ht_byte index,ht_byte *value)
{
    struct zenbook_ht *ht=context;
    return ht_sbs_native_packet(&ht->io,false,index,0,value);
}
static int refresh_sbs(struct zenbook_ht *ht)
{
    struct ht_gauge_full_io io={.ipc={.read=sbs_read,.restore=sbs_restore,.set=sbs_set,.get=sbs_get,.ctx=ht,.now_us=port_now,.port=&ht->io},.query=gauge_prefix_query};
    acpi_handle ec;
    int ret;
    unsigned int attempt;
    if(ht->manual_owned)return -EBUSY;
    if(ht->charger_faulted)return -EUCLEAN;
    if(ht->sbs_sampled && time_before(jiffies,ht->sbs_updated+(ht->sbs_status ? 1:30)*HZ))return ht->sbs_status;
    if(ACPI_FAILURE(acpi_get_handle(NULL,"\\_SB.PC00.LPCB.H_EC",&ec)) || ec_get_handle()!=ec){ret=-ENODEV;goto cache;}
    for(attempt=0;attempt<2;attempt++){
        if(ACPI_FAILURE(acpi_acquire_mutex(ec,"ECMT",1000))){ret=-EBUSY;break;}
        if(attempt)ht->sbs_retries++;
        ret=ht_sbs_native_collect(&io,&ht->sbs,&ht->sbs_trace);
        acpi_release_mutex(ec,"ECMT");
        ht->sbs_attempts++;ht->sbs_trace_time=ktime_get_boottime_ns();
        if(ret){
            ht->sbs_failures++;ht->sbs_last_failure=ht->sbs_trace;
            ht->sbs_failure_time=ht->sbs_trace_time;
        }else{
            ht->sbs_successes++;
            if(attempt)ht->sbs_recovered_refreshes++;
        }
        if(attempt || !ht_sbs_retryable(&ht->sbs_trace))break;
        /* Previous collection has restored/read back all49 IPC bytes. Yield
         * with ECMT released before one complete fresh fixed read attempt. */
        msleep(100);
    }
    if(ret==-EUCLEAN){ht->charger_faulted=true;dev_err(ht->dev,"Battery SBS IPC restoration failed%s; further controller requests disabled\n",ht_ipc_stall_note(&io.ipc));}
cache:
    if(ret)(void)ht_optional_recover(&ht->io,ret);
    ht->sbs_status=ret;ht->sbs_sampled=true;ht->sbs_updated=jiffies;return ret;
}
static ssize_t battery_sbs_show(struct device *dev,struct device_attribute *attr,char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    unsigned int i;
    int ret,len;
    mutex_lock(&ht->lock);
    ret=refresh_sbs(ht);if(ret)goto out;
    len=sysfs_emit(buf,"{\"schema\":1,\"transport\":\"native_smbus_read_word\",\"maximum_cache_seconds\":30,\"age_milliseconds\":%u,\"device_type_hex\":\"",jiffies_to_msecs(jiffies-ht->sbs_updated));
    len=emit_gauge_hex(buf,len,ht->sbs.identity,2);
    len+=sysfs_emit_at(buf,len,"\",\"firmware_hex\":\"");len=emit_gauge_hex(buf,len,ht->sbs.firmware,13);
    len+=sysfs_emit_at(buf,len,"\",\"words\":[");
    for(i=0;i<HT_SBS_WORDS;i++)len+=sysfs_emit_at(buf,len,"%s%u",i ? ",":"",ht->sbs.words[i]);
    ret=len+sysfs_emit_at(buf,len,"]}\n");
out:
    mutex_unlock(&ht->lock);return ret;
}
static DEVICE_ATTR(battery_sbs,0400,battery_sbs_show,NULL);
static const char *sbs_phase_name(unsigned int phase)
{
    static const char * const names[]={"none","snapshot","idle","identity","firmware",
        "prepare","word-sentinel","word-channel","word-command","word-submit",
        "word-completion","word-bus-status","word-rx-low","word-rx-high","mode-bracket","complete",
        "native-word-completion","native-word-result","word-rx-tail"};
    return phase<ARRAY_SIZE(names) ? names[phase]:"unknown";
}
static int emit_sbs_trace(char *buf,int len,const struct ht_sbs_trace *trace,u64 recorded,u64 now)
{
    len+=sysfs_emit_at(buf,len,"{\"transport\":\"%s\",\"phase\":\"%s\",\"result\":%d,\"operation_status\":%d,\"restoration_status\":%d,\"age_milliseconds\":%llu,\"sentinel_attempt\":%u,\"bracket\":%s,\"command\":",
        trace->native_word ? "native_smbus_read_word":"legacy_i2c_combined_read_word",sbs_phase_name(trace->phase),trace->result,trace->operation_status,trace->restoration_status,
        div_u64(now-recorded,1000000),trace->attempt,trace->bracket ? "true":"false");
    if(trace->command_valid)len+=sysfs_emit_at(buf,len,"%u",trace->command);
    else len+=sysfs_emit_at(buf,len,"null");
    len+=sysfs_emit_at(buf,len,",\"completion_status\":");
    if(trace->completion_valid)len+=sysfs_emit_at(buf,len,"%u",trace->completion);
    else len+=sysfs_emit_at(buf,len,"null");
    len+=sysfs_emit_at(buf,len,",\"bus_status\":");
    if(trace->bus_status_valid)len+=sysfs_emit_at(buf,len,"%u",trace->bus_status);
    else len+=sysfs_emit_at(buf,len,"null");
    len+=sysfs_emit_at(buf,len,",\"worker_result\":");
    if(trace->worker_result_valid)len+=sysfs_emit_at(buf,len,"%u",trace->worker_result);
    else len+=sysfs_emit_at(buf,len,"null");
    len+=sysfs_emit_at(buf,len,",\"software_observation\":");
    if(!trace->software.sampled)len+=sysfs_emit_at(buf,len,"null");
    else{
        len+=sysfs_emit_at(buf,len,"{\"result\":%d,\"atomic\":false,\"current_operation_proven\":false,\"raw_hex\":",trace->software.result);
        if(trace->software.result)len+=sysfs_emit_at(buf,len,"null");
        else len+=sysfs_emit_at(buf,len,"\"%02x%02x%02x%02x\"",trace->software.bytes[0],trace->software.bytes[1],trace->software.bytes[2],trace->software.bytes[3]);
        len+=sysfs_emit_at(buf,len,"}");
    }
    return len+sysfs_emit_at(buf,len,"}");
}
static ssize_t battery_sbs_diagnostics_show(struct device *dev,struct device_attribute *attr,char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    int len;u64 now;
    mutex_lock(&ht->lock);now=ktime_get_boottime_ns();
    len=sysfs_emit(buf,"{\"schema\":1,\"transport\":\"native_smbus_read_word\",\"cached_metadata_only\":true,\"attempts\":%llu,\"successes\":%llu,\"failures\":%llu,\"retries\":%llu,\"recovered_refreshes\":%llu,\"retry_limit\":1,\"retry_backoff_milliseconds\":100,\"last_attempt\":",
        ht->sbs_attempts,ht->sbs_successes,ht->sbs_failures,ht->sbs_retries,ht->sbs_recovered_refreshes);
    if(ht->sbs_attempts)len=emit_sbs_trace(buf,len,&ht->sbs_trace,ht->sbs_trace_time,now);
    else len+=sysfs_emit_at(buf,len,"null");
    len+=sysfs_emit_at(buf,len,",\"last_failure\":");
    if(ht->sbs_failures)len=emit_sbs_trace(buf,len,&ht->sbs_last_failure,ht->sbs_failure_time,now);
    else len+=sysfs_emit_at(buf,len,"null");
    len+=sysfs_emit_at(buf,len,"}\n");mutex_unlock(&ht->lock);return len;
}
static DEVICE_ATTR_RO(battery_sbs_diagnostics);
static int refresh_battery_identity(struct zenbook_ht *ht)
{
    struct ht_gauge_full_io io={.ipc={.read=gauge_block_read,.restore=gauge_block_restore,.set=gauge_block_set,.get=gauge_block_get,.ctx=ht,.now_us=port_now,.port=&ht->io},.query=gauge_prefix_query};
    acpi_handle ec;
    int ret;
    if(ht->manual_owned)return -EBUSY;
    if(ht->charger_faulted)return -EUCLEAN;
    if(ht->gauge_identity_sampled && time_before(jiffies,ht->gauge_identity_updated+(ht->gauge_identity_status ? 1:300)*HZ))return ht->gauge_identity_status;
    if(ACPI_FAILURE(acpi_get_handle(NULL,"\\_SB.PC00.LPCB.H_EC",&ec)) || ec_get_handle()!=ec){ret=-ENODEV;goto cache;}
    if(ACPI_FAILURE(acpi_acquire_mutex(ec,"ECMT",1000))){ret=-EBUSY;goto cache;}
    ret=ht_gauge_strings_collect(&io,&ht->gauge_strings);
    acpi_release_mutex(ec,"ECMT");
    if(ret==-EUCLEAN){ht->charger_faulted=true;dev_err(ht->dev,"Battery identity IPC restoration failed%s; further controller requests disabled\n",ht_ipc_stall_note(&io.ipc));}
cache:
    if(ret)(void)ht_optional_recover(&ht->io,ret);
    ht->gauge_identity_status=ret;ht->gauge_identity_sampled=true;ht->gauge_identity_updated=jiffies;return ret;
}
static ssize_t battery_identity_show(struct device *dev,struct device_attribute *attr,char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    struct ht_gauge_strings *s=&ht->gauge_strings;
    int ret,len;
    mutex_lock(&ht->lock);
    ret=refresh_battery_identity(ht);if(ret)goto out;
    len=sysfs_emit(buf,"{\"schema\":1,\"maximum_cache_seconds\":300,\"age_milliseconds\":%u,\"device_type_hex\":\"",jiffies_to_msecs(jiffies-ht->gauge_identity_updated));
    len=emit_gauge_hex(buf,len,s->identity,2);
    len+=sysfs_emit_at(buf,len,"\",\"firmware_hex\":\"");len=emit_gauge_hex(buf,len,s->firmware,13);
    len+=sysfs_emit_at(buf,len,"\",\"manufacturer_hex\":\"");len=emit_gauge_hex(buf,len,s->manufacturer,s->lengths[0]);
    len+=sysfs_emit_at(buf,len,"\",\"model_hex\":\"");len=emit_gauge_hex(buf,len,s->model,s->lengths[1]);
    ret=len+sysfs_emit_at(buf,len,"\"}\n");
out:
    mutex_unlock(&ht->lock);return ret;
}
static DEVICE_ATTR(battery_identity,0400,battery_identity_show,NULL);
static ssize_t battery_gauge_metrics_show(struct device *dev,struct device_attribute *attr,char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    struct ht_gauge_sample *s=&ht->gauge_sample;
    int ret,len;
    mutex_lock(&ht->lock);
    ret=refresh_gauge(ht,false);if(ret)goto out;
    len=sysfs_emit(buf,"{\"schema\":1,\"maximum_cache_seconds\":5,\"age_milliseconds\":%u,\"device_type_hex\":\"",jiffies_to_msecs(jiffies-ht->gauge_updated));
    len=emit_gauge_hex(buf,len,s->identity,2);
    len+=sysfs_emit_at(buf,len,"\",\"firmware_hex\":\"");len=emit_gauge_hex(buf,len,s->firmware,13);
    len+=sysfs_emit_at(buf,len,"\",\"da1_hex\":\"");len=emit_gauge_hex(buf,len,s->da1,20);
    len+=sysfs_emit_at(buf,len,"\",\"da2_hex\":\"");len=emit_gauge_hex(buf,len,s->da2,14);
    ret=len+sysfs_emit_at(buf,len,"\"}\n");
out:
    mutex_unlock(&ht->lock);return ret;
}
static DEVICE_ATTR(battery_gauge_metrics,0400,battery_gauge_metrics_show,NULL);
static ssize_t battery_lifetime_show(struct device *dev,struct device_attribute *attr,char *buf)
{
    static const unsigned int lengths[]={31,4,4,31,31},names[]={1,2,3,4,5};
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    struct ht_gauge_full_lifetime *s=&ht->gauge_lifetime;
    unsigned int i;
    int ret,len;
    mutex_lock(&ht->lock);
    ret=refresh_gauge(ht,true);if(ret)goto out;
    len=sysfs_emit(buf,"{\"schema\":1,\"maximum_cache_seconds\":60,\"age_milliseconds\":%u,\"device_type_hex\":\"",jiffies_to_msecs(jiffies-ht->lifetime_updated));
    len=emit_gauge_hex(buf,len,s->identity,2);
    len+=sysfs_emit_at(buf,len,"\",\"firmware_hex\":\"");len=emit_gauge_hex(buf,len,s->firmware,13);
    for(i=0;i<5;i++) {
        len+=sysfs_emit_at(buf,len,"\",\"block%u_prefix_hex\":\"",names[i]);
        len=emit_gauge_hex(buf,len,s->blocks[i],lengths[i]);
    }
    len+=sysfs_emit_at(buf,len,"\",\"complete_blocks\":true");
    for(i=0;i<5;i++) {
        len+=sysfs_emit_at(buf,len,",\"block%u_hex\":\"",names[i]);
        len=emit_gauge_hex(buf,len,s->blocks[i],ht_gauge_block_lengths[i]);
        len+=sysfs_emit_at(buf,len,"\"");
    }
    ret=len+sysfs_emit_at(buf,len,"}\n");
out:
    mutex_unlock(&ht->lock);return ret;
}
static DEVICE_ATTR(battery_lifetime,0400,battery_lifetime_show,NULL);
static ssize_t battery_lifetime_refresh_store(struct device *dev,struct device_attribute *attr,const char *buf,size_t count)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    unsigned int value;
    int ret=kstrtouint(buf,10,&value);
    if(ret || value!=1)return -EINVAL;
    mutex_lock(&ht->lock);
    if (ht->removing) {
        mutex_unlock(&ht->lock);
        ht_audit(ht,"battery_lifetime_refresh: %d",-ENODEV);
        return -ENODEV;
    }
    ht->lifetime_sampled=false;
    ret=refresh_gauge(ht,true);
    mutex_unlock(&ht->lock);
    ht_audit(ht,"battery_lifetime_refresh: %d",ret);
    return ret ? ret:count;
}
static DEVICE_ATTR_WO(battery_lifetime_refresh);

static int ht_eeprom_buffer(struct zenbook_ht *ht)
{
    /* WMNB is Serialized on qualified .301. This exact recovered E5 read is
     * never reached unless the probe-time version query returned real data. */
    /* The actual ATK driver pads the two original scalar arguments to1024
     * zeroed bytes before IoWMIExecuteMethod. Preserve that input layout. */
    u32 *args;
    struct acpi_buffer input={HT_EEPROM_REPLY_MAX,NULL},output={ACPI_ALLOCATE_BUFFER,NULL};
    union acpi_object *object;
    acpi_status status;
    unsigned int length=0;
    int ret;
    if (!ht_eeprom_ready(ht->firmware_reply[1].status,ht->firmware_reply[1].raw)) {
        ht->eeprom_buffer_rejections++;
        return -EOPNOTSUPP;
    }
    input.pointer=kzalloc(input.length,GFP_KERNEL);
    if (!input.pointer)return -ENOMEM;
    args=input.pointer;args[0]=0x60059;args[1]=0xe5;
    ht->eeprom_buffer_calls++;
    status=wmi_evaluate_method(ASUS_WMI_MGMT_GUID,0,ASUS_WMI_METHODID_DEVS,&input,&output);
    kfree(input.pointer);
    if (ACPI_FAILURE(status)) {kfree(output.pointer);return -EIO;}
    object=output.pointer;
    if (!object) {ret=-ENODATA;goto out;}
    if (object->type==ACPI_TYPE_INTEGER) {
        ret=(u32)object->integer.value==ASUS_WMI_UNSUPPORTED_METHOD ? -EOPNOTSUPP:-EPROTO;
        goto out;
    }
    if (object->type!=ACPI_TYPE_BUFFER) {ret=-EPROTO;goto out;}
    ret=ht_eeprom_frame(object->buffer.pointer,object->buffer.length,&length);
    if (!ret) {
        memcpy(ht->oem_data,object->buffer.pointer,length);
        ht->oem_length=length;ht->oem_value=object->buffer.length;
    }
out:
    kfree(output.pointer);return ret;
}

static ssize_t oem_request_store(struct device *dev,struct device_attribute *attr,const char *buf,size_t count)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    u32 abi,op,index,value,flags,retval=0;
    u64 nonce;
    int ret;
    if (count!=32) return -EINVAL;
    abi=get_unaligned_le32(buf);op=get_unaligned_le32(buf+4);
    index=get_unaligned_le32(buf+8);value=get_unaligned_le32(buf+12);
    flags=get_unaligned_le32(buf+20);
    nonce=(u64)get_unaligned_le32(buf+24) | ((u64)get_unaligned_le32(buf+28)<<32);
    if (abi!=1 || get_unaligned_le32(buf+16)) return -EINVAL;
    ret=ht_oem_valid(op,index,value,flags);if (ret)return ret;
    mutex_lock(&ht->lock);
    ht->oem_nonce=nonce;ht->oem_op=op;ht->oem_length=0;ht->oem_value=0;
    if (ht->removing) {ht->oem_status=-ENODEV;goto out;}
    if (ht->manual_owned) {ht->oem_status=-EBUSY;goto out;}
    if (ht_oem_mutates(op) && !flags) {ht->oem_status=-EAGAIN;goto out;}
    if (op==HT_OEM_PD_SNAPSHOT) {
        ret=ht_read_pd(ht);
    } else if (op==HT_OEM_EEPROM_BUFFER) {
        ret=ht_eeprom_buffer(ht);
    } else if (op==HT_OEM_WMI_DSTS || op==HT_OEM_EEPROM) {
        ret=asus_wmi_evaluate_method(op==HT_OEM_WMI_DSTS ? ASUS_WMI_METHODID_DSTS : ASUS_WMI_METHODID_DEVS,
            op==HT_OEM_WMI_DSTS ? index : 0x60059,op==HT_OEM_WMI_DSTS ? value : index,&retval);
        ret=ht_oem_scalar_status(op,ret,retval);
        ht->oem_value=retval;
    } else {
        ret=ht_oem_ec(&ht->io,op,index,value,flags!=0,&ht->oem_value,ht->oem_data,&ht->oem_length);
        if (ret && ret!=-EAGAIN && ret!=-EPERM) (void)ht_optional_recover(&ht->io,ret);
    }
    ht->oem_status=ret;
    ht->telemetry_valid=false;
    /* Ops 11/13 are gated read-path EEPROM queries issued in bursts by one
     * table collection; keep them out of the notice log. */
    if (op==HT_OEM_EEPROM || op==HT_OEM_EEPROM_BUFFER)
        dev_dbg(ht->dev,"oem_request op %u index %#x applied: %d\n",op,index,ret);
    else if (ht_oem_mutates(op))
        ht_audit(ht,"oem_request op %u index %#x value %u applied: %d",op,index,value,ret);
out:
    mutex_unlock(&ht->lock);
    return count;
}
static DEVICE_ATTR_WO(oem_request);

struct ht_upc_output { char *buf; ssize_t len; unsigned int count; bool truncated; };

static acpi_status ht_usb_upc(acpi_handle handle, u32 level, void *context, void **retval)
{
    struct ht_upc_output *out=context;
    struct acpi_buffer result={ACPI_ALLOCATE_BUFFER,NULL};
    struct acpi_buffer path={ACPI_ALLOCATE_BUFFER,NULL};
    union acpi_object *obj;
    char *name;
    acpi_status status;
    u64 connectable,type;

    if (!acpi_has_method(handle,"_UPC")) return AE_OK;
    status=acpi_evaluate_object(handle,"_UPC",NULL,&result);
    if (ACPI_FAILURE(status)) return AE_OK;
    obj=result.pointer;
    if (!obj || obj->type!=ACPI_TYPE_PACKAGE || obj->package.count!=4 ||
        obj->package.elements[0].type!=ACPI_TYPE_INTEGER ||
        obj->package.elements[1].type!=ACPI_TYPE_INTEGER) goto free_result;
    connectable=obj->package.elements[0].integer.value;
    type=obj->package.elements[1].integer.value;
    if (type>255 || connectable>255) goto free_result;
    status=acpi_get_name(handle,ACPI_FULL_PATHNAME,&path);
    if (ACPI_FAILURE(status)) goto free_result;
    name=path.pointer;
    if (name[0]=='\\')name++;
    /* ACPI names have no JSON control characters. Reserve the closing array. */
    if (out->len+strlen(name)+100>=PAGE_SIZE) {
        out->truncated=true;
        kfree(path.pointer);kfree(result.pointer);return AE_CTRL_TERMINATE;
    }
    out->len+=scnprintf(out->buf+out->len,PAGE_SIZE-out->len,
        "%s{\"path\":\"%s\",\"connectable\":%llu,\"type\":%llu}",
        out->count ? "," : "",name,connectable,type);
    out->count++;
    kfree(path.pointer);
free_result:
    kfree(result.pointer);
    return AE_OK;
}

/* L4: _UPC is static firmware data. Walk the namespace once at probe (and on
 * an explicit diagnostics_reprobe) instead of on every unprivileged read.
 * Returns a PAGE_SIZE kmalloc buffer holding the unchanged JSON, or NULL. */
static char *ht_upc_build(void)
{
    struct ht_upc_output out={NULL,0,0,false};
    acpi_status status;
    out.buf=kzalloc(PAGE_SIZE,GFP_KERNEL);
    if (!out.buf) return NULL;
    out.len=scnprintf(out.buf,PAGE_SIZE,"{\"ports\":[");
    status=acpi_walk_namespace(ACPI_TYPE_DEVICE,ACPI_ROOT_OBJECT,ACPI_UINT32_MAX,
                              ht_usb_upc,NULL,&out,NULL);
    out.len+=scnprintf(out.buf+out.len,PAGE_SIZE-out.len,"],\"complete\":%s}\n",
        status==AE_OK && !out.truncated ? "true" : "false");
    return out.buf;
}

static ssize_t usb_connector_types_show(struct device *dev,struct device_attribute *attr,char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    ssize_t len;
    mutex_lock(&ht->lock);
    len=ht->upc_cache ? sysfs_emit(buf,"%s",ht->upc_cache) : -ENOMEM;
    mutex_unlock(&ht->lock);
    return len;
}
static DEVICE_ATTR_RO(usb_connector_types);
static ssize_t oem_response_show(struct device *dev,struct device_attribute *attr,char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    unsigned int i;int len;
    mutex_lock(&ht->lock);
    len=sysfs_emit(buf,"{\"abi\":1,\"nonce\":%llu,\"op\":%u,\"status\":%d,\"value\":%ld,\"data_hex\":\"",
        ht->oem_nonce,ht->oem_op,ht->oem_status,ht->oem_value);
    for(i=0;i<ht->oem_length;i++)len+=sysfs_emit_at(buf,len,"%02x",ht->oem_data[i]);
    len+=sysfs_emit_at(buf,len,"\"}\n");mutex_unlock(&ht->lock);return len;
}
static DEVICE_ATTR(oem_response,0400,oem_response_show,NULL);
static int ht_package_sample(struct zenbook_ht *ht,long *value)
{
    u32 low=0,high=0;
    u64 first=ktime_get_boottime_ns(),last,now;
    int ret;
    if (!ht->package_supported) return -EOPNOTSUPP;
    if (ht->package_valid && first/1000-ht->package_time_us<1000000) {
        *value=ht->package_power_uw;return 0;
    }
    ret=rdmsr_safe_on_cpu(0,MSR_PKG_ENERGY_STATUS,&low,&high);
    last=ktime_get_boottime_ns();now=(first+(last-first)/2)/1000;
    if (ret || high || last-first>10000000) {
        ht->package_initialized=false;ht->package_valid=false;
        return ret ? ret : high ? -EPROTO : -EAGAIN;
    }
    ret=ht->package_initialized ? ht_psys_uw(ht->package_energy,low,
        now-ht->package_time_us,ht->package_exponent,value) : -ENODATA;
    ht->package_before=ht->package_energy;
    ht->package_elapsed_us=now-ht->package_time_us;
    ht->package_energy=low;ht->package_time_us=now;ht->package_initialized=true;
    ht->package_valid=!ret;if (!ret)ht->package_power_uw=*value;
    return ret;
}

/* Process context only (sysfs/hwmon read under ht->lock): one bounded re-sample
 * after an idle re-prime, so every consumer sees a measurement on first read. */
static int ht_package_power(struct zenbook_ht *ht,long *value)
{
    int ret=ht_package_sample(ht,value);
    if (ht_energy_reprime(ret) && ht->package_initialized) {
        msleep(HT_ENERGY_REPRIME_MS);ret=ht_package_sample(ht,value);
    }
    return ret;
}

static ssize_t cpu_package_power_show(struct device *dev,struct device_attribute *attr,char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    long value;
    int ret;
    mutex_lock(&ht->lock);
    ret=ht_package_power(ht,&value);
    if (!ret)ret=sysfs_emit(buf,"{\"schema\":1,\"cpu\":0,\"energy_before\":%u,\"energy_after\":%u,\"energy_exponent\":%u,\"elapsed_microseconds\":%llu,\"power_microwatts\":%ld,\"maximum_cache_seconds\":1,\"age_microseconds\":%llu}\n",
        ht->package_before,ht->package_energy,ht->package_exponent,
        (unsigned long long)ht->package_elapsed_us,value,
        (unsigned long long)(ktime_get_boottime_ns()/1000-ht->package_time_us));
    mutex_unlock(&ht->lock);return ret;
}
static DEVICE_ATTR(cpu_package_power,0400,cpu_package_power_show,NULL);
static void ht_frequency_on_cpu(void *data)
{
    struct ht_frequency_sample *sample=data;
    u32 a,b,c,d;
    unsigned int i;
    cpuid(0,&a,&b,&c,&d);
    if (b!=0x756e6547 || d!=0x49656e69 || c!=0x6c65746e || a<0x16) {
        sample->error=-EOPNOTSUPP;return;
    }
    cpuid_count(0x16,0,&a,&b,&c,&d);
    sample->reference=c&0xffff;
    if (!sample->reference || sample->reference>1000) {
        sample->error=-ENODATA;return;
    }
    for (i=0;i<2;i++) {
        u32 low=0,high=0;
        sample->field_error[i]=rdmsr_safe(i ? 0x1ad : 0x198,&low,&high);
        sample->status[i]=((u64)high<<32)|low;
        if (!sample->field_error[i])
            sample->field_error[i]=ht_ratio_mhz(sample->status[i],i!=0,
                sample->reference,&sample->ratio[i],&sample->mhz[i]);
    }
}

static ssize_t cpu_reported_frequency_show(struct device *dev,
                                          struct device_attribute *attr,char *buf)
{
    struct zenbook_ht *ht=dev_get_drvdata(dev);
    struct ht_frequency_sample sample;
    ssize_t length;
    unsigned int i;
    int ret;
    /* L4: at most one CPU0 IPI per second, failures included. */
    mutex_lock(&ht->lock);
    if (!ht->frequency_sampled || time_after_eq(jiffies,ht->frequency_updated+HT_SAMPLE_CACHE)) {
        memset(&ht->frequency,0,sizeof(ht->frequency));
        ht->frequency_status=smp_call_function_single(0,ht_frequency_on_cpu,&ht->frequency,1);
        if (!ht->frequency_status) ht->frequency_status=ht->frequency.error;
        ht->frequency_updated=jiffies;ht->frequency_sampled=true;
    }
    sample=ht->frequency;ret=ht->frequency_status;
    mutex_unlock(&ht->lock);
    if (ret) return ret;
    length=sysfs_emit(buf,"{\"schema\":1,\"cpu\":0,\"reference_mhz\":%u",sample.reference);
    for (i=0;i<2;i++)
        length+=sysfs_emit_at(buf,length,",\"%s\":{\"errno\":%d,\"ratio\":%u,\"mhz\":%u,\"raw_msr_hex\":\"0x%016llx\"}",
            i ? "maximum" : "current",-sample.field_error[i],sample.ratio[i],sample.mhz[i],
            (unsigned long long)sample.status[i]);
    length+=sysfs_emit_at(buf,length,"}\n");
    return length;
}
static DEVICE_ATTR_RO(cpu_reported_frequency);

static struct attribute *ht_attrs[]={&dev_attr_cpu_package_power.attr,&dev_attr_cpu_reported_frequency.attr,&dev_attr_ec_telemetry.attr,&dev_attr_ec_diagnostics.attr,&dev_attr_fan_diagnostics.attr,&dev_attr_firmware_diagnostics.attr,
    &dev_attr_fault_state.attr,&dev_attr_battery_manufacturer.attr,&dev_attr_battery_model.attr,
    &dev_attr_battery_history.attr,&dev_attr_battery_history_refresh.attr,&dev_attr_battery_gauge_status.attr,
    &dev_attr_battery_information.attr,&dev_attr_battery_pf_cache.attr,&dev_attr_battery_cache_state.attr,&dev_attr_ec_chip_name.attr,
    &dev_attr_diagnostics_reprobe.attr,&dev_attr_oem_request.attr,&dev_attr_oem_response.attr,
    &dev_attr_usb_connector_types.attr,&dev_attr_pd_contract.attr,&dev_attr_pd_source_caps.attr,&dev_attr_charger_adc.attr,&dev_attr_charger_metrics.attr,&dev_attr_battery_gauge_metrics.attr,&dev_attr_battery_gauge_extra.attr,&dev_attr_battery_identity.attr,&dev_attr_battery_sbs.attr,&dev_attr_battery_sbs_diagnostics.attr,&dev_attr_battery_lifetime.attr,&dev_attr_battery_lifetime_refresh.attr,&dev_attr_pd_identity.attr,&dev_attr_pd_extended.attr,NULL};
ATTRIBUTE_GROUPS(ht);

static int ht_cpu_voltage(long *value)
{
    u32 low=0,high=0;
    int ret=rdmsr_safe_on_cpu(0,0x198,&low,&high);
    u64 status=((u64)high<<32)|low;
    return ret ? ret : ht_perf_status_mv(status,value);
}

/* Caller holds ht->lock. in6 stays world-readable (CPU-reported voltage is
 * deliberately public), but one PERF_STATUS IPI per second at most (L4). */
static int ht_cpu_voltage_cached(struct zenbook_ht *ht,long *value)
{
    if (!ht->cpu_mv_sampled || time_after_eq(jiffies,ht->cpu_mv_updated+HT_SAMPLE_CACHE)) {
        ht->cpu_mv_status=ht_cpu_voltage(&ht->cpu_mv);
        ht->cpu_mv_updated=jiffies;ht->cpu_mv_sampled=true;
    }
    if (!ht->cpu_mv_status) *value=ht->cpu_mv;
    return ht->cpu_mv_status;
}

/* Qualified Intel platform only; read hardware energy without programming
 * RAPL limits or a mailbox. This is platform power, not per-port USB-C current. */
static int ht_psys_sample(struct zenbook_ht *ht,long *value)
{
    u32 low,high;
    u64 now=ktime_get_boottime_ns()/1000;
    int ret;
    if (ht->psys_valid && now-ht->psys_time_us<1000000) {
        *value=ht->psys_power_uw;return 0;
    }
    ret=rdmsr_safe_on_cpu(0,MSR_PLATFORM_ENERGY_STATUS,&low,&high);
    if (ret || high) {ht->psys_initialized=false;ht->psys_valid=false;return ret ? ret : -EPROTO;}
    ret=ht->psys_initialized ? ht_psys_uw(ht->psys_energy,low,now-ht->psys_time_us,
                                       ht->psys_exponent,value) : -ENODATA;
    ht->psys_energy=low;ht->psys_time_us=now;ht->psys_initialized=true;
    ht->psys_valid=!ret;if (!ret)ht->psys_power_uw=*value;
    return ret;
}

static int ht_psys_power(struct zenbook_ht *ht,long *value)
{
    int ret=ht_psys_sample(ht,value);
    if (ht_energy_reprime(ret) && ht->psys_initialized) {
        msleep(HT_ENERGY_REPRIME_MS);ret=ht_psys_sample(ht,value);
    }
    return ret;
}

static umode_t ht_visible(const void *data, enum hwmon_sensor_types type,
                         u32 attr, int channel)
{
    const struct zenbook_ht *ht=data;
    /* Restricted to root (0400): every read below starts an EC broker/SMBus
     * session or samples RAPL/PSYS energy. Unprivileged consumers use the
     * org.zenbook.Hardware1 service. Labels follow their inputs. */
    if(type==hwmon_temp && channel==16 && (attr==hwmon_temp_input || attr==hwmon_temp_label))return 0400;
    if(type==hwmon_temp && channel>=9 && channel<16 && (attr==hwmon_temp_input || attr==hwmon_temp_label))return 0400;
    if ((type==hwmon_temp && channel==8 && (attr==hwmon_temp_input || attr==hwmon_temp_label)) ||
        (type==hwmon_in && (channel==8 || channel==9) && (attr==hwmon_in_input || attr==hwmon_in_label)) ||
        (type==hwmon_curr && (channel==3 || channel==4) && (attr==hwmon_curr_input || attr==hwmon_curr_label)))return 0400;
    if (((type==hwmon_in && channel==7 && (attr==hwmon_in_input || attr==hwmon_in_label)) ||
         (type==hwmon_curr && channel==2 && (attr==hwmon_curr_input || attr==hwmon_curr_label)) ||
         (type==hwmon_power && channel==1 && (attr==hwmon_power_input || attr==hwmon_power_label))))return 0400;
    if (type==hwmon_power && !channel && ht->psys_supported &&
        (attr==hwmon_power_input || attr==hwmon_power_label))return 0400;
    if (type==hwmon_power && channel==2 && ht->package_supported &&
        (attr==hwmon_power_input || attr==hwmon_power_label))return 0400;
    if (type==hwmon_temp && channel<8 && ht->supported_temp[channel] &&
        (attr==hwmon_temp_input || attr==hwmon_temp_label)) return 0444;
    if (type==hwmon_in && channel<7 && ht->supported_in[channel] &&
        (attr==hwmon_in_input || attr==hwmon_in_label)) return 0444;
    if (type==hwmon_curr && channel<2 && ht->supported_curr[channel] &&
        (attr==hwmon_curr_input || attr==hwmon_curr_label)) return 0444;
    if (channel != 0) return 0;
    if (type == hwmon_fan && (attr == hwmon_fan_input || attr == hwmon_fan_label)) return 0444;
    if (type == hwmon_pwm && (attr == hwmon_pwm_enable || attr == hwmon_pwm_input)) return 0644;
    if (type == hwmon_chip && attr == hwmon_chip_update_interval) return 0444;
    return 0;
}

static int ht_read_value(struct device *dev, enum hwmon_sensor_types type,
                         u32 attr, int channel, long *value)
{
    struct zenbook_ht *ht = dev_get_drvdata(dev);
    ht_byte mode = 255;
    int ret = -EOPNOTSUPP;
    if (channel < 0) return ret;
    if (type == hwmon_chip && attr == hwmon_chip_update_interval) {
        *value = 1000;
        return 0;
    }
    mutex_lock(&ht->lock);
    if (type==hwmon_in && attr==hwmon_in_input && channel==6) {
        ret=ht_cpu_voltage_cached(ht,value);
    } else if(type==hwmon_temp && channel==16 && attr==hwmon_temp_input) {
        ret=refresh_gauge_extra(ht);
        if(!ret) {
            *value=((unsigned int)ht->gauge_extra.da2[14] | ((unsigned int)ht->gauge_extra.da2[15]<<8))*100L-273150;
            if(*value < -40000 || *value > 125000)ret=-ENODATA;
        }
    } else if(type==hwmon_temp && channel>=9 && channel<16 && attr==hwmon_temp_input) {
        ret=refresh_gauge(ht,false);
        if(!ret) {
            unsigned int offset=2*(channel-9);
            long code=ht->gauge_sample.da2[offset] | ((unsigned int)ht->gauge_sample.da2[offset+1]<<8);
            *value=code*100-273150;
            if(*value < -40000 || *value > 125000)ret=-ENODATA;
        }
    } else if ((type==hwmon_temp && channel==8 && attr==hwmon_temp_input) ||
        (type==hwmon_in && (channel==8 || channel==9) && attr==hwmon_in_input) ||
        (type==hwmon_curr && (channel==3 || channel==4) && attr==hwmon_curr_input)) {
        unsigned int bit=type==hwmon_temp ? 1 : type==hwmon_in ? (channel==8 ? 4 : 2) : channel==3 ? 16 : 8;
        ret=refresh_charger_extra(ht);
        if(!ret && !(ht->charger_extra.valid_mask&bit))ret=-ENODATA;
        if(!ret)*value=type==hwmon_temp ? ht->charger_extra.die_mc : type==hwmon_in ?
            (channel==8 ? ht->charger_extra.system_mv : ht->charger_extra.vbat_mv) :
            ((channel==3 ? ht->charger_extra.charge_ua : ht->charger_extra.discharge_ua)+500)/1000;
    } else if ((type==hwmon_in && channel==7 && attr==hwmon_in_input) ||
        (type==hwmon_curr && channel==2 && attr==hwmon_curr_input) ||
        (type==hwmon_power && channel==1 && attr==hwmon_power_input)) {
        ret=refresh_charger(ht);
        if(!ret)*value=type==hwmon_in ? ht->charger.voltage_mv :
            type==hwmon_curr ? (ht->charger.current_ua+500)/1000 : ht->charger.power_uw;
    } else if (type==hwmon_power && !channel && attr==hwmon_power_input) {
        ret=ht_psys_power(ht,value);
    } else if (type==hwmon_power && channel==2 && attr==hwmon_power_input) {
        ret=ht_package_power(ht,value);
    } else if (type==hwmon_pwm && attr==hwmon_pwm_input) {
        *value=ht->requested_pwm; ret=0;
    } else if (type==hwmon_temp || type==hwmon_in || type==hwmon_curr) {
        static const int vin[]={4,13,14,15,16,7};
        ret=refresh_telemetry(ht);
        if (!ret && type==hwmon_temp && channel<8) {
            long raw=channel==0 ? ht->snapshot.value[0] : channel<6 ? ht->snapshot.board[channel-1] :
                channel==6 ? ht->snapshot.value[3] : ht->snapshot.value[1];
            ret=ht_temperature(raw,channel==6,value);
        } else if (!ret && type==hwmon_in && channel<6) {
            *value=ht->snapshot.value[vin[channel]];
            if (*value < (channel>0 && channel<5 ? 2000 : 4000) ||
                *value > (channel>0 && channel<5 ? 5000 : 20000)) ret=-ENODATA;
        } else if (!ret && type==hwmon_curr && channel<2) {
            *value=ht->snapshot.value[channel ? 6 : 5];
            if (*value<0) ret=-ENODATA;
            else if (!channel) *value=ht_signed_word(*value);
        }
    } else if (type == hwmon_fan && attr == hwmon_fan_input) {
        ret = refresh_rpm(ht, false);
        if (!ret) *value = ht->rpm;
    } else if (type == hwmon_pwm && attr == hwmon_pwm_enable) {
        ret = ht_read(&ht->io, 0x31, &mode);
        if (!ret) {
            if (mode == 0) *value = 2; /* Standard hwmon: automatic. */
            else if (mode == 1 && ht->manual_owned) *value = ht->requested_pwm==255 ? 0 : 1; /* Full speed. */
            else ret = -ENODATA;
        }
    }
    mutex_unlock(&ht->lock);
    return ret;
}

static int ht_read_label(struct device *dev, enum hwmon_sensor_types type,
                         u32 attr, int channel, const char **value)
{
    static const char * const temps[]={"EC CPU","SSD NTC","Ambient NTC","CPU NTC","Charger NTC","DDR NTC","Battery","EC GPU"};
    static const char * const volts[]={"Battery pack","Battery cell 1","Battery cell 2","Battery cell 3","Battery cell 4","Battery charge target","CPU voltage (MSR)"};
    static const char * const currents[]={"Battery signed current","Battery charge target"};
    if (type==hwmon_temp && attr==hwmon_temp_label && channel>=0 && channel<8) *value=temps[channel];
    else if(type==hwmon_temp && attr==hwmon_temp_label && channel==16)*value="Battery gauge algorithm";
    else if(type==hwmon_temp && attr==hwmon_temp_label && channel>=9 && channel<16) {
        static const char * const names[]={"Battery gauge internal","Battery TS1","Battery TS2","Battery TS3","Battery TS4","Battery cell (gauge)","Battery FET (gauge)"};
        *value=names[channel-9];
    }
    else if (type==hwmon_in && attr==hwmon_in_label && channel>=0 && channel<7) *value=volts[channel];
    else if (type==hwmon_curr && attr==hwmon_curr_label && channel>=0 && channel<2) *value=currents[channel];
    else if (type==hwmon_temp && attr==hwmon_temp_label && channel==8) *value="Charger die (ADC)";
    else if (type==hwmon_in && attr==hwmon_in_label && channel==8) *value="Charger system rail (ADC)";
    else if (type==hwmon_in && attr==hwmon_in_label && channel==9) *value="Charger VBAT pin (ADC)";
    else if (type==hwmon_curr && attr==hwmon_curr_label && channel==3) *value="Charger battery charge (ADC)";
    else if (type==hwmon_curr && attr==hwmon_curr_label && channel==4) *value="Charger battery discharge (ADC)";
    else if (type==hwmon_in && attr==hwmon_in_label && channel==7) *value="USB-C input voltage (ADC)";
    else if (type==hwmon_curr && attr==hwmon_curr_label && channel==2) *value="USB-C input current (ADC)";
    else if (type==hwmon_power && attr==hwmon_power_label && channel==1) *value="USB-C input power (ADC V*I)";
    else if (type==hwmon_fan && attr==hwmon_fan_label && channel==0) *value="CPU fan";
    else if (type==hwmon_power && attr==hwmon_power_label && channel==0) *value="Platform power (PSYS)";
    else if (type==hwmon_power && attr==hwmon_power_label && channel==2) *value="CPU package power (RAPL)";
    else return -EOPNOTSUPP;
    return 0;
}

static int ht_write_value(struct device *dev, enum hwmon_sensor_types type,
                          u32 attr, int channel, long value)
{
    struct zenbook_ht *ht = dev_get_drvdata(dev);
    ht_byte mode = 255;
    int ret;
    if (type!=hwmon_pwm || channel!=0) return -EINVAL;
    if (attr==hwmon_pwm_enable) { if (value<0 || value>2) return -EINVAL; }
    else if (attr==hwmon_pwm_input) { if (value<0 || value>255) return -ERANGE; }
    else return -EINVAL;
    cancel_delayed_work_sync(&ht->watchdog);
    mutex_lock(&ht->lock);
    if (ht->removing) {
        mutex_unlock(&ht->lock);
        ht_audit(ht, "%s=%ld refused during teardown: %d",
                 attr==hwmon_pwm_enable ? "pwm1_enable" : "pwm1", value, -ENODEV);
        return -ENODEV;
    }
    if (attr==hwmon_pwm_input) {
        if (ht->manual_owned) {
            ret=ht_write(&ht->io,0x35,value);
            if (ret) { (void)return_auto(ht); goto out; }
        }
        ht->requested_pwm=value;
        ht->rpm_valid=false;
        ret=0;
        goto out;
    }
    if (value == 2) {
        ret = return_auto(ht);
        goto out;
    }
    ret = ht_read(&ht->io, 0x31, &mode);
    if (ret) goto out;
    if (mode != 0 && !ht->manual_owned) { ret = -EBUSY; goto out; }
    ret = refresh_rpm(ht, true);
    if (ret) goto out;
    ht->minimum_rpm = ht_minimum_rpm(ht->rpm);
    /* Own restoration (and pin the module) even if the next write fails. */
    ret = ht_own_manual(ht);
    if (ret) goto out;
    if (value==0) ht->requested_pwm=255;
    ret = ht_manual(&ht->io,ht->requested_pwm);
    ht->rpm_valid = false;
    if (ret) {
        int restore = return_auto(ht);
        if (restore) dev_err(ht->dev, "Failed manual request and restoration: %d/%d\n", ret, restore);
    }
out:
    if (ht->manual_owned) schedule_delayed_work(&ht->watchdog, HZ);
    ht_audit(ht, "%s=%ld: %d, fan %s", attr==hwmon_pwm_enable ? "pwm1_enable" : "pwm1",
             value, ret, ht->manual_owned ? "driver-owned manual" : "automatic or not owned");
    mutex_unlock(&ht->lock);
    return ret;
}

static const struct hwmon_ops ht_ops = {
    .is_visible = ht_visible,
    .read = ht_read_value,
    .read_string = ht_read_label,
    .write = ht_write_value,
};
static const struct hwmon_channel_info * const ht_info[] = {
    HWMON_CHANNEL_INFO(chip, HWMON_C_UPDATE_INTERVAL),
    HWMON_CHANNEL_INFO(fan, HWMON_F_INPUT | HWMON_F_LABEL),
    HWMON_CHANNEL_INFO(pwm, HWMON_PWM_ENABLE | HWMON_PWM_INPUT),
    HWMON_CHANNEL_INFO(temp, HWMON_T_INPUT | HWMON_T_LABEL, HWMON_T_INPUT | HWMON_T_LABEL,
        HWMON_T_INPUT | HWMON_T_LABEL, HWMON_T_INPUT | HWMON_T_LABEL,
        HWMON_T_INPUT | HWMON_T_LABEL, HWMON_T_INPUT | HWMON_T_LABEL,
        HWMON_T_INPUT | HWMON_T_LABEL, HWMON_T_INPUT | HWMON_T_LABEL,
        HWMON_T_INPUT | HWMON_T_LABEL,
        HWMON_T_INPUT | HWMON_T_LABEL, HWMON_T_INPUT | HWMON_T_LABEL,
        HWMON_T_INPUT | HWMON_T_LABEL, HWMON_T_INPUT | HWMON_T_LABEL,
        HWMON_T_INPUT | HWMON_T_LABEL, HWMON_T_INPUT | HWMON_T_LABEL,
        HWMON_T_INPUT | HWMON_T_LABEL, HWMON_T_INPUT | HWMON_T_LABEL),
    HWMON_CHANNEL_INFO(in, HWMON_I_INPUT | HWMON_I_LABEL, HWMON_I_INPUT | HWMON_I_LABEL,
        HWMON_I_INPUT | HWMON_I_LABEL, HWMON_I_INPUT | HWMON_I_LABEL,
        HWMON_I_INPUT | HWMON_I_LABEL,
        HWMON_I_INPUT | HWMON_I_LABEL, HWMON_I_INPUT | HWMON_I_LABEL,
        HWMON_I_INPUT | HWMON_I_LABEL, HWMON_I_INPUT | HWMON_I_LABEL,
        HWMON_I_INPUT | HWMON_I_LABEL),
    HWMON_CHANNEL_INFO(curr, HWMON_C_INPUT | HWMON_C_LABEL, HWMON_C_INPUT | HWMON_C_LABEL,
        HWMON_C_INPUT | HWMON_C_LABEL, HWMON_C_INPUT | HWMON_C_LABEL,
        HWMON_C_INPUT | HWMON_C_LABEL),
    HWMON_CHANNEL_INFO(power, HWMON_P_INPUT | HWMON_P_LABEL, HWMON_P_INPUT | HWMON_P_LABEL,
        HWMON_P_INPUT | HWMON_P_LABEL),
    NULL
};
static const struct hwmon_chip_info ht_chip = {.ops = &ht_ops, .info = ht_info};

static const struct dmi_system_id supported[] = {
    {.matches = {
        DMI_EXACT_MATCH(DMI_SYS_VENDOR, "ASUSTeK COMPUTER INC."),
        DMI_EXACT_MATCH(DMI_PRODUCT_NAME, "Zenbook Flip UP3404VA_UP3404VA"),
        DMI_EXACT_MATCH(DMI_BIOS_VERSION, "UP3404VA.301"),
    }},
    {}
};

static void ht_upc_free(void *data)
{
    struct zenbook_ht *ht = data;
    kfree(ht->upc_cache);
    ht->upc_cache = NULL;
}

static int ht_probe(struct platform_device *pdev)
{
    struct zenbook_ht *ht;
    struct device *hwmon;
    ht_byte mode = 255;
    long converted;
    unsigned int i;
    u32 energy_low=0,energy_high=0;
    int ret;
    if (!dmi_check_system(supported)) return -ENODEV;
    ht = devm_kzalloc(&pdev->dev, sizeof(*ht), GFP_KERNEL);
    if (!ht) return -ENOMEM;
    if (!devm_request_region(&pdev->dev, PORT_DATA, 2, DRIVER)) return -EBUSY;
    ht->dev = &pdev->dev;
    ht->io = (struct ht_io){port_status, port_data, port_command, port_write,
                            port_now, port_pause, NULL, 5};
    mutex_init(&ht->lock);
    INIT_DELAYED_WORK(&ht->watchdog, fan_watchdog);
    ret = ht_identify(&ht->io);
    if (!ret) ret = ht_read(&ht->io, 0x31, &mode);
    if (!ret && mode != 0) ret = -EBUSY;
    if (!ret) ret = refresh_rpm(ht, true);
    if (ret) return dev_err_probe(&pdev->dev, ret, "HealthyTable probe refused\n");
    ht->requested_pwm=255;
    ret=refresh_telemetry(ht);
    if (ret) return dev_err_probe(&pdev->dev,ret,"Telemetry probe failed at field %u; retain prior driver\n",ht->snapshot.last_field);
    for(i=0;i<ARRAY_SIZE(ht_firmware_queries);i++) {
        const struct ht_firmware_recipe *q=&ht_firmware_queries[i];
        ht->firmware_reply[i].raw=0xffffffff;
        ht->firmware_reply[i].status=asus_wmi_evaluate_method(q->method,q->device,q->selector,
            &ht->firmware_reply[i].raw);
    }
    ht->supported_temp[0]=!ht_temperature(ht->snapshot.value[0],false,&converted);
    for (i=1;i<6;i++) ht->supported_temp[i]=!ht_temperature(ht->snapshot.board[i-1],false,&converted);
    ht->supported_temp[6]=!ht_temperature(ht->snapshot.value[3],true,&converted);
    ht->supported_temp[7]=!ht_temperature(ht->snapshot.value[1],false,&converted);
    ht->supported_in[0]=ht->snapshot.value[4]>=4000 && ht->snapshot.value[4]<=20000;
    for (i=1;i<5;i++) ht->supported_in[i]=ht->snapshot.value[12+i]>=2000 && ht->snapshot.value[12+i]<=5000;
    ht->supported_in[5]=ht->snapshot.value[7]>=4000 && ht->snapshot.value[7]<=20000;
    ht->supported_in[6]=!ht_cpu_voltage(&converted);
    ht->supported_curr[0]=ht->snapshot.value[5]>=0;
    ht->supported_curr[1]=ht->snapshot.value[6]>=0;
    if (!rdmsr_safe_on_cpu(0,MSR_RAPL_POWER_UNIT,&energy_low,&energy_high) && !energy_high) {
        ht->psys_exponent=(energy_low>>8)&31;
        ht->package_exponent=ht->psys_exponent;
        if (ht->package_exponent && !rdmsr_safe_on_cpu(0,MSR_PKG_ENERGY_STATUS,&energy_low,&energy_high) && !energy_high) {
            ht->package_supported=true;ht->package_initialized=true;ht->package_energy=energy_low;
            ht->package_time_us=ktime_get_boottime_ns()/1000;
        }
        if (ht->psys_exponent && !rdmsr_safe_on_cpu(0,MSR_PLATFORM_ENERGY_STATUS,&energy_low,&energy_high) &&
            energy_low && !energy_high) {
            ht->psys_supported=true;ht->psys_initialized=true;ht->psys_energy=energy_low;
            ht->psys_time_us=ktime_get_boottime_ns()/1000;
        }
    }
    /* Registered before hwmon, so devres frees the cache only after the
     * attribute files are gone. A failed walk allocation reads -ENOMEM. */
    ht->upc_cache = ht_upc_build();
    ret = devm_add_action_or_reset(&pdev->dev, ht_upc_free, ht);
    if (ret) return ret;
    hwmon = devm_hwmon_device_register_with_info(&pdev->dev, "zenbook_ec", ht, &ht_chip, ht_groups);
    if (IS_ERR(hwmon)) return PTR_ERR(hwmon);
    platform_set_drvdata(pdev, ht);
    dev_info(&pdev->dev, "HealthyTable 15, one fan, %ld RPM; automatic mode retained\n", ht->rpm);
    return 0;
}

#define HT_TEARDOWN_RESTORE_ATTEMPTS 3
#define HT_TEARDOWN_RESTORE_DELAY_MS 50

/*
 * Remove and shutdown. The hwmon and attribute files are devres-managed and
 * stay live until after this returns, so first refuse every write path and
 * stop the watchdog from being queued again, then make bounded attempts to
 * return the fan to firmware-automatic mode. ht_restore_owned() drains a
 * stale output byte and reads the mode back after each write.
 */
static void ht_remove(struct platform_device *pdev)
{
    struct zenbook_ht *ht = platform_get_drvdata(pdev);
    unsigned int attempt;
    int ret = 0;

    mutex_lock(&ht->lock);
    ht->removing = true;
    mutex_unlock(&ht->lock);
#if LINUX_VERSION_CODE >= KERNEL_VERSION(6,10,0)
    disable_delayed_work_sync(&ht->watchdog);
#else
    /* Writers and the watchdog check removing before queueing. */
    cancel_delayed_work_sync(&ht->watchdog);
#endif
    mutex_lock(&ht->lock);
    for (attempt = 0; ht->manual_owned && attempt < HT_TEARDOWN_RESTORE_ATTEMPTS; attempt++) {
        if (attempt)
            msleep(HT_TEARDOWN_RESTORE_DELAY_MS);
        ret = return_auto(ht);
        if (ret)
            dev_err(ht->dev, "Automatic fan restoration attempt %u failed: %d\n",
                    attempt + 1, ret);
    }
    if (ht->manual_owned) {
        dev_crit(ht->dev, "Automatic fan mode NOT verified after %u attempts (%d); fan may remain in manual mode without a watchdog\n",
                 HT_TEARDOWN_RESTORE_ATTEMPTS, ret);
        /* Nothing can restore it after teardown; drop the module pin. */
        ht_release_manual(ht);
    }
    mutex_unlock(&ht->lock);
}

static int ht_suspend(struct device *dev)
{
    struct zenbook_ht *ht = dev_get_drvdata(dev);
    int ret = 0;
    cancel_delayed_work_sync(&ht->watchdog);
    mutex_lock(&ht->lock);
    if (ht->manual_owned) ret = return_auto(ht);
    ht->rpm_valid = false;
    ht->telemetry_valid = false;
    ht->sbs_sampled=false;ht->gauge_identity_sampled=false;ht->gauge_extra_sampled=false;ht->identity_sampled=false;ht->extended_sampled=false;ht->gauge_sampled=false;ht->lifetime_sampled=false;ht->extra_sampled=false;ht->charger_sampled=false;ht->pd_valid=false;ht->pd_sources_valid=false;ht->psys_initialized=false;ht->psys_valid=false;ht->package_initialized=false;ht->package_valid=false;
    ht->diag_sampled=false;ht->frequency_sampled=false;ht->cpu_mv_sampled=false;
    if (ret && ht->manual_owned) schedule_delayed_work(&ht->watchdog,HZ);
    mutex_unlock(&ht->lock);
    return ret;
}

static int ht_resume(struct device *dev)
{
    struct zenbook_ht *ht = dev_get_drvdata(dev);
    mutex_lock(&ht->lock);
    ht->rpm_valid = false;
    ht->sbs_sampled=false;ht->gauge_identity_sampled=false;ht->gauge_extra_sampled=false;ht->identity_sampled=false;ht->extended_sampled=false;ht->gauge_sampled=false;ht->lifetime_sampled=false;ht->extra_sampled=false;ht->charger_sampled=false;ht->pd_valid=false;ht->pd_sources_valid=false;ht->psys_initialized=false;ht->psys_valid=false;ht->package_initialized=false;ht->package_valid=false;
    ht->diag_sampled=false;ht->frequency_sampled=false;ht->cpu_mv_sampled=false;
    mutex_unlock(&ht->lock);
    return 0;
}
static DEFINE_SIMPLE_DEV_PM_OPS(ht_pm, ht_suspend, ht_resume);
static struct platform_driver ht_driver = {
    .probe = ht_probe,
#if LINUX_VERSION_CODE >= KERNEL_VERSION(6,11,0)
    .remove = ht_remove,
#else
    .remove_new = ht_remove,
#endif
    .shutdown = ht_remove,
    /* H2: no sysfs unbind/bind; removal only via rmmod (blocked by the
     * module reference while the fan is driver-owned manual) or shutdown. */
    .driver = {.name = DRIVER, .pm = pm_sleep_ptr(&ht_pm), .suppress_bind_attrs = true},
};
static struct platform_device *ht_device;

static int __init ht_init(void)
{
    int ret;
    if (!dmi_check_system(supported)) return -ENODEV;
    ret = platform_driver_register(&ht_driver);
    if (ret) return ret;
    ht_device = platform_device_register_simple(DRIVER, -1, NULL, 0);
    if (IS_ERR(ht_device)) { ret = PTR_ERR(ht_device); goto unregister_driver; }
    if (platform_get_drvdata(ht_device)) return 0;
    platform_device_unregister(ht_device);
    ret = -ENODEV;
unregister_driver:
    platform_driver_unregister(&ht_driver);
    return ret;
}
static void __exit ht_exit(void)
{
    platform_device_unregister(ht_device);
    platform_driver_unregister(&ht_driver);
}
module_init(ht_init);
module_exit(ht_exit);
MODULE_LICENSE("GPL");
MODULE_AUTHOR("jc1122");
MODULE_DESCRIPTION("UP3404VA.301 ASUS HealthyTable fan/PWM, thermal, battery and adapter diagnostics");
MODULE_VERSION("0.85.0");
#if LINUX_VERSION_CODE >= KERNEL_VERSION(6,13,0)
MODULE_IMPORT_NS("ASUS_WMI");
#else
MODULE_IMPORT_NS(ASUS_WMI);
#endif
