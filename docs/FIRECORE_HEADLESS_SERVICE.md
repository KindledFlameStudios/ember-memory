# FireCore headless local service seam

This prototype adds `ember_memory.firecore` at the pinned Ember source revision `270510291cc23a69d600f5cf08cbea60d486d7ff`. Ember owns this module and its SQLite lexical/index lifecycle. It imports Ember's pure-Python `BM25` and tokenizer, then uses only the Python standard library for FTS/literal candidate selection, SQLite, JSON, HMAC, and stdio. It does not import the controller, vector backends, embedding providers, hooks, or network listeners.

## Invocation and trust boundary

- Source checkout entry point: `python -X utf8 -m ember_memory.firecore`; package entry point: `ember-firecore`.
- Forge launches one child per search/open operation, communicates with one bounded JSON request/response on stdio, and sets a per-process HMAC key in the child environment. No listener or background process is created.
- The child accepts only authenticated protocol `ember.firecore.local/1`, a trusted owner supplied by Forge, an explicit stable source ID, restore epoch, coverage revision, and a complete bounded canonical snapshot.
- The index path is supplied by the Forge host. Its records are rebuildable projections; the durable local `source_state` sequence and cursor key fence source revisions and issued cursors.

## Lifecycle contract

`FireCoreService.reconcile` transactionally replaces one owner's projection for one stable source. Its owner/source primary keys isolate tenants. Forge supplies `restore_epoch` as an opaque fence: it combines its stable source ID, an independent lifecycle token persisted outside `forge.db`, and canonical generation/source revisions. Forge advances the token on first tool registration per host process and through the trusted `MarkFireCoreSourceReplaced` hook after a canonical DB replacement. That token is stable across tool-constructor calls, Ember one-shot child invocations, and document/FTS rebuilds. `coverage_revision` changes when the complete visible message inventory or message revisions change. The durable service sequence increments whenever epoch or coverage changes. Search cursors carry authenticated principal, source, restore epoch, coverage revision, sequence, query digest, view, and offset. Cursors from a prior source view or a rebuilt/changed source are rejected. Detection assumes the lifecycle sidecar is preserved and the replacement hook is called; restoring both DB and sidecar or replacing DB without the hook is outside this prototype contract.

`search` uses Ember BM25 over a bounded canonical projection for ordinary token queries and an exhaustive casefolded literal path for short/punctuated queries. Source/result order tie-breakers use `(created_at, source_order, message_id)`, where `source_order` is supplied by Forge from canonical `created_at,rowid` traversal and rowid itself is never exposed as a citation. Query completeness is distinct from result-page continuation. `open` requires the previously cited message revision and returns `changed` without replacement text when it no longer matches. Its explicit `canonical-message-parts-binary-payloads-omitted-v1` convention preserves structured part, speaker, branch, and tool-call/result metadata while omitting binary payload bytes and redacting reasoning content. The four-capability destination and production package activation remain outside this prototype.

## Verification

Run `python -X utf8 -m unittest tests.test_firecore -v` from the Ember checkout. Tests use only temporary synthetic SQLite data and no providers or services. The Forge integration candidate is maintained separately in `C:/firecore-s0-s4`; the original in-progress `C:/Projects/ember-memory` checkout remains unmodified by this work.
