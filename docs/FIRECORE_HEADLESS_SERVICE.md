# FireCore headless local service seam

Ember owns the lexical service and disposable SQLite projection. The service
module imports only its lexical scorer and Python's standard library; the
headless wheel deliberately carries a minimal `ember_memory` namespace
and does not install controller, vector, embedding, provider, hook, or GUI
dependencies.

## Archive Door operations

The Forge bridge exposes the master four navigation capabilities:

- `memory_sessions`: find authorized sessions by title/lineage metadata and update
  window.
- `memory_search`: unquoted queries match all lexical terms; double-quoted
  queries use FTS phrase-token matching. Short or punctuated queries use the
  literal fallback. Results are grouped by session, with an exact source
  reference and an exact matched excerpt, plus a default preview of the
  immediately preceding canonical message (speaker and at most 100 characters).
  Role, session, and date filters are
  cursor-bound; the active session is excluded by default, and tool exchanges
  and summary messages are opt-in.
- `memory_open`: open the exact cited message and optionally bounded canonical
  neighbors before/after it. Context is byte-bounded; if truncated, its
  `context_continuation` points to an authorized `memory_session` page beginning
  at the first omitted source message.
- `memory_session`: page an authorized session in canonical order with an
  authenticated continuation cursor. Repeat `start_message_id` from an open
  continuation along with the returned cursor to continue that anchored page.

Search reports source freshness and query completeness independently. Ordinary
token search uses SQLite FTS5/BM25; short or punctuated queries use a literal
SQLite scan. Cursors bind principal, source, epoch, coverage, query/session,
sequence, view, and position. The current implementation supports at most
50,000 visible messages, 32 MiB per Forge-to-Ember request, 2 MiB per response,
512 characters per query, and 50 messages per session page. Anchored context and each session page are
limited to 1 MiB of serialized messages. These are prototype bounds, not a
claim of million-record readiness.

## Invocation and artifact identity

For source development, Forge launches
`python -X utf8 -m ember_memory.firecore`. For a checkout-independent
headless install, build a wheel from this repository:

`python scripts/build_firecore_package.py --output <artifact-directory>`

The builder uses only the standard library and emits a pure-Python wheel with no
runtime dependencies. Install it into a dedicated environment:

`python -m venv <install-root>/venv`
`<install-root>/venv/Scripts/python.exe -m pip install --no-deps <wheel>`

Configure the opt-in Forge process with `FIRECORE_PYTHON` pointing to that
environment's interpreter and `FIRECORE_EMBER_ROOT` pointing to its
`Lib/site-packages` directory (use the platform's equivalent path off
Windows). Forge verifies SHA-256 over the two package initializers, service,
and scorer before each invocation; the fingerprint is identical for the source
checkout and built artifact. The child receives a
per-invocation HMAC token over stdio and an allowlisted environment. No network
listener, daemon, provider, or GUI is involved.

## Lifecycle and source authority

Forge's canonical SQLite history remains authoritative. The current Go boundary reads a transaction-bound complete session/revision manifest on every operation and revalidates source and runtime principal before disclosure. An in-process manifest cache identifies changed sessions; only their bounded canonical message pages are transported to Ember. Cold starts, lifecycle epoch changes, or invalidated sync state reconcile the full bounded source. It assigns source-local order by Forge's canonical `created_at,rowid` traversal; rowid is never exposed as a universal citation.
The source lifecycle sidecar is independent of `forge.db` and advances on
first registration per Forge process or via `MarkFireCoreSourceReplaced`
after a supported same-process database replacement.

`FireCoreService.reconcile_incremental` atomically replaces documents and FTS rows for every changed session, removes sessions absent from the complete manifest, and records the new manifest. It fails closed if the index is missing a required changed-session delta or a supplied record does not match the manifest revision. Interrupted transactions leave the prior committed projection intact. The session-granularity revision ledger means one changed session is fully paged and replaced; a single very large session can still cause a large refresh. The complete manifest remains O(number of authorized sessions) to read, hash, compare, and transport each operation. Deletions are reflected after a changed canonical revision, so removed content is not returned as current. Index rebuilding cannot detect restoring both the canonical database and lifecycle sidecar, nor an unannounced same-process swap that bypasses the replacement hook. Supported restore recovery must preserve the independent sidecar or call the hook.

Search and page results carry explicit source/query status. Open binds to the
cited message revision and returns `changed` without replacement wording
when evidence has changed. The
`canonical-message-parts-binary-payloads-omitted-v1` convention preserves
structured text/tool activity, omits binary payload bytes, and redacts
reasoning. This remains a default-off synthetic prototype, not production
activation or a real-history pilot.

## Verification

Run `python -X utf8 -m unittest tests.test_firecore tests.test_firecore_incremental` or the focused pytest command in the Forge candidate report for disposable synthetic service checks. `scripts/benchmark_firecore_synthetic.py --records 20000` measures Ember service-only behavior; it is not the end-to-end Forge boundary result. The end-to-end 2,000-message Forge measurement, artifact SHA, exact install commands, and focused build/test evidence are recorded in `docs/reports/2026-10-16-archive-door-candidate.md` in the Forge candidate. No user history, profile, provider, or running service was accessed. The separate `C:/firecore-s0-s4` worktree and the user's original `C:/Projects/ember-memory` checkout were not edited.
