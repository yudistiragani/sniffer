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

One worker owns one device lock. Each job creates a separate session directory.
Capture starts before app interaction. Appium uses no-reset/auto-launch-disabled
capabilities; Frida may attach/spawn before automation activates the app. The
configured selectors are initial candidates, not verified against the user's app.
The search-input ID was subsequently observed in a user-provided XML dump (not
proof the whole flow works). Instagram UI actions emit per-step START/END/FAILED
terminal logs, with named lookup timeouts and health checkpoints while polling.

Standalone capture needs no Appium. Standalone automation can disable capture.
mitmproxy addon runs in the mitmdump process; it imports parser/writer from this
installed package. There is no pretend attachment to an arbitrary running proxy.
Frida events are separate from HTTP response records.

Recorder exports are redacted best-effort and bounded to 2 MiB encoded/decoded JSON;
other bodies are metadata-only. Raw `.mitm` is opt-in and unredacted. Proxy CA/config
is isolated in configurable `mitm_confdir`; no CA is installed on Android.
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
