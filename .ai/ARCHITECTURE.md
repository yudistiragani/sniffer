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

Latest user direction: input keyword jobs drive UI; existing external proxy
independently captures and publishes. See `docs/keyword-worker.md`. New explicit
`worker-keywords --targeted-trial` is separate from the legacy worker and collect.
Temporary strict input `{keyword:string}`; no producer-supplied scripts/options.
Queue-server instance ID + tube + numeric job ID form a stable local marker key.
Worker holds device lease/queue heartbeat; on a reserved job it checks the
explicit Frida endpoint and, only if unreachable and no `frida-server` PID exists,
starts the explicitly configured Android executable on loopback. A worker-owned
server stays available across jobs; graceful shutdown SIGTERMs only its recorded
PID after command-line identity verification. Existing server processes and ADB
forwards are never changed. Pass the launch shell script as one ADB shell command
argument to preserve `--listen` on older platform-tools; Frida may expose only
the executable path in `/proc/PID/cmdline`, which is accepted only for the recorded
PID and exact configured executable during owned cleanup. Each job opens an Appium session,
if needed resolves the package launcher and sends ONE explicit am start (no -S),
then waits up to20s for foreground + one main PID, then attaches the approved
native REPL trial (300s for keyword worker; standalone collect remains120s),
starts each job by tapping Home regardless of the prior foreground tab, searches,
and taps the first clickable result. It swipes the observed/configured post viewer
with a5–8s initial dwell and randomized5–7s between up to119 follow-up gestures
(120 requested visits counting the first result); near the trial deadline it
stops cleanly with the actual attempted count. Unique post transitions are not
verified. Each normal press-drag-release runs from80% to12% of viewer height at
1000 px/s and waits1s for transition settling before the human dwell. It compares
a transient hash of accessible active-item metadata; if unchanged for10s, it
makes at most one recovery drag (700 px/s,80%-to-5% path), counted toward the
119-gesture cap. If identity remains
unchanged or unavailable, it stops rather than swiping blindly. This does not
verify unique posts or decoded media pixels. It then settles3s and unloads
trial/cleans Appium, checkpoints lease, persists completion, then ACKs. While idle
there is no attached trial. Runtime error releases/buries then stops the worker;
lease loss never ACKs. No local recorder/mitmweb access/outgoing results. ACK is UI
only, not proxy capture/publish verification; no exactly-once across crashes/restarts.
No force-stop, clear/reset, automatic login or Frida spawn. Startup traffic can
precede trial readiness; no guarantee early requests are captured. Failure metadata
records static phase and error type, never raw messages.

Validated baseline: Appium only with proxy off, `--no-capture`, Frida disabled.
User supplied readable native timeline JSON, then a paired TopSerpQuery
request/response with the controlled keyword in remote mitmproxy after the
separately approved trial. Keyword-search capture is evidenced for that run;
parser live-output acceptance and remote recorder integration remain unverified.
Frida bootstrap/version and native minimal-attach were operator-verified;
no generic bypass or long-running stability is implied.
Optional integrations are never activated, or external services stopped, implicitly.

One worker owns one device lock. Each job creates a separate session directory.
Capture starts before app interaction. Appium uses no-reset/auto-launch-disabled
capabilities; Frida may attach/spawn before automation activates the app. The
configured selectors are initial candidates, not verified against the user's app.
The search-input ID was subsequently observed in a user-provided XML dump. After
stale handling was added, the user reported one successful one-scroll UI-only
search on android01. Later operator keyword response evidence is recorded above;
the local parser uses its structural shape, not the raw personal data.
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
typed pin exceptions for three fixed IG/CDN hosts when original Conscrypt accepted the
same host/equal leaf in that invocation/thread and no trust call failed. Other
errors/hosts/overloads and outer PoP verification remain original. Thirty-second
internal deadline disables override independently of REPL timeout; logging caps
at100+marker. Unload on REPL exit; no CA/APK/OS/config changes. Fail-closed guards
and limitations are in docs/facebook-pinning-trial.md. User subsequently supplied
readable /api/v1/feed/timeline/ JSON in remote mitmweb: endpoint-scoped live
decryption evidence, not semantic search/worker acceptance or universal coverage.
The exact CDN host instagram.fcgk16-1.fna.fbcdn.net was separately approved after
its proxy handshake failure; no wildcard/other CDN host is included. Public
research docs/instagram-public-scripts.md corroborates the Java verifier path,
not build compatibility; third-party scripts are not dependencies or auto-loaded.

