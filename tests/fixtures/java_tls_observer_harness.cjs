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
    Process: {arch: "ia32"},
    send(event) {
        if (scenario === "transport") throw new Error(secret);
        events.push(event);
    }
};
if (scenario !== "no_bridge") {
    context.Java = {
        available: scenario !== "unavailable",
        perform(callback) { callback(); },
        use(name) {
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
        assert.equal(events.filter(e => e.event === "java_tls.class_unavailable").length, 4);
    }
} else {
    assert.equal(overload.implementation.apply(receiver, args), result);
    assert.equal(second.implementation.call(receiver), undefined);
    assert.equal(calls, 1);
    if (scenario === "limit") {
        for (let i = 0; i < 250; i++)
            assert.equal(overload.implementation.apply(receiver, args), result);
        assert.equal(calls, 251);
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
assert(!JSON.stringify(events).includes(secret));
console.log(JSON.stringify({ok: true}));
