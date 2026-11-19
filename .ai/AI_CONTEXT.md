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
Unknown endpoints retain redacted `unmapped_json`; the later TopSerp parser
implementation and operator keyword-capture evidence are recorded below.
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

User's native TLS observer result (pid30270): ia32, pointerSize4, ELF machine3,
hooks ready on /system/lib/libcrypto.so X509_verify_cert and five libssl.so APIs;
libjavacrypto reports no additional hooks. Supplied output contains NO tls.call.
Hook installation is not evidence those functions handle IG requests; do not
replace returns or infer the app's verifier from this snapshot.
`javaBridgeAvailable=false` in this observer means the global Java bridge was not
bundled, NOT that the application has no Java/ART runtime. Frida17 removed bridges
from plain create_script; official frida-tools REPL agents include them.
Reference: https://frida.re/news/2025/05/17/frida-17-0-0-released/ .

Next minimal native Java-availability probe uses an ephemeral pinned REPL:
frida-tools14.13.2 (requires Frida>=17.26,<18) with Frida17.27.0 explicitly pinned,
via uv run --with. CLI flags -p/--realm native/-q/-t/--exit-on-error were verified
locally with --help; no actual Android attach by agent. No project dependency or
lockfile change is needed. Only typeof Java/Java.available/Process.arch are read.
Run only after previous observer/job completes; no simultaneous worker/inspect.
This does not load Java trust hooks, alter certificates, or prove a bypass works.

Operator's REPL Java probe succeeded: arch ia32, bridgeLoaded true,
javaAvailable true. Native Java access is confirmed, not verifier-hook stability.
Prepared shared/java_tls_observer.js for official REPL only, not Python
create_script: available Conscrypt verifyChain/checkTrustedRecursive/
checkServerTrusted and known OkHttp check/check$okhttp overloads, exact original
receiver/arguments/results/exceptions. No bypass or exception-constructor hooks.
At most200 metadata events plus limit marker; no arguments/raw messages/hosts/
certificates/headers/stacks. Coarse reported_* categories are hints, not diagnosis.
Missing/late/obfuscated classes and other class loaders/native paths may be missed.
Next operator step: one30s native REPL attach to current main PID, manually search
after java_tls.ready, no concurrent workers/observers. REPL has no project lock;
operator must enforce exclusivity. No spawn/eternalize or device/service changes.
Node simulations cover preservation, exception identity, categories/privacy, event
limit, absent bridge/classes and failed logging. Actual Java hooks remain untested
on Android by agent; remote native HTTPS capture remains blocked/unaccepted.
Local validation after Java observer:125 tests passed, Ruff/diff checks clean,
wheel/sdist build succeeded. These include simulations, not live TLS validation.

Operator supplied live Java observer output: installed7 = system Conscrypt
verifyChain1/checkTrustedRecursive1/checkServerTrusted5. org.conscrypt and both
known OkHttp CertificatePinner classes unavailable in the selected loader.
Supplied repeated Conscrypt calls returned normally; no reject events. Search
still loading; remote mitmproxy at10:08:40.988 reports client-disconnected handshake
for i.instagram.com. This does not prove pinning or tie that connection to the
successful Conscrypt calls. No bypass justified for this observed success path.
Added UTC time/callId/native threadId and once-per-overload Java caller symbols
(max12 frames, class/method only, max200 chars each; no raw stack/signatures/paths/
arguments). Failed sampling does not alter verifier behavior. Next one bounded
native REPL run to identify callers, with contemporaneous proxy timestamp/timezone.
Still no destination/socket correlation; JNI/native callers may not appear.
Local validation after caller metadata:126 tests passed, Ruff/diff clean,
wheel/sdist build succeeded; metadata lookup failure and capped samples simulated.

