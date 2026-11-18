// Explicit operator-approved, temporary test. NOT an observe-only script.
// Official native Frida REPL only; never load alongside another TLS hook.
"use strict";

(() => {
    const allowedHosts = new Set(["i.instagram.com", "i-fallback.instagram.com"]);
    const durationMs = 30000;
    const maxEvents = 100;
    const contexts = new Map();
    let emitted = 0;
    let callId = 0;
    let deadline = 0;
    function emit(event, fields) {
        try {
            if (emitted >= maxEvents) return;
            emitted++;
            send(Object.assign({event: event, time: new Date().toISOString()}, fields || {}));
            if (emitted === maxEvents) send({event: "fb_trial.limit", maxEvents: maxEvents});
        } catch (_) {}
    }
    function host(value) {
        // Match only exact fixed hosts. No wildcard, URL parsing or arbitrary toString.
        return typeof value === "string" && allowedHosts.has(value) ? value : null;
    }
    function leaf(certs) {
        try {
            return certs != null && certs.length > 0 && certs.length <= 16
                ? certs[0] : null;
        } catch (_) { return null; }
    }
    function threadId() {
        try { return Process.getCurrentThreadId(); } catch (_) { return null; }
    }
    function current(id) {
        const stack = contexts.get(id);
        return stack && stack.length ? stack[stack.length - 1] : null;
    }
    function compatible(overload, returnType) {
        // Don't overwrite an existing instrumenter's hook.
        return overload.returnType.className === returnType && overload.implementation == null;
    }

    emit("fb_trial.runtime", {
        mode: "targeted_pinning_exception_override", durationMs: durationMs,
        allowedHosts: Array.from(allowedHosts), expectedVersion: "416.0.0.47.66"
    });
    if (typeof Java === "undefined" || !Java.available || Process.arch !== "ia32") {
        emit("fb_trial.refused", {reason: "runtime_mismatch"});
        return;
    }
    try {
        Java.perform(() => {
            let verify, trust, Throwable, CertificateException, PeerException;
            try {
                const app = Java.use("android.app.ActivityThread").currentApplication();
                const name = app.getPackageName();
                const info = app.getPackageManager().getPackageInfo("com.instagram.android", 0);
                if (name !== "com.instagram.android" ||
                    info.versionName.value !== "416.0.0.47.66" ||
                    info.versionCode.value !== 382206160) {
                    emit("fb_trial.refused", {reason: "app_version_mismatch"});
                    return;
                }
                verify = Java.use(
                    "com.facebook.mobilenetwork.internal.certificateverifier.CertificateVerifier"
                ).verify.overload(
                    "[Ljava.security.cert.X509Certificate;", "java.lang.String", "boolean"
                );
                trust = Java.use("com.android.org.conscrypt.TrustManagerImpl")
                    .checkServerTrusted.overload(
                        "[Ljava.security.cert.X509Certificate;", "java.lang.String", "java.lang.String"
                    );
                Throwable = Java.use("java.lang.Throwable");
                CertificateException = Java.use("java.security.cert.CertificateException");
                PeerException = Java.use("javax.net.ssl.SSLPeerUnverifiedException");
                if (!compatible(verify, "void") || !compatible(trust, "java.util.List")) {
                    emit("fb_trial.refused", {reason: "signature_or_existing_hook"});
                    return;
                }
            } catch (_) {
                emit("fb_trial.refused", {reason: "prerequisites_unavailable"});
                return;
            }

            function pinningException(error) {
                try {
                    // Frida's Java bridge wraps a thrown Java Throwable in an Error
                    // with $h. Reject plain JS errors or unrecognized Java types.
                    if (error == null || error.$h == null) return false;
                    const javaError = Java.cast(error, Throwable);
                    if (!CertificateException.class.isInstance(javaError) &&
                        !PeerException.class.isInstance(javaError)) return false;
                    // Preserve specialized validity/parsing/etc. exceptions regardless
                    // of their message. Unknown app-specific subclasses fail closed.
                    const type = javaError.getClass().getName();
                    if (type !== "java.security.cert.CertificateException" &&
                        type !== "javax.net.ssl.SSLPeerUnverifiedException") return false;
                    const message = javaError.getMessage();
                    if (typeof message !== "string" || message.length > 4096) return false;
                    if (/trust anchor|expired|not yet valid|hostname|host name|proof.of.possession/i
                        .test(message)) return false;
                    return /\b(?:pinning (?:failure|failed)|pin verification (?:failure|failed)|certificate pin mismatch)\b/i
                        .test(message);
                } catch (_) { return false; }
            }

            const trustImplementation = function (certs, authType, hostname) {
                const context = current(threadId());
                let result;
                try {
                    result = trust.call(this, certs, authType, hostname);
                } catch (error) {
                    if (context) context.trustFailed = true;
                    throw error;
                }
                try {
                    const candidate = leaf(certs);
                    if (context && context.host !== null && context.host === host(hostname) &&
                        context.leaf != null && candidate != null &&
                        context.leaf.equals(candidate) &&
                        result != null && result.size() > 0) context.trusted = true;
                } catch (_) {
                    if (context) context.trustFailed = true;
                }
                return result;
            };
            const verifyImplementation = function (certs, hostname, flag) {
                const id = threadId();
                if (id === null || Date.now() >= deadline)
                    return verify.call(this, certs, hostname, flag);
                const context = {
                    id: ++callId, host: host(hostname), leaf: leaf(certs),
                    trusted: false, trustFailed: false
                };
                let stack = contexts.get(id);
                if (!stack) { stack = []; contexts.set(id, stack); }
                stack.push(context);
                try {
                    const result = verify.call(this, certs, hostname, flag);
                    emit("fb_trial.original_return", {callId: context.id});
                    return result;
                } catch (error) {
                    if (Date.now() < deadline && context.host !== null &&
                        context.trusted && !context.trustFailed && pinningException(error)) {
                        emit("fb_trial.override", {
                            callId: context.id, systemTrustObserved: true
                        });
                        // This exact original method is void. No other overload is changed.
                        return;
                    }
                    emit("fb_trial.preserved_rejection", {
                        callId: context.id, hostAllowed: context.host !== null,
                        systemTrustObserved: context.trusted && !context.trustFailed
                    });
                    throw error;
                } finally {
                    stack.pop();
                    if (stack.length === 0) contexts.delete(id);
                }
            };
            // Install the non-mutating trust observer first. Roll back on partial setup.
            try {
                trust.implementation = trustImplementation;
                verify.implementation = verifyImplementation;
            } catch (_) {
                try {
                    if (trust.implementation === trustImplementation) trust.implementation = null;
                    if (verify.implementation === verifyImplementation) verify.implementation = null;
                } catch (_) {}
                emit("fb_trial.refused", {reason: "hook_install_failed"});
                return;
            }
            deadline = Date.now() + durationMs;
            emit("fb_trial.ready", {durationMs: durationMs, maxEvents: maxEvents});
        });
    } catch (_) {
        emit("fb_trial.refused", {reason: "java_setup_failed"});
    }
})();
