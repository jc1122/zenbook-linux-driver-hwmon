#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Add the optional read-only charger rows to an existing Vitals extension."""
from pathlib import Path
import argparse,shutil,json,hashlib,os
# Provenance: the inserted blocks (integrations/vitals/*.js and *-method.txt)
# are this project's own work. The short anchor strings matched below (import
# lines, method signatures such as '    _queryBattery(callback) {\n', the
# 'hertz' case, 'destroy() {') are taken from the upstream Vitals extension
# (https://github.com/corecoding/Vitals, GPL-2.0 LICENSE; its source files also
# carry a BSD-style notice) and are used only to locate insertion points in an
# installed copy; no Vitals code is copied into this repository.
ROOT=Path(__file__).resolve().parents[1]
IMPORT="import {chargerRows} from './helpers/zenbook-charger.js';\n"
METRICS_METHOD="    _queryZenbookCharger(callback) {\n        if (this._zenbookChargerPending) return;\n        this._zenbookChargerPending = true;\n        const discover = this._zenbookChargerPath ? Promise.resolve(this._zenbookChargerPath) :\n            new FileModule.File('/sys/class/hwmon').list().then(files =>\n                Promise.all(files.map(async name => {\n                    const path = '/sys/class/hwmon/' + name;\n                    try { return (await new FileModule.File(path + '/name').read()).trim() === 'zenbook_ec' ? path : null; }\n                    catch (_) { return null; }\n                })).then(paths => paths.find(Boolean)));\n        discover.then(async path => {\n            if (!path) return;\n            this._zenbookChargerPath = path;\n            const [contract, power, adc, extra, sources] = await Promise.all([\n                new FileModule.File(path + '/pd_contract').read().then(x => JSON.parse(x)).catch(() => null),\n                new FileModule.File(path + '/power1_input').read().then(x => Number(x.trim())).catch(() => null),\n                new FileModule.File(path + '/charger_adc').read().then(x => JSON.parse(x)).catch(() => null),\n                new FileModule.File(path + '/charger_metrics').read().then(x => JSON.parse(x)).catch(() => null),\n                new FileModule.File(path + '/pd_source_caps').read().then(x => JSON.parse(x)).catch(() => null)\n            ]);\n            if (this._zenbookChargerDestroyed) return;\n            for (const row of [...chargerRows(contract, power, adc), ...chargerExtraRows(extra), ...pdSourceRows(sources)])\n                this._returnValue(callback, row.label, row.value, row.type, row.format);\n        }).catch(() => {\n            this._zenbookChargerPath = null;\n        }).finally(() => { this._zenbookChargerPending = false; });\n    }\n\n    _queryZenbookCPU(callback) {\n        if (this._zenbookCpuPending) return;\n        this._zenbookCpuPending = true;\n        new FileModule.File('/sys/devices/system/cpu').list().then(async names => {\n            const cpus = await Promise.all(names.filter(n => /^cpu[0-9]+$/.test(n)).map(async name => {\n                const values = await Promise.all(CPU_FIELDS.map(field =>\n                    new FileModule.File('/sys/devices/system/cpu/' + name + '/thermal_throttle/' + field).read().then(x => x.trim()).catch(() => null)));\n                return {cpu: Number(name.slice(3)), counters: Object.fromEntries(CPU_FIELDS.map((key, i) => [key, values[i]]))};\n            }));\n            if (this._zenbookChargerDestroyed) return;\n            for (const row of cpuRows(cpus, this._zenbookLastCpu || []))\n                this._returnValue(callback, row.label, row.value, row.type, row.format);\n            this._zenbookLastCpu = cpus;\n        }).catch(() => {\n            if (!this._zenbookChargerDestroyed) for (const row of cpuRows())\n                this._returnValue(callback, row.label, row.value, row.type, row.format);\n            this._zenbookLastCpu = [];\n        }).finally(() => { this._zenbookCpuPending = false; });\n    }\n\n    _queryZenbookSSD(callback) {\n        if (this._zenbookSsdPending) return;\n        this._zenbookSsdPending = true;\n        Promise.all([\n            new FileModule.File('/run/zenbook-hardware-metrics/ssd.json').read().then(x => JSON.parse(x)).catch(() => null),\n            new FileModule.File('/proc/uptime').read().then(x => Number(x.trim().split(/\\s+/)[0])).catch(() => NaN)\n        ]).then(([data, uptime]) => {\n            if (this._zenbookChargerDestroyed) return;\n            const names = Array.isArray(data?.devices) ? data.devices.filter(x => x && /^nvme[0-9]+n[0-9]+$/.test(x.device)).map(x => x.device) : [];\n            this._zenbookSsdDevices = [...new Set([...(this._zenbookSsdDevices || []), ...names])];\n            for (const row of ssdRows(data, uptime, this._zenbookSsdDevices))\n                this._returnValue(callback, row.label, row.value, row.type, row.format);\n        }).catch(() => {\n            if (!this._zenbookChargerDestroyed) for (const row of ssdRows(null, NaN, this._zenbookSsdDevices || []))\n                this._returnValue(callback, row.label, row.value, row.type, row.format);\n        }).finally(() => { this._zenbookSsdPending = false; });\n    }\n\n"
METHOD="    _queryZenbookCharger(callback) {\n        if (this._zenbookChargerPending) return;\n        this._zenbookChargerPending = true;\n        const discover = this._zenbookChargerPath ? Promise.resolve(this._zenbookChargerPath) :\n            new FileModule.File('/sys/class/hwmon').list().then(files =>\n                Promise.all(files.map(async name => {\n                    const path = '/sys/class/hwmon/' + name;\n                    try { return (await new FileModule.File(path + '/name').read()).trim() === 'zenbook_ec' ? path : null; }\n                    catch (_) { return null; }\n                })).then(paths => paths.find(Boolean)));\n        discover.then(async path => {\n            if (!path) return;\n            this._zenbookChargerPath = path;\n            this._queryZenbookGauge(path, callback);\n            const [contract, power, adc, extra, sources] = await Promise.all([\n                new FileModule.File(path + '/pd_contract').read().then(x => JSON.parse(x)).catch(() => null),\n                new FileModule.File(path + '/power1_input').read().then(x => Number(x.trim())).catch(() => null),\n                new FileModule.File(path + '/charger_adc').read().then(x => JSON.parse(x)).catch(() => null),\n                new FileModule.File(path + '/charger_metrics').read().then(x => JSON.parse(x)).catch(() => null),\n                new FileModule.File(path + '/pd_source_caps').read().then(x => JSON.parse(x)).catch(() => null)\n            ]);\n            if (this._zenbookChargerDestroyed) return;\n            for (const row of [...chargerRows(contract, power, adc), ...chargerExtraRows(extra), ...pdSourceRows(sources)])\n                this._returnValue(callback, row.label, row.value, row.type, row.format);\n        }).catch(() => {\n            this._zenbookChargerPath = null;\n        }).finally(() => { this._zenbookChargerPending = false; });\n    }\n\n    _queryZenbookCPU(callback) {\n        if (this._zenbookCpuPending) return;\n        this._zenbookCpuPending = true;\n        new FileModule.File('/sys/devices/system/cpu').list().then(async names => {\n            const cpus = await Promise.all(names.filter(n => /^cpu[0-9]+$/.test(n)).map(async name => {\n                const values = await Promise.all(CPU_FIELDS.map(field =>\n                    new FileModule.File('/sys/devices/system/cpu/' + name + '/thermal_throttle/' + field).read().then(x => x.trim()).catch(() => null)));\n                return {cpu: Number(name.slice(3)), counters: Object.fromEntries(CPU_FIELDS.map((key, i) => [key, values[i]]))};\n            }));\n            if (this._zenbookChargerDestroyed) return;\n            for (const row of cpuRows(cpus, this._zenbookLastCpu || []))\n                this._returnValue(callback, row.label, row.value, row.type, row.format);\n            this._zenbookLastCpu = cpus;\n        }).catch(() => {\n            if (!this._zenbookChargerDestroyed) for (const row of cpuRows())\n                this._returnValue(callback, row.label, row.value, row.type, row.format);\n            this._zenbookLastCpu = [];\n        }).finally(() => { this._zenbookCpuPending = false; });\n    }\n\n    _queryZenbookSSD(callback) {\n        if (this._zenbookSsdPending) return;\n        this._zenbookSsdPending = true;\n        Promise.all([\n            new FileModule.File('/run/zenbook-hardware-metrics/ssd.json').read().then(x => JSON.parse(x)).catch(() => null),\n            new FileModule.File('/proc/uptime').read().then(x => Number(x.trim().split(/\\s+/)[0])).catch(() => NaN)\n        ]).then(([data, uptime]) => {\n            if (this._zenbookChargerDestroyed) return;\n            const names = Array.isArray(data?.devices) ? data.devices.filter(x => x && /^nvme[0-9]+n[0-9]+$/.test(x.device)).map(x => x.device) : [];\n            this._zenbookSsdDevices = [...new Set([...(this._zenbookSsdDevices || []), ...names])];\n            for (const row of ssdRows(data, uptime, this._zenbookSsdDevices))\n                this._returnValue(callback, row.label, row.value, row.type, row.format);\n        }).catch(() => {\n            if (!this._zenbookChargerDestroyed) for (const row of ssdRows(null, NaN, this._zenbookSsdDevices || []))\n                this._returnValue(callback, row.label, row.value, row.type, row.format);\n        }).finally(() => { this._zenbookSsdPending = false; });\n    }\n\n    _queryZenbookGauge(path, callback) {\n        if (this._zenbookGaugePending) return;\n        this._zenbookGaugePending = true;\n        Promise.all([\n            new FileModule.File(path + '/battery_gauge_metrics').read().then(x => JSON.parse(x)).catch(() => null),\n            new FileModule.File(path + '/battery_lifetime').read().then(x => JSON.parse(x)).catch(() => null)\n        ]).then(([gauge, lifetime]) => {\n            if (this._zenbookChargerDestroyed) return;\n            for (const row of [...gaugeRows(gauge), ...lifetimeRows(lifetime)])\n                this._returnValue(callback, row.label, row.value, row.type, row.format);\n        }).catch(() => {\n            if (!this._zenbookChargerDestroyed) for (const row of [...gaugeRows(), ...lifetimeRows()])\n                this._returnValue(callback, row.label, row.value, row.type, row.format);\n        }).finally(() => { this._zenbookGaugePending = false; });\n    }\n\n"
BMS_IMPORT="import {gaugeRows, lifetimeRows} from './helpers/zenbook-battery.js';\n"
EXTRA_IMPORT="import {CPU_FIELDS, cpuRows, ssdRows, chargerExtraRows, pdSourceRows} from './helpers/zenbook-metrics.js';\n"
PREVIOUS_METHOD="    _queryZenbookCharger(callback) {\n        if (this._zenbookChargerPending) return;\n        this._zenbookChargerPending = true;\n        const discover = this._zenbookChargerPath ? Promise.resolve(this._zenbookChargerPath) :\n            new FileModule.File('/sys/class/hwmon').list().then(files =>\n                Promise.all(files.map(async name => {\n                    const path = '/sys/class/hwmon/' + name;\n                    try { return (await new FileModule.File(path + '/name').read()).trim() === 'zenbook_ec' ? path : null; }\n                    catch (_) { return null; }\n                })).then(paths => paths.find(Boolean)));\n        discover.then(async path => {\n            if (!path) return;\n            this._zenbookChargerPath = path;\n            const [contract, power, adc] = await Promise.all([\n                new FileModule.File(path + '/pd_contract').read().then(x => JSON.parse(x)).catch(() => null),\n                new FileModule.File(path + '/power1_input').read().then(x => Number(x.trim())).catch(() => null),\n                new FileModule.File(path + '/charger_adc').read().then(x => JSON.parse(x)).catch(() => null)\n            ]);\n            if (this._zenbookChargerDestroyed) return;\n            for (const row of chargerRows(contract, power, adc))\n                this._returnValue(callback, row.label, row.value, row.type, row.format);\n        }).catch(() => {\n            this._zenbookChargerPath = null;\n        }).finally(() => { this._zenbookChargerPending = false; });\n    }\n\n"
PREVIOUS_HELPER_SHA256='25067e119ed11d656d8953bf59a4695bd4108ad55fef12db7c2434fcbdff02e3'

