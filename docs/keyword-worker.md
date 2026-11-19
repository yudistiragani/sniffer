# Keyword worker: external proxy captures and publishes

## Responsibility

The producer engine puts a job in the configured **input** tube. The worker
reserves it, opens one bounded targeted Frida trial, uses Appium to search, opens
the first clickable result, then swipes through at most120 total content visits
(first result counts as visit1; at most119 follow-up swipes). It then unloads its
trial and closes its Appium session before acknowledging. The external proxy already configured on Android
is responsible for capturing and publishing data. This worker does **not**
start a local proxy, access mitmweb API, parse or push results, create
`posts.jsonl`, or modify Android proxy/CA. If Instagram is not foreground, it
opens it once through its Android launcher intent without clearing data.

An ACK means **UI steps and owned cleanup completed**. It is not evidence that
HTTP was captured, that the proxy published anything, that the job returned a
fixed number of posts, or that another consumer processed the result.

## Temporary input contract

Each Beanstalk job body is a JSON object with exactly one string field:

```json
{"keyword":"prabowo"}
```

Keyword must contain 1–200 characters after trimming. Empty/non-string keywords,
invalid JSON and extra fields (including job-supplied script paths, device IDs
or scroll count) are invalid and buried. After Enter, the worker taps the first
visible clickable result and performs at most119 upward swipes, with the existing
first-result dwell of5–8s and randomized5–7s between follow-up swipes, for a
ceiling of120 requested content visits including the first post. It targets the
observed Reels `clips_viewer_view_pager` (or configured `post_feed_viewer`) rather
than swiping the whole screen. Before each gesture, it reacquires the viewer and
reads fresh Appium bounds because Instagram may replace the pager after a
transition. It uses a press-drag-release from80% down the viewer (near, but above,
the metadata row) to12% down at `1000 px/s`; coordinates come from those bounds.
Each drag is followed by a1s transition-settle wait and the
randomized human dwell. It compares an ephemeral hash of accessible post
metadata (never logged or persisted) to detect whether the visible item changed.
If it remains unchanged for up to10s, it sends at most one recovery drag at
`700 px/s`, from80% to5% of viewer height; that gesture counts against the
119-gesture cap. If
identity remains unchanged or cannot be checked, the worker stops rather than
swiping blindly. These metadata comparisons do not prove unique posts or that
the image/video pixels finished loading. Appium success only confirms the
gesture command ran; it does not prove that Instagram changed posts. The
existing300s trial is a hard job bound; if
time is nearly exhausted, the worker stops cleanly with fewer visits. The UI does
not expose a verified unique-post counter here: swipes/visits are attempts, not
proof that120 distinct posts loaded. The producer contract and tube name remain
to be confirmed; do not use the proxy's result tube as an input tube.

Queue host/port and `instagram_tube` come from `beanstalk` in local YAML.
`SNIFFER_BEANSTALK_HOST` / `SNIFFER_BEANSTALK_PORT` can override host/port.
The existing `results` / `remote_mitmweb` sections are not used by this worker.
The configured input queue address is independent of the result queue address.
Do not guess that `202.56.161.146:22400` and the result tube are input details.
Beanstalk plain TCP has no built-in encryption/authentication: use a protected
network and authorized queue access.

## Running

After deploying this code and configuring the real input queue, set android01's
existing `frida_endpoint` (known forward `127.0.0.1:27052`) in local YAML.
To permit startup when the server process is absent, also configure
`frida_server_path` to the exact previously verified executable path on Android,
for example `/data/local/tmp/sniffer-frida.1ortVs/frida-server` only if that
exact file still exists and is executable on the target.
IG must already be logged in. If it is closed/backgrounded, the worker resolves
the installed Instagram launcher activity, checks the component belongs to the
Instagram package, then sends one `am start` without `-S`. It waits up to20s for foreground plus exactly
one main PID. For every keyword job, it then taps the Home tab before opening
Search, so the flow does not depend on whether IG was left on Profile or another
tab. It uses configured `home_tab` selectors or built-in Home/Beranda accessibility
labels and the Instagram feed-tab ID; if no Home tab is found, the job fails
rather than searching from an unknown screen. If already foreground, it sends
no launch command. If a prior job left IG inside Reels, the worker detects the
visible `post_feed_viewer`, taps its configured `post_viewer_back` (default
accessibility label `Back`), and waits up to5s for the viewer to close. If still
open or the button is unavailable, it sends Android Back once and verifies again;
if Reels remains open, the job stops rather than searching from the wrong page.
It never respawns or force-stops Instagram. Appium, Android proxy configuration
and CA remain operator-managed. The worker never changes the
ADB forward. On a job it first checks the Frida endpoint; if reachable, it uses
that server and never stops it. If unreachable, an existing `frida-server` process
blocks any replacement. Only when no process exists does it start the configured
binary on Android loopback at the endpoint port. That server stays available
across jobs, then the worker sends SIGTERM only to its recorded PID on graceful
shutdown, after verifying that PID's command line still names the configured
binary. A crash can leave a worker-started server behind; the next run treats it
as existing and does not assume ownership. Do not run another worker, Appium job,
Frida observer/trial or manual STF interaction on the device.
The launch script is passed as one `adb shell` command argument so older
platform-tools cannot split the Frida `--listen` option from the server command.

