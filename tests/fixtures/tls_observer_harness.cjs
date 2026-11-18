// Offline GumJS surface simulation. No real process attachment or network calls.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const [scriptPath, scenario] = process.argv.slice(2);
const messages = [];
const hooks = [];
let observer;

class Pointer {
    constructor(value, machine = 3) { this.value = value; this.machine = machine; }
    toString() { return "0x" + this.value.toString(16); }
    toInt32() { return this.value | 0; }
    isNull() { return this.value === 0; }
    compare(other) { return this.value - other.value; }
    add(amount) { return new Pointer(this.value + amount, this.machine); }
    readU32() {
        if (scenario === "unreadable") throw new Error("unreadable");
        return 0x464c457f;
    }
    readU16() { return this.machine; }
    replace() { assert.fail("Observer must not replace native values"); }
}

const names = [
    "SSL_do_handshake", "SSL_get_verify_result", "X509_verify_cert",
    "SSL_set_custom_verify", "SSL_CTX_set_custom_verify", "SSL_CTX_set_verify"
];
const tlsModule = {
    name: "libssl.so",
    path: ["translated", "matching_arm"].includes(scenario) ? "/system/lib/arm/libssl.so" : "/system/lib/libssl.so",
    base: new Pointer(0x1000, ["translated", "matching_arm"].includes(scenario) ? 40 : 3),
    size: 0x1000,
    findExportByName(name) {
        if (scenario === "missing") return null;
        if (scenario === "forwarded") return new Pointer(0x9000);
        return names.includes(name) ? new Pointer(0x1100 + names.indexOf(name) * 16) : null;
    }
};
const context = {
    Process: {
        id: 123, arch: scenario === "matching_arm" ? "arm" : "ia32", pointerSize: 4,
        attachModuleObserver(callbacks) {
            observer = callbacks;
            callbacks.onAdded(tlsModule);
            return {};
        }
    },
    Interceptor: {
        attach(address, callbacks) {
            if (scenario === "hook_error") throw new Error("unsupported interceptor");
            const listener = {detached: false, detach() { this.detached = true; }};
            hooks.push({address, callbacks, listener});
            return listener;
        },
        replace() { assert.fail("Observer must not replace functions"); }
    },
    send(payload) { messages.push(payload); }
};

vm.runInNewContext(fs.readFileSync(scriptPath, "utf8"), context);
assert.equal(messages[0].event, "tls.runtime");
assert.equal(messages[0].mode, "observe_only");
assert.equal(messages[0].javaBridgeAvailable, false);

if (scenario === "translated" || scenario === "unreadable" || scenario === "missing" ||
    scenario === "forwarded" || scenario === "hook_error") {
    assert.equal(hooks.length, 0);
    const expected = {
        translated: "tls.skipped_machine", unreadable: "tls.module_unreadable",
        missing: "tls.module_ready", forwarded: "tls.export_outside_module",
        hook_error: "tls.hook_error"
    }[scenario];
    assert(messages.some(m => m.event === expected));
} else {
    assert.equal(hooks.length, names.length);
    if (scenario === "unload") {
        observer.onRemoved(tlsModule);
        assert(hooks.every(h => h.listener.detached));
        observer.onAdded(tlsModule);
        assert.equal(hooks.length, names.length * 2);
    } else {
        for (const hook of hooks) {
            if (hook.callbacks.onEnter) {
                const args = [new Pointer(10), new Pointer(1), new Pointer(0x4444)];
                hook.callbacks.onEnter(args);
                assert.deepEqual(args.map(p => p.value), [10, 1, 0x4444]);
            }
            if (hook.callbacks.onLeave) {
                const result = new Pointer(-1);
                hook.callbacks.onLeave(result);
                assert.equal(result.value, -1);
            }
        }
        assert(messages.some(m => m.event === "tls.call"));
        if (scenario === "limit") {
            for (let i = 0; i < 500; i++) hooks[0].callbacks.onLeave(new Pointer(1));
            assert.equal(messages.filter(m => m.event === "tls.limit").length, 1);
            assert.equal(messages.length, 201);
        }
    }
}
console.log(JSON.stringify({scenario, ok: true, events: messages.length}));