AMP="""            case 'amp': // milliamps from the qualified EC monitoring cache
                value = value / 1000;
                format = '%.2f %s';
                ending = 'A';
                break;
"""

OLD_METHOD="    _queryZenbookCharger(callback) {\n        if (this._zenbookChargerPending) return;\n        this._zenbookChargerPending = true;\n        const discover = this._zenbookChargerPath ? Promise.resolve(this._zenbookChargerPath) :\n            new FileModule.File('/sys/class/hwmon').list().then(files =>\n                Promise.all(files.map(async name => {\n                    const path = '/sys/class/hwmon/' + name;\n                    try { return (await new FileModule.File(path + '/name').read()).trim() === 'zenbook_ec' ? path : null; }\n                    catch (_) { return null; }\n                })).then(paths => paths.find(Boolean)));\n        discover.then(async path => {\n            if (!path) return;\n            this._zenbookChargerPath = path;\n            const [contract, power] = await Promise.all([\n                new FileModule.File(path + '/pd_contract').read().then(x => JSON.parse(x)).catch(() => null),\n                new FileModule.File(path + '/power1_input').read().then(x => Number(x.trim())).catch(() => null)\n            ]);\n            if (this._zenbookChargerDestroyed) return;\n            for (const row of chargerRows(contract, power))\n                this._returnValue(callback, row.label, row.value, row.type, row.format);\n        }).catch(() => {\n            this._zenbookChargerPath = null;\n        }).finally(() => { this._zenbookChargerPending = false; });\n    }\n\n"
PREVIOUS_BATTERY_SHA256='d0d88910d3c1962ae538a73c304db34a77d0263904462cd1fae46dae0a7f93c6'
OLD_HELPER_SHA256='2be9aa15250fae947e140e3c94ff6e205012fdf67975e80ad5ad0c2d914685ba'

