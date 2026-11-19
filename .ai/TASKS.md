# Delivery and follow-up

## Active priority (latest direction)

- User now requests one automatic keyword search +10 scrolls + outgoing post
  results, destination202.56.161.146:22400 / tube sniffer_instagram_result.
  Approved keyword prabowo and explicit targeted trial up to120s.
- [x] Implement opt-in one-shot collect CLI, read-only remote mitmweb API collector,
  fixed120s official native REPL orchestration (default standalone remains30s),
  foreground-only Appium, no restart/spawn/configured concurrent hooks.
- [x] Implement separate outgoing results config, durable per-post outbox/receipts,
  max-job-size checks, deterministic consumer dedup IDs and publish-only retry.
  Existing input worker unchanged; no live production queue writes.
- [ ] Obtain actual mitmweb WEB API URL and exact proxy-observed Android client IP.
  Auth only privately if needed; require HTTPS or loopback tunnel, not proxy18919.
- [ ] Operator deploy/configure, dry-run then one bounded collect/publish; verify
  real remote framing/parsed post quality,10 gestures and target queue receipts.
  Consumer processing/ACK, repeated-run stability remain separate acceptance.

### Prior capture/parser milestones

- User explicitly wants Instagram requests readable in remote mitmproxy NEXT,
  before Beanstalk testing. Do not mistake an Appium baseline for finished sniffing.
- [x] User explicitly prepared Frida17.27.0 x86_64 server/loopback27052 forwarding;
  minimal attach confirmed ia32/pointerSize4 + Houdini, stayed attached5s.
  Do not assume TLS hook stability or full capture from this probe.
- [x] User metadata: IG416.0.0.47.66/versionCode382206160, ARMv7 APK on Android
  x86_64/Houdini; minSdk26/targetSdk36. Translation may affect instrumentation.
- [x] User reports no-proxy/no-Frida keyword UI baseline runs. Capture counter0
  and semantic flagfalse are expected; actual data extraction remains unverified.
- Re-enable remote proxy for controlled testing with the verified system CA and
  current functional IG build. Run with --no-capture --no-frida (no LOCAL recorder),
  and inspect REMOTE HTTPS flows. Stop repeating UI/queue tests if native TLS fails.
- Tune scroll geometry/speed after this baseline if requested; do not change it
  blindly without target dimensions/result layout.
- [x] Controlled proxy-on retest still fails native Instagram TLS; search spins.
- First emulated inspect failed at attach with generic ProtocolError before script
  load. Server/IG were running in later snapshot; Binder pid17 crash excerpt is
  not enough to correlate a new IG crash. Original exception was hidden by CLI.
- [x] One controlled retry produced ProtocolError "the connection is closed" at
  emulated attach before script load. Stop emulated retries; cause remains unproven.
- Prepared opt-in shared/tls_observer.js (no bypass), to use after realm/module view
  is known. Inspect hook availability/tls.call metadata, no automatic retry on crash.
  Root is available; Magisk is not a prerequisite.
- Next one native TLS observer/search run using --no-frida-spawn; IG must already
  be running/foreground. Never auto-restart a missing app in this diagnostic mode.
  Read frida.jsonl; zero calls may mean the native view misses translated ARM TLS.
- [x] User native observer: hooks installed on machine3 system libssl/libcrypto;
  no tls.call in provided snapshot. Do not treat hook_ready as observed invocation.
- [x] Native Java bridge availability probe via pinned ephemeral frida-tools REPL
  (14.13.2 + Frida17.27.0), no trust hooks or bypass. Plain Frida17 scripts lack
  Java bridge by default; observer's flagfalse does not mean IG lacks Java.
- [x] User probe returned arch ia32, bridgeLoaded true, javaAvailable true.
- [x] Prepared observe-only shared/java_tls_observer.js and Node Java-bridge
  simulations; preserves exact original calls/results/exceptions, no bypass.
