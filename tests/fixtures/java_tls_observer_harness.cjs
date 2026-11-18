"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const [script, scenario] = process.argv.slice(2);
const events = [];
const receiver = {};
const secret = "PRIVATE_HOST_COOKIE_TOKEN_CERT";
const args = [secret, {certificate: secret}, null];
const result = {unchanged: true};
let failure = null;
let calls = 0;
let backtraces = 0;
const facebookClass =
    "com.facebook.mobilenetwork.internal.certificateverifier.CertificateVerifier";
const fbOverloads = Array.from({length: 4}, () => ({
    calls: 0,
    failure: null,
    expected: null,
    call(self, ...actual) {
        this.calls++;
        assert.equal(self, receiver);
        assert.deepEqual(actual, this.expected);
        if (this.failure) throw this.failure;
        return undefined;
    }
}));
const overload = {
    call(self, ...actual) {
        calls++;
        assert.equal(self, receiver);
        assert.deepEqual(actual, args);
        if (failure) throw failure;
        return result;
    }
};
const second = {call() { return undefined; }};
const broken = {};
Object.defineProperty(broken, "implementation", {set() {throw new Error(secret);}});
const context = {
    Process: {
        arch: "ia32",
        getCurrentThreadId() {
            if (scenario === "metadata_error") throw new Error(secret);
            return 42;
        }
    },
    send(event) {
        if (scenario === "transport") throw new Error(secret);
        events.push(event);
    }
};
if (scenario !== "no_bridge") {
    context.Java = {
        available: scenario !== "unavailable",
        perform(callback) { callback(); },
        backtrace(options) {
            backtraces++;
            assert.equal(options.limit, 12);
            if (scenario === "metadata_error") throw new Error(secret);
            return {frames: Array.from({length: 20}, () => ({
                className: "com.example.TlsCaller", methodName: "verify",
                origin: secret, signature: secret, fileName: secret
            }))};
        },
        use(name) {
            if (scenario === "facebook" && name === facebookClass) return {
                verify: {overloads: fbOverloads.slice(0, 3)},
                verifyWithProofOfPossession: {overloads: fbOverloads.slice(3)}
            };
            if (scenario === "missing" || name !== "com.android.org.conscrypt.TrustManagerImpl")
                throw new Error(secret);
            return {
                verifyChain: {overloads: [overload, second]},
                checkServerTrusted: {overloads: [broken]}
            };
        }
    };
}
vm.runInNewContext(fs.readFileSync(script, "utf8"), context);
if (["no_bridge", "unavailable", "missing"].includes(scenario)) {
    assert.equal(overload.implementation, undefined);
    if (scenario === "missing") {
        assert.equal(events.find(e => e.event === "java_tls.ready").installed, 0);
        assert.equal(events.filter(e => e.event === "java_tls.class_unavailable").length, 5);
    }
} else {
    assert.equal(overload.implementation.apply(receiver, args), result);
    assert.equal(second.implementation.call(receiver), undefined);
    assert.equal(calls, 1);
    assert.equal(backtraces, 2);
    if (scenario !== "transport") {
        const starts = events.filter(e => e.event === "java_tls.call");
        assert.equal(starts[0].callId, 1);
        assert.equal(starts[0].threadId, scenario === "metadata_error" ? null : 42);
        assert(!Number.isNaN(Date.parse(starts[0].time)));
        const end = events.find(e => e.event === "java_tls.return");
        assert.equal(end.callId, starts[0].callId);
        const sample = events.find(e => e.event === "java_tls.caller");
        assert.equal(sample.callId, starts[0].callId);
        if (scenario === "metadata_error") assert.equal(sample.frames, null);
        else {
            assert.equal(sample.frames.length, 12);
            assert.equal(JSON.stringify(sample.frames[0]), JSON.stringify({
                className: "com.example.TlsCaller", method: "verify"
            }));
        }
    }
    if (scenario === "limit") {
        // A success flood must not exhaust the budget or skip original calls.
        const before = events.length;
        for (let i = 0; i < 250; i++)
            assert.equal(overload.implementation.apply(receiver, args), result);
        assert.equal(calls, 251);
        assert.equal(events.length, before + 2);
        assert(!events.some(e => e.event === "java_tls.limit"));
        // Rejections remain visible after call/return sampling, up to global cap.
        failure = {message: secret};
        for (let i = 0; i < 250; i++)
            assert.throws(() => overload.implementation.apply(receiver, args), e => e === failure);
        assert.equal(calls, 501);
        assert(events.some(e => e.event === "java_tls.reject" && e.callId > 251));
        assert.equal(events.length, 201);
        assert.equal(events.filter(e => e.event === "java_tls.limit").length, 1);
    } else {
        for (const [message, expected] of [
            ["Certificate pinning failure! " + secret, "reported_pinning"],
            ["Trust anchor for certification path not found " + secret, "reported_trust_anchor"],
            ["Hostname not verified " + secret, "reported_hostname"],
            ["Certificate expired " + secret, "reported_validity"],
            [secret, "unclassified"]
        ]) {
            failure = {getMessage() {return message;}};
            assert.throws(() => overload.implementation.apply(receiver, args), e => e === failure);
            if (scenario !== "transport")
                assert.equal(events.at(-1).category, expected);
        }
        failure = {};
        Object.defineProperty(failure, "getMessage", {get() {throw new Error(secret);}});
        assert.throws(() => overload.implementation.apply(receiver, args), e => e === failure);
        if (scenario !== "transport") {
            assert.equal(events.at(-1).category, "unclassified");
            assert(events.some(e => e.event === "java_tls.hook_error"));
        }
    }
}
if (typeof overload.implementation === "function") assert.equal(backtraces, 2);
if (scenario === "facebook") {
    const signatures = [
        [[{certificate: secret}], secret, true],
        [[[1, 2]], secret],
        [[[1, 2]], secret, false],
        [[[1, 2]], secret, true, 7, [3, 4], [5, 6]]
    ];
    for (const [index, fb] of fbOverloads.entries()) {
        fb.expected = signatures[index];
        for (let i = 0; i < 4; i++)
            assert.equal(fb.implementation.apply(receiver, fb.expected), undefined);
        fb.failure = {message: "Certificate pinning failure! " + secret};
        assert.throws(() => fb.implementation.apply(receiver, fb.expected), e => e === fb.failure);
        assert.equal(fb.calls, 5);
        const rejected = events.at(-1);
        assert.equal(rejected.event, "java_tls.reject");
        assert.equal(rejected.className, facebookClass);
        assert.equal(rejected.method, index === 3 ? "verifyWithProofOfPossession" : "verify");
        assert.equal(rejected.overload, index === 3 ? 0 : index);
        assert.equal(rejected.category, "reported_pinning");
    }
    const fbEvents = events.filter(e => e.className === facebookClass);
    assert.equal(fbEvents.filter(e => e.event === "java_tls.call").length, 8);
    assert.equal(fbEvents.filter(e => e.event === "java_tls.return").length, 8);
    assert.equal(fbEvents.filter(e => e.event === "java_tls.caller").length, 4);
    assert.equal(backtraces, 6);
}
assert(!JSON.stringify(events).includes(secret));
console.log(JSON.stringify({ok: true}));