Recorder exports are redacted best-effort and bounded to 2 MiB encoded/decoded JSON;
other bodies are metadata-only. Raw `.mitm` is opt-in and unredacted. Proxy CA/config
is isolated in configurable `mitm_confdir`; no CA is installed on Android.
That describes the CLI: the operator separately approved and manually added the
remote proxy's verified CA on android01. See AI_CONTEXT.md for provenance and hash.
The original search executor's capture is local; keep `--no-capture` when that UI
command uses the remote proxy. The separately approved collect command below
reads the remote mitmweb API instead. Local proxy_host is a bind address, not a remote endpoint.
Session directories are created mode 0700 on POSIX. Job success with capture enabled
requires at least one matching non-transport-error response. That alone does not
prove semantic search extraction. The semantic flag requires at least one
complete, nonempty2xx TopSerpQuery response matching the exact job keyword;
partial search responses are counted separately. It does not promise exhaustive
results or production worker acceptance, and the ACK policy is unchanged.

## Observed Instagram search parser

Shared capture/decoding.py decodes bounded UTF-8 JSON-object sequences (512 docs,
2MiB); it does not guess multipart/SSE framing. Instagram parser identifies
exact HTTPS API host, POST /graphql/query, form TopSerpQuery and query variables
(256KiB request). Other endpoints stay unmapped_json, never recursively mined.
Base manual_pagination_query MEDIA_GRID items map to indexed slots (max2000).
Only observed page-info and SerpClipsViewerFragment deferred paths are merged;
post patch IDs must equal base slot IDs. Parent IDs deduplicate results, carousel
children stay nested. Unsupported data/errors/truncation/limits/missing explicit
final marker keep sequences partial/invalid; a standalone plain JSON object can
be complete without an explicit marker. Actual remote MIME framing is pending.

The selected-field projection excludes arbitrary raw request/response metadata,
tracking, manifests and cursor values; it retains only has_next_page/has_end_cursor.
All media URL querystrings/fragments are dropped: references, not signed download
URLs. Captions/selected account fields remain personal data, not anonymous.
SearchPostWriter maintains one bounded per-session snapshot keyed(keyword,parent
ID), enriches repeated pages, and atomically replaces posts.jsonl (10k rows/32MiB).
No multi-process writer sharing or cross-job/global deduplication is implied.
Requests.jsonl retains normalized per-flow records/status, not raw search bodies.

capture/offline.py exposes the same parser through parse instagram-search with
operator-exported response body + minimal paired request metadata and an expected
keyword. It refuses an existing output directory and invents no HTTP status.
This is base-package, file-only parsing, NOT remote mitmweb integration or job ACK.
No TLS/CA/Frida/Android/APK changes or automatic API replay/pagination are involved.

## Explicit ten-scroll collection and outgoing results

collect.py is a separate one-shot orchestration path, not a default worker hook.
Operator approved120s targeted native trial for this path,3 exact hosts with all
existing trust/build guards. JS still defaults30s and accepts only30s/120s.
TrialREPL uses pinned official REPL for Java17 bridge, one current PID/native realm,
no auto-reload/spawn/retry/eternalize. Monotonic health deadline and script deadline
bound the override; cleanup stops only its child. Foreground IG is required before
and during UI actions. No activate_app/service/proxy/CA changes.

RemoteCapture uses read-only GET /flows and GET /flows/{id}/request|response/
content.data, compatible with inspected mitmweb11.0.2 source. Snapshots old IDs
before controlled search; exact client IP + request keyword + API host/path/port/
method + remote Date/time boundary + finished HTTP response/no replay. Different
session-ID digests signal ambiguous concurrent searches. Detects baseline eviction.
No raw credentials/headers/session values persisted. GET body/list sizes bounded;
HTTPS verified or HTTP loopback tunnel only, no redirects. Web URL/client IP must
be explicitly configured. This is not installing an addon or a new API service.

Device and remote-origin/client locks are local-host only. Operator exclusivity
is required on shared NAT/STF/other hosts. Ten gestures are not ten pages/guaranteed
post count; no posts/failure prevents publishing. Successful UI/capture cleanup
precedes outgoing sends. Parser completion stays distinct from HTTP completion.

ResultsQueue settings/env are separate from input Beanstalk. The collect recorder
accumulates normalized posts in bounded memory and logs metadata only; it does
not create posts.jsonl. results.py writes a bounded durable outbox of full
normalized per-post JSON records (no envelope) before any put, checks
configured/server max-job-size before pending puts and atomically saves each
INSERTED receipt. Consumer may dedup using (job_id,keyword,id) after lost reply/crash
(at-least-once, not exactly-once). Results prepare/publish operate saved capture
only; no automation rerun, reserve/delete or input worker ACK changes. In-memory
posts are not recoverable if the run fails before writing the outbox.
No live remote acceptance is implied by local HTTP/protocol/JS simulations.

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
