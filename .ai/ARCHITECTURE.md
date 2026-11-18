# Architecture

`src/sniffer` is a Python package. CLI calls services directly, not other CLI
commands or `exec()` of source files. Third-party integrations are lazy imports.

- `cli.py`: independent operational commands.
- `settings.py`: validated YAML config, selected environment overrides.
- `device.py`: ADB adapter and small local JSON inventory.
- `runtime.py`: subprocess execution, atomic JSON, file locks, port checks.
- `jobs.py`: strict, bounded keyword-search payload.
- `integrations/`: Redroid/STF Docker, Appium, Frida, mitmproxy adapters.
- `platforms/instagram/`: executor, UI selectors/flow, parser.
- `platforms/tiktok/`: explicitly unsupported search extension point.
- `capture/`: recorder addon, output writer, session lifecycle.
- `worker.py`: Beanstalk reserve/touch/retry/bury/ack.
- `scripts/{shared,instagram,tiktok}`: packaged JavaScript resources.

## Execution

Validated baseline: Appium only with proxy off, `--no-capture`, Frida disabled.
Current goal: native Instagram traffic readable in remote mitmproxy. Proxy-on
testing still fails native-app TLS. No Frida server/script is presumed available;
bootstrap/version and minimal-attach stability must precede app-specific hooks.
Optional integrations are never activated, or external services stopped, implicitly.

One worker owns one device lock. Each job creates a separate session directory.
Capture starts before app interaction. Appium uses no-reset/auto-launch-disabled
capabilities; Frida may attach/spawn before automation activates the app. The
configured selectors are initial candidates, not verified against the user's app.
The search-input ID was subsequently observed in a user-provided XML dump. After
stale handling was added, the user reported one successful one-scroll UI-only
search on android01; capture and semantic extraction remain unverified.
Instagram UI actions emit per-step START/END/FAILED
terminal logs, with named lookup timeouts and health checkpoints while polling.
Stale-only interactions reacquire a fresh element at most three times. Keyword
entry retries are clear/type/readback transactions to prevent duplicate partial
text. Unrelated driver errors are not retried. Appium's session context logs quit,
fails successful jobs when quit fails, and preserves an already raised UI exception.
Before connecting, systemPort is checked with a short bounded wait and POSIX
SO_REUSEADDR (TIME_WAIT tolerance, not permission to take over a listener).

Standalone capture needs no Appium. Standalone automation can disable capture.
mitmproxy addon runs in the mitmdump process; it imports parser/writer from this
installed package. There is no pretend attachment to an arbitrary running proxy.
Frida events are separate from HTTP response records.

`shared/tls_observer.js` is an opt-in native TLS diagnostic, not a bypass. It emits
bounded metadata for selected native SSL/crypto APIs, never changes args/results,
and skips modules whose ELF machine differs from the target process (native bridge
safety). Module-load observation covers late libraries. Java bridge is not bundled.
Negative nonblocking handshake returns alone are NOT proof of pinning.
One-shot Instagram CLI overrides `--frida-endpoint`/repeatable `--frida-script`
require `--frida` and change in-memory settings only, not local YAML/registry.
The adapter resolves an existing PID via ADB pidof, matching the operator's minimal
probe; ambiguous PIDs are rejected rather than guessed. Generic spawn fallback
remains if no app process exists; open IG manually for diagnostic attach testing.
Frida script errors/unexpected detach fail health checks; cleanup preserves an
existing primary exception. Console prints known TLS event names; full metadata
goes to frida.jsonl, and the session directory is logged before connection.
`frida inspect` is a separate device-locked, bounded metadata-only attach command.
It uses only runtime_probe.js and disables spawn; caller explicitly selects native
or emulated realm. Houdini's emulated realm may expose otherwise hidden ARM libs.
It does NOT activate the TLS observer, alter proxy, or silently enable emulated
mode in automation. Emulated-view compatibility still requires operator testing.
Attach failures preserve original exception type and bounded/redacted detail in
frida-attach-error.json, surfaced as RuntimeError so the CLI does not hide a generic
ProtocolError. PID is logged to aid correlation; no automatic retry/fallback.
`--no-frida-spawn` on one-shot search requires --frida, disables both Frida spawn
and Appium activation, and requires IG already running/foreground. This guard is
available for a deliberate native TLS observation after failed emulated attach.
Frida remains in the native realm for search; no implicit emulated fallback.