- [x] Operator Java run: installed7 all system Conscrypt, provided calls returned
  normally/no rejects; both known OkHttp classes + org.conscrypt unavailable in
  selected loader. Search still loading; proxy i.instagram.com handshake disconnect
  at10:08:40.988. Successful Java calls not tied to failing connection.
- [x] Added bounded once-per-overload Java caller symbols, UTC time/callId/threadId;
  no raw stack/path/arguments or TLS decision changes.
- [x] User caller trace identified Facebook MobileNetwork CertificateVerifier
  verifyWithProofOfPossession -> verify -> Conscrypt, called from Tigon event loop.
  Conscrypt returned normally;200-event cap reached at call93.
- [x] User signature probe:3 verify overloads +1 verifyWithProofOfPossession, all void.
- [x] Added observe-only Facebook method hooks; call/return first2 invocations per
  overload, all rejects eligible until global cap. No bypass or discarded errors.
- [x] Operator run installed11 hooks: Conscrypt returns normally inside Facebook
  verify call2; verify rejects reported_pinning10:26:55.573Z and outer
  verifyWithProofOfPossession propagates rejection10:26:55.575Z, same thread32571.
  Pattern repeats. Strong evidence of app-level pin-related rejection after
  system trust success, not proof of independent PoP failure/host correlation.
- [x] Operator explicitly approved preparing a separate opt-in targeted test.
- [x] Prepared instagram/facebook_pinning_trial.js: original verifier runs first;
  exact build/ABI/signature/host guards, same-invocation/thread original system
  trust acceptance for same leaf, typed recognized pin exception only,30s expiry.
  Observer unchanged, no implicit worker activation or CA/APK/OS changes.
- [x] User trial: ready10:39:22Z, two override events10:39:29Z with original system
  trust observed; user reports search works. Other-host rejections remain preserved.
- [x] User supplied readable native timeline response in remote mitmweb:
  i.instagram.com/api/v1/feed/timeline/, body status="ok", populated feed_items.
  HTTPS decryption confirmed for this endpoint; HTTP status code not supplied.
  This is home feed, not keyword-search extraction or remote-recorder integration.
- [x] User supplied TLS failure for instagram.fcgk16-1.fna.fbcdn.net and approved
  adding exactly this host (no wildcard). Trial now3 approved hosts; guards unchanged.
- [x] Requested public-source research: Beeper describes same verifier/Tigon path;
  reviewed KnifeLemon/Aniketh01/depreciating source. Broader trust-all/startup hooks
  not adopted; not verified compatible with IG416/Android9/Houdini. Sources in
  docs/instagram-public-scripts.md. No third-party code copied or executed.
- [x] Operator paired search sample: POST /graphql/query, TopSerpQuery,
  variables.query="kopi toraja", pagination=true. MEDIA_GRID posts + deferred
  caption/count/user fragments confirm keyword-search capture for that run.
  Supplied flags all is_final=false; completion/HTTP code/framing not established.
- [x] Implement bounded JSON-sequence decoder, exact request/keyword matching,
  deferred path+ID merge, parent deduplication, normalized posts.jsonl snapshot.
  Privacy allowlist/no signed URL queries; synthetic fixtures only. Trial unchanged.
- [x] Offline base-package parse instagram-search command, no network/device/
  proxy dependency; new-output-only, explicit complete/partial/invalid summary.
- [ ] Operator export decoded body + minimal paired metadata; validate offline
  summary/posts and inspect actual Content-Type/framing/final marker. No raw
  cookie/session/cursor/tracking/contact values in fixtures or shared logs.
- [x] Prepared read-only remote mitmweb collector with baseline/IP/query/time
  correlation; live URL/auth/client-IP/framing acceptance remains pending above.
- Search HTTPS milestone is met; live parser output and remote integration are
  next. Other CDN scope remains unapproved; no repeated setup or blanket hooks.
  Beanstalk result publishing is now requested above; image/OS migrations remain deferred.

## Initial delivery

