# SPDX-License-Identifier: GPL-2.0-only
"""Dispatch for the remaining ASUS service and OEM exports.

The Linux API returns structured native values. Platform absence is reported
as a runtime error, rather than substituting a guessed sensor or OS result.
"""
from pathlib import Path
import errno
import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import importlib.util
from types import SimpleNamespace
import efi_oem
import linux_services
import specialty_thermal
import adapter_ratings
import adapter_diagnostics
import firmware_queries
import hardware_status
import usb_power
import native_oem
import pd_sources
import pd_identity
import battery_diagnostics
import battery_identity
import xgm_hid
import wwan
import wireless
import field_reads
import remembered_controls

VERSION='0.85.0'
HERE=Path(__file__).resolve().parent
EFI_NAMES=set(efi_oem.READS)|set(efi_oem.WRITES)
NATIVE_NAMES=set(native_oem.MUTATIONS)|{'WOA_EC_read','Adapter_Read_PD_IC_PN','Adapter_Read_Contract_PDO','CPU_ReadCpuVoltage'}
LIFECYCLE={'InitializeWinIo','ShutdownWinIo','StopWinIoDriver','GetRefCount','GetIoDllVersion','GetInfVersion','GetDriverVersion','GetUWPVersion','GetNum_Key','WMISetAppPath','TraceOutput','TraceOutputCritical','wmiadd','GetXgmFw','Power_PD_Charging'}
NORMAL_CONTROLS={'HealthyTable_SetFanPwmDuty','HealthyTable_SetFanTestMode','HealthyTable_SetFanIndex',
 'WMISetBatteryHealth','WMISetBatteryHealthToUser','WMISetQuietFan','Thermal_Read_CpuPackagePower','SaveEcLog'}
REVERSIBLE_SETTERS=NORMAL_CONTROLS-{'Thermal_Read_CpuPackagePower','SaveEcLog','HealthyTable_SetFanIndex'}

