# Operator-approved, temporary Facebook pinning trial

This script changes an application TLS decision. It is **not** an observer and
must only be used on an authorized test device/app. The operator explicitly
approved preparing this bounded test after the observe-only trace showed
Conscrypt returning normally, then Facebook `CertificateVerifier.verify`
throwing a pin-related exception.

## Scope and guards

`src/sniffer/scripts/instagram/facebook_pinning_trial.js` runs only through the
official Frida REPL in the native realm. It refuses unless the Java bridge exists,
the process architecture is ia32, and the current package/version is exactly
`com.instagram.android`, `416.0.0.47.66`, versionCode382206160. No APK is changed.
It requires the following exact signatures and no existing hooks on them in this
agent's Java bridge:

- Facebook `CertificateVerifier.verify(X509Certificate[], String, boolean): void`.
- System Conscrypt
  `TrustManagerImpl.checkServerTrusted(X509Certificate[], String, String): List`.

The original Facebook method always executes first. Its normal return is
preserved. An exception may become a void return ONLY when:

- The original hostname is exactly `i.instagram.com` or `i-fallback.instagram.com`
  (no suffix/wildcard matching).
- During that same synchronous invocation, on the same native thread, the original
  Conscrypt method returns a nonempty trusted chain for the same hostname and
  equal leaf certificate. The system method's arguments/results are not changed.
- No system trust exception occurred in that invocation, even one caught by the
  original Facebook method.
- The thrown Java object's exact class is `java.security.cert.CertificateException`
  or `javax.net.ssl.SSLPeerUnverifiedException`, not a specialized validity/parsing
  exception, app-specific subclass or plain JS error.
- Its locally inspected message contains a narrowly recognized pinning-failure
  phrase and no trust-anchor/validity/hostname/proof-of-possession wording.
- The script is still inside its30second override window.

Unknown messages/types, missing correlation, comparison/inspection failures,
other hosts, other overloads, or expiry preserve the original exception. The
outer `verifyWithProofOfPossession` is NOT replaced; it continues its original
execution after the inner method. No boolean is fabricated, no trust manager
returns an empty chain, and no blanket SSL/native hook is installed.

**Limitations:** The original exception is suppressed at this method boundary;
execution cannot resume inside it after the throw. This does not prove every
later app check runs. The correlation depends on the observed Java path and may
fail closed if an implementation differs. Pinning-error classification is
text-based; unknown phrases will NOT be overridden. This is not a universal or
production-safe bypass. A later independent PoP/native/other-host check can still
reject the connection. An override event is NOT proof of successful capture.

## One controlled run

Deploy the new file first. Finish the previous observer and every worker/Appium
run. Never load both scripts together. The REPL does not acquire project device
locks and cannot reliably detect other agents' hooks: operator exclusivity is
mandatory.

Open Instagram manually; keep the existing approved proxy, CA, server and
loopback forwarding. Do not restart shared services, spawn/relaunch the app,
change an APK or clear data.

```bash
(
set -euo pipefail
PID=$(adb -s 127.0.0.1:5555 shell pidof com.instagram.android | tr -d '\r') ||
  { echo "Open Instagram manually first"; exit 1; }
[[ "$PID" =~ ^[0-9]+$ ]] ||
  { echo "STOP: expected one main Instagram PID"; exit 1; }
uv run --extra frida \
  --with "frida-tools==14.13.2" --with "frida==17.27.0" \
  frida -H 127.0.0.1:27052 -p "$PID" --realm native \
  -q -t 30 --exit-on-error \
  -l src/sniffer/scripts/instagram/facebook_pinning_trial.js
)
```

After `fb_trial.ready`, search manually in STF. Stop if the app/server crashes;
do not loop retry or widen guards. `fb_trial.refused` means prerequisites did
not match: share its static reason, do not force activation.

Overrides stop automatically30seconds after successful setup, even if the script
remains loaded. Expired hooks become pass-through. REPL exit unloads the script;
never eternalize it. There is no config/worker integration or automatic activation.

Events are capped at100 plus a limit marker and contain only static reasons,
call IDs and guard booleans; no dynamic host, cert, message, header, token, key,
body or raw exception. The fixed two-host scope is shown at startup. Reaching the
logging cap does not extend the30second override window.

Share `fb_trial.ready/override/preserved_rejection/refused` events, whether search
finished, and whether mitmweb shows a readable HTTP response from the intended IG
host at the same time (hostname/status/time only). Do not share cookies, tokens,
raw traffic or response bodies. Worker/semantic-parser tests remain deferred
until native HTTP response acceptance.

## Validation

Node simulations cover exact original forwarding, void return, exception identity
on rejection, host/leaf/thread correlation, trust errors (including caught trust
errors), expiry before/during calls, no stale trust reuse, signature/version/ABI/
bridge/existing-hook guards, rollback after partial installation, message/type
guards, transport failure, and logging cap. These are not live Android tests.
The agent did not attach to or modify the user's device.

Java bridge exception handling uses Frida's Java-Throwable `$h` wrapper, checked
against upstream source:
https://github.com/frida/frida-java-bridge/blob/main/lib/env.js .
