# SPDX-License-Identifier: GPL-2.0-only
"""Native hardware metrics beyond the original ASUS API inventory."""
import errno
import field_reads
import native_oem
import charger_adc
import wireless
import wireless_native
import ec_diagnostics
import usb_power
import hardware_status
import package_power
import pd_contract
import battery_diagnostics
import battery_identity
import battery_extra
import battery_sbs
import thermistors
import specialty_thermal
import adapter_ratings
import adapter_diagnostics
import firmware_queries
import pd_sources
import pd_identity
import charger_metrics
import cpu_throttling
import ssd_health


def _guard(function):
    try:return function()
    except OSError as error:return {'available':False,'errno':error.errno or errno.EIO,'error':str(error)}


def _ec_cpu():
    """EC CPU temperature and CPU-reported voltage from the native hwmon device."""
    result={}
    for key,name,scale,unit in (('temperature','temp1_input',1000,'celsius'),('voltage','in6_input',1000,'volts')):
        try:
            raw=int((native_oem.device()/name).read_text())
            result[key]={'available':True,unit:raw/scale,'raw':raw}
        except (OSError,RuntimeError,ValueError) as error:
            result[key]={'available':False,'errno':getattr(error,'errno',None) or errno.EIO}
    result['voltage_kind']='CPU-reported P-state voltage (MSR_PERF_STATUS), not an independent rail ADC'
    result['temperature_source']='HealthyTable EC CPU sensor'
    return result


def report():
    result= {'schema':1,'wireless_links':wireless.links(),'wireless_chain_signal':_guard(lambda:wireless.call('RF_WiFi_Main_Aux_Rssi',{})),'usb_c_power':usb_power.result(),'cpu_frequencies':hardware_status.frequencies(),'cpu_reported_frequency':hardware_status.reported_frequencies(),'cpu_package_power':package_power.report(),'battery_identity':battery_identity.report(),'cpu_throttling':cpu_throttling.report(),'ssd_health':ssd_health.read_cached(),
            'board_thermistors':thermistors.report(),'specialty_temperatures':specialty_thermal.report(),'adapter_capabilities':adapter_ratings.report(),'adapter_diagnostics':adapter_diagnostics.report(),'firmware_diagnostics':firmware_queries.report(),'battery_gauge':battery_diagnostics.report(),'battery_lifetime':battery_diagnostics.lifetime_report(),
            'battery_gauge_extra':battery_extra.report(),'battery_sbs':battery_sbs.report(),'battery_sbs_diagnostics':battery_sbs.diagnostics(),
            'usb_pd_source_capabilities':pd_sources.report(),'usb_pd_identity':pd_identity.report(),'charger_input':charger_adc.report(),'charger':charger_metrics.report(),'platform_power':pd_contract.platform_power(),'cpu_power_limits':_guard(field_reads.power_limits),'ec_cpu':_ec_cpu(),
            'unavailable':{
                'usb_pd_cable_identity':'Fixed received-identity reader is implemented; availability depends on an acknowledged controller response.',
                                'specialty_temperature_labels':'Eight original getters provide no measurement on this qualified EC platform. GPU TS1L uses the existing EC GPU channel; see specialty_temperatures for current availability.',
                'wwan_and_xg_mobile':'No matching hardware connected in this qualification.'}}
    result['wireless_capabilities']=wireless_native.report()
    result['ec_diagnostics']=ec_diagnostics.report()
    result['fan_diagnostics']=ec_diagnostics.fan_report()
    try:result['wireless_cards']=wireless.cards()
    except OSError as e:result['wireless_cards']={'available':False,**wireless_native.error(e)}
    identity=result['usb_pd_identity']
    if any(p.get('cable',{}).get('available') for p in identity.get('ports',[])):
        result['unavailable'].pop('usb_pd_cable_identity',None)
    return result