Latest user trace at10:16:12.716Z identified actual Java caller path:
TigonMNSServiceHolder.runEVLoop -> Facebook MobileNetwork CertificateVerifier
verifyWithProofOfPossession -> verify -> X509TrustManagerExtensions -> Conscrypt.
Provided Conscrypt calls returned normally on thread31614. Global200-event cap
was reached at call93; no conclusion about unrecorded outer verifier decisions.
Signature-only probe confirmed CertificateVerifier.verify returns void for
(X509Certificate[],String,boolean), (byte[][],String), (byte[][],String,boolean);
verifyWithProofOfPossession returns void for
(byte[][],String,boolean,int,byte[],byte[]).
Prepared observe-only hooks of both Facebook methods in the same Java REPL script.
Do not force a boolean or assume the method name proves pinning/PoP rejection.
Call/return metadata is now sampled for first2 invocations per overload; all
exceptions still emit sanitized reject metadata until global200 cap. Every
original invocation still executes and preserves void result/exception identity.
Next one30s operator native run, manually search; inspect Facebook-class
call/return/reject events with concurrent proxy error. Same loaded classes would
yield11 installed hooks; class-specific hook_ready is the actual coverage evidence.
No host/socket correlation or decrypted-traffic acceptance yet.
Local validation after Facebook observer/sampling:127 tests passed, Ruff/diff
clean, wheel/sdist build succeeded. Facebook hook behavior is simulated only;
operator has verified its signatures/caller path, not yet its observed outcomes.

Latest operator run at10:26:49Z installed all11 expected hooks. At10:26:55Z
same thread32571: Facebook verifyWithProofOfPossession call1 -> verify
(X509Certificate[],String,boolean) call2 -> Conscrypt calls3-6 RETURN normally,
then Facebook verify call2 REJECT reported_pinning at10:26:55.573Z and outer
verifyWithProofOfPossession call1 REJECT at10:26:55.575Z. Pattern repeats through
10:27:06.954Z. The outer event is consistent with exception propagation, not
evidence of a second independent PoP failure.
Strong observed evidence of app-level Facebook verifier rejection categorized
from pin-related exception text after system trust success; raw exception text
was not exported and no host/socket correlation exists. Not capture acceptance.
No need to repeat the same observer just to establish this rejection path.
Next decision requires operator approval before preparing a separate opt-in
targeted pinning exception override for a bounded authorized test. Keep observer
non-mutating; do not implicitly change TLS/CA/APK/OS or enable a bypass in workers.

Operator explicitly chose "Siapkan uji bypass terarah" on the approval form:
prepare a separate opt-in bounded authorized test, retain original system trust,
no CA/APK/OS changes or implicit worker activation. Implemented
instagram/facebook_pinning_trial.js (official native REPL only). Exact package
IG416.0.0.47.66/versionCode382206160/ia32 guard; original verify(cert[],host,bool)
always runs. Only recognized pinning-failure text on typed Java CertificateException/
SSLPeerUnverifiedException may be suppressed, for exact i.instagram.com or
i-fallback.instagram.com, after original checkServerTrusted(cert[],auth,host)
accepted same host/equal leaf within current invocation/thread, with no trust
failure. Other errors preserve exception identity. Outer PoP method is not hooked.
Internal30second deadline even if left loaded;100 metadata events+marker, no raw
messages/certs/args/dynamic hosts. Observer remains unchanged; no config/worker
integration. Fail-closed mismatch must not be worked around blindly.
The original method cannot resume after its throw; later internal checks might
not run. This is explicit temporary weakened app pinning, not production-safe or
universal. Original outer verification may reject independently. No live test by
agent; NEXT operator deploy and one bounded run, manually search after ready,
share events + HTTP hostname/status/time and UI outcome (no bodies/secrets).
See docs/facebook-pinning-trial.md for command/constraints. Do not run observer
and trial concurrently; REPL doesn't take project locks. Stop on crash.
Specialized/app-specific exception subclasses also fail closed even if they
mention pinning; only the two exact standard exception classes are eligible.
Local validation:162 tests passed, Ruff/diff clean, wheel/sdist build succeeded;
wheel contains the trial JS. All trial behavior tests are Node simulations, not
live Instagram interception. No device commands or deployment performed by agent.

Operator trial at10:39:22Z ready: two fb_trial.override events at10:39:29.325Z/
.374Z with systemTrustObserved true. User reports search now works but questions
whether traffic entered mitmproxy. Remaining supplied events have hostAllowed
false/systemTrustObserved false: out-of-scope host rejections preserved, NOT
evidence of failed system trust for the two allowed hosts. Do not widen host scope
blindly. Trial only overrides eligible pinning failures; it does not route traffic,
configure proxy or export HTTP flows. Search UI can use cached data; no readable
HTTP response sample yet. NEXT inspect existing remote mitmweb with display filter
cleared around10:39:29Z (account for timezone); report hostname/status/time or
same-period TLS errors. Distinguish empty display, handshake errors and readable
HTTP response before another instrumentation change. No repeat trial needed just
to interpret these events; capture/remote-recorder acceptance remains pending.

