# Task context

## Agreed scope

Build a small Python executor in `D:\Workspace\Office\NoLimit\DE\sniffer`, not a copy
of the reference backend at `D:\Workspace\Personal\Media Mage\cyber-legion-be`.
Development is local Windows; Git transports code to a Linux server where device
integration runs. Use `pyproject.toml`, `uv`, a lockfile, and a packaged CLI.

Initial platform: **Instagram keyword search**, bounded scrolling, traffic capture,
file output, and a thin Beanstalk worker. TikTok is a future extension point, not
implemented search. No API, dashboard, Redis, SQL server, AI, or distributed scheduler.
Per-platform extraction parsers; shared recording/decoding/writing.

### Frida assumptions and validated UI baseline

Initially the user asked to treat Frida server/scripts as unavailable; do not
depend on old scripts or Magisk. The operator has since explicitly prepared a
new server and verified one native metadata attach, as recorded below. This does
not make a TLS bypass available or authorize implicit injection on ordinary jobs.
The Appium keyword-search/scroll baseline without capture/proxy has passed.
That baseline is not the end goal; native capture remains the current priority.
The optional Frida adapter remains
scaffolding; this is not permission to delete/stop existing external services.
The code already defaults `frida=False`; no loader or server is started in this mode.
Installing a Python extra is not the same as enabling instrumentation.

Team report, not independently verified: Instagram version 379 search was described
as deprecated; version 416 search works with the proxy OFF. An intermediate
380-ish version was suggested, but exact builds/APKs are not established. Do not
upgrade/downgrade the user's app or obtain APKs automatically. Record actual
installed version/ABI before making version-dependent automation changes.
Team says Appium flow remains usable, scroll size could be smoother, and Frida
injection on a Magisk-customized Redroid crashes/is unstable. Do not equate the
successful UI smoke with functional search API responses on the older version.
Version-related search failure and app TLS failure through proxy are distinct.
Do not introduce bypass work or injection without a separate request.

### Current priority: remote Instagram capture

After the no-proxy/no-Frida UI baseline succeeded (job
`manual-d588162819534900b1d75222d0833932`), user explicitly corrected the proposed
move to Beanstalk: first make Instagram requests readable in remote mitmproxy.
Worker acceptance is deferred, not the capture goal. Test the currently functional
Instagram version with proxy re-enabled and the verified System CA, still without
Frida. Keep `--no-capture --no-frida`: this disables local mitmdump/injection,
NOT Android's externally configured proxy. Verify method/path/status/response in
remote mitmweb; a TLS/domain log or local captured_responses=0 is not acceptance.
If native TLS still fails, focus app-specific trust/pinning diagnostics; do not
repeat CA installation, arbitrary upgrades, or assume Frida already exists.

The repository also supports a limited infrastructure interface: register existing
devices, inspect/start existing STF, and create/start/stop/destroy NEW managed
Redroid devices with an explicitly selected local image. Do not build a full device
farm orchestrator. Keep create, start, provision, stop, and destroy separate.

## User-provided infrastructure (not inspected live)

| Resource | Image / endpoint |
| --- | --- |
| android01 | `redroid/redroid:9.0.0_houdini`, `127.0.0.1:5555 -> 5555` |
| android02 | same image, `127.0.0.1:5556 -> 5555` |
| STF | existing Compose-style stack, project inferred as `stf`, to verify |
| stf-proxy-1 | nginx; published 7100 |
| stf-provider-1 | published 7400-7500 |
| stf-adb-1 | ADB container; 5037 not host-published in supplied output |

Also present: STF app/API/auth-mock/reaper/processor/websocket/groups-engine,
triproxy, storage, RethinkDB. "Healthy" does not prove end-to-end functionality.
These loopback endpoints belong to the server, not the Windows workstation.
User reports an emulator can log in; exact app versions/ABI/login require testing.
The Android 9 Houdini image tag does NOT prove Magisk is installed.

## Capture and instrumentation decisions

Appium automates UI, mitmproxy captures proxied traffic, Frida instruments app
processes. The executor coordinates them; Appium does not inherently run Frida.
Frida scripts are shared by default, platform-specific only when needed, never
required per UI page. Configure explicit Frida target; never assume USB device
or equality with ADB serial.

CA trust/proxy setup is distinct from Frida scripts. User CA may not be trusted,
and TLS pinning may prevent capture. No automatic trust bypass/CA installation.
Shared example script only emits a readiness message, not traffic instrumentation.
Do not invent Instagram endpoints or call unknown JSON a normalized search result.

## Current implementation status

Initial base implementation is delivered; see TASKS.md for local verification and
outstanding live acceptance. `uv.lock` is generated. Optional dependencies are
installed/tested locally with `uv sync --all-extras`. No live server changes,
existing-container operations, device automation, or Instagram HTTPS capture have
been performed by the coding agent.

CLI examples:

```text
uv run sniffer automation instagram search --device android01 --keyword "kopi lokal" --dry-run
uv run --all-extras sniffer worker instagram --device android01
uv run sniffer device create android03 --image OPERATOR_AUDITED_IMAGE
uv run sniffer device start android03
```

