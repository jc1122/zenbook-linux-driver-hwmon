#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Linux counterpart to ASUS hardware diagnostics on the qualified UP3404VA.

Uses the guarded kernel driver for EC operations and standard Linux APIs for
features already implemented upstream. No arbitrary EC, MSR, I2C or flash writes.
"""
from pathlib import Path
import argparse
import datetime
import json
import os
import platform
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
# The --sudo-fallback re-run uses python3 -I, which leaves the script
# directory off sys.path; import providers only from this runtime directory.
if str(HERE) not in sys.path: sys.path.insert(0, str(HERE))
SUDO_PYTHON = '/usr/bin/python3'
def read(path, default=None):
    try: return Path(path).read_text().strip()
    except (OSError, ValueError): return default

def number(path):
    try: return int(read(path))
    except (TypeError, ValueError): return None

def manual_fan_mode(mode):
    return mode in (0,1) if type(mode) is int and mode in (0,1,2) else None

def device():
    items = [p for p in Path('/sys/class/hwmon').glob('hwmon*')
             if read(p/'name') == 'zenbook_ec']
    if len(items) != 1: raise RuntimeError('Expected one zenbook_ec device; load zenbook_healthytable.')
    return items[0]

def native():
    p = device()
    return json.loads((p/'ec_telemetry').read_text())

def power():
    import package_power
    return package_power.require_report()

def inventory():
    cpu={}
    for line in read('/proc/cpuinfo','').splitlines():
        if ':' in line:
            k,v=line.split(':',1)
            if k.strip() in ('vendor_id','model name','cpu MHz'):cpu.setdefault(k.strip(),v.strip())
    mem={}
    for line in read('/proc/meminfo','').splitlines():
        k,v=line.split(':',1)
        if k in ('MemTotal','MemAvailable','SwapTotal','SwapFree'):mem[k]=v.strip()
    gpu=[]
    for p in sorted(Path('/sys/class/drm').glob('card[0-9]*')):
        if '-' in p.name or not (p/'device/vendor').is_file():continue
        gpu.append({'card':p.name,'vendor':read(p/'device/vendor'),'device':read(p/'device/device'),
                    'driver':(p/'device/driver').resolve().name})
    return {'system':{'vendor':read('/sys/class/dmi/id/sys_vendor'),
        'model':read('/sys/class/dmi/id/product_name'),'bios':read('/sys/class/dmi/id/bios_version'),
        'bios_date':read('/sys/class/dmi/id/bios_date'),'os':platform.platform()},
        'cpu':cpu,'memory':mem,'gpu':gpu}

# Sections whose driver attributes are root-only from 0.79; a non-root caller
# obtains them from the service's Metrics() (same providers, run as root).
RESTRICTED_METRICS=('cpu_package_power','battery_identity','battery_gauge','battery_lifetime','battery_gauge_extra',
                    'battery_sbs','battery_sbs_diagnostics','usb_pd_identity','charger_input','charger','platform_power')

def restricted_metrics(args=None):
    """Root: None (read locally). Non-root: restricted sections from the
    service; if it is unavailable or refuses, None plus a one-line notice, and
    the local typed-unavailable values remain."""
    if os.geteuid()==0:return None
    try:report=service_client(args).metrics()
    except OSError as error:
        print('zenbook-hardware: '+str(error)+'; root-only sections remain unavailable.',file=sys.stderr);return None
    if not isinstance(report,dict):return None
    return {key:report[key] for key in RESTRICTED_METRICS if key in report}

def snapshot(restricted=None):
    def pick(key,local):
        return restricted[key] if restricted and key in restricted else local()
    p=device();ec_status={'available':True}
    try:ec=native()
    except OSError as error:
        ec={};ec_status={'available':False,'errno':error.errno,'error':str(error)}
    bat=Path('/sys/class/power_supply/BAT0')
    def val(name):return number(bat/name)
    full,design=val('charge_full'),val('charge_full_design')
    r={'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),
       'driver_version':read('/sys/module/zenbook_healthytable/version'),
       'fan':{'rpm':number(p/'fan1_input'),'mode':number(p/'pwm1_enable'),
              'manual_pwm_requested':number(p/'pwm1'),'manual_pwm_minimum':0},
       'temperatures_celsius':{},'voltages_volts':{},'currents_amperes':{},
       'battery':{'status':read(bat/'status'),'percent':ec.get('battery_percent'),
           'cycles':ec.get('battery_cycles'),'full_mAh':ec.get('battery_full_mAh'),
           'design_mAh':design/1000 if design else None,
           'health_percent':round(100*full/design,2) if full and design else None,
           'manufacturer':read(p/'battery_manufacturer'),'model':read(p/'battery_model'),
           'charge_limit_percent':val('charge_control_end_threshold')},
       'profile':read('/sys/firmware/acpi/platform_profile'),
       'profile_choices':read('/sys/firmware/acpi/platform_profile_choices'),
       'keyboard_backlight':{'level':number('/sys/class/leds/asus::kbd_backlight/brightness'),
           'maximum':number('/sys/class/leds/asus::kbd_backlight/max_brightness')},
       'usb_c':[], 'power_limits_watts':{},'ec':ec,'ec_status':ec_status}
    import battery_diagnostics
    r['fan'].update({'count':1,'manual':manual_fan_mode(r['fan']['mode'])})
    import ec_diagnostics
    r['fan']['ec_diagnostics']=ec_diagnostics.fan_report()
    r['battery'].update({'full':battery_diagnostics.is_full(r['battery']['status']),
        'charge_limit_supported':(bat/'charge_control_end_threshold').is_file()})
    import linux_services
    try:r['ac_online']=linux_services.ac_online()
    except OSError as error:
        r['ac_online']=None;r['ac_status_error']={'errno':error.errno or 5,'error':str(error)}
    import battery_identity
    identity=pick('battery_identity',battery_identity.report);r['battery']['identity']=identity
    for key in ('manufacturer','model'):
        if identity.get(key) is not None:
            r['battery'][key]=identity[key];r['battery'][key+'_source']=identity['source']
        elif not r['battery'].get(key):r['battery'][key]=None
    manufacturer=r['battery'].get('manufacturer') or ''
    ec['gauge_identifier_raw']=identity.get('gauge_identifier_raw') if identity['available'] else ord(manufacturer[3]) if len(manufacturer)>3 else None
    import battery_diagnostics
    r['battery']['error']=battery_diagnostics.battery_error(ec.get('battery_status_flags'))
    ec['battery_current_mA']=battery_diagnostics.signed_current(ec.get('battery_current_mA_raw'))
    r['ec_info']={'chip_name':bytes(ec.get('chip_name_raw',[])).decode('ascii',errors='replace'),
        'firmware':bytes(ec.get('firmware_raw',[])).decode('ascii',errors='replace')}
    import hardware_status
    frequency=hardware_status.frequencies();r['cpu_frequencies']=frequency
    reported=hardware_status.reported_frequencies();r['cpu_reported_frequency']=reported
    import package_power
    r['cpu_package_power']=pick('cpu_package_power',package_power.report)
    r['cpu_frequency_mhz']=reported.get('current',{}).get('mhz')
    r['cpu_max_frequency_mhz']=reported.get('maximum',{}).get('mhz')
    for prefix,target,scale in (('temp','temperatures_celsius',1000),('in','voltages_volts',1000),('curr','currents_amperes',1000)):
        for f in sorted(p.glob(prefix+'*_input')):
            label=read(f.with_name(f.name.replace('_input','_label')),f.stem)
            v=number(f)
            r[target][label]=v/scale if v is not None else None
    import extra_sensors
    r['temperatures_celsius'].update(extra_sensors.temperatures())
    rawdate=ec.get('battery_manufacture_date_raw',0)
    if type(rawdate) is int and rawdate>0:
        try:r['battery']['manufacture_date']=datetime.date(1980+(rawdate>>9),(rawdate>>5)&15,rawdate&31).isoformat()
        except ValueError:pass
    import usb_power
    usb=usb_power.result();r['usb_c']=usb['ports']
    r['usb_c_status']={key:value for key,value in usb.items() if key!='ports'}
    for z in Path('/sys/class/powercap').glob('intel-rapl:*'):
        if not read(z/'name','').startswith('package-'):continue
        for f in z.glob('constraint_*_power_limit_uw'):
            v=number(f)
            if v is not None:r['power_limits_watts'][read(z/'name')+'/'+read(f.with_name(f.name.replace('_power_limit_uw','_name')),f.name)]=v/1e6
    import cpu_throttling,ssd_health,charger_metrics,charger_adc
    r['cpu_throttling']=cpu_throttling.report()
    r['ssd_health']=ssd_health.read_cached()
    r['charger_metrics']=pick('charger',charger_metrics.report)
    r['charger_input']=pick('charger_input',charger_adc.report)
    import battery_diagnostics,thermistors
    r['battery_gauge_metrics']=pick('battery_gauge',battery_diagnostics.report)
    r['board_thermistors']=thermistors.report()
    r['inventory']=inventory()
    return r

def elevated(argv):
    """Explicit --sudo-fallback only, after the service proved unavailable:
    plain interactive sudo. No stored credential or keyring is ever used."""
    from auth import sudo_fallback
    import user_preferences
    print('zenbook-hardware: privileged service unavailable; using interactive sudo (--sudo-fallback).',file=sys.stderr)
    # Fixed interpreter, isolated (-I: no PYTHON* env, user site or script-dir
    # path injection) and no root-owned bytecode in the caller's tree (-B).
    return sudo_fallback([SUDO_PYTHON,'-I','-B',str(Path(__file__).resolve()),'--caller-config-home',user_preferences.configuration_home(),*argv])

def service_client(args):
    import auth
    return auth.ServiceClient(interactive=not getattr(args,'non_interactive',False) and auth.interactive_default())

def routed(args,argv,operation):
    """Non-root privileged work goes to org.zenbook.Hardware1. Returns
    (used_sudo, value). Without --sudo-fallback an unavailable service is an
    error that tells the user to run with sudo."""
    import auth
    auth.deprecated_auth_notice()
    try:return False,operation(service_client(args))
    except auth.ServiceUnavailable:
        if not getattr(args,'sudo_fallback',False):raise
    return True,elevated(argv)

def root_only(what):
    import compat
    return PermissionError(13,what+' requires root; '+compat.ROOT_CLI_HINT+'.')

def fan_state():
    try:p=device()
    except RuntimeError:return {'mode':None,'requested_pwm':None,'rpm':None}
    return {'mode':number(p/'pwm1_enable'),'requested_pwm':number(p/'pwm1'),'rpm':number(p/'fan1_input')}

def fan_via_service(client,args):
    """Non-root fan control: SetFanAuto, or a bounded lease held by this process.
    The service restores firmware automatic on release, expiry, exit/kill
    (bus disconnect), low RPM and daemon stop."""
    if args.value=='auto':
        ended=client.set_fan_auto()
        return {**fan_state(),'automatic_restored':ended.get('automatic_restored'),'ended_lease':ended.get('lease')}
    started={}
    def acquired(lease_id):
        started.update(fan_state())
        print('zenbook-hardware: fan lease '+lease_id+' for '+str(args.duration)+' s; Ctrl-C restores automatic.',file=sys.stderr,flush=True)
    ended=client.hold_fan_lease(args.duration,args.value,acquired)
    return {**started,'lease':{'id':ended.get('lease'),'seconds':args.duration,'request':args.value,'reason':ended.get('reason'),
            'automatic_restored':ended.get('automatic_restored'),
            'mode_after':ended.get('mode') if ended.get('mode') is not None else fan_state()['mode']}}

def control_via_service(client,args):
    import auth
    if args.command=='fan':return fan_via_service(client,args)
    if args.command=='profile':
        return auth.remember_as_user(client,'profile',args.value,lambda:client.control('profile',{'value':args.value}))
    if args.command in ('charge-limit','keyboard'):return client.control(args.command,{'value':args.value})
    if args.command=='charger':return client.control('charger',{} if args.connector is None else {'connector':args.connector})
    if args.command=='battery-history':return client.control('battery-history-refresh')
    return client.control(args.command)

def api_field(row):
    import field_reads
    names=[name for name,field in field_reads.FIELDS.items() if field==row['field']]
    if not names:raise OSError(19,'Unknown native field.')
    return field_reads.call(names[0],{})

def write_verified(path,value):
    import remembered_controls
    p=Path(path);before_identity=remembered_controls.identity(p);before=p.read_text().strip()
    try:
        p.write_text(str(value)+'\n');after=p.read_text().strip()
        if after!=str(value) or remembered_controls.identity(p)!=before_identity:raise RuntimeError('Requested setting or device identity did not read back.')
    except Exception as error:
        restored=False
        try:
            # Never replace a later external selection or a replacement device.
            if remembered_controls.identity(p)==before_identity and p.read_text().strip()==str(value):
                if before!=str(value):p.write_text(before+'\n')
                restored=p.read_text().strip()==before
        except OSError:pass
        raise remembered_controls.ControlError(getattr(error,'errno',None) or 5,'Setting verification failed.',
            {'before':before,'requested':str(value),'hardware_restored':restored}) from error
    return {'before':before,'after':after}

def control(args):
    if read('/sys/class/dmi/id/product_name')!='Zenbook Flip UP3404VA_UP3404VA':
        raise RuntimeError('This tool is restricted to the qualified UP3404VA.')
    if args.command=='fan':
        p=device()
        try:
            if args.value=='auto':(p/'pwm1_enable').write_text('2\n')
            elif args.value=='full':(p/'pwm1_enable').write_text('0\n')
            else:
                percent=int(args.value)
                if not 0<=percent<=100:raise ValueError('Fan percentage must be 0..100, auto or full.')
                duty=(percent*255+50)//100
                (p/'pwm1').write_text(str(duty)+'\n');(p/'pwm1_enable').write_text('1\n')
            return {'mode':number(p/'pwm1_enable'),'requested_pwm':number(p/'pwm1'),'rpm':number(p/'fan1_input')}
        except Exception:
            (p/'pwm1_enable').write_text('2\n');raise
    if args.command=='profile':return write_verified('/sys/firmware/acpi/platform_profile',args.value)
    if args.command=='charge-limit':return write_verified('/sys/class/power_supply/BAT0/charge_control_end_threshold',args.value)
    if args.command=='keyboard':return write_verified('/sys/class/leds/asus::kbd_backlight/brightness',args.value)
    if args.command=='power':return power()
    if args.command=='usb-activity':
        import usb_activity
        return usb_activity.sample()
    if args.command=='charger':
        import charger
        return charger.report(args.connector)
    if args.command=='battery-gauge':return json.loads((device()/'battery_gauge_status').read_text())
    if args.command=='reprobe':
        (device()/'diagnostics_reprobe').write_text('1\n')
        return snapshot()
    if args.command=='battery-history':
        import battery_diagnostics
        if args.refresh:(device()/'battery_lifetime_refresh').write_text('1\n')
        return battery_diagnostics.lifetime_report()
    raise RuntimeError('Unknown control.')

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--caller-config-home',help=argparse.SUPPRESS)
    parser.add_argument('--sudo-fallback',action='store_true',
        help='If the privileged service is unavailable, re-run the privileged command with interactive sudo')
    parser.add_argument('--non-interactive',action='store_true',help='Never ask polkit for interactive authentication')
    sub=parser.add_subparsers(dest='command',required=True)
    show=sub.add_parser('show');show.add_argument('--json',action='store_true')
    sub.add_parser('capabilities')
    sub.add_parser('preferences',help='Read saved user choices; does not apply them')
    api=sub.add_parser('api');api.add_argument('name')
    api.add_argument('--args',default='{}',help='JSON object of typed API parameters')
    api.add_argument('--apply',action='store_true',help='Execute a reviewed mutation plan')
    api.add_argument('--expect-sha256',help='Exact digest returned by the reviewed plan')
    fan=sub.add_parser('fan');fan.add_argument('value',help='auto, full, or 0..100 percent requested duty')
    fan.add_argument('--duration',type=int,choices=range(1,301),default=60,metavar='1..300',
        help='Non-root: hold the manual fan lease this many seconds, then restore automatic (root ignores it)')
    profile=sub.add_parser('profile');profile.add_argument('value',choices=('quiet','balanced','performance'))
    charge=sub.add_parser('charge-limit');charge.add_argument('value',type=int,choices=range(101),metavar='0..100')
    kbd=sub.add_parser('keyboard');kbd.add_argument('value',type=int,choices=range(4))
    sub.add_parser('power')
    sub.add_parser('usb-activity',help='Measure USB bulk/isochronous transfer activity')
    sub.add_parser('disk-activity',help='Read non-system disk I/O activity')
    sub.add_parser('hdmi',help='Read HDMI connector presence')
    sub.add_parser('wireless',help='Read cached AP capabilities, association PHY, card names and RSSI distributions')
    sub.add_parser('ec-diagnostics',help='Read the fixed source-gated raw EC diagnostic tables')
    metrics_parser=sub.add_parser('metrics',help='Charger ADC/protection, CPU throttle counters and SSD health')
    metrics_parser.add_argument('--refresh-ssd',action='store_true',help='Refresh the read-only privileged SMART cache')
    charger_parser=sub.add_parser('charger',help='Charger input ADC, negotiated power limits and UCSI diagnostics')
    charger_parser.add_argument('--connector',type=int,choices=(1,2),help='Filter one port; default: both EC ports')
    sub.add_parser('firmware-storage',help='BIOS/CMOS storage metadata; never reads contents')
    history=sub.add_parser('battery-history');history.add_argument('--refresh',action='store_true')
    sub.add_parser('battery-gauge')
    sub.add_parser('reprobe')
    record=sub.add_parser('record');record.add_argument('path',type=Path)
    record.add_argument('--samples',type=int,choices=range(1,301),default=10,metavar='1..300')
    record.add_argument('--interval',type=float,default=1.0)
    args=parser.parse_args(argv)
    import user_preferences
    user_preferences.configure(args.caller_config_home)
    if args.command=='preferences':
        print(json.dumps(user_preferences.read(),indent=2));return 0
    if args.command=='record':
        if not .5<=args.interval<=60:parser.error('Interval must be 0.5..60 seconds.')
        import ec_diagnostics,compat
        values={'path':str(args.path),'samples':args.samples,'interval':args.interval}
        compat.validate('SaveEcLog',values)
        # The service refuses SaveEcLog (caller-chosen file): a non-root caller
        # records unprivileged as itself; root-only fields report typed errors.
        record_snapshot=snapshot if os.geteuid()==0 else lambda:snapshot(restricted_metrics(args))
        print(json.dumps(ec_diagnostics.write_log(str(args.path),args.samples,args.interval,record_snapshot)));return 0
    if args.command=='firmware-storage':
        import extra_sensors
        print(json.dumps(extra_sensors.firmware_storage(),indent=2));return 0
    if args.command=='metrics':
        if args.refresh_ssd:
            if os.geteuid()!=0:raise root_only('Refreshing the SMART cache')
            import ssd_health
            ssd_health.export()
        import metrics
        report=metrics.report();restricted=restricted_metrics(args)
        if restricted:
            report.update(restricted)
            if any(p.get('cable',{}).get('available') for p in report.get('usb_pd_identity',{}).get('ports',[])):
                report.get('unavailable',{}).pop('usb_pd_cable_identity',None)
        print(json.dumps(report,indent=2,ensure_ascii=False));return 0
    if args.command=='wireless':
        import wireless_native,wireless
        result=wireless_native.report()
        try:result['cards']=wireless.cards()
        except OSError as e:result['cards_error']=wireless_native.error(e)
        print(json.dumps(result,indent=2,ensure_ascii=False));return 0
    if args.command=='ec-diagnostics':
        import ec_diagnostics
        print(json.dumps(ec_diagnostics.report(),indent=2));return 0
    if args.command=='power':
        if os.geteuid()!=0:
            used_sudo,result=routed(args,sys.argv[1:] if argv is None else argv,lambda client:client.control('power'))
            if used_sudo:return result
        else:result=power()
        print(json.dumps(result,indent=2));return 0
    if args.command=='disk-activity':
        import disk_activity
        print(json.dumps(disk_activity.report(),indent=2));return 0
    if args.command=='hdmi':
        import hdmi_presence
        print(json.dumps(hdmi_presence.report(),indent=2));return 0
    if args.command in ('fan','profile','charge-limit','keyboard','charger','battery-gauge','reprobe','usb-activity') or args.command=='battery-history' and args.refresh:
        if args.command=='fan' and args.value not in ('auto','full'):
            if not args.value.isdecimal() or not 0<=int(args.value)<=100:parser.error('Fan percentage must be 0..100, auto or full.')
        if os.geteuid()!=0:
            used_sudo,result=routed(args,sys.argv[1:] if argv is None else argv,lambda client:control_via_service(client,args))
            if used_sudo:return result
        elif args.command=='profile':
            import remembered_controls
            from types import SimpleNamespace
            result=remembered_controls.set_and_remember(SimpleNamespace(control=control),'profile',args.value)
        else:result=control(args)
    elif args.command=='capabilities':result=json.loads((HERE/'capabilities.json').read_text())
    elif args.command=='api':
        cap=json.loads((HERE/'capabilities.json').read_text())
        row=cap['exports'].get(args.name)
        if not row:parser.error('Unknown ASUS export.')
        api_args=json.loads(args.args)
        if not isinstance(api_args,dict):parser.error('--args must be a JSON object.')
        if row.get('backend'):
            import compat
            compat.validate(args.name,api_args,args.apply,args.expect_sha256)
            route=compat.privilege_route(args.name,api_args,args.apply) if os.geteuid()!=0 and compat.needs_root(args.name,api_args,args.apply) else 'direct'
            if route=='root-cli':raise root_only(args.name)
            if route=='service':
                import auth
                used_sudo,value=routed(args,sys.argv[1:] if argv is None else argv,
                    lambda client:auth.service_call(args.name,api_args,args.apply,args.expect_sha256,client=client))
                if used_sudo:return value
            else:value=compat.dispatch(args.name,api_args,args.apply,args.expect_sha256)
            if value is None:raise RuntimeError('The provider has no value for this hardware/state: '+args.name)
            result={'function':args.name,'value':value,'implementation':row['backend']}
        elif row.get('field'):
            if row['field'].startswith('gauge.') and os.geteuid()!=0:
                used_sudo,value=routed(args,sys.argv[1:] if argv is None else argv,lambda client:client.call(args.name,{}))
                if used_sudo:return value
            else:value=api_field(row)
            result={'function':args.name,'value':value,'units':row.get('units'),'implementation':row['status']}
        elif row.get('command'):
            result={'function':args.name,'command':row['command'],'note':row['reason']}
        else:raise RuntimeError(row['status']+': '+row['reason'])
    elif args.command=='battery-history':
        import battery_diagnostics
        result=battery_diagnostics.lifetime_report()
    else:
        result=snapshot(restricted_metrics(args))
        if not args.json:
            print('Fan:',result['fan']['rpm'],'RPM; mode',result['fan']['mode'],'(2=automatic, 0=full, 1=manual)')
            for k,v in result['temperatures_celsius'].items():print(k+':',v,'°C')
            for k,v in result['voltages_volts'].items():print(k+':',v,'V')
            print('Battery:',result['battery']['percent'],'%; health',result['battery']['health_percent'],'%; cycles',result['battery']['cycles'])
            print('Profile:',result['profile'],'; charge limit:',result['battery']['charge_limit_percent'],'%')
            return 0
    print(json.dumps(result,indent=2,ensure_ascii=False));return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,RuntimeError,KeyError,subprocess.SubprocessError) as e:
        if hasattr(e,'control_result'):print(json.dumps({'error':str(e),'errno':e.errno,'control':e.control_result}),file=sys.stderr)
        elif hasattr(e,'committed'):print(json.dumps({'error':str(e),'errno':e.errno,'configuration_committed':e.committed}),file=sys.stderr)
        else:print(str(e),file=sys.stderr)
        raise SystemExit(1)
