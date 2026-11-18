# Agent operating rules

- Preserve existing STF/android01/android02, accounts, volumes, and data.
- Inventory/adopt is non-destructive. Never silently recreate/update adopted resources.
- Require explicit confirmation for destroy. Stop first; never delete volumes/data.
- Do not upgrade the existing Android 9 devices to make tooling easier.
- Do not kill/restart the shared STF ADB server.
- Keep ADB bound to loopback; do not publish insecure management ports.
- One active automation/worker per device. Respect device and service locks.
- No automatic CA installation, TLS trust changes, login, or arbitrary job-supplied scripts.
- Instrument only devices/apps the operator is authorized to test.
- Treat Frida server/scripts as unavailable until explicitly verified/provisioned;
  no Magisk dependency. UI-only baseline has passed; native capture is the goal.
  Do not run unrequested injection, stop/delete external Frida services, or change
  installed Instagram versions. Inspect actual device/process/APK ABIs separately.
- Never commit credentials, CA private keys, accounts, raw traffic, runtime state, APKs.
- Redact credential fields in exports; response content still contains potentially
  personal data and requires restricted storage.
- Preserve user edits; do not initialize/publish Git or operate the remote server
  unless separately requested.
- Update `.ai/` documentation when changing implementation/architecture.
- Distinguish mocked/local tests from live integration; never claim capture/search
  is verified without an actual configured device and response samples.
