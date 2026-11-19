"use strict";
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const [script, scenario] = process.argv.slice(2);
const events = [];
const secret = "PRIVATE_CERT_TOKEN_HEADER";
let now = Date.parse("2026-11-18T12:00:00Z");
class Clock extends Date {
    constructor(...args) { super(...(args.length ? args : [now])); }
    static now() { return now; }
}
let fbCalls = 0;
let trustCalls = 0;
let callTrust = true;
let trustFailure = false;
let tid = 17;
const receiver = {};
const trustReceiver = {};
const certificate = {
    equals(other) {
        if (scenario === "metadata_error") throw new Error(secret);
        return other === certificate;
    }
};
const certs = [certificate];
const host = scenario === "other_host" ? "other.invalid" :
    scenario === "suffix_host" ? "i.instagram.com.other.invalid" :
    scenario === "cdn" ? "instagram.fcgk16-1.fna.fbcdn.net" :
    scenario === "cdn_suffix" ? "instagram.fcgk16-1.fna.fbcdn.net.other.invalid" :
    scenario === "other_cdn" ? "instagram.fcgk17-1.fna.fbcdn.net" :
    scenario === "fallback" ? "i-fallback.instagram.com" : "i.instagram.com";
const originalError = {
    $h: {}, type: scenario === "wrong_type" ? "Other" :
        scenario === "peer_exception" ? "PeerException" : "CertificateException",
    text: scenario === "nonpinning" ? "Hostname verification failed " + secret :
        "Pinning failure " + secret
};
if (scenario === "validity") originalError.text = "Pinning failure: certificate expired";
if (scenario === "proof_failure") originalError.text = "Pinning failure: proof of possession";
if (scenario === "ambiguous") originalError.text = "pinning enabled: unrelated failure";
if (scenario === "long_message") originalError.text = "Pinning failure " + "x".repeat(5000);
if (scenario === "plain_js") delete originalError.$h;
const trustError = {$h: {}, type: "CertificateException", text: "Trust anchor missing " + secret};
const trustResult = {size() {return scenario === "empty_trust" ? 0 : 1;}};
let trustImpl = null;
let verifyImpl = null;
const trust = {
    returnType: {className: "java.util.List"},
    get implementation() {return trustImpl;},
    set implementation(value) {trustImpl = value;},
    call(self, ...args) {
        trustCalls++;
        assert.equal(self, trustReceiver);
        assert.equal(args[1], "RSA");
        if (trustFailure) throw trustError;
        return trustResult;
    }
};
const verify = {
    returnType: {className: scenario === "signature" ? "boolean" : "void"},
    get implementation() {return verifyImpl;},
    set implementation(value) {
        if (scenario === "partial_install" && value !== null) throw new Error(secret);
        verifyImpl = value;
    },
    call(self, ...args) {
        fbCalls++;
        assert.equal(self, receiver);
        assert.equal(args[0], certs);
        assert.equal(args[1], host);
        assert.equal(args[2], true);
        if (scenario !== "no_trust" && callTrust) {
            const observedCerts = scenario === "wrong_leaf" ? [{}] : certs;
            const observedHost = scenario === "wrong_host" ? "other.invalid" : host;
            const oldTid = tid;
            if (scenario === "thread_mismatch") tid = 18;
            try {
                const result = (trustImpl || ((...a) => trust.call(trustReceiver, ...a)))
                    .call(trustReceiver, observedCerts, "RSA", observedHost);
                assert.equal(result, trustResult);
            } catch (error) {
                if (scenario !== "swallowed_trust_reject") throw error;
                assert.equal(error, trustError);
            } finally {tid = oldTid;}
        }
        if (scenario === "mid_expiry") now += 31000;
        if (scenario === "original_success") return undefined;
        throw originalError;
    }
};
if (scenario === "existing_hook") verifyImpl = function existing() {};
const classes = {
    "android.app.ActivityThread": {currentApplication() {return {
        getPackageName() {return "com.instagram.android";},
        getPackageManager() {return {
            getPackageInfo() {return {
                versionName: {value: scenario === "version" ? "other" : "416.0.0.47.66"},
                versionCode: {value: 382206160}
            };}
        };}
    };}},
    "com.facebook.mobilenetwork.internal.certificateverifier.CertificateVerifier": {
        verify: {overload(...args) {
            assert.deepEqual(args, [
                "[Ljava.security.cert.X509Certificate;", "java.lang.String", "boolean"
            ]);
            return verify;
        }}
    },
    "com.android.org.conscrypt.TrustManagerImpl": {
        checkServerTrusted: {overload(...args) {
            assert.deepEqual(args, [
                "[Ljava.security.cert.X509Certificate;", "java.lang.String", "java.lang.String"
            ]);
            return trust;
        }}
    },
    "java.lang.Throwable": {},
    "java.security.cert.CertificateException": {
        class: {isInstance(e) {return e.type === "CertificateException";}}
    },
    "javax.net.ssl.SSLPeerUnverifiedException": {
        class: {isInstance(e) {return e.type === "PeerException";}}
    }
};
const context = {
    Date: Clock,
    Process: {
        arch: scenario === "abi" ? "arm" : "ia32",
        getCurrentThreadId() {
            if (scenario === "thread_error") throw new Error(secret);
            return tid;
        }
    },
    send(event) {
        if (scenario === "transport") throw new Error(secret);
        events.push(event);
    }
};
if (scenario.startsWith("duration_")) {
    context.__snifferTrialDurationMs = scenario === "duration_120" ||
        scenario === "duration_120_expired" ? 120000 :
        scenario === "duration_300" || scenario === "duration_300_expired" ? 300000 :
        scenario === "duration_string" ? "120000" : 120001;
}
if (scenario !== "bridge_missing") context.Java = {
    available: true,
    perform(callback) {callback();},
    use(name) {return classes[name];},
    cast(error) {
        if (scenario === "cast_error") throw new Error(secret);
        assert(error.$h);
        return {
            type: error.type,
            getMessage() {return error.text;},
            getClass() {return {getName() {
                if (scenario === "subclass") return "java.security.cert.CertificateExpiredException";
                return error.type === "PeerException" ? "javax.net.ssl.SSLPeerUnverifiedException" :
                    "java.security.cert.CertificateException";
            }};}
        };
    }
};
vm.runInNewContext(fs.readFileSync(script, "utf8"), context);
if (["abi", "version", "signature", "existing_hook", "partial_install", "bridge_missing",
    "duration_string", "duration_invalid"]
    .includes(scenario)) {
    assert(events.some(e => e.event === "fb_trial.refused"));
    assert.equal(trustImpl, null);
    if (scenario === "existing_hook") assert.equal(verifyImpl.name, "existing");
    else assert.equal(verifyImpl, null);
    assert.equal(fbCalls, 0);
} else {
    if (scenario !== "transport") assert(events.some(e => e.event === "fb_trial.ready"));
    if (scenario === "expired") now += 31000;
    if (scenario === "duration_120") {
        now += 31000;
        assert(events.some(e => e.event === "fb_trial.ready" && e.durationMs === 120000));
    }
    if (scenario === "duration_120_expired") now += 121000;
    if (scenario === "duration_300_expired") now += 301000;
    trustFailure = ["trust_reject", "swallowed_trust_reject"].includes(scenario);
    const allowed = ["override", "fallback", "cdn", "peer_exception", "stale", "transport", "limit",
        "duration_120", "duration_300"]
        .includes(scenario);
    if (allowed || scenario === "original_success")
        assert.equal(verifyImpl.call(receiver, certs, host, true), undefined);
    else {
        const expected = scenario === "trust_reject" ? trustError : originalError;
        assert.throws(() => verifyImpl.call(receiver, certs, host, true), e => e === expected);
    }
    assert.equal(fbCalls, 1);
    assert.equal(trustCalls, scenario === "no_trust" ? 0 : 1);
    if (scenario === "stale") {
        callTrust = false;
        assert.throws(() => verifyImpl.call(receiver, certs, host, true), e => e === originalError);
        assert.equal(events.at(-1).event, "fb_trial.preserved_rejection");
        assert.equal(events.at(-1).systemTrustObserved, false);
    }
    if (scenario === "limit") {
        for (let i = 0; i < 150; i++)
            assert.equal(verifyImpl.call(receiver, certs, host, true), undefined);
        assert.equal(events.length, 101);
        assert.equal(events.filter(e => e.event === "fb_trial.limit").length, 1);
        assert.equal(fbCalls, 151);
        now += 31000;
        assert.throws(() => verifyImpl.call(receiver, certs, host, true), e => e === originalError);
    }
    if (scenario === "duration_300") {
        assert(events.some(e => e.event === "fb_trial.ready" && e.durationMs === 300000));
    }
    if (scenario !== "transport" && scenario !== "limit")
        assert.equal(events.filter(e => e.event === "fb_trial.override").length, allowed ? 1 : 0);
}
assert(!JSON.stringify(events).includes(secret));
assert(!JSON.stringify(events).includes("other.invalid"));
console.log(JSON.stringify({ok: true}));
