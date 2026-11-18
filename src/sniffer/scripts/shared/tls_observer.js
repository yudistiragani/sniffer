// Diagnostic only: observe native TLS calls, never replace arguments/return values.
// No Java bridge, certificate changes, request bodies, headers, tokens, or payloads.
"use strict";

const limit = 200;
let emitted = 0;
const observedModules = new Set();
const attachedAddresses = new Set();
const listenersByModule = new Map();
const machines = {ia32: 3, x64: 62, arm: 40, arm64: 183};

function emit(event, fields) {
    if (emitted >= limit) return;
    emitted++;
    send(Object.assign({event: event}, fields || {}));
    if (emitted === limit) send({event: "tls.limit", maxEvents: limit});
}

function install(module) {
    if (!/^(libssl|libcrypto|libjavacrypto|libconscrypt[^/]*|libcronet[^/]*|libliger)\.so$/i.test(module.name))
        return;
    const key = module.path + "@" + module.base;
    if (observedModules.has(key)) return;
    observedModules.add(key);
    const listeners = [];
    listenersByModule.set(key, listeners);

    // Do not Interceptor.attach ARM code translated by Houdini in an ia32 process.
    // Read only an ELF header, not arbitrary instructions or application data.
    let machine;
    try {
        if (module.base.readU32() !== 0x464c457f)
            throw new Error("Not an ELF header");
        machine = module.base.add(18).readU16();
    } catch (_) {
        emit("tls.module_unreadable", {module: module.name});
        return;
    }
    emit("tls.module", {module: module.name, path: module.path, machine: machine});
    if (machines[Process.arch] !== machine) {
        emit("tls.skipped_machine", {module: module.name, machine: machine});
        return;
    }

    let hooks = 0;
    for (const name of [
        "SSL_do_handshake", "SSL_get_verify_result", "X509_verify_cert",
        "SSL_set_custom_verify", "SSL_CTX_set_custom_verify", "SSL_CTX_set_verify"
    ]) {
        try {
            // Frida 17: export lookup belongs to the module instance.
            const address = module.findExportByName(name);
            if (address === null || attachedAddresses.has(address.toString())) continue;
            // Do not follow a forwarded export into another module/ABI.
            if (address.compare(module.base) < 0 ||
                address.compare(module.base.add(module.size)) >= 0) {
                emit("tls.export_outside_module", {module: module.name, function: name});
                continue;
            }
            const callbacks = name.includes("set_") ? {
                onEnter(args) {
                    emit("tls.call", {
                        module: module.name, function: name,
                        mode: args[1].toInt32(), hasCallback: !args[2].isNull()
                    });
                }
            } : {
                onLeave(retval) {
                    // A negative handshake result can be nonblocking WANT_READ;
                    // this is metadata, NOT a diagnosis of pinning/failure.
                    emit("tls.call", {
                        module: module.name, function: name, result: retval.toInt32()
                    });
                }
            };
            const listener = Interceptor.attach(address, callbacks);
            attachedAddresses.add(address.toString());
            listeners.push({address: address.toString(), listener: listener});
            hooks++;
            emit("tls.hook_ready", {module: module.name, function: name});
        } catch (_) {
            emit("tls.hook_error", {module: module.name, function: name});
        }
    }
    emit("tls.module_ready", {module: module.name, newHooks: hooks});
}

emit("tls.runtime", {
    pid: Process.id, arch: Process.arch, pointerSize: Process.pointerSize,
    maxEvents: limit, mode: "observe_only",
    javaBridgeAvailable: typeof Java !== "undefined"
});
// Observer covers both already-loaded libraries and later dlopen() calls.
// Unloading this script removes its Frida-owned interception listeners.
const observer = Process.attachModuleObserver({
    onAdded(module) { install(module); },
    onRemoved(module) {
        const key = module.path + "@" + module.base;
        for (const item of listenersByModule.get(key) || []) {
            try { item.listener.detach(); } catch (_) {}
            attachedAddresses.delete(item.address);
        }
        listenersByModule.delete(key);
        observedModules.delete(key);
    }
});