User supplied proxy TLS handshake disconnect for
instagram.fcgk16-1.fna.fbcdn.net. This shows that CDN connection reached the proxy,
but not readable HTTP; does not establish API capture or exact CDN verifier cause.
Operator approved "Tambahkan satu host CDN ini" and requested public JS research.
Added ONLY that exact hostname to trial allowlist (now3), unchanged guards/30s.
No *.fbcdn.net or other regional CDN hosts; API-flow acceptance still pending.

Read-only research found Beeper2025-11-24 article documenting the same
CertificateVerifier.verify/Tigon stack and readable mitmproxy after a broad no-op
hook plus Eltion patches. Eltion repo currently GitHub-disabled (not reviewed).
Reviewed KnifeLemon/Android-SSL-Pinning-Bypass e423bc691eba0dfebc686930f27387b9c58fcd2a
(v442/444/449/455, Android12 x86_64 claim), Aniketh01/
Instagram-android-ssl-pinning-bypass4162de84022e8276e32a9e2cf912ad8d44911126
(v433 Android15 arm64; source mentions422), depreciating/
Instagram-SSL-Pinning-Bypass f5cf91943d90040861d8defff10cbc8ee5d7c999 (v435).
Public scripts use broader verifier/PoP no-ops and/or Tigon startup configuration
plus trust-all Conscrypt/SSLContext. Not proven on our IG416/Houdini/Android9.
Our observed runtime path takes precedence over their version heuristics.
No third-party code copied/installed/executed, no image/APK/OS changes or implicit
new hooks. Sources/commit-pinned review in docs/instagram-public-scripts.md.
NEXT one operator trial with exact approved CDN + inspect readable API/CDN
HTTP host/status/time in remote mitmweb, not just more Frida events.
Local validation after exact-CDN update:165 tests passed, Ruff/diff clean,
wheel/sdist build succeeded. New simulations allow approved CDN and reject its
suffix-spoof and a different regional CDN. Live expanded scope remains untested.

Latest user evidence (2026-11-18): remote mitmweb exposes readable native response
from https://i.instagram.com/api/v1/feed/timeline/ with status="ok" and populated
feed_items. This establishes HTTPS decryption/capture for that timeline endpoint,
not just server-connect metadata. Body status is not an observed HTTP status code.
Timeline is home-feed traffic, not proof of keyword-search response extraction.
No raw sample copied: supplied content includes cookies, tracking tokens,
identifiers and signed media URLs. Consecutive JSON objects in the paste do not
establish framing/Content-Type; do not assume a single standard JSON document.
NEXT correlate a fresh controlled keyword search with request time and keyword;
obtain sanitized host/path/method/HTTP status/Content-Type and response shape.
Do not repeat CA/realm setup or broaden hooks just to re-prove timeline capture.
Remote recorder/output transport, semantic search parsing, repeated-run stability
and worker acceptance remain pending. Agent has not operated the remote device.

## Keyword-search response evidence and parser implementation

Operator subsequently supplied POST https://i.instagram.com/graphql/query with
form operation TopSerpQuery and variables.query="kopi toraja"; pagination=true
with an after cursor. Paired response has manual_pagination_query.edges[].node
MEDIA_GRID items, XDTMediaDict photos/video/reel/carousel. This is direct evidence
of native keyword-search capture for that operator run, not just Explore/timeline.
The excerpt shows20 parent items and deferred SerpClipsViewerFragment docs adding
caption/counts/user metadata, plus TopSerpPagingInfo__force_flush (has_next_page).
Every supplied final flag isfalse: do not claim whole-response completion.
Actual HTTP status and Content-Type/wire framing still not supplied. No raw sample
values/contacts/identifiers/cursors/signed URLs saved to project.