PREVIOUS_BMS_METHOD=METHOD
PREVIOUS_BMS_IMPORT=BMS_IMPORT
PREVIOUS_BMS_HELPER_SHA256='9751fb81396e45ac547922138d5c0fea6d278be8a548b052c232ee339b5d14e3'
PREVIOUS_ALERT_BATTERY_SHA256='df164c00bfea1d312ce061851ffdca0382aa58c309738aeae6d78ae1e5efdd1f'
BMS_IMPORT="import {gaugeRows, lifetimeRows, pdAlertRows} from './helpers/zenbook-battery.js';\n"
METHOD=METHOD.replace("new FileModule.File(path + '/battery_lifetime').read().then(x => JSON.parse(x)).catch(() => null)\n",
    "new FileModule.File(path + '/battery_lifetime').read().then(x => JSON.parse(x)).catch(() => null),\n            new FileModule.File(path + '/pd_identity').read().then(x => JSON.parse(x)).catch(() => null)\n")
METHOD=METHOD.replace('then(([gauge, lifetime])', 'then(([gauge, lifetime, identities])')
METHOD=METHOD.replace('[...gaugeRows(gauge), ...lifetimeRows(lifetime)]', '[...gaugeRows(gauge), ...lifetimeRows(lifetime), ...pdAlertRows(identities, chargerRows)]')
METHOD=METHOD.replace('[...gaugeRows(), ...lifetimeRows()]', '[...gaugeRows(), ...lifetimeRows(), ...pdAlertRows()]')