For an operator-supervised first job use:

```bash
uv run --extra automation --extra frida \
  --with "frida-tools==14.13.2" \
  --with "frida==17.27.0" \
  sniffer worker-keywords --device android01 --targeted-trial --once
```

`--once` processes at most one reservation, or exits after one reserve timeout.
Without `--once` the worker stays up, watches the configured input tube and
processes jobs serially. **No Frida trial is attached while waiting.**
`--targeted-trial` is required; the legacy `sniffer worker instagram` is
unchanged and does not silently activate this TLS change.

Per job, the order is: confirm/start Frida server, open Instagram if necessary,
verify foreground and one main PID, then attach the official pinned Frida REPL.
The trial attaches only to one
already-running main PID in native realm, disables auto-reload, and waits for
`fb_trial.ready`. The existing exact IG build/ABI, host, original system trust
and typed-pinning-exception guards remain. The keyword worker uses an approved
300-second trial deadline to allow the longer feed run; standalone collect stays
at120 seconds. The internal guard remains aligned with the REPL timeout;
the wrapper checks a conservative deadline during automation. It unloads on
success/failure and never stops a pre-existing Frida server. Server lifecycle
tests are local simulations, not live device verification.
No proxy or result queue status is verified by the worker.
The earlier `monkey` launch failed on the user's emulator with a physical-key
message; `cmd package resolve-activity` identified the launcher but `am start`
has not yet been tested live. Resolution/launch failures stop without another
attempt. The launcher does not clear app data, force-stop, kill, change credentials or
automate login; Appium session capabilities still use noReset=true/fullReset=false.
Trial attachment happens only after foreground and PID readiness. Startup network
requests can precede the hook, so initial app traffic may fail until trial ready.
If the login screen appears, stop and log in manually; successful login is not
assumed or automated. Real device behavior still requires operator verification.

## Delivery and failure semantics

- Input worker holds the device lock locally and touches the reserved job via
  its reserving connection. Producer should use TTR **120 seconds or longer**.
- After successful UI, trial/Appium cleanup and a bounded 3-second response wait,
  a local completion marker is written before deleting the queue job.
- The marker ID is derived from the Beanstalk server's `stats.id` (instance),
  input tube and Beanstalk job ID, not just the keyword. A redelivery on the
  same server instance can ACK the marker without repeating UI. A queue restart
  changes its instance ID, so this is **not exactly-once across restarts**.
- Invalid payload or insufficient TTR is buried. Runtime failures (including
  trial refusal/expiry, app crash or Appium cleanup failure) cause release with
  configured delay, or bury after configured maximum reserves, then **stop the
  worker** for operator inspection. There is no unattended attach retry after
  such failures. Restart only after diagnosing the error.
- Lost reservation means no ACK/release from that connection. Ctrl+C/SIGTERM
  releases the reservation if possible and cleans owned trial/Appium resources.
- One failed delete/reply can cause redelivery; completion markers help only
  while local state and queue-instance identity are preserved. A crash before
  the marker can repeat a search; external proxy output may therefore duplicate.

Per-job `session.json`, sanitized `frida.jsonl`, `result.json` or `failure.json`
are stored under the restricted output directory. Keyword is in session metadata;
do not commit output. Raw HTTP and post payloads are not saved by this worker.
Failure metadata includes a non-sensitive phase (`foreground_and_pid`,
`frida_attach`, `search_and_scroll`, etc.) and exception type, not raw errors.