- [x] Runnable `uv` package, lockfile, CLI, tests, docs.
- [x] Inventory/doctor, device locks and port checks.
- [x] Managed Redroid create/start/stop/destroy + metadata-only adopt existing.
- [x] Existing STF status/start without recreate.
- [x] Appium, proxy, Frida adapters; independent commands where applicable.
- [x] Instagram keyword-search flow + bounded scroll (one user-reported live UI-only smoke passed).
- [x] mitmproxy recorder + platform parser boundary; observed IG TopSerp parser
  added later, unknown endpoints remain unmapped_json.
- [x] Beanstalk worker with bounded retry and long-job touch.
- [x] TikTok extension point, explicitly unsupported search.
- [x] Opt-in ADB reverse/global proxy setup; no CA/root installation.

## Local verification

`uv sync --locked --all-extras`, `uv run --all-extras pytest -q`,
`uv run --all-extras ruff check .`, `uv build`, and CLI dry-run were exercised.
The suite includes a real mitmdump -> local HTTP endpoint smoke test
and greenstalk -> local synthetic Beanstalk-protocol server. Most device/Docker/UI/
Frida tests are mocks. Wheel packaging includes JavaScript resources.
Latest full run: **283 passed**, Ruff/diff checks clean, sdist/wheel build successful.
New tests include real loopback mitmweb API simulation, actual outgoing synthetic
Beanstalk protocol (use/stats/put only), outbox recovery and120s JS guard scenarios.
Offline imports load no mitmproxy/Appium/Frida; new parser modules verified in wheel. Base-only
installation was also exercised; the optional real-proxy test skips without capture extra.
Observer JS is exercised under a Node-based simulated GumJS harness (Node optional
for development, not a runtime requirement). This is not live native-hook validation.
The agent has not operated real Instagram, remote Docker, STF, Magisk, Appium, or
production Beanstalk. User separately reported one successful live UI-only search
on android01 after the stale fix. Local tests do not prove live capture acceptance.

## Required before live acceptance

- Inspect server Docker mounts/labels/architecture and ADB access. Never infer
  mounts or Magisk/root from `docker ps`.
- Verify how new Redroid instances connect to STF's ADB/provider network; creation
  does not automatically enroll a device into STF.
- Audit/select/build a Magisk image; test a NEW device first. Official Redroid docs:
  https://github.com/remote-android/redroid-doc . Third-party build tooling:
  https://github.com/ayasa520/redroid-script . Do not assume a Magisk tag exists
  on Docker Hub or trust arbitrary prebuilt images. Pin image digest after testing.
- Check Android 9 compatibility of Appium/UiAutomator2 and native bridge/app ABI.
- Inspect Instagram version, language, UI locators, active search-result tab.
- [x] First UI-only rerun after stale fix: user reports search + one scroll succeeds,
  job manual-aac0b06464784944a7fb7b1ad7e3755f. Zero captured responses expected
  with --no-capture; semantic flag false is not a UI failure.
- Confirm repeated-run stability. If port becomes busy again, inspect Appium
  sessions/ADB forwards; do not kill unknown owners.
- Verify login manually; do not add automated credential entry.
- [x] User verified remote HTTP reachability and server-side HTTPS to i.instagram.com.
- [x] Operator added verified remote CA to android01 System store as c8750f0d.1,
  preserving .0, with explicit consent. No automated install command was added.
- [x] Browser HTTPS works after CA addition, according to user.
- [x] After targeted trial, user supplied readable native timeline JSON in remote
  mitmweb. This supersedes the earlier native-TLS blocker for that endpoint only.
- After readable native traffic, integrate recorder/output on remote mitmweb
  (CLI capture is local only).
- [x] Real search-response structure supplied; implement parser with synthetic
  structural fixtures, not copied account data. Live output acceptance pending.
- Confirm producer's actual job contract, tube, TTR, retry policy, expected output.
- Decide specific search-result category if default results are insufficient.

## Deferred

TikTok automation, full STF deployment, automatic Magisk-image building, CA
installation, mass provisioning, distributed locks, external result sink, API.