PREVIOUS_COMPLETE_METHOD=METHOD
PREVIOUS_COMPLETE_IMPORT=BMS_IMPORT
PREVIOUS_COMPLETE_HELPER_SHA256='1cfb3bc63674c4ce3476288c72cab2973a77d6734a795ff1e12d64b3064aec67'
BMS_IMPORT="import {gaugeRows, gaugeExtraRows, lifetimeRows, pdAlertRows} from './helpers/zenbook-battery.js';\n"
METHOD=METHOD.replace("new FileModule.File(path + '/pd_identity').read().then(x => JSON.parse(x)).catch(() => null)\n",
    "new FileModule.File(path + '/pd_identity').read().then(x => JSON.parse(x)).catch(() => null),\n            new FileModule.File(path + '/battery_gauge_extra').read().then(x => JSON.parse(x)).catch(() => null)\n")
METHOD=METHOD.replace('then(([gauge, lifetime, identities])','then(([gauge, lifetime, identities, extras])')
METHOD=METHOD.replace('[...gaugeRows(gauge), ...lifetimeRows(lifetime)', '[...gaugeRows(gauge), ...gaugeExtraRows(extras), ...lifetimeRows(lifetime)')
METHOD=METHOD.replace('[...gaugeRows(), ...lifetimeRows()', '[...gaugeRows(), ...gaugeExtraRows(), ...lifetimeRows()')

PREVIOUS_EXTRA_METHOD=METHOD
PREVIOUS_EXTRA_IMPORT=BMS_IMPORT
PREVIOUS_EXTRA_HELPER_SHA256='1696eb8fe295da1bb21fe4713efb619874b0d67898a566ac3a99daded00a894a'
BMS_IMPORT=BMS_IMPORT.replace('gaugeRows, gaugeExtraRows,','gaugeRows, gaugeExtraRows, sbsRows,')
METHOD=METHOD.replace("new FileModule.File(path + '/battery_gauge_extra').read().then(x => JSON.parse(x)).catch(() => null)\n",
    "new FileModule.File(path + '/battery_gauge_extra').read().then(x => JSON.parse(x)).catch(() => null),\n            new FileModule.File(path + '/battery_sbs').read().then(x => JSON.parse(x)).catch(() => null)\n")
METHOD=METHOD.replace('then(([gauge, lifetime, identities, extras])','then(([gauge, lifetime, identities, extras, sbs])')
METHOD=METHOD.replace('...gaugeExtraRows(extras),','...gaugeExtraRows(extras), ...sbsRows(sbs),')
METHOD=METHOD.replace('...gaugeExtraRows(),','...gaugeExtraRows(), ...sbsRows(),')

PREVIOUS_SBS_HELPER_SHA256='9b79f09b493fe2a5d6649a7efd463f3fa526ee9d280565b20bb3eb0229b75a90'

# 0.79: driver attributes that start EC broker sessions or sample RAPL/PSYS
# energy are root-only. The reviewed 0.78 block read them directly; the new
# block takes them from the org.zenbook.Hardware1 Metrics() reply instead.
FILE_METHOD=METHOD
METHOD=(ROOT/'integrations/vitals/charger-method.txt').read_text()
SERVICE_IMPORT="import {metricsSource, dbusMetricsCall, serviceInputs} from './helpers/zenbook-service.js';\n"
# Installed 0.78 helpers (unchanged in 0.79; accepted explicitly as reviewed).
PREVIOUS_FILE_CHARGER_SHA256='25067e119ed11d656d8953bf59a4695bd4108ad55fef12db7c2434fcbdff02e3'
PREVIOUS_FILE_METRICS_SHA256='23e7af72cb2b135fb59074a4e791b3b12e562533b71140d0243300ebf5398e74'
PREVIOUS_FILE_BATTERY_SHA256='fb7407d9b744daa94d1a3c4aefa321a02b4fe669cc52776535d4a8e69a451075'

