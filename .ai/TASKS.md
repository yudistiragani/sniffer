# Delivery and follow-up

## Initial delivery

- [x] Runnable `uv` package, lockfile, CLI, tests, docs.
- [x] Inventory/doctor, device locks and port checks.
- [x] Managed Redroid create/start/stop/destroy + metadata-only adopt existing.
- [x] Existing STF status/start without recreate.
- [x] Appium, proxy, Frida adapters; independent commands where applicable.
- [x] Instagram keyword-search flow + bounded scroll (requires live selector validation).
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
Latest full run: **83 passed**, Ruff clean. Initial sdist/wheel build was successful. Base-only
installation was also exercised; the optional real-proxy test skips without capture extra.
No real Instagram, remote Docker, STF, Magisk device, Appium server, or production
Beanstalk queue was tested. Passing tests are NOT live acceptance.

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
- Rerun UI-only search after the stale-element fix: user logs identify stale at
  search_tab.click, followed by occupied systemPort 8201. Reacquisition, bounded
  port wait/TIME_WAIT tolerance, and cleanup logging are implemented, not live verified.
  If port remains busy, inspect Appium sessions/ADB forwards; do not kill unknown owners.
- Verify login manually; do not add automated credential entry.
- Set up actual proxy reachability, CA trust, and optional Frida server/scripts.
- Get real search-response samples; implement semantic extraction with fixtures.
- Confirm producer's actual job contract, tube, TTR, retry policy, expected output.
- Decide specific search-result category if default results are insufficient.

## Deferred

TikTok automation, full STF deployment, automatic Magisk-image building, CA
installation, mass provisioning, distributed locks, external result sink, API.