An intervening native attach failed "connection closed": user read-only output
showed ADB forward intact, no visible server process/device27052 listener, binary
still17.27.0. Operator restarted the SAME binary in a dedicated foreground shell,
then continued the bounded trial + one --no-frida/--no-capture Appium run. Agent
did not execute remote commands. Server stop cause remains unknown; no emulated
retry, CA/APK/OS/proxy/host-allowlist change or persistent trial was introduced.

User approved implementation and switched to Build. Added shared bounded UTF-8
JSON-sequence decoder, IG416 observed-shape parser, recorder routing by exact
host/path/method/form operation/query, deferred path+media-ID merge, parent-post
deduplication, selected normalized fields and explicit partial/invalid outcomes.
GraphQL errors/unsupported paths/units/limits/missing final block completeness.
Request operation/query/pagination only survive; signed media querystrings,
tracking/session/cursor values and manifests are not exported by this parser.
Captions/user fields remain personal data requiring restricted retention.
Unknown JSON endpoint behavior remains unmapped_json; no blanket recursive search.

Recorder writes per-flow normalized requests.jsonl and atomic enriched posts.jsonl
snapshot keyed(keyword,parent ID), bounded10k posts/32MiB. Local executor semantic
flag now requires >=1 exact-keyword complete2xx response with nonempty posts;
partial response counts remain explicit. No change to worker default/ACK policy.
Offline base-only CLI: sniffer parse instagram-search --request request.json
--response response.body --keyword ... --output NEW_DIRECTORY. Minimal request
metadata format and limitations in docs/instagram-search-parsing.md; no device,
network, proxy attachment or automatic remote-output transport.
Tests use authored synthetic structural fixtures ONLY. TLS trial/script untouched.
NEXT operator export complete decoded response + minimal paired request metadata,
run offline parser and inspect summary/posts. Remote recorder deployment/transport,
job correlation, repeated-run stability and end-to-end queue acceptance still pending.

Local validation after parser implementation:240 tests passed, Ruff/diff checks
clean, wheel/sdist built. New modules confirmed in wheel; offline imports do not
load mitmproxy/Appium/Frida. Includes actual local HTTP proxy smoke, simulated
recorder/executor and synthetic JSON-sequence/CLI tests, NOT remote IG parser
acceptance. No dependencies/lockfile/TLS scripts changed and no deployment performed.

## Approved one-shot automation and outgoing results (2026-11-19)

User now requests search +10 scrolls and publishing data to Beanstalk
202.56.161.146:22400. Form supplied tube sniffer_instagram_result, keyword prabowo,
and explicitly approved up-to120second targeted trial. Capture/format choices were
not filled; implementation states one-post-per-message recommendation and chooses
read-only existing mitmweb API rather than installing/restarting an addon/service.
No backend/API service or queue-driven persistent trial was introduced.

New explicit CLI automation instagram collect --device android01 --keyword ...
--targeted-trial --publish performs one controlled run only. Requires configured
remote WEB API URL (not proxy18919), exact proxy-observed client IP, existing
frida_endpoint, IG manually foreground, no configured observer/scripts/concurrent
device jobs. Dry-run is side-effect free. Appium opens once before instrumentation;
no activate_app/spawn/restart. Native official REPL pinned17.27.0/tools14.13.2
supplies Java, disables auto-reload, waits ready, exits on refusal/failure/expiry.
Default JS trial stays30s; a fixed approved120s global parameter is accepted only
in addition to30s, all other durations fail closed. Three exact hosts/system trust/
build/signatures/typed pin exception guards unchanged. Wrapper has a conservative
monotonic deadline and owns/cleans only its REPL child, never IG/server/STF.

Read-only collector checks mitmweb11.0.2 GET /flows and GET request/response
content.data; route/metadata verified against public source, not remote server.
Baseline flow IDs refreshed after trial ready, exact client IP/query/API method/
host/path/port, proxy Date/time window, finished response and no replay. Detects
differing search-session IDs using in-memory digest; refuses baseline eviction/
view changes/API errors/non2xx/size limits. Raw API headers/body metadata kept
transient, never persisted. HTTP allowed only loopback tunnel; otherwise HTTPS,
no redirects/TLS-disable. Optional SNIFFER_MITMWEB_AUTHORIZATION read from env
at use time (secret card needed if agent must receive/use it). No auth in URL.

