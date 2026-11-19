# One controlled search, ten scrolls, outgoing Beanstalk results

## Approved scope and deployment boundary

On2026-11-19 the operator requested a bounded automation run and publishing
normalized data to `202.56.161.146:22400`. The approval form supplied result tube
`sniffer_instagram_result`, keyword `prabowo`, and explicit permission for a
targeted TLS trial up to120seconds. Capture/format choice fields were omitted;
implementation uses the stated one-message-per-post recommendation. The operator
later clarified that the full normalized post JSON must be sent directly, with no
extra envelope and no `posts.jsonl` in automatic collect. Remote
collection uses read-only mitmweb GET endpoints instead of modifying its service
or installing an addon. No live queue puts or remote device commands were run
by the coding agent.

This is an explicit **one-shot collect command**, not a silently enabled worker
feature. Existing input-job worker and its queue/ACK behavior are unchanged.
It uses android01's existing proxy/CA, Frida server/forward and logged-in IG.
No proxy listener, CA/APK/Android changes, spawn/app activation, service restarts,
clear-data, server bootstrap, native/emulated fallback or injection retries.
No previous worker/Appium/Frida observer/trial may be active on the device.

## Set existing service addresses

Keep `config/local.yaml`; edit/merge only the required sections (do not duplicate
YAML keys or overwrite the device's existing configuration):

```yaml
devices:
  android01:
    # Preserve its other existing fields.
    frida_endpoint: "127.0.0.1:27052"
remote_mitmweb:
  url: "http://127.0.0.1:19080"  # EXAMPLE: existing SSH tunnel to the WEB UI/API
  client_ip: "192.0.2.10"        # PLACEHOLDER: exact Android client IP seen by proxy
results:
  host: "202.56.161.146"
  port: 22400
  tube: sniffer_instagram_result
```

**The web API port is not the Android HTTP proxy port18919.** Obtain the actual
web URL and proxy-observed `client_conn.peername[0]`. The example does not establish
a tunnel. HTTP is accepted only on loopback; otherwise require HTTPS. Do not
disable TLS validation or expose an unauthenticated mitmweb management API.
The client IP may be the Redroid host's NAT address, not its ADB address. If two
devices share it, keep other searches on that proxy client idle during this run.
Local locks cannot control STF clicks or executors on another machine.

Environment overrides are supported:
`SNIFFER_MITMWEB_URL`, `SNIFFER_MITMWEB_CLIENT_IP`,
`SNIFFER_RESULTS_HOST`, `SNIFFER_RESULTS_PORT`, `SNIFFER_RESULTS_TUBE`.
Secrets must not go in URLs/YAML/history/chat. If a reverse proxy/newer mitmweb
requires auth, provision `SNIFFER_MITMWEB_AUTHORIZATION` securely in the run
environment (`Bearer ...` or the reverse proxy's accepted authorization value).
Do not change authentication or restart mitmweb just for this client.

Beanstalk standard TCP has no built-in auth/encryption. Restrict queue access to
authorized hosts over a protected network/firewall/VPN. Payload captions/account
fields may contain personal data. No raw request headers, cookies, session IDs,
tracking tokens, manifests or signed media URL querystrings are sent.

## Check configuration without touching services

Run from the repository root after pulling the updated code:

```bash
uv run sniffer automation instagram collect \
  --device android01 --keyword "prabowo" \
  --targeted-trial --publish --dry-run
```

Dry-run validates configuration and prints the planned job/destination; it opens
no sockets/device/session and creates no output. It does not prove connectivity.

## Execute the approved bounded run

Keep the already verified Frida server and loopback forwarding running. Open
Instagram manually in the foreground, logged in. Stop all other device jobs/hooks.
Keep the mitmweb flow list unfiltered and do not clear/modify/evict flows during
collection. This code never clears/replays/kills or mutates a remote flow.

```bash
uv run --extra automation --extra frida \
  --with "frida-tools==14.13.2" --with "frida==17.27.0" \
  sniffer automation instagram collect \
  --device android01 --keyword "prabowo" \
  --targeted-trial --publish
```

Only this command's explicit flag enables the approved120s trial. Default direct
REPL script usage remains30s. The packaged script accepts only30,000 or120,000ms;
exact three-host/build/ABI/signature/original-system-trust guards are unchanged.
The official REPL supplies Frida17's Java bridge. Auto-reload is disabled to avoid
resetting the deadline. The wrapper waits for ready, stops before expiry, and
unloads its own child on exit; it does not run a second observer or eternalize.
Attach failure/refusal/crash stops the run without retry.

The command:
- Preflights the outgoing queue using `use` and `stats` only (no test puts).
- Opens one Appium session, verifies foreground, snapshots the remote flow IDs.
- Starts one native targeted REPL, re-arms the remote baseline immediately before
  search, types/submits the keyword, and performs exactly10 UI scroll gestures.
- During checkpoints reads new finished API responses only, matching API host,
  method, proxy-observed client IP, remote time boundary and exact request keyword.
  Old/replayed/other-client/wrong-query traffic is excluded. Differing request
  search-session IDs for this client/query are treated as ambiguous; only an
  in-memory digest is compared, not saved or published.
- After a short response-settle period, cleans up its own REPL/Appium session.
  It persists an outbox, then `capture-result.json`, then publishes posts.

Ten scroll gestures do not guarantee ten network pages or any fixed number of
posts. Search may have cached data/no next page. No matching parsed posts means
failure and **no publish**. Partial parsed responses remain explicitly flagged;
the consumer must inspect `complete_response_observed`. The run summary separates
complete/partial responses and never claims exhaustive results.
HTTP non-2xx, API errors, view eviction, expiry or UI failure abort before publish.
Blocking Appium/network calls return through a health checkpoint; the script's
independent internal deadline still limits the TLS decision change.

## Result envelope and durable recovery

One parent post per keyword per run, normalized from the snapshot, becomes:

```json
{"kind":"instagram_search_post","keyword":"prabowo","job_id":"collect-unique-id","id":"1001_2001","caption":"synthetic caption","complete_response_observed":false}
```

See [parser field projection](instagram-search-parsing.md) for the full `post`
shape. Caption text is not filtered by exact substring: these are Instagram's
ranked results for the request keyword.
The full normalized parser record is sent as-is, with no extra wrapper. Consumer
deduplication can use `(job_id, keyword, id)`; those fields do not give exactly-once.
Media URLs remain sanitized references, not working signed download links.

Output keeps `session.json`, metadata-only `requests.jsonl`, sanitized
`frida.jsonl`, generated bounded `collect-trial.js`, `capture-result.json`,
`result-outbox.json`, receipt summary and success/failure metadata.
Raw API headers/request bodies are never saved by the collector. Automatic collect
keeps enriched posts in bounded memory until the ten-scroll run completes and
persists them in the outbox; it does not create `posts.jsonl`. If the process fails
before the outbox is written, in-memory posts cannot be recovered without a new run.

Outbox is written BEFORE putting any post. Every successful INSERTED ID is saved
atomically before the next put. Each payload is checked against the configured
byte limit and server `max-job-size`; no truncation or silent dropping.
Publish failure keeps pending entries and stops. Resume the **same output**:

```bash
uv run sniffer results publish --output output/THE_EXISTING_COLLECT_SESSION
```

Do not start another automation run just to retry a put. A crash/lost INSERTED
reply before its local receipt can duplicate delivery. Delivery is **at-least-once**;
the downstream consumer should deduplicate on `(job_id, keyword, id)`. Remote acceptance is not
proof its consumer processed/ACKed the post. This publisher never reserves or
deletes any queue message.

Capture without `--publish` still writes the outbox for a later `results publish`.
The older `results prepare` remains available for legacy sessions that already
contain `posts.jsonl`; it cannot recover a new collect run that failed before
its outbox was written. Publish pins the destination saved in the
outbox instead of silently switching servers on retry. Output files are restricted
runtime state, never fixtures/Git. Keep retention limited.

## Compatibility and verification limits

Read-only routes and `flow_to_json` fields were checked against
[mitmweb11.0.2 source](https://github.com/mitmproxy/mitmproxy/blob/v11.0.2/mitmproxy/tools/web/app.py):
`GET /flows` and `GET /flows/{id}/{request|response}/content.data`.
Raw management metadata stays in memory and is size-bounded. Redirects are refused,
default environment HTTP proxies bypassed, HTTPS certificates verified.
Actual web URL/auth/client IP and live remote body framing remain operator checks.
The client does not add support for unknown multipart/SSE framing to the parser.

Local tests exercise a real loopback HTTP API simulator, real synthetic Beanstalk
wire protocol, lifecycle mocks and the actual JavaScript under Node simulation.
They do not prove live Android stability, actual120s orchestration, remote API
permissions/framing or delivery to the user's queue. No remote tests/deployment
were performed by the coding agent.
