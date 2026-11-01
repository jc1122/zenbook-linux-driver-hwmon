# SPDX-License-Identifier: GPL-2.0-only
"""Identity-matched local Wi-Fi card descriptions, independent of link state."""
from pathlib import Path
import errno
import re
import stat
import wireless
import identity_inventory
from platform_metadata import text


def error(e):return {'errno':getattr(e,'errno',None) or errno.EPROTO,'error':str(e)}

def pci_identity(path):
    st=path.stat();values={}
    for key,digits in (('vendor',4),('device',4),('class',6)):
        value=text(path/key)
        if not re.fullmatch('0x[0-9a-fA-F]{'+str(digits)+'}',value):raise OSError(errno.EPROTO,'Invalid wireless PCI identity.')
        values[key]=value[2:].lower()
    return (st.st_dev,st.st_ino,values['vendor'],values['device'],values['class']),values


def cards(root=None):
    root=wireless.NET_ROOT if root is None else root;paths=wireless.interfaces(root)
    if not paths:raise OSError(errno.ENODEV,'No wireless interface is available.')
    try:names,name_errors=identity_inventory.pci_names();name_failure=None
    except OSError as e:names={};name_errors=0;name_failure=e
    rows=[]
    for p in paths:
        row={'interface':p.name,'driver':None,'name':None,'name_available':False}
        try:
            before=wireless.identity(p);device=(p/'device').resolve(strict=True);ds=device.stat()
            try:
                driver=p/'device/driver'
                if not stat.S_ISLNK(driver.lstat().st_mode):raise OSError(errno.ENODATA,'No wireless driver association.')
                row['driver']=driver.resolve(strict=True).name
            except OSError as e:row['driver_error']=error(e)
            try:
                if re.fullmatch(identity_inventory.BDF,device.name):
                    old,ids=pci_identity(device);record=names.get(device.name.lower())
                    row.update(bus='pci',vendor_id=ids['vendor'],device_id=ids['device'],class_id=ids['class'])
                    # Malformed/duplicate local PCI database rows were dropped; report how many.
                    if name_errors:row['name_parse_errors']=name_errors
                    if not record or (record['vendor_id'],record['device_id'],record['class_id'])!=(ids['vendor'],ids['device'],ids['class'][:4]):
                        if name_failure:raise name_failure
                        raise OSError(errno.ENODATA,'No identity-matched local PCI card caption.')
                    label=record['device_name'];vendor=record['vendor_name']
                    if not label or re.fullmatch(r'(?:Device )?'+re.escape(ids['device']),label,re.I):raise OSError(errno.ENODATA,'PCI database has no descriptive card name.')
                    row.update(name=(vendor+' '+label).strip(),name_available=True,name_source='Local PCI database matched by address/class/vendor/device')
                    if old!=pci_identity(device)[0]:raise OSError(errno.EAGAIN,'Wireless PCI identity changed.')
                else:
                    usb=device if (device/'idVendor').exists() else device.parent
                    if not (usb/'idVendor').exists():raise OSError(errno.EOPNOTSUPP,'No qualified descriptive card provider for this bus.')
                    us=usb.stat();vendor=text(usb/'idVendor');product=text(usb/'idProduct')
                    if not re.fullmatch('[0-9a-fA-F]{4}',vendor) or not re.fullmatch('[0-9a-fA-F]{4}',product):raise OSError(errno.EPROTO,'Invalid wireless USB identity.')
                    label=text(usb/'product')
                    if not label:raise OSError(errno.ENODATA,'USB device has no product description.')
                    try:maker=text(usb/'manufacturer')
                    except FileNotFoundError:maker=''
                    row.update(bus='usb',vendor_id=vendor.lower(),device_id=product.lower(),name=(maker+' '+label).strip(),name_available=True,name_source='Device-reported USB manufacturer/product descriptors')
                    if (us.st_dev,us.st_ino)!=(usb.stat().st_dev,usb.stat().st_ino) or (vendor,product)!=(text(usb/'idVendor'),text(usb/'idProduct')):raise OSError(errno.EAGAIN,'Wireless USB identity changed.')
            except OSError as e:row.update(name=None,name_available=False,name_error=error(e))
            if before!=wireless.identity(p) or (ds.st_dev,ds.st_ino)!=(device.stat().st_dev,device.stat().st_ino) or device!=(p/'device').resolve(strict=True):raise OSError(errno.EAGAIN,'Wireless card changed during enumeration.')
        except OSError as e:row.update(driver=None,name=None,name_available=False,**error(e))
        rows.append(row)
    if [p.name for p in paths]!=[p.name for p in wireless.interfaces(root)]:raise OSError(errno.EAGAIN,'Wireless card census changed.')
    return rows