Actual Magisk image selection/build remains pending: accepting a configurable image
is not proof it contains working Magisk. No image has been pulled or created.
The default parser records redacted `unmapped_json`, not normalized search results.
Proxy provisioning is opt-in reverse/global-proxy setup, not full CA/root provisioning.

## First server feedback and UI diagnosis

User's doctor reports Android 9 / SDK28 / x86_64, ADB connected, Appium ready,
Python extras present, Beanstalk reachable, and free system/proxy ports. This is
user-supplied output, not agent-operated live acceptance. Frida target and CA trust
remain unverified. User's UI-only search reached the search screen but did not type.

Local `output/diagnostics/ig-search.xml` contains an enabled/clickable EditText with
ID `com.instagram.android:id/action_bar_search_edit_text`, matching default config.
At dump time it is empty and unfocused. This does NOT prove a locator mismatch or
the need to tap an extra Explore bar. Original XML contains private search/account
data: leave ignored in output/, never copy it wholesale into fixtures or docs.

Search now logs START/END/FAILED per lookup, click, clear, type, submit, results,
and scroll, without keyword/text or raw exception details. Named selector timeouts
and health checks help identify which Appium call fails/stalls. This is diagnostic
instrumentation, not a confirmed live fix.

User's next run reported `StaleElementReferenceException` at `search_tab.click`
after successful lookup, then `Port unavailable: 127.0.0.1:8201` on retry.
Stale element references are now reacquired with at most three interaction attempts;
lookup tolerates stale visibility checks. Input retries clear + replace + verify the
whole keyword, never blindly append a possibly partially entered keyword.
Appium startup briefly waits for systemPort and uses a POSIX reusable bind check to
avoid treating reusable TIME_WAIT as an active listener. The actual port owner is
not known from user logs: this may still be an active session/ADB forward.
Session cleanup is logged and preserves primary UI failures if quit also fails.
No automatic process kill, forward removal, or device reset is performed.

## User-reported UI success

On 2026-11-18, user reran UI-only Instagram keyword search on android01 after the
stale/lifecycle patch and reported success: `action=search`, `scrolls=1`,
job `manual-aac0b06464784944a7fb7b1ad7e3755f`, output session
`20261118T072326Z_instagram_android01_2cdc4c59`.
`captured_responses=0` is expected because this test used `--no-capture`.
`semantic_search_results_verified=false` is expected because semantic extraction
is not implemented. This validates a single user-operated UI smoke, not HTTPS
capture, Frida, Beanstalk execution, all search categories, or multi-run stability.
Next: inspect current proxy/reverse configuration read-only, then prepare capture
with the correct CA before enabling it. Do not blindly overwrite the existing proxy.

## Remote proxy and operator-performed CA setup

The actual proxy is REMOTE at `103.191.17.34:18919`, not the Redroid host.
The user set Android's global proxy explicitly with `provision --proxy`, without
ADB reverse. Continue UI automation with `--no-capture`: the current CLI capture
command starts a LOCAL mitmdump; it does not collect traffic from the remote service.
Remote recorder integration/output transport is still not implemented.

Proxy server: root-operated mitmweb 11.0.2, supervised as
`mitm:mitmproxy_android_00`. Process PID 2231928 was observed at diagnosis time
(not a permanent identifier). confdir `~/.mitmproxy` resolves to `/root/.mitmproxy`.
HTTP neverssl works. example.com had a domain-specific name-resolution failure,
not a global DNS outage: i.instagram.com resolves. Curl through the proxy with
its CA verified TLS and received an origin HTTP404 for `https://i.instagram.com/`.
HTTP404 at the root is not a TLS failure. These are user-provided results.

The user showed a preexisting system CA with serial starting 655F3A56, different
from the current proxy CA. Current verified public CA:
- Serial: `26589AE0A3732411F6D5F0EBCE7C25AE142D8F8D`
- SHA256: `6C:61:F9:92:48:4E:DF:C3:05:7A:D4:37:90:C0:61:40:02:81:03:47:06:1D:A7:C8:2B:F6:EC:30:05:37:D8:36`
- OpenSSL subject_hash_old: `c8750f0d`

User explicitly approved additive System CA installation on android01 via the
consent card. ADB shell is uid0, root overlay filesystem is rw. The operator then
ran a manual fingerprint-verified staging/hardlink procedure and confirmed the
current CA at `/system/etc/security/cacerts/c8750f0d.1`; preexisting `.0` preserved.
The first attempt's `ln -T` was unsupported by this Android9 toybox; corrected
plain `ln` with nonexistence checks succeeded. Do not repeat `ln -T` instructions.
No automatic CA installation was added to the project. The agent did not connect
to or change the server directly. No device reboot or account reset was performed.

Next: reopen the emulator browser (without clearing data) and test the resolvable
`https://i.instagram.com/`, verifying method/path/status in remote mitmweb. Origin
404 is acceptable for transport testing. Then test the Instagram app separately;
pinning is possible but not established. Adding the CA file is not proof that
already-running applications reloaded trust, or that all app HTTPS is decrypted.

