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
- Test `frida inspect --realm emulated` metadata-only first: translated ARM libraries
  may be absent from native ia32 enumeration. Command never spawns or hooks TLS.
  Stop if unsupported/crashed; do not force a realm or patch memory.
- Prepared opt-in shared/tls_observer.js (no bypass), to use after realm/module view
  is known. Inspect hook availability/tls.call metadata, no automatic retry on crash.
  Root is available; Magisk is not a prerequisite.
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
Latest full run: **108 passed**, Ruff/diff checks clean, sdist/wheel build successful. Base-only
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
