import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import Meta from 'gi://Meta';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import {getNumLock} from './num-lock.mjs';
import {getWindows, parsePreferences, splitNul, authorizeCaller, requestPolicy,
    processStartTime, PREFERENCES_FILE} from './windows.mjs';

const NAME = 'org.zenbook.HardwareBridge';
const XML = `<node><interface name="org.zenbook.HardwareBridge">
<method name="GetWindows"><arg name="include_titles" type="b" direction="in"/>
<arg name="windows_json" type="s" direction="out"/></method>
<method name="GetVersion"><arg name="version" type="s" direction="out"/></method>
<method name="GetNumLock"><arg name="num_lock" type="b" direction="out"/></method>
</interface></node>`;
const decoder = new TextDecoder();

function readText(path, limit = 65536) {
    try {
        const [ok, bytes] = GLib.file_get_contents(path);
        return ok && bytes.length <= limit ? decoder.decode(bytes) : null;
    } catch (_error) { return null; }
}

// Preferences are read per request: a private, regular, user-owned file only.
function preferences() {
    const path = GLib.build_filenamev([GLib.get_user_config_dir(), PREFERENCES_FILE]);
    try {
        const file = Gio.File.new_for_path(path);
        const info = file.query_info('standard::type,unix::uid,unix::mode',
            Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null);
        if (info.get_file_type() !== Gio.FileType.REGULAR ||
            info.get_attribute_uint32('unix::uid') !== new Gio.Credentials().get_unix_user() ||
            (info.get_attribute_uint32('unix::mode') & 0o022)) return parsePreferences(null);
        return parsePreferences(readText(path, 8192));
    } catch (_error) { return parsePreferences(null); }
}

export default class HardwareBridge extends Extension {
    enable() {
        this._owned = false;
        const call = (method, params, invocation, answer) => this._authorize(invocation, params, method, answer);
        this._object = Gio.DBusExportedObject.wrapJSObject(XML, {
            GetVersion: () => '4',
            GetNumLockAsync: (params, invocation) => call('GetNumLock', params, invocation,
                () => new GLib.Variant('(b)', [getNumLock(global.stage)])),
            GetWindowsAsync: (params, invocation) => call('GetWindows', params, invocation,
                () => new GLib.Variant('(s)', [getWindows(global.display,
                    Shell.WindowTracker.get_default(), params[0], Meta.TabList.NORMAL_ALL)])),
        });
        this._object.export(Gio.DBus.session, '/org/zenbook/HardwareBridge');
        // DO_NOT_QUEUE without ALLOW_REPLACEMENT: if another process holds the
        // name we never queue behind it, and nobody can take it from us.
        this._name = Gio.bus_own_name_on_connection(Gio.DBus.session, NAME,
            Gio.BusNameOwnerFlags.DO_NOT_QUEUE,
            () => { this._owned = true; },
            () => {
                if (this._owned || this._name) console.warn(`${NAME}: name not owned by the Shell bridge; refusing requests`);
                this._owned = false;
            });
    }

    _authorize(invocation, params, method, answer) {
        const sender = invocation.get_sender();
        const decide = authorized => {
            const prefs = preferences();
            const refusal = requestPolicy({method, includeTitles: params[0], owned: this._owned,
                authorized, exposeTitles: prefs.exposeWindowTitles});
            if (refusal) return invocation.return_dbus_error(refusal[0], refusal[1]);
            try { invocation.return_value(answer()); } catch (error) {
                invocation.return_dbus_error('org.freedesktop.DBus.Error.Failed', String(error?.message ?? error));
            }
        };
        if (!this._owned || typeof sender !== 'string') return decide(false);
        Gio.DBus.session.call('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
            'GetConnectionCredentials', new GLib.Variant('(s)', [sender]), new GLib.VariantType('(a{sv})'),
            Gio.DBusCallFlags.NONE, 2000, null, (connection, result) => {
                let authorized = false;
                try {
                    const credentials = connection.call_finish(result).recursiveUnpack()[0];
                    const pid = credentials.ProcessID;
                    if (Number.isInteger(pid) && pid > 0) {
                        const base = `/proc/${pid}`;
                        const startBefore = processStartTime(readText(`${base}/stat`));
                        let exe = null;
                        try { exe = GLib.file_read_link(`${base}/exe`); } catch (_error) { exe = null; }
                        const caller = {uid: credentials.UnixUserID, sessionUid: new Gio.Credentials().get_unix_user(),
                            exe, cmdline: splitNul(readText(`${base}/cmdline`)),
                            environ: splitNul(readText(`${base}/environ`, 1048576)), startBefore,
                            startAfter: processStartTime(readText(`${base}/stat`))};
                        authorized = authorizeCaller(caller, preferences().trustedScripts).ok;
                    }
                } catch (_error) { authorized = false; }
                decide(authorized);
            });
    }

    disable() {
        if (this._name) Gio.bus_unown_name(this._name);
        this._name = null;
        this._owned = false;
        this._object?.unexport();
        this._object = null;
    }
}
