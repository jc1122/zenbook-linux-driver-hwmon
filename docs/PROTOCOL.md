# Recovered protocols and Linux providers

## Pack and cell power measurement bases in0.68

The compatible DA1 format assigns separate V/I pairs to cell powers and SBS
Voltage()*Current() to pack power. Both pack/average fields are signed centiwatts
at bytes28/30. Sources: [TI BQ40Z50-R4, section16.1.63](https://www.ti.com/lit/ug/sluuch2/sluuch2.pdf)
and [R5, section16.1.65](https://www.ti.com/lit/pdf/SLUUCN4B).
R4 sections16.10/16.11 distinguish summed cell voltages from coulomb-counter
current. This is a format reference, not physical OEM-chip identification.

Inference: those separate measurement bases and the absence of per-field
acquisition timestamps do not establish equality with a simultaneously sampled
cell sum. The previous5percent sum gate was unjustified. Pack remains its own
reported field; sum/delta are optional diagnostics, never a replacement power
measurement. Existing range/frame/identity/age/topology and per-cell V/I checks
remain. Eight retained nonzero-discharge observations support the correction:
all pack registers were nonzero/in-range, while the previous sum guard hid them.
No new broker query, gauge configuration or calibration write is introduced.

## Disk temperature source and Linux identity in0.67

Original83430 queries ROOT\WMI MSStorageDriver_FailurePredictData through
827d0, searches the cached SMART attribute table for IDc2 and formats its first
raw byte. The original bool is passed to COM initialization/cleanup, not a disk
selector. Native Celsius from associated hwmon/SMART is retained as a Linux
quantity; NVMe composite temperature is not represented as an ATA C2 raw byte.

Native physical-block/sysfs identity, matching dev_t/node inode, and diskseq
bracket metadata and readings. Linux documents diskseq as an unsigned64
monotonically increasing disk generation, including replacement of some backing
media: [kernel sysfs-block ABI](https://www.kernel.org/doc/Documentation/ABI/stable/sysfs-block).
Associated hwmon provider identity/ancestry and the final census are rechecked.
No ATA attribute raw-byte assumption, serial read, controller write or discovery
command is added. A separate HDDInfoc8700/bb4f0 review confirms its bool controls
CoInitializeEx/CoUninitialize only; Model/Size/MediaType3 selection is fixed.

## Original e-marker export field widths in0.66

Complete wrappers20f50/21090/211d0/21310 have no unresolved branches.
Each gates on HealthyTable>=23 then uses fixed DD bank6 requests, accumulates
higher register first by shifting8 and OR, returning0 on transport error.
PID reads41..42 (16 bits of the Product VDO); XID reads3b..3e (32 bits);
Other reads47..4a (32-bit fifth VDO). Despite its name, VID reads37..3a,
all32 bits of the ID Header, rather than only the lower16-bit USB vendor ID.
Native received SOP-prime data retains both full header and typed vendor ID;
VID raw_header=true exposes the original full-width quantity explicitly.
Original fixed bank-cache availability and native fixed-controller availability
are separate: this model has HealthyTable15 and currently no completed cable
identity. No identity is inferred from a PDO, charger brand or absent cache.

## Remaining radio and display source contracts in0.65

RF_USBHDMIIsUsed95fb0 returns94900's cached boolean at class+48. The helper
queries ROOT\WMI WmiMonitorConnectionParams with VideoOutputTechnology=5;
b7570 increments for each returned instance and does not read Active. Linux
HDMI-A/B cached connection status replaces the previous USB-only quantity.
The explicit usb_display metric remains independent USB/partner-DP evidence.

RF_BTConnectedType93ed0 uses941d0: Bluetooth search bReturnConnected=1,
ClassOfDevice bits8..12, 31-entry byte/DWORD indirect table. Cases1..9 label
Computer, Phone, LAN/Network access point, Audio/Video, Peripheral, Imaging,
Wearable, Toy, Health; case31 Uncategorized; other cases Others. Native class
codes preserve the quantity without reproducing spelling/semicolon formatting.

WWAN wrappers97220/972d0/97380 select cached offsets20/0/40 from949b0,
respectively. a1070 parses netsh mbn show interface; a07c0 uses show
homeprovider and line index3, 9ff10 uses show connection and line index8,
a1580 uses show signal and line index4. Home/technology take text after a
colon through newline; RSSI takes text inside parentheses, omitting the final
four unit characters before ')'. This is static parser recovery, not a live
Windows unit/calibration test. Native technology, primary-SIM home and measured
RSSI dBm remain typed and separately labelled; percent quality is not converted.
Native calls now pin an existing unique D-Bus owner and recheck object names
and properties used as context. No service activation or whole-modem dump.

System_Read_TabletModeab230 calls43880's vendor gate then read-only OEM8e,
payload33, returning the byte or INTMAX after a transport error. GateFFFF
returns0. Linux advertised EV_SW/SW_TABLET_MODE is a logical equivalent; the
raw vendor-byte interpretation and physically folded case are not claimed.


## Remaining platform source contracts in0.64

RF_USBIsTranster96f40 reads class0 set by94900 from b9d70's count of
Win32_PerfFormattedData_PerfDisk_PhysicalDisk entries with parsed integer
PercentDiskTime>20, excluding exact name0 C:. USB inventory9e730 writes separate
fields. This proves the earlier native USB-byte route was a different quantity.
Native now reports the disk predicate with measured queue-weighted Linux counters,
root-backing topology and separate busy time. The original unfiltered synthetic
Windows_Total instance is omitted, with cross-OS accounting explicitly unqualified.
See [Windows disk-time properties](https://learn.microsoft.com/en-us/previous-versions/aa394262(v=vs.85))
and [Linux I/O counter fields](https://www.kernel.org/doc/html/latest/admin-guide/iostats.html).

The separate USB metric keeps GETX64-byte headers with NULL payload/zero allocation.
The [Linux binary usbmon implementation](https://raw.githubusercontent.com/torvalds/linux/v7.0/drivers/usb/mon/mon_bin.c)
defines per-reader queued/dropped statistics; querying resets that reader's loss
count. Native baseline flush affects only its new reader. Incomplete or erroneous
capture never proves an inactive bus or exact total; real elapsed/boottime and
observed lower-bound bytes remain explicit.

System_Check_S_Modeaae80 resolves system wldp.dll's WldpQueryWindowsLockdownMode,
then accepts successful enum1/2. Its [Windows-only contract](https://learn.microsoft.com/en-us/windows/win32/api/wldp/nf-wldp-wldpquerywindowslockdownmode)
is not a Linux SecureBoot/lockdown query; native not-applicable is intentional.
HDDUsagec9870 follows HDD MediaType3 through disk/partition/volume metadata and
sums Size and Size-SizeRemaining, so native filesystem capacity is the right
quantity. SDSizecf980/c1790 overwrite the output with each matching removable
SD-caption Size. Native scalar sum and optional complete per-card records retain
that capacity information without copying Windows buffer/last-match quirks.

## Wireless observation source contracts in0.63

Wrappers93c70/974f0/97590/976c0 select associated BSSID, primary channel, connection
state and signed RSSI from helper94ea0. It queries current WLAN association, formats
six BSSID octets and matches the active SSID/BSSID before reading BSS lRssi. Its
11-case PHY jump table is resolved separately; unsupported native physical labels
are not inferred from it. Native uses validated nl80211 association/frequency/dBm.

Helper90c40 supplies counts at class5c/84/ac and group strings at60/88/b0. The2.4GHz
string contains channel1/6/11/other, now explicit beside native full-channel counts.
Original5/6GHz intervals have off-by-one-MHz cuts and the low-band branch broadly
accepts sub5001MHz entries. Native keeps qualified band membership, U-NII labels,
complete observed channels and explicit unclassified counts; source bugs are not
used to relabel4.9GHz as2.4GHz. Shared native AP reads now bracket owner/netdev/scan/
BSS identity with an overall deadline and typed failure instead of partial success.

Main/Aux wrapper97d30 formats class130/134. Original vendor helpers can fall back
to the same connected-BSS lRssi twice. Native retains genuine chain values and
leaves physical Main/Aux mapping unknown. WMI wrapperd2c80 requests both
BytesReceivedPersec and BytesSentPersec from Win32_PerfFormattedData_Tcpip_Networkinterface.
The [Microsoft class documentation](https://learn.microsoft.com/en-us/previous-versions/aa394293(v=vs.85)) confirms separate receive/send byte rates.
Native detailed RX/TX rates preserve both quantities; default RX+TX and actual
elapsed counter interval are explicit native semantics, not a Windows buffer ABI.

## Fan and battery controls in0.62

Original fan setter58770 posts the fullbyte in DD82/35; index585a0 posts0..4
in DD82/32. TestMode58930 posts boolean DD82/31 while retaining a process-wide
Global FancontrolMutex (10-second acquisition wait), released on auto. This
wait is not a manual-mode expiry. Native uses kernel serialization/ownership,
read-verified automatic restoration and low-RPM/fault checks, not Windows mutex
or selector ABI. Only qualified logical fan0/raw selection1 is available.
Full requested byte range is retained; firmware may quantize it (observed max254
for request255), and raw writes to fan control remain blocked before I/O.

Original71ee0 checks battery-health support through6e8e0, supplies Device_ID
1179735 and decimal Control_status to DEVS, and tests its result. Its integer
argument has no recovered40% floor and no user-choice write in this routine.
Native meaningful percentage0..100 follows the [Linux ASUS RSOC setter](https://raw.githubusercontent.com/torvalds/linux/v7.0/drivers/platform/x86/asus-wmi.c),
which checks firmware acknowledgment and caches the setting because firmware has
no threshold read method. Native readback proves that stored acknowledged value,
not actual charge cutoff. ToUser's successful-choice record remains separate.

## Battery extrema and package power in0.61

Thermal_Read_CpuPackagePowerabef0 delegates Intel helper3ef20/IOCTL8010207c.
The primary driver handler298c reads MSR606[12:8] energy exponent and two MSR611
package-energy values. Helper1000 waits using KeDelayExecutionThread after
forming a negative10-times interval; the100000 argument requests100ms in its
[documented100ns units](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/wdm/nf-wdm-kedelayexecutionthread).
The original delta*10000/2^exponent result is nominal milliwatts, truncated to a
DWORD by the DLL. Native uses actual elapsed time and explicit watts/microwatts,
fixed CPU0 package placement, guarded32-bit wraps and bounded freshness. It
does not replicate an assumed exact sleep duration or unsigned underflow.

The three extrema exports56ab0/56dd0/570c0 require version10, reject the legacy
DD1/5b bit6 error, and use PF bit7 versus DD1/03 bit2 to decide a refresh through
DD81/5a=80. They wait for ready bit3 before helpers534a0/53540/535e0 accumulate
unsigned little-endian words at DD1/90..95. Native fresh qualified block1 words
at offsets16/18/20 retain mV, charge mA and raw unsigned discharge mA. Signed
discharge magnitude in the broader report is a separate presentation.

LifetimeBlock355550 uses the same version/error/refresh gates, ready bit2 and
helper52800's32 DD1/a0..bf bytes. The original helper zeroes individual failed
bytes; native never fabricates partial success. The target's independently
qualified fresh manufacturer block3 has26 complete bytes, with a16-byte time
prefix and ten opaque OEM bytes. Native publishes that complete target payload
with explicit length/scope, rather than appending six unverified cache bytes.
The existing broken legacy cache remains separately unavailable; fresh gauge
measurements do not establish a healthy legacy cache or another firmware layout.

## Seven PDO selectors in0.60

Adapter_Read_PDO1..7 RVAs20b30..20b90 pass byte index0..6 to shared20ba0.
That routine requires firmware version14..7ffffffe, then reads DD6 registers
05+4i down to02+4i, shifting the accumulator8 bits per byte. The result is a
little-endian32-bit object. Unsupported-version and transaction-failure values
are ffffffff and7fffffff; native typed errors replace those sentinels.

The qualified native BIOS provides separate per-port RX_SOURCE_CAPS caches.
Each count1..7 is followed by complete raw objects; AC/port-validity gates and
two complete contract-bracketed passes reject stale/changing data. A raw
active-contract object must appear in that source list. Fixed active-contract
voltage/current/watt consistency is checked as before. A nonfixed active
object does not require an invented fixed conversion to expose raw source
objects. Its type remains unqualified_nonfixed and no limits are inferred.
Native index bounds follow seven source slots instead of the original byte
argument's possible arithmetic wrapping. Other BIOS layouts remain unqualified.

## CPU frequency and power status in0.59

Intel frequency exports3e980/3eae0 select IOCTL80102084/88. Primary driver
handlers259c/2798 extract MSR198[14:8] and MSR1ad[7:0], respectively. Each
multiplies by a reference frequency obtained through command5 on MSR150, with
the original kernel helper performing WRMSR. Those writes are not reproduced.
The qualified CPU supplies reference MHz directly through CPUID.16H ECX[15:0],
as specified in the [Intel instruction manual](https://cdrdv2-public.intel.com/812383/253666-sdm-vol-2a.pdf).
Native reads CPUID and both fixed MSRs in one CPU0 callback; failures stay
independent. Current P-state ratio is distinct from effective busy/idle clock,
and the maximum turbo ratio is distinct from policy limits or all-core maximum.
Original sampling follows its calling processor; native fixes CPU0 explicitly.
AMD90/94 and other processor/model variants remain unqualified on this device.

Power_Read_ACDCMode883a0 reads GetSystemPowerStatus ACLineStatus. The original
BatteryHealthyTable_ACStatus4f1d0 uses that OS status on ARM, or the x86 DD0/1
AC bit after firmware-version discovery. Native ADP1 online is the same native
AC-present quantity with strict errors instead of the original false/sentinel
failure results. Power_PD_Charging880b0 checks AC and version8 DD4/8 adapter
flags; mixed-adapter version11 adds DD4/0c exclusion. Native selects actual
UCSI sink/input PD/PPS state, separate from battery charging and from input ADC
draw. The qualified BIOS's constant60/00 legacy status bytes are not extra
live measurements. Type-C advertisements and unknown/failed providers do not
become PD input.

## Selected driver and user registration in0.58

GetInfVersion RVAa7a40 delegatesa6090. Its fixed UTF16 description is ASUS
System Control Interface V2. CM_Get_Device_ID_List/CM_Locate_DevNode enumerate
present devices; registry property1 selects the description and property0a
supplies the driver registry key. The export opens ControlSet001/Control/Class
and reads DriverVersion. It is not the SDK's literal version. The separate
GetIoDllVersion returns10001, while GetDriverVersion/GetRefCount use driver
IOCTL80102040/44. Native counterparts identify their actual Linux components:
installed system-control platform module, frontend, loaded HealthyTable module
and kernel module references.

Native selection follows the actual asus-nb-wmi driver/module link, which can
refer to asus_wmi rather than the similarly named module. Read-only modinfo
filename/name/version/intree/vermagic fields must agree with the running kernel,
the selected file and stable binding. A declared version is distinct from a
kernel-release version for an in-tree module without its own version string.
No provider/parse error falls back to a frontend constant.

WMISetAppPath's original user-name registration is represented by actual native
caller-owned configuration. Shared privilege-drop plumbing keeps every file
operation unprivileged for sudo/setuid callers, with explicit custom-directory
context. Fixed compat.json updates preserve private bounded JSON, revisions and
unrelated values. This replaces Windows registry/user-name handling without
running the registered application or modifying firmware/hardware policies.

## Remaining OEM wrapper contracts in0.57.1

Adapter_Read_Contract_PDO RVA209e0 reads DD6/21 down through1e, shifting the
accumulator by8 each time: a little-endian32-bit PDO. Errors and unsupported
returns have distinct sentinels; native uses typed errors and the independently
qualified current per-port contract cache, preserving the PDO's limit quantity.

CPU_ReadCpuVoltage RVA3ec60 first checks DSTS120079 present bit16 and low-word
mV. Its Intel branch calls IOCTL80102080. The actual reference ASUS kernel driver
dispatches that opcode to RVA2e54, reads MSR198 through30b0, selects bits47:32,
multiplies by the stored float1/8192 and double1000, then truncates. Native
rounded mV use the same bitfield/scale, with at most1mV presentation difference.
No independent rail measurement or voltage-control facility is inferred.

WOA_EC_read RVA742e0 delegates6cd80, supplying commandcode/param0 to
ec_read_command_byte and parsing its string result. WOA_EC_write jumps to6d5b0,
supplying commandcode/param0/param1 to ec_write_command_byte, with named S5507
family handling. This is separate from native x86 HealthyTable logical registers.
Raw native writes use the exact allowlisted packet directly; bank6[0] is not a
discovered support predicate. The qualified maximum-bank guard rejects absent
banks before I/O. Fan/cache selectors and reviewed-apply requirements remain.
The posted write's input-buffer completion is not a firmware acceptance reply.
Native results retain transport completion and explicitly unknown acknowledgment,
with readback unverified. Firmware effect is not inferred from host-port success.

## OEM control corrections in0.56

Original Power_Set_Monitor_PowerDropped RVA883e0 requires table19+ and sends
DD/87/09 with `(value <<7)+5`. Native boolean0/1 therefore maps to05/85.
Adapter_Read_Power_Data_Flag RVA21e20 reads DD/06/01. Versions14..23 clear
DD/86/01/00;24+ instead send DD/86/35 with the exact byte just read. This
preserves newly arrived bits outside that mask. Standalone clear remains the
legacy register1 command. Notify RVA22270 requires23+ and writes86/36.
Charger clear/read-clear uses27 and28, and PD name reads5/02..0d with request
byte1; these require14+. Typed errors retain failed read/clear stages rather
than inventing a zero. No source operation uses a nonzero bank6[0] predicate.
The qualified .301 transport bank guard remains authoritative and prevents
both read and write access to absent6/7 before I/O. No allowlist expansion.

Reviewed plans bind recipe revision2. Positive packet/version/mask/fault tests
use mocked I/O; current hardware qualification uses reads and plans only.

## Control selection persistence in0.55

Grouped setter/helper review separates immediate WMISetBatteryHealth from
WMISetBatteryHealthToUser. The latter performs the device call, writes the
BatteryHealthLevel DWORD and conditionally saves BatteryHealthSetting.txt through
the registered app-user path. QuietFan likewise saves QuietFanSetting.txt after
its device call. Their setters do not establish an automatic boot reapplication
contract. Native records contain only verified successful selections, with no
Windows registry/filesystem emulation or new charge policy.

The exact installed Power Profiles daemon0.30 source verifies the existing
platform-profile notification path: external profile change -> INTERNAL
activation -> save_configuration. It already persists profile selection.
The native setter therefore retains its existing sysfs primitive and does not
introduce D-Bus Set/hold/action changes or a competing daemon. See the official
[Power Profiles interface](https://upower.pages.freedesktop.org/power-profiles-daemon/gdbus-org.freedesktop.UPower.PowerProfiles.html).
Per-user file access always follows privilege drop to the actual caller; native
hardware readback and preference revision checks remain separate operations.

## Connected network and Bluetooth classes in0.52

RF_Net_Connected_Type RVA94010 delegates9e2a0. The helper reads interface rows
and selects non-tunnel hardware interfaces with media connected, preferring
types6,244,71. Its outputs are Ethernet, WWANPP2, WiFi or an unknown sentinel.
The [MIB_IF_ROW2 definition](https://learn.microsoft.com/en-us/windows/win32/api/netioapi/ns-netioapi-mib_if_row2)
confirms the source field roles. Linux counterparts classify physical device-backed
links using flags/carrier plus existing NetworkManager
[device metadata](https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.Device.html)
and [type values](https://networkmanager.dev/docs/api/latest/nm-dbus-types.html).
A modem's IpInterface maps the data link even when Interface names its control
port. Fixed [CurrentCapabilities](https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.Device.Modem.html)
reads require known cellular capability flags; analog POTS is excluded, and
missing, mixed analog/cellular or unknown families remain unclassified. The
5GNR flag is0x40; no APN/operator/device identifier is read. Known virtual
NetworkManager classes remain excluded even if a device link exists. Native WWAN is broader than the original3GPP2 enum and is labelled generic
cellular. A missing type is not inferred from Ethernet framing, name or operstate.
Two bounded metadata snapshots and local device/link rechecks reject changes.
The provider only reads already-owned D-Bus objects; it does not activate the
service, read connection profiles or query Internet connectivity.

RF_BTConnectedNum/Type/IsUsed delegate941d0. The helper sets only
fReturnConnected in [BLUETOOTH_DEVICE_SEARCH_PARAMS](https://learn.microsoft.com/en-us/windows/win32/api/bluetoothapis/ns-bluetoothapis-bluetooth_device_search_params),
without inquiry, and switches on (ulClassofDevice >>8)&31. Recovered cases1..9
are Computer, Phone, LAN/Network Access Point, Audio/Video, Peripheral, Imaging,
Wearable, Toy and Health;31 is Uncategorized; other codes use Other. Native
[BlueZ Device1.Class](https://github.com/bluez/bluez/blob/master/doc/org.bluez.Device.rst)
is optional. Exact validated24-bit raw class and major label are added without
changing connected counts; absent or invalid properties do not become a class
inferred from the icon, services or device name. The unique daemon owner is
rechecked before returning known data.

## Remaining field recipes reviewed in0.51

The grouped60-field comparison includes fragment fallthrough, not just jump
closure or the first exception range. Chip-buffer RVA51c60 falls through51c8e
and reads14 BB bytes12..1f; numeric chip-name RVA43620 packs only BB12..15.
Family RVA43880 returnsffff when BB51 highbit is clear. Otherwise it packs BB3/4,
normalizing uppercase hex pairs to7fff except AB/AC/CF. ASCII firmware metadata
is a different quantity. ChargingCurrent RVA50d60 ends in movsx of its U16 word.
FullCharged uses DD1/01 bit10. Legacy PFalarm uses DD1/5b bit7 and inverse bit6.

BatteryInformation RVA4f680 rejects cache error bit6; when not busy/timeout it
requests DD[81,5a,10], polls ready bit10 and reads32 DD1/60..7f bytes.
Cached PF uses the existing request80, ready20 and DD1/5c..5f. Native collectors
hold the shared mutex, reject manual ownership, bound readiness polling to four
observations/three1s delays, double-read payload and bracket it with state checks.
Error/busy/transport failure is not success or zero padding. The requests only
refresh volatile firmware read caches; they do not unseal/reset/configure a gauge.
A pre-existing firmware cache error is not bypassed merely to obtain data.

The battery summary helper selects present BATTERY_STATUS.Voltage for the
misnamed high-level DesignVoltage. CapacityPercentage truncates remaining/full
percent then rounds half-up to tens. The native counterpart preserves exact and
bucketed percentages explicitly, with Linux charge-counter units. No nominal
voltage or EC RSOC substitution. ManufactureDate decodes packed SBS date bits and
rejects invalid dates rather than reproducing the original fabricated fallback.
PL1/PL2 original IOCTL80102074/78 choose their output slots; Linux counterparts
use configured RAPL long/short constraint watts, not measured power.

## Battery summary wrapper selections

BatteryHealthyTable_ECChipID RVA51b80 selects BB10 and returns its byte on a zero
transport-error status. ECChipName separately formats four name bytes. Qualified
chip ID0 is valid and differs from ASCII5571. Battery_Read_CellVoltage RVA3b730
writes all four DWORD channels into its output formatter; the former first-cell
alias omitted three readings. Native output keeps the qualified bank1 channels
48/4a/4c/4e and per-channel availability, without a new command.

Battery_Read_ASOC RVA3afd0 returns summary field14. Full helper3b070..3b590 uses
IOCTL294044 BATTERY_INFORMATION;3b28b/28e load DesignedCapacity/FullChargedCapacity,
and3b2a6..3b2b4 divide full by design without a100 factor. Battery_Read_Capacity
RVA3b590 returns field0c, written at3b318..3b320 from BATTERY_STATUS.Capacity after
IOCTL29404c. The [information structure](https://learn.microsoft.com/en-us/windows/win32/power/battery-information-str)
and [status structure](https://learn.microsoft.com/en-us/windows/win32/power/battery-status-str)
confirm the field offsets/quantities. Native ASOC uses same-unit Linux charge
counters; remaining capacity explicitly reports mAh. Windows capacity is energy
or relative, so native charge is not labelled mWh and no energy estimate is made.

## Native inventory identity selections

Original query/property literals recovered from export bodies are:
Baseboard Manufacturer atRVA c4c10, BIOS ReleaseDate c5080, BIOS Name c5590,
Processor Name c62a0, ComputerSystem SystemFamily c72e0, VideoController Caption
c7d10, Baseboard Product cd3a0, OperatingSystem Caption/OSArchitecture cdbf0 and
ComputerSystem Model cf0b0. OS export additionally resolves RtlGetVersion from
ntdll; its Windows version formatting is not reproduced as a Linux build number.
The original [Baseboard Product property](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-baseboard)
selects SMBIOS Type2 product, distinct from system Type1 model/family. Native
kernel board_vendor/board_name/product_family/product_name preserve these roles.
BIOS identity uses native bios_version and validated ISO calendar bios_date;
Windows WMI Name/live string equivalence is outside this native qualification.

GPU descriptions use [pciutils machine-readable output](https://man7.org/linux/man-pages/man8/lspci.8.html)
with explicit linux-sysfs access and numeric IDs. Option-like fields are ignored
regardless of position, with local names matched to stable cached class/vendor/
device identities. No network-resolution or configuration-dump option is used.
Native PCI class03 coverage includes unbound devices; absent descriptions remain
unknown. It is not a Windows driver-provided caption or a non-PCI GPU provider.

Native OS identity follows the [os-release format and precedence](https://www.freedesktop.org/software/systemd/man/latest/os-release.html).
Only declared distribution fields are returned. Quoting is decoded without shell
execution, substitution or concatenated quoted strings. Later duplicate keys win;
invalid selected fields and file races are explicit. uname supplies the separate
kernel version/machine without hostname, and an explicit kernel-ISA mapping
provides width independently of userspace ABI. Optional distribution BUILD_ID is
not replaced by a kernel build string or a Windows build number.

## CPU, platform and desktop metadata

CPU_ReadCpuId atRVA3ea00 extends past its first exception fragment through3eae0.
Its IOCTL80102068 op21 sends the input leaf; driverRVA304f loads EAX, zeroes ECX
at3051 and executes CPUID at3053, returning all four registers. Native unprivileged
C uses that instruction with an optional subleaf extension, and read-only
ARCH_GET_CPUID guards disabled-thread execution. CPU_ReadCPUUsage at3e710 samples
GetSystemTimes twice around Sleep100ms and returns1-idleDelta/(user+kernelDelta),
using the double1 at1ad950. WMIGetCPUUsg separately reads LoadPercentage.
CPU_ReadRegCPUInfo at3ed10 reads CentralProcessor/0 ProcessorNameString;
WMIGetCPUArchitecture reads the [Architecture numeric enum](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-processor).

WMIGet90Number helperbd270 selects OEMStringArray; branchbe2d8 sets SAFEARRAY
index4 before SafeArrayGetElement atbe2ee. Native cached Type11 selection preserves
that exact fifth string, not a SKU or a search for a90 prefix. Other queries read
ComputerSystemProduct.UUID, Bios.SerialNumber and Baseboard.SerialNumber. Native
sources are system product_uuid/product_serial and board_serial with explicit
firmware-counterpart scope. Chassis helper jump/byte tablesD27fc/D2808 classify
Desktop3/13/35 and Notebook10/30/31/32, unknown otherwise. Card-reader selection
is fixed DeviceID USB VID0BDA/PID0129; MAC source uses physicalAdapter=true.
Local-time formatting uses local CRT strftime %Y-%m-%d %H:%M:%S.

AppList_OpenWindows export28440/worker28600/callback32ab0 enumerates native Win32
windows and emits process_name/process_title/cpu_usage/mem_usage/z_order/is_focused.
Windows enabled/visible/active-popup/toolwindow/titlebar/title filters have no
identical Wayland API. Native selection uses compositor normal Alt-Tab membership
without reading titles for selection. [Mutter get_tab_list](https://mutter.gnome.org/meta/method.Display.get_tab_list.html)
with null workspace covers workspaces, and [sort_windows_by_stacking](https://mutter.gnome.org/meta/method.Display.sort_windows_by_stacking.html)
returns lowest-first, reversed explicitly. Selected PIDs reuse the validated
procfs CPU/RSS collector without positive/ranking filters. An additional identity
check after the final compositor query rejects recycled PIDs. AT-SPI fallback
uses the official [Accessible interface](https://github.com/GNOME/at-spi2-core/blob/main/xml/Accessible.xml)
GetChildren/GetRole/Name via pinned unique owners; application PIDs come from the
bus daemon. No libatspi initialization or service activation is used. Its native
coverage remains partial with explicit unknown compositor fields.

## Application registrations

GetApplist_x64/x86 call machine helperRVAa3d00 (HKLM80000002) and user helper
a25d0 (HKCU80000001). Their native/WOW6432 uninstall paths differ; helpers read
DisplayName, DisplayVersion and SystemComponent. App_Get_Win32App/WOW6432 use
HKLM plus registry enumeration helper3a2f0 and their respective uninstall paths.
Both UWP exports enumerate HKLM AppxAllUserStore Applications; App_Get_UWPApp
also normalizes the package-name prefix. Native JSON preserves package identity
and metadata, rather than reproduce Windows prefix/string formats or guess a
Linux equivalent of SystemComponent.

Native providers use [dpkg-query status metadata](https://manpages.debian.org/testing/dpkg/dpkg-query.1.en.html)
and dpkg-architecture ABI widths, [Flatpak list](https://docs.flatpak.org/en/latest/flatpak-command-reference.html)
app/runtime plus all-extension registrations, and the installed-only
[snapd Unix REST API](https://snapcraft.io/docs/snapd-rest-api) GET/v2/snaps?select=all.
No POST or remote store-search endpoint is implemented. Matching installed snap
manifests are identity/race checked and safely parsed for declared architectures.
The [snapd2.77.1 parser](https://github.com/canonical/snapd/blob/2.77.1/snap/info_snap_yaml.go)
defaults an omitted/empty architecture list to all; that format default is labelled
and never replaced by the host's ISA. Native source/scope, partial errors and
optional unavailable fields remain explicit. No Windows registry access occurs.

## Application process counters

Original CPU worker RVA2c140 and memory worker RVA2d6c0 query
Win32_PerfFormattedData_PerfProc_Process for Name, IDProcess,
PercentProcessorTime and WorkingSet. Both exclude IDProcess0. Comparators
RVA30560 (float+40/seta) and RVA320b0 (signed+44/setg) rank descending. CPU
checks positive values at2ce31 and stops after5 at2d2ab; memory caps size at10
at2e303 and checks positive memory at2e3d5. Both emit CPU/memory values.
Original CPU formatting divides by the hardcoded float64 ten at1acc78;
WorkingSet is converted through a signed32-bit value and divided by1024.
Native Linux units are explicit and avoid that presentation divisor/overflow.
The CPU loop's missing small-vector bound is not reproduced.

Native fixed procfs fields follow the [kernel procfs documentation](https://docs.kernel.org/filesystems/proc.html):
comm/state, user/system CPU ticks, starttime and statm resident pages (with a stat
identity bracket). Two measured
samples use PID/starttime identity and actual clock-tick/page units. Sorted top
limits and positive filters follow source selection; error/partial-census
metadata and PID tie order make native coverage explicit. No UID filter,
command-line/environment read or psutil name expansion remains in these routes.

## Application hardware configuration

Original `AppList_HardwareConfig` at RVA27900 queries `ROOT\WMI` / `select *
from WmiMonitorBrightness`. Helper RVA2b640 reads `CurrentBrightness` and
overwrites the result on each monitor. Helper RVA319c0 uses the MMDevice
enumerator and IAudioEndpointVolume GUIDs, selecting default render endpoint
with data-flow0/role0. Vtable slots9/15 read scalar volume/mute; scalar is
multiplied by100 and truncated to integer, with zero emitted when muted.
The [Microsoft SDK interface](https://github.com/microsoft/win32metadata/blob/main/generation/WinSDK/RecompiledIdlHeaders/um/endpointvolume.h)
confirms method order; the [brightness class](https://learn.microsoft.com/en-us/windows/win32/wmicoreprov/wmimonitorbrightness)
documents its percentage field. These are static source/interface proofs,
separate from execution of Windows binaries or device qualification.

Native output keeps all kernel backlights with actual/max percentages and
the user's default PipeWire output via the read-only
[`wpctl get-volume`](https://pipewire.pages.freedesktop.org/wireplumber/man/wpctl.html)
command. It retains configured volume and mute separately, with effective
percentage zero on mute and explicit independent field errors. PipeWire gain
above100% is preserved. Native percentages describe each platform's software
setting; matching audio curves, physical luminance and sound pressure are not
claimed. This replaces the old unrelated CPU/RAM/process-list payload.

## HealthyTable

The qualified x86 interface uses ports 0x25c/0x25d and protocol version 15.
The transport reserves both ports, serializes requests, bounds transaction
waits and validates a fixed packet set. Bank/register recipes are in the
portable protocol headers and have fault-injected tests.

Fan test mode must be enabled before writing the hardware duty because enabling
clears a preloaded hardware target. The hwmon target is cached in automatic
mode; the driver applies it only after taking manual ownership. Fan status and
RPM are checked by the kernel watchdog, which restores automatic operation
on a lost/stalled fan or communication error. Existing firmware ACPI fan status
on this BIOS references a missing CFSP object; this driver uses the recovered
HealthyTable fan register instead.

## EC USB-C active contract

The UP3404VA.301 ACPI device `\\_SB.PC00.LPCB.H_EC` has a serialized `RDER`
method. It acquires the firmware EC mutex and reads one EC RAM byte through
its command mailbox. Operation 12 of the root-only native RPC reads a fixed
allowlist; it accepts no address, write/apply flag or controller command.
`WTER`, raw Super-I/O access and host SMBus transfers are not exposed.

| Cache field | EC address |
| --- | --- |
| AC/battery presence, adapter whole watts | 0x0380, 0x0381 |
| Port A contract-valid bit 6, watts | 0x0bf0, 0x0ab1 |
| Port A nominal mV, mA; little-endian words | 0x0ab2, 0x0ab4 |
| Port A active PDO; little-endian dword | 0x0b28 |
| Port B contract-valid bit 6, watts | 0x0bf1, 0x0aba |
| Port B nominal mV, mA; little-endian words | 0x0ab6, 0x0ab8 |
| Port B active PDO; little-endian dword | 0x0b98 |

These locations and the firmware's parser/clear paths were checked against
this machine's EC firmware code. A live port A read independently agrees on
20,000 mV, 3,250 mA, 65 W and PDO 0x00064145. A physical unplug/port B/port A
test also verified clearing and both connector mappings; see VALIDATION.md.

Two complete identical passes are required; changing snapshots return EAGAIN.
Userspace requires AC presence, the per-port valid bit, a fixed-supply PDO and
agreement between the PDO and cached mV/mA/watts. Unplugged stale values are
suppressed. Unsupported types remain unavailable. These fields describe a
negotiated supply limit, not ADC readings or instantaneous consumption.
The ACPI method's firmware-level error return is byte 0xff, so status and
cross-field consistency checks are essential; it is not an independent PD analyzer.

## PSYS platform power and public monitoring

On the qualified Intel machine, MSR_PLATFORM_ENERGY_STATUS (0x64d) contains a
changing 32-bit platform energy count. Energy units come from
MSR_RAPL_POWER_UNIT (0x606), bits 12:8, giving 2^-unit joules per count.
The qualified machine reports exponent 14. Two independent direct-register
intervals matched Linux's `intel-rapl:1` / `psys` conversion (18.7778 W and
26.5967 W); installed hwmon later matched at 31.7738 W.

Read-only `power1_input` gives microwatts from energy delta / elapsed time,
with a one-second cache and bounded intervals. Handle one unsigned 32-bit wrap;
reject stopped/zero counters, implausible power, intervals below 100 ms or
above 30 s. Suspend/resume invalidates the baseline. A first sample returns
unavailable until another valid interval, never a fabricated zero. No RAPL
power limit, calibration or mailbox is written. This is hardware-reported,
sampled platform power, not an independently calibrated USB-C or wall meter.

The fixed `pd_contract` monitoring attribute is world-readable and cached for
two seconds. Its schema-1 JSON wraps the same validated snapshot bytes used by
the root-only operation 12, in a separate buffer so it cannot affect RPC
nonces/responses. Manual fan ownership returns EBUSY even for a cached sample.

This firmware's recovered SMBus polling descriptors cache charger settings
and status, but no input-current (0x83) or input-voltage (0x87) ADC results.
The 0.11 OEM combined-read worker supplies a firmware-mediated path with a
pending-transaction drain; host controller access and ADC-control writes remain
unexposed. See the current provider below. The charger-family datasheet
describes direct measurements, but their existence alone does not establish
a working Linux access path or the board's sense-resistor calibration.

References: [Linux RAPL implementation](https://github.com/torvalds/linux/blob/v7.0/drivers/powercap/intel_rapl_common.c),
[Renesas ISL9241 monitoring and ADC registers](https://www.renesas.com/en/document/dst/isl9241-datasheet).

## Historical read-only EC investigation before 0.11

A fixed, temporary read-only qualification probe verified the firmware's
0x92 EC command through Linux `ec_transaction()`, using the actual H_EC device,
the firmware ECMT mutex and the kernel EC transaction lock. Address order is
high byte, then low byte. Four known RAM reads matched ACPI RDER exactly;
an initial reversed-order probe was rejected because it did not match.

The RDER mailbox's recovered range check permits only the first 4 KiB of EC
RAM. The alternative 0x92 path reaches the SMBus controller at 0x1c11–0x1c16.
Read-only status/staging reads succeeded. One sample showed an idle control
value 0x0c and the last battery transaction (address byte 0x17, register 0x19,
data 0x1f2c). These are observations of the EC's bus controller, not new
transactions to the charger or fresh ADC measurements.

The firmware-polled charger Control3 cache at 0x08be contained 0x4003. In the
ISL9241-compatible register layout, bit 0 indicates the ADC is enabled. Cached
Information2 was 0x4c44, consistent with AC present and forward buck operation.
This does not independently verify the physical chip's manufacturer/device ID,
cache freshness, ADC current or sense-resistor calibration.

The legacy ACPI SMPT/SMST/SMAD/SMCD field names do not prove a functional
standard SMBus bridge: this firmware uses SMPT=0xaa for modern-standby entry,
and the other putative bridge registers have no recovered transaction handler.
Do not initiate transactions by writing a presumed standard protocol there.

During that read-only phase, no 0x93 register write, raw Super-I/O access,
SMBus START, charger configuration write or firmware update was executed.
Safe host/EC SMBus arbitration was still unresolved. No general register-access API or experimental transport was added
to the installed driver; current/power ADC availability is unchanged.

## ASUS WMI

The native module calls the existing ASUS WMI kernel provider. Fixed query IDs:

| Function | Method/device/argument |
| --- | --- |
| CPU voltage | DSTS, 0x120079, 0; present bit 16, low word millivolts |
| Adapter wattage | DSTS, 0x1200f2, 1/2/3; present bit 16 |
| Generic sensor mask | DSTS, 0x60068, 0; `p_sensor` mask |
| EEPROM read recipes | DEVS, 0x60059; recovered version/date/count/read selectors |

The earlier generic-sensor mapping to a voltage query was incorrect and is
corrected in 0.7. Unknown WMI queries and EEPROM selectors are rejected.
The local firmware's decoded methods expose an empty generic sensor mask and
no responding adapter/CPU-voltage/EEPROM feature. This is different from an
unimplemented Linux query.

The original ARM WOA interface calls `ATD_STS.ec_read_command_byte` and
`ec_write_command_byte`, passing commandcode/param0/param1. It is not the x86
HealthyTable bank layout. No ATD_STS provider is present on the qualified machine.

## XG Mobile

`GetXgmFw` selects ASUS VID 0b05, PID 1970 (GC31) before PID 1a9a (GC33), on
the HID application collection usage page ff31, usage 0076. The firmware query
is a 64-byte feature SET with report ID 5a, command a0, followed after 100 ms
by feature GET 5a. The source copies32 bytes from offset1 (command plus31 bytes)
and returns the31 firmware bytes followed by its initialized zero byte. Native
retains exactly bytes2..32 as its firmware payload; byte33 is outside that copy.
Native code parses the complete HID descriptor, rechecks collection and device
identity on the opened handle before a feature request, rejects ambiguous
matches, requires the complete reply, closes the
handle on all paths and never exposes firmware-update commands. Real GC31/GC33
qualification remains pending because no device is connected.

## UEFI

CNFG, MFG0 and HEAL use GUID 91b89306-5bac-4ae0-aab3-207ec12e989b.
OemBDConf uses f952fc4a-5222-4dbb-9302-c9b9dd9d7c9c.
For the source's ASUS2025 branch, activation/UUID CNFG selects
329d6974-be41-4325-b2fd-ad693193525b; manufacturing/HEAL/CSC/language operations
skip that branch. Current qualified hardware has no ASUS2025 identity. No other
family is physically qualified by the native implementation.

| Field | Record/data offset/length |
| --- | --- |
| Stored UUID | CNFG / 0 / 16 raw bytes |
| Activation time | CNFG / 32 / 19 |
| OS language | CNFG / 112 / 8 |
| Manufacturing time | MFG0 / 148 / 23 |
| CSC repair flag | HEAL / 1 / 1 |
| CSC clear command | OemBDConf / fixed command byte 77 |

The efivarfs four-byte attributes prefix is preserved. Records must have the
expected layout. Writes use full-record revision checks, verified backups,
temporary immutable handling only with opt-in, and exact readback. No arbitrary
variable creation/deletion or factory mutation is part of qualification.

Grouped0.56 review follows all ten export bodies and the Windows privilege,
identity and write-fallback helpers. The fallback resolves the registered
DriverStore secgpnv `CcSetFirmwareEnvironmentVariableW` for the same variable,
GUID, payload and length; it is Windows service plumbing rather than another
field format. Native efivarfs remains the Linux provider. The source takes the
language from its caller, copies raw UUID bytes and formats all256 HEAL bytes
as hexadecimal. Independent native/CLI/C reads and five reviewed-plan result
digests match direct record slices; simulated writes retain backup/revision/
attributes/immutable behavior. Physical factory writes remain unperformed.

## Linux interfaces

ACPI `_UPC` values 00/03 mean host type A and 08/09/0a mean type C; nonconnectable
ports are internal. Native code obtains the real ACPI package and matches USB
root-port firmware paths, avoiding connector guesses. USB activity uses
MON_IOCX_GETX with a NULL data pointer and zero allocation; only aggregate
bulk/isochronous completion counters are returned.

Reference interfaces:

- [Linux WMI development guide](https://www.kernel.org/doc/html/latest/wmi/driver-development-guide.html)
- [Linux ASUS WMI implementation](https://github.com/torvalds/linux/blob/master/drivers/platform/x86/asus-wmi.c)
- [HIDRAW feature reports](https://www.kernel.org/doc/html/latest/hid/hidraw.html)
- [USB monitor binary ABI](https://www.kernel.org/doc/html/latest/usb/usbmon.html)
- [ACPI USB port capabilities](https://uefi.org/specs/ACPI/6.4_A/09_ACPI_Defined_Devices_and_Device_Specific_Objects.html)
- [efivarfs format and immutable protection](https://www.kernel.org/doc/html/latest/filesystems/efivarfs.html)

## 0.8 CPU voltage and UCSI fallback

On the qualified Intel model, read-only MSR_PERF_STATUS (0x198) bits 47:32
provide a changing P-state voltage code. Divide by 8192 volts and round to
millivolts for hwmon. Reject zero/reserved/implausible codes. The kernel uses
rdmsr_safe_on_cpu on CPU 0, never a write or overclocking mailbox. This report
is CPU-reported P-state voltage, not an independent motherboard ADC reading.
[Documented Intel voltage field](https://community.intel.com/t5/Software-Tuning-Performance/MSR-PERF-STATUS-voltage-reading/m-p/1169885).

The TI TPS65994BF controller responds to standard UCSI GET queries through
kernel debugfs. The qualified BIOS's GET_PDOS reply begins with count 4 and
then fixed PDOs, but the 16-byte response cuts off the fourth object's final
byte. The firmware repeats the same reply for different offsets/counts and also for
local/partner and source/sink selections; the requested target is not verified.
Decode only complete objects: 5 V/3 A, 9 V/3 A, 15 V/3 A. Do not infer the
fourth PDO's type/flags or a maximum charger rating from its truncated bytes.
The kernel's live vbus/average/peak counters return zero and are represented
as unavailable, not as measured zero. Only fixed GET operations are exposed;
there are no reset, role swap or power-control commands. Connector-two counters
are not inferred from the first connector's debug fields.

## Charger input ADC in 0.11

On UP3404VA.301, OEM indexed getter/setter commands 0xaa/0xab operate a
volatile EC request mailbox. Combined operation 4 uses the EC firmware's
pending-SMBus drain and completion bookkeeping before a synchronous register
pointer/write followed by read. It is distinct from the other raw transfer
operations, which are not exposed. Channel B, wire address 0x12, one pointer
byte and two response bytes are fixed. The accepted chip registers are only
0xfe, 0xff, 0x4c, 0x4e, 0x4d, 0x83 and 0x87. No charger setting is written.

The kernel holds its transport lock and firmware ECMT throughout. It refuses
an active OEM/test mailbox or manual fan ownership; saves, restores and verifies
all ten touched IPC bytes, including buffers and count; and disables further
ADC requests on a restoration failure. Fixed 0x92/0x93 EC access reads/restores
only this IPC state. There is no general register/address/write API. Hardware
errors and successful samples are both cached for two seconds; suspend/resume
invalidates the cache. Load/probe performs no charger transaction.

Manufacturer/device IDs must equal 0x0049/0x000e. ADC enable, AC presence,
forward power-stage operation and firmware shunt-ratio configuration are checked.
Voltage before/after the current read must agree within one 96 mV step; 0.11.1
retries that measured triplet at most twice before reporting EAGAIN. Current
is eight bits; voltage uses bits 13:6. Missing or changing data stays unavailable.

The board's firmware converts PD current in mA to half-scale adapter-current
DAC values. A stock 3,250 mA contract yields the 0x0658 DAC value (1,624 nominal
mA before board scaling). Together with the battery-current halving and 2:1
shunt configuration, this qualifies a 10 milliohm input shunt: 44.4 mA/ADC count,
not the datasheet's 22.2 mA figure for a 20 milliohm shunt. Input voltage is
96 mV/count. Watts are calculated from these measured input voltage/current
samples; Intel PSYS is independent. No load/battery-flow power estimate is used.
This is not AC wall consumption or an external meter calibration.

Read-only `charger_adc` schema 1 contains raw words, converted integer units,
resolution, shunt scale and cache age. Standard hwmon exposes input millivolts
at `in7_input`, rounded milliamps at `curr3_input`, and microwatts at `power2_input`.
Userspace attributes a sample to a connector only when exactly one valid PD
contract is active. Original opaque ASUS diagnostic APIs retain their own
unavailable results when the firmware does not implement them.

## Extended ISL9241 monitoring and source capabilities (0.12)

Additional fixed combined reads: battery-voltage ADC 0x81, die ADC 0x82,
discharge-current ADC 0x84, charge-current ADC 0x85, system-voltage ADC 0x86,
Information1 0x3a and realtime Information4 0x91. Information3 0x90 clears
interrupt state on read and is excluded from the allowlist. The existing OEM
worker, EC mutex, idle gating and verified volatile-mailbox restoration apply.
No charger configuration register write is exposed. Information2 and ADC enable
are checked before and after the sample. ADC-disabled battery modes return
unavailable channels while retaining valid realtime status.

The board's 5 milliohm battery shunt is qualified from OEM current-DAC scaling
and the input/battery-shunt ratio bit. Renesas ISL9241 Table 12 and Equation 3
supply conversion units: charge 44.4 mA/code, discharge 88.8 mA/code, VBAT pin
64 mV/code, VSYS 96 mV/code, die code = 251.7 - 0.6154 * degrees C. Pin voltage
is not relabelled as battery pack voltage. External meter calibration is pending.

Firmware polling descriptors map port 0 register 0x30, length 29, to XDATA
0x0b32; port 1 maps the same register/length to 0x0ba2. These match the public
TI RX_SOURCE_CAPS layout: count and seven LE32 objects. Only these fixed ranges
and existing contract addresses are read via ACPI RDER. Stale inactive-port data
is discarded. Contract fields bracket each complete pass; two equal passes
reject transitions. Userspace checks PDO counts, first 5 V profile, padding and
active-contract membership. No controller request or PD role change is issued.

Primary documentation: [Renesas ISL9241 datasheet](https://www.renesas.com/en/document/dst/isl9241-datasheet),
[TI TPS25750 host interface reference](https://www.ti.com/lit/pdf/slvuc05)
(layout reference; no assertion that the target controller is TPS25750).

## Thermistor and battery-gauge recovery (0.13)

The qualified ACPI SEN1..5 _STR/_TMP methods provide component names and TSR
fields. ERAM is based at 0x300. Firmware HealthyTable selector dispatch maps
indices 1..5 to0322/0329/0324/0325/0326, yielding SSD/ambient/CPU/charger/DDR.
Selector 0 is ignored, explaining the duplicated previous reading in older code.
Selection is now read, validated, restored, and fault tested.

The DE broker's original safety/PF recipe also supports fixed read-only
manufacturer identification, DAStatus and lifetime selectors. Only 1,2,60,62,
63,64,71,72 are added. Its firmware worker drains pending SMBus work. The
0x4556 OEM identity and firmware prefix45560234004002 qualify this layout;
the physical IC vendor is not proven. DA1's first 20 and DA2's first 14 bytes are
qualified. Temperature/current polarity and inactive-cell/input checks agree
with the existing battery gauge readings. Shared XDATA0354 overlaps byte 31
of the response and firmware scratch; it is deliberately excluded. Short block
prefixes avoid leftover data from preceding responses. Lifetime prefixes require
two matching fresh queries and carry explicit partial-layout limitations.

## Fixed PD received-identity access (0.13)

Own firmware poller code identifies channel A and wire addresses 40/48 for the
TPS65994BF controller's two ports. A temporary fixed read probe returned APP
mode, complete source-profile prefixes and25-byte identity-register payloads.
Both SOP48 and SOP-prime49 records had response status0. The native reader
permits only03/48/49 register pointers, one output byte,5/26 input bytes, and
operation4 of the serialized broker. It saves/restores/verifies all 34 touched
volatile mailbox bytes and shares the restoration-failure latch with charger
access. It never writes a controller value or 4CC command. Contract snapshots
bracket the operation; unknown mode/length or changing contract returns an error.

Layout references (format references, not a claim that the OEM gauge is TI or
that the controller is the older D model): [TI battery manufacturer-data formats](https://www.ti.com/lit/ug/sluubu5a/sluubu5a.pdf),
[TI received-PD identity format](https://www.ti.com/lit/ug/slvubh2b/slvubh2b.pdf).

## Lifetime event prefixes (0.14)

Read-only DE manufacturer selector 0x61 adds only its first four bytes, covering
shutdown, partial/full reset and watchdog reset counters. Qualified lifetime
prefix lengths for 0x60/61/62/63/64 are 31/4/4/31/31. Blocks4/5 use 16-bit event
count/last-cycle pairs in the target-qualified compatible layout. The final pair's
count is complete, but its last cycle extends into excluded firmware scratch;
never pad a missing high byte or infer it from the current battery cycle.

Format reference: [TI BQ40z50-R3 lifetime blocks](https://www.ti.com/lit/ug/sluubu5a/sluubu5a.pdf).
This is a layout reference, not proof of the physical OEM gauge vendor. A short observation did not establish the OEM
runtime counter units or its update cadence.
The four-byte reset prefix and two event cycle values have independent live checks;
zero safety event counts are format-qualified, not induced-fault validation.

## Received PD Alert Data Object (0.15)

The fixed TCPC register set now also permits read-only0x74 (one pointer byte,
five response bytes including the length). Its four-byte payload was independently
read on both endpoints. Received-alert data use the same ECMT/driver locks,
contract bracket and 34-byte volatile-mailbox restoration as received identity.
Wrong lengths and failures return no partial sample; restoration failure latches
further controller access off. No transmitted-alert0x75 or arbitrary pointer is
accepted. [TI received-ADO format](https://www.ti.com/lit/ug/slvubh2b/slvubh2b.pdf)
is supported by the measured length; incompatible extended/status layouts remain
unqualified. The full native ADO is distinct from the original single cache byte.

The original e-marker header starts at bank6/0x37, certificate at0x3b, product
at0x3f, and opaque Other at0x47. That offset corresponds to received VDO index4.
The native reader requires a complete acknowledged response containing that VDO.

## Complete battery blocks (0.17)

The fixed opcode0x10/subindex11 dispatch uses the firmware SMBus block routine
with the independent XDATA9040 receive buffer. Channel B, wire16 and read
command23 are fixed. The original DE broker selects only the already-qualified
identity/firmware and lifetime read commands. No raw host SMBus-controller access,
gauge configuration, unseal/reset or arbitrary command is exposed.

The reader requires all16 OEM control bytes to be idle, holds the driver lock and
ECMT, and snapshots/restores/verifies48 volatile control/RX bytes. Different5a/a5
RX sentinels and two equal replies prove every requested byte was replaced and
reject short or overlong responses. The complete data must also match the
original DE prefix. Restoration failure latches controller access off.

On the exact qualified OEM gauge the observed lengths are32/8/26/32/32 for
selectors60..64. These recover byte31 of blocks1/4/5 without scratch overlap.
The FET maximum and complete last-cycle fields use the same supported prefix
layout. Block2/3 lengths disagree with the TI reference20/4; their additional
bytes are exposed raw, with no balancing or time-unit claim. Actual IC vendor
and runtime cadence remain unverified.

The older [BQ40z50 reference](https://www.ti.com/lit/ug/sluua43a/sluua43a.pdf)
does describe the eight-byte reset/balancing layout, supporting the four existing
byte-sized reset counters. Its runtime block contains sixteen bytes of16-bit
fields, also unlike the observed26-byte OEM payload. The previously published
four-byte runtime integer is an opaque prefix; it may combine fields. Neither
an R3 four-byte-runtime interpretation nor an older two-hour conversion is
qualified for this OEM response. Resolving that requires additional target evidence.

## Complete changing battery measurements (0.18)

The same fixed block worker reads DAStatus selectors71/72 as32/24-byte frames.
The exact device and firmware gates, idle checks,48-byte snapshot/restoration,
ECMT/driver serialization and shared restoration-failure latch are retained.
The original fast five-second sensor path remains separate.

Live data can change between requests. The reader fills the independent RX buffer
with5a, issues one fixed read and inspects the complete32-byte buffer. The firmware
worker writes the response sequentially: a replaced final requested byte proves
the expected extent, while an untouched suffix rejects longer replies. If the
last byte equals the sentinel, a single fresh request usesa5. Every accepted
frame comes from one transaction; separate live replies are never blended or
required to match. Short replies retain their sentinel and fail both attempts.

The qualified DA1 prefix extends through four signed cell powers, total power
and average power in centiwatts. Only the two populated cells are published;
same-frame voltage/current validate the declared power encoding without replacing
a rejected value with locally calculated power. These values are computed by the
gauge, not a separate power ADC. Nonzero scaling still needs physical qualification.
DA2 word7 is the gauge's algorithm temperature in0.1K, not a new thermistor.
The final eight OEM DA2 bytes remain raw. The two frames may have different
sample times. A separate15-second read-only cache servesbattery_gauge_extra and
temp17_input; failures return no partial frame and suspend/resume invalidates it.

The [BQ40z50-R2 reference](https://www.ti.com/lit/ug/sluubk0b/sluubk0b.pdf)
documents the compatible32-byte DA1 and16-byte DA2 prefix. The actual OEM DA2
frame is24 bytes; this reference does not identify the physical gauge vendor.

## Complete SBS battery identity (0.20)

The original bank1 manufacturer/model cache reads time out on this BIOS; their
empty strings previously propagated as successful API values. A fixed private
probe used the qualified battery-only SMBus worker to read SBS commands20/21,
returning complete10/7-byte reported strings. These are standard block READ
commands, not ManufacturerAccess selectors with the same numeric values.

The native reader accepts only those two commands, exact OEM identity/firmware,
channel B/wire16 and the established opcode10/subindex11 worker. Two passes use
5a/a5 RX sentinels to find a1..32-byte written extent and require equal contents.
It never selects an unseal, FET, configuration or reset operation. The existing
48-byte snapshot/restore/readback and shared fault latch apply. A separate300s
cache invalidates after suspend/resume and explicit reprobe.

Printable strings feed native APIs and the old sysfs text attributes. Raw bytes
remain separate from text; the original ASUS GaugeIC convention is the fourth
reported manufacturer byte, with no physical vendor interpretation. The complete
gauge DeviceType0x4556 and firmware remain separate identifiers.

Newer [R4](https://www.ti.com/lit/ug/sluuch2/sluuch2.pdf) and
[R5](https://www.ti.com/lit/pdf/SLUUCN4B) references were also checked for the
remaining DA2 fields. Both declare24 bytes but enumerate13 two-byte fields,
including UserTemperature, which would require26 bytes. The actual24-byte OEM
tail cannot be assigned those offsets reliably; it remains raw. Neither manual
establishes the OEM history layout or physical vendor.

## USB display and UCSI capability audit (0.21)

The native USB display query uses DRM connectors with a USB device ancestor and
the Linux partner DisplayPort alt-mode ABI. Only partner modes with SVIDff01 are
considered; local mode capability does not prove use. The kernel's configuration
attribute describes the partner role, so an active sink partner plus selected
pins means local DP source transport. Status, object identity and configuration
are read again; changing metadata produces an unavailable object. Unmapped
external or virtual outputs remain unknown, while independent positive evidence
is preserved. No modeset, role swap, alt-mode write, EDID or serial read is used.

Primary references: [Linux DisplayPort driver](https://github.com/torvalds/linux/blob/master/drivers/usb/typec/altmodes/displayport.c),
[Linux Type-C ABI](https://www.kernel.org/doc/html/latest/admin-guide/abi-testing.html).
The kernel configuration is evidence of reported transport, not a verified picture
or identification of the HDMI side of an adapter.

A fresh fixed UCSI GET_CAPABILITY returned two connectors, features0 and platform
PD revision0x0200. Neither cable-details nor GET_PD_MESSAGE is advertised. Capability
bits alone are insufficient on this firmware: GET_PDOS already works despite its
missing capability bit. One fixed GET_CABLE_PROPERTY on the active charger port
therefore checked the alternative directly. It returned16 zero bytes with the
contract and automatic fan preserved; those bytes cannot qualify usable cable
properties. No PD-message/discovery/reset/power/role command was sent. The
platform revision is not the partner/charger revision.


## Direct SBS read words (0.23)

The existing synchronous OEM combined-read operation4 also works on the
qualified battery route: channelB, wire address0x16, outgoing length1, incoming
length2. Only the fixed command byte is sent; no SBS data byte is written. The
allowlist is1a,03,08,09,0a,0b,14,15,0c,0d,0e,0f,10,17,18,19. This is separate
from both the block worker and ManufacturerAccess selectors. BatteryStatus16,
serials, configuration changes and arbitrary commands are excluded.

The collector snapshots49 volatile mailbox bytes (including9010), refuses a
busy request, verifies the existing gauge type/firmware, validates completion,
uses RX sentinels to reject incomplete words, and brackets mode/specification.
Every mutation path restores all bytes and verifies them; a restoration failure
latches the existing shared controller fault. Manual fan ownership blocks reads;
suspend/resume invalidates the30-second cache. The words are sequential samples,
not a simultaneous frame. Specification0x0031 is qualified; other scaling/version
values are unavailable. Capacity mode0 reportsmAh; mode1 reportscWh, converted
toWh without a voltage-based estimate. 0xffff desired-current/voltage values mean
maximum requested, not a physical measurement. Average current is signed.

The private target test completed32 reads and restored all49 bytes. Both passes
reported the same design/full capacities and cycle count as independent Linux
battery data, while direct pack voltage matched the live gauge cell sum rather
than Linux's design-valued voltage. Full-battery charge requests were zero;
nonzero charging/discharging tests remain pending. IC vendor identity is still
unknown: the compatible TI reference defines units but does not identify this IC.

Reference: [TI SBS command descriptions and scaling, sections14.4 and14.9-14.27](https://www.ti.com/lit/ug/sluubk0b/sluubk0b.pdf).


## UCSI, CPUFreq and loaded-driver status (0.24)

Linux UCSI `power_supply` voltage/current properties are derived from source
PDOs, the request RDO, or nominal Type-C voltage/current advertisements. They
are not electrical ADC readings, even though their sysfs names end in_now.
The native report uses explicit `ucsi_values` names and measurement=false;
legacy measurement slots stay null. Disconnected defaults are suppressed,
source-facing current advertisements do not indicate local charging input,
and independent maxima are not multiplied into power. Actual shared-input
measurements remain in `charger_input` from the separate ISL9241 ADC.

The PD input Boolean requires validated online/status/selected USB type, with
PD orPPS, local sink role and enabled input path. This reports input-path state,
not battery charging current; a full battery can still have PD input online.
Known positives survive another unavailable port. A negative requires known
state for every UCSI supply. Mandatory failures, contradictory roles, changing
identity/state/inventory remain unavailable; optional metadata errors do not
invalidate known input state. No Type-C/PD command or property write is used.

CPU frequencies are positive kernel CPUFreq kHz readings converted toMHz.
A maximum requires every enumerated policy for that field; partial policies
remain visible but do not create a false global maximum or zeroMHz. Current
and possible maximum have independent availability. `scaling_cur_freq` is
explicitly driver-reported and may represent a requested P-state; no exact
instantaneous hardware-frequency claim is made. Policy identity/inventory
changes are rejected. Dedicated original API routes avoid unrelated full EC
sensor queries. Loaded module version/refcount use fixed validated reads and
an identity bracket, without successful empty/zero error defaults.

The signed-current conversion accepts only an actual unsigned16-bit EC word.
0xffff decodes to-1mA; invalid/missing raw words become null. The common original
API filter preserves this legitimate signed value instead of treating it as the
unavailable marker used by other raw HealthyTable fields.

References: [Linux7.0 UCSI power supply implementation](https://github.com/torvalds/linux/blob/v7.0/drivers/usb/typec/ucsi/psy.c),
[CPUFreq policy attribute meanings](https://docs.kernel.org/admin-guide/pm/cpufreq.html).


## Wireless link and BSS-cache sources (0.25)

Fixed `iw dev <kernel-interface> link`, `station dump` and `scan dump` are the
only new nl80211 queries. `scan dump` retrieves the existing cache; no trigger,
scan request, association, disconnect or property write is permitted. Interface
name/index/inode, association and inventory checks reject hotplug/roam races.
Unknown connection state stays unknown; independent known positive links survive
other-port failures. The scalar link APIs choose the first associated interface
by kernel name. A structured native metrics report retains every interface.

Link RSSI requires an explicit dBm unit. Rates are currently reported TX/RX
link rates, not throughput or maximum card capabilities. MCS/PHY markers are
read only from bitrate lines, never from SSID text; unavailable formats stay
unknown. Decimal whole-MHz formatting is accepted without rounding fractional
frequency into a guessed channel. Linux channel formulas include5935MHz/channel2
and4.9GHz channels. Active-peer station signal/chains are matched by associated
BSSID rather than the first station; physical main/aux antenna mapping is unknown.

RSSI-count APIs use kernel cached BSS records directly, rather than joining two
independently aging caches. Only explicit dBm qualifies. Unspecified0..100 quality
cannot be converted or compared to a dBm threshold. An unknown target-band value
makes an exact count unavailable unless another local interface has a known
qualifying measurement for that same BSSID/frequency. Duplicate observations
count once, using any qualifying local observation. Cache ages are not promoted
to fresh measurements. Empty successful kernel dumps mean zero cached records,
not proof that no access point is currently nearby.

Other AP-count/channel/U-NII APIs retain unprivileged NetworkManager cache reads.
They bind an existing unique owner without activation, validate mandatory BSS
identity/frequency/LastScan, bracket scan/device inventory, and deduplicate BSSID/
frequency observations. An empty never-scanned cache is unavailable; a known
scanned-empty cache can yield0. Quality percentages remain percentages. The
region bins describe frequency groups, not local regulatory authorization.
Only BSSID/frequency/quality metadata is retained from the property replies;
SSID values are not returned by these count providers. Kernel
wireless/driver metadata and generic up-interface queries do not depend on this
cache or NetworkManager. Byte-throughput sampling remains the separate0.19 path.

References: [nl80211 BSS signal units](https://github.com/torvalds/linux/blob/v7.0/include/uapi/linux/nl80211.h),
[Linux channel mapping](https://github.com/torvalds/linux/blob/v7.0/net/wireless/util.c),
[NetworkManager wireless cache](https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.Device.Wireless.html),
[NetworkManager BSS metadata](https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.AccessPoint.html).


## Recorded firmware runtime (0.26)

The older compatible lifetime block3 definition begins with eight little-endian
U16 time counters. The first is recorded firmware runtime, with stored resolution
2h. The qualified OEM reply is26bytes, longer than that reference. Only offset0
is decoded as runtime in this release; other region meanings and extra bytes are
not assigned. Physical IC vendor is not identified by the compatible layout.

The existing five-hour read-only target capture observed word0 values13976→13977
at09:59..10:01UTC and13977→13978 at12:01..12:03UTC. Monotonic edge brackets give
7199.9999..7440.0001s between increments. This supports the two-hour stored scale;
no interpolation, accurate wall-clock oscillator, host uptime or battery-age
claim follows. All captured first8-word records satisfied total-minus-other-seven
between0 and7, consistent with independently quantized region totals. The other
region counters and their configured thresholds remain uninterpreted.

`recorded_firmware_runtime` requires the existing exact target identity/firmware,
complete raw block3 and consistent time prefix. Short frames, maximum-value
counters or broken prefix relationships withhold the derived time while keeping
other good history. Reset/saturation/wrap behavior has not been experimentally
qualified. The old4-byte `runtime_counter_raw` and its `runtime_unit_verified:false`
are retained as opaque compatibility metadata; they must not be multiplied by2.
Use the new nested U16 field. Raw26-byte original API data is unchanged; the
original block3 JSON API adds the typed runtime metadata. Vitals adds one recorded
firmware-runtime string with its2h step size. No new register query or write is used.

Reference: [Compatible block3 layout and time units, sections12.1.47 and13.9.9](https://www.ti.com/lit/ug/sluua43a/sluua43a.pdf).


## Region and balancing histories (0.27)

The complete qualified first16-byte block3 prefix now exposes seven U16 durations
with reference region codes UT/LT/STL/RT/STH/HT/OT. The existing runtime/full-frame/
first8-word consistency gate is reused. Units are2h steps; independently quantized
region totals can fall below recorded runtime. Actual configured thresholds are
not available, so no Celsius ranges, present region or physical thermistor location
is assigned. Block3 bytes16..25 remain raw. Original block3 JSON adds the typed
region durations without changing the complete raw payload or legacy field.

Complete8-byte block2 matches the compatible four reset counters followed by four
U8 balancing-time counters. The target has two applicable cells; only offsets4/5
are exposed, and the two inactive bytes must be zero for this interpretation.
Units come from the compatible reference (2h). The target currently reports255/255; ambiguous maximum values remain unavailable
as converted time. Meaningful nonzero accumulation is not physically qualified. Synthetic
positive values check decoding, not hardware accuracy. Maximum-valued cells are
withheld individually while other good cell history remains available. A zero
recorded counter is quantized and does not state current balancing activity.
No balance activation, reset, unseal, dataflash or gauge configuration is used.

Both groups are in native history/metrics. Vitals adds seven code-labelled region
rows and two balancing rows with step size. The actual thresholds, inactive storage,
extra OEM fields and physical IC vendor remain unqualified.

Reference: [Compatible lifetime layout/units, sections12.1.46-47 and13.9.8-9](https://www.ti.com/lit/ug/sluua43a/sluua43a.pdf).


## GPU utilization and tablet state (0.28)

GPU utilization uses validated kernel DRM percentages when advertised, or the
existing i915 PMU busy events with explicitly advertised ns units. Each fixed
perf read is exactly24bytes: value/time_enabled/time_running. Percentages use
counter deltas over the matching running interval. Multiplexed intervals are
withheld rather than extrapolated; counter resets/wrap, no running time, busy
above running time, delayed reads, suspend gaps and changed provider inventories
remain unavailable. Each engine has its own measured duration and availability;
there is no summed device percentage. All descriptors close, including initial
packet failures. This does not bypass perf access restrictions or add a monitor
service, GPU load generator or hardware setting.

Tablet detection starts with sysfs EV_SW capability bit1, opens only advertised
tablet-switch evdev devices read-only, verifies the character device major/minor,
then uses EVIOCGBIT(EV_SW,8) and EVIOCGSW(8). No event stream is read. A valid
positive switch proves tablet mode; a negative result requires the entire
advertised census to be readable and unchanged. A missing, inaccessible or
changing provider cannot be reported as off. Physical fold transitions remain
unperformed; capability/state reads qualify only the current observation.

References: [perf counter read formats/timing](https://man7.org/linux/man-pages/man2/perf_event_open.2.html),
[Linux state/capability ioctls](https://docs.kernel.org/input/event-codes.html),
[i915 PMU implementation](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/i915/i915_pmu.c).


## Fixed SBS operation diagnostics (0.29)

`battery_sbs_diagnostics` is read-only cached module metadata. It does not refresh
SBS or touch controller registers. Attempt/success/failure counters cover the
loaded module instance; each completed actual collection records its result,
phase, optional command/completion/bus status, sentinel pass and mode-bracket
flag. Raw0 is distinguished from an unobserved null status. Operation error and
restoration error are separate, with restoration failure still returningEUCLEAN
and latching controller access off. The last failed attempt survives subsequent
success, so a recovered sample cannot erase the failure evidence. Ages use kernel
boottime and include suspend. Failed prerequisites/manual/cache hits do not count
as a new wire collection.

Tracing adds no I/O, command, retry, status poll, data/configuration write or
sleep; the untraced wrapper and all fixed request/restoration restrictions remain.
All371 ordinary and382 sentinel-retry injected failures are compared across traced
and untraced helpers for identical return, I/O count, output and restored memory.
The native metrics report also includes validated `smart_battery_diagnostics`.
These fields locate the intermittent EIO before any protocol timing is changed;
they do not qualify a fix or an undocumented firmware response.


## Bounded SBS completion retry (0.30)

Actual failure traces on the qualified target identify the first fixed SBS
command0x1a with completion0x40 and successful restoration. The firmware writes
0x40 after its combined transfer returns unsuccessful; it is not pending work.
Separate isolated reads subsequently succeed with completion0x80, so support
for the fixed query is established independently of the failed reply.

A refresh can make at most two complete collection attempts. Only a traced
word-completion EIO with observed0x40, a qualified fixed command and zero
restoration error permits the second attempt. All49 bytes have already restored
and passed readback. ECMT is released for100ms, then reacquired; the full identity,
mode/specification, complete-reply/sentinel and restoration gates run again.
No partial frame or prior cached measurement substitutes for a fresh valid result.
Unexpected status, absent/unqualified identity, transport errors, short frames,
mode changes and restoration errors do not use this retry path. EUCLEAN still
latches controller readers off. If the second attempt fails, the value remains
unavailable; this is bounded recovery, not a promise of infallible firmware.

Cached diagnostics count both attempts, retain the original failed trace and add
retry/recovered-refresh counters with the explicit1/100ms policy. The physical
firmware/bus failure cause remains unproven. No new command, controller setting,
configuration write, reset or unseal is introduced.


## Firmware software-status observation (0.31)

The qualified target combined-transfer path stores software copies at0x9602
(status copy),0x9603(return value),0x961f(channel index) and0x9620(acquisition return).
Only after a fixed word reports the qualified completed0x40 failure, the module
can read those four SRAM addresses via fixed read92 twice before mandatory IPC
restoration and before releasing ECMT. All49 bytes still restore/read back even
if the observation fails. No controller status/FIFO register,
read-to-clear location, BMS command, reset or write is added. The observer accepts
only equal passes, failed return0, channel1 and acquisition0/1; other/error cases
publish a failed observation with null raw bytes. Observer errors do not turn the
failed collection into data or change the established one-retry policy.

The nested `software_observation` in cached SBS diagnostics contains result,
optional four-byte raw_hex and explicit atomic/current_operation_proven=false.
The firmware can reuse software scratch, including before these reads. Matching
context and equal passes reduce torn copies but do not prove current provenance,
an exact hardware fault, bus availability or a new measurement. These bytes are
never used for acceptance, retry selection or control. A software observation may
fail while the original collection's verified restoration remains successful.
Cached diagnostic reads remain free of controller access; a failed collection now
adds at most eight fixed software-memory reads. Successful collections add none.


## Native SMBus ReadWord (0.32)

The target table785E entry9 points through46EA toD8E3, then17AD with word protocol0C.
The routine sets read direction, sends the fixed SBS command and copies only the
received low/high data registers into9040/9041. Selector5 is a different routine
and was never requested. Native request uses channel selectors0=2/5=2, subindex6=9,
wire8=16h, command9 from the existing16-word allowlist and opcode4=10h. Both channel
mappings are checked. It returns control9004=0 and worker-result9007=1; unexpected
control/result is a protocol error, completed result0 is unavailable. No combined
I2C fallback or legacy0x40/software-copy interpretation is used.

The private probe read all16 words twice and specification/mode again (34 reads),
seeded/read all32 RX bytes for32 frames and proved untouched30-byte suffixes with
both5A/A5 sentinels. It restored/read back all49 bytes, returned the driver to auto,
and matched Linux capacities/cycles. The production collector seeds the entire RX
once; each word re-seeds its two data bytes and checks all30 suffix bytes before
another request. It never rewrites the suffix between words, so an overlong frame
cannot be concealed by a later seed/request. A final-byte sentinel collision retries
only that complete word with the alternate data sentinel, without combining frames.

Exact model/gauge/firmware, mode/specification brackets,30s cache, manual exclusion
and49-byte restoration/fault latch remain. At most one complete fresh collection
retry can follow a native completed result0 with successful restoration, with ECMT
released for100ms. Short frames, changed mode/specification, unexpected status,
transport/identity or restoration errors do not use this retry. Diagnostics tag the
transport and expose worker_result separately from legacy bus_status. Native frames
have no legacy software observation. Native/legacy payload units are unchanged;
parsers accept those known transport tags and reject unknown ones.


## Filesystem capacity providers (0.33)

`WMIGetHDDUsage` and `WMIGetSSDUsage` return per-mount filesystem capacity, not
physical-device I/O activity. Existing path/mount/total/used/free/percent fields
remain on readable rows with available=true and an explicit source. Values come
from one fstatvfs sample on a pinned O_PATH directory descriptor per mount.
User-available free space may exclude reserved blocks, so used+free may be less
than total. Total=blocks*frsize, used=(blocks-bfree)*frsize, free=bavail*frsize;
percent is rounded to one decimal from100*used/(used+free), retaining the former
psutil semantics (zero when the denominator is zero).
Invalid or failed samples keep path/mount/available=false/errno/error with no
numeric substitution. A present disk with no mounted filesystem in this namespace
has mount=null and ENODATA; no selected disks still returns an empty list. Shared
block-tree child/path/mount pairs are sampled once. Results are sequential samples,
not an atomic cross-mount snapshot or a sum of physical disk usage. Only read-only
inventory and filesystem metadata are accessed; there is no SMART, mount or device
control request in this provider. Unknown arguments to these two reads are rejected.

Version0.69 matches the descriptor's fdinfo mount ID, fstat inode/dev_t and the
mountinfo record to the selected lsblk major:minor. O_PATH pins the original
directory while fstatvfs samples it. The original descriptor stays open through
final mount-record and reopened-path identity checks. Physical block sysfs
identity/diskseq and classification, plus the selected tree, bracket the reads.
Missing/replaced mappings cannot fall through to a parent filesystem. Successful
rows expose mount_id/filesystem_device/identity_verified. Individual read errors
preserve readable siblings; changed global selection/generation raises EAGAIN.
Unknown synthetic/multi-device dev_t mappings remain unavailable, with no backing
layout guessed. Unrelated nsfs opaque roots remain valid mountinfo metadata.
The cooperative sampling budget is8s, each lsblk call at most4s; individual kernel
metadata syscalls are not hard-cancellable. Bounds cover64 roots,1024 tree nodes,
256 distinct observations and4096 mount records. No filesystem-property column is
requested from lsblk. See the kernel's [mountinfo and fdinfo definitions](https://docs.kernel.org/filesystems/proc.html).


## Native input and display metadata (0.34)

GetNum_Key preserves nullable num_lock/keyboard_num and adds per-event/LED
availability and observation metadata. The count uses readable native64 KEY_A/KEY_Z
capabilities on event devices, not a count of unique physical keyboards. A failed
or changing input census withholds the exact count; observed devices remain
separate. Num Lock requires a nonempty complete, consistent binary LED census.
Missing, conflicting or failed LEDs yield null, not off or partial consensus.
Directory identity/census and capability/LED states are rechecked. This reads
static capabilities/LED state only, never key contents or an input-event stream;
it does not claim desktop-session key state.

Three original display queries use cached DRM state. Exact external count
requires valid states for all external DRM connectors; unknown status cannot
become disconnected. Property/LCD lists retain unknown connectors with explicit
availability/errors, alongside stable connected entries. Missing/empty DRM
providers error rather than create a zero monitor count. Internal classification
uses eDP/LVDS/DSI connector types. Identity, connection and census are rechecked.
Optional modes/EDID failures do not erase connection state. Monitor identity
comes only from a validated128-byte base EDID (exact header/checksum/version1,
valid manufacturer code; printable ASCII monitor-name descriptor when present).
Extensions are not decoded or claimed valid, and their contents do not invalidate
independently qualified base identity. No EDID serial is emitted. Availability of
connection, modes, base EDID and textual model is separate; a missing textual
model is not invented from a serial or generic label. These are sequential cached
metadata reads, not atomic physical cable detection or proof of a visible picture.
No DDC/I2C request, modeset, display configuration or input state write is used.
[Linux DRM base-EDID validation reference](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/drm_edid.c).


## Desktop-session Num Lock (0.35)

Bridge2 adds typed Boolean GetNumLock using the default Clutter seat keymap's
get_num_lock_state. Primary GetNum_Key.num_lock is this logical toggle, with
explicit availability; it is not a physical LED, key press or Xwayland substitute.
Separate num_lock_led_consensus/num_lock_led_available/num_lock_led_complete and
per-LED rows retain the hardware observations. num_lock_complete now describes
the primary session value. Native keyboard capability/count fields are retained.

Only an existing Unix session bus and existing fixed bridge name are queried.
The client pins the unique owner, requires its Unix UID to match the caller,
checks bridge version2 and the Boolean reply, then rechecks name ownership.
Missing/unsupported/failed/changed providers return null with errno, never false
or a fallback LED value. Calls have2s timeouts and no activation request. No input
event subscription/content, Num Lock toggle or other state write is performed.

The local bridge installer verifies known owned file hashes, keeps a private
backup and preserves enabled/disabled preferences. On GNOME50, a newly installed
local extension needs normal discovery at login; ReloadExtension is explicitly
unsupported by the50.1 D-Bus implementation. No unsafe evaluation or automated
logout is used. Isolated GJS/D-Bus synthetic true/false tests establish the wire
contract, not the owner's real session state or physical transition.
[Clutter keymap getter](https://mutter.gnome.org/clutter/method.Keymap.get_num_lock_state.html),
[seat keymap](https://mutter.gnome.org/clutter/method.Seat.get_keymap.html),
[GNOME50.1 D-Bus implementation](https://github.com/GNOME/gnome-shell/blob/50.1/js/ui/shellDBus.js).


## GNOME50 stage/context correction (0.36)

Bridge3 calls the getter with global.stage. The adapter resolves get_context(),
then Clutter.Context.get_backend(), Clutter.Backend.get_default_seat(),
Clutter.Seat.get_keymap() and Keymap.get_num_lock_state(). Installed Mutter18
introspection exposes each method; GNOME50.1 keyboardManager uses the equivalent
stage.context backend route. Shell's Meta.Backend lacks get_default_seat, so the
bridge2 caller was incorrect despite synthetic getter/transport tests passing.
Old bridge2 is rejected by the current client. Expanded adapter tests exercise
missing stage/context/backend and the actual method chain. This source/type proof
still does not replace owner-session activation/real-state qualification.
[GNOME50.1 keymap route](https://github.com/GNOME/gnome-shell/blob/50.1/js/misc/keyboardManager.js).


## USB data inventory and root-port groups (0.37)

Five USB queries use cached sysfs descriptor/address metadata with topology,
directory identity and mandatory-field rereads. Unreadable device/class metadata
is retained as an unavailable row; exact USBNum errors rather than silently
omitting it. Optional product/manufacturer/link-speed/removability/bcdDevice
failures retain presence with per-field errors/nulls. No serial is read. Link
speed is reported negotiation metadata, never measured throughput.

USBNum and USBPort retain their non-hub scope. Type-C and A/C connection queries
include enumerated hubs, so an empty connected hub is still a connection. Unknown
connector mappings cannot produce false or an exact zero count; a verified Type-C
positive can survive unrelated unknown rows. Exact A/C count is nullable with
observed_count and coverage metadata. Unknown arguments are rejected before reads.

Root ports behind hubs retain their host-connection scope. Valid reciprocal peer
links within one host controller identify the high/super-speed halves; registered
Type-C connector links merge aliases. Connected components form port groups.
Conflicting group classifications stay unknown; matching port numbers, names or
VID/PID never merge unrelated devices. No missing peer is invented. These are
sequential enumerated USB data connections grouped by available kernel evidence,
not all physical/power-only cable connections or a visible-picture assertion.
No USB authorization/configuration, power, bind/unbind, reset or controller
request is issued. [Kernel USB peer-port semantics](https://docs.kernel.org/7.0/driver-api/usb/power-management.html),
[USB sysfs ABI](https://github.com/torvalds/linux/blob/master/Documentation/ABI/testing/sysfs-bus-usb).

## EEPROM E5 buffer (0.45)

Actual ATKACPI IOCTL22240c forwards the method ID via IoWMIExecuteMethod on the
ASUS management GUID. It zero-pads input to1024 bytes and maps a four-byteFE
reply to unsupported. The native root RPC13 accepts only selectorE5 with zero
value/flags, uses the same fixed60059/DEVS input, and requires a successful
probe-time version before invoking WMI. No general buffer/method access is added.

E5 framing consumes9+byte6 bytes after5a/a5 magic. Validate the actual reply
length (maximum1024, frame maximum264); the original temporary256-byte copy is
not reproduced. Remaining header/payload/checksum meanings are opaque. The native
collector follows the original two-consecutive-unusable-reply termination rule,
with a separate explicit64-frame bound and partial/error metadata. A raw register
wordFFFFFFFF is not a generic unavailable sentinel; date/count/version selectors
have their own checks. Existing failure statuses remain failures, never raw data.
The current .301 version result is unsupported: no E5 WMI call is made here.


Wireless 0.53 uses existing System D-Bus unique owners and current mac80211
peer capability files. It never issues a radio scan or setting operation.
Only selected HT/VHT/HE capability/operation and rate elements are decoded; SSID,
vendor/WPS payloads and credentials are not exported. TLV sizes, duplicate
capabilities, per-bandwidth MCS maps, PPE lengths and operation widths are
validated. Standard rate arithmetic replaces anomalous original table entries;
three-decimal Mbit/s values and HE GI assumptions are explicit. Current Tx/Rx
rate encoding remains separately labelled observed metadata. EHT/unknown legacy
association modes are not inferred from unrelated measurements.

The public wireless cache pins boot, monotonic age, ifindex/sysfs PHY identity,
NetworkManager owner, active-connection generation and associated AP identity.
Fresh readers recheck that context. Collector owner/BSS inventories and current
association are bracketed; failed histogram reads preserve independently valid
capabilities. BSS fingerprints deduplicate observations; newest known age wins.
Returned observation ages include public-cache age. Histograms retain missing
dBm and out-of-range counts. Native bins fix original decade-boundary omissions.
The separate service has no capabilities, denies IP and has only the parsed
metrics directory writable. Existing isolated NVMe service is preserved.


Diagnostic logging0.54.1 reconstructs the original fixed descriptor data and
special-handler dispatch without executing vendor code. Forty protocol15 scalar
recipes, four chip-name bytes,32 project-revision bytes and11 manufacturer bytes
are bounded and version/model guarded. String bytes are checked twice. Word
reads retain the high/low/high rollover guard. Fixed source routes add no
arbitrary EC/SMBus selector interface and no factory mutation.

The board group reads its count and saved selector, selects verified1..5 values
and restores that exact selector even after an intermediate failure. Restoration
has bounded retries and independent readback; failed restoration withholds the
sample. Count changes and per-string changes remain EAGAIN. Only an owned late
reply may be consumed during restoration. GPIO and consumer rows require newer
protocols; no requests for them are issued here. Kernel raw diagnostics are
sequential, uncached snapshots with boot-time start/duration metadata.

A separate fan-only reader changes no selector or policy. DD2/35 returns twice
the seven-bit firmware duty code. Odd/off-scale codes, changed mode/raw selector and
unqualified fan counts are rejected. Fan reads do not depend on a complete EC
or gauge transaction. The explicit logger reuses existing bounded EEPROM source
semantics; ordinary metrics and fan monitoring never advance EEPROM events.

The target DD2/35 handler tests9130 bit7, controlled by the DD2/31 manual gate.
No automatic-mode duty request is sent. This is a firmware availability limit,
not a zero code or a reason to discard the other diagnostic fields. The raw
selector is pinned/rechecked independently of the logical single-channel index.


## Immediate USB attachment and descriptor quantities (0.70)

Original96030 uses the selected device instance's immediate parent hub and
IOCTL_USB_GET_PORT_CONNECTOR_PROPERTIES0x220458, returning bit3+1 as its
Type-C/non-Type-C class. Shared9e730 uses bit0 user-connectable and bit3 for
the separate C/non-C counters. Its five version/port strings select the Windows
USB Mass Storage Device friendly-name/descriptor path and bcdUSB0200/0210/0300/
0310/0320; descriptor firmware bcdDevice and link rate are different quantities.

Native default classification/counts now follow the immediate kernel device/port
link and validate parent hub, interface class09, port name and ancestry. Root host
observation remains explicitly selectable. Downstream unknown socket type never
inherits the laptop root's type. Kernel connect_type supplies user visibility;
_UPC connectivity alone is not that flag. The A-named result is labelled
user-connectable non-Type-C, without relabelling known B/proprietary shapes as A.
Reciprocal same-controller peers and registered Type-C links merge physical halves;
identity/link/classification/census checks retain unknowns and partial lower bounds.

Cached sysfs version renders descriptor bcdUSB as hexadecimal major.minor; native
preserves those exact16 bits, separate from bcdDevice and negotiated speed. Cached
configuration/interface-class census and identities bracket classification; device
class08 or active interface class08 selects the native mass-storage subset.
Detailed USBNum includes raw-version bins, other/unknown versions and separate
subset completeness; default scalar count and richer USBPort inventory remain.
Windows strings/friendly-name filtering are not imitated. Read failures never
become a false zero storage count, and optional failures do not erase presence.
No USB descriptor/control transaction, scan, power, bind or authorization write.
Kernel references: [USB sysfs ABI](https://github.com/torvalds/linux/blob/v7.0/Documentation/ABI/testing/sysfs-bus-usb),
[bcdUSB renderer](https://github.com/torvalds/linux/blob/v7.0/drivers/usb/core/sysfs.c)
and [port metadata/peers](https://github.com/torvalds/linux/blob/v7.0/drivers/usb/core/port.c).


Original20e60/Adapter_Read_PD_ADO uses the same >=14 version and status gates
as the other bank6 scalar diagnostics, then reads exactly DD6/26. Full native
ADO32 from fixed TCPC received register74 is a distinct quantity; its existence
does not establish that cache byte's meaning. Version0.70 default therefore
reports qualified bank absence (EOPNOTSUPP) and preserves ADO32 under explicit
native_alert=true and existing labelled reports. Unknown provider/support metadata
remains an error. No extra controller or unimplemented bank access is introduced.
USB connection count is per logical device connection as in the original loop;
separate socket_count merges advertised peer/Type-C halves, retaining both useful
quantities without losing the source count.


## GPU provider coexistence and unfiltered monitor names (0.71)

Original c8160 forwards to the shared c01c0 WMI query of GPUPerformanceCounters/
GPUEngine Name/UtilizationPercentage, converts 3D-labelled entries and selects their
maximum. Linux has no per-process3D counter set; native DRM device busy percent and
i915 per-engine busy nanoseconds remain declared counterparts. The former native
report returned as soon as any DRM busy row existed, so a failed DRM read hid
working i915 PMU data. Both bounded (<=64) provider censuses are now read; each
row is labelled, discovery and decode failures stay per provider (decode as
EPROTO), and identities/census are rechecked before publication. A changed identity
fails only previously available rows. Provider coverage and per-row availability
are reported separately. No provider is summed, substituted, clamped, extrapolated
or calibrated against another; no load is generated and no setting is written.

Original cb3e0 uses the shared bd270 query of WMIMonitorID UserFriendlyName with no
internal-panel filter. The native list had kept only eDP/LVDS/DSI connectors. Its
default now retains connected/unknown internal and external DRM rows with the same
base-EDID, identity, census and availability rules; strict boolean internal_only
preserves the panel-only view. No DDC/I2C request, modeset or EDID serial is used.

The remaining23 export wrappers (battery identity/lifetime blocks, storage and
monitor WMI queries, hardware configuration, Num Lock, p_sensor mask, frontend
version and connected network type) were reviewed against their native providers
without behaviour change. All252 exports now carry explicit scoped source-review
bindings. This is review coverage only; the original PE was not executed, and
functional parity and hardware qualification remain separately recorded.


## Gauge history decodes from TI references (0.75)

Public research (TI bq40z50 R1/R2/R3/R4/R5, BQ4050, BQ40Z80 manuals, TI E2E,
open decoders, repair fora) supports three decodes without new hardware access:

- Block2 balancing counters: U8 in2 h steps "up to a limit of510 hours"
  ([SLUUBK0B](https://www.ti.com/lit/pdf/sluubk0)), so 255 is reported as
  saturated, at least510 h, not unavailable.
- DAStatus2 bytes14..15 are gauging temperature (0.1 K) and bytes16..23 are
  uncompensated cell voltages1..4. R4/R5 list a26-byte field set for a declared
  24-byte block; the live target selects the variant without UserTemperature:
  bytes16..19 track compensated DA1 cells1..2 and bytes20..23 are zero on the
  two-cell pack. The decode is gated on exactly that check.
- Temperature regions use TI T1..T6 boundaries. Defaults (T1 0, T2 12, T5 20,
  T6 25, T3 30, T4 55 °C, 1 °C hysteresis) are published as reference metadata
  with `read_from_pack: false`; the OEM may have changed them and sealed data
  flash is not read.

Not decodable from public sources: lifetime block3 bytes16..25 (no TI variant has
a26-byte block3), the battery-information and PF cache layouts, ASUS DD bank6,
adapter-rating semantics. DeviceType0x4556 follows TI's device-number convention
for a "bq40z556" custom part (one repair-forum report on an ASUS pack); this is
inference and does not change any decode. For the PD controller, TI's TPS65987
host-interface manual documents read-only RX SCEDB (0x76) and RX SDB (0x78), but
the TPS65994 map is not published and the original ASUS APIs use the unsupported
DD bank6 path on this firmware, so no direct controller register is added.


## Received-PD extended registers, read-only (0.77)

Root-only `pd_extended` reads TPS65994 registers 0x41, 0x42, 0x76 and 0x78 for
each port with an active contract, using the qualified pointer-and-read
operation, ECMT/driver locks, contract bracketing and the 34-byte mailbox
restoration and fault latch. Registers 0x08/0x09 (command/data) are refused;
no 4CC command or controller write exists. The controller's own length byte is
reported raw.

Live on the qualified charger contract (connector 2, three identical reads):
0x41 length8 `0000005000000000`, 0x42 length3 `1a0d00`, 0x76 length0, 0x78
length4 `0f000000`; the inactive connector is not read. TI's sibling TPS65987
manual documents these as 4/4/24/7-byte registers and states that unallocated
registers return length0. Conclusions: received Source_Capabilities_Extended
(0x76) is not implemented by this controller firmware, so the original
Source_Cap_Extend VID/PID/XID/FW/HW APIs have no native provider here. The
other three registers exist with different lengths than the sibling layout, so
their bit meanings are not assigned; under the sibling layout 0x41 bit1
(extended capabilities received) is clear, consistent with 0x76 absence but not
proof. No mapping of 0x78 to the original Get_Status APIs is claimed.