Separate results config/env from input beanstalk worker. After10 UI gestures+
settle and successful owned cleanup, writes capture-result then durable outbox
before first put. One allowlisted normalized parent post/message incl schema1,
event_id hash(job/keyword/post), job/device/keyword, completeness flag. Partial
responses stay flagged; do not imply exhaustive results or10 pages/fixed postcount.
Preflight use/stats only, max-job-size checked before pending puts, INSERTED IDs
saved after each. results publish resumes existing outbox and does not rerun UI;
results prepare can prepare a completed saved capture. At-least-once after lost
reply/crash; downstream consumer must dedup event_id. Never reserve/delete input
jobs; old worker defaults/ACK policy unchanged. No live production queue puts.

Doc docs/automated-collection.md. Operator still must provide actual web API URL
without credentials and client_conn.peername IP before runnable live config.
Actual remote auth, wire framing,120s Android stability and target queue delivery/
consumer acceptance remain unverified. Do not silently expose/restart services.

Local validation after collect/results implementation:283 tests passed, Ruff/diff
checks clean, wheel/sdist built. Real loopback HTTP API simulator and synthetic
Beanstalk wire server verify GET-only capture / use+stats+put only; lifecycle mocks,
outbox receipt recovery, pinned-REPL command and Node120s guard/expiry simulations.
No requests/puts to actual infrastructure, no deployed config/CA/proxy changes.

Operator requested config/local.yaml after returning to Build. No existing local
file was present here. Created a Git-ignored operator profile preserving example
device/selectors/local paths and separate incoming queue defaults; android01
frida_endpoint=127.0.0.1:27052 and outgoing results202.56.161.146:22400 /
sniffer_instagram_result. Appium4723 remains the example/default, not a new live
verification. remote_mitmweb.url/client_ip intentionally null because neither
was supplied; collect must fail before any service access until configured.
No secret/token or guessed web port/NAT IP. File exists ONLY on this workstation;
Git push/pull will not transfer it. Operator must copy/merge on server without
overwriting any existing server-local profile. No service/device changes.

User clarified the objective: retain automatic search+10 scroll+sniff+parse, but
do not create posts.jsonl in collect; publish each FULL normalized post JSON
directly (no envelope). User explicitly chose protected temporary outbox for
retry. Collect now accumulates/deduplicates in bounded memory, logs only response
metadata, writes outbox after successful capture even without --publish, then
optionally puts records. Existing offline/local recorder still writes posts.jsonl.
Any old outbox remains unmodified and publishable with its original payload.
If capture fails before outbox persistence the in-memory data cannot be recovered.
Lost put reply/receipt can duplicate; consumer dedup by (job_id,keyword,id).
Remote web API remains required by current collector; HTTP-only remote without
an accessible secure tunnel has not been resolved. No remote service accessed.
Local validation after direct JSON/outbox change:284 tests passed, Ruff/diff clean,
wheel/sdist build successful. Tests use synthetic capture and queue, not live proxy.

## Latest direction: input keyword worker; proxy owns result publishing

User corrected the architecture: external engine puts keyword jobs into Beanstalk;
our worker watches, searches, scrolls10 times, and existing proxy separately sniffs
and pushes results. No remote mitmweb API/tunnel, local posts.jsonl or outgoing
publisher required for this path. Producer host/port/tube/schema not yet confirmed;
temporary strictly validated input {"keyword":"prabowo"} only, other fields refused.
Do not assume outgoing result host/tube are input host/tube.

User explicitly approved per-job targeted Frida: attach only on reservation,
native official pinned REPL, existing verified three-host/system-trust/build guards
and120s cap; unload after job and stay unattached while queue idle. Existing IG
must already be open/foreground; no spawn/app/service/proxy/CA restart/change.
New opt-in command `sniffer worker-keywords --device android01 --targeted-trial`
(--once for one reservation/timeout). Legacy worker unchanged, no silent hooks.
UI automation only: ACK means10 gestures, owned cleanup and 3s wait, NOT evidence
proxy captured or pushed. External proxy state is not queried; it remains operator's
responsibility to verify. Device lock and lease heartbeat held per reservation.
Success marker before delete keyed hash(queue stats.id instance,tube,job id);
crash before marker or queue restart may repeat job. Runtime error releases/buries
according to retry cap then stops worker; no unattended repeat attach after trial
failure. Invalid payload/TTR buried, lease lost never ACK. No code connects to
actual server or publishes any result; no live trial/worker acceptance yet.
Documentation docs/keyword-worker.md.
Local validation:311 tests passed, Ruff/diff clean, wheel/sdist built. Includes
actual synthetic loopback queue protocol and mocked Appium/Frida lifecycle; no
real queue/device/proxy commands were run by agent. User's earlier working
UI/capture smoke does not prove this new per-job worker path.