PREVIOUS_RUNTIME_HELPER_SHA256='3cbb1c714f5287bb32c256bb8c70b960275ef90364b5b1bba4e08bd674737a74'
PREVIOUS_REGION_HELPER_SHA256='eb536e4b92e23cc62e641e8f8399927b371b235e6fbb12b45a5974494122d4f5'
PREVIOUS_GAUGE_POWER_HELPER_SHA256='4f054f87626c7376043c11b19a1ee3a40e46e53d1a6ac17b8b4a3fb75588c914'
PREVIOUS_BALANCING_HELPER_SHA256='ae0604b93b05928078796c546b055ef64238eb86fae9940e91fb859bed1f8b6a'

def replaced_once(text,old,new):
    if text.count(old)!=1:raise RuntimeError('Unsupported Vitals source layout; anchor must occur exactly once: '+old[:60])
    return text.replace(old,new,1)

PREVIOUS_FIXED_ACTIVE_METRICS_SHA256='0df60792d366da693141c09cd0f4fce41f323c3296c5b3ae36f86713ad287cf0'

def reviewed_metrics(extension,new):
    data=(extension/'helpers/zenbook-metrics.js').read_bytes()
    return data==new or hashlib.sha256(data).hexdigest() in (PREVIOUS_FIXED_ACTIVE_METRICS_SHA256,PREVIOUS_FILE_METRICS_SHA256)

def reviewed_charger(data,new):
    return data==new or hashlib.sha256(data).hexdigest()==PREVIOUS_FILE_CHARGER_SHA256

