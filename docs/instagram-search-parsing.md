# Instagram TopSerpQuery parsing

## Evidence and scope

The operator supplied a paired native request and response on 2026-11-18:
`POST https://i.instagram.com/graphql/query`, form operation `TopSerpQuery`,
`variables.query="kopi toraja"`. The request had `is_pagination_request=true` and
an `after` cursor: this is a continuation of keyword-search results, not merely
the home timeline or Explore landing page.

Observed response data lives at
`data.manual_pagination_query.edges[].node.items[]`. Media grid units contain
photo, video/reel and carousel posts. Later `SerpClipsViewerFragment` documents
provide caption, counts and user enrichment using paths such as
`["manual_pagination_query","edges",0,"node","items",1]`.
`TopSerpPagingInfo__force_flush` adds connection-level page information.
The supplied excerpt did not contain an `is_final=true` marker.

No raw account data, contact details, identifiers, session/cursor/tracking values
or signed media URLs from that sample were copied into the repository. Tests use
a newly authored synthetic fixture with the same structural shape.

## What is implemented

- Exact HTTPS API hosts `i.instagram.com` / `i-fallback.instagram.com`, path
  `/graphql/query`, method POST, form operation `TopSerpQuery`, parsed variables.
  A GraphQL URL alone, document ID, or background traffic is not search evidence.
- Request query must equal the expected job keyword when one exists (no substring,
  fuzzy matching or caption-based relevance filtering). Query is form-decoded once.
  Duplicate operation/variables fields and duplicate JSON variable keys are refused.
  Build-specific `client_doc_id` is not pinned or replayed.
- UTF-8 single JSON objects or whitespace-separated JSON objects; at most 2 MiB
  encoded/decoded response, 256 KiB request, 512 documents and 2,000 grid slots.
  MIME multipart/SSE framing is not guessed; unsupported/truncated input is marked
  partial/invalid. The actual remote Content-Type/framing still needs inspection.
- Merge only the observed deferred paths, check media ID against the base slot,
  and deduplicate parent posts by ID. Patches may arrive out of slot order.
  Patch-only records are not counted as additional posts. GraphQL errors, bad
  identities, unsupported units/patches and missing final markers prevent complete
  status. Complete here means this response, never all search results.
- Initial and delayed user/media fields are combined. Carousel children remain
  nested rather than counted as separate search posts. Missing counts stay null;
  zero stays zero. At most 100 carousel children / 10 media versions are exported.
  This is a selected-field export, not a promise of complete media metadata.

`requests.jsonl` contains normalized per-response records (`kind=instagram_search`)
with operation, keyword, pagination boolean, parse status, issues, posts and counts.
Mismatched keywords emit `search_keyword_mismatch` with no posts.

`posts.jsonl` is an atomically replaced session snapshot: one row per
`(keyword, parent post ID)`, enriched by later pages without replacing known fields
with missing/null values. Maximum 10,000 rows / 32 MiB. Only one recorder owns a
session directory; this is not a multi-process shared writer.
`complete_response_observed` means that post appeared in at least one completely
parsed response; it does not attest every field's freshness. Offline HTTP status
may be unknown, so this is not independent proof of HTTP 2xx.

Post fields: ID, shortcode/permalink, type, posting time, caption, available
like/comment/play/view/reshare counts, selected user fields, image/video references,
duration, and carousel children. Session/cursor/tracking values, manifests, viewer
relationship state and arbitrary source fields are excluded.
ALL query strings/fragments are removed from image/video URLs. These are
sanitized references, **not working signed download URLs**. No media is downloaded.
Captions/user fields still contain personal data; use restricted storage/retention.

## Offline use with an exported response

This path needs only the base package: no mitmproxy, Appium, Frida, device or
network connection. Keep inputs under ignored `output/`, not fixtures/Git.

Export the selected flow's **decoded response body** to
`output/import/response.body`. Preserve the entire sequence, including later
patches and its final marker if present. Do not combine different HTTP responses.
Do not export/share cookies or authorization headers.

Create `output/import/request.json` with minimal metadata from that same flow:

```json
{
  "method": "POST",
  "url": "https://i.instagram.com/graphql/query",
  "content_type": "application/x-www-form-urlencoded",
  "body": "fb_api_req_friendly_name=TopSerpQuery&variables=%7B%22query%22%3A%22kopi+toraja%22%2C%22is_pagination_request%22%3Atrue%7D"
}
```

This is reduced operator-supplied metadata, not an automatic flow export or proof
of provenance. Copy the actual keyword/pagination boolean, not session IDs,
cookies, `after`, authorization, or full raw request fields. For other keywords,
encode the form correctly (a literal `+` must be `%2B`).
Optional `status_code` must be the actual observed HTTP code; omitted is null,
never assumed 200. Non-2xx responses cannot be marked complete.

Run from the repository root, using a **new output directory**:

```bash
uv run sniffer parse instagram-search \
  --request output/import/request.json \
  --response output/import/response.body \
  --keyword "kopi toraja" \
  --output output/parsed-search-001
```

The CLI prints only a summary and creates `parse-summary.json`, `requests.jsonl`,
and (when posts exist) `posts.jsonl`. It refuses existing output directories.
Partial/invalid parsing is an inspectable outcome, not a CLI crash: always check
`parse_status`, `stream_complete` and `issues`. No completion/job ACK is created.

## Capture / executor boundary

The project-owned local mitmdump recorder calls the same parser and post writer.
`semantic_search_results_verified=true` requires at least one response with
nonempty normalized posts, exact job keyword, complete parsing and HTTP 2xx.
Additional partial responses are counted separately; this flag does not imply
exhaustive search, repeated-run stability or production queue acceptance.
UI-only jobs stay false.

The existing remote mitmweb is **not** automatically connected to this recorder.
`--no-capture` still disables local recording, not Android's remote proxy.
Offline parsing provides an inspectable file boundary, not remote transport/job
correlation. Do not restart/reconfigure the shared proxy to install this code
without an explicit deployment decision.

Subsequently added: the separately approved
[one-shot ten-scroll collect command](automated-collection.md) reads the existing
mitmweb API over GET instead of installing this addon. It requires explicit web
URL/client IP and opt-in trial/publish flags. The ordinary search command and
input-job worker are not silently switched to remote capture.

TLS scripts, host allowlists, CA, Android/APK, Frida lifetime and worker defaults
are unchanged. No automatic request replay or cursor-driven API crawling is added.