def frontend():
    spec=importlib.util.spec_from_file_location('zenbook_native_frontend',HERE/'zenbook-hardware.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def normal_control(name,args):
    front=frontend()
    if name=='HealthyTable_SetFanIndex':
        index=native_oem.integer(args.get('index'),0,0,'fan index')
        return {'index':index,'count':1,'selection':'The single native fan channel is already selected.'}
    if name=='HealthyTable_SetFanPwmDuty':
        duty=native_oem.integer(args.get('duty'),0,255,'duty')
        p=native_oem.device();(p/'pwm1').write_text(str(duty)+'\n')
        stored=int((p/'pwm1').read_text());mode=int((p/'pwm1_enable').read_text())
        return {'requested_pwm':duty,'stored_pwm':stored,'request_readback_verified':stored==duty,
                'mode':mode,'deferred_while_automatic':mode==2}
    if name=='HealthyTable_SetFanTestMode':
        manual=args.get('manual')
        if not isinstance(manual,bool):raise ValueError('manual must be a JSON boolean.')
        p=native_oem.device();(p/'pwm1_enable').write_text('1\n' if manual else '2\n')
        mode=int((p/'pwm1_enable').read_text())
        return {'requested_manual':manual,'mode':mode,'mode_readback_verified':mode in (0,1) if manual else mode==2,
                'requested_pwm':int((p/'pwm1').read_text())}
    if name in ('WMISetBatteryHealth','WMISetBatteryHealthToUser'):
        percent=native_oem.integer(args.get('percent'),0,100,'percent')
        if name=='WMISetBatteryHealthToUser':return remembered_controls.set_and_remember(front,'charge-limit',percent)
        return front.control(SimpleNamespace(command='charge-limit',value=percent))
    if name=='WMISetQuietFan':
        mode=args.get('profile')
        if mode not in ('quiet','balanced','performance'):raise ValueError('profile must be quiet, balanced or performance.')
        return remembered_controls.set_and_remember(front,'profile',mode)
    if name=='Thermal_Read_CpuPackagePower':return front.power()
    if name=='SaveEcLog':
        import ec_diagnostics
        return ec_diagnostics.write_log(args.get('path'),args.get('samples',1),args.get('interval',1),front.snapshot)
    raise KeyError(name)

def validate(name,args,apply=False,expected_sha256=None):
    if not isinstance(args,dict):raise ValueError('API arguments must be a JSON object.')
    if name=='RF_USBIsTranster':linux_services.validate_usb_activity(args)
    if name in ('CPU_ReadCpuVoltage','Adapter_Read_PD_IC_PN') and args:
        raise ValueError('This OEM read takes no arguments.')
    control_keys={'HealthyTable_SetFanPwmDuty':{'duty'},'HealthyTable_SetFanTestMode':{'manual'},
                  'HealthyTable_SetFanIndex':{'index'},'WMISetBatteryHealth':{'percent'},
                  'WMISetBatteryHealthToUser':{'percent'},'WMISetQuietFan':{'profile'},
                  'Thermal_Read_CpuPackagePower':set()}
    lifecycle_keys={name:set() for name in LIFECYCLE}
    lifecycle_keys.update(WMISetAppPath={'path'},TraceOutput={'text'},TraceOutputCritical={'text'},wmiadd={'value'})
    allowed=control_keys.get(name,lifecycle_keys.get(name))
    if allowed is not None and set(args)!=allowed:raise ValueError('Unexpected or missing control/lifecycle arguments.')
    if name=='wmiadd':native_oem.integer(args['value'],0,0xffffffff,'value')
    if name in ('TraceOutput','TraceOutputCritical') and (not isinstance(args['text'],str) or not 1<=len(args['text'])<=4096):
        raise ValueError('text must contain 1..4096 characters.')
    if name=='WMISetAppPath' and (not isinstance(args['path'],str) or not Path(args['path']).is_absolute()):
        raise ValueError('path must be an absolute application path.')
    if name in field_reads.NAMES:field_reads.validate(name,args)
    if name in specialty_thermal.NAMES:specialty_thermal.validate(name,args)
    if name in adapter_ratings.NAMES:adapter_ratings.validate(name,args)
    if name in adapter_diagnostics.NAMES:adapter_diagnostics.validate(name,args)
    if name in firmware_queries.NAMES:firmware_queries.validate(name,args)
    if name in linux_services.hardware_memory.NAMES:linux_services.hardware_memory.validate(name,args)
    if name in linux_services.cpu_metadata.NAMES:linux_services.cpu_metadata.validate(name,args)
    if name in linux_services.identity_inventory.NAMES:linux_services.identity_inventory.validate(name,args)
    if name in linux_services.battery_summary.NAMES:linux_services.battery_summary.validate(name,args)
    if name in linux_services.platform_metadata.NAMES:linux_services.platform_metadata.validate(name,args)
    if name=='AppList_OpenWindows':linux_services.desktop_windows.validate(args)
    if name=='WMIGetLCDModel':
        import display_state
        display_state.validate(name,args)
    if name in linux_services.storage_inventory.NAMES:linux_services.storage_inventory.validate(name,args)
    if name in wwan.NAMES:wwan.validate(name,args)
    if name in {'RF_USBNum','RF_USBPort','RF_USBISTYPEC','RF_USB_A_Num','RF_USB_C_Num'}:
        import usb_inventory
        usb_inventory.validate(name,args)
    if name in wireless.LINK_NAMES|wireless.CACHE_NAMES|wireless.CARD_NAMES or name in wireless.RSSI_NAMES:wireless.validate(name,args)
    if name in set(hardware_status.NAMES)|{'Power_PD_Charging','GetDriverVersion','GetRefCount','GetNum_Key','WMIGetGPUUsg','System_Read_TabletMode'} and args:raise ValueError('This hardware status query takes no arguments.')
    if name in battery_identity.NAMES and args:raise ValueError('This battery identity read takes no arguments.')
    if name=='RF_USBHDMIIsUsed':linux_services.validate_display_activity(args)
    if name in linux_services.EMPTY_HW_READS and args:raise ValueError('This hardware query takes no arguments.')
    if name=='WMIGetWiFiBytesPersec' and (set(args)-{'detailed'} or type(args.get('detailed',False)) is not bool):
        raise ValueError('Only an optional boolean detailed argument is accepted.')
    if name in efi_oem.WRITES:
        plan=efi_oem.call(name,args,False)
        if apply and expected_sha256!=plan['expected_sha256']:raise RuntimeError('Apply requires the exact digest from the reviewed OEM field plan.')
    elif name in native_oem.MUTATIONS:
        plan=native_oem.mutation_plan(name,args)
        if apply and expected_sha256!=plan['expected_sha256']:raise RuntimeError('Apply requires the exact digest from the reviewed OEM operation plan.')
    elif name=='WOA_EC_read':native_oem.raw_index(args)
    elif name in pd_identity.NAMES:
        pd_identity.validate(name,args)
    elif name in battery_diagnostics.NAMES:
        if args:raise ValueError('This battery read takes no arguments.')
    elif name in pd_sources.NAMES:
        if name=='Adapter_Read_PDO':native_oem.integer(args.get('index'),0,6,'PDO index')
        allowed={'index','connector'} if name=='Adapter_Read_PDO' else {'connector'}
        if set(args)-allowed:raise ValueError('Only the PDO index and optional connector selector are accepted.')
        if 'connector' in args and (isinstance(args['connector'],bool) or args['connector'] not in (1,2)):
            raise ValueError('connector must be 1 or 2.')
    elif name=='Adapter_Read_Contract_PDO':
        if set(args)-{'connector'}:raise ValueError('Only the optional connector selector is accepted.')
        if 'connector' in args and (isinstance(args['connector'],bool) or args['connector'] not in (1,2)):
            raise ValueError('connector must be 1 or 2.')
    elif name=='GetSENSOR_WMI_Data':
        if args:raise ValueError('GetSENSOR_WMI_Data takes no arguments.')
    if name=='HealthyTable_SetFanPwmDuty':native_oem.integer(args.get('duty'),0,255,'duty')
    if name=='HealthyTable_SetFanIndex':native_oem.integer(args.get('index'),0,0,'fan index')
    if name=='HealthyTable_SetFanTestMode' and not isinstance(args.get('manual'),bool):raise ValueError('manual must be a JSON boolean.')
    if name in ('WMISetBatteryHealth','WMISetBatteryHealthToUser'):native_oem.integer(args.get('percent'),0,100,'percent')
    if name=='WMISetQuietFan' and args.get('profile') not in ('quiet','balanced','performance'):raise ValueError('Invalid performance profile.')
    if name=='SaveEcLog':
        import math
        if set(args)-{'path','samples','interval'} or not isinstance(args.get('path'),str) or not args['path']:raise ValueError('Use a new path and optional samples/interval only.')
        native_oem.integer(args.get('samples',1),1,300,'samples')
        interval=args.get('interval',1)
        if type(interval) not in (int,float) or not math.isfinite(interval) or not .5<=interval<=60:raise ValueError('interval must be a finite numeric0.5..60 seconds.')
    if 'include_titles' in args and not isinstance(args['include_titles'],bool):raise ValueError('include_titles must be a JSON boolean.')
    if 'allow_immutable' in args and not isinstance(args['allow_immutable'],bool):raise ValueError('allow_immutable must be a JSON boolean.')

def needs_root(name,args,apply=False):
    import wireless_native
    if name in wireless_native.NAMES:return wireless_native.needs_root(name)
    if name in field_reads.NAMES:return name in field_reads.ROOT_READS
    if name=='WMIGetHDDTemp':
        # Root only when a selected disk lacks a world-readable hwmon reading and
        # would need the SMART fallback; never run smartctl to decide this.
        if os.geteuid()==0:return False
        import disk_temperature
        def refuse(*_a,**_k):raise PermissionError(errno.EACCES,'SMART fallback requires privilege.')
        try:rows=disk_temperature.report('all',runner=refuse)  # same selection as the WMIGetHDDTemp route
        except OSError:return True
        return any(r.get('errno')==errno.EACCES for r in rows)
    if name=='SaveEcLog':return firmware_queries.report()['eeprom_table']['available']
    if name=='GetEEPROM_Data':return firmware_queries.report()['eeprom_table']['available']
    # 0.79: the driver makes gauge/lifetime/identity, received PD identity and
    # package-power attributes root-only, so non-root callers use the service.
    if name in pd_sources.NAMES:return False
    if name in battery_diagnostics.NAMES or name in battery_identity.NAMES:return True
    if name=='Adapter_Read_PD_ADO':return args.get('native_alert') is True
    if name in pd_identity.NAMES:return True
    if name=='Adapter_Read_Contract_PDO':
        try:return not (native_oem.device()/'pd_contract').exists()
        except RuntimeError:return True
    if name=='CPU_ReadCpuVoltage':
        try:return not (native_oem.device()/'in6_input').exists()
        except RuntimeError:return True
    if name=='Thermal_Read_CpuPackagePower':return True
    if name in NORMAL_CONTROLS:return name not in ('SaveEcLog','HealthyTable_SetFanIndex')
    if name in efi_oem.WRITES:return apply
    if name in native_oem.MUTATIONS:return apply
    if name in NATIVE_NAMES:return True
    if name=='StopWinIoDriver':return apply
    if name=='InitializeWinIo':return not Path('/sys/module/zenbook_healthytable').exists()
    if name=='GetXgmFw':return True
    if name=='RF_USBIsTranster':return args.get('metric')=='usb_traffic'
    return name in linux_services.ROOT_READS

# Client-side routing for a non-root caller whose request needs privilege.
# Mirrors the service's refusals (service/hwd_core.py CLIENT_ONLY and its
# firmware/driver EOPNOTSUPP rules) so that the client never asks for them.
CLIENT_ONLY={'WMISetAppPath','SaveEcLog','TraceOutput','TraceOutputCritical'}
ROOT_CLI_HINT='run with sudo zenbook-hardware (the privileged service does not perform this operation)'

def privilege_route(name,args,apply=False):
    """'client' (run unprivileged in this process), 'root-cli' (firmware apply,
    driver load/unload: only `sudo zenbook-hardware`) or 'service'."""
    if name in CLIENT_ONLY:return 'client'
    if name in efi_oem.WRITES and apply:return 'root-cli'
    if name=='StopWinIoDriver' and apply:return 'root-cli'
    if name=='InitializeWinIo' and not Path('/sys/module/zenbook_healthytable').exists():return 'root-cli'
    return 'service'

def config_path():
    import user_preferences
    return Path(user_preferences.configuration_home())/'zenbook-hardware/compat.json'
def config():
    import user_preferences
    return user_preferences.application_config()['values']
def set_app_path(args,apply,expected):
    import user_preferences
    return user_preferences.set_application_path(args.get('path'),apply,expected)

def lifecycle(name,args,apply=False,expected=None):
    if name=='GetIoDllVersion':return VERSION
    if name=='GetInfVersion':
        import driver_package
        return driver_package.report()
    if name=='GetDriverVersion':return hardware_status.driver_value('version')
    if name=='GetUWPVersion':return {'linux_frontend':VERSION,'gnome_bridge':4,'windows_UWP_applicable':False,
                                  'gnome_bridge_scope':'Bundled extension protocol; actual session availability is reported by desktop queries.'}
    if name=='wmiadd':return (native_oem.integer(args.get('value'),0,0xffffffff,'value')+1)&0xffffffff
    if name=='GetRefCount':return hardware_status.driver_value('refcnt')
    if name=='GetNum_Key':
        return linux_services.keyboard_state()
    if name=='WMISetAppPath':return set_app_path(args,apply,expected)
    if name=='InitializeWinIo':
        if not Path('/sys/module/zenbook_healthytable').exists():linux_services.run(['modprobe','zenbook_healthytable'])
        p=native_oem.device();return {'initialized':True,'module_version':hardware_status.driver_value('version'),'rpm':int((p/'fan1_input').read_text())}
    if name=='ShutdownWinIo':return {'client_released':True,'shared_kernel_driver_retained':Path('/sys/module/zenbook_healthytable').exists()}
    if name=='StopWinIoDriver':
        plan={'operation':'unload zenbook_healthytable after restoring automatic','loaded':Path('/sys/module/zenbook_healthytable').exists(),'applied':False}
        digest=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest();plan['expected_sha256']=digest
        if not apply:return plan
        if expected!=digest:raise RuntimeError('Driver state changed or the reviewed digest was not supplied.')
        if plan['loaded']:
            p=native_oem.device();(p/'pwm1_enable').write_text('2\n')
            if (p/'pwm1_enable').read_text().strip()!='2':raise RuntimeError('Automatic fan restoration failed.')
            linux_services.run(['modprobe','-r','zenbook_healthytable'])
        return {**plan,'applied':True,'loaded':False,'dkms_and_boot_configuration_retained':True}
    if name in ('TraceOutput','TraceOutputCritical'):
        message=args.get('text')
        if not isinstance(message,str) or not 1<=len(message)<=4096:raise ValueError('text must contain 1..4096 characters.')
        level='crit' if name=='TraceOutputCritical' else 'info'
        result=subprocess.run([linux_services.system_tool('systemd-cat'),'-t','zenbook-hardware','-p',level],input=message,text=True,capture_output=True,timeout=3)
        if result.returncode:raise RuntimeError('Journal logging failed.')
        return {'recorded':True,'priority':level}
    if name=='Power_PD_Charging':
        return usb_power.pd_input_online()
    if name=='GetXgmFw':
        return xgm_hid.firmware()
    raise KeyError(name)

def dispatch(name,args,apply=False,expected_sha256=None):
    if not isinstance(args,dict):raise ValueError('API arguments must be a JSON object.')
    if name in field_reads.NAMES:return field_reads.call(name,args)
    if name in EFI_NAMES:return efi_oem.call(name,args,apply,expected_sha256)
    if name in NATIVE_NAMES:return native_oem.call(name,args,apply,expected_sha256)
    if name in hardware_status.NAMES:return hardware_status.call(name,args)
    if name in LIFECYCLE:return lifecycle(name,args,apply,expected_sha256)
    if name in NORMAL_CONTROLS:return normal_control(name,args)
    if name in pd_sources.NAMES:return pd_sources.call(name,args)
    if name in battery_diagnostics.NAMES:return battery_diagnostics.call(name,args)
    if name in battery_identity.NAMES:return battery_identity.call(name,args)
    if name in pd_identity.NAMES:return pd_identity.call(name,args)
    if name in specialty_thermal.NAMES:return specialty_thermal.call(name,args)
    if name in adapter_ratings.NAMES:return adapter_ratings.call(name,args)
    if name in adapter_diagnostics.NAMES:return adapter_diagnostics.call(name,args)
    if name in firmware_queries.NAMES:return firmware_queries.call(name,args)
    return linux_services.call(name,args)
