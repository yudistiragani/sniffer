# Delivery and follow-up

## Active priority (latest direction)

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
- [ ] Operator: one30s native REPL run of updated observer, manually search after
  ready; share Facebook-class call/return/reject + contemporaneous proxy error.
  No concurrent jobs (REPL has no project lock); stop on crash. No claim of
  host/socket correlation, pinning cause or decrypted capture yet.
- Native HTTPS capture is active priority; Beanstalk acceptance and image/OS
  migrations remain deferred. No APK switch or universal hook by guesswork.

## Initial delivery

- [x] Runnable `uv` package, lockfile, CLI, tests, docs.
- [x] Inventory/doctor, device locks and port checks.
- [x] Managed Redroid create/start/stop/destroy + metadata-only adopt existing.
- [x] Existing STF status/start without recreate.
- [x] Appium, proxy, Frida adapters; independent commands where applicable.
- [x] Instagram keyword-search flow + bounded scroll (one user-reported live UI-only smoke passed).
- [x] mitmproxy recorder + platform parser boundary (`unmapped_json`, not semantic extraction).
- [x] Beanstalk worker with bounded retry and long-job touch.
- [x] TikTok extension point, explicitly unsupported search.
- [x] Opt-in ADB reverse/global proxy setup; no CA/root installation.

## Local verification

`uv sync --locked --all-extras`, `uv run --all-extras pytest -q`,
`uv run --all-extras ruff check .`, `uv build`, and CLI dry-run were exercised.
The suite includes a real mitmdump -> local HTTP endpoint smoke test
and greenstalk -> local synthetic Beanstalk-protocol server. Most device/Docker/UI/
Frida tests are mocks. Wheel packaging includes JavaScript resources.
Latest full run: **127 passed**, Ruff/diff checks clean, sdist/wheel build successful. Base-only
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
- Instagram previously failed TLS and search spun after browser HTTPS worked;
  browser trust does not prove app trust. Retest current working build before
  attributing all symptoms to pinning; no mechanism has been confirmed.
- After readable native traffic, integrate recorder/output on remote mitmweb
  (CLI capture is local only).
- Get real search-response samples; implement semantic extraction with fixtures.
- Confirm producer's actual job contract, tube, TTR, retry policy, expected output.
- Decide specific search-result category if default results are insufficient.

## Deferred

TikTok automation, full STF deployment, automatic Magisk-image building, CA
installation, mass provisioning, distributed locks, external result sink, API.