`shared/java_tls_observer.js` is a separate observe-only REPL script. Frida17's
official REPL supplies Java; the plain Python loader does not. It wraps available
Conscrypt verifier/OkHttp pinner overloads with exact original calls, unchanged
results/exceptions and bounded sanitized metadata (200 events plus limit).
It does not hook class loading, exception constructors, or alter TLS decisions.
It may miss other loaders/late/obfuscated/native verification. REPL duration is
bounded by the operator command; unlike CLI jobs it has no project device lock:
operator exclusivity is mandatory. See docs/frida-diagnostics.md.
Java events now include UTC time and callId/threadId for invocation pairing.
One caller sample per overload has up to12 Java class/method symbols only (200
characters each), no signature/origin/path/raw stack or arguments. Sampling and
thread lookup failures are isolated from the original verifier. No socket/host
correlation is implied; a Java backtrace may omit native callers.
The observed Facebook MobileNetwork CertificateVerifier verify/
verifyWithProofOfPossession overloads are also wrapped, without altering void
returns or original exceptions. First2 invocations per overload emit call/return
pairs; all rejects remain eligible until global200-event cap (even if their call
was unsampled). This keeps repeated successful Conscrypt calls from hiding the
outer verifier's result. Caller sampling stays once per overload.

After explicit operator approval, `instagram/facebook_pinning_trial.js` is a
SEPARATE opt-in native REPL test, not an observer/default/worker feature. Exact
IG416/versionCode382206160/ia32 and method signatures are required. It calls
original Facebook verify(cert[],host,bool) first, and overrides only recognized
typed pin exceptions for two fixed IG hosts when original Conscrypt accepted the
same host/equal leaf in that invocation/thread and no trust call failed. Other
errors/hosts/overloads and outer PoP verification remain original. Thirty-second
internal deadline disables override independently of REPL timeout; logging caps
at100+marker. Unload on REPL exit; no CA/APK/OS/config changes. Fail-closed guards
and limitations are in docs/facebook-pinning-trial.md. No live acceptance yet.

Recorder exports are redacted best-effort and bounded to 2 MiB encoded/decoded JSON;
other bodies are metadata-only. Raw `.mitm` is opt-in and unredacted. Proxy CA/config
is isolated in configurable `mitm_confdir`; no CA is installed on Android.
That describes the CLI: the operator separately approved and manually added the
remote proxy's verified CA on android01. See AI_CONTEXT.md for provenance and hash.
Remote capture is external to the current executor; keep `--no-capture` when UI
automation uses that remote proxy. Local proxy_host is a bind address, not a remote endpoint.
Session directories are created mode 0700 on POSIX. Job success with capture enabled
requires at least one matching non-transport-error response. That does not prove
semantic search extraction; the result explicitly reports it as unverified.

## Infrastructure

Configuration defines adopted android01/android02. New registrations live in
`.state/devices.json`, protected by inventory locks and atomic replacement.
`device configure` changes only connection metadata in that registry, preserving
ownership and immutable runtime identity. YAML-defined devices are edited in local YAML.
Managed container lifecycle verifies stored immutable container ID + ownership
label + name. Adopted resources cannot be destroyed by device lifecycle commands.
Create never reuses an existing container or data directory; no auto-pull, `--rm`,
volume deletion, or implicit provisioning. Magisk image must be supplied/audited.
STF start only starts already-created containers from the configured Compose project.
New Redroid instances are not automatically registered to the STF ADB container.

File locks are local-host only. No multi-host locking guarantee. Device/session
ownership and port locks are separate; child components reuse the device lease.
Proxy startup briefly shares a bootstrap lock to serialize CA directory initialization.
Runtime state, captures, emulator data, certificates, and secrets stay outside Git.