def base_plan(extension,sensors_override=None):
    sensors=(extension/'sensors.js').read_text() if sensors_override is None else sensors_override
    values=(extension/'values.js').read_text()
    new=(ROOT/'integrations/vitals/charger.js').read_bytes()
    extra=(ROOT/'integrations/vitals/metrics.js').read_bytes()
    battery=(ROOT/'integrations/vitals/battery.js').read_bytes()
    changes={}
    if IMPORT in sensors:
        helper=(extension/'helpers/zenbook-charger.js').read_bytes()
        if PREVIOUS_EXTRA_METHOD in sensors and EXTRA_IMPORT in sensors and PREVIOUS_EXTRA_IMPORT in sensors:
            current=(extension/'helpers/zenbook-battery.js').read_bytes()
            if not reviewed_charger(helper,new) or not reviewed_metrics(extension,extra) or hashlib.sha256(current).hexdigest()!=PREVIOUS_EXTRA_HELPER_SHA256:
                raise RuntimeError('The previous gauge-extra integration has local changes.')
            sensors=replaced_once(sensors,PREVIOUS_EXTRA_METHOD,FILE_METHOD)
            sensors=replaced_once(sensors,PREVIOUS_EXTRA_IMPORT,BMS_IMPORT)
            return {'sensors.js':sensors.encode(),'helpers/zenbook-battery.js':battery}
        if PREVIOUS_COMPLETE_METHOD in sensors and EXTRA_IMPORT in sensors and PREVIOUS_COMPLETE_IMPORT in sensors:
            current=(extension/'helpers/zenbook-battery.js').read_bytes()
            if not reviewed_charger(helper,new) or not reviewed_metrics(extension,extra) or hashlib.sha256(current).hexdigest() not in (PREVIOUS_COMPLETE_HELPER_SHA256,PREVIOUS_ALERT_BATTERY_SHA256):
                raise RuntimeError('The previous complete-block integration has local changes.')
            sensors=replaced_once(sensors,PREVIOUS_COMPLETE_METHOD,FILE_METHOD)
            sensors=replaced_once(sensors,PREVIOUS_COMPLETE_IMPORT,BMS_IMPORT)
            return {'sensors.js':sensors.encode(),'helpers/zenbook-battery.js':battery}
        if PREVIOUS_BMS_METHOD in sensors and EXTRA_IMPORT in sensors and PREVIOUS_BMS_IMPORT in sensors:
            current=(extension/'helpers/zenbook-battery.js').read_bytes()
            if not reviewed_charger(helper,new) or not reviewed_metrics(extension,extra) or hashlib.sha256(current).hexdigest() not in (PREVIOUS_BMS_HELPER_SHA256,PREVIOUS_BATTERY_SHA256):
                raise RuntimeError('The previous battery integration has local changes.')
            sensors=replaced_once(sensors,PREVIOUS_BMS_METHOD,FILE_METHOD)
            sensors=replaced_once(sensors,PREVIOUS_BMS_IMPORT,BMS_IMPORT)
            return {'sensors.js':sensors.encode(),'helpers/zenbook-battery.js':battery}
        if FILE_METHOD in sensors and EXTRA_IMPORT in sensors and BMS_IMPORT in sensors:
            if not reviewed_charger(helper,new) or not reviewed_metrics(extension,extra):
                raise RuntimeError('The installed metrics helper has local changes.')
            current=(extension/'helpers/zenbook-battery.js').read_bytes()
            if current==battery:return {}
            if hashlib.sha256(current).hexdigest() not in (PREVIOUS_FILE_BATTERY_SHA256,PREVIOUS_BALANCING_HELPER_SHA256,PREVIOUS_GAUGE_POWER_HELPER_SHA256,PREVIOUS_REGION_HELPER_SHA256,PREVIOUS_RUNTIME_HELPER_SHA256,PREVIOUS_SBS_HELPER_SHA256,PREVIOUS_BATTERY_SHA256,PREVIOUS_BMS_HELPER_SHA256,PREVIOUS_ALERT_BATTERY_SHA256):
                raise RuntimeError('The installed battery helper has local changes.')
            return {'helpers/zenbook-battery.js':battery}
        if METRICS_METHOD in sensors and EXTRA_IMPORT in sensors:
            if not reviewed_charger(helper,new) or not reviewed_metrics(extension,extra):
                raise RuntimeError('The previous metrics helper has local changes.')
            sensors=replaced_once(sensors,METRICS_METHOD,FILE_METHOD)
            sensors=replaced_once(sensors,EXTRA_IMPORT,EXTRA_IMPORT+BMS_IMPORT)
            return {'sensors.js':sensors.encode(),'helpers/zenbook-battery.js':battery}
        digest=hashlib.sha256(helper).hexdigest()
        old=PREVIOUS_METHOD if digest==PREVIOUS_HELPER_SHA256 and PREVIOUS_METHOD in sensors else \
            OLD_METHOD if digest==OLD_HELPER_SHA256 and OLD_METHOD in sensors else None
        if old is None:raise RuntimeError('A different charger integration already exists.')
        sensors=replaced_once(sensors,old,FILE_METHOD)
        sensors=replaced_once(sensors,IMPORT,IMPORT+EXTRA_IMPORT+BMS_IMPORT)
    else:
        sensors=replaced_once(sensors,"import * as FileModule from './helpers/file.js';\n","import * as FileModule from './helpers/file.js';\n"+IMPORT+EXTRA_IMPORT+BMS_IMPORT)
        sensors=replaced_once(sensors,'    _queryBattery(callback) {\n',FILE_METHOD+'    _queryBattery(callback) {\n        this._queryZenbookCharger(callback);\n')
        sensors=replaced_once(sensors,'    destroy() {\n','    destroy() {\n        this._zenbookChargerDestroyed = true;\n')
        values=replaced_once(values,"            case 'hertz':\n",AMP+"            case 'hertz':\n")
        changes['values.js']=values.encode()
    sensors=replaced_once(sensors,'    _queryProcessor(callback, dwell) {\n','    _queryProcessor(callback, dwell) {\n        this._queryZenbookCPU(callback);\n')
    sensors=replaced_once(sensors,'    _queryStorage(callback, dwell) {\n','    _queryStorage(callback, dwell) {\n        this._queryZenbookSSD(callback);\n')
    changes.update({'sensors.js':sensors.encode(),'helpers/zenbook-charger.js':new,'helpers/zenbook-metrics.js':extra,'helpers/zenbook-battery.js':battery})
    return changes


SERVICE_HELPER='helpers/zenbook-service.js'

def service_plan(extension,sensors_override=None):
    """Move root-only readings (0.79) from direct sysfs reads to the service reply."""
    original=(extension/'sensors.js').read_text() if sensors_override is None else sensors_override
    sensors=original
    helper=extension/SERVICE_HELPER;new=(ROOT/'integrations/vitals/service.js').read_bytes()
    if SERVICE_IMPORT in sensors:
        if not helper.exists() or helper.read_bytes()!=new:raise RuntimeError('The installed service helper has local changes.')
        sensors=replaced_once(sensors,SERVICE_IMPORT,'')
        sensors=replaced_once(sensors,METHOD,FILE_METHOD)
    elif helper.exists() or 'zenbook-service.js' in sensors or '_zenbookServiceMetrics' in sensors:
        raise RuntimeError('A different service integration already exists.')
    changes=base_plan(extension,sensors)
    sensors=changes.get('sensors.js',sensors.encode()).decode()
    sensors=replaced_once(sensors,BMS_IMPORT,BMS_IMPORT+SERVICE_IMPORT)
    sensors=replaced_once(sensors,FILE_METHOD,METHOD)
    if sensors!=original:changes['sensors.js']=sensors.encode()
    else:changes.pop('sensors.js',None)
    if not helper.exists() or helper.read_bytes()!=new:changes[SERVICE_HELPER]=new
    charger=extension/'helpers/zenbook-charger.js';new_charger=(ROOT/'integrations/vitals/charger.js').read_bytes()
    if 'helpers/zenbook-charger.js' not in changes and charger.exists() and charger.read_bytes()!=new_charger:
        changes['helpers/zenbook-charger.js']=new_charger  # base_plan accepted it as a reviewed version
    return changes


