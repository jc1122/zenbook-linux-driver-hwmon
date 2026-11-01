// Native Alt-Tab membership, then explicit compositor stacking. No title read
// occurs unless the caller requests it; process CPU/RSS enrichment is external.
export function getWindows(display, tracker, includeTitles, tabListKind) {
    if (typeof includeTitles !== 'boolean') throw new Error('Expected title flag');
    const members = display.get_tab_list(tabListKind, null);
    const ordered = display.sort_windows_by_stacking(members).slice().reverse();
    const focus = display.focus_window;
    const rows = [];
    let failures = 0;
    for (const window of ordered) {
        try {
            const app = tracker.get_window_app(window);
            const pid = window.get_pid();
            const row = {
                id: window.get_stable_sequence(), pid: Number.isInteger(pid) && pid > 0 ? pid : 0,
                app_id: app?.get_id() ?? null,
                application: app?.get_name() ?? window.get_wm_class(),
                focused: window === focus,
                minimized: window.minimized,
                z_order: rows.length,
            };
            if (includeTitles) row.title = window.get_title();
            rows.push(row);
        } catch (_error) { failures++; }
    }
    return JSON.stringify({schema: 1, windows: rows, source: 'GNOME Shell',
        titles_included: includeTitles, complete: failures === 0 && focus === display.focus_window,
        enumeration_errors: failures,
        coverage: 'Normal Alt-Tab windows across workspaces; topmost first, zero-based compositor stack order'});
}

// ---- Caller policy (M3) ---------------------------------------------------
// Window titles are exposed only when the desktop user opts in through
// $XDG_CONFIG_HOME/zenbook-hardware/bridge.json {"expose_window_titles": true}.
// Membership/stack/focus rows without titles remain available to authorized
// callers. Callers are authorized only when the bus daemon reports the session
// UID and the process is the installed runtime's Python CLI/C-ABI bridge (or a
// script the user lists in "trusted_scripts"). This narrows the audience; it
// is not a boundary against code already running as the same user.
export const PREFERENCES_FILE = 'zenbook-hardware/bridge.json';
export const ERROR_PREFIX = 'org.zenbook.HardwareBridge.Error.';
const RUNTIME_SCRIPT = /^\/usr(?:\/local)?\/lib\/asus-healthytable\/[0-9]+\.[0-9]+\.[0-9]+\/(?:zenbook-hardware|api_bridge)\.py$/;
const PYTHON_EXE = /^\/usr\/bin\/python3(?:\.[0-9]+)?$/;
const PYTHON_ARGV0 = /^(?:\/usr\/bin\/)?python3(?:\.[0-9]+)?$/;
const PYTHON_FLAGS = /^-[IBEsPOuq]+$/;
const ALWAYS_REFUSED_ENV = ['LD_PRELOAD', 'LD_LIBRARY_PATH', 'LD_AUDIT', 'PYTHONEXECUTABLE'];
const PYTHON_ENV = ['PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONUSERBASE', 'PYTHONINSPECT', 'PYTHONPLATLIBDIR'];
const SCRIPT_PATH = /^\/(?:[A-Za-z0-9._+-]+\/)*[A-Za-z0-9._+-]+\.py$/;

export function parsePreferences(text) {
    const result = {exposeWindowTitles: false, trustedScripts: []};
    if (text === null || text === undefined) return result;
    if (typeof text !== 'string' || text.length > 8192) throw new Error('Invalid bridge preferences');
    const data = JSON.parse(text);
    if (data === null || typeof data !== 'object' || Array.isArray(data)) throw new Error('Invalid bridge preferences');
    if ('expose_window_titles' in data) {
        if (typeof data.expose_window_titles !== 'boolean') throw new Error('Invalid title preference');
        result.exposeWindowTitles = data.expose_window_titles;
    }
    if ('trusted_scripts' in data) {
        const list = data.trusted_scripts;
        if (!Array.isArray(list) || list.length > 16 || list.some(p => typeof p !== 'string' ||
            p.length > 4096 || !SCRIPT_PATH.test(p) || p.split('/').includes('..')))
            throw new Error('Invalid trusted script list');
        result.trustedScripts = list.slice();
    }
    return result;
}

export function splitNul(text) {
    if (typeof text !== 'string') return [];
    const parts = text.split('\0');
    if (parts.length && parts[parts.length - 1] === '') parts.pop();
    return parts;
}

// caller: {uid, sessionUid, exe, cmdline: [argv...], environ: ['K=V'...],
// startBefore, startAfter}. Returns {ok, reason}.
export function authorizeCaller(caller, trustedScripts = []) {
    const refuse = reason => ({ok: false, reason});
    if (!caller || typeof caller !== 'object') return refuse('no caller credentials');
    if (!Number.isInteger(caller.uid) || caller.uid !== caller.sessionUid) return refuse('caller is not the session user');
    if (caller.startBefore === undefined || caller.startBefore === null || caller.startBefore !== caller.startAfter)
        return refuse('caller process changed during the check');
    if (typeof caller.exe !== 'string' || !PYTHON_EXE.test(caller.exe)) return refuse('caller executable is not the system Python');
    const argv = Array.isArray(caller.cmdline) ? caller.cmdline : [];
    if (argv.length < 2 || !PYTHON_ARGV0.test(argv[0])) return refuse('caller is not a Python script invocation');
    let index = 1;
    const flags = [];
    while (index < argv.length && PYTHON_FLAGS.test(argv[index])) flags.push(argv[index++]);
    const script = argv[index];
    if (typeof script !== 'string' || !(RUNTIME_SCRIPT.test(script) || trustedScripts.includes(script)))
        return refuse('caller script is not the installed zenbook-hardware runtime');
    const isolated = flags.some(flag => flag.includes('I') || flag.includes('E'));
    const names = (Array.isArray(caller.environ) ? caller.environ : []).map(entry => String(entry).split('=', 1)[0]);
    if (names.some(name => ALWAYS_REFUSED_ENV.includes(name)) || (!isolated && names.some(name => PYTHON_ENV.includes(name))))
        return refuse('caller environment can redirect the runtime');
    return {ok: true, reason: 'installed runtime'};
}

// Decide one request. Returns null to answer, or [error name, message].
export function requestPolicy({method, includeTitles, owned, authorized, exposeTitles}) {
    if (method === 'GetVersion') return null;
    if (!owned) return [`${ERROR_PREFIX}NotOwner`, 'This bridge instance does not own org.zenbook.HardwareBridge.'];
    if (!authorized) return [`${ERROR_PREFIX}AccessDenied`, 'Caller is not an authorized zenbook-hardware client.'];
    if (method === 'GetWindows') {
        if (typeof includeTitles !== 'boolean') return ['org.freedesktop.DBus.Error.InvalidArgs', 'Expected title flag'];
        if (includeTitles && exposeTitles !== true)
            return [`${ERROR_PREFIX}TitlesDisabled`, 'Window titles are off; set expose_window_titles in ' + PREFERENCES_FILE + '.'];
    }
    return null;
}

// Field 22 (starttime) of /proc/PID/stat; comm may contain spaces/parentheses.
export function processStartTime(stat) {
    if (typeof stat !== 'string') return null;
    const end = stat.lastIndexOf(')');
    if (end < 0) return null;
    const value = stat.slice(end + 2).split(' ')[19];
    return /^[0-9]+$/.test(value ?? '') ? value : null;
}
