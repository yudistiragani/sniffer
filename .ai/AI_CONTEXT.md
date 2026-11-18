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
instrumentation, not a confirmed live fix; next step is rerun and collect those logs.