WIRELESS_IMPORT="import {wirelessRows} from './helpers/zenbook-wireless.js';\n"
WIRELESS_CALL='        this._queryZenbookWireless(callback);\n'
WIRELESS_DESTROY='        this._zenbookWirelessProcess?.force_exit();\n'
WIRELESS_METHOD=(ROOT/'integrations/vitals/wireless-method.txt').read_text()

def wireless_plan(extension,sensors_override=None):
    original=(extension/'sensors.js').read_text() if sensors_override is None else sensors_override
    sensors=original
    helper=extension/'helpers/zenbook-wireless.js'
    new=(ROOT/'integrations/vitals/wireless.js').read_bytes()
    if WIRELESS_IMPORT in sensors:
        if not helper.exists() or helper.read_bytes()!=new:
            raise RuntimeError('The installed wireless helper has local changes.')
        for part in (WIRELESS_IMPORT,WIRELESS_METHOD,WIRELESS_CALL):sensors=replaced_once(sensors,part,'')
        if WIRELESS_DESTROY in sensors:sensors=replaced_once(sensors,WIRELESS_DESTROY,'')
    elif helper.exists() or '_queryZenbookWireless' in sensors:
        raise RuntimeError('A different wireless integration already exists.')
    changes=service_plan(extension,sensors)
    sensors=changes.get('sensors.js',sensors.encode()).decode()
    sensors=replaced_once(sensors,IMPORT,IMPORT+WIRELESS_IMPORT)
    sensors=replaced_once(sensors,'    _queryZenbookCharger(callback) {\n',WIRELESS_METHOD+'    _queryZenbookCharger(callback) {\n')
    network='    _queryNetwork(callback, dwell) {\n'
    # Complete Vitals sources refresh with Network, independent of Battery.
    # Older minimal migration fixtures contain only the managed battery method.
    anchor=network if network in sensors else '    _queryZenbookCharger(callback) {\n'
    sensors=replaced_once(sensors,anchor,anchor+WIRELESS_CALL)
    destroy='        this._zenbookChargerDestroyed = true;\n'
    if destroy in sensors:sensors=replaced_once(sensors,destroy,destroy+WIRELESS_DESTROY)
    if sensors!=original:changes['sensors.js']=sensors.encode()
    else:changes.pop('sensors.js',None)
    if not helper.exists():changes['helpers/zenbook-wireless.js']=new
    return changes


PREVIOUS_FAN_HELPER_SHA256='2f0b8645579b22e80223529d2752bb7cbffaa05da809f1a09f5bf0c816121bcb'
FAN_IMPORT="import {fanRows} from './helpers/zenbook-fan.js';\n"
FAN_METHOD=(ROOT/'integrations/vitals/fan-method.txt').read_text()
FAN_CALL="        if (type === 'fan' && (!wantedKeys || [...wantedKeys].some(key => /fan_ec_duty_code|fan_ec_control/.test(key)))) this._queryZenbookFan(callback);\n"
FAN_FALLBACK='        this._queryZenbookFan(callback);\n'

def fan_plan(extension,sensors_override=None):
    original=(extension/'sensors.js').read_text() if sensors_override is None else sensors_override;sensors=original
    helper=extension/'helpers/zenbook-fan.js';new=(ROOT/'integrations/vitals/fan.js').read_bytes()
    if FAN_IMPORT in sensors:
        if not helper.exists() or helper.read_bytes()!=new and hashlib.sha256(helper.read_bytes()).hexdigest()!=PREVIOUS_FAN_HELPER_SHA256:raise RuntimeError('The installed fan helper has local changes.')
        for part in (FAN_IMPORT,FAN_METHOD):sensors=replaced_once(sensors,part,'')
        sensors=replaced_once(sensors,FAN_CALL if FAN_CALL in sensors else FAN_FALLBACK,'')
    elif helper.exists() or '_queryZenbookFan' in sensors:raise RuntimeError('A different fan integration already exists.')
    changes=wireless_plan(extension,sensors)
    sensors=changes.get('sensors.js',sensors.encode()).decode()
    sensors=replaced_once(sensors,IMPORT,IMPORT+FAN_IMPORT)
    sensors=replaced_once(sensors,'    _queryZenbookCharger(callback) {\n',FAN_METHOD+'    _queryZenbookCharger(callback) {\n')
    anchor='    _queryTempVoltFan(callback, type, wantedKeys) {\n'
    if anchor in sensors:sensors=replaced_once(sensors,anchor,anchor+FAN_CALL)
    else:sensors=replaced_once(sensors,'    _queryZenbookCharger(callback) {\n','    _queryZenbookCharger(callback) {\n'+FAN_FALLBACK)
    if sensors!=original:changes['sensors.js']=sensors.encode()
    else:changes.pop('sensors.js',None)
    if not helper.exists() or helper.read_bytes()!=new:changes['helpers/zenbook-fan.js']=new
    return changes


