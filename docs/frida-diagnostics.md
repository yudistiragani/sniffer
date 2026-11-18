# Native TLS observer (not a bypass)

## Verified prerequisites, as reported by operator

Frida17.27.0 client/server; Android x86_64 server in isolated loopback27052, ADB
forward27052 with --no-rebind. Instagram416.0.0.47.66 APK is armeabi-v7a; a minimal
attach probe reported **ia32**, pointerSize4, libhoudini, libssl, libcrypto,
libjavacrypto, libart. It stayed attached5s. No TLS-hook stability claim follows.
The current proxy is remote; browser HTTPS works after additive verified CA setup.
Native-app HTTPS still fails with proxy on.

## What the observer does

Before intercepting native functions, inspect the realm's module view. Houdini
processes may expose ARM libraries separately from the default native (ia32) realm:
https://frida.re/news/2021/02/10/frida-14-2-released/ .
This API exists but does NOT guarantee emulated attachment works on every Redroid
build; do not auto-retry on an error or modify the APK/memory to force it.

Open Instagram manually, then use a metadata-only probe:

```bash
uv run --extra frida sniffer frida inspect --device android01 \
  --endpoint 127.0.0.1:27052 --realm emulated --duration 5
```

This command has a device lock, never spawns/activates an app, loads only
`shared/runtime_probe.js`, and detaches after the bounded probe. It does not load
the TLS observer, run Appium, alter Android proxy, start a Frida server, or modify
certificates. Native default is also available with `--realm native`.
Inspect actual arch/module paths; unsupported emulated realm or a crash is a
diagnostic result, not permission to inject again automatically.
Java instrumentation belongs in the native realm; Frida17's plain script API does
not automatically bundle a Java bridge. No Java hook is supplied here.

`shared/tls_observer.js` observes calls/return metadata of selected exported native
SSL/crypto functions. It never replaces functions, args, callbacks, return values,
trust stores, or certificates. No request/response bodies, tokens, headers,
certificate contents, stack/memory dumps, or plaintext payloads are collected.

ELF machine must match actual Process.arch. Translated ARM modules inside an ia32
process are reported/skipped, not intercepted. Forwarded exports outside the module
are skipped. Module load/unload handled; at most200 metadata events plus limit marker.
Missing exports/Java bridge or no tls.call events do NOT prove absence of pinning.
Handshake return -1 can be nonblocking IO, not a certificate rejection by itself.

This still uses instrumentation and may crash an incompatible process. Do not
auto-retry on a crash. No universal TLS bypass is shipped.

## One controlled run

Keep the operator-started Frida server and its forwarding alive. Do not launch a
second instance or take over unknown forwards. Open Instagram manually so the adapter
can attach to its existing PID; running PID is obtained with ADB pidof rather than
Frida enumerate_applications. Only if no running PID exists does the generic adapter
attempt spawn (not proven stable in this environment). Do not clear account data.

After pushing/pulling this code, in the Redroid server's repo:

```bash
uv run --extra automation --extra frida sniffer automation instagram search \
  --device android01 --keyword "kopi lokal" --scroll-count 1 \
  --no-capture --frida --frida-endpoint 127.0.0.1:27052 \
  --frida-script shared/tls_observer.js
```

`--no-capture` disables LOCAL mitmdump, not Android's remote proxy. Ensure global
proxy remains the intended remote endpoint. Do not restore CA or global proxy as
an automatic side effect of this diagnostic command.

Endpoint/script overrides apply in memory for this run only and require --frida;
no YAML/registry change. Runtime prints session output path and known TLS event
labels; full metadata is in `frida.jsonl` in that directory, including failed jobs.
UI may still spin/fail while TLS remains blocked: that is expected for an observer.
Do not treat this as successful native capture or parser acceptance.

Share only observer metadata and relevant proxy TLS error lines. For readability,
inspect the session file without exporting unrelated capture files:

```bash
tail -n 40 output/SESSION_DIRECTORY_FROM_LOG/frida.jsonl
```

The code writes script errors and checks unexpected detach between UI operations.
It does not automatically relaunch a crashed app, kill external services, remove
forwards, install CA/Magisk, or modify the APK.

## Local validation

Node (optional, development only) executes the actual observer JS in a simulated
GumJS environment during tests. Scenarios cover native/translated machine checks,
missing/forwarded exports, attach errors, untouched args/returns, module unload/
reload, and event limit. These tests do not verify real Android interception.