User reported prior keyword job released/stopped when IG was not launched and
explicitly approved auto-opening IG per job with NO clear app data or account loss.
Worker now sends exactly one package-restricted Android launcher monkey intent if
not foreground, waits at most20s for foreground AND one positive unambiguous main
PID with heartbeat checkpoints, then attaches trial and waits ready before search.
Already-foreground app is never launched again. No force-stop, clear/reset,
credential/login, Frida spawn or retry; Appium noReset/fullReset=false unchanged.
Failure is recorded as static phase+error type for diagnosis, without raw output.
Initial app startup traffic may occur before hook, not guaranteed to decrypt.
Real Android launcher/login/capture behavior remains to be user-tested; agent did
not operate device, reset data, push code or touch server.
Local verification:318 tests passed, Ruff/diff clean, wheel/sdist built; launcher
and PID handling tested with mocks, not a real device.

User tested job298236: LAUNCH_START then failure foreground_and_pid before attach,
job released/worker stopped. Operator's manual `monkey` reported
"SYS_KEYS has no physical keys", process existed but launcher remained foreground.
User's read-only `cmd package resolve-activity --brief` returned
com.instagram.android/.activity.MainTabActivity. Changed worker to dynamically
resolve Android MAIN/LAUNCHER via cmd package, validate exactly one shell-safe
component belonging to com.instagram.android, then invoke am start -n without
-S once. Refuse missing/ambiguous/foreign/malicious component; no fallback retry,
force-stop, clear data, credentials, APK/OS changes or Frida spawn. Wait for
foreground+single PID before attach as before. Actual am start is unverified on
device; user must deploy and test; agent made no remote/device changes.
Local verification after launcher replacement:323 tests passed, Ruff/diff clean,
wheel/sdist built. Activity resolution/start tests are mocks, not live Android.

User requested automatic Frida server startup for the keyword worker, in order
server -> app init -> attach/trial -> search. Implemented WorkerFridaServer:
endpoint first probed; reachable server reused; if unreachable, existing
frida-server process blocks any attempt to replace it; only if none exists will
the explicitly configured per-device `frida_server_path` be checked executable
and started on Android loopback at endpoint port. Existing ADB forwards untouched.
The worker keeps a server it started across jobs and, on graceful exit, SIGTERMs
only its recorded PID after `/proc/PID/cmdline` identity check. Existing server
is never stopped. Abrupt worker death can leave server running; next run adopts
it and never claims ownership. Example path is the operator-reported
`/data/local/tmp/sniffer-frida.1ortVs/frida-server`, but it must be confirmed in
local config/on device. No device/server was accessed. Requires deployment and
live test; server readiness, attach, login/session and proxy capture unverified.
Local validation after lifecycle changes:331 tests passed, Ruff/diff clean,
wheel/sdist built; lifecycle tests use mocks only.

Operator tested startup: worker logged Frida START then failed readiness after
10s before opening IG; PID41365 remained on device and cleanup skipped because
Frida exposed just argv0 in cmdline. `/proc/net/tcp` confirmed listener at
127.0.0.1:27042 (`69A2`), while configured endpoint/forward targeted27052
(`69AC`). First diagnostic instruction incorrectly used `69C4` for27052; corrected.
Root cause in implementation: ADB `shell sh -c <script>` split the launch payload
on older platform-tools, so listen arguments were not passed and server used
default27042. Fixed to pass full launch script as a single `adb shell` argument;
owned cleanup now accepts exact executable-only cmdline for its recorded PID.
Local validation after this fix:332 tests passed, Ruff/diff clean, wheel/sdist built.
Tests simulate shell invocation and cleanup, not live Android. Current
misconfigured server PID remains operator-owned/orphaned; it must be stopped
manually after confirming PID/cmdline, then deploy corrected code and let worker
start server. Do not assume script can replace an existing inaccessible server.