PREVIOUS_FREQUENCY_IMPORT="import {frequencyRows} from './helpers/zenbook-frequency.js';\n"
PREVIOUS_FREQUENCY_METHOD=(ROOT/'integrations/vitals/frequency-method-v1.txt').read_text()
PREVIOUS_FREQUENCY_HELPER_SHA256='88ffab2eb1088f614275f87c69901869fc580c79bfaaa77644d72a69b9e1916e'
FREQUENCY_IMPORT="import {frequencyRows, packagePowerRows} from './helpers/zenbook-frequency.js';\n"
FREQUENCY_METHOD=(ROOT/'integrations/vitals/frequency-method.txt').read_text()
PREVIOUS_FILE_FREQUENCY_METHOD=(ROOT/'integrations/vitals/frequency-method-v2.txt').read_text()
PREVIOUS_FILE_FREQUENCY_HELPER_SHA256='22d7cfa7795da96135a71621e4ddc7a3f923a3ad5d04d613f7cd4811892cd6e2'
FREQUENCY_CALL='        this._queryZenbookFrequency(callback);\n'

def plan(extension):
    original=(extension/'sensors.js').read_text();sensors=original
    helper=extension/'helpers/zenbook-frequency.js';new=(ROOT/'integrations/vitals/frequency.js').read_bytes()
    previous=PREVIOUS_FREQUENCY_IMPORT in sensors
    if previous and FREQUENCY_IMPORT in sensors:raise RuntimeError('Conflicting frequency integrations exist.')
    if FREQUENCY_IMPORT in sensors or previous:
        file_method=not previous and FREQUENCY_METHOD not in sensors and PREVIOUS_FILE_FREQUENCY_METHOD in sensors
        digest=hashlib.sha256(helper.read_bytes()).hexdigest() if helper.exists() else None
        if not helper.exists() or (digest!=PREVIOUS_FREQUENCY_HELPER_SHA256 if previous else
                                   helper.read_bytes()!=new and not (file_method and digest==PREVIOUS_FILE_FREQUENCY_HELPER_SHA256)):
            raise RuntimeError('The installed frequency helper has local changes.')
        method=PREVIOUS_FREQUENCY_METHOD if previous else PREVIOUS_FILE_FREQUENCY_METHOD if file_method else FREQUENCY_METHOD
        for part in ((PREVIOUS_FREQUENCY_IMPORT if previous else FREQUENCY_IMPORT),method,FREQUENCY_CALL):sensors=replaced_once(sensors,part,'')
    elif helper.exists() or '_queryZenbookFrequency' in sensors:raise RuntimeError('A different frequency integration already exists.')
    changes=fan_plan(extension,sensors)
    sensors=changes.get('sensors.js',sensors.encode()).decode()
    sensors=replaced_once(sensors,IMPORT,IMPORT+FREQUENCY_IMPORT)
    sensors=replaced_once(sensors,'    _queryZenbookCharger(callback) {\n',FREQUENCY_METHOD+'    _queryZenbookCharger(callback) {\n')
    anchor='    _queryZenbookCPU(callback) {\n'
    sensors=replaced_once(sensors,anchor,anchor+FREQUENCY_CALL)
    if sensors!=original:changes['sensors.js']=sensors.encode()
    else:changes.pop('sensors.js',None)
    if not helper.exists() or helper.read_bytes()!=new:changes['helpers/zenbook-frequency.js']=new
    metrics=extension/'helpers/zenbook-metrics.js';new_metrics=(ROOT/'integrations/vitals/metrics.js').read_bytes()
    if metrics.exists() and metrics.read_bytes()!=new_metrics:
        if not reviewed_metrics(extension,new_metrics):raise RuntimeError('The installed metrics helper has local changes.')
        changes['helpers/zenbook-metrics.js']=new_metrics
    return changes


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extension',type=Path,default=Path.home()/'.local/share/gnome-shell/extensions/Vitals@CoreCoding.com')
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    changes=plan(args.extension)
    if args.apply and changes:
        args.backup.mkdir(parents=True,exist_ok=False,mode=0o700)
        for name,data in changes.items():
            path=args.extension/name
            if path.exists():
                destination=args.backup/name;destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(path,destination)
            path.write_bytes(data)
            if path.read_bytes()!=data:raise RuntimeError('Integration readback failed.')
    print(json.dumps({'applied':args.apply,'files':{n:hashlib.sha256(b).hexdigest() for n,b in changes.items()},'backup':str(args.backup)},indent=2))

if __name__=='__main__':main()
