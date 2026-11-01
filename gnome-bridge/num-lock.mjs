export function getNumLock(stage) {
    if (typeof stage?.get_context !== 'function')
        throw new Error('No desktop stage context');
    const context = stage.get_context();
    if (typeof context?.get_backend !== 'function')
        throw new Error('No desktop Clutter context backend');
    const backend = context.get_backend();
    if (typeof backend?.get_default_seat !== 'function')
        throw new Error('No default desktop seat');
    const seat = backend.get_default_seat();
    if (typeof seat?.get_keymap !== 'function')
        throw new Error('No desktop seat keymap');
    const keymap = seat.get_keymap();
    if (typeof keymap?.get_num_lock_state !== 'function')
        throw new Error('No desktop Num Lock state provider');
    const value = keymap.get_num_lock_state();
    if (typeof value !== 'boolean')
        throw new Error('Invalid desktop Num Lock state');
    return value;
}