User subsequently reported HTTPS access in the emulator browser succeeds after
the CA addition. This is browser-only acceptance, not Instagram-app decryption.
The subsequent native-app test still failed TLS and search kept spinning despite
browser HTTPS success. A controlled retest of the working app build with proxy
re-enabled also failed TLS at i-fallback.instagram.com. The user asked whether
missing Frida hooks explains the failure; app-specific TLS validation/pinning is
suspected, not proven by disconnect messages alone.

Latest package metadata from user:
- Instagram `416.0.0.47.66`, versionCode `382206160`.
- `minSdk=26`, `targetSdk=36`.
- APK `primaryCpuAbi=armeabi-v7a`, `secondaryCpuAbi=null`.
- Android primary ABI `x86_64` (existing Android9 Houdini environment).

This suggests a 32-bit ARM APK running through native translation on x86_64.
It is relevant to Frida/native-hook compatibility, but not proof of the reported
injection crash cause. A standalone frida-server normally follows device OS ABI
(x86_64), not the APK's armeabi-v7a ABI. Determine actual target-process architecture
and native bridge behavior during a minimal diagnostic attach before native hooks.
Do not silently replace the APK, select ARM server from APK ABI, assume old scripts
exist, or run a blanket TLS hook. Next obtain client version and prepare a matching
server; then test minimal instrumentation stability before any app-specific hook.

User has since prepared verified official Frida17.27.0 Android-x86_64 server at
`/data/local/tmp/sniffer-frida.1ortVs/frida-server` (runtime path, not permanent).
It runs explicitly on Android loopback27052, forwarded with ADB --no-rebind to
host27052. User confirmed enumeration (73 processes) and a minimal IG attach probe:
pid27109 at that moment, Process.arch=ia32, pointerSize4, libhoudini/libart/libssl/
libcrypto/libjavacrypto present. Probe stayed attached5s. This does not validate
native TLS hooks, Java bridge, bypass, or long-running injection stability.

The next diagnostic is metadata-only `sniffer frida inspect --realm emulated`:
Frida officially supports a separate emulated realm for some NativeBridge/Houdini
processes, which may reveal ARM libraries absent from the native ia32 module view.
See https://frida.re/news/2021/02/10/frida-14-2-released/ . Compatibility here is
NOT established. Inspect loads only runtime_probe.js, never a TLS hook, never
spawns/activates an app, and stops on unsupported/crashed attach without retries.
No proxy/certificate changes are part of inspect. User must keep the explicit
server/forward running and open IG manually before testing.

Also prepared (not yet live tested): opt-in shared/tls_observer.js for bounded
native TLS metadata. No bypass, no request bodies/tokens; only same-machine ELF
modules and in-module exports are intercepted. Use after verifying the realm and
module view, not a blanket hook. Java instrumentation requires a bridge in the
native realm; plain Frida17 scripts do not automatically include it. The one-run
Instagram endpoint/script CLI overrides avoid changing YAML or registry. Native
TLS capture is still blocked until proven otherwise; agent has not operated server.

Local validation after diagnostic/error-reporting additions: 119 tests pass, Ruff and git diff
checks clean, wheel/sdist build succeeds. Node executes the actual TLS observer in
simulated GumJS to test machine guards, non-mutating callbacks, cleanup, and event
limits. These are not real Android TLS/interception tests. Runtime inspector,
emulated realm, and TLS observer still require user-operated server testing.

User's first emulated inspect failed during attach with ProtocolError (before
script load). At subsequent observation frida-server pid29133 and IG main pid29689
were running, with IG fbns pid29485. The crash buffer excerpt referenced Binder
pid17 at02:15, not enough to attribute a crash to this attempt (clock correlation
unknown). Do NOT conclude emulated support, anti-Frida detection, or that no
restart ever occurred from these snapshots.

The CLI previously hid the original ProtocolError string. Attach exceptions now
become actionable RuntimeErrors with bounded/sanitized detail, and a
frida-attach-error.json includes realm/pid/phase/original type/detail. No automatic
retry or fallback was added. Next operator action: after updating code, at most
one deliberate metadata-only retry to collect the original error, if they elect
to continue; stop on crash. Do not switch APKs, patch memory, or restart services
based only on the generic ProtocolError.

The one deliberate retry now exposes the detail: attach emulated to IG pid29689
failed in ~1.4s with ProtocolError "the connection is closed", before script load.
This is Frida attach/channel failure, not a mitmproxy HTTP/TLS error. It does NOT
identify anti-Frida, a certificate verifier, or a proven root cause in Houdini.
Stop emulated retries. Next: one native TLS observer run in the realm with prior
successful metadata attach, without bypassing certificate decisions. Native view
may miss ARM app libraries; no observed native calls does not prove no pinning.
Use --no-frida-spawn so missing/background IG causes failure rather than restart;
open IG manually beforehand, keep server/forward, no concurrent worker/inspect.
Inspect frida.jsonl for hook/call metadata even if UI search still spins.
