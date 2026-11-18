// Observe only. Load with the official Frida REPL (which bundles the Java bridge).
// Never emit arguments, hosts, certificates, raw exceptions, headers or payloads.
"use strict";

(() => {
    const maxEvents = 200;
    let emitted = 0;
    let nextCallId = 0;
    function emit(event, fields) {
        // Diagnostics must not change a verifier's result even if transport fails.
        try {
            if (emitted >= maxEvents) return;
            emitted++;
            send(Object.assign({event: event, time: new Date().toISOString()}, fields || {}));
            if (emitted === maxEvents)
                send({event: "java_tls.limit", maxEvents: maxEvents});
        } catch (_) {}
    }

    function threadId() {
        try { return Process.getCurrentThreadId(); } catch (_) { return null; }
    }

    function callerFrames() {
        try {
            // Only symbolic Java class/method names; no signature, origin, file,
            // line, native addresses, raw stack strings or runtime arguments.
            return Java.backtrace({limit: 12}).frames.slice(0, 12).map(frame => {
                function symbol(value) {
                    return typeof value === "string" && value.length <= 200 &&
                        /^[A-Za-z0-9_.$<>-]+$/.test(value) ? value : "[omitted]";
                }
                return {
                    className: symbol(frame.className),
                    method: symbol(frame.methodName)
                };
            });
        } catch (_) { return null; }
    }

    function category(error) {
        // A reported category is a hint, not proof of the underlying mechanism.
        // Inspect a bounded message locally; never serialize the error itself.
        try {
            const message = typeof error.getMessage === "function"
                ? error.getMessage() : error.message;
            const text = message == null ? "" : String(message).slice(0, 4096).toLowerCase();
            if (/pinning|pinned|pin verification/.test(text)) return "reported_pinning";
            if (/trust anchor|unable to find valid certification path/.test(text))
                return "reported_trust_anchor";
            if (/hostname|host name|subject alternative/.test(text)) return "reported_hostname";
            if (/expired|not yet valid|validity/.test(text)) return "reported_validity";
        } catch (_) {}
        return "unclassified";
    }

    emit("java_tls.runtime", {
        arch: Process.arch, mode: "observe_only", maxEvents: maxEvents,
        bridgeLoaded: typeof Java !== "undefined",
        javaAvailable: typeof Java !== "undefined" && Java.available
    });
    if (typeof Java === "undefined" || !Java.available) return;

    try {
        Java.perform(() => {
            let installed = 0;
            const targets = [
                ["com.android.org.conscrypt.TrustManagerImpl",
                    ["verifyChain", "checkTrustedRecursive", "checkServerTrusted"]],
                ["org.conscrypt.TrustManagerImpl",
                    ["verifyChain", "checkTrustedRecursive", "checkServerTrusted"]],
                ["okhttp3.CertificatePinner", ["check", "check$okhttp"]],
                ["com.squareup.okhttp.CertificatePinner", ["check"]]
            ];
            for (const [className, methods] of targets) {
                let klass;
                try {
                    klass = Java.use(className);
                } catch (_) {
                    emit("java_tls.class_unavailable", {className: className});
                    continue;
                }
                for (const method of methods) {
                    try {
                        const dispatcher = klass[method];
                        if (!dispatcher || !dispatcher.overloads) continue;
                        dispatcher.overloads.forEach((overload, index) => {
                            let sampled = false;
                            // Capture this exact overload; do not redispatch or recurse.
                            overload.implementation = function () {
                                const metadata = {
                                    className: className, method: method, overload: index,
                                    callId: ++nextCallId, threadId: threadId()
                                };
                                emit("java_tls.call", metadata);
                                if (!sampled && emitted < maxEvents) {
                                    sampled = true;
                                    emit("java_tls.caller", Object.assign({}, metadata, {
                                        frames: callerFrames()
                                    }));
                                }
                                let result;
                                try {
                                    result = overload.call(this, ...arguments);
                                } catch (error) {
                                    emit("java_tls.reject", Object.assign({}, metadata, {
                                        category: category(error)
                                    }));
                                    throw error;
                                }
                                emit("java_tls.return", metadata);
                                return result;
                            };
                            installed++;
                            emit("java_tls.hook_ready", {
                                className: className, method: method, overload: index
                            });
                        });
                    } catch (_) {
                        emit("java_tls.hook_error", {className: className, method: method});
                    }
                }
            }
            emit("java_tls.ready", {installed: installed});
        });
    } catch (_) {
        emit("java_tls.setup_error");
    }
})();
